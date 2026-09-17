# Flasher (`api/app/services/flasher`)

Production programming. The wider design is in
[docs/flasher/design.md](../../../../docs/flasher/design.md). The UI rules are in
`web/src/components/flasher/CLAUDE.md`.

## The load-bearing rules

Full design: `docs/flasher/design.md` (§15 = file sets, §14 = the bundle model it replaced, §13 = the history before that).

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

- **THE BROWSER OPENS NO SERIAL PORT. The agent does every byte** (2026-09-17,
  decision
  [0023](../../../../docs/decisions/0023-the-agent-programs-the-device.md)).
  `esp_connect`, `erase`, `flash` and `esp_reset` are relayed by
  `Station.agentEsp` to `POST /esp`, which runs Python's esptool against the
  station's socket; the device console is `POST /monitor/open` plus a poll of
  `GET /monitor?since=`. `connect_mode` comes back prefixed `agent:`. The PAGE
  still fetches the firmware and passes the bytes on loopback, because the
  agent holds no token. **There is no browser fallback** — `station.ts` lost
  948 lines, esptool-js included — so a bench with no agent cannot program,
  and both benches say so.

  Three consequences for anything you change here:

  1. **The connect ladder lives once, in `EspRun` (`agent.py`).** The rungs
     below are its rungs. Do not re-implement them in the page.
  2. **A station must own a socket.** The agent addresses a port by its
     `/dev/cu.*` node, so `Assign socket…` is a list of the agent's own names
     and not Chrome's picker. Nothing is adopted by arrival.
  3. **The transport profile comes from the deployment VERSION.** Nothing
     sniffs USB ids any more, because no `SerialPort` object exists here. A C6
     procedure names `usb_serial_jtag` itself; everything else gets the bridge.


- **ONE revision binds everything: the DEPLOYMENT VERSION.** It pins firmware
  images (`deployment_images`), a berryware release (`file_set_id`), a
  drawing (`artwork_set_id`), the procedure (`steps`), and the parameter
  wiring. The `Release` entity was folded in and DROPPED (2026-07-29) — its
  identity is a derived **fingerprint**, so "firmware unchanged since v5"
  needs no second versioned object. Never reintroduce a parallel versioned
  wrapper around firmware; add a fingerprint if you need to compare.
- **A RELEASE IS A FILE SET, and a file has no version of its own**
  (2026-09-18, decision
  [0029](../../../../docs/decisions/0029-a-release-is-a-file-set.md)).
  `file_blobs` is bytes keyed by sha256, platform wide; `file_sets` is an
  immutable manifest of `(filename, blob)` whose `fingerprint` is its
  identity, unique on the platform, with a `kind` (`berryware` | `artwork`)
  decided from the extensions of the whole manifest — a mix is refused. A set
  is NOT project-scoped: the same folder imported for two projects is one
  row. `bundle.ensure_set` is the ONE constructor (import, derive, migration);
  `bundle.version_entries` is the one reader of "what does this version pin",
  and the engine, the validator, `checks._pinned_files` and every JSON go
  through it. There is no draft state on a set, so nothing here publishes.
  Five things follow:

  1. **`bundle.stamp()` recomputes the FIRMWARE fingerprint only**, after any
     change to images. The files need no cache — the set's fingerprint is on
     the set. A run stamps `bundle.version_files_fingerprint(v)`, which is the
     old formula over both sets, so historical run stamps still match.
  2. **`_pick_set` in `routers/flasher.py` is the one place a version's set
     pointer is resolved**: `None` inherits, a negative id clears (a PATCH
     sends explicit `null`), and the set's kind must match the field — a
     drawing pinned as berryware would reach the device as a download.
  3. **A set enters by `POST /file-sets/import` or `POST /file-sets/{id}/derive`.**
     Derive copies a manifest, applies uploads (replace by name or add),
     borrows entries from any other set (`take`), drops names (`remove`), and
     runs `ensure_set` on the result — so deriving back to an existing
     manifest FINDS that set rather than forking it. There is no paste
     endpoint and no per-file endpoint.
  4. **Delete is per set, guarded by `bundle.set_users`** — the same join the
     list prints as `used_by`. Any deployment version, draft or published,
     refuses it with 409 naming them. `bundle.prune_blobs` runs after a
     delete: a blob no set names is bytes, not history.
  5. **Text is stored LF-normalised (`bundle.normalise_text`) and a non-UTF-8
     upload (or one with a NUL) is kept as bytes** with `is_binary` set — the
     column is `is_binary` because `binary` is reserved in SQL; the JSON key
     is still `binary`. Content addressing only pays off if the same source
     always yields the same hash.

  `services/flasher/fileset_migrate.py` did the fold once, in one checked
  transaction, and reports on `/api/health/schema` as `file_sets.fold`. It
  dropped `device_files`, `device_file_versions`, `berry_bundles`,
  `berry_bundle_files` and `deployment_files`; do not add DDL for any of them
  back.
- **A version DECLARES the parameters it needs; the values keep a revision log**
  (2026-09-17, decision
  [0024](../../../../docs/decisions/0024-a-version-declares-the-parameters-it-needs.md)).
  `services/flasher/params.py` is the ONE implementation of "which keys does
  this version use" — the publish gate, the parameter editor and the freeze all
  call it, and `validate.py` no longer keeps its own copy of the walk. Four
  things follow:

  1. **A ParamSet is still NOT versioned** (2026-07-27, unchanged): rotating a
     WiFi password must not mint a version of every deployment. What is
     versioned is `DeploymentVersion.param_schema`, frozen on publish.
     **THREE places name a set, and only one of them is what a run uses.**
     `Deployment.param_set_id` is the default a NEW version starts from — the
     deployment's own link, and what the head card edits.
     `DeploymentVersion.param_set_id` is the pin, taken at creation and never
     moved, and it is the one the engine reads. A version composed from another
     inherits that one; a FIRST version inherits the deployment's. Moving the
     deployment's set therefore never rewrites a published version, and the
     version card says so when the two differ.
  2. **`PUT /param-sets/{name}` refuses to remove a key a PUBLISHED version
     declares**, naming them; `force` is recorded on the revision. Drafts are
     not counted on purpose — their author is usually the person editing.
     `DELETE` refuses while any version points at the set.
  3. **Every write appends a `ParamSetRevision`**, and a run stamps
     `param_set_revision_id`. `changed` NAMES the keys whose value moved and
     never prints the old one; the values themselves live in the revision's own
     `values_enc`, which is what `POST /param-sets/{id}/revert` reads. This is
     the only record that a MEANING changed — same key, new broker — which
     passes every other check there is.
     **A revert APPENDS.** Reverting r5 to r2 writes r6 with r2's values, so
     the history still says r3-r5 happened and that somebody undid them, and
     the breaking guard applies to it exactly as it does to a save.
  4. **`params.OP_PARAM_FIELDS` is a FIFTH declaration site** beside the four
     below. An op that reads a parameter by name instead of interpolating
     `{it}` must be listed there. `derive_credentials` reads `creds_salt`
     straight out of the run's variables and raises without it, so before this
     the one key whose loss cannot be recovered from at the bench read as
     "needed by nobody — safe to remove".

- **Drafts are validated at run start too.** They were exempt, and that is the
  worst place to skip it: `protocol.subst` leaves an unresolved placeholder as
  LITERAL TEXT, and `set_and_check` compares what it sent against what it read
  back — both `"{MqttHost}"` — so the step PASSES and the device ships pointed
  at a broker called `{MqttHost}`. Only a later step that observes the effect
  catches it, which the WiFi poll does and nothing else does.

- **`validate.check()` is the single gate.** The live composer and the publish
  button call the same function, so the editor can never disagree with the
  refusal. Errors block publishing (chip/transport mismatch,
  overlapping flash offsets, unresolved `{placeholder}` or assert variable,
  autoexec.be not last, serial op before `serial_open`); warnings inform.
  Publishing also requires a comment. **A new step op has to be declared in
  FOUR places**, and missing one fails late: the engine's `_exec` dispatch, its
  rules here, `STEP_OPS` in `routers/flasher.py` (which refuses an unknown op on
  compose, with a 400 that says nothing about the other three) and
  `web/src/components/flasher/stepSchema.ts` so the editor can author it.
- **Deleting a firmware asset is usage-guarded, and the guard lives in the
  API.** An asset pinned by any deployment version refuses with 409 and names
  the users; `_firmware_usage` is the single source for that answer. A file
  set has the same rule through `bundle.set_users` (above). Programming runs
  record what they flashed, so the pinned artifacts must outlive any tidy-up.
- **A setting that decides what happens to HARDWARE lives on the platform, and
  preferably on the STEP** (2026-09-17, user decision). Four of them were
  TypeScript constants in the browser bundle, so changing any one meant a web
  build and a deploy, and it moved every deployment at once:

  | was | is now |
  |---|---|
  | `TRANSPORT_PROFILES` in `station.ts` | `services/flasher/transports.py`, served by `/meta`, resolved into each run's spec as `spec.transport` |
  | the flash baud, per profile | **`baud` on the `esp_connect` / `erase` / `flash` step**, gated by `validate.check` against `transports.FLASH_BAUDS` |
  | `DEFAULT_PLACEHOLDERS` (what gets engraved) | `engine.DEFAULT_MARK_PLACEHOLDERS`, always stated in the step's args; the step's own `placeholder` still wins |
  | `ROLLS`, `SERIAL_MIN/MAX` | the agent's own PPD report, and `/meta`'s `serial_len` |

  The engine forwards EVERY step field to the bench (`args = dict(step)`), so a
  new per-step setting needs no plumbing — add it to `stepSchema.ts` so it can
  be edited, and gate it in `validate.check` if a wrong value damages something.
  Do not reintroduce a browser copy, not even as a fallback: a second table is
  a second answer.

  **Why the baud belongs on the step and not on the profile**: measured on a
  Dongle V2 (CH340) with the 2.27 MB image, 460800 = 45.4 s, **750000 = 32.5 s
  (3/3 clean)**, while 576000 and 921600 both corrupt the transfer — the
  bridge's 12 MHz clock divides exactly into 750000 and not into the other two.
  That is a property of one board. The Aqua shares the profile and has never
  been flashed at 750000, so it keeps the default until someone tries it.

- **A DRAFT can be deleted; anything published cannot** (2026-09-17).
  `DELETE /deployment-versions/{id}` exists because `New version` now mints a
  draft on one click, and a draft somebody opened and closed must not leave a
  rejected row behind forever. It refuses for `published` — that is what a
  device was given — and for any version a `ProgrammingRun` records, since a
  draft runs as a bench trial. `reject` stays beside it for that case: the row
  is kept as history. The ORM cascade is what removes the version's images,
  so the delete has to go through the endpoint.
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
- **The bench opens on the project's CONFIG version and its LATEST batch;
  the marking bench on the project's marking procedure** (2026-09-17, user
  decision — the batch half reverses 2026-09-16, which preselected none). The
  version defaults to the `kind: "flash"` deployment's current version — read
  from the kind, never from the name — and the batch to the newest `run_date`
  (then id), status not consulted. Both are applied ONCE per project pick, so
  an operator who clears the batch to "bench trial" stays there. The batch is
  still not remembered across sessions: it is re-derived, not restored. In
  batch mode with no batch picked the stations get no version at all, so a run
  cannot quietly become a bench trial. NOTE: no batch in the database pins a
  version or follows a channel, so `POST /runs` 409s unless the request names
  one — the default is what makes the bench work, not a convenience.
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
- **`GET /api/flasher/files/{set_id}/{filename}` is deliberately
  unauthenticated** (`authgate._OPEN_PREFIXES`) — the DEVICE fetches it with
  Tasmota's `UrlFetch`, which sends no auth headers, and the bench fetches
  the artwork from it. The URL ends with the filename because Tasmota saves
  by the last path segment.

- **An op that makes the device fetch something builds its URL in
  `RunEngine._url`, never by gluing a base onto a path** (2026-09-16). The op
  takes an optional `url` template, `{base_url}` resolves inside it, and the
  per-item names it adds (`file_set_id`, `filename` for `download_files`)
  are declared in `validate.OP_LOCAL_VARS` — without that row the dataflow gate
  rejects a correct step. Add both in the same change as the op.

- **`base_url` is resolved at hello, and CONFIGURATION OUTRANKS THE BENCH.**
  The platform cannot know the address a device can reach it by: the container
  sees a bridge IP, and `public_base_url` is a dev default of `localhost`. So
  the browser reports the two addresses it is provably reaching the platform by
  (`client_info.api_base`, `client_info.page_base`), and `_resolve_base_url`
  takes the first USABLE candidate in this order: the `base_url` param,
  `device_base_url`, `public_base_url`, the bench API origin, the bench page
  origin. **`device_base_url` is a DEVICE address, not a browser one** — on
  production it is the `http://` twin of the public name, because Tasmota
  completes no TLS against the Cloudflare edge and validates no certificate
  anyway ([0025](../../../../docs/decisions/0025-a-device-fetches-from-its-own-address.md)).
  It is empty everywhere else and drops out. The bench
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
  V2 version could ever have flashed from the browser. **Decision 0023 returned
  the platform to that same Python esptool**, which takes `detect` directly, so
  the resolution step is gone with the rest of the browser path — but
  `validate.check()` still gates all three flash parameters, because a version
  is authored once and may outlive whichever tool reads it.

- **The Dongle V2 bridge is a CH340 and reports NO USB serial number**
  (verified 2026-09-16: `idVendor` 0x1A86, `idProduct` 0x7523, "USB2.0-Serial",
  and `ioreg` shows no serial-number key). **Decision 0023 made most of what
  followed from that moot** — the browser no longer opens a port, so there is
  no grant to lose and no picker to re-answer. What survives it:

  1. **A station is bound to a SOCKET, by name, from the agent's list**
     ([bench-serial-ports.md](../../../../docs/reference/bench-serial-ports.md)
     holds the two hardware facts that make it hard, and names the four
     browser-side attempts that failed so nobody rebuilds one; the answer is
     now trivial because the agent can simply see the node).
  2. **Device identity comes from the FIRMWARE, never the bridge.** The MAC and
     the Tasmota topic are read over the console (`Status 0`), which is why the
     marking procedure has to talk to the device before it can mark it.
  3. **`GET /api/flasher/bench-policy.mobileconfig` is now only about loopback
     access**, for a machine whose Chrome is managed. The serial grant in it is
     vestigial.

- **The connect LADDER is `EspRun`'s, in `agent.py`, and each rung is a defect
  it was built for** (2026-09-16, moved to the agent 2026-09-17): `default_reset` at the profile's baud, then at 115200, then
  `no_reset` at the profile's baud after pulsing EN ourselves with the operator
  holding BOOT. Rung 3 exists because a board whose IO0 is not driven (unit
  `20:e7:c8:92:b6:10`) lands back in flash boot on EVERY reset — and esptool
  runs several per connect, so **more attempts make it worse, not better**. That
  rung needs a hand on the device, so it KEEPS RETRYING while it says so
  (every 1.2 s for 30 s) and then fails — asking once would only move the retry into the operator's hands while
  they are still reaching for the board. There is no "BOOT held" switch: the
  ladder reaches that rung by itself, and a switch would be one more thing to
  leave in the wrong position. The rung that worked is reported as `connect_mode` and stored in the
  run's results: a unit that only answers with BOOT held has a fault, and
  rescuing it silently every run is how that stays invisible.

- **A deploy used to break every bench tab that was already open** (prod run
  6329, 2026-09-17). esptool-js loaded its per-chip module lazily, Vite emitted
  it as a hashed chunk, a new image replaced every chunk, and a tab opened
  before the deploy failed its first connect with `Failed to fetch dynamically
  imported module …/esp32-<hash>.js` — on every rung, ending in "BOOT was not
  held within 30s" while the operator held BOOT. **Decision 0023 removed the
  cause**: nothing in the flashing path is lazily imported any more. The guard
  in `main.tsx` (reload once on Vite's `vite:preloadError`) stays, because any
  route in the app can still be a stale chunk after a deploy.
- **esptool-js changed baud by CLOSING and REOPENING the port**, and that is
  why the ladder below has a 115200 rung. A Web Serial close/open toggles DTR
  and RTS; on a board that resets from it the stub is gone and the next command
  reads `Invalid head of packet`. **Python's esptool does not do this** — it
  sets the speed on the open descriptor — so the rung may turn out to be
  unnecessary now. It is kept until a bench proves it: the fault it was built
  for (unit `20:e7:c8:92:b6:10`, 2026-09-16) is a property of the board, and
  only a run on that unit can say whether the transport was the whole story.
- **Marking is a RUN, and `mark_laser` is the only op the bench does not execute
  itself** (2026-09-16, decision
  [0020](../../../../docs/decisions/0020-marking-goes-through-lightburn.md)). A
  marking procedure is an ordinary deployment version with `kind = "mark"`: its
  own steps, its own history rows, the same publish gate. The template is a
  pinned ARTWORK SET — one `.lbrn2` per set, `artwork_set_id` beside the
  berryware `file_set_id` — so the version still answers "which drawing did
  this unit get"; that is why there is no `marking_templates` table, and why
  adding one would fork the answer. The engine names the file and
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

