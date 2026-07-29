# Production flasher on the platform — verification + migration plan

Migrating `~/Projects/CE_Production_flasher` (Tkinter + esptool + pyserial on the
operator's PC) into the 7Sigma platform as a web-based, multi-station production
programmer with every device conversation stored in Postgres.

Status: **web-only path proven on real hardware** — a CE_Dongle_V3 (ESP32-C6)
was erased, flashed (factory + LittleFS, MD5-verified), reset, booted and
configured entirely from Chrome in 66.5 s, unattended (§1, §7). Laser marking is
researched and prototyped against the real LightBurn (§10). Nothing has been
implemented in `api/` or `web/` yet — this document is the proposal.

---

## 1. Verification: can the browser do it alone?

### Measured on this machine (Chrome 150, macOS, 10 cores)

| Question | Result | How it was checked |
|---|---|---|
| Web Serial available | yes — `requestPort`, `getPorts`, `setSignals`, `getSignals`, `forget` | `clients/flasher-poc/probe.js`, headless Chrome |
| Handshake-line control (DTR/RTS) — needed for reset/boot strapping | yes, `SerialPort.setSignals()` | same |
| Web Serial inside a **DedicatedWorker** | **yes** (`getPorts` works, `requestPort` does not — needs user activation) | same |
| Ports remembered across reloads without re-picking | yes — `getPorts()` returns previously granted ports | same |
| ESP ROM protocol from JS | yes — `esptool-js` 0.6.0: `main()` (detect + stub + baud change), `eraseFlash()`, `writeFlash()` with deflate + **MD5 verify**, `after("hard_reset")` | read the shipped implementation, not the docs |
| ESP32-C6 native USB reset | handled — `UsbJtagSerialReset` auto-selected on PID `0x1001`, or forced with `before: "usb_reset"` | read `esptool-js/lib/reset.js` + `constructResetSequence()` |
| Tasmota dialog + verification logic in JS | yes — 37/37 checks against the **real** recorded serial output, plus the C6 flash map cross-checked against the firmware project's partition CSV | `npm test` in `clients/flasher-poc` |
| Multi-image flash in one session (C6 factory + LittleFS) | yes — `writeFlash({fileArray:[…]})` | `station.js::espFlash` |
| 5 stations in parallel | architecturally clear: 5 ports + 1 worker each, 10 cores available | worker probe above |

### Proven on hardware (2026-07-26): a full CE_Dongle_V3 cycle in 66.5 s

Unattended, from Chrome: detect ESP32-C6 rev 2 (MAC `58:8c:81:2f:74:74`) → erase
19.6 s → write factory 2.4 MB @0x0 + LittleFS 3.4 MB @0x4B0000, both MD5-verified,
42.1 s → hard-reset pulse → USB re-enumerate 2.0 s → open monitor → firmware
answered on the first probe → `Status 2`/`Status 0` captured
(`15.5.0(tasmota)`, `ESP32-C6 v0.2`, topic `dongle_588C812F7474`) →
`FriendlyName1` set and verified. Details and the two bugs it exposed: §7.

Still open: the 5-station parallel measurement (needs ≥2 adapters plugged in).

To run it yourself:

```bash
cd clients/flasher-poc && npm install
cp ~/Projects/CE_Production_flasher/binaries/*.bin public/firmware/
npm run dev      # http://127.0.0.1:5174 in Chrome
```

Pick the scenario, **Connect port…**, **Run scenario**. It erases, flashes with
MD5 verification, hard-resets, reopens at 115200, waits for the boot banner,
reads `Status 2` / `Status 0`, sets `FriendlyName1` and verifies the readback.
Then plug in a second adapter, `+ Station`, and hit **Run on all ready stations**
to see parallel behaviour. **Download run JSON** captures the evidence.

Scenarios shipped in the harness:

| Scenario | Target | What it does |
|---|---|---|
| `CE_Dongle_V2` / `CE_Aqua_V2` | ESP32, UART bridge | erase → factory image @0x0 → reset → Tasmota dialog |
| `CE_Dongle_V3` blank device | **ESP32-C6**, native USB | erase → factory @0x0 **+ LittleFS @0x4B0000** → reset → re-enumerate → Tasmota dialog |
| `CE_Dongle_V3` app-only | ESP32-C6, native USB | app @0xE0000 only, no erase → keeps `/.settings` and the FS |
| `Monitor only` | anything already running | opens the port and talks Tasmota, **erases nothing** |

For the ESP32-C6, run **`Monitor only` first**: it attaches without erasing, so
you can confirm the handshake-line handling does not reboot a running device
before risking a flash cycle. Watch the log line about handshake lines — the C6
profile leaves DTR/RTS **untouched** on purpose (§7).

### Automating the browser leg (for regression testing)

Chrome's port picker needs a user gesture, and **CDP cannot answer it**: the
`DeviceAccess` domain exists on the page session but never emits
`deviceRequestPrompted` for Web Serial (measured — `requestPort()` rejects with
`NotFoundError: No port selected by the user`), so it only covers Bluetooth.
Two ways to get unattended runs anyway:

1. **One click per automation profile.** Launch Chrome with a dedicated
   `--user-data-dir`, click *Connect port…* once; the grant persists per origin,
   so every later run picks the port up from `getPorts()` with no interaction.
   `scratchpad/cdp/run.mjs` already drives everything else over CDP.
2. **`SerialAllowAllPortsForUrls` policy** for the bench origin — zero clicks,
   but it is an enterprise policy on the machine (and on macOS the reliable path
   writes to `/Library/Managed Preferences`, i.e. sudo).

For the production bench itself neither is needed: an operator picks each of the
5 ports once and Chrome remembers them.

### Known limits of web-only (decide with eyes open)

1. **Chromium only.** Chrome/Edge/Brave desktop. No Safari, no Firefox, no iPad.
2. **Secure context.** `localhost` or HTTPS. The platform is served over plain
   HTTP on the LAN today — that must become HTTPS (or the bench uses an SSH
   tunnel / `localhost` port-forward) before Web Serial works off-machine.
3. **One click per port, once.** The port picker needs a user gesture; after that
   the grant persists per origin, so a bench of 5 adapters is picked once.
4. **Native-USB re-enumeration.** A C6 that reboots drops off the USB bus; the
   `SerialPort` handle dies and must be re-acquired (`await_reenumerate` step).
   On a UART bridge this never happens.
5. **Laser marking is only half browser-doable.** Generating the job and getting
   it *loaded* into LightBurn works from the browser alone (download +
   file association), but pressing `START` cannot: no UDP from JS, no HTTP/WS in
   LightBurn, no URL scheme. Either the operator presses Start, or the backend
   does it over LAN UDP. Both are designed in §10.

---

## 2. Where the pieces live

| Piece | Location | Notes |
|---|---|---|
| Scenario engine, step implementations, Tasmota protocol | `api/app/services/flasher/` (`engine.py`, `steps.py`, `tasmota.py`, `credentials.py`) | ports `tasmota.py` + `serial_device.py` + `config.py` + `test.py` |
| HTTP + WebSocket endpoints | `api/app/routers/flasher.py` | thin: parse → service, per the api conventions |
| Tables | `api/app/models.py` | §4 |
| Firmware binaries | MinIO via `services/storage.py` | keys `firmware/<asset_id>/<filename>` |
| Secrets (WiFi pw, creds salt, MQTT pw) | encrypted with `services/crypto.py` (Fernet from `SECRET_KEY`) | never in a scenario JSON, never in git |
| Operator bench UI | `web/src/pages/FlashBench.tsx` | up to 5 station columns, live log, PASS/FAIL |
| Scenario + firmware admin | `web/src/pages/FlashScenarios.tsx` | step editor, firmware upload, param sets |
| Run history | project page tab + `web/src/pages/FlashRuns.tsx` | filter by project/device/status, drill into logs |
| Browser-side serial + esptool | `web/src/flasher/` (worker per station) | lifted from `clients/flasher-poc` |

Scenarios attach to a **platform `Project`** — the same projects that already
carry BOMs and production runs — so a flashed device is traceable to the design
revision and (optionally) to the `ProductionRun` it was built for.

---

## 3. Execution split — the one real design decision

Two defensible architectures; recommending a **hybrid**, split by phase:

| Phase | Runs where | Why |
|---|---|---|
| **ROM bootloader** (detect, erase, write, verify, reset) | **Browser**, esptool-js | Thousands of latency-sensitive SLIP round trips plus DTR/RTS timing. Piping that over a WebSocket to Python is fragile and buys nothing — esptool-js exists precisely for this. Progress + terminal output stream to the API as they happen. |
| **Tasmota dialog** (commands, waits, asserts, config, credentials, file downloads) | **Backend**, browser is a dumb byte pipe over WebSocket | Line-based and latency-tolerant (5–30 s timeouts). Keeps ONE implementation of the scenario logic (Python, reusing the existing code), writes every line into Postgres *as it arrives* — nothing is lost if the tab closes — and lets Jaravis read/analyse runs later. |

This is what the old `REQUIREMENTS.md` on the `web_ui` branch intended ("act as
a dumb pipe"), except that branch never got there: the browser was an admin UI
and a local Python agent still did the flashing. The hybrid removes the agent.

### WebSocket protocol sketch (`/api/flasher/ws/{run_id}`)

```
browser → server   {t:"hello", scenario_version_id, station, port_info, chip, mac}
server  → browser  {t:"action", id, kind:"erase"|"flash"|"reset"|"reenumerate"|"open"|"close",
                    args:{firmware_url, address, flash_mode, freq, size, baud, before, after}}
browser → server   {t:"progress", id, written, total} | {t:"log", dir:"esptool", lines:[…]}
browser → server   {t:"result", id, ok, error?, info?:{chip, mac, md5}}
server  → browser  {t:"tx", data:"Status 2\n"}          # dialog phase
browser → server   {t:"rx", data:"…RSL: STATUS2 = {…}"}  # raw, server does the parsing
server  → browser  {t:"state", step, index, total, status}
server  → browser  {t:"done", status:"pass"|"fail", error?, results:{…}}
```

Every `tx`/`rx`/`log` is appended to `flash_run_logs` with a server timestamp and
a sequence number, so the stored log is complete and ordered even across
reconnects. A dropped socket marks the run `aborted` after a grace period; the
browser can reconnect to the same `run_id` and continue.

---

## 4. Data model

Append-only where it matters; new tables in `api/app/models.py`:

```
flash_scenarios              id, project_id→projects, name, chip, description,
                             current_version_id (Integer, not FK — platform pattern),
                             created_at
flash_scenario_versions      id, scenario_id, version_no, status ('draft'|'published'|
                             'rejected'), created_by, approved_by, comment, created_at,
                             transport_profile, flash_config JSONB, monitor_baud,
                             steps JSONB           -- the ordered step list (§5)
flash_param_sets             id, project_id, name ('production'|'bench'|…),
                             values_enc TEXT       -- Fernet-encrypted JSON
                                                   -- SSID/password, MqttHost/Port,
                                                   -- creds_salt, base_url, …
firmware_assets              id, project_id, filename, version, chip, size,
                             sha256, storage_key, uploaded_at, uploaded_by,
                             kind ('factory'|'app'|'filesystem'|'safeboot'),
                             default_address   -- e.g. 0x0 / 0xE0000 / 0x4B0000
device_units                 id, project_id, mac UNIQUE, chip, first_seen, last_seen,
                             last_status, notes          -- identity = the ESP MAC
flash_runs                   id, scenario_version_id, device_unit_id, project_id,
                             production_run_id NULL→production_runs,
                             operator, station_index, status ('running'|'pass'|'fail'|
                             'aborted'), started_at, finished_at, duration_ms, error,
                             results JSONB,              -- captured values
                             params_snapshot JSONB,      -- what was ACTUALLY applied
                                                         -- (secrets masked)
                             firmware_asset_id, firmware_sha256, flash_md5,
                             client_info JSONB           -- UA, port USB ids
flash_run_steps              id, run_id, index, op, label, status, started_at,
                             duration_ms, error, response JSONB
flash_run_logs               id, run_id, seq, ts, device_ts, dir ('tx'|'rx'|'app'|
                             'err'|'esptool'), text      -- index (run_id, seq)
device_credentials           id, device_unit_id, kind ('mqtt'), username,
                             secret_enc, hash_line_enc, issued_at, scenario_run_id
```

Notes:

- **`device_credentials` replaces `mosquitto_passwords.txt`.** One row per
  device instead of an append-only text file that lives outside git; encrypted at
  rest; an export endpoint regenerates the mosquitto password file for a project
  or a date range.
- **`params_snapshot`** is the REQUIREMENTS' "settings snapshot": the merged
  release + param-set values actually pushed, with secrets masked — so a run can
  be audited without exposing passwords.
- Scenario versions carry a `status` and `approved_by`, i.e. the platform's
  existing draft→published shape. Whether editing a production scenario must go
  through the Proposals view is a decision for you (§10).

---

## 5. Scenario language

Verified vocabulary (implemented and tested in the PoC):

| Op | Args | Ported from |
|---|---|---|
| `esp_connect` | — | `program_device.py` (chip detect) |
| `erase` | — | `erase_device.py` |
| `flash` | `files: [{firmware, address}]` (or single `firmware`+`address`), `verify_md5` | `program_device.py`, `pio-tools/ce_flash_fs.py` |
| `esp_reset` | — | esptool `--after hard_reset` |
| `await_reenumerate` | `timeout` | **new** — ESP32-C6 native USB |
| `serial_open` / `serial_close` | `baud` | `SerialDevice.initialize/shutdown` |
| `reset` | — | `SerialDevice.reset_device` (RTS pulse / USB-JTAG sequence) |
| `wait_boot` | `timeout`, `pattern` | `Tasmota.wait_for_device_boot` (a fixed `sleep(4)` today — now an actual boot-marker wait) |
| `command` | `cmd`, `payload`, `expect_key`, `timeout`, `capture` | `SerialDevice.send_command*` |
| `set_and_check` | `cmd`, `value`, `confirm`, `response_key` | `Tasmota.set_and_check` |
| `expect` | `pattern`, `timeout` | — |
| `assert_equals` / `assert_range` | `var`\|`path`, `equals`\|`min`/`max` | the `assert`s in `test.py` |
| `sleep` | `seconds` | `asyncio.sleep` |

Still to add for full parity with the Python (straightforward, backend-side):

| Op | Args | Ported from |
|---|---|---|
| `backlog` | `commands[]` | `scenarios/config/ce_universal.py` (Backlog batching) |
| `derive_credentials` | `from_var`, `salt_ref`, `store` | `hash_password.py` + the MQTT creds block |
| `download_files` | `base_url`, `files[]`, `verify_size` | the `UrlFetch` + `file_size` loop |
| `berry` | `code` | `Tasmota.file_delete_berry` / `list_dir` |
| `wait_wifi` | `ssid`, `timeout` | `wifi_status` + `wait_for` |
| `template_set` / `template_restore` | `template` | `test.py` backup/restore around the relay test |
| `capture_sensors` | `prefix`, `assert_range` | the DS18B20 loop in `test.py` |
| `relay_check` | `switch`, `on`, `off` | `_check_relay` |
| `push_fs_files` | `files[]`, `chunk`, `prune` | `CE_Dongle_v3_board/firmware/tools/push_fs_serial.py` — base64 through `Br`, preserves `/.settings` (needed to update a *configured* C6, see §7) |

Values interpolate `{placeholders}` from the param set and from earlier captures
(`{mac}`, `{topic}`, `{mqtt_password}`), which is how the ad-hoc string building
in `config.py` becomes data instead of code.

---

## 6. Five devices at once

- One **Web Worker per station**, each calling `navigator.serial.getPorts()` to
  get its own `SerialPort` (verified available in workers) — flashing 5 devices
  never blocks the UI thread, and each station's CPU work (deflate + MD5) lands
  on its own core.
- One WebSocket and one `flash_run` row per station; `asyncio` on the API side
  handles 5 concurrent dialogs trivially.
- Stations are **positional slots** persisted in `localStorage` (matching the
  physical bench layout) and keyed to the port's USB ids, replacing the
  hardcoded per-host `programming_ports` in `settings.json`. Unplug → the slot
  greys out; plug in → it re-attaches (`navigator.serial` connect/disconnect
  events, already wired in the PoC).
- Optional stagger: start flashes ~1 s apart so five 460800-baud writes don't
  peak the USB controller at once. Measure first, then decide.

---

## 7. ESP32-C6 and ESP32 — the transport rules (hard requirement)

Both **ESP32** and **ESP32-C6** are targets from now on, and they need different
handshake-line handling. The C6's built-in USB-Serial/JTAG peripheral has no
external auto-reset circuit: it *emulates* one, and **resets the chip when
DTR=0 while RTS=1**.

The decisive evidence is in the CE_Dongle_v3 project's own
`firmware/tools/push_fs_serial.py`, which documents a bug it had to fix:
pyserial applies DTR before RTS, so "clear both lines on open" stepped through
`(DTR=0, RTS=1)` and **rebooted the device on every single connect**. Its fix
was to leave DTR/RTS asserted and attach to the running device.

Therefore, in monitor mode on native USB the rule is: **do not call
`setSignals()` at all.** Chrome's line state after `port.open()` is not
specified and a two-line change is not guaranteed atomic, so the only safe
option is not to touch them. During *flashing* esptool-js drives the lines
deliberately (a reset is the point) using the USB-JTAG sequence.

Rules the implementation must keep (encoded as `TRANSPORT_PROFILES` in
`clients/flasher-poc/scenario.js`, asserted by `npm test`):

| | External USB-UART bridge (CP210x/CH340/FTDI) | ESP32-C6 built-in USB-Serial/JTAG |
|---|---|---|
| Detect | any other USB VID/PID | VID `0x303a`, PID `0x1001` |
| Connect reset | `default_reset` → esptool-js `ClassicReset` | `usb_reset` → `UsbJtagSerialReset` |
| Flash baud | raise it (460800) | leave 115200 — CDC ignores baud; changing it only forces a needless port re-open |
| Monitor open | set `{DTR:false, RTS:false}` (releases EN/IO0) | **never call `setSignals`** — see above (`usb_serial_jtag_deassert` exists only to measure whether a single Chrome call is atomic; not for production) |
| Reset while monitoring | pulse RTS (EN) | USB-JTAG sequence → close → `await_reenumerate` → reopen |
| After a chip reset | port handle stays valid | USB device disappears and returns → re-acquire the `SerialPort` via the `connect` event, then confirm it is openable |

### CE_Dongle_V3 flash map (verified against the project's partition CSV)

`firmware/partitions/esp32c6_partition_8MB_app3904k_fs3392k.csv`, 8 MB flash,
`qio` / 80 MHz baked into the image header by PlatformIO (so the scenario passes
`mode/freq/size = "keep"` and esptool-js patches nothing):

| Offset | Partition | Production write |
|---|---|---|
| `0x000000` | bootloader + partition table + safeboot + app0 | `tasmota32c6-CE_DONGLE_V3.factory.bin` |
| `0x0E0000` | `app0` (3904 k) | app-only update path — **preserves settings + FS** |
| `0x4B0000` | `spiffs` = LittleFS (0x350000 = 3 473 408 B) | `ce_littlefs.bin` built from `firmware/fs/` |

Two consequences that make the C6 scenario differ from the V2 ESP32 one, even
though the *device config dialogue is the same*:

1. **The factory image ships an EMPTY LittleFS** (`custom_files_upload =
   no_files`), so a blank production device needs the populated filesystem image
   flashed as a second file — exactly what the project's own
   `pio-tools/ce_flash_fs.py` "Flash factory + filesystem" task does. This
   replaces V2's `UrlFetch` download loop: the Berry scripts arrive by flash,
   not over WiFi.
2. **This firmware stores Tasmota's whole Settings blob on LittleFS**
   (`/.settings`), so writing the FS image resets all configuration. That is
   correct for a blank device and *wrong* for a configured field unit — hence
   the separate app-only scenario. A future `push_fs_files` step can port
   `push_fs_serial.py` (it streams base64 chunks through `Br` Berry calls, ≤800
   chars per console line, and never touches `/.settings`) so the platform can
   update scripts on a configured device from the browser too.

Also worth carrying over: `provision.be` self-heals the template and SetOptions
at boot, so the scenario does not need to push the GPIO template the way
`test.py` did for the V2 Aqua.

### Measured on a real CE_Dongle_V3 (2026-07-26)

The browser (Chrome, esptool-js over Web Serial) flashed the C6 correctly on the
first try — `factory.bin` @0x0 **and** `ce_littlefs.bin` @0x4B0000, both
MD5-verified against flash — but the run then failed at "wait for boot" with
zero bytes received. Two separate causes, both now fixed in the harness:

1. **esptool-js's `after("hard_reset")` never resets a native-USB chip.** Its
   `HardReset` strategy is only `sleep(100); setRTS(false)` — it *releases* a
   reset it assumes the connect sequence left asserted. Both `ClassicReset` and
   `UsbJtagSerialReset` END with RTS deasserted, so that call is a no-op
   transition and the chip stays in the flasher stub — silent forever.
   *Fix:* pulse it ourselves — `DTR=0` (IO0 high, app boot not download mode),
   `RTS=1` (EN low), hold 150 ms, `RTS=0`. Verified from the CLI: the chip
   rebooted, the USB device came back in **0.4 s**, and it printed
   `Project dongle - Dongle Version 15.5.0(tasmota)-3.3.8(2026-07-22T00:39:30)`
   → the build date matches the flashed image, and
   `BRY: Successfully loaded 'autoexec.be'` → the LittleFS write was good too.
   `StatusPRM.RestartReason` reads `"Usb uart reset digital core"`.
2. **A boot banner cannot be caught on native USB.** The CDC port only exists
   while the firmware runs, so everything printed before the host opens the port
   is lost; the banner lands ~2.4 s after reset, and an idle Tasmota then prints
   nothing at all. *Fix:* `wait_boot` now **polls** (`Status 0` every 2 s until
   it answers) and treats a reply — not a log line — as proof the firmware is
   up. A banner match is accepted as an early exit if one happens to arrive.

Handshake-line behaviour, measured on the same device:

| Test | Result |
|---|---|
| Open the port 5× with DTR/RTS left asserted, 3 s apart | `UptimeSec` climbed 29→37→46→54→63, no banner → **attaching never resets it** |
| Open, then clear DTR and RTS as separate calls | `UptimeSec` dropped to **1** → **it rebooted**, exactly the trap `push_fs_serial.py` documents |

So the `monitor_signals: null` rule for native USB is not a precaution, it is a
measured requirement. Timing for capacity planning: the blank-device C6 flash
(2.4 MB factory + 3.4 MB filesystem, 115200 over CDC) took **116 s**, of which
the filesystem was 19.7 s (it compresses to 57 kB). Budget ~2.5 min per C6, and
that is wall-clock for five in parallel too, if the USB controller keeps up.

Device identity for the record: MAC `58:8C:81:2F:74:74` → topic
`dongle_588C812F7474`, and `autoexec.be` applies the boot config (incl. the MQTT
host) by itself — so the scenario has less to push than the V2 flow did.

---

## 8. What this fixes versus the current Python tool

1. **No install on the operator PC** — no Python, no venv, no `requirements.txt`,
   no README in Polish about PATH. A browser and a URL.
2. **Logs are queryable, not files.** Today: `reports/<device>_<type>.json` on
   whoever's laptop ran it, and `report["serialLog"]` only if the run completed.
   After: every line in Postgres as it arrives, per device, per run, searchable,
   linked to the project and production run.
3. **Device history by MAC.** Today the device identity comes from the Tasmota
   topic *after* a successful config; the MAC is read by esptool anyway, so a run
   is attributable even when it fails early.
4. **Scenarios are data, versioned.** Today `config.py` and `test.py` hardcode
   the sequence, and adding a product means editing Python and copying a folder
   (`test.py` even dispatches with `getattr(tester, model)`). After: an ordered
   step list per project, immutably versioned, and each run records the exact
   version used.
5. **Secrets stop living in git-adjacent plaintext.** `settings.json` currently
   carries the WiFi password, the MQTT password and `creds_salt`; those move into
   encrypted param sets.
6. **Credentials are a table, not `mosquitto_passwords.txt`** appended by hand —
   with an export endpoint that reproduces the file when the broker needs it.
7. **Five devices, one page, real parallelism** (today: subprocess-per-op,
   Tkinter, 3 hardcoded columns, per-host port lists).
8. **A failing step says what failed.** Today several failures are swallowed
   (`config.py` catches everything into `report["Error"]`, `test.py` has a bare
   `except: pass` at the bottom, `main.py` greps subprocess stdout for
   `"Chip erase completed successfully"`). The engine records per-step status,
   duration and error.
9. **Erase/flash verification is real** — MD5 of the written image versus the
   flash, instead of string-matching esptool's stdout.
10. **Boot waits become conditions, not `sleep(4)`.**

---

## 9. Migration phases

| # | Phase | Deliverable | Estimate |
|---|---|---|---|
| 0 | Hardware proof (§1) | one CE device flashed + configured from Chrome; then two in parallel; C6 checked with `Monitor only` | 15 min of your time |
| 1 | Schema + storage | tables in `models.py`, startup migrations, firmware upload to MinIO, `flash_param_sets` with Fernet | ~½ day |
| 2 | Engine + WS | `services/flasher/` with the §5 ops, `routers/flasher.py`, logs streaming to Postgres, run/step lifecycle | ~1½ days |
| 3 | Operator bench UI | `FlashBench.tsx`, worker-per-station, esptool-js integration, live log, PASS/FAIL, 5 slots | ~1½ days |
| 4 | Admin + history UI | scenario editor, firmware assets, run history + log viewer, project tab | ~1 day |
| 5 | Port the CE scenarios | `CE_Dongle_V2`, `CE_Aqua_V2` (ESP32) and `CE_Dongle_V3` (C6: factory+FS, plus app-only) as data; run side by side against the Python tool / PlatformIO tasks until they agree | ~1 day |
| 6a | Laser marking, zero-install | `mark_browser` step: render the patched `.lbrn2`, download it, operator presses Start + confirms; `marking_templates`/`mark_jobs` tables | ~½ day |
| 6b | Laser marking, hands-off (optional) | `mark_agent`: bench helper with an outbound WS to the platform, doing `FORCELOAD`/`START`/`STATUS` locally with dialog guards; driver already prototyped in `clients/lightburn-mark/`, needs the WS wrapper + packaging | ~1 day |
| 7 | Cutover extras | mosquitto export, retire the Tkinter app | ~½ day |

Phases 1–4 are the platform work; 5 is the actual migration; 6 folds marking
back in. The Python tool keeps working untouched until 5 passes.

---

## 10. Laser marking (LightBurn)

Researched and **measured against the installed LightBurn 1.7.03 on 2026-07-26**
(licensed, no laser connected). Prototype driver:
[`clients/lightburn-mark/mark.py`](../../clients/lightburn-mark/mark.py).

### Is there anything newer than the old UDP interface? No — but it is alive

LightBurn still exposes exactly one external control channel: the UDP socket
interface, now officially documented ([Automation with UDP][udp-doc]) and
**extended in 2.0** (`LASER:LaserName` was added), so it is not a deprecated
back door. There is no REST/WebSocket API and no scripting API; an open API is
still an open feature request on their tracker ([1][fider-api], [2][fider-script]).
Community wrappers ([bunkford][bunkford], [ShowStopper][showstopper]) do the
same thing our `lightburn.py` does.

### Verified command set (ports 19840 out / 19841 in, replies `OK` / `!` / `?`)

| Command | Measured result here | Notes |
|---|---|---|
| `PING` | `OK` in ~215 ms | **only** answers when no modal dialog is up — this is our health check |
| `LOADFILE:<path>` / `FORCELOAD:<path>` | `OK` in ~310 ms | absolute paths; **spaces work unquoted**; relative paths resolve against LightBurn's CWD |
| `IMPORT:<path>` | `OK` | adds to the current document instead of replacing it |
| `STATUS` | `OK` **with no laser attached** | means "not busy", **not** "laser present" |
| `START` | `OK` **with no laser attached** | confirms acceptance only — never that a job ran or was correct |
| `LASER:<name>` | `!` | needs LightBurn 2.0+; useless on 1.7.03 |
| anything else | `?` | |
| `CLOSE` / `FORCECLOSE` | `OK`, process exits | verified |

Reachability: the listener binds the **wildcard** address (`UDP *:19840`, IPv6
socket accepting IPv4-mapped traffic), and it answered on the machine's LAN
address (`192.168.200.46`) as well as loopback. Replies always go to **port
19841 on the sender's address**. So the platform API can drive a bench PC's
LightBurn across the LAN — no local agent needed for the commands themselves.
*Not verified* (Docker was stopped at the time): a container must be able to
**receive** on 19841, and because the reply targets a fixed port rather than the
request's source port, bridge-NAT conntrack will not return it — expect to
publish `19841:19841/udp` or run that sender with host networking.

### The three failure modes that matter in production

1. **A modal dialog freezes the whole interface.** Confirmed twice by accident
   in one session: the licence prompt made every command return `!` or nothing
   (including `FORCECLOSE`), and a `LOADFILE` for a path that did not exist
   produced **no reply at all** plus a "file could not be found" dialog that
   had to be clicked away by hand. Design consequence: `PING` before **and
   after** every command; silence = "a human must go to the bench", surfaced as
   a station alarm, never as a hang. The prototype does exactly this.
2. **Never hand LightBurn a path it cannot open.** The driver stats the file
   first and refuses locally — verified that this leaves LightBurn responsive.
   Unique per-run filenames (`<serial>-<run-id>.lbrn2`) also stop a browser
   download from colliding into `name (1).lbrn2`.
3. **There is no completion or correctness signal.** `START` returns `OK`
   without a laser. The only progress signal is polling `STATUS` for busy→idle,
   and **that is still unverified** (with no laser it returns idle immediately).
   Until it is checked on the real machine, a mark is *operator-confirmed*, not
   machine-proven: the run stores the exact `.lbrn2` that was sent plus the
   command log, and the operator confirms the engraving.

### Can marking be browser-only? Load yes, START no

Measured, so the trade-off is concrete:

| Step | Browser-only | Evidence |
|---|---|---|
| Render the serial-patched `.lbrn2` | **yes** | ordinary download, unique filename per run |
| Load it into LightBurn | **yes, confirmed end to end** | LightBurn registers `lbrn`/`lbrn2`/`lbt` as document types (its `Info.plist`), so Chrome's *Always open files of this type* (or the `AutoOpenFileTypes` policy) hands the download straight to it. Verified with the equivalent `open <file>`: a **running** LightBurn took it with no dialog (`PING` stayed `OK`) and the operator confirmed the engraving text on screen showed the patched serial (`AABBCCDDEEFF`) |
| Press `START` | **no** | no UDP from JS, no HTTP/WS in LightBurn, and **no URL scheme is registered** (`CFBundleURLTypes` is absent), so a `lightburn://` link is impossible too |
| Detect job finished / succeeded | **no** | needs UDP `STATUS` polling — and even that is only busy/idle, still unverified without a laser |

So there is a legitimate zero-install flow: **auto-load → operator presses Start
→ operator confirms**. For a fiber laser that is arguably the correct design:
a human is already at the fixture placing the part, and nothing fires from a web
page unattended.

Its two weaknesses, both from the same root — the `open` path has no
`FORCELOAD` equivalent:

1. Auto-open is an opt-in per file type (operator ticks the box once, or we set
   `AutoOpenFileTypes` + `AutoOpenAllowedForURLs` — the same policy mechanism as
   the serial grant).
2. If the operator nudges anything in the loaded document, the next auto-open can
   raise "save changes?", which blocks the load (and would block UDP automation
   too). `FORCELOAD` over UDP bypasses exactly that dialog.

### How it fits the platform — the network is NOT assumed

The platform runs on a server that **may or may not** share a network with the
bench PC (user constraint, 2026-07-26). That rules out the obvious design: the
backend cannot send UDP to a bench behind NAT or on another subnet, and it cannot
write the job file onto the bench PC's disk. The only component reliably next to
LightBurn is the bench PC itself, so there are exactly two supported modes.

| | `mark_browser` — zero install | `mark_agent` — bench helper |
|---|---|---|
| Start button on the web page | prepares the job only | **fires the laser** |
| Hands-off Start | no — operator presses Start in LightBurn | yes |
| Install on the bench | none | one small process (login item) |
| Network requirement | none | **outbound** connection to the platform only |
| Job file delivery | Chrome download + auto-open (file association) | helper fetches from the API and writes it locally |
| Immune to the dialog freeze | no — `open` can hit "save changes?" | yes — `FORCELOAD` bypasses that dialog |
| Completion signal | operator confirm | local `STATUS` polling |

**Hands-off marking requires the helper.** Something has to send a datagram to
`127.0.0.1:19840` on the bench PC and no browser API can (§1 limit 5); the
Direct Sockets `UDPSocket` exists only in Isolated Web Apps, ChromeOS-only.

The helper is deliberately marking-only and network-agnostic: it opens an
**outbound** WebSocket to the platform (traverses NAT, needs no inbound ports or
firewall rules, no LAN assumption), receives `{serial, template, job bytes}`,
writes the `.lbrn2` locally, runs `PING` → `FORCELOAD` → `PING` → `START` →
poll `STATUS`, and streams the command log back for storage. The logic is already
prototyped in `clients/lightburn-mark/mark.py`; only the WS client wrapper is
missing. Benches without a laser install nothing, and flashing stays in the
browser either way.

Outbound-only also avoids the page calling `http://127.0.0.1` directly, which
current Chrome gates behind a Local Network Access permission prompt.

A third mode — backend sends the UDP itself over the LAN — is verified to work
(LightBurn's listener binds the wildcard address and answered on
`192.168.200.46`) but only applies when the platform genuinely shares the bench
network. It is not the design baseline.

New scenario step, backend-side:

```
{ "op": "mark", "mode": "browser" | "agent",
  "template": "AQUA_DONGLE_Side_Info.lbrn2",
  "placeholder": "123456789011", "value": "{topic_serial}",
  "host": "{station_lightburn_host}", "job_dir": "{station_job_dir}",
  "start": true, "job_timeout": 300, "confirm": "operator" }
```

Data model additions: `marking_templates` (project-scoped `.lbrn2` in MinIO,
versioned like firmware assets) and `mark_jobs` (`flash_run_id`,
`device_unit_id`, `template_version_id`, `serial`, `job_file_key` — the exact
generated file, `status`, `seconds`, `operator_confirmed`, `log`). Marking then
lives in the same run record as the flash, which is the point: one device, one
traceable history.

Rejected alternative: LightBurn's own **Variable Text** (CSV/Merge or Serial
Number modes, [docs][vartext]) instead of patching the XML. It needs the
`Current`/`Start`/`End` row index managed inside LightBurn's UI ("on the first
run of a project you must Reset the Current value"), the docs do not state that
the CSV is re-read per run, and nothing lets us set the row over UDP — so it
cannot be driven deterministically from the platform. Patching a copy of the
template is deterministic and already proven in production.

Two things to decide: whether to **upgrade the benches to LightBurn 2.x** (gets
`LASER:<name>`, i.e. picking the right machine when a bench has more than one),
and whether marking is a step *inside* the flashing scenario or a separate
scenario run against an already-flashed device (the current tool marks from the
Tasmota topic on a second station — the platform can do either, and knows the
serial from the flash run either way).

[udp-doc]: https://docs.lightburnsoftware.com/2.1/Guides/AutomationWithUDP/
[vartext]: https://docs.lightburnsoftware.com/2.1/Reference/VariableText/
[fider-api]: https://lightburn.fider.io/posts/1089/open-api-or-interface-for-external-script-or-extension-programming
[fider-script]: https://lightburn.fider.io/posts/205/control-lightburn-from-a-script
[bunkford]: https://github.com/bunkford/lightburn_automation
[showstopper]: https://github.com/ShowStopperTheSecond/LightBurn-UDP-API

## 11. Decisions needed from you

1. **Operator identity.** The platform has no user/auth system (only the MCP
   bearer token). Options: (a) a free-text/dropdown operator name on the bench,
   recorded on each run — cheap, no auth; (b) real login + roles like the old
   `web_flasher` branch had; (c) nothing. Recommend (a) now, (b) if the bench
   ever leaves the LAN.
2. **Scenario approval.** Route scenario edits through the existing Proposals
   view (consistent with the library, adds a QA gate) or let an admin publish
   directly? Recommend gating: a wrong MQTT host in production is expensive.
3. **HTTPS.** Web Serial needs a secure context, so an operator PC that is not
   the server needs HTTPS or a localhost tunnel. Which do you want?
4. **LightBurn marking** (§10) — `mark_browser` (zero install, operator presses
   Start in LightBurn) or `mark_agent` (one small helper per laser bench, Start
   fires from the web page)? Hands-off needs the helper. And do we upgrade benches
   to LightBurn 2.x for `LASER:<name>`?
5. **Scope of "project"** — attach scenarios to the existing platform projects
   (traceability to BOM/production runs) or keep a standalone product list?
   Recommend the former; it is the reason to host this here at all.

## 12. Traceability model — decided and built (2026-07-27)

Decisions taken with the user, and the schema that implements them. **The tables
exist in Postgres already** (`create_all` + one idempotent `ALTER TABLE`);
routers, services and UI are the next phases.

### Decisions

| Question | Decision |
|---|---|
| What is versioned | A **release version** pins firmware images + the programming steps. Parameter *values* are NOT in it: they come from a `ParamSet` at run time and the resolved values are snapshotted onto each run, so rotating a WiFi password does not mint a release version. |
| Production run ↔ release | A programming run **must** belong to a production run, and the release version is taken from that batch. An override is allowed but records a reason and an audit row. |
| Device credentials | Stored **in the clear**, as today (`reports/*.json`, `mosquitto_passwords.txt` parity). Consequence: never returned by list endpoints — detail views only. The shared secrets (WiFi password, salt) stay Fernet-encrypted in `param_sets`. |
| Logs | **Everything** is kept, esptool progress included — expect a few thousand rows per run. |
| Existing `run_devices` | **Kept unchanged** as the batch's planned serial list. `device_units` records physical reality; the two are reconciled by serial into a per-batch coverage report. Nothing migrated, no endpoint removed. |
| Operator identity | A name recorded per run (no auth system exists yet). |
| Release publishing | An admin action on the release version (`draft` → `published`), not the component Proposals view. |

### Tables

| Table | Role |
|---|---|
| `firmware_assets` | the `.bin`s, **content-addressed** (`uq_firmware_project_sha`), bytes in MinIO, `kind` = factory\|app\|filesystem\|safeboot |
| `releases` / `release_versions` | named target per project / immutable firmware+steps bundle (`status`, `approved_by`, `steps` JSONB, `transport_profile`, `flash_config`) |
| `release_images` | image → offset mapping; a blank C6 needs two rows (factory @0x0, LittleFS @0x4B0000) |
| `param_sets` | per-project/env placeholder values, Fernet-encrypted |
| `production_runs.release_version_id` | **new column** — which bundle the batch is programmed with (soft pointer) |
| `device_units` | the physical device, **`mac` UNIQUE** = identity; `tasmota_id` and `serial` are labels |
| `programming_runs` | one row per attempt, pass or fail; `device_unit_id` **NULLABLE** by design; pins `production_run_id` + `release_version_id` (both NOT NULL) |
| `programming_steps` | per-step outcome + duration |
| `programming_logs` | append-only raw log (`dir` = tx\|rx\|app\|err\|esptool, `device_ts` keeps the device's own clock) |
| `device_config_values` | per-device config keys with history (`current` flag, `set_by_run_id` provenance) |

### Why a failed device is no longer anonymous

1. The run row is written **before step 1**, already carrying batch, release,
   station, operator and time.
2. `esp_connect` reads chip + MAC **before the erase** — measured at **1.79 s**
   against the real C6, versus 19.6 s for the erase alone. That upserts
   `device_units` by MAC and links the run, so every failure after ~2 s is
   attributed to a device.
3. If even the MAC read fails, the run stays with `device_unit_id = NULL` but
   keeps its full log and error, and is listed as an **unidentified attempt**
   that can be linked to a device afterwards (audited).

### Reconciliation report per batch

`run_devices` (planned) vs `device_units`+`programming_runs` (actual), matched on
serial (`58:8C:81:2F:74:74` → `588C812F7474` → topic `dongle_588C812F7474`):
registry count · programmed OK · failed · **programmed but not in the registry**
· in the registry but never programmed.

### Build order

1. ~~Tables + migration~~ **done** — 10 tables + `production_runs.release_version_id` verified in Postgres
2. Firmware upload to MinIO (sha256 dedupe) + releases/versions CRUD + publish
3. Run lifecycle service: create-before-step-1, MAC upsert, step/log writers, params snapshot
4. Bench wiring: browser streams its log + step results to the API
5. Device view, run view (step timeline + raw log + JSON export matching `reports/*.json`), unidentified list + retro-link
6. `derive_credentials` → `device_config_values`, mosquitto export

---

## 13. Production build — the decided artifact model (2026-07-29)

Decisions taken with the user on 2026-07-29, each verified against the two
source repos (`~/Projects/CE_Production_flasher`,
`~/Projects/CE_Dongle_v3_board`).

### Releases and deployment scripts are two different things

Verified in the old tool's `settings.json`: `process = ["erase", "flash",
"config", "test"]`. The flash comes from `binaries/` and is one stage; the
`config` + `test` stages are the operator's scenario. The platform keeps that
separation:

| Entity | Meaning | Tables |
|---|---|---|
| **Release** | what gets FLASHED: firmware images at offsets | `releases` / `release_versions` / `release_images` — unchanged, but `steps` on `release_versions` is retired (steps move out) |
| **Device files** | the `.be` / `.json` payload the device downloads (autoexec.be, driver JSONs, …) | NEW `device_files` (project, filename) + `device_file_versions` (version_no, content, sha256, status, comment) — versioned separately from firmware |
| **Deployment script** | the ordered config/test steps the programmer runs after the flash | NEW `deployment_scripts` + `deployment_script_versions` (steps JSONB, status draft→published) |
| **Links** | a deployment script version PINS one release version and a set of device file versions | `deployment_script_version.release_version_id` + NEW `deployment_script_files` link table |

`programming_runs` gains `deployment_script_version_id`; it keeps the pinned
`release_version_id` (denormalised — exactly what was flashed).
`production_runs` gains `deployment_script_version_id`; the batch assigns the
script, the script brings the firmware. All flasher tables are empty, so these
are plain `ALTER TABLE` startup migrations.

### Device files travel over HTTP, not inside a LittleFS image

User decision: flash **factory only** (it ships an empty LittleFS,
`custom_files_upload = no_files`), never the populated `ce_littlefs.bin`. The
deployment script then:

1. configures WiFi and waits for the connection (V2 `config.py` flow),
2. has the DEVICE download each pinned file version over HTTP
   (`UrlFetch` + `file_size` verification — the proven V2 loop, previously
   served from `disfunction.cc/berry/release/`),
3. verifies each size against the platform's stored byte count.

The platform serves them itself: `GET {public_base_url}/api/flasher/files/…`
(same reachability rule as the KiCad HTTP library — `public_base_url` must be
the LAN address the device can reach, never `localhost`). Published versions
only; `UrlFetch` sends no auth headers, so the endpoint is unauthenticated by
design, like the KiCad catalog.

### New V3 steps: SIM PIN and the LTE proof

Verified in the firmware (`autoexec.be` header, `xdrv_128_lte_modem.ino`):

- **`LteSimPin` is provisioned once over serial, early in the script**
  (persists to `/.drvset128`, survives app-only flashes — the firmware's own
  `tools/provision_secrets.py` flow). HARD GUARD, documented at
  xdrv_128 ~483–495: the driver never re-sends a rejected PIN (3 wrong tries
  PUK-lock the SIM), and only a *different* `LteSimPin` value clears the
  latch. The step must therefore send the PIN once and treat a rejection as a
  terminal run failure, never retry.
- **The LTE test ends the script**: clear `SSId1`/`Password1` → the WAN
  failover (WiFi primary, LTE hot standby, `WanBootArm`) switches to LTE →
  poll `LteState` until connected, then verify connectivity (checks ported
  from `firmware/tools/failover_test.py` + `MANUAL_TEST_PLAN.md`). The final
  state doubles as the shipping state: no WiFi credentials on the device.
- The PIN value is a run parameter (param set or operator input), never in a
  script version.

### Web Serial and TLS — clarified

`localhost` **is** a secure context: the bench needs no TLS when the page is
served from the same machine (that is why every PoC test worked over plain
HTTP on 127.0.0.1). HTTPS becomes necessary only when the bench page is opened
from a different machine than the server. Dongle_V3 tests run on the dev Mac
at `localhost:5173`; the device-download `base_url` must still be the Mac's
LAN IP so the WiFi-connected device can reach it.

### SIM PIN — three sources, engine-prompted (user decision 2026-07-29)

Resolution order in the `lte_sim_pin` step: the operator's bench field →
`sim_pin` in the param set → a **mid-run prompt** (`{t:"prompt"}` over the run
WebSocket; the bench shows a modal). A script for PIN-less SIMs omits the step
or marks it `optional` (an empty value then skips it). The PIN is sent ONCE
and a rejection is a terminal failure — the driver PUK-guards re-sends
(xdrv_128 ~483) and the engine must never retry. The PIN is masked in the
stored tx log and in `params_snapshot`.

### Device identity — what the firmware can actually report (verified)

`device_units` stores mac, chip, tasmota_id, serial, **imei, iccid, imsi,
modem_model, modem_fw** (user requirement 2026-07-29); the engine writes any
captured variable with one of those reserved names to the device row.
Verified against xdrv_128 + the fs sources:

- `LteState` → `{"Lte":{"Up":0|1,"WantUp":..,"IP":..,"GW":..,"Ifname":..,"LastErr":..}}`
  — the LTE-proof poll target (`Lte.Up == 1`).
- The teleperiod JSON (`Status 10` → `StatusSNS.LTE`) carries `Iccid`,
  `SimNumber`, `Oper`, `PLMN`, `RSSI` … — ICCID and MSISDN are capturable today.
- **IMEI and IMSI are NOT exposed on the console yet**: the driver reads the
  IMSI internally (AT+CIMI) but publishes neither. Filling those columns needs
  a small firmware addition (extend `LteState` or add an `LteInfo` command).
  The schema and capture path are ready for it.

## 14. Deployment bundles — ONE revision binds everything (2026-07-29)

The first pass gave firmware, berryware and the procedure their own versioned
lives and bound them through a "deployment script" version. The binding was
real but invisible: five sibling lists in the UI, no composed view, no diff,
and authoring meant six publishes across four panels. User verdict: *"they
don't seem combined… I'd like a single revision that binds together other
revisions of firmware and berryware"*, plus *"the files come in bundles, so
even if files are independently revisioned, I'm mostly interested in the
bundle version and which files it has"*.

### The model

**Deployment** (named target per project) → **Deployment version** (THE
revision). One version pins:

| Slot | Stored as | Independently versioned? |
|---|---|---|
| Firmware | `deployment_images` (asset + offset) | assets are content-addressed and shared |
| Berryware | `deployment_files` (exact `device_file_versions`, ordered) | yes — plus a **set label** (`release-1.3.11`) and a set fingerprint, because the user thinks in bundles |
| Procedure | `steps` JSONB | in the version |
| Parameters | `param_set_id` + `param_defaults` | values resolve at run time, snapshotted per run |
| Transport | profile + monitor baud | in the version |

**The `Release` entity is gone.** Its images moved onto the version and its
identity became a derived **fingerprint** (`sha256` over the ordered
address+sha list; the file set gets its own, order-independent). That is what
lets the UI say "firmware unchanged since v5" or "3 files changed" with no
second object to manage — and it works: the V2 eras that share a berryware set
share a fingerprint, which is how every historical set recovered its real name
(`release-0.0.1` … `release-1.3.11`) by propagation.

**Channels** (`production`, `bench`) are named pointers at a version. Going
live and rolling back are channel moves; history is never edited. A batch
either pins a version or follows a channel, and a run always records what
actually resolved.

### Guardrails (`services/flasher/validate.py`)

One function serves both the live composer and the publish button, so the
editor can never disagree with the gate. Errors refuse publication:

1. every pinned artifact is published;
2. chip agreement across deployment, images and transport (`usb_serial_jtag`
   only for native-USB parts);
3. flash-map offsets parse, are unique, and **do not overlap** (checked
   against real image sizes);
4. **dataflow**: every `{placeholder}` resolves from parameters or an EARLIER
   step's capture, and every asserted variable exists — this catches the
   `{SSId1}` vs `{SSID1}` class of typo before a device sees it;
5. downloads need pinned files and **`autoexec.be` must be last**;
6. flashing needs images and `esp_connect` first;
7. no serial op before `serial_open`.

Warnings cover the rest (SIM PIN with no source, pinned-but-unused artifacts,
`esp_connect` not first). Publishing also **requires a comment** and shows the
diff — you approve a diff, never a form.

### Elasticity

`POST /deployments/{id}/versions` takes a `from_version_id` and **inherits
every section you do not name**, so "bump the berryware" is one field. The
composer adds a **folder import**: drop `firmware/fs/` or a
`berry/release-x.y.z` directory and only files whose content actually changed
mint a version — verified idempotent (19 files → 0 changed on a re-import).
Draft versions are runnable as **bench trials** (no batch, recorded
`draft_run`); a batch runs published versions only.

That import exposed a real bug worth keeping written down: text files must be
stored with **LF endings normalised**. The old path read text (Python
translates CRLF), the new one read bytes, so five CRLF files reported
"changed" on every import forever. Content addressing is only useful if the
same source yields the same hash whoever uploads it.

### Migration

Renames, not rebuilds: `deployment_script*` → `deployment*` with ids intact,
so all **6,321 imported V2 runs** kept their version. Release images folded
into the versions that pinned them, chip lifted onto the deployment, release
tables dropped. The rename half runs BEFORE `create_all` — otherwise it would
build empty bundle tables beside the populated script ones and strand the
history.

### Cleanup: every version now validates

Turning the validator on its own history found three classes of unusable
version, all artifacts of the first import pass. Fixed rather than hidden
(`scratchpad/cleanup.py`, run on both stacks; **6,321/6,321 runs kept their
pin**):

1. **Empty-step placeholders** — the era versions created before the
   procedures were reverse-engineered. Superseded, zero runs → deleted (10).
2. **"unmatched" berryware eras** — 4 reports whose downloaded file sizes
   matched no release. They are *partial downloads* (e.g. `mateodongle_aqua.be`
   at 11,159 B against a real 32,872 B), which is why nothing matched. The
   intended deployment is the era whose date range contains the run, so those
   4 runs moved there with a `results.retro_note` recording why, and the empty
   placeholder versions went (3).
3. **Aqua pinned no berryware at all** — device files are project-scoped and
   the Aqua units live in their own project, so the import had nothing to pin.
   Their 2024-07 era is `release-0.0.1`; those 6 files are now imported into
   that project and pinned, and the version validates.

Remaining state: 12 versions across 5 deployments, **all valid**, and the retro
deployments deliberately carry no channel — V2 is history, not a live target.

One trap worth recording: the cleanup script's own final report first claimed
13 versions were still bad after deleting them. Sessions here use
`expire_on_commit=False`, so `deployment.versions` still held the deleted rows
in memory. Audit from a fresh session, never from the one that mutated.

---

### Berryware BUNDLES are first-class (2026-07-29)

The user receives berryware as a bundle with the berry project's own release
number, so the platform now models exactly that: `berry_bundles` — one row per
distinct file SET per project, identity = the set fingerprint, label = the
release name (`release-1.3.11`, `fs @ 2026-07-22`). Files still version
individually underneath; the bundle is the unit you SEE and PIN.

- The folder import mints/reuses the bundle automatically (same fingerprint →
  same bundle, whatever the folder was called; a real name upgrades a generic
  "N files" label but never overwrites another real name).
- The composer pins a whole bundle in one pick; a deployment version whose set
  matches a bundle links it and mirrors its label (`link_bundle` after every
  `stamp`). Ad-hoc file picks stay unlabeled until named — a bundle is a
  deliberate act, never an accident.
- Artifacts shows the bundle list (label, files, used-by) above the raw
  per-file pool.

### WiFi and MQTT go down in ONE Backlog each (2026-07-29)

Set separately, the device can restart between `SSId1` and `Password1` and
come up with the new SSID but the old password. Both now travel in a single
`Backlog` (one restart with a complete config), and because Backlog does not
reliably echo, the procedure verifies by READBACK + assert after the boot.
Same pattern for the whole MQTT block. Encoded in
`docs/flasher/scripts/v2_steps.py` and live in the current versions of all
three production deployments — each proven end-to-end in simulation
(`simulate_bench.py`): Dongle_V2 28/28, Aqua_V2 39/39, Dongle_V3 32/32
including the LTE failover proof.

### Fidelity audit + the graphical procedure editor (2026-07-30)

**Audit against `CE_Production_flasher` at HEAD.** The config procedure is
faithful: `SetOption153 1` → Modbus ×2 → WiFi → reset → WiFi poll → `Status ?`
→ derive credentials → downloads → MQTT block → `SetOption153 0` → clear the
AP, in that exact order. Three deliberate differences, all recorded:

1. WiFi and the MQTT block travel in ONE `Backlog` each (user requirement) —
   the original set them one at a time, so the device could restart between
   `SSId1` and `Password1`.
2. `wait_boot` POLLS instead of the original's `sleep(4)`.
3. Readback + assert steps were ADDED after each Backlog, because Backlog does
   not reliably echo what a `set_and_check` would have verified.

**One real gap found and fixed.** `test.py::_check_relay` checks BOTH states —
the switch must read ON while the relay is OFF (the wiring inverts it) and OFF
while it is ON. The reconstruction asserted only the second half, so a relay
stuck ON would have passed. The Aqua test procedure now asserts both, and reads
the DS18B20 temperature from the relays-OFF sample as the original does.
Published as `Aqua_V2 test (retroactive)` v2 on both stacks.

**The procedure editor is graphical** (`StepEditor.tsx` + `stepSchema.ts`).
Each step is a row you can read at a glance and open to edit; the fields come
from a schema keyed by op, so the form always matches the step. Two
consequences the user asked for:

- **A `flash` step picks its firmware images** (with offsets pre-filled from
  the partition map) and a **`download_files` step picks its berryware
  bundle** — so the composer no longer needs separate firmware and berryware
  sections. Both still write the VERSION's pins: the version remains the one
  place a payload is defined, the controls simply live where the work happens.
- **Every value is a literal OR a parameter**, chosen from a dropdown that
  offers the param set's keys, the runtime variables and anything an EARLIER
  step captured — `ValuePicker` writes the `{Name}` form so nobody types
  braces. `capture` is a name ← path table, and `Backlog` is a list of
  setting + value rows using the same picker.

"Edit as JSON" is still there for a bulk paste. The dropdowns are convenience
only — `validate.check()` on the server stays the authority, so the editor can
never disagree with the publish gate. Round-trip verified: a version composed
the way the editor writes it validates and passes 28/28 in simulation.

**The same rows render a PUBLISHED procedure** (`readOnly`), so the deployment
view shows what the composer authored instead of a flat list: each step opens
to its fields as text, `{parameters}` are highlighted as resolved-at-run-time,
the flash step names its images and offsets, and the download step names its
bundle. Read-only for now by request — one component, so allowing edits later
is a flag rather than a second implementation. Its context comes from the
version payload itself, so the view costs no extra requests.

### Firmware admin, chip detection, and the 1.3.11 question (2026-07-30)

**`/production/files` administers the pool**, one kind per tab. Firmware and
bundles are two-column: how a thing gets in on the left, what exists on the
right. Only **esp32 and esp32c6** are offered (user decision).

**The chip comes from the image header, not a dropdown.** `_detect_chip` reads
`chip_id` at offset 12 of the ESP image header, at offset 0 for a bare app
image or 0x1000 for a padded whole-flash image — verified against all three
real builds (V2 factory → 0 = esp32, V3 factory → 13 = esp32c6). The upload
overrides whatever was selected, because a mislabelled chip is how a build
reaches the wrong part. Headerless images (LittleFS) keep the selection.

**Offsets are derived, shown, and pre-filled.** `DEFAULT_OFFSETS[chip][kind]`
comes from the projects' own partition maps (esp32c6: factory 0x0, app
0xE0000, filesystem 0x4B0000 from
`esp32c6_partition_8MB_app3904k_fs3392k.csv`; esp32: factory 0x0, app
0x10000). The firmware pool shows the offset per row and the composer
pre-fills it — a version may still override, since the layout has the final
say. A blank means "no safe default".

**The `release` bundle was 1.3.11.** The un-suffixed `/berry/release`
directory carried no number, so it was identified by content: 17 of 18 files
byte-identical to `release-1.3.11`, and the 18th (`DEYE_LP3.json`) differs
only in formatting — the parsed JSON is identical, server mtime 2025-12-11,
minutes after the 1.3.11 files. Per the user's call, the pristine 1.3.11 set
was imported, the four versions using the served copy were re-pointed to it
(`scripts/swap_bundle.py`, each carrying a note about the substitution), and
the ambiguous bundle was deleted. Watch out for the stale headers in that
repo: every `.be` file says `#NEW RELEASE 1.3.0` and
`self.version = "1.3.x"` even in 1.3.11 — the directory name is the only
reliable version marker.

**Consequence of the flashability gate:** the three generation-B versions that
pin the never-archived pre-2024-08 placeholder now report as unrunnable
("not a writable ESP image"). That is correct and permanent — they are
records of 643 real runs whose firmware bytes are lost, so they can be read
but never programmed.

### Could a V2 actually be programmed today? (2026-07-29)

Answered by simulation rather than assertion:
`docs/flasher/scripts/simulate_bench.py <version_id>` connects to the run
WebSocket as the bench, answers the esptool actions, and replies to every
console command the way a Tasmota V2 dongle would. It found four real defects
that a hardware session would otherwise have found the hard way.

1. **The final step always failed.** The V2 flow ends by clearing the bench
   WiFi (`SSId1 0`), after which the device restarts and stops answering —
   `config.py` wrapped exactly that call in `try/except`. The engine treated
   silence as failure, so a *correct* run ended `fail` on step 28 of 28. The
   `command` op now takes `optional: true`, where silence is the pass.
2. **Three versions pinned a 158-byte placeholder as firmware.** The validator
   checked chip and offsets but never whether an image is writable. Flashing
   one would have bricked a unit. `firmware_assets.flashable` is now decided
   from the bytes at upload (ESP magic `0xE9` at offset 0, or at `0x1000` for a
   padded whole-flash image — the V2 factory images are of the second kind) and
   the validator refuses a version that pins a non-flashable image.
3. **Prod could not run the bench at all.** Neither nginx hop passed the
   WebSocket upgrade, so `/api/flasher/ws/<run>` answered 404. Both now map
   `$http_upgrade` conditionally (`web/nginx-api-proxy.inc` and the server's
   own `nginx.conf`).
4. **A startup migration had been silently rolling back for days.** The
   first-pass statements still altered `release_versions`, which the bundle
   pass drops; because that whole block is ONE transaction under a bare
   `except: pass`, every later column add vanished with no trace, and an
   obsolete `ADD COLUMN IF NOT EXISTS deployment_script_version_id` had
   re-created two stale columns. The block now logs its failure, the obsolete
   statements are gone, and the stale columns are dropped.

Two runnable targets came out of it, each **28/28 steps green in simulation**
and on their deployment's `bench` channel (proven in simulation, not yet on
hardware — `production` waits for a real unit):

- **Dongle_V2 production** — generation-C flow, firmware 14.2.0, the current
  berryware set.
- **Aqua_V2 production** — the same flow with the CE_AQUA_V2 build. Note it
  does *not* push `Template`/`Module`: from 2024-07-22 the GPIO template is
  compiled into the firmware, so the modern flow must not re-push it.

The retro deployments stay as history and carry no channel.

### Retroactive V2 import (2026-07-29)

All 6,321 `CE_Dongle_production` reports (2024-06-10..2026-07-08) are in the
platform: **5,502 devices**, 6,321 programming runs (6,126 pass / 195 fail),
**2,444,307 log lines**, 16,269 config values, 5 return notes. Provenance per
run: `results.retro_source` = the report path; re-running the importer skips
those. Scripts: `scratchpad/retro/{scan_reports,setup_artifacts,import_runs}.py`.

Deduction, all evidence-based (nothing guessed):

- **Firmware** from the boot banner (`Project dongle - Dongle Version
  <core>(tasmota)-<tag>(<built>)`). Three builds observed; bytes recovered
  for all three — `13.4.0-2_0_14@2024-07-22` (server ota/release-13.4.0, bin
  contains the tag), `14.2.0-3_0_4@2024-10-25` (server ota/release-14.2.0,
  mtime = the build date), `14.2.0-3_0_4@2025-11-05` (the bench PC's own
  binaries/, file dated 2025-11-05). The pre-2024-08 build (642 runs, no
  serialLog era) is a PLACEHOLDER asset — bytes never archived.
- **Berryware** by size-fingerprinting each report's `Downloaded files`
  against the mirrored `disfunction.cc` berry release dirs (ssh
  `ubuntu:~/aws-deployment/www/html/`). Every era matched exactly one dir
  (0.0.1 → 1.1.41 → 1.2.6 → 1.3.0 → current `release`); 4 straggler reports
  matched none and carry their own script version marked `unmatched`.
- **Eras** = one `Dongle_V2 config (retroactive)` script version per observed
  firmware+berry combo (8), pinning the release version and the exact file
  versions; tests import under `Dongle_V2 test (retroactive)`.
- **Batches deliberately NOT assigned** (`production_run_id` NULL) — user
  decision: never guess. `device_units.mac` is NULL for the 4,045 6-hex-era
  devices (the reports only ever knew the topic suffix); the 2,276 12-hex
  devices carry their real MAC. Both columns went nullable for exactly this.

### Reverse-engineered V2 scripts (2026-07-29)

The retro script versions carry real steps now, reconstructed from
`~/Projects/CE_Production_flasher` git history and **cross-checked against the
commands counted in the imported logs** (`scratchpad/retro/v2_steps.py`,
`apply_v2_scripts.py`). Three config generations, each a published version per
era, with the runs repointed:

| Gen | When | What the bench sent | Evidence |
|---|---|---|---|
| A | 2024-06-06..06-23 (`22fcfdf`) | every option over serial; **no** autoexec gate | config.py at those commits |
| B | 2024-06-24..07-21 (`b96a15e` "models and its templates") | adds `SetOption153` gating, model `Template`/`Module`, `GroupTopic1`/`FriendlyName1`/`Topic` | logs for that era show Template 431× and Module 195× |
| C | 2024-07-22..now (`25eb466` "new binaries with most important settings built in") | options move INTO the firmware; script shrinks to gate → Modbus → WiFi → creds → downloads → MQTT → ungate → clear AP | the current era's logs show exactly `SetOption153`×2, `SSId1`×2, `Password1`, `ModbusSerialConfig`, `ModbusBaudrate`, `MqttFingerprint1/2`, `MqttPassword`, `MqttUser`, `MqttHost`, `MqttPort` per run |

Two more things the reconstruction settled:

- **`Topic` was `dongle_%12X`** (Tasmota expands `%12X` to the last three MAC
  bytes) — that is *why* the V2 fleet is identified by a 6-hex suffix and the
  full MAC was never recorded (commit `b808d25`).
- **122 of the 5,502 "dongles" are CE_Aqua units.** Their own logs contain
  `Template successfully set to 'CE_Aqua'` (`device_data.json.template_name`,
  derived by the production repo's own `find_template_name`). They were moved
  to the CE_Aqua_V2 project with their runs, onto `Aqua_V2 config
  (retroactive)` + its own release; the Aqua functional test (relay matrix
  Power1-3 vs Switch7-9 + DS18B20 range check, template backed up and
  restored) is ported from `test.py::CE_Aqua`. `test.py::CE_Dongle_V2` is
  empty by design — the dongle has no functional test, and its retro test
  script says so in 7 steps.

## 14. One revision binds everything — the bundle refactor (2026-07-29)

The three artifact families were versioned separately and the UI showed them
as five unrelated lists, so "what does a device get" had no single answer.
Fixed by promoting the binder and folding the rest into it.

- **`Deployment` + `DeploymentVersion` are THE unit.** One version pins
  firmware images at offsets, the exact berryware file versions, the procedure
  and the parameter wiring. `programming_runs.deployment_version_id` is the
  only pin a run needs.
- **The `Release` entity is gone.** Its images became `deployment_images`;
  its identity became a derived `firmware_fingerprint` (sha256 over the
  ordered address+sha pairs). `files_fingerprint` does the same for the
  berryware SET, plus `files_label` ("release-1.3.11") — the user thinks in
  file bundles even though files version individually (their words). Two
  versions pinning the same bytes share a fingerprint, which is what lets the
  timeline say "firmware unchanged, berryware 3 changed" for free.
- **Channels** (`production`, `bench`) are named pointers at a version.
  Going live and rolling back are channel moves; history is never edited.
- **Composing inherits.** `POST /deployments/{id}/versions` takes
  `from_version_id` and only the sections that CHANGE; everything else is
  carried over. A folder import
  (`POST /projects/{id}/device-files/import`) resolves a whole berryware
  directory in one call, reusing every file whose content is unchanged.
- **Drafts are runnable on the bench only** (`draft_run` on the run), never
  for a batch.
- **Newlines are normalised to LF on every device-file write.** A CRLF file
  read as bytes hashes differently from the same file read as text, which made
  5 of the V3 files report "changed" on every import when nothing had.

### The publish gates (`services/flasher/validate.py`)

One function, called live by the composer and again by the publish button, so
the editor can never disagree with the gate: pinned artifacts must be
published; chip agreement across deployment/images/transport; **images must be
writable ESP images** (magic 0xE9 at 0x0, or at 0x1000 for a padded
whole-flash image — this is what catches a PLACEHOLDER asset before it bricks
a unit); flash offsets unique and non-overlapping against real image sizes;
every `{placeholder}` resolves from a parameter or an EARLIER step's capture;
`autoexec.be` downloads last; a serial op cannot precede `serial_open`;
`lte_sim_pin` without a PIN source warns.

### Proven by simulation, not assumption

`clients/flasher-poc/simulate_bench.py` acts as the bench and as a Tasmota
device, so a procedure can be run end to end with no hardware. It found four
real defects that would each have failed on a live unit:

1. the final clear-AP step failed the run — the device goes silent by design
   (the old `config.py` wrapped it in `try/except`), so `command` gained an
   `optional` flag where silence is the pass case;
2. `Module 0` answers `{"Module":{"0":"CE_Aqua_v2"}}` and `SwitchMode0`
   answers a 28-entry array — neither can be confirmed by value, so both read
   the key and assert the captured template name instead;
3. localhost as `public_base_url` (the device cannot reach it) — already
   guarded, and the guard is what fired;
4. the Aqua target had inherited the June-2024 `release-0.0.1` berryware from
   its retro base, which must never ship today.

**WiFi and MQTT settings each go in ONE `Backlog`** (user decision
2026-07-29). Sent as separate commands, Tasmota restarts between them, so the
device briefly attempts the new SSID with the old password; the old tool hid
that behind a fixed sleep after every write. Backlog applies the whole group,
then restarts once. Because `Backlog` only answers `{"Backlog":"Done"}`, each
batch is followed by an explicit readback + `assert_equals`, so the values are
still proven — after the restart rather than between the writes.

Simulation status, all steps passing: `Dongle_V2 production` 28/28,
`Aqua_V2 production` 39/39, `Dongle_V3 blank device` 32/32. Each sits on its
deployment's `bench` channel; `production` waits for a real unit.

### The two nginx hops both proxy the run WebSocket

The engine runs over `/api/flasher/ws/<run>`. The web image's
`nginx-api-proxy.inc` and the server's outer `nginx.conf` (`location /lib/`)
both pass `Upgrade`/`Connection` via a `map $http_upgrade $connection_upgrade`
— conditional, so ordinary keep-alive requests are untouched. Without both,
the bench gets a 404 on the upgrade and no run can start.

### Implementation record (2026-07-29)

Built in this pass — schema (5 new tables + column moves, startup-migrated),
`services/flasher/` (engine, protocol, credentials — credential derivation
verified 3/3 against real `mosquitto_passwords.txt` pairs, line parser
verified against the recorded real serial output), `routers/flasher.py`
(CRUD + publish gates + unauthenticated device-file serving + devices/runs/
logs + coverage + WS), web: Flasher admin, Flash bench (ported PoC station,
WS run client), Devices list, device detail, flash-run detail with live log
tail. Publish gate: a script version publishes only when its pinned release
version and every pinned file version are published — a run can never flash
a draft. Seed script: `scratchpad/seed_flasher_v3.py` (blank-device Dongle_V3
scenario, 33 steps, publishes everything).

