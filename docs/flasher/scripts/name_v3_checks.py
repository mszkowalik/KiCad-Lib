#!/usr/bin/env python3
"""Compose Dongle_V3 v4: the same procedure, with each proving step NAMED.

Naming is what turns a run's timeline into the device view's green/red grid.
Nothing else changes — same firmware, same bundle, same order.
"""
import json
import urllib.request

API = "http://localhost:8020/api/flasher"
FROM = 33  # Dongle_V3 v3

# step index -> check name
NAMES = {
    0: "identity.mac",
    2: "firmware.flash",
    6: "firmware.boot",
    8: "identity.name",
    9: "sim.pin",
    15: "wifi.join",
    17: "berryware.files",
    18: "mqtt.config",
    23: "mqtt.connect",
    29: "lte.failover",
    30: "sim.identity",
    31: "mqtt.lte",
}


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    src = call("GET", f"/deployment-versions/{FROM}")
    steps = json.loads(json.dumps(src["steps"]))
    for idx, name in NAMES.items():
        step = steps[idx]
        step["check"] = name
        print(f"{idx:2} {step['op']:18} {name}")
    body = {"from_version_id": FROM, "steps": steps, "created_by": "claude",
            "comment": "Name what each step proves, so a run fills the device's check grid"}
    made = call("POST", "/deployments/1/versions", body)
    print("draft", made["id"], "v", made["version_no"], "valid:", made["validation"]["ok"],
          made["validation"]["errors"], made["validation"]["warnings"])
    if made["validation"]["ok"]:
        call("POST", f"/deployment-versions/{made['id']}/publish", {"approved_by": "claude"})
        print("published")


main()
