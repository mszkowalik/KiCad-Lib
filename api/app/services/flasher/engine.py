"""The run engine: executes ONE deployment version against one device.

A deployment version binds firmware + berryware + procedure + parameters, so
the engine loads a single id and has everything (design.md §14).

Execution split (docs/flasher/design.md §3): the BROWSER performs the esptool
phase (erase/flash/verify — thousands of latency-sensitive SLIP round trips)
as `action` messages it acknowledges with `result`; the BACKEND owns the whole
scenario — step order, the Tasmota dialog (browser = dumb byte pipe), file
downloads, credential derivation, SIM PIN — and writes every line and step
outcome to Postgres AS IT ARRIVES, so a closed tab loses nothing.

DB pattern: the engine lives in an async WebSocket handler; every DB touch
runs in a thread with its own short-lived session. The serial log is buffered
and flushed in batches (a boot prints hundreds of lines per second).

WebSocket protocol (server view):
  recv {t:"hello", params, client_info}     — operator params (sim_pin, …)
  send {t:"run", spec}                      — steps overview + flash spec
  send {t:"action", id, op, args}           — browser-side op
  recv {t:"result", id, ok, error?, info?}
  send {t:"tx", data}                       — dialog byte pipe
  recv {t:"rx", data}                       — one console line per message
  recv {t:"log", dir, text}                 — esptool/app lines for the record
  send {t:"prompt", id, field, label, secret} / recv {t:"prompt_result", id, value}
  send {t:"state", index, total, label, status}
  recv {t:"abort"}
  send {t:"done", status, error?, results}
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from ...config import settings
from ...db import SessionLocal
from ... import models as M
from .. import crypto
from . import checks, credentials, protocol

BROWSER_OPS = {
    "esp_connect", "erase", "flash", "esp_reset", "await_reenumerate",
    "serial_open", "serial_close", "reset",
}
# Generous per-op ceilings for browser actions (a C6 full flash measured 116 s;
# an ESP32 erase ~20 s). A step's own `timeout` (seconds) overrides.
ACTION_TIMEOUTS = {"erase": 240, "flash": 900, "await_reenumerate": 90, "esp_connect": 90}
SECRET_RE = re.compile(r"password|pin|salt|secret|token", re.I)
# Captured variables with these names also update the device row — the
# "all identification stored per device" requirement (2026-07-29).
IDENTITY_VARS = {
    "topic": "tasmota_id",
    "imei": "imei",
    "iccid": "iccid",
    "imsi": "imsi",
    "modem_model": "modem_model",
    "modem_fw": "modem_fw",
}


class Aborted(Exception):
    pass


class StepFailed(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunEngine:
    def __init__(self, ws, run_id: int):
        self.ws = ws
        self.run_id = run_id
        self.vars: dict[str, Any] = {}
        self.results: dict[str, Any] = {}
        self.last_response: Any = None
        self.rx_q: asyncio.Queue[str] = asyncio.Queue()
        self.pending: dict[int, asyncio.Future] = {}
        self.abort_event = asyncio.Event()
        self._msg_id = 0
        self._seq = 0
        self._logbuf: list[dict] = []
        self._loglock = asyncio.Lock()
        self._recv_task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None
        self.device_unit_id: int | None = None
        self.spec: dict = {}

    # ------------------------------------------------------------- DB helpers

    async def _db(self, fn):
        def wrapped():
            db = SessionLocal()
            try:
                out = fn(db)
                db.commit()
                return out
            finally:
                db.close()

        return await asyncio.to_thread(wrapped)

    async def _load(self) -> None:
        def load(db):
            run = db.get(M.ProgrammingRun, self.run_id)
            if run is None:
                raise StepFailed(f"programming run {self.run_id} not found")
            if run.status != "running":
                raise StepFailed(f"run {self.run_id} is {run.status}, not running")
            # ONE id carries the whole truth: images, files, procedure, params.
            v = db.get(M.DeploymentVersion, run.deployment_version_id)
            if v is None:
                raise StepFailed("this run points at no deployment version")
            dep = db.get(M.Deployment, v.deployment_id)
            prod = db.get(M.ProductionRun, run.production_run_id) if run.production_run_id else None
            images = [
                {
                    "firmware_asset_id": img.asset.id, "filename": img.asset.filename,
                    "address": img.address, "sha256": img.asset.sha256,
                    "size": img.asset.size_bytes, "kind": img.asset.kind,
                    "url": f"/api/flasher/firmware/{img.asset.id}/bin",
                }
                for img in v.images
            ]
            files = [
                {
                    "version_id": link.file_version.id,
                    "filename": link.file_version.file.filename,
                    "size_bytes": link.file_version.size_bytes,
                    "sha256": link.file_version.sha256,
                }
                for link in sorted(v.files, key=lambda f: f.position)
            ]
            params: dict[str, Any] = {}
            if v.param_defaults:
                params.update(v.param_defaults)
            if v.param_set_id:
                ps = db.get(M.ParamSet, v.param_set_id)
                if ps and ps.values_enc:
                    import json as _json
                    params.update(_json.loads(crypto.decrypt_token(ps.values_enc)))
            return {
                "project_id": dep.project_id,
                "production_run_id": prod.id if prod else None,
                "deployment_name": dep.name,
                "deployment_version_no": v.version_no,
                "draft": v.status == "draft",
                "chip": dep.chip,
                "transport_profile": v.transport_profile,
                "monitor_baud": v.monitor_baud,
                "flash_config": v.flash_config,
                "steps": v.steps or [],
                "images": images,
                "files": files,
                "params": params,
            }

        self.spec = await self._db(load)
        self.vars = dict(self.spec["params"])
        self.vars.setdefault("base_url", settings.public_base_url)

    # --------------------------------------------------------------- logging

    def log(self, direction: str, text: str, device_ts: str = "") -> None:
        self._seq += 1
        self._logbuf.append({
            "run_id": self.run_id, "seq": self._seq, "ts": utcnow(),
            "device_ts": device_ts, "dir": direction, "text": text[:4000],
        })

    async def _flush_logs(self) -> None:
        async with self._loglock:
            if not self._logbuf:
                return
            batch, self._logbuf = self._logbuf, []

            def write(db):
                db.bulk_insert_mappings(M.ProgrammingLog, batch)

            await self._db(write)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            try:
                await self._flush_logs()
            except Exception:
                pass  # never let a log hiccup kill the run

    # ------------------------------------------------------------ WS plumbing

    async def _send(self, msg: dict) -> None:
        await self.ws.send_json(msg)

    async def _recv_loop(self) -> None:
        try:
            while True:
                msg = await self.ws.receive_json()
                t = msg.get("t")
                if t == "rx":
                    line = str(msg.get("data", ""))
                    self.log("rx", line, protocol.device_ts(line))
                    self.rx_q.put_nowait(line)
                elif t == "log":
                    self.log(str(msg.get("dir", "app"))[:10], str(msg.get("text", "")))
                elif t in ("result", "prompt_result"):
                    fut = self.pending.pop(int(msg.get("id", -1)), None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                elif t == "abort":
                    self.log("app", "operator aborted the run")
                    self.abort_event.set()
        except Exception:
            # Socket gone: abort whatever is in flight; the outer handler
            # decides the run status.
            self.abort_event.set()

    async def _await_msg(self, msg_id: int, timeout: float) -> dict:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[msg_id] = fut
        abort_wait = asyncio.create_task(self.abort_event.wait())
        try:
            done, _ = await asyncio.wait(
                {fut, abort_wait}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if fut in done:
                return fut.result()
            if abort_wait in done:
                raise Aborted()
            raise StepFailed(f"no reply from the bench within {timeout:.0f}s")
        finally:
            abort_wait.cancel()
            self.pending.pop(msg_id, None)

    async def action(self, op: str, args: dict | None = None, timeout: float | None = None) -> dict:
        self._msg_id += 1
        mid = self._msg_id
        await self._send({"t": "action", "id": mid, "op": op, "args": args or {}})
        limit = timeout or ACTION_TIMEOUTS.get(op, 60)
        msg = await self._await_msg(mid, limit)
        if not msg.get("ok"):
            raise StepFailed(msg.get("error") or f"{op} failed on the bench")
        return msg.get("info") or {}

    async def prompt(self, field: str, label: str, secret: bool = True) -> str:
        self._msg_id += 1
        mid = self._msg_id
        self.log("app", f"waiting for operator input: {label}")
        await self._send({"t": "prompt", "id": mid, "field": field, "label": label, "secret": secret})
        msg = await self._await_msg(mid, 600)
        return str(msg.get("value", ""))

    # --------------------------------------------------------- dialog helpers

    def drain_rx(self) -> None:
        while not self.rx_q.empty():
            self.rx_q.get_nowait()

    async def next_line(self, timeout: float) -> str | None:
        abort_wait = asyncio.create_task(self.abort_event.wait())
        getter = asyncio.create_task(self.rx_q.get())
        try:
            done, _ = await asyncio.wait(
                {getter, abort_wait}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if getter in done:
                return getter.result()
            if abort_wait in done:
                raise Aborted()
            return None
        finally:
            abort_wait.cancel()
            if not getter.done():
                getter.cancel()

    async def send_serial(self, text: str, mask: str | None = None) -> None:
        shown = text if mask is None else text.replace(mask, "•••")
        self.log("tx", shown.rstrip("\n"))
        await self._send({"t": "tx", "data": text})

    async def wait_for(self, key: str, timeout: float, pattern: re.Pattern | None = None) -> Any:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            line = await self.next_line(remaining)
            if line is None:
                return None
            if pattern is not None and pattern.search(line):
                return line
            parsed = protocol.parse_line(line)
            if parsed is not None and key and protocol.matches(parsed, key):
                return parsed

    async def send_command(
        self, cmd: str, payload: Any = None, expect_key: str | None = None,
        timeout: float = 10, mask: str | None = None,
    ) -> Any:
        self.drain_rx()
        body = f"{cmd}\n" if payload in (None, "") else f"{cmd} {payload}\n"
        await self.send_serial(body, mask=mask)
        resp = await self.wait_for(expect_key or cmd, timeout)
        self.last_response = resp
        return resp

    # ------------------------------------------------------------- lifecycle

    async def run(self) -> None:
        status, error = "pass", None
        try:
            await self._load()
            hello = await self.ws.receive_json()
            if hello.get("t") != "hello":
                raise StepFailed("bench did not say hello")
            operator_params = hello.get("params") or {}
            self.vars.update({k: v for k, v in operator_params.items() if v not in (None, "")})
            masked = {
                k: ("•••" if SECRET_RE.search(k) else v) for k, v in self.vars.items()
            }
            client_info = hello.get("client_info") or {}

            def start(db):
                run = db.get(M.ProgrammingRun, self.run_id)
                run.params_snapshot = masked
                run.client_info = client_info

            await self._db(start)
            self._recv_task = asyncio.create_task(self._recv_loop())
            self._flush_task = asyncio.create_task(self._flush_loop())
            await self._send({"t": "run", "spec": {
                k: self.spec[k] for k in (
                    "deployment_name", "deployment_version_no", "draft", "chip",
                    "transport_profile", "monitor_baud", "flash_config", "images",
                )
            } | {"steps": [{"op": s.get("op"), "label": s.get("label", s.get("op"))}
                           for s in self.spec["steps"]]}})

            steps = self.spec["steps"]
            for idx, step in enumerate(steps):
                label = step.get("label") or step.get("op", "?")
                await self._send({"t": "state", "index": idx, "total": len(steps),
                                  "label": label, "status": "running"})
                self.log("app", f"--- step {idx + 1}/{len(steps)}: {label} ({step.get('op')})")
                step_id = await self._db(lambda db, i=idx, s=step: self._step_start(db, i, s))
                t0 = asyncio.get_running_loop().time()
                try:
                    outcome = await self._exec(step) or "pass"
                    dur = int((asyncio.get_running_loop().time() - t0) * 1000)
                    await self._db(lambda db, sid=step_id, o=outcome, d=dur:
                                   self._step_end(db, sid, o, d, None))
                    await self._send({"t": "state", "index": idx, "total": len(steps),
                                      "label": label, "status": outcome})
                    self.log("app", f"--- step {idx + 1} {outcome} in {dur / 1000:.2f}s")
                except (StepFailed, Aborted) as e:
                    dur = int((asyncio.get_running_loop().time() - t0) * 1000)
                    msg = str(e) or ("aborted" if isinstance(e, Aborted) else "fail")
                    await self._db(lambda db, sid=step_id, d=dur, m=msg:
                                   self._step_end(db, sid, "fail", d, m))
                    raise
        except Aborted:
            status, error = "aborted", "aborted"
        except StepFailed as e:
            status, error = "fail", str(e)
        except Exception as e:  # engine bug or socket death — still record it
            status, error = "fail", f"engine error: {e}"
        finally:
            await self._finalize(status, error)

    def _step_start(self, db, idx: int, step: dict) -> int:
        row = M.ProgrammingStep(
            run_id=self.run_id, idx=idx, op=str(step.get("op", ""))[:40],
            label=str(step.get("label", ""))[:200], status="running",
            check_name=str(step.get("check", ""))[:60],
        )
        db.add(row)
        db.flush()
        return row.id

    def _step_end(self, db, step_id: int, status: str, dur_ms: int, error: str | None) -> None:
        row = db.get(M.ProgrammingStep, step_id)
        row.status = status
        row.duration_ms = dur_ms
        row.error = error
        resp = self.last_response
        if isinstance(resp, (dict, list)):
            row.response = resp

    async def _finalize(self, status: str, error: str | None) -> None:
        for task in (self._recv_task, self._flush_task):
            if task:
                task.cancel()
        try:
            await self._flush_logs()
        except Exception:
            pass
        clean_results = {
            k: v for k, v in self.results.items() if not SECRET_RE.search(k)
        }

        def fin(db):
            run = db.get(M.ProgrammingRun, self.run_id)
            if run.status != "running":
                return
            run.status = status
            run.finished_at = utcnow()
            if run.started_at:
                run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
            run.error = error
            run.results = clean_results
            if run.device_unit_id:
                dev = db.get(M.DeviceUnit, run.device_unit_id)
                dev.last_seen = utcnow()
                dev.last_status = status
                # Decision 0003 §5: the first PASS in a batch is the device's
                # `produced` event — it enters finished-goods stock at that
                # run's per-device cost, and nobody has to record it by hand.
                if status == "pass" and run.production_run_id and not run.draft_run:
                    from ..orders import mark_produced
                    try:
                        mark_produced(db, dev, run.production_run_id, actor=run.operator or "flasher",
                                      note=f"passed programming run #{run.id}")
                    except Exception as e:  # noqa: BLE001 — a history conflict must not fail the run
                        import logging
                        logging.getLogger(__name__).warning(
                            f"device {dev.id}: produced event not written: {e}")
            # The green/red grid the device view shows. Derived here so it exists
            # for a run that died mid-way too: the steps that did pass still
            # prove their functionality, and the rest go grey.
            db.flush()
            checks.recompute(db, run)

        await self._db(fin)
        try:
            await self._send({"t": "done", "status": status, "error": error,
                              "results": clean_results})
        except Exception:
            pass

    # ------------------------------------------------------------ device row

    async def _register_device(self, chip: str, mac: str) -> None:
        mac_norm = mac.strip().lower()
        serial = mac_norm.replace(":", "").upper()

        def upsert(db):
            dev = db.query(M.DeviceUnit).filter(M.DeviceUnit.mac == mac_norm).one_or_none()
            if dev is None:
                dev = M.DeviceUnit(
                    project_id=self.spec["project_id"], mac=mac_norm, chip=chip,
                    serial=serial,
                )
                db.add(dev)
                db.flush()
            else:
                dev.chip = chip or dev.chip
                dev.serial = dev.serial or serial
                dev.last_seen = utcnow()
            run = db.get(M.ProgrammingRun, self.run_id)
            run.device_unit_id = dev.id
            run.mac_read = mac_norm
            run.chip_read = chip
            run.attempt_no = (
                db.query(M.ProgrammingRun)
                .filter(M.ProgrammingRun.device_unit_id == dev.id,
                        M.ProgrammingRun.id != self.run_id)
                .count() + 1
            )
            return dev.id

        self.device_unit_id = await self._db(upsert)
        self.vars["mac"] = mac_norm
        self.vars["serial"] = serial
        self.results["chip"] = chip
        self.results["mac"] = mac_norm

    async def _store_identity(self, names: dict[str, Any]) -> None:
        cols = {IDENTITY_VARS[k]: str(v) for k, v in names.items()
                if k in IDENTITY_VARS and v not in (None, "")}
        if not cols or not self.device_unit_id:
            return

        def write(db):
            dev = db.get(M.DeviceUnit, self.device_unit_id)
            for col, val in cols.items():
                setattr(dev, col, val)

        await self._db(write)

    def _capture(self, step: dict, resp: Any) -> dict[str, Any]:
        got: dict[str, Any] = {}
        for name, path in (step.get("capture") or {}).items():
            value = protocol.dig(resp, path)
            self.vars[name] = value
            self.results[name] = value
            got[name] = value
            self.log("app", f"captured {name} = {value!r}")
        return got

    # ----------------------------------------------------------------- steps

    async def _exec(self, step: dict) -> str | None:
        op = step.get("op")
        V = lambda v: protocol.subst(v, self.vars)  # noqa: E731
        timeout = float(step.get("timeout", 10))

        if op in BROWSER_OPS:
            args = dict(step)
            args.pop("op", None)
            args.pop("label", None)
            if op == "flash":
                images = self.spec["images"]
                kinds = step.get("kinds")
                if kinds:
                    images = [i for i in images if i["kind"] in kinds]
                if not images:
                    raise StepFailed("flash step, but the script pins no release images")
                args["images"] = images
                args["flash_config"] = self.spec["flash_config"] or {}
                self.results["images"] = [f"{i['filename']}@{i['address']}" for i in images]
            if op == "serial_open":
                args.setdefault("baud", self.spec["monitor_baud"])
            info = await self.action(op, args, timeout=float(step["timeout"]) if "timeout" in step else None)
            if op == "esp_connect":
                chip, mac = str(info.get("chip", "")), str(info.get("mac", ""))
                if not mac:
                    raise StepFailed("bench reported no MAC")
                want = (self.spec["chip"] or "").lower().replace("-", "")
                if want and want not in chip.lower().replace("-", "").replace(" ", ""):
                    raise StepFailed(f'release expects {self.spec["chip"]} but the device reports "{chip}"')
                await self._register_device(chip, mac)
            return None

        if op == "sleep":
            await asyncio.sleep(float(step.get("seconds", 1)))
            return None

        if op == "wait_boot":
            probe = step.get("probe") or {"cmd": "Status", "payload": "0", "expect_key": "Status"}
            every = float(step.get("probe_every", 2))
            pattern = re.compile(step["pattern"], re.I) if step.get("pattern") else None
            deadline = asyncio.get_running_loop().time() + timeout
            attempt = 0
            while asyncio.get_running_loop().time() < deadline:
                attempt += 1
                self.drain_rx()
                payload = probe.get("payload")
                await self.send_serial(f"{probe['cmd']} {payload}\n" if payload else f"{probe['cmd']}\n")
                window = min(every, deadline - asyncio.get_running_loop().time())
                hit = await self.wait_for(probe.get("expect_key", probe["cmd"]), window, pattern)
                if hit is not None:
                    self.log("app", f"device answered on probe {attempt} — firmware is up")
                    await asyncio.sleep(0.3)
                    self.drain_rx()
                    return None
                self.log("app", f"probe {attempt}: no answer yet")
            raise StepFailed(
                f'device never answered "{probe["cmd"]}" within {timeout:.0f}s '
                "(is it running the app, or still in the ROM/stub loader?)"
            )

        if op == "command":
            resp = await self.send_command(V(step["cmd"]), V(step.get("payload")),
                                           step.get("expect_key"), timeout)
            if resp is None:
                # `optional` means silence is the EXPECTED outcome. The V2 flow
                # ends by clearing the bench WiFi, after which the device
                # restarts and stops answering — config.py wrapped exactly this
                # call in try/except. Without the flag a correct run fails on
                # its last step.
                if step.get("optional"):
                    self.log("app", f"{step['cmd']}: no answer, which this step expects")
                    return "pass"
                raise StepFailed(f'no response to "{step["cmd"]}" within {timeout:.0f}s')
            got = self._capture(step, resp)
            await self._store_identity(got)
            return None

        if op == "set_and_check":
            value = V(step["value"])
            confirm = value if "confirm" not in step else V(step["confirm"])
            key = step.get("response_key") or step["cmd"]
            resp = await self.send_command(V(step["cmd"]), value, key, timeout)
            if resp is None:
                raise StepFailed(f"no response for {step['cmd']}")
            if not isinstance(resp, dict):
                raise StepFailed(f"unexpected response type for {step['cmd']}: {resp!r}")
            hit = next((k for k in resp if key.lower() in k.lower()), None)
            if hit is None:
                raise StepFailed(f"response for {step['cmd']} has no {key}: {resp}")
            if str(resp[hit]) != str(confirm):
                raise StepFailed(f'{step["cmd"]}: got "{resp[hit]}", expected "{confirm}"')
            self.log("app", f"{step['cmd']} confirmed = {confirm}")
            got = self._capture(step, resp)
            await self._store_identity(got)
            return None

        if op == "backlog":
            cmds = [V(c) for c in step.get("commands", [])]
            resp = await self.send_command("Backlog", "; ".join(cmds),
                                           step.get("expect_key"), timeout)
            if step.get("expect_key") and resp is None:
                raise StepFailed(f"no {step['expect_key']} response to Backlog")
            return None

        if op == "berry":
            resp = await self.send_command("Br", V(step["code"]), "Br", timeout)
            if resp is None:
                raise StepFailed("no Br response")
            self._capture(step, resp)
            return None

        if op == "expect":
            pattern = re.compile(V(step["pattern"]), re.I)
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                line = await self.next_line(deadline - asyncio.get_running_loop().time())
                if line is None:
                    break
                if pattern.search(line):
                    return None
            raise StepFailed(f"expected /{step['pattern']}/ not seen")

        if op == "assert_equals":
            got = self.vars.get(step["var"]) if step.get("var") else protocol.dig(self.last_response, step["path"])
            want = V(step["equals"])
            if str(got) != str(want):
                raise StepFailed(f'assert_equals: got "{got}", expected "{want}"')
            self.log("app", f"assert ok: {step.get('var') or step.get('path')} == {want}")
            return None

        if op == "assert_range":
            raw = self.vars.get(step["var"]) if step.get("var") else protocol.dig(self.last_response, step["path"])
            try:
                got = float(raw)
            except (TypeError, ValueError):
                raise StepFailed(f"assert_range: {raw!r} is not a number")
            if not (float(step["min"]) <= got <= float(step["max"])):
                raise StepFailed(f"assert_range: {got} outside [{step['min']}, {step['max']}]")
            self.log("app", f"assert ok: {got} in [{step['min']}, {step['max']}]")
            return None

        if op == "poll_until":
            return await self._poll_until(step, timeout)

        if op == "download_files":
            return await self._download_files(step)

        if op == "derive_credentials":
            return await self._derive_credentials(step)

        if op == "lte_sim_pin":
            return await self._lte_sim_pin(step, timeout)

        raise StepFailed(f'unknown op "{op}"')

    # ------------------------------------------------------------ complex ops

    async def _poll_until(self, step: dict, timeout: float) -> None:
        """Send `cmd` every `every` seconds until the response satisfies the
        condition (path+equals / path+matches / min+max), or just answers when
        no condition is given. This is how the LTE switch-over is proven:
        poll LteState until the modem reports a connection."""
        every = float(step.get("every", 2))
        path = step.get("path")
        deadline = asyncio.get_running_loop().time() + timeout
        attempt = 0
        while asyncio.get_running_loop().time() < deadline:
            attempt += 1
            resp = await self.send_command(
                protocol.subst(step["cmd"], self.vars), step.get("payload"),
                step.get("expect_key"), min(every, max(deadline - asyncio.get_running_loop().time(), 0.5)),
            )
            if resp is not None:
                ok = True
                if path:
                    value = protocol.dig(resp, path)
                    if "equals" in step:
                        ok = str(value) == str(protocol.subst(step["equals"], self.vars))
                    elif "matches" in step:
                        ok = value is not None and re.search(step["matches"], str(value), re.I) is not None
                    elif "min" in step or "max" in step:
                        try:
                            v = float(value)
                            ok = float(step.get("min", "-inf")) <= v <= float(step.get("max", "inf"))
                        except (TypeError, ValueError):
                            ok = False
                    else:
                        ok = value not in (None, "")
                if ok:
                    self.log("app", f"poll_until satisfied on attempt {attempt}")
                    self._capture(step, resp)
                    return None
            wait = deadline - asyncio.get_running_loop().time()
            if wait > 0:
                await asyncio.sleep(min(every, wait))
        raise StepFailed(f'poll_until: condition on "{step["cmd"]}" not met within {timeout:.0f}s')

    async def _download_files(self, step: dict) -> None:
        """The device fetches every pinned file version from THIS platform over
        HTTP (UrlFetch), then the size is verified against the stored byte
        count — the V2 config.py loop, with the platform as the file host."""
        files = self.spec["files"]
        if not files:
            raise StepFailed("download_files: the script version pins no device files")
        base = str(self.vars.get("base_url", "")).rstrip("/")
        if not base or "localhost" in base or "127.0.0.1" in base:
            raise StepFailed(
                f'download_files: base_url "{base}" is not reachable from the device — '
                "set public_base_url (or the base_url param) to the platform's LAN address"
            )
        per_file_timeout = float(step.get("timeout", 30))
        retries = int(step.get("retries", 3))
        for f in files:
            url = f"{base}/api/flasher/files/{f['version_id']}/{f['filename']}"
            ok = False
            for attempt in range(1, retries + 1):
                resp = await self.send_command("UrlFetch", url, "UrlFetch", per_file_timeout)
                if isinstance(resp, dict) and any(
                    str(v) == "Done" for k, v in resp.items() if "urlfetch" in k.lower()
                ):
                    ok = True
                    break
                self.log("app", f"download attempt {attempt} for {f['filename']} failed")
            if not ok:
                raise StepFailed(f"failed to download {f['filename']} after {retries} attempts")
            size = await self._file_size(f["filename"])
            if size != f["size_bytes"]:
                raise StepFailed(
                    f"{f['filename']}: device reports {size} bytes, platform stored {f['size_bytes']}"
                )
            self.log("app", f"{f['filename']} downloaded, {size} bytes verified")
            self.results.setdefault("downloaded", []).append(f["filename"])

    async def _file_size(self, filename: str) -> int:
        resp = await self.send_command("Br", f'return open("{filename}", "r").size()', "Br", 10)
        if isinstance(resp, dict):
            value = next((v for k, v in resp.items() if k.lower() == "br"), None)
            try:
                return int(value)
            except (TypeError, ValueError):
                return -1
        return -1

    async def _derive_credentials(self, step: dict) -> None:
        """Port of the V2 credential block: username = the device's Tasmota
        topic, password derived from username + fleet salt. Written to
        device_config_values (per-device, clear by decision 2026-07-27)."""
        user_var = step.get("user_var", "topic")
        username = str(self.vars.get(user_var, "") or "")
        if not username or len(username.split("_")) != 2:
            raise StepFailed(f"derive_credentials: no usable device name in var {user_var!r} ({username!r})")
        salt = str(self.vars.get(step.get("salt_param", "creds_salt"), "") or "")
        if not salt:
            raise StepFailed("derive_credentials: creds_salt param is missing")
        username, password, salt, final_hash = credentials.derive(username, "", salt)
        line = credentials.mosquitto_line(username, salt, final_hash)
        self.vars["mqtt_user"] = username
        self.vars["mqtt_password"] = password
        self.results["mqtt_user"] = username
        if not self.device_unit_id:
            raise StepFailed("derive_credentials: no device identified yet (esp_connect must run first)")

        def write(db):
            for key, value, secret in (
                ("mqtt_user", username, False),
                ("mqtt_password", password, True),
                ("mqtt_creds_line", line, True),
            ):
                (db.query(M.DeviceConfigValue)
                   .filter(M.DeviceConfigValue.device_unit_id == self.device_unit_id,
                           M.DeviceConfigValue.key == key,
                           M.DeviceConfigValue.current.is_(True))
                   .update({"current": False}))
                db.add(M.DeviceConfigValue(
                    device_unit_id=self.device_unit_id, key=key, value=value,
                    is_secret=secret, set_by_run_id=self.run_id, current=True,
                ))

        await self._db(write)
        self.log("app", f"MQTT credentials derived for {username}")

    async def _lte_sim_pin(self, step: dict, timeout: float) -> str | None:
        """Provision the SIM PIN, once. Resolution order (user decision
        2026-07-29): operator field on the bench → param set default → mid-run
        prompt. A script for PIN-less SIMs omits this step, or marks it
        optional so an empty value skips it.

        NEVER retried: the firmware's own driver documents that a re-sent
        wrong PIN would PUK-lock the SIM within minutes (xdrv_128 ~483)."""
        pin = str(self.vars.get("sim_pin", "") or "").strip()
        if not pin:
            if step.get("optional"):
                self.log("app", "no SIM PIN configured — step marked optional, skipping")
                return "skipped"
            pin = (await self.prompt("sim_pin", "Enter the SIM PIN for this device", secret=True)).strip()
            if not pin:
                raise StepFailed("no SIM PIN provided")
            self.vars["sim_pin"] = pin
        resp = await self.send_command("LteSimPin", pin, "LteSimPin", timeout, mask=pin)
        if resp is None:
            raise StepFailed("no response to LteSimPin")
        self.last_response = resp if not isinstance(resp, dict) else {
            k: ("•••" if "pin" in k.lower() else v) for k, v in resp.items()
        }
        self.log("app", "SIM PIN provisioned (sent once, never retried)")
        return None
