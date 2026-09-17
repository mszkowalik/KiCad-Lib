# Flasher UI (`web/src/components/flasher`)

The production programming screens. The backend rules are in
`api/app/services/flasher/CLAUDE.md` and the wider design is in
[docs/flasher/design.md](../../../../docs/flasher/design.md).

## Flasher UI — where things live

- `src/flasher/station.ts` is the PORTED, HARDWARE-VERIFIED PoC (one USB
  adapter = one Station: esptool phase + monitor byte pipe). The transport
  rules in it are measured requirements (ESP32-C6 native USB: never call
  `setSignals()` in monitor mode; explicit reset pulse because esptool-js's
  `after("hard_reset")` is a no-op) — do not "clean them up".
- `src/flasher/runClient.ts` talks to the engine WebSocket: it executes
  `action` ops, pipes `tx`/`rx`, answers `prompt`s (SIM PIN modal) and
  forwards every station log line as `{t:"log"}` so the stored record is
  complete. The scenario itself NEVER runs in the browser.
- Pages: **`/production/deployments`** is the home of the flasher — three
  columns (deployments → version timeline → composed view of the selected
  version), with `Composer` for new versions and `DiffView` for comparisons.
  **`/production/files`** administers everything a version pins, one kind per
  tab (`?tab=bundles|firmware|files|parameters`) — bundles first, because that
  is the unit berryware ships in. `/production/artifacts` redirects there. Then `/production/bench` (stations),
  `/production/devices` (+ `/:id`), `/production/flash-runs/:id` (step
  timeline + full log, live-tails by polling `after=<last seq>`). The bench log
  box keeps a bounded tail — the full log is in Postgres.
- **The composer inherits by omission.** A section left untouched sends
  `undefined` and the backend inherits it from `from_version_id`; only touched
  sections are transmitted. Keep that contract — sending a section you did not
  edit turns "berryware bump" into a full rewrite of the version.
- **Validation comes from the server, always.** The composer PATCHes the draft
  and renders the returned `validation`; never re-implement a rule in the
  browser, or the editor will eventually disagree with the publish gate.
- **`StepEditor` renders the procedure in BOTH places** — editable in the
  composer, `readOnly` on a published version — from one schema
  (`stepSchema.ts`, keyed by op). Add an op there and both views get it. The
  read-only path takes its context from the version payload itself
  (`assetsOf` / `bundlesOf` in `VersionView`), so it needs no extra fetches;
  making a published procedure editable later is a flag, not a second view.
- **A flash step selects its firmware and a download step its bundle**, and
  both write the VERSION's pins. Keep it that way: the version stays the single
  definition of a payload (fingerprints, diffs and bundle identity all derive
  from it) — the step editor only puts the controls where the work happens.
- **Berryware reads as a BUNDLE, not a file list** (user feedback 2026-07-30).
  The version view and the composer lead with one pill — bundle name + file
  count, green for a named bundle and amber for an unnamed ad-hoc set — and put
  the file table behind a Show-files toggle. Deleting an artifact goes through
  the API's usage guard; surface the 409 text, never pre-filter in the browser
  (the backend knows every reference).
- **The marking bench is its own page, and `BenchStation` takes a `mode`**
  (2026-09-16). `mode="mark"` drops Erase and Test — a marking bench has no
  business wiping a device — and renames Program to Mark. `autoStart` fires the
  procedure when a device arrives, ARMED ONCE per device: the arm drops when the
  port goes live and only returns when it goes away, so a finished part left in
  the fixture is not marked twice. **Both benches offer it** — the flash bench
  since 2026-09-16, where it saves a click per unit on a tray of dongles — but
  the defaults differ on purpose: marking arrives armed, flashing does not,
  because a programming run erases the device before it writes. Whatever else
  gets this, keep the once-per-device arm: a retry loop on a failing unit is
  the failure mode it exists to prevent.
- **A station owns a SOCKET, and nothing is adopted automatically**
  (2026-09-16). `Assign socket…` picks a port once, identifies which
  `/dev/cu.*` node it is, and stores `slot -> node` in the browser; after that
  the station takes that node and no other, across replugs and reloads, and the
  port row prints the real name. An unassigned station stays empty however many
  devices appear. **Arrival order is gone** — it handed station 1 whatever
  turned up, so moving a cable silently moved the station.
- **Identification OPENS the port, which resets an ESP32.** That is the price of
  the only trick that works (`identifyPort` in `flasher/station.ts`: note what
  the agent says is held, open, look again). So it never runs against a busy
  station, the result is cached per `SerialPort` object, and the identifications
  are queued — two at once and both look "newly held".
- **Without the agent the bench still works, it just forgets.** `identifyPort`
  returns "" rather than throwing, assignment holds the port for the session,
  and the row says the station cannot remember its socket. Do not turn that into
  an error: a bench with no agent is a usable bench.
- **One station gets a different LAYOUT, not a different component.**
  `.bench-station.is-mark` re-flows the same markup into two columns through
  named grid areas — what the operator acts on at the left, what they read at
  the right. The four-up card is a narrow column because four have to fit side
  by side; with one laser that shape wastes the page and pushes the log below
  the fold. Any conditional block (the BOOT notice, an error) spans both
  columns, so it never lands in a lane whose width depends on which column drew
  it. The marking station also carries a **large mono readout of what was
  engraved** (`results.marked`): the operator's check is against the part in
  their hand, so it is the biggest text on the page.
- **The marking station's NAME is keyed `"mark"`, not by slot.** It shares
  `BenchStation` with flashing slot 0, so keying both by index meant renaming
  one renamed the other.
- **The manual mark and a marking run share ONE implementation**
  (`runMarkJob` in `flasher/markAgent.ts`). Both fetch the artwork the version
  pins, patch the one text shape and hand the finished job to the agent; the
  only difference is where the string came from — the device's own topic, or
  the operator's keyboard. Two copies would drift the moment one of them
  learned something. The manual card reads the template and the placeholder off
  the version's `mark_laser` STEP, so it cannot disagree with the run about
  which drawing a unit gets.
- **A TYPED mark or label is not recorded at all** (user decision 2026-09-17).
  It names no run and proves nothing: the operator is replacing a spoiled label
  or engraving a bare part. A history row saying a unit was marked, with nobody
  able to say against what, is worse than no row. Everything the two BUTTONS do
  runs the procedure, and that still records.
- **The marking station is two columns, split by SUBJECT**
  (`.bench-mark-cols`). Left is the device — serial, port, what the station is
  doing. Right is one box per machine, each with its own status above its own
  button, because "LightBurn is not answering" and "the printer has no roll"
  are fixed in different rooms. The shared hop, the agent itself, stays on the
  page strip above.
- **The chain between the two boxes is a THIRD mode, not a third Automatic**
  (user decision 2026-09-17). Linked, one press of Mark engraves and then
  prints, so the operator keeps the trigger and still does one press per
  device — which is what Automatic was being used for, at the cost of the pass
  starting by itself. It is drawn between the boxes because it belongs to
  neither: it says what ONE press does. A linked Mark is disabled while the
  printer is not ready, because a marked part with no label is worse than a
  part that waits.
- **Automatic is TWO checkboxes, one per machine.** A bench may engrave all day
  and print nothing, or print while the laser is down. Each arms only when its
  own machine is ready, and an automatic pass runs with the other action
  skipped.
- **The marking station reads the device when it ARRIVES, not when a button is
  pressed** (`preRead`, user decision 2026-09-17). Two reasons, and the second
  is the better one: a press no longer waits 0.7-1.1 s for `wait_boot`, and the
  operator sees the serial and can check it against the part BEFORE committing
  a label or a burn. What it asks comes off the version's own `command` step —
  the command, the expect key, the capture path — and the value is put through
  the action step's `take_after`, so the box cannot show a different string
  from the one that goes on the part. **The probe closes the port again.** An
  open reader is how the rest of `station.ts` recognises "a run is using this
  port": `noteDisconnect` will not release a held port while one exists, and
  `identifyPort` learns a station's socket by OPENING the port, which fails on
  one that is already open. A probe that stayed open cost the station its
  socket on the next replug (found on the bench, 2026-09-17).
- **A serial is 8 to 12 characters with no whitespace**, checked in BOTH modes
  (`serialProblem`): what the operator typed, and what the device answered. A
  device that answers with something else is not an identified device, and the
  station says which rule it broke rather than only greying the buttons. The
  engine enforces the same bounds, so this is the early, readable half of the
  rule and not the only one.
- **Until the device has answered, both buttons stay disabled** (user decision
  2026-09-17), and the box says why: waiting, reading, or the error. A press
  that cannot name the part is not worth the label. Manual is the way past it.
- **The two buttons run the SAME version and differ only by `skipOps`**, which
  travels in the run's hello. One procedure reads the device once; which action
  this press wanted is the bench's business, not the version's. The engine
  honours it for `mark_laser` and `print_label` and nothing else, so a bench
  can never quietly change what a unit was made under (decision 0021).
- **The stocked rolls are a list in `BenchStation.tsx`, not the agent's.** The
  agent can report all 61 the PPD knows; a dropdown of 61 is a search. Add a
  row when a roll is actually bought.
- **The agent's two hops are reported SEPARATELY** (`MarkBench`'s AgentPanel).
  "Agent down" is fixed on the bench machine and "LightBurn is not answering" is
  fixed in LightBurn, so an operator told only "marking unavailable" would not
  know which. The first failure also reads as the second: a page on a public
  origin reaching `127.0.0.1` trips Chrome's Local Network Access check and
  fails with `ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS`, not a timeout — which
  is why `markAgent.ts` says so in the error text rather than "not running".
- The vite dev proxy has `ws: true` for `/api` — required by the run
  WebSocket; keep it when touching `vite.config.ts`.

## The "Planned as" column is the step EDITOR, not a label

Every non-header invoice line renders a step select (catalog from
`GET /api/cost-steps`, grouped by stage) writing `plan_key` directly; the
"link to a specific plan item…" option opens the old PlanLinkDialog for
free-form `c<id>` links. The split dialog carries the same select per row, and
picking a step back-fills the row's kind from the catalog default. The run
panel's "Where the money goes" table shows per-step plan-vs-billed with
supplier chips whose data comes from `RunActuals.steps[].sources` — computed
server-side in `run_actuals`, never re-derived in the browser.


