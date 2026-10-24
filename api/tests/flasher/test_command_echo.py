"""The engine never takes the device's command echo as the reply (work list row 50).

Tasmota repeats every command as `CMD: <command>`. `parse_line` reads the text
after the first '=' of a line that is not JSON and `matches` accepts the key as
a substring of it, so an echo whose command held an '=' answered its own key.
Run 8980 (CE_Dongle_V3, 2026-10-24) is the case: "hy-BR-id" in the file list
of a `Br` download matched `Br` 0.06 s after the command, and the size check
read `None`.

No database: the engine is driven through a stand-in WebSocket. Run from
`api/`:
    python -m pytest tests/flasher -q
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.services.flasher import engine as E
from app.services.flasher import protocol

# The echo of run 8980, step 23, as the run log stored it (seq 285).
RUN_8980_ECHO = (
    "23:50:17.269 CMD: Br var b='http://disfunction.cc/lib/api/flasher/files/23/' var r=[] "
    "for f:['AFORE_AF-TH.json','DEYE_HP3.json','DEYE_LP1.json','DEYE_LP3.json','EASTRON.json',"
    "'GOODWE.json','ORNO.json','SOFAR.json','SOLIS_GRID.json','SOLIS_HYBRID.json',"
    "'mateodongle_aqua.be','mateodongle_buttons.be','mateodongle_config.be','mateodongle_leds.be',"
    "'mateodongle_monitoring.be','mateodongle_processes_handler.be','mateodongle_web_config.be',"
    "'mux.json','mux_presets.json','autoexec.be'] var n=-1 var k=0 while n<0&&k<3 k+=1 try "
    "tasmota.urlfetch(b+f,f) var h=open(f) n=h.size() h.close() except .. end tasmota.yield() end "
    "r.push(n) end return r.concat(',')"
)
SIZES = "2652,2989,2101,4967,945,2335,389,2442,852,2319,47902,2218,12304,8968,56331,15936,39987,39,571,12968"
REPLY = '23:50:24.401 RSL: RESULT = {"Br":"' + SIZES + '"}'


class FakeWs:
    def __init__(self):
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def send_json(self, msg: dict) -> None:
        self.sent.append(msg)

    async def receive_json(self) -> dict:
        return await self.inbox.get()


def test_the_run_8980_echo_matched_the_key_before_this_change():
    """The defect itself, so the test below is known to cover it."""
    parsed = protocol.parse_line(RUN_8980_ECHO)
    assert protocol.matches(parsed, "Br")


def test_an_echo_is_recognised_with_and_without_the_device_time():
    assert protocol.is_echo(RUN_8980_ECHO)
    assert protocol.is_echo("CMD: Backlog Wifi 1; MqttUser dongle_x")
    assert not protocol.is_echo(REPLY)
    assert not protocol.is_echo('12:00:01.000 MQT: stat/dongle_x/RESULT = {"Br":"1"}')
    assert not protocol.is_echo("23:50:17.269 RSL: RESULT = {\"CMD\":\"x\"}")


def test_wait_for_skips_the_echo_and_returns_the_real_reply():
    async def go():
        eng = E.RunEngine(FakeWs(), run_id=0)
        ws = eng.ws
        recv = asyncio.create_task(eng._recv_loop())
        await ws.inbox.put({"t": "rx", "data": RUN_8980_ECHO})
        await ws.inbox.put({"t": "rx", "data": REPLY})
        got = await eng.wait_for("Br", 2)
        recv.cancel()
        return got

    assert asyncio.run(go()) == {"Br": SIZES}


def test_an_echo_alone_is_no_answer():
    async def go():
        eng = E.RunEngine(FakeWs(), run_id=0)
        recv = asyncio.create_task(eng._recv_loop())
        await eng.ws.inbox.put({"t": "rx", "data": RUN_8980_ECHO})
        got = await eng.wait_for("Br", 0.3)
        recv.cancel()
        return got

    assert asyncio.run(go()) is None
