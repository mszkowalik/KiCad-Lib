#!/usr/bin/env python3
"""Drive a deployment version end-to-end against a SIMULATED device.

Acts as the bench: answers the engine's browser actions (esptool phase) with
success, then replies to every console command the way a Tasmota V2 dongle
would. This proves the procedure actually completes — no hardware needed.

Usage: simulate_bench.py <deployment_version_id> [api]
"""
import asyncio
import json
import re
import sys

import requests
import websockets

API = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8020"
WS = API.replace("http://", "ws://").replace("https://", "wss://")
VERSION = int(sys.argv[1])

MAC = "f8:b3:b7:42:da:f8"
TOPIC = "dongle_F8B3B742DAF8"
# Filled from the deployment's own chip once the run spec arrives, so the
# engine's chip guard is tested rather than tripped by the harness itself.
CHIP_REPORTED = "ESP32-D0WDQ6 (revision 3)"


class FakeDevice:
    """Enough Tasmota to satisfy the V2/V3 procedures."""

    def __init__(self):
        self.settings: dict[str, object] = {}
        self.wifi_on = False
        self.mqtt_count = 0
        self.fs: dict[str, int] = {}
        self.lte_up = 0

    def respond(self, line: str) -> list[str]:
        """Return the console lines a real device would print."""
        cmd, _, payload = line.strip().partition(" ")
        payload = payload.strip()
        key = cmd

        if cmd == "Status":
            if payload == "2":
                return [self._rsl("STATUS2", {"StatusFWR": {
                    "Version": "14.2.0(tasmota)", "Core": "2_0_14",
                    "Hardware": "ESP32-D0WDQ6", "BuildDateTime": "2024-10-25T21:51:49"}})]
            if payload == "11":
                sts = {"StatusSTS": {"UptimeSec": 42, "MqttCount": self.mqtt_count,
                                     "POWER1": "OFF", "Switch7": "ON", "Switch8": "ON",
                                     "Switch9": "ON"}}
                if self.wifi_on:
                    sts["StatusSTS"]["Wifi"] = {
                        "SSId": str(self.settings.get("SSId1", "")), "RSSI": 74,
                        "BSSId": "AA:BB:CC:DD:EE:FF", "Channel": 6}
                return [self._rsl("STATUS11", sts)]
            if payload == "10":
                return [self._rsl("STATUS10", {"StatusSNS": {
                    "Time": "2026-07-29T21:00:00", "Switch7": "ON", "Switch8": "ON",
                    "Switch9": "ON", "DS18B20-1": {"Id": "01191F", "Temperature": 24.3},
                    "LTE": {"Up": self.lte_up, "Iccid": "8948030024031234567",
                            "SimNumber": "", "Oper": "Plus", "RSSI": -71}}})]
            # "Status" / "Status ?"
            return [self._rsl("STATUS", {"Status": {
                "Module": 0, "DeviceName": "Dongle", "Topic": TOPIC,
                "FriendlyName": ["Dongle"], "Power": 0}})]

        if cmd == "LteState":
            self.lte_queries = getattr(self, "lte_queries", 0) + 1
            if not self.wifi_on and self.lte_queries >= 2:
                self.lte_up = 1
            return [self._rsl("RESULT", {"Lte": {
                "Up": self.lte_up, "WantUp": 1, "IP": "10.64.1.23",
                "GW": "10.64.1.1", "Ifname": "pp1", "LastErr": 0}})]

        if cmd == "UrlFetch":
            name = payload.rstrip("/").split("/")[-1]
            self.fs[name] = -1  # size filled from the platform below
            return [self._rsl("RESULT", {"UrlFetch": "Done"}), name]

        if cmd == "Br":
            m = re.search(r'open\("([^"]+)"', payload)
            if m:
                return [self._rsl("RESULT", {"Br": self.fs.get(m.group(1), -1)})]
            return [self._rsl("RESULT", {"Br": "true"})]

        if cmd == "Restart":
            return [self._rsl("RESULT", {"Restart": 1}), "banner"]

        if cmd == "Template":
            if not payload:
                return [self._rsl("RESULT", {"NAME": self.settings.get("Template_NAME", "Dongle")})]
            try:
                name = json.loads(payload).get("NAME", "?")
            except json.JSONDecodeError:
                name = "?"
            self.settings["Template_NAME"] = name
            return [self._rsl("RESULT", {"NAME": name, "GPIO": [1] * 36, "FLAG": 0, "BASE": 1})]

        if cmd == "Module":
            # Real Tasmota answers with the ACTIVE template name keyed by the
            # module number: {"Module":{"0":"CE_Aqua_v2"}} — evidence in the
            # imported logs ("Module successfully set to '{'0': 'CE_Aqua'}'").
            name = str(self.settings.get("Template_NAME", "Dongle"))
            return [self._rsl("RESULT", {"Module": {payload or "0": name}})]

        if cmd in ("Power1", "Power2", "Power3"):
            self.settings[cmd] = payload or "OFF"
            return [self._rsl("RESULT", {cmd: self.settings[cmd]})]

        # Tasmota answers boolean commands with ON/OFF, not the digit it was given.
        if cmd in ("LedPower", "SwitchMode0") or cmd.startswith("SetOption"):
            on = payload in ("1", "ON", "on")
            self.settings[cmd] = "ON" if on else "OFF"
            # SwitchMode0 is echoed under the un-indexed key (the old tool's
            # response_key handling, commit 48ed3fa).
            key = "SwitchMode" if cmd == "SwitchMode0" else cmd
            out = [self._rsl("RESULT", {key: self.settings[cmd]})]
            return out + (["banner"] if cmd.startswith("SetOption") else [])

        if cmd == "SSId1" and payload == "0":
            # Clearing the AP: the device restarts and goes quiet. This is the
            # behaviour config.py wrapped in try/except. On a V3 the WAN
            # failover then carries the link over to LTE (WanBootArm), which is
            # what the LteState poll is waiting for.
            self.settings["SSId1"] = ""
            self.wifi_on = False
            self.lte_up = 1
            return []  # deliberate silence

        if cmd in ("Password1", "SSId1"):
            if payload == "":  # query
                return [self._rsl("RESULT", {cmd: self.settings.get(cmd, "")})]
            self.settings[cmd] = payload
            if cmd == "Password1":
                self.wifi_on = True
            return [self._rsl("RESULT", {cmd: payload}), "banner"]

        if cmd.startswith("Mqtt"):
            if payload == "":  # query
                return [self._rsl("RESULT", {cmd: self.settings.get(cmd, "")})]
            self.settings[cmd] = payload
            if cmd in ("MqttHost", "MqttPort", "MqttUser", "MqttPassword"):
                self.mqtt_count = 1
            return [self._rsl("RESULT", {cmd: payload}), "banner"]

        if cmd == "LteSimPin":
            return [self._rsl("RESULT", {"LteSimPin": "****"})]

        if cmd == "Backlog":
            out, restart = [], False
            for part in payload.split(";"):
                for line in self.respond(part.strip()):
                    if line == "banner":
                        restart = True   # one restart for the whole batch
                    else:
                        out.append(line)
            out.append(self._rsl("RESULT", {"Backlog": "Done"}))
            return out + (["banner"] if restart else [])

        # Anything else: echo, the way Tasmota echoes an accepted command.
        self.settings[key] = payload
        return [self._rsl("RESULT", {key: payload or "Done"})]

    @staticmethod
    def _rsl(tag: str, body: dict) -> str:
        return f"00:00:42.000 RSL: {tag} = {json.dumps(body)}"


async def main():
    run = requests.post(f"{API}/api/flasher/runs", json={
        "deployment_version_id": VERSION, "operator": "simulator",
        "station": "sim"}).json()
    if "run_id" not in run:
        print("could not create the run:", run)
        return 1
    print(f"run {run['run_id']} (draft={run['draft_run']})")

    dev = FakeDevice()
    # The platform's own file sizes, so the size verification passes.
    version = requests.get(f"{API}/api/flasher/deployment-versions/{VERSION}").json()
    sizes = {f["filename"]: f["size_bytes"] for f in version.get("files", [])}
    steps_total = len(version.get("steps", []))
    failures = []

    async with websockets.connect(f"{WS}/api/flasher/ws/{run['run_id']}",
                                  max_size=4 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"t": "hello", "params": {"sim_pin": "1234"},
                                  "client_info": {"user_agent": "simulator"}}))
        while True:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=90))
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                print("  socket ended")
                break
            t = msg.get("t")
            if t == "run":
                chip = (msg["spec"].get("chip") or "").lower()
                if "c6" in chip:
                    globals()["CHIP_REPORTED"] = "ESP32-C6 (QFN40) (revision v0.2)"
            if t == "action":
                info = {}
                if msg["op"] == "esp_connect":
                    info = {"chip": CHIP_REPORTED, "mac": MAC}
                await ws.send(json.dumps({"t": "result", "id": msg["id"], "ok": True, "info": info}))
            elif t == "tx":
                data = str(msg["data"])
                lines = dev.respond(data)
                for line in lines:
                    if line == "banner":
                        await ws.send(json.dumps({"t": "rx", "data":
                            "00:00:00.100 Project dongle - Dongle Version 14.2.0(tasmota)-3_0_4"}))
                        continue
                    if line in sizes or line in dev.fs:
                        dev.fs[line] = sizes.get(line, -1)
                        continue
                    await ws.send(json.dumps({"t": "rx", "data": line}))
            elif t == "prompt":
                await ws.send(json.dumps({"t": "prompt_result", "id": msg["id"], "value": "1234"}))
            elif t == "state":
                if msg["status"] not in ("running", "pass", "skipped"):
                    failures.append(f"step {msg['index'] + 1} {msg['label']}: {msg['status']}")
            elif t == "done":
                print(f"  RESULT: {msg['status']}"
                      + (f" — {msg['error']}" if msg.get("error") else ""))
                break

    detail = requests.get(f"{API}/api/flasher/runs/{run['run_id']}").json()
    done = [s for s in detail["steps"] if s["status"] == "pass"]
    bad = [s for s in detail["steps"] if s["status"] == "fail"]
    print(f"  steps: {len(done)}/{steps_total} passed"
          + (f", FAILED at step {bad[0]['idx'] + 1} ({bad[0]['op']}): {bad[0]['error']}" if bad else ""))
    if detail["results"]:
        keep = {k: v for k, v in detail["results"].items()
                if k in ("topic", "device_name", "fw_version", "mqtt_user", "iccid", "downloaded")}
        print(f"  captured: {keep}")
    return 0 if detail["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
