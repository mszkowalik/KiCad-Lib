"""Publish gates for a deployment version.

Every check here exists because the mistake it catches is cheap to make and
expensive to discover on a bench full of devices. `check()` returns errors
(publishing is refused) and warnings (publishing is allowed, the UI shows
them), and the composer calls the same function live while you edit — one
implementation, so the editor can never disagree with the publish button.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ... import models as M
from .. import crypto
from . import bundle

PLACEHOLDER = re.compile(r"\{(\w+)\}")

# Transport profiles and the chips they are valid for. Native USB-Serial/JTAG
# exists only on the C/S families; picking it for a plain ESP32 means the
# monitor phase would never touch DTR/RTS on a part that NEEDS them.
NATIVE_USB_CHIPS = ("esp32c3", "esp32c6", "esp32s2", "esp32s3", "esp32h2")

# Ops the engine runs in the browser, i.e. the flash phase.
FLASH_OPS = {"erase", "flash", "esp_reset", "await_reenumerate"}


def _norm_chip(s: str) -> str:
    return (s or "").lower().replace("-", "").replace(" ", "").replace("_", "")


def _addr(a: str) -> int | None:
    try:
        return int(a, 16)
    except (TypeError, ValueError):
        return None


def _param_keys(db, version: M.DeploymentVersion) -> set[str]:
    keys = set((version.param_defaults or {}).keys())
    if version.param_set_id:
        ps = db.get(M.ParamSet, version.param_set_id)
        if ps and ps.values_enc:
            try:
                keys |= set(json.loads(crypto.decrypt_token(ps.values_enc)).keys())
            except Exception:  # noqa: BLE001 — an unreadable set is its own error below
                keys.add("<undecryptable>")
    return keys


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)


def check(db, version: M.DeploymentVersion) -> dict:
    """Return {"errors": [...], "warnings": [...], "ok": bool}."""
    errors: list[str] = []
    warnings: list[str] = []
    deployment = db.get(M.Deployment, version.deployment_id)
    steps = version.steps or []
    ops = [s.get("op") for s in steps]

    # 1. Everything pinned must be published — a run can never flash a draft.
    for link in version.files:
        fv = link.file_version
        if fv.status != "published":
            errors.append(
                f"berryware file {fv.file.filename} v{fv.version_no} is {fv.status} — "
                "publish it first")

    # 2. Chip agreement across deployment, images and transport profile.
    dep_chip = _norm_chip(deployment.chip if deployment else "")
    for img in version.images:
        img_chip = _norm_chip(img.asset.chip)
        if dep_chip and img_chip and img_chip != dep_chip:
            errors.append(
                f"image {img.asset.filename} is built for {img.asset.chip}, but this "
                f"deployment targets {deployment.chip}")
        elif not img_chip:
            warnings.append(f"image {img.asset.filename} has no chip recorded")
    native = dep_chip in [_norm_chip(c) for c in NATIVE_USB_CHIPS]
    if version.transport_profile == "usb_serial_jtag" and dep_chip and not native:
        errors.append(
            f"transport usb_serial_jtag needs a native-USB part; {deployment.chip} uses an "
            "external UART bridge (the monitor phase would never release EN/IO0)")
    if version.transport_profile == "uart_bridge" and native:
        warnings.append(
            f"{deployment.chip} has built-in USB-Serial/JTAG — uart_bridge is only right if "
            "this board really is wired through an external bridge")

    # 3. Flash map: unique, non-overlapping, parseable offsets.
    spans: list[tuple[int, int, str]] = []
    for img in version.images:
        start = _addr(img.address)
        if start is None:
            errors.append(f"image {img.asset.filename}: '{img.address}' is not a hex offset")
            continue
        spans.append((start, start + max(img.asset.size_bytes, 1), img.asset.filename))
    spans.sort()
    for (a_start, a_end, a_name), (b_start, b_end, b_name) in zip(spans, spans[1:]):
        if b_start < a_end:
            errors.append(
                f"flash map overlap: {a_name} covers 0x{a_start:X}..0x{a_end:X} but "
                f"{b_name} starts at 0x{b_start:X}")

    # 4. Dataflow: every {placeholder} must resolve, and only from EARLIER steps.
    available = set(bundle.RUNTIME_VARS) | _param_keys(db, version)
    for idx, step in enumerate(steps):
        for text in _walk_strings({k: v for k, v in step.items()
                                   if k not in ("label", "note", "capture")}):
            for name in PLACEHOLDER.findall(text):
                if name not in available:
                    errors.append(
                        f"step {idx + 1} ({step.get('op')}) uses {{{name}}}, which no parameter "
                        "defines and no earlier step captures")
        var = step.get("var")
        if var and var not in available:
            errors.append(
                f"step {idx + 1} ({step.get('op')}) asserts on '{var}', which no earlier step "
                "captures")
        available |= set((step.get("capture") or {}).keys())
        if step.get("op") == "derive_credentials":
            available |= {"mqtt_user", "mqtt_password"}
        if step.get("op") == "esp_connect":
            available |= {"mac", "serial", "chip"}

    # 5. Downloads: need pinned files, and autoexec.be must come last.
    if "download_files" in ops and not version.files:
        errors.append("the procedure downloads files, but this version pins no berryware")
    if version.files and "download_files" not in ops:
        warnings.append(
            f"{len(version.files)} berryware files are pinned but the procedure never "
            "downloads them")
    if version.files:
        ordered = sorted(version.files, key=lambda f: f.position)
        names = [f.file_version.file.filename for f in ordered]
        if "autoexec.be" in names and names[-1] != "autoexec.be":
            errors.append(
                "autoexec.be must be downloaded LAST — otherwise a partial download leaves a "
                "device that boots an incomplete application")

    # 6. Flash phase sanity.
    if any(o in FLASH_OPS for o in ops) and not version.images:
        errors.append("the procedure flashes, but this version pins no firmware image")
    if version.images and "flash" not in ops:
        warnings.append("firmware images are pinned but the procedure never flashes them")
    if "flash" in ops and "esp_connect" not in ops:
        errors.append("a flash step needs esp_connect first (it opens the ROM loader)")
    if "esp_connect" in ops and ops.index("esp_connect") != 0:
        warnings.append(
            "esp_connect is not the first step — the MAC is read there, so anything before it "
            "cannot be attributed to a device if it fails")

    # 7. SIM PIN provisioning.
    for idx, step in enumerate(steps):
        if step.get("op") != "lte_sim_pin":
            continue
        has_source = "sim_pin" in _param_keys(db, version)
        if not has_source and not step.get("optional"):
            warnings.append(
                f"step {idx + 1} provisions the SIM PIN but no param set supplies 'sim_pin' — "
                "the operator will be prompted for every unit (mark it optional for PIN-less SIMs)")

    # Cross-cutting: serial ops need an open port.
    monitor_ops = {"command", "set_and_check", "backlog", "berry", "expect", "wait_boot",
                   "poll_until", "download_files", "lte_sim_pin", "reset"}
    open_now = False
    for idx, step in enumerate(steps):
        op = step.get("op")
        if op == "serial_open":
            open_now = True
        elif op == "serial_close":
            open_now = False
        elif op in monitor_ops and not open_now:
            errors.append(
                f"step {idx + 1} ({op}) talks to the device, but no serial port is open at that "
                "point — add serial_open first")
            break
    if not steps:
        errors.append("a deployment version needs at least one step")

    return {"errors": errors, "warnings": warnings, "ok": not errors}
