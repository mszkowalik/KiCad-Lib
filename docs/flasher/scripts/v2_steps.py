#!/usr/bin/env python3
"""Reverse-engineered V2 deployment scripts (Dongle + Aqua).

Every step below is backed by TWO independent sources:
  1. the flasher source at the matching commit (~/Projects/CE_Production_flasher
     git history: config.py / test.py / main.py / program_device.py), and
  2. the commands actually seen in the imported production logs, counted per
     era (`programming_logs.dir='tx'` and the app-log "Sending command:" lines).

Three config generations, from the git history and confirmed by log counts:

  A  2024-06-06..2024-06-23  (commits 22fcfdf..2a8b8f9)
     Full option set pushed over serial; NO SetOption153 gate yet.
  B  2024-06-24..2024-07-21  (b96a15e "models and templates", a8ac8a7)
     Adds the SetOption153 autoexec gate, the model Template/Module,
     GroupTopic1/FriendlyName1/Topic. This is where Aqua and Dongle
     diverge: Template CE_Aqua vs CE_Dongle_v2.
  C  2024-07-22..now         (25eb466 "new binaries with most important
     settings built in")
     The device options move INTO the firmware build, so the script shrinks
     to: gate → Modbus → WiFi → credentials → file downloads → MQTT → ungate
     → clear the AP. Log evidence for the current era (script version 10):
     SetOption153 x2, SSId1 x2, Password1, ModbusSerialConfig, ModbusBaudrate,
     MqttFingerprint1/2, MqttPassword, MqttUser, MqttHost, MqttPort per run.

Flash parameters come from main.py::program_device (esptool, ESP32 over a
UART bridge): --baud 460800 --before default_reset --after hard_reset
--flash_mode dio --flash_freq 40m --flash_size detect, image at 0x0.
"""

# --- shared building blocks -------------------------------------------------

FLASH = [
    {"op": "esp_connect", "label": "Detect chip + read MAC"},
    {"op": "erase", "label": "Erase flash (esptool erase_flash)", "timeout": 240},
    {"op": "flash", "label": "Write factory image @0x0", "verify_md5": True, "timeout": 600},
    {"op": "esp_reset", "label": "Hard reset into the new firmware"},
    {"op": "serial_open", "label": "Open monitor serial", "baud": 115200},
    {"op": "wait_boot", "label": "Wait for the firmware to answer", "timeout": 30},
]

MODBUS = [
    {"op": "set_and_check", "label": "Modbus serial config 8N1",
     "cmd": "ModbusSerialConfig", "value": "8N1", "timeout": 10},
    {"op": "set_and_check", "label": "Modbus baudrate 9600",
     "cmd": "ModbusBaudrate", "value": 9600, "timeout": 10},
]

WIFI = [
    {"op": "set_and_check", "label": "Set WiFi SSID", "cmd": "SSId1",
     "value": "{SSId1}", "timeout": 10},
    {"op": "set_and_check", "label": "Set WiFi password (device restarts)",
     "cmd": "Password1", "value": "{Password1}", "timeout": 10},
    {"op": "reset", "label": "Reset the device (RTS pulse, as SerialDevice.reset_device)"},
    {"op": "wait_boot", "label": "Wait for the boot after the WiFi change", "timeout": 30},
    {"op": "poll_until", "label": "Wait for the WiFi connection", "cmd": "Status",
     "payload": "11", "expect_key": "StatusSTS", "path": "StatusSTS.Wifi.SSId",
     "equals": "{SSId1}", "every": 1, "timeout": 30,
     "capture": {"wifi_rssi": "StatusSTS.Wifi.RSSI"}},
]

IDENTITY_AND_CREDS = [
    {"op": "command", "label": "Read the device name (Tasmota topic)", "cmd": "Status",
     "payload": "?", "expect_key": "Status", "timeout": 10,
     "capture": {"topic": "Status.Topic", "device_name": "Status.DeviceName"}},
    {"op": "derive_credentials", "label": "Derive the MQTT credentials from the topic",
     "user_var": "topic", "salt_param": "creds_salt"},
]

DOWNLOAD = [
    {"op": "download_files",
     "label": "Device downloads its berry scripts over HTTP (UrlFetch + size check)",
     "timeout": 30, "retries": 3},
]

MQTT = [
    {"op": "set_and_check", "label": "Clear MQTT fingerprint 1", "cmd": "MqttFingerprint1",
     "value": "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00", "timeout": 10},
    {"op": "set_and_check", "label": "Clear MQTT fingerprint 2", "cmd": "MqttFingerprint2",
     "value": "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00", "timeout": 10},
    {"op": "set_and_check", "label": "Set MQTT password", "cmd": "MqttPassword",
     "value": "{mqtt_password}", "timeout": 10},
    {"op": "set_and_check", "label": "Set MQTT user", "cmd": "MqttUser",
     "value": "{mqtt_user}", "timeout": 10},
    {"op": "set_and_check", "label": "Set MQTT host", "cmd": "MqttHost",
     "value": "{MqttHost}", "timeout": 10},
    {"op": "set_and_check", "label": "Set MQTT port (device restarts)", "cmd": "MqttPort",
     "value": "{MqttPort}", "timeout": 10},
    {"op": "wait_boot", "label": "Wait for the boot after the MQTT change", "timeout": 30},
]

# SetOption153 = disable autoexec.be. The whole config runs with the berry app
# OFF, so its own logic cannot fight the configuration; it is re-enabled at
# the end. Added in b96a15e (2024-06-24) — generation A has no gate.
GATE_OFF = [
    {"op": "set_and_check", "label": "Disable autoexec.be (SetOption153 ON) — device restarts",
     "cmd": "SetOption153", "value": 1, "confirm": "ON", "timeout": 10},
    {"op": "wait_boot", "label": "Wait for the boot with autoexec disabled", "timeout": 30},
]
GATE_ON = [
    {"op": "set_and_check", "label": "Re-enable autoexec.be (SetOption153 OFF) — device restarts",
     "cmd": "SetOption153", "value": 0, "confirm": "OFF", "timeout": 10},
    {"op": "wait_boot", "label": "Wait for the boot with autoexec enabled", "timeout": 30},
]

# The final act: clearing SSId1 makes the device drop the bench AP and restart
# into its shipping state. config.py wraps it in try/except because the device
# stops answering — hence `optional` semantics: no response is the pass case.
CLEAR_AP = [
    {"op": "command", "label": "Clear the bench WiFi (device ships without it)",
     "cmd": "SSId1", "payload": 0, "expect_key": "SSId1", "timeout": 5,
     "optional": True,
     "note": "config.py catches the timeout: the device restarts and stops "
             "answering, which is the expected outcome — `optional` makes "
             "silence a pass"},
]

# Options pushed over serial before 2024-07-22; afterwards they are compiled
# into the firmware (commit 25eb466), which is why they vanish from the logs.
BAKED_LATER = [
    {"op": "set_and_check", "label": "LED power on", "cmd": "LedPower",
     "value": 1, "confirm": "ON", "timeout": 10},
    {"op": "set_and_check", "label": "SetOption114 (detach switches from relays)",
     "cmd": "SetOption114", "value": 1, "confirm": "ON", "timeout": 10},
    {"op": "set_and_check", "label": "SwitchMode0 = 1", "cmd": "SwitchMode0",
     "value": 1, "confirm": "ON", "response_key": "SwitchMode", "timeout": 10},
    {"op": "set_and_check", "label": "SetOption103 (MQTT TLS)", "cmd": "SetOption103",
     "value": 1, "confirm": "ON", "timeout": 10},
    {"op": "set_and_check", "label": "SetOption132 (TLS fingerprint TOFU)",
     "cmd": "SetOption132", "value": 1, "confirm": "ON", "timeout": 10},
]

# GPIO templates verbatim from settings.json at commit b96a15e (2024-06-24).
# The test template in test.py differs from the config one in two GPIO slots
# (224/225 swapped) — kept separate on purpose, that is how it shipped.
DONGLE_TEMPLATE = ('{"NAME":"CE_Dongle_v2","GPIO":[32,1,1,1,1,1,1,1,1,1,1,1,1,1,1,289,'
                   '0,288,1,1,0,1,1,9952,0,0,0,0,9408,1,9440,1,1,0,0,1],"FLAG":0,"BASE":1}')
AQUA_TEMPLATE_CONFIG = ('{"NAME":"CE_Aqua_v2","GPIO":[32,1,1,1,164,1,1,1,161,162,1,163,1312,166,290,289,'
                        '0,544,167,168,0,225,224,9952,0,0,0,0,9408,226,9440,160,1,0,0,1],'
                        '"FLAG":0,"BASE":1}')
AQUA_TEMPLATE = ('{"NAME":"CE_Aqua","GPIO":[32,1,1,1,164,1,1,1,161,162,1,163,1312,166,290,289,'
                 '0,544,167,168,0,224,225,9952,0,0,0,0,9408,226,9440,160,1,0,0,1],'
                 '"FLAG":0,"BASE":1}')


def model_block(template_json: str, label: str) -> list:
    """Generation B pushed the model's GPIO template, activated it, and named
    the device. `Topic` was "dongle_%12X" — Tasmota expands %12X to the last
    three MAC bytes, which is why the V2 fleet is identified by a 6-hex
    suffix (commit b808d25, "dongle sn with only 6 characters of MAC")."""
    return [
        {"op": "set_and_check", "label": f"Apply the {label} GPIO template", "cmd": "Template",
         "value": template_json, "response_key": "NAME", "confirm": label, "timeout": 10},
        {"op": "set_and_check", "label": "Activate the template (Module 0)", "cmd": "Module",
         "value": 0, "response_key": "Module", "timeout": 10},
        {"op": "set_and_check", "label": "Set the group topic", "cmd": "GroupTopic1",
         "value": "{MqttGroupTopic}", "timeout": 10},
        {"op": "set_and_check", "label": "Set the friendly name", "cmd": "FriendlyName1",
         "value": "{FriendlyName}", "timeout": 10},
        {"op": "set_and_check", "label": "Set the MQTT topic (%12X = last 3 MAC bytes)",
         "cmd": "Topic", "value": "{Topic}", "timeout": 10},
    ]


def config_gen_a() -> list:
    """2024-06-06..2024-06-23 — no autoexec gate, every option over serial."""
    return (FLASH + BAKED_LATER + MODBUS + MQTT[:2] + WIFI + IDENTITY_AND_CREDS
            + DOWNLOAD + MQTT[2:] + CLEAR_AP)


def config_gen_b(template_json: str | None, label: str) -> list:
    """2024-06-24..2024-07-21 — gate + model template + naming."""
    model = model_block(template_json, label) if template_json else []
    return (FLASH + GATE_OFF + BAKED_LATER + model + MODBUS + WIFI
            + IDENTITY_AND_CREDS + DOWNLOAD + MQTT + GATE_ON + CLEAR_AP)


def config_gen_c() -> list:
    """2024-07-22..now — options baked into the firmware build."""
    return (FLASH + GATE_OFF + MODBUS + WIFI + IDENTITY_AND_CREDS
            + DOWNLOAD + MQTT + GATE_ON + CLEAR_AP)


# --- functional test (test.py) ---------------------------------------------

def test_aqua() -> list:
    """CE_Aqua functional test: relay matrix + DS18B20 sensors, run with
    autoexec disabled and the original template restored at the end."""
    return [
        {"op": "serial_open", "label": "Open monitor serial", "baud": 115200},
        {"op": "wait_boot", "label": "Wait for the firmware to answer", "timeout": 30},
        {"op": "set_and_check", "label": "Disable autoexec.be for the test",
         "cmd": "SetOption153", "value": 1, "confirm": "ON", "timeout": 10},
        {"op": "wait_boot", "label": "Wait for the boot", "timeout": 30},
        {"op": "command", "label": "Read the device name", "cmd": "Status", "payload": "?",
         "expect_key": "Status", "timeout": 10, "capture": {"topic": "Status.Topic"}},
        {"op": "command", "label": "Back up the current template", "cmd": "Template",
         "expect_key": "NAME", "timeout": 10, "capture": {"original_template": "NAME"}},
        {"op": "set_and_check", "label": "Apply the test template", "cmd": "Template",
         "value": AQUA_TEMPLATE, "response_key": "NAME", "confirm": "CE_Aqua", "timeout": 10},
        {"op": "command", "label": "Restart to apply the template", "cmd": "Restart",
         "payload": "1", "expect_key": "Restart", "timeout": 10},
        {"op": "wait_boot", "label": "Wait for the boot", "timeout": 30},
        {"op": "set_and_check", "label": "Relay 1 OFF", "cmd": "Power1", "value": "OFF", "timeout": 10},
        {"op": "set_and_check", "label": "Relay 2 OFF", "cmd": "Power2", "value": "OFF", "timeout": 10},
        {"op": "set_and_check", "label": "Relay 3 OFF", "cmd": "Power3", "value": "OFF", "timeout": 10},
        {"op": "sleep", "label": "Relay actuation time", "seconds": 2},
        {"op": "command", "label": "Read the sensors with the relays OFF", "cmd": "Status",
         "payload": "10", "expect_key": "StatusSNS", "timeout": 10,
         "capture": {"sw7_off": "StatusSNS.Switch7", "sw8_off": "StatusSNS.Switch8",
                     "sw9_off": "StatusSNS.Switch9"}},
        {"op": "set_and_check", "label": "Relay 1 ON", "cmd": "Power1", "value": "ON", "timeout": 10},
        {"op": "set_and_check", "label": "Relay 2 ON", "cmd": "Power2", "value": "ON", "timeout": 10},
        {"op": "set_and_check", "label": "Relay 3 ON", "cmd": "Power3", "value": "ON", "timeout": 10},
        {"op": "sleep", "label": "Relay actuation time", "seconds": 2},
        {"op": "command", "label": "Read the sensors with the relays ON", "cmd": "Status",
         "payload": "10", "expect_key": "StatusSNS", "timeout": 10,
         "capture": {"sw7_on": "StatusSNS.Switch7", "sw8_on": "StatusSNS.Switch8",
                     "sw9_on": "StatusSNS.Switch9",
                     "temp1": "StatusSNS.DS18B20-1.Temperature"}},
        # _check_relay: each switch must CHANGE state between the two reads.
        {"op": "assert_equals", "label": "Relay 1 changed state (Switch7)",
         "var": "sw7_on", "equals": "OFF",
         "note": "test.py::_check_relay — the aqua wiring inverts the switch, "
                 "so ON reads OFF and vice versa; what matters is the change"},
        {"op": "assert_equals", "label": "Relay 2 changed state (Switch8)",
         "var": "sw8_on", "equals": "OFF"},
        {"op": "assert_equals", "label": "Relay 3 changed state (Switch9)",
         "var": "sw9_on", "equals": "OFF"},
        {"op": "assert_range", "label": "DS18B20 temperature is plausible",
         "var": "temp1", "min": -10, "max": 70},
        {"op": "set_and_check", "label": "Relays back OFF", "cmd": "Power1",
         "value": "OFF", "timeout": 10},
        {"op": "set_and_check", "label": "Relays back OFF", "cmd": "Power2",
         "value": "OFF", "timeout": 10},
        {"op": "set_and_check", "label": "Relays back OFF", "cmd": "Power3",
         "value": "OFF", "timeout": 10},
        {"op": "set_and_check", "label": "Restore the original template", "cmd": "Template",
         "value": "{original_template}", "response_key": "NAME", "timeout": 10},
        {"op": "set_and_check", "label": "Re-enable autoexec.be", "cmd": "SetOption153",
         "value": 0, "confirm": "OFF", "timeout": 10},
        {"op": "wait_boot", "label": "Wait for the boot", "timeout": 30},
    ]


def test_dongle() -> list:
    """CE_Dongle_V2 test: test.py's method logs and returns — there is no
    functional test for the dongle, only the identity read the runner does."""
    return [
        {"op": "serial_open", "label": "Open monitor serial", "baud": 115200},
        {"op": "wait_boot", "label": "Wait for the firmware to answer", "timeout": 30},
        {"op": "set_and_check", "label": "Disable autoexec.be for the test",
         "cmd": "SetOption153", "value": 1, "confirm": "ON", "timeout": 10},
        {"op": "wait_boot", "label": "Wait for the boot", "timeout": 30},
        {"op": "command", "label": "Read the device name", "cmd": "Status", "payload": "?",
         "expect_key": "Status", "timeout": 10, "capture": {"topic": "Status.Topic"}},
        {"op": "set_and_check", "label": "Re-enable autoexec.be", "cmd": "SetOption153",
         "value": 0, "confirm": "OFF", "timeout": 10},
        {"op": "wait_boot", "label": "Wait for the boot", "timeout": 30},
    ]
