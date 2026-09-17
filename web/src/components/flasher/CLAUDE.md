# Flasher UI (`web/src/components/flasher`)

The production programming screens. The backend rules are in
`api/app/services/flasher/CLAUDE.md` and the wider design is in
[docs/flasher/design.md](../../../../docs/flasher/design.md).

## A version's NOTE is prose, and the deployment card is not a form to scroll

Two things on the Deployments page were reported unreadable from the bench
(2026-09-17), and both were the same mistake — a style chosen for one length of
text applied to another.

- **`.card-subtitle` is a CAPTION style** — 11px uppercase mono with
  letter-spacing. It suits "retro-import · 2026-07-29 · changed: berryware".
  `VersionView` used it for the version's publish comment as well, which is
  free text of any length: a five-line paragraph rendered that way looks like a
  heading and reads like nothing. The note now has `.version-note`, sentence
  case, under its own label. Keep the caption for captions.
- **The note is NOT repeated on the timeline row.** Seven versions of one
  deployment share an opening sentence, so a clipped copy per row told them
  apart not at all while costing a line each. The row carries the CHANGE
  summary, which does; the note is on its `title` and in full on the card.
- **Two columns, and the wide one belongs to the PROCEDURE.** The page was
  three — a picker for three deployments down the left at 15%, the timeline at
  30%, and the composed version in what was left — so the 28-step procedure,
  which is the thing the page exists to show, read in about half the window and
  truncated every step's command. The deployments are `.depl-tiles` across the
  top now (tiles, not a dropdown: the pills say which version each channel runs
  and what kind the procedure is), the timeline is the left column, and the
  deployment's fields sit with the version in the right one. Measured at
  1500 px: the detail column went 660 → 864 px, and the head 415 → 224 px.
- **The procedure card comes BEFORE firmware and berryware in `VersionView`.**
  Firmware is one table row and berryware is one pill; they pushed the steps
  off the bottom of the window for no benefit.

## Flasher UI — where things live

- `src/flasher/station.ts` is a RELAY to the bench agent, not an
  implementation (decision
  [0023](../../../../docs/decisions/0023-the-agent-programs-the-device.md)).
  One station = one USB SOCKET on the bench machine. It names the socket and
  the operation; the agent runs Python's esptool and holds the console. **This
  page opens no serial port, so there is no Web Serial here at all** — no
  picker, no permission, no `navigator.serial`. The transport rules are still
  measured requirements and are honoured by the agent (ESP32-C6 native USB:
  `monitor_signals` is null and DTR/RTS are left alone) — do not "clean them
  up" on either side.
- `src/flasher/runClient.ts` talks to the engine WebSocket: it executes
  `action` ops, pipes `tx`/`rx`, answers `prompt`s (SIM PIN modal) and
  forwards every station log line as `{t:"log"}` so the stored record is
  complete. The scenario itself NEVER runs in the browser.
- Pages: **`/production/deployments`** is the home of the flasher — deployment
  tiles across the top, then two columns (version timeline → the deployment's
  own fields and the selected version), with `DiffView` for comparisons.
  **`/production/files`** administers what a version PINS, one kind per tab
  (`?tab=bundles|firmware|files`) — bundles first, because that is the unit
  berryware ships in. `/production/artifacts` redirects there.
  **`/production/parameters`** is what a version DEPENDS on and does not
  contain: the values, who needs each key, and the revision log (decision
  [0024](../../../../docs/decisions/0024-a-version-declares-the-parameters-it-needs.md)).
  It was a fourth tab under Files until 2026-09-17;
  `/production/files/parameters` redirects. Then `/production/bench` (stations),
  `/production/devices` (+ `/:id`), `/production/flash-runs/:id` (step
  timeline + full log, live-tails by polling `after=<last seq>`). The bench log
  box keeps a bounded tail — the full log is in Postgres.
- **There is no composer. A draft is edited where it is read** (2026-09-17,
  user request). `Composer.tsx` was a modal that rendered the same four
  sections a second time, editable, over `VersionView` — two renderings of a
  procedure, which is two places every step op has to be understood, and they
  had already diverged on which controls a section carries. `New version` now
  POSTs a draft inheriting everything, selects it, and `VersionView` becomes
  the editor. Four consequences:

  1. **`VersionView` is one component with a `status` branch, not two views.**
     `StepEditor`'s `readOnly` was always a flag; now the whole card is.
  2. **Every edit PATCHes and takes the server's `validation` back whole.**
     Never re-implement a rule in the browser — `validate.check()` is the one
     gate and the errors under the header must be the publish button's own.
  3. **Inherit by omission still holds.** A PATCH sends only what changed; a
     section you did not touch must stay `undefined`, or a berryware bump
     becomes a full rewrite of the version.
  4. **Firmware and berryware have no controls of their own**, and never did —
     a `flash` step picks its images and a `download_files` step its bundle,
     inside `StepEditor`. Those two cards are summaries of what the procedure
     pinned.
- **Discarding a draft DELETES it; rejecting keeps it.** `DELETE
  /deployment-versions/{id}` removes a draft nothing has used, because a
  version minted by one click and looked at must not leave a rejected row
  behind forever. The server refuses for a published version, and for any
  version a programming run records (a draft runs as a bench trial) — the UI
  falls back to `reject`, which keeps the row as history. The card offers
  `Delete this version` on anything not published.
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
- **The BATCH is the only mode control, and "no batch" is the bench trial**
  (user decision 2026-09-17). There used to be a `batch run` / `bench trial`
  dropdown beside the batch one, which made "batch run with no batch picked" a
  state the page had to detect and warn about — and which disabled Automatic
  until it was resolved. One control cannot express it: a batch means
  production on that batch's assigned version, none means a trial that may run
  a draft and is recorded as such.
- **There is no Test button on a station.** A test is an ordinary deployment
  with `kind: "test"`, so it is run by picking its version like any other, and
  a second button that silently ran a different version was a way to program a
  unit under a procedure nobody chose (user decision 2026-09-17). The kind
  still decides which BENCH offers a procedure; it no longer adds a button.
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
- **The socket picker WATCHES, because a port name identifies nothing**
  (`SocketPicker.tsx`, user request 2026-09-17). Four identical CH340s give
  four `/dev/cu.usbserial-*` names an operator cannot tell apart, so the picker
  opens with whatever is there — including nothing — polls the agent while it
  is open, and marks anything that ARRIVES as `new`, sorted to the top. Plug
  the device in with the dialog open and take the row that appears; that is how
  Chrome's own picker solved the same problem. It never auto-assigns: two
  cables can arrive at once, and appearing is a hint rather than a decision.
  Both benches use it — the marking station needs a socket for exactly the same
  reason, to read the device's serial.
- **A station owns a SOCKET, chosen BY NAME from the agent's list**
  (2026-09-16, simplified by 0023 on 2026-09-17). `Assign socket…` shows the
  agent's `/dev/cu.*` nodes with who holds each, and stores `slot -> node` in
  the browser; after that the station takes that node and no other, across
  replugs and reloads. An unassigned station stays empty however many devices
  appear, and cannot run at all — the agent addresses a port by its name.
  **Arrival order is gone** — it handed station 1 whatever turned up, so moving
  a cable silently moved the station. **So is `identifyPort`**, the
  open-the-port-and-compare trick that existed only because Web Serial would
  not name a port; the agent simply names it.
- **Without the agent the bench does NOT work, and says so.** That is the
  trade 0023 made deliberately: one implementation, no fallback. The flashing
  bench keeps a `/hello` heartbeat so the banner is honest, and a station whose
  socket has no cable in it reads empty rather than ready.
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
  (`runMarkJob` in `flasher/benchAgent.ts`). Both fetch the artwork the version
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


