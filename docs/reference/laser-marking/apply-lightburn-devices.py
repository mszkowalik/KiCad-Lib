#!/usr/bin/env python3
"""Put the M4's two LightBurn profiles into this machine's prefs.ini.

Run with LightBurn CLOSED (it rewrites prefs.ini on exit and would discard this).
Replaces profiles of the same name, keeps every other device, backs up first.
Afterwards, start LightBurn with 'M4 IR 1064nm' selected and set it as the
default device: only the profile LightBurn starts with can connect.

    python3 apply-lightburn-devices.py
"""
import json, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = Path.home() / "Library/Preferences/LightBurn/prefs.ini"

if subprocess.run(["pgrep", "-f", "MacOS/LightBurn"], capture_output=True).returncode == 0:
    sys.exit("LightBurn is running — quit it first")
ours = json.loads((HERE / "lightburn-devices.json").read_text(encoding="utf-8"))["DeviceList"]
names = {x["DisplayName"] for x in ours}
bak = P.with_suffix(".ini.bak-%s" % time.strftime("%Y%m%d-%H%M%S"))
shutil.copy2(P, bak)
prefs = json.loads(P.read_text(encoding="utf-8"))
kept = [x for x in prefs.get("DeviceList", []) if x["DisplayName"] not in names]
prefs["DeviceList"] = kept + ours
prefs["DefaultDevice"] = len(kept) + [x["DisplayName"] for x in ours].index("M4 IR 1064nm")
P.write_text(json.dumps(prefs, indent=4, ensure_ascii=False), encoding="utf-8")
print("backup:", bak)
print("devices:", [x["DisplayName"] for x in prefs["DeviceList"]], "default:", prefs["DefaultDevice"])
