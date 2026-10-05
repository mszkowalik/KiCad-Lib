"""A device unplugged during the console phase fails the run at once.

Before 2026-10-05 a bench whose device was pulled mid-run showed no failure:
the agent's console reader died with one "[read error]" line, the page only
logged its failed writes, and the engine waited out every step's timeout — and
a step that expects no answer (a Backlog with no expected key, an optional
command) passed. The bench now says `device_lost`, and the engine ends the wait
and fails every later step that talks to the device, until the console is
opened again.

No database: the engine is driven through a stand-in WebSocket. Run from
`api/`:
    python -m pytest tests/flasher -q
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest

from app.services.flasher import engine as E


class FakeWs:
    """Sends are recorded; receives come from a queue the test fills."""

    def __init__(self):
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def send_json(self, msg: dict) -> None:
        self.sent.append(msg)

    async def receive_json(self) -> dict:
        return await self.inbox.get()


def _engine() -> tuple[E.RunEngine, FakeWs]:
    ws = FakeWs()
    return E.RunEngine(ws, run_id=0), ws


def test_a_wait_ends_when_the_device_is_lost_and_the_step_says_why():
    async def go():
        eng, ws = _engine()
        recv = asyncio.create_task(eng._recv_loop())
        step = asyncio.create_task(eng._exec({"op": "command", "cmd": "Status", "timeout": 30}))
        await asyncio.sleep(0.05)
        await ws.inbox.put({"t": "device_lost", "error": "device reports readiness to read but returned no data"})
        t0 = asyncio.get_running_loop().time()
        with pytest.raises(E.StepFailed):
            await step
        assert asyncio.get_running_loop().time() - t0 < 1.0     # not the 30 s timeout
        assert eng.device_lost.startswith("device reports")
        recv.cancel()

    asyncio.run(go())


def test_a_later_step_that_talks_to_the_device_fails_and_an_optional_one_passes():
    async def go():
        eng, ws = _engine()
        eng.device_lost = "tx failed: write failed"
        eng.lost_event.set()
        for step in ({"op": "backlog", "commands": ["SetOption1 1"]}, {"op": "wait_boot", "timeout": 20},
                     {"op": "command", "cmd": "Status"}):
            with pytest.raises(E.StepFailed) as e:
                await eng._exec(step)
            assert "disconnected" in str(e.value)
        assert await eng._exec({"op": "command", "cmd": "WifiConfig", "optional": True}) == "pass"
        assert not [m for m in ws.sent if m.get("t") == "tx"]          # nothing was written to a gone port

    asyncio.run(go())


def test_opening_the_console_again_clears_the_lost_device():
    async def go():
        eng, ws = _engine()
        eng.spec = {"monitor_baud": 115200}
        eng.device_lost = "gone"
        eng.lost_event.set()
        recv = asyncio.create_task(eng._recv_loop())
        step = asyncio.create_task(eng._exec({"op": "serial_open"}))
        await asyncio.sleep(0.05)
        action = next(m for m in ws.sent if m.get("t") == "action")
        await ws.inbox.put({"t": "result", "id": action["id"], "ok": True})
        await step
        assert eng.device_lost == "" and not eng.lost_event.is_set()
        recv.cancel()

    asyncio.run(go())
