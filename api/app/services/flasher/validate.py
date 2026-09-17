"""Publish gates for a deployment version.

Every check here exists because the mistake it catches is cheap to make and
expensive to discover on a bench full of devices. `check()` returns errors
(publishing is refused) and warnings (publishing is allowed, the UI shows
them), and the composer calls the same function live while you edit — one
implementation, so the editor can never disagree with the publish button.
"""
from __future__ import annotations

import re

from ... import models as M
from . import bundle, params as params_svc

# `PLACEHOLDER` and the string walker live in `params.py` — the same walk
# decides what a version DECLARES, and two copies would drift.
PLACEHOLDER = params_svc.PLACEHOLDER

# Transport profiles and the chips they are valid for. Native USB-Serial/JTAG
# exists only on the C/S families; picking it for a plain ESP32 means the
# monitor phase would never touch DTR/RTS on a part that NEEDS them.
NATIVE_USB_CHIPS = ("esp32c3", "esp32c6", "esp32s2", "esp32s3", "esp32h2")

# Ops the engine runs in the browser, i.e. the flash phase.
FLASH_OPS = {"erase", "flash", "esp_reset", "await_reenumerate"}

# Names an op supplies to its OWN url template, once per item it fetches. They
# are not run variables — no parameter defines them and no step captures them —
# so the dataflow check below would otherwise reject a step that uses them
# correctly. Add a row here in the same change that adds a url template to an op
# (see `RunEngine._url`).
OP_LOCAL_VARS = {"download_files": {"file_version_id", "filename"}}

# What esptool-js accepts for the three flash parameters (its own
# `types/arguments.d.ts`). A value outside these lists is not a preference the
# bench can interpret — it throws mid-run, after the erase has already wiped the
# device. `size: "detect"` IS accepted, but only because `Station.espFlash`
# resolves it before esptool-js sees it; read the comment there before changing
# either side.
FLASH_SIZES = {"detect", "keep", "256KB", "512KB", "1MB", "2MB", "2MB-c1",
               "4MB", "4MB-c1", "8MB", "16MB", "32MB", "64MB", "128MB"}
FLASH_MODES = {"keep", "dio", "qio", "dout", "qout"}
FLASH_FREQS = {"keep", "80m", "60m", "48m", "40m", "30m", "26m", "24m", "20m",
               "16m", "15m", "12m"}

# A literal loopback host in a url template. The device fetches over WiFi, so
# this is not a value that might work — it is one that cannot.
LOOPBACK_URL = re.compile(r"//(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])", re.I)


def _norm_chip(s: str) -> str:
    return (s or "").lower().replace("-", "").replace(" ", "").replace("_", "")


def _addr(a: str) -> int | None:
    try:
        return int(a, 16)
    except (TypeError, ValueError):
        return None


def check(db, version: M.DeploymentVersion) -> dict:
    """Return {"errors": [...], "warnings": [...], "ok": bool}."""
    errors: list[str] = []
    warnings: list[str] = []
    deployment = db.get(M.Deployment, version.deployment_id)
    steps = version.steps or []
    ops = [s.get("op") for s in steps]

    # 0. Flash parameters the bench can actually use. Wrong here means the run
    #    dies in the browser AFTER the erase step, with the device blank.
    for key, allowed in (("size", FLASH_SIZES), ("mode", FLASH_MODES),
                         ("freq", FLASH_FREQS)):
        value = (version.flash_config or {}).get(key)
        if value is not None and value not in allowed:
            errors.append(
                f"flash {key} '{value}' is not one esptool understands "
                f"({', '.join(sorted(allowed))})")

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
        if not img.asset.flashable:
            errors.append(
                f"{img.asset.filename} is not a writable ESP image — it is a placeholder or "
                "truncated upload, and flashing it would brick the device"
                + (f" ({img.asset.notes.split(';')[0]})" if img.asset.notes else ""))
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
    available = set(bundle.RUNTIME_VARS) | params_svc.available_keys(db, version)
    for idx, step in enumerate(steps):
        local = OP_LOCAL_VARS.get(step.get("op"), set())
        url = step.get("url")
        if isinstance(url, str) and LOOPBACK_URL.search(url):
            errors.append(
                f"step {idx + 1} ({step.get('op')}) hardcodes a loopback host in its "
                "url — no device can reach it; use {base_url}")
        for text in params_svc._walk_strings({k: v for k, v in step.items()
                                   if k not in ("label", "note", "capture")}):
            for name in PLACEHOLDER.findall(text):
                if name not in available and name not in local:
                    errors.append(
                        f"step {idx + 1} ({step.get('op')}) uses {{{name}}}, which no parameter "
                        "defines and no earlier step captures")
        var = step.get("var")
        if var and var not in available:
            errors.append(
                f"step {idx + 1} ({step.get('op')}) asserts on '{var}', which no earlier step "
                "captures")
        # An op that reads a parameter by NAME rather than interpolating it.
        # The walk above cannot see these: `derive_credentials` takes the salt
        # straight out of the run's variables and raises mid-run without it, so
        # a version missing `creds_salt` published cleanly and failed at the
        # bench after the erase (found 2026-09-17).
        for field, default in params_svc.OP_PARAM_FIELDS.get(step.get("op"), []):
            name = str(step.get(field) or default)
            if name not in available:
                errors.append(
                    f"step {idx + 1} ({step.get('op')}) needs the '{name}' parameter, which no "
                    "parameter set or default supplies")
        available |= set((step.get("capture") or {}).keys())
        if step.get("op") == "derive_credentials":
            available |= {"mqtt_user", "mqtt_password"}
        if step.get("op") == "esp_connect":
            available |= {"mac", "serial", "chip"}

    # 5. Downloads: need pinned files, and autoexec.be must come last.
    if "download_files" in ops and not version.files:
        errors.append("the procedure downloads files, but this version pins no berryware")
    if version.files and "download_files" not in ops and "mark_laser" not in ops:
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

    # 7. Laser marking. The template is a pinned file like berryware is, so the
    #    version still answers "what did this unit get" on its own.
    pinned_names = [f.file_version.file.filename for f in version.files]
    for idx, step in enumerate(steps):
        if step.get("op") != "mark_laser":
            continue
        if not version.files:
            errors.append(f"step {idx + 1} marks, but this version pins no template file")
            continue
        named = str(step.get("template") or "")
        if named and named not in pinned_names:
            errors.append(
                f"step {idx + 1} names template {named!r}, which this version does not pin "
                f"({', '.join(pinned_names)})")
        elif not named and len(version.files) > 1:
            errors.append(
                f"step {idx + 1} does not name a template, but this version pins "
                f"{len(version.files)}: {', '.join(pinned_names)}")
        if not step.get("start", True):
            warnings.append(
                f"step {idx + 1} loads the job but never starts it — the operator has to press "
                "Start in LightBurn, and the run cannot prove the part was marked")
        if not str(step.get("value", "{mac}")).strip():
            errors.append(f"step {idx + 1} has nothing to engrave")
    if "mark_laser" in ops and (version.deployment.kind or "flash") != "mark":
        warnings.append(
            'this procedure marks, but its deployment kind is not "mark" — the bench offers it '
            "on the flashing page rather than the marking page")

    # 7b. Labels. No pinned file, unlike the laser: a Code 128 label has no
    #     artwork, and its geometry comes from the printer's own PPD on the
    #     bench. What the version owns is WHAT GOES ON IT, which is this step.
    for idx, step in enumerate(steps):
        if step.get("op") != "print_label":
            continue
        if not str(step.get("value", "{mac}")).strip():
            errors.append(f"step {idx + 1} has nothing to print")
        dots = step.get("dots")
        if dots is not None and not 2 <= int(dots) <= 8:
            errors.append(
                f"step {idx + 1} asks for a {dots}-dot module. Two dots at 300 dpi is already "
                "0.169 mm, below the 0.25 mm a Code 128 scanner is entitled to expect, and "
                "eight is wider than any roll we stock")
        if int(step.get("copies") or 1) > 1 and not step.get("label"):
            warnings.append(
                f"step {idx + 1} prints {step.get('copies')} labels and has no label text — "
                "the run log will not say why a unit got more than one")
    if "print_label" in ops and (version.deployment.kind or "flash") != "mark":
        warnings.append(
            'this procedure prints a label, but its deployment kind is not "mark" — the bench '
            "offers it on the flashing page rather than the marking page")

    # 8. SIM PIN provisioning.
    for idx, step in enumerate(steps):
        if step.get("op") != "lte_sim_pin":
            continue
        has_source = "sim_pin" in params_svc.available_keys(db, version)
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
