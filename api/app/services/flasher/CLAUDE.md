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
  Publishing also requires a comment. When you add a step op, add its rules
  here in the same change.
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
- **`GET /api/flasher/files/{version_id}/{filename}` is deliberately
  unauthenticated** — the DEVICE fetches it with Tasmota's `UrlFetch`, which
  sends no auth headers. Published versions only; the URL ends with the
  filename because Tasmota saves by the last path segment. The reachable base
  is `settings.public_base_url` (LAN address, never localhost).
- **The engine (`services/flasher/engine.py`) owns the scenario; the browser
  only executes `action` ops and pipes bytes.** Ops in `BROWSER_OPS` run on
  the bench (esptool phase — latency-sensitive); every other op is Python.
  All DB writes go through `RunEngine._db` (own short-lived session per call,
  in a thread); logs are buffered and bulk-flushed every 0.5 s. A run row is
  created BEFORE step 1 and finalized in a `finally:` — a socket death, an
  engine bug or a failed `_load` must still close the row.
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

