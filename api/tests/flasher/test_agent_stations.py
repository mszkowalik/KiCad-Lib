"""The bench agent serves several stations at once, and stops a job on request.

Work list rows 49 and 51 (decision 0099). Before this the agent had one
console and one esptool job for the whole machine: a second station's console
closed the first one's (runs 8964 and 8966), a second job was refused with
"the agent is already programming a device", and Abort left esptool erasing
or writing, because a thread cannot be stopped from outside.

No serial port is opened here. esptool is replaced by a small Python process
that prints what esptool prints, and the console by a stand-in. Run from
`api/`:
    python -m pytest tests/flasher/test_agent_stations.py -q
"""
import base64
import hashlib
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest

from app.services.bench_agent import agent as A

# A stand-in for `python -m esptool`: names its port in every line, takes as
# long as asked, and ends the way esptool ends.
FAKE = r"""
import sys, time
port, seconds, outcome = sys.argv[1], float(sys.argv[2]), sys.argv[3]
print(f"esptool.py v4.8.1 on {port}", flush=True)
print(f"Serial port {port}", flush=True)
time.sleep(seconds)
if outcome == "ok":
    print("Chip is ESP32-C6 (QFN40) (revision v0.2)")
    print("BASE MAC: 98:a3:16:be:da:" + port[-2:])
    print(f"done on {port}")
    sys.exit(0)
print("")
print("A fatal error occurred: Failed to connect to ESP32-C6: No serial data received.")
sys.exit(2)
"""


def _fake_esptool(monkeypatch, seconds: float = 0.0, outcome: str = "ok"):
    def command(argv):
        port = argv[argv.index("--port") + 1]
        return [sys.executable, "-c", FAKE, port, str(seconds), outcome]
    monkeypatch.setattr(A, "esptool_command", command)
    # Nothing here is a real node: the holder checks find nothing to report.
    monkeypatch.setattr(A, "_holders", lambda nodes: {})
    monkeypatch.setattr(A, "_held_by_me", lambda node: False)


def _agent(tmp_path) -> A.Agent:
    a = A.Agent({"https://disfunction.cc"}, "127.0.0.1", tmp_path)
    a.esptool_version = "4.8.1"
    return a


def _wait(job: A.Job, seconds: float = 10) -> None:
    deadline = time.time() + seconds
    while not job.done and time.time() < deadline:
        time.sleep(0.02)
    assert job.done, "the job did not end"


def _texts(job: A.Job) -> list[str]:
    return [line["text"] for line in job.lines]


# ------------------------------------------------- row 49: one job per port

def test_two_ports_program_at_once_and_each_log_holds_only_its_own_lines(monkeypatch, tmp_path):
    _fake_esptool(monkeypatch, seconds=1.0)
    a = _agent(tmp_path)
    t0 = time.time()
    one = a.start_esp({"op": "connect", "port": "/dev/cu.usbmodem101", "chip": "esp32c6", "baud": 115200})
    two = a.start_esp({"op": "connect", "port": "/dev/cu.usbmodem1101", "chip": "esp32c6", "baud": 115200})
    assert "job" in one and "job" in two, (one, two)
    j1, j2 = a.jobs[one["job"]], a.jobs[two["job"]]
    _wait(j1)
    _wait(j2)
    # Side by side, not one after the other: two 1 s jobs end well inside 2 s.
    assert time.time() - t0 < 1.9
    assert j1.result["status"] == "pass" and j2.result["status"] == "pass"
    assert j1.result["info"]["mac"].endswith(":01")
    assert j2.result["info"]["mac"].endswith(":01")
    assert any("usbmodem101" in t for t in _texts(j1))
    assert all("usbmodem1101" not in t for t in _texts(j1))
    assert any("usbmodem1101" in t for t in _texts(j2))
    assert all("usbmodem1101" in t for t in _texts(j2) if "usbmodem" in t)
    assert a.esp_runs == {}


def test_a_second_job_on_the_same_port_is_refused_and_another_port_is_not(monkeypatch, tmp_path):
    _fake_esptool(monkeypatch, seconds=1.0)
    a = _agent(tmp_path)
    first = a.start_esp({"op": "connect", "port": "/dev/cu.usbmodem101", "baud": 115200})
    again = a.start_esp({"op": "connect", "port": "/dev/cu.usbmodem101", "baud": 115200})
    other = a.start_esp({"op": "connect", "port": "/dev/cu.usbmodem201", "baud": 115200})
    assert "job" in first
    assert "already programming the device on /dev/cu.usbmodem101" in again["error"]
    assert "job" in other
    _wait(a.jobs[first["job"]])
    _wait(a.jobs[other["job"]])


# ------------------------------------------------- row 51: a job can be stopped

def test_cancel_stops_a_running_esptool_within_two_seconds(monkeypatch, tmp_path):
    _fake_esptool(monkeypatch, seconds=60)
    monkeypatch.setattr(A, "image_cache_dir", lambda: tmp_path)
    a = _agent(tmp_path)
    started = a.start_esp({"op": "flash", "port": "/dev/cu.usbmodem101", "baud": 115200,
                           "images": [{"address": "0x0", "name": "fw.bin",
                                       "data": base64.b64encode(b"\xe9" * 64).decode()}]})
    job = a.jobs[started["job"]]
    time.sleep(0.5)                       # esptool is writing
    t0 = time.time()
    out = a.cancel_esp({"job": started["job"]})
    assert out["running"] and out["done"]
    assert time.time() - t0 < 2.0
    assert job.result == {"status": "fail", "error": A.CANCELLED, "cancelled": True}
    assert any("cancelled" in t for t in _texts(job))
    # The port is free at once: the next job on it starts.
    _fake_esptool(monkeypatch, seconds=0)
    nxt = a.start_esp({"op": "connect", "port": "/dev/cu.usbmodem101", "baud": 115200})
    assert "job" in nxt, nxt
    _wait(a.jobs[nxt["job"]])


def test_cancel_ends_the_boot_wait_at_once(monkeypatch, tmp_path):
    """"Stop waiting" for BOOT: the ladder retries for 30 s unless told to stop."""
    _fake_esptool(monkeypatch, seconds=0, outcome="fail")
    monkeypatch.setattr(A.EspRun, "_pulse_enable", lambda self: None)
    a = _agent(tmp_path)
    started = a.start_esp({"op": "erase", "port": "/dev/cu.usbserial-10", "baud": 460800})
    job = a.jobs[started["job"]]
    deadline = time.time() + 10
    while not any("waiting for the BOOT button" in t for t in _texts(job)):
        assert time.time() < deadline, _texts(job)
        time.sleep(0.05)
    t0 = time.time()
    out = a.cancel_esp({"port": "/dev/cu.usbserial-10"})
    assert out["done"] and time.time() - t0 < 2.0
    assert job.result["cancelled"] is True


def test_cancelling_a_job_that_already_ended_is_not_an_error(tmp_path):
    a = _agent(tmp_path)
    assert a.cancel_esp({"port": "/dev/cu.usbmodem101"}) == {"ok": True, "running": False}
    assert a.cancel_esp({"job": 12345}) == {"ok": True, "running": False}


def test_esptools_own_last_words_are_the_message():
    lines = ["Serial port /dev/cu.usbmodem101", "",
             "A fatal error occurred: Could not open /dev/cu.usbmodem101, the port is busy or doesn't exist.",
             "([Errno 2] could not open port /dev/cu.usbmodem101)"]
    msg = A.esptool_failure(lines)
    assert msg.startswith("Could not open /dev/cu.usbmodem101")
    assert "could not open port" in msg            # what the ladder reads
    assert A.esptool_failure(["Connecting....", "done"]) == ""


# ------------------------------------------------- row 49: one console per port

class FakeMonitor:
    def __init__(self, port, baud, signals):
        self.port, self.written, self.closed, self.error = port, [], False, ""

    def since(self, n, wait=0.0):
        return n, []

    def write(self, text):
        self.written.append(text)

    def reset(self):
        pass

    def close(self):
        self.closed = True


def _consoles(monkeypatch, tmp_path) -> A.Agent:
    monkeypatch.setattr(A, "Monitor", FakeMonitor)
    monkeypatch.setattr(A, "_holders", lambda nodes: {})
    monkeypatch.setattr(A, "_held_by_me", lambda node: False)
    return _agent(tmp_path)


def test_each_port_keeps_its_own_console(monkeypatch, tmp_path):
    a = _consoles(monkeypatch, tmp_path)
    assert a.monitor_open({"port": "p1", "baud": 115200})["open"]
    assert a.monitor_open({"port": "p2", "baud": 115200})["open"]
    p1, p2 = a.monitors["p1"], a.monitors["p2"]
    assert not p1.closed                     # opening p2 left p1 alone
    assert a.monitor_write({"port": "p1", "text": "Status 0\n"}) == {"ok": True}
    assert p1.written == ["Status 0\n"] and p2.written == []
    assert a.monitor_write({"port": "p3", "text": "x"})["error"] == "the monitor is not open on p3"
    a.monitor_close({"port": "p1"})
    assert p1.closed and not p2.closed and list(a.monitors) == ["p2"]
    assert a.monitor_lines("p1", 0)["open"] is False
    assert a.monitor_lines("p2", 0)["open"] is True


def test_a_call_with_no_port_reaches_a_console_only_when_there_is_one(monkeypatch, tmp_path):
    """A page from before per-port consoles names no port. With one console
    that is the one it means; with two, guessing is the defect."""
    a = _consoles(monkeypatch, tmp_path)
    a.monitor_open({"port": "p1"})
    assert a.monitor_write({"text": "x"}) == {"ok": True}
    a.monitor_open({"port": "p2"})
    assert "not open" in a.monitor_write({"text": "x"})["error"]
    assert a.monitors["p1"].written == ["x"] and a.monitors["p2"].written == []


def test_a_console_is_refused_while_its_port_is_being_programmed(monkeypatch, tmp_path):
    _fake_esptool(monkeypatch, seconds=1.0)
    a = _consoles(monkeypatch, tmp_path)
    a.monitor_open({"port": "p1"})
    started = a.start_esp({"op": "connect", "port": "p1", "baud": 115200})
    assert "p1" not in a.monitors            # esptool needs the port to itself
    assert "being programmed" in a.monitor_open({"port": "p1"})["error"]
    _wait(a.jobs[started["job"]])
    assert a.monitor_open({"port": "p1"})["open"]


def test_the_idle_watch_closes_only_the_quiet_console(monkeypatch, tmp_path):
    a = _consoles(monkeypatch, tmp_path)
    a.monitor_open({"port": "quiet"})
    a.monitor_open({"port": "busy"})
    a.monitor_touched["quiet"] = time.time() - A.MONITOR_IDLE_S - 5
    calls = iter([None, KeyboardInterrupt()])

    def sleep(_s):
        nxt = next(calls)
        if nxt:
            raise nxt
    monkeypatch.setattr(A.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        A.watch_monitor(a)
    assert list(a.monitors) == ["busy"]


# ------------------------------------------------- the image cache

def test_an_image_is_sent_once_and_then_read_from_this_machine(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "image_cache_dir", lambda: tmp_path)
    data = b"\xe9\x03" + b"\x00" * 1000
    sha = hashlib.sha256(data).hexdigest()
    ref = {"address": "0x0", "name": "fw.bin", "sha256": sha}
    assert A.resolve_images([ref]) == ([], [sha])
    got, missing = A.resolve_images([{**ref, "data": base64.b64encode(data).decode()}])
    assert not missing and got[0][1].read_bytes() == data
    got, missing = A.resolve_images([ref])
    assert not missing and got[0][1] == tmp_path / f"{sha}.bin"


def test_bytes_that_do_not_hash_to_the_platforms_sha_are_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "image_cache_dir", lambda: tmp_path)
    with pytest.raises(A.MarkError, match="not flashing them"):
        A.resolve_images([{"address": "0x0", "name": "fw.bin", "sha256": "0" * 64,
                           "data": base64.b64encode(b"other bytes").decode()}])


def test_a_damaged_cached_image_is_asked_for_again(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "image_cache_dir", lambda: tmp_path)
    sha = hashlib.sha256(b"good").hexdigest()
    (tmp_path / f"{sha}.bin").write_bytes(b"bad!")
    assert A.resolve_images([{"address": "0x0", "sha256": sha}]) == ([], [sha])
    assert not (tmp_path / f"{sha}.bin").exists()


def test_a_flash_with_an_image_the_machine_lacks_is_refused_before_a_job_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "image_cache_dir", lambda: tmp_path)
    a = _agent(tmp_path)
    out = a.start_esp({"op": "flash", "port": "p1",
                       "images": [{"address": "0x0", "name": "fw.bin", "sha256": "ab" * 32}]})
    assert out["missing"] == ["ab" * 32] and not a.jobs and not a.esp_runs


# ------------------------------------------------- review findings, 2026-10-24

def test_a_running_job_is_never_forgotten_however_many_others_finish(tmp_path):
    a = _agent(tmp_path)
    slow = A.Job(1)
    with a.lock:
        a._keep_job(slow)
        for i in range(2, 2 + 3 * A.KEEP_JOBS):
            j = A.Job(i)
            j.done = True
            a._keep_job(j)
    assert 1 in a.jobs                          # still running: still answerable
    assert len(a.jobs) == A.KEEP_JOBS


def test_a_close_while_the_console_opens_wins(monkeypatch, tmp_path):
    """The open waits outside the lock (a C6 may still be coming back), so a
    close can arrive in the middle. The console must not appear after it."""
    a = _consoles(monkeypatch, tmp_path)
    opened = []

    class SlowMonitor(FakeMonitor):
        def __init__(self, port, baud, signals):
            a.monitor_close({"port": port})      # the close lands mid-open
            super().__init__(port, baud, signals)
            opened.append(self)
    monkeypatch.setattr(A, "Monitor", SlowMonitor)
    out = a.monitor_open({"port": "p1"})
    assert "closed while it opened" in out["error"]
    assert "p1" not in a.monitors and opened[0].closed


def test_a_console_is_not_installed_over_a_job_that_started_while_it_opened(monkeypatch, tmp_path):
    _fake_esptool(monkeypatch, seconds=1.0)
    a = _consoles(monkeypatch, tmp_path)
    started = {}

    class RacingMonitor(FakeMonitor):
        def __init__(self, port, baud, signals):
            super().__init__(port, baud, signals)
            with a.lock:                          # the job slips in mid-open
                a.opening.discard(port)
            started.update(a.start_esp({"op": "connect", "port": port, "baud": 115200}))
            with a.lock:
                a.opening.add(port)
    monkeypatch.setattr(A, "Monitor", RacingMonitor)
    out = a.monitor_open({"port": "p1"})
    assert "being programmed" in out["error"] and "p1" not in a.monitors
    _wait(a.jobs[started["job"]])


def test_a_job_is_refused_while_its_port_s_console_is_opening(tmp_path):
    a = _agent(tmp_path)
    a.opening.add("p1")
    assert "console is opening" in a.start_esp({"op": "connect", "port": "p1"})["error"]


def test_the_registry_is_read_again_only_when_the_nodes_change(monkeypatch):
    import types
    reads = []

    def comports():
        reads.append(1)
        return [types.SimpleNamespace(device="/dev/cu.usbmodem101", serial_number="98:A3:16:BE:DA:EC")]
    fake = types.SimpleNamespace(comports=comports)
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(tools=types.SimpleNamespace(list_ports=fake)))
    monkeypatch.setitem(sys.modules, "serial.tools", types.SimpleNamespace(list_ports=fake))
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", fake)
    monkeypatch.setattr(A, "_SERIALS", {"nodes": None, "at": 0.0, "map": {}})
    nodes = ["/dev/cu.usbmodem101"]
    for _ in range(5):
        assert A.usb_serial_numbers(nodes)["/dev/cu.usbmodem101"] == "98:A3:16:BE:DA:EC"
    assert len(reads) == 1
    A.usb_serial_numbers(nodes + ["/dev/cu.usbmodem1101"])
    assert len(reads) == 2
