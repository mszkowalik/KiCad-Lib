# Flasher (`api/app/services/flasher`)

Production programming. The wider design is in
[docs/flasher/design.md](../../../../docs/flasher/design.md). The UI rules are in
`web/src/components/flasher/CLAUDE.md`.

## The load-bearing rules

Full design: `docs/flasher/design.md` (§14 = the bundle model, §13 = its history).

- **`programming_logs` is keyed by `(run_id, seq)` and has NO surrogate id**
  (2026-09-12, `services/proglog_migrate.py`). It is the largest row count in
  the database — 2.44 M rows over 6321 runs — and it only grows, because every
  line of every run is kept by user decision (2026-07-27). The old `id` column
  carried a 52 MB index that `pg_stat_user_indexes` said had never been scanned
  once; dropping it took the table from 375 MB to 304 MB. Do not add a
  surrogate key back: the reader filters `run_id` and `seq` and orders by `seq`,
  and the writer is a `bulk_insert_mappings` that supplies neither. **On this
  table, cost per row is the design constraint** — a column here is four bytes
  times two and a half million.

- **ONE revision binds everything: the DEPLOYMENT VERSION.** It pins firmware
  images (`deployment_images`), berryware (`deployment_files` → exact
  `device_file_versions`), the procedure (`steps`), and the parameter wiring.
  The `Release` entity was folded in and DROPPED (2026-07-29) — its identity
  is now a derived **fingerprint**, so "firmware unchanged since v5" needs no
  second versioned object. Never reintroduce a parallel versioned wrapper
  around firmware; add a fingerprint if you need to compare.
- **Fingerprints are cache, never authority.** `bundle.stamp()` recomputes
  both from the child rows; call it after ANY change to images or files.
  `firmware_fingerprint` is order-sensitive (address+sha), `files_fingerprint`
  is a set (reordering downloads is a procedure change, not a payload change).
  Equal file fingerprints mean the same berryware bundle — that is how every
  historical V2 set recovered its real name by propagation.
- **`validate.check()` is the single gate.** The live composer and the publish
  button call the same function, so the editor can never disagree with the
  refusal. Errors block publishing (unpublished pins, chip/transport mismatch,
  overlapping flash offsets, unresolved `{placeholder}` or assert variable,
  autoexec.be not last, serial op before `serial_open`); warnings inform.
  Publishing also requires a comment. **A new step op has to be declared in
  FOUR places**, and missing one fails late: the engine's `_exec` dispatch, its
  rules here, `STEP_OPS` in `routers/flasher.py` (which refuses an unknown op on
  compose, with a 400 that says nothing about the other three) and
  `web/src/components/flasher/stepSchema.ts` so the editor can author it.
- **Device file text is stored LF-normalised** (`_normalise_text`). A CRLF file
  read as bytes hashes differently from the same file read as text, which made
  five V3 files report "changed" on every import when nothing had. Content
  addressing only pays off if the same source always yields the same hash.
- **Deleting an artifact is usage-guarded, and the guard lives in the API.**
  A firmware asset pinned by any deployment version, a bundle used by any
  version, a device file version pinned by a version or a bundle: all refuse
  with 409 and name the users. Programming runs record what they flashed, so
  the pinned artifacts must outlive any tidy-up. `_firmware_usage` /
  `_file_version_usage` are the single source for those answers — reuse them
  rather than re-deriving a join per call site.
- **A bundle's file SET is its identity; only the label is editable.** A
  different set is a different bundle (`ensure_bundle` resolves by fingerprint,
  so the same folder never forks a twin). Renaming one updates
  `files_label` on every version using it, because the version DISPLAYS the
  bundle's name rather than storing its own.
- **Channels are pointers, history is immutable.** `deployment_channels` name a
  version (`production`, `bench`); rolling back moves a channel. A batch pins a
  version or follows a channel; run creation resolves it and records the
  result. Draft versions run ONLY as bench trials (`draft_run=True`, no batch).
- **Functional checks are DERIVED, never authored** (`services/flasher/checks.py`).
  A step names what it proves (`check: "relay.2"`) and its own pass/fail becomes
  the check; imported runs, which have no steps, get the same names from their
  stored evidence. `recompute(db, run)` rebuilds a run's rows from scratch, so
  `POST /api/flasher/checks/recompute` can upgrade all history after you improve
  an extractor — never hand-write a `run_checks` row, and never let a check
  disagree with the run's own log. Add a new name to `CATALOG` (an unknown name
  still records, in "other"). An extractor that re-judges historical
  measurements must reproduce the original rule, inversions included.
- **A run's `operator` is the SIGNED-IN ACCOUNT, never a field** (`actor_of`,
  2026-09-16). The bench asked for a name in a text box; it was usually empty,
  and a record of who produced a unit is worth nothing when the person types
  it themselves. `POST /runs` and `POST /bench-runs` take no `operator`, and
  the engine seeds `{operator}` from the run row. It is a stamp, not device
  configuration: no procedure in the library interpolates it.
- **The bench opens on the project's CONFIG version, and on NO batch**
  (2026-09-16). The version defaults to the `kind: "flash"` deployment's
  current version — read from the kind, never from the name — because that is
  what a batch is programmed with all day. The batch is the opposite: it is
  never remembered and never preselected, because a remembered batch is the one
  a tray gets programmed into by accident the next morning. In batch mode with
  no batch picked the stations get no version at all, so a run cannot quietly
  become a bench trial. NOTE: no batch in the database pins a version or
  follows a channel, so `POST /runs` 409s unless the request names one — the
  default is what makes the bench work, not a convenience.
- **A field on the bench belongs to the PROCEDURE, not to the bench.**
  `version_json` carries `needs_sim_pin` (any step with op `lte_sim_pin`), and
  the bench shows its SIM PIN box only then — a Dongle_V2 or an Aqua has no
  modem, and a box nobody can use is one somebody fills in by mistake. Add the
  same kind of flag rather than keying anything off a project or a name.
- **"Is this device programmed" has ONE implementation: `checks.verdict`**
  (2026-09-16, [decision 0021](../../../../docs/decisions/0021-a-device-is-judged-by-the-rule-it-was-made-under.md)).
  The newest config run passed → any test that started after it passed →
  nothing erased it since. A test that RAN and failed always counts; a test
  that did not run counts only when that run's own `test_required` says so.
  Marking is never consulted. Never re-derive this from `last_status` or from
  the newest row: a device's history holds marking jobs and erases too.
- **The requirement lives in three places and only one of them is the rule.**
  `Deployment.active` is the default ticked on a NEW batch, `ProductionRun
  .requires_test` is the decision, and `ProgrammingRun.test_required` is the
  copy taken when the run starts — that copy is what judges a device that
  already exists. Pinning it is the same reason the fingerprints beside it are
  pinned: one project-wide switch would otherwise have re-judged 555 finished
  units.
- **A device's grid is its newest MEASURING run, never its best one**
  (`for_device`, `counts_for_devices`). Only `flash` and `test` measure
  anything; a marking job would otherwise blank the grid and an erase would
  replace the evidence. An older pass must not outlive a newer run that failed,
  aborted or is still open — best-ever-per-check kept a device fully green
  through a failed retry. The lifetime tally rides along in `attempts` for the
  hover. A live run has no `run_checks` rows until it finalizes, so
  `for_device` stands in the procedure's declared checks, grey. The device list
  uses the same rule, or the two views disagree.
- **The SERVER decides which identity rows a device page draws, label and all**
  (`_identity_rows` in `routers/flasher.py`). It returns
  `[{key, label, value}]` and the page renders the list: a field that exists on
  the model must be able to appear without a frontend change, so never put a
  field name back in `DeviceDetail.tsx`. MAC and serial are always drawn; each
  of the others is drawn when the device carries it, when a procedure of its
  project CAPTURES it (`capture` keys — the same names `engine.IDENTITY_VARS`
  writes to the device row), or when a sibling device in the project carries
  it. Without that rule every Dongle_V2 printed five empty modem rows. The
  third source keeps imported history readable once the procedure that produced
  it is gone.
- **The configuration card shows the LAST run to configure the device**, not
  every value it ever carried: three keys written four times printed twelve
  rows that read like twelve settings. Earlier values stay in
  `device_config_values` and are still reachable through their own run.
- **`GET /api/flasher/files/{version_id}/{filename}` is deliberately
  unauthenticated** — the DEVICE fetches it with Tasmota's `UrlFetch`, which
  sends no auth headers. Published versions only; the URL ends with the
  filename because Tasmota saves by the last path segment.

- **An op that makes the device fetch something builds its URL in
  `RunEngine._url`, never by gluing a base onto a path** (2026-09-16). The op
  takes an optional `url` template, `{base_url}` resolves inside it, and the
  per-item names it adds (`file_version_id`, `filename` for `download_files`)
  are declared in `validate.OP_LOCAL_VARS` — without that row the dataflow gate
  rejects a correct step. Add both in the same change as the op.

- **`base_url` is resolved at hello, and CONFIGURATION OUTRANKS THE BENCH.**
  The platform cannot know the address a device can reach it by: the container
  sees a bridge IP, and `public_base_url` is a dev default of `localhost`. So
  the browser reports the two addresses it is provably reaching the platform by
  (`client_info.api_base`, `client_info.page_base`), and `_resolve_base_url`
  takes the first USABLE candidate in this order: the `base_url` param,
  `public_base_url`, the bench API origin, the bench page origin. The bench
  ranks last because the winner is an address the engine then tells a DEVICE to
  fetch from — so a value the browser merely asserts is used only where the
  platform has no usable one of its own, which is the dev case and nothing else.
  **In production the configured value wins and the bench candidates are never
  weighed.** `usable_base()` vets every candidate the same way (http(s), a host,
  no userinfo, not loopback) because one of them is input, not configuration; a
  rejected candidate is SKIPPED with its reason in the run log, not used and
  failed on at step 18.
- **The engine (`services/flasher/engine.py`) owns the scenario; the browser
  only executes `action` ops and pipes bytes.** Ops in `BROWSER_OPS` run on
  the bench (esptool phase — latency-sensitive); every other op is Python.
  All DB writes go through `RunEngine._db` (own short-lived session per call,
  in a thread); logs are buffered and bulk-flushed every 0.5 s. A run row is
  created BEFORE step 1 and finalized in a `finally:` — a socket death, an
  engine bug or a failed `_load` must still close the row.
- **`flash_config.size: "detect"` is resolved in `station.ts`, never handed to
  esptool-js** (2026-09-16, found on the first V2 hardware run). esptool-js
  understands `"detect"` in ONE place, the image-header rewrite. Its own fit
  check passes the literal string to `flashSizeBytes()`, which looks for "KB"
  or "MB", returns -1, and refuses every image with "File 1 doesn't fit in the
  available flash" — **after the erase step has already wiped the device**.
  Every V2 deployment version carries `detect`, because the procedures were
  reconstructed from a Python esptool that accepts `--flash_size detect`, so no
  V2 version could ever have flashed from the browser. `validate.check()` now
  gates all three flash parameters against the values esptool-js declares.

- **The Dongle V2 bridge is a CH340 and reports NO USB serial number**
  (verified 2026-09-16: `idVendor` 0x1A86, `idProduct` 0x7523, "USB2.0-Serial",
  and `ioreg` shows no serial-number key). Three consequences, all load-bearing
  for the bench:
  1. **Two V2 units are indistinguishable over USB.** `SerialPort.getInfo()`
     returns only `usbVendorId`, `usbProductId` and a Bluetooth class id — no
     path, no location, no serial number — so `Station.sameDevice()` is as
     specific as it can ever be and a multi-slot page must arbitrate an
     arriving port by ARRIVAL, never by identity, and **a station cannot be
     bound to a USB socket at all** — the port belongs to the dongle, and
     `getInfo()` hides the one name that encodes the socket. Four attempts at
     it failed; do not try a fifth without reading
     [docs/reference/bench-serial-ports.md](../../../../docs/reference/bench-serial-ports.md),
     which records each one, what was measured, and what would have to change
     (a C6 may not need any of it). A refused assign SAYS whose port it is, and
     the label carries `#n` from `getPorts()`, because the USB ids alone cannot
     tell two stations' ports apart.
  2. **The Web Serial grant does NOT survive an unplug** (measured
     2026-09-16: after a replug the run log shows `granted ports: 0`, and
     `port.connected` on the held handle is `false`). With no serial number
     Chrome cannot durably identify the device, so the permission is dropped
     with the device and `getPorts()` comes back EMPTY. No amount of
     re-acquiring helps — there is nothing to re-acquire, and only a fresh
     `requestPort()` popup would restore it. **One pick per unit is therefore
     the BASELINE the bench must work well under**, because the software also
     runs on machines nobody here can configure. `Station.ensurePort()` asks
     inside the operator's own Start click — a user gesture does not survive an
     intervening fetch, so the port is obtained BEFORE the run is created, never
     after. A serial policy removes the pick, but it is an optimisation for a
     bench somebody owns, never something the product may depend on. **A bench therefore needs a Chrome
     serial policy**, and on a dev Mac it needs no root: the user-level
     `com.google.Chrome` domain is honoured (verified 2026-09-16, where an
     older `SerialAllowAllPortsForUrls` entry for `http://127.0.0.1:5174` was
     already live and working). The policy's origins are EXACT — `localhost`
     and `127.0.0.1` are different origins, and so is a different port, which
     is why that old entry never covered the bench on 5173. **The product
     ships this inside the bench agent, not as a script** (2026-09-17): the
     agent's first start writes the grant into the user's `com.google.Chrome`
     domain for the origin baked into its launcher, and both benches offer the
     agent download. `GET /api/flasher/bench-policy.mobileconfig` still
     generates a macOS profile for the origin the BROWSER says it is on
     (`Origin`, else `Referer`) — for a machine whose Chrome is managed, where
     `/Library/Managed Preferences` outranks the user domain and only an
     administrator can install anything. Only the browser knows the real
     address, and a grant written for the wrong one silently does nothing. It grants `SerialAllowUsbDevicesForUrls` for
     `BENCH_USB_BRIDGES` only — never "any serial port", which is not a grant to
     hand out by download. Windows is not covered yet. A part that DOES
     report a serial number, such as the C6's native USB, never had this
     problem — which is why V3 benches never hit it.
  3. **Device identity comes from the FIRMWARE, never the bridge.** The MAC and
     the Tasmota topic are read over the console (`Status 0`), which is why the
     marking procedure has to talk to the device before it can mark it.

- **A `SerialPort` handle does not survive the device leaving the bus**
  (2026-09-16). After a replug Chrome hands out a NEW object from
  `getPorts()`; `open()` on the old one fails with "Failed to open serial
  port." The GRANT survives, so this never needs another port-picker popup —
  `Station.resolvePort()` re-acquires by USB ids and every open path calls it
  first, including each retry. An operator swapping one device for the next is
  the normal case on a bench, not an edge case.

- **`Station.espOpen` is a LADDER, and each rung is a defect it was built for**
  (2026-09-16): `default_reset` at the profile's baud, then at 115200, then
  `no_reset` at the profile's baud after pulsing EN ourselves with the operator
  holding BOOT. Rung 3 exists because a board whose IO0 is not driven (unit
  `20:e7:c8:92:b6:10`) lands back in flash boot on EVERY reset — and esptool-js
  runs seven per connect, so **more attempts make it worse, not better**. That
  rung needs a hand on the device, so it KEEPS RETRYING while it says so
  (`onBootWait`, every 1.2 s for 30 s, with a Stop waiting button) and then
  fails — asking once would only move the retry into the operator's hands while
  they are still reaching for the board. There is no "BOOT held" switch: the
  ladder reaches that rung by itself, and a switch would be one more thing to
  leave in the wrong position. The rung that worked is reported as `connect_mode` and stored in the
  run's results: a unit that only answers with BOOT held has a fault, and
  rescuing it silently every run is how that stays invisible.

- **A deploy breaks every bench tab that is already open, and it looks like a
  device fault** (prod run 6329, 2026-09-17). esptool-js loads its per-chip
  module lazily, Vite emits it as a hashed chunk, and a new image replaces
  every chunk — so a tab opened before the deploy fails its first connect with
  `Failed to fetch dynamically imported module …/esp32-<hash>.js`, on every
  rung, and the ladder ended in "BOOT was not held within 30s" while the
  operator held BOOT. Two guards: `main.tsx` reloads once on Vite's
  `vite:preloadError`, and `Station.espOpen` aborts the ladder on that error
  with "reload the page" instead of blaming the device. Never treat a
  module-load failure as a rung. The esptool phase itself runs in the browser
  over USB; the internet carries only the engine's step messages, so latency
  was never the cause.

- **esptool-js changes baud by CLOSING and REOPENING the port**
  (`changeBaud()` → `transport.disconnect()` then `connect()`), and a Web Serial
  close/open toggles DTR and RTS. On a board that resets from that, the stub is
  gone and the next command reads `Invalid head of packet`. Python esptool
  changes speed on the open descriptor and never sees this. `espOpen` therefore
  falls back to 115200 on any failure, where `romBaudrate === baudrate` and
  esptool-js skips the change entirely; erase uses 115200 outright, because a
  three-second command gains nothing from the switch. **A board that needs BOOT
  held is not a board that cannot take 460800** — those are two faults, and the
  BOOT rung used to charge every unit the price of both. It now starts at the
  profile's baud and drops to 115200 only when esptool got as far as logging
  `Changing baudrate` (`Station.sawBaudChange`), which means the sync and the
  stub were fine and the speed switch alone failed. Holding BOOT harder does not
  fix that one, so it is the only failure worth demoting on.

- **Marking is a RUN, and `mark_laser` is the only op the bench does not execute
  itself** (2026-09-16, decision
  [0020](../../../../docs/decisions/0020-marking-goes-through-lightburn.md)). A
  marking procedure is an ordinary deployment version with `kind = "mark"`: its
  own steps, its own history rows, the same publish gate. The template is a
  pinned DEVICE FILE, like berryware, so the version still answers "which
  drawing did this unit get" — that is why there is no `marking_templates`
  table, and why adding one would fork the answer. The engine names the file and
  the text; the BENCH fetches the artwork, patches the one text shape, and
  relays the finished job to the bench agent. The engine never touches the XML
  and never sees the laser. Read
  [docs/reference/laser-marking.md](../../../../docs/reference/laser-marking.md)
  before changing any of it — it holds what the controller is, and the four
  measurements that say why we do not drive it directly.

- **A serial is 8 to 12 characters with no whitespace** (`SERIAL_MIN`,
  `SERIAL_MAX`, user decision 2026-09-17), and `_identity_value` refuses
  anything else for BOTH marking ops. The bench checks the same bounds before it
  creates a run, but the engine is the gate that matters: it is what a value
  passes through on its way to a part, whatever started the run. Outside that
  range means the capture went wrong — a whole Tasmota topic, an empty split, a
  fragment of a log line — rather than a serial somebody meant to engrave.

- **A label is GENERATED, so `print_label` pins no file** (2026-09-17, decision
  [0022](../../../../docs/decisions/0022-labels-are-generated-by-the-bench-agent.md)).
  The step IS the label definition, and it is versioned because the steps are.
  The bench agent builds the Code 128 symbol and the page from the printer's own
  PPD and runs `lp`; the engine says what goes on the label and records what the
  bench reports back, including the roll — which the station may override,
  because the roll is what is loaded on the day and the printer cannot say.
  Measurements in [reference/label-printing.md](../../../../docs/reference/label-printing.md).

- **A bench may skip `mark_laser`, `print_label` and `wait_boot`, and nothing
  else** (`SKIPPABLE_OPS`). `wait_boot` is in that set because its whole job is
  to WAIT until the device answers, and the marking bench has already had an
  answer — it reads the identity the moment a device is plugged in. Skipping it
  assumes nothing: the `command` step still reads the identity inside the run,
  so a device that went quiet in between fails there instead of waiting out a
  boot that already happened. Measured on runs 6372-6374: `wait_boot` cost
  0.7-1.1 s of every press and `serial_open` cost 8 ms. One marking procedure reads the device once and then
  engraves, prints, or both — which is what the two buttons on the bench are.
  The request arrives in the run's hello, because which action was pressed is
  the bench's business. Widening that set would let a bench decide what a unit
  was made under, and
  [0021](../../../../docs/decisions/0021-a-device-is-judged-by-the-rule-it-was-made-under.md)
  says that is the version's answer. What was left out is written into the run
  log, and the skipped steps simply have no rows.

- **An erase is recorded ONLY once it knows the MAC**
  (`POST /api/flasher/bench-runs`, `programming_runs.action = "erase"` with a
  NULL `deployment_version_id`). An erase runs no procedure, so it was
  deliberately unrecorded — until a unit that could not be programmed left no
  trace anywhere. It identifies a device, and that is what makes the attempt
  worth keeping. One that never reaches a MAC still records nothing: there is no
  device to attach it to.

- **Transport rules are measured requirements, not style** (design.md §7): on
  `usb_serial_jtag` (ESP32-C6) the monitor phase never touches DTR/RTS, a
  reset re-enumerates USB, and esptool-js's `after("hard_reset")` alone never
  restarts the chip — the pulse in `web/src/flasher/station.ts` does.
- **`lte_sim_pin` is sent once and NEVER retried** — the firmware driver
  PUK-guards a re-sent rejected PIN (xdrv_128 ~483). Resolution: bench field →
  param-set `sim_pin` → WS prompt. The PIN is masked in the stored log and in
  `params_snapshot` (`SECRET_RE` masks any param whose key matches
  password|pin|salt|secret|token).
- **Captured variables with reserved names update the device row**
  (`IDENTITY_VARS`: topic→tasmota_id, imei, iccid, imsi, modem_model,
  modem_fw). Device identity is the MAC (`device_units.mac` UNIQUE),
  upserted at `esp_connect` ~2 s into a run, so even early failures are
  attributed. `mosquitto` export regenerates the broker file from
  `device_config_values` (`mqtt_creds_line`, `current=True`).
- **Credential derivation (`services/flasher/credentials.py`) is frozen** —
  verified byte-for-byte against real `mosquitto_passwords.txt` pairs. Any
  change strands the deployed fleet.

