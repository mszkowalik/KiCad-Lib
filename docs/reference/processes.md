# Production processes and twins

How decisions
[0058](../decisions/0058-a-process-is-versioned-stages-over-the-pool.md),
[0059](../decisions/0059-every-unit-has-a-twin-and-programming-names-it.md) and
[0060](../decisions/0060-the-process-is-the-one-source-of-history-materials-and-cost.md)
and [0061](../decisions/0061-an-invoice-can-pay-for-several-steps-and-the-benches-record-theirs.md)
and [0074](../decisions/0074-a-units-history-is-correctable-and-names-its-bench-runs.md)
are built. Code: `api/app/services/process.py` (the document, prepared parts,
the project's materials), `api/app/services/twins.py` (twins, crafting, the
assembly step, step costs, prices), `api/app/services/twin_rebuild.py` (old
batches into twins), `api/app/services/bench_links.py` (old bench runs linked
to their devices by topic),
`api/app/routers/process.py`, `web/src/components/process/`,
`web/src/components/project/ProcessTab.tsx`,
`web/src/components/run/RunProcess.tsx` (the crafting screen),
`web/src/components/TwinCard.tsx` (the device page).

## The process document

`ProcessVersion.graph` holds three lists:

| List | Holds |
|---|---|
| `steps` | the step LIBRARY. Each step has a `kind` (`assembly`, `receive`, `step`, `program`, `test`, `mark_laser`, `label`, `finish`), which fixes its station (`process.KINDS`); `needs` / `needs_not` (step keys or choice names); `inputs` (parts it adds per unit); `required`; a `group` that makes steps options of one choice; and, on a bench step, the `deployment_id` that says how it is done |
| `route` | the usual order, drawn by the map and offered first by the batch page |
| `prepared` | recipes for PREPARED PARTS: internal parts made before they meet a device, held as stock lots |

- A process has exactly one `assembly`, one `receive`, one `program` and one
  `finish` step. The assembly lists no parts in the process: its parts and
  fees are recorded with the step in "Record assembly", from the JLC order
  or typed for another assembly house.
  `finish` needs every required step by itself (`process.required_terms`). A
  choice is satisfied by any one of its options, and once one option is done
  the others are refused.
- An input names a library part (`component_id`), or a part the library does
  not hold by the MPN its purchases carry (`mpn`). The shipping cartons are
  the case: the pool keys them `m<MPN>`, so a step draws them from there.
- **A bench step names a deployment of its kind** (`process.DEPLOYMENT_KIND_FOR`:
  `program` → `flash`, `test` → `test`, `mark_laser` and `label` → `mark`),
  of the same project. `check` refuses another kind and warns when a bench step names
  none. It also refuses a REQUIRED `test`, `mark_laser` or `label` step when
  the project has no deployment of that kind: nothing could record it but a
  person's statement. `program` is exempt.
- **The project's materials are the process inputs** (`process_materials`):
  every input of every `step` on the main route, a prepared part expanded into
  its recipe. `project_bom` prices them in place of the extra BOM items, and
  `POST /projects/{id}/extra-items` refuses a new item. A batch is priced from
  the version it pinned (`version_for_run`), the project from the current one.
- **The current version is a pointer** (`Project.current_process_version_id`,
  `process.current_version`), never the highest number. Publish moves it;
  "Publish as history" (`historical`) does not, so a version written for older
  devices is never what a new batch pins. "Make current"
  (`POST /process-versions/{id}/make-current`) moves it to any published
  version.
- **A batch moves to another published version** with
  `POST /runs/{id}/process-version` (`twins.repin`, dry run first). It refuses
  a closed batch, and a target that lacks a step a twin of the batch has done
  or the bench stack names. The clicks keep the version they ran under. The
  audit row `craft.repin` names the previous version: undo is a move back. A
  bench stack the target's program step cannot take is cleared
  (`bench_stack_cleared`), and a move back does not select it again.
- The lifecycle is the deployment-version one. An edit makes a draft (one per
  project), a published version is immutable, and publishing needs a comment
  and a clean `process.check()`. The editor and the publish button call the
  same function. This is a draft gate outside the library's auto-publish rule
  (`api/app/services/CLAUDE.md`), on purpose.

## Twins

A twin is one unit's record from "receive" on (`M.Twin`). A click of a step on
N twins is one `StepRun`; each twin is linked to it by a `TwinStep`, and the
click's draws carry its `step_run_id`. A twin's history is its links, in the
words each step had then.

**An unnamed twin is never addressed by its id.** Before programming, units
are taken as "N from this STACK": the unnamed active twins of one batch with
the same `stack_key`, which holds the steps done and the prepared-part lots
used (`enclose@A785`). Twins of a stack are identical by construction, so the
platform picks which twins a click takes, and naming any one of them is not a
guess. No endpoint and no screen may take an unnamed twin's id. A screen
that asks "which twin is this unit?" before programming brings back pretend
serials (0059, Consequences).

- **A click on a prepared part takes ONE lot** (`twins._plan_draws`), so the
  units it touches stay one physical pile. Units enclosed from two lots are
  two stacks. Only a lot made on or before the click's date can feed it.
- **Found units are their own pile.** Their stack key carries a
  `found@<origin batch>` token (no step, no lot), so the bench never names a
  found unit in place of a board the batch received. `enter_found` refuses a
  device a batch already produced (rebuild that batch instead), and unnamed
  units while their origin batch holds unnamed units of its own: those are
  its spares or its received boards.
- **Every step draw goes through `twins.write_draws`**, which binds a
  prepared part to its lot. A bought part is drawn on the pool entry its
  purchases sit under (`run_actuals.resolve_pool_identity`), as the shortage
  check finds it.
- **After programming, a twin is addressed by its DEVICE**, which can be
  chosen by a scanned code or picked from a list. `StepRun.chosen` records
  which: `stack`, `scanned`, `list`, `bench`, `merge`, `found`, `supplier`
  (an assembly recorded from a JLC order), `manual` (an assembly recorded for
  another house), `rebuilt` (an old batch's records), `stated` (a bench step a
  person stated). A scan is an observation; a pick from a list is a person's
  statement.
- **Programming and marking are refused on the batch screen.** Their benches
  read the device and record them. A person may STATE a `test`, `mark_laser`
  or `label` step on named devices, with the reason (`apply_step(stated=…)`,
  `twins.STATABLE_KINDS`), when no platform bench run recorded it. Programming
  is never stated: the bench names the twin.
- **Every crafting click is one journal batch** (`routers/process._click`,
  kind `craft.<action>`, `source_ref` `run:<id>`): receive, step, scrap,
  finish, merge, found, reopen, swap, relink and a cost link. `craft_view`
  gives each click its `batch_id` while that write is not undone yet, and the
  batch screen offers "Undo…" on it; the check runs when it is pressed. A
  swap, a relink and a cost link record no click, so they are undone on the
  Write log. A rebuild's clicks have no "Undo…": a rebuild is undone whole, by
  "Undo rebuild". `journal.check_reversible` refuses while a later click, a
  bench step (a `TwinStep` outside the journal on a twin or click it made) or
  a link the click made has grown stands on it, while a link it removed has
  been made again, when it would make a unit that left us unfinished, and on
  a closed batch. Only an undo cancels a later batch out; a redo stands. The
  Write log never redoes a crafting click: do it again on the batch screen,
  where every check runs. Any undo or redo is refused where it would take a
  part's stock or a lot below zero and below its present level
  (`journal.stock_blockers`, see change-tracking.md). The Ledger refuses a `craft.rebuild` batch:
  "Undo rebuild" owns it. Bench clicks are not journalled. A dry run uses a
  savepoint.
- **A wrong bench fact is corrected by a click.** `twins.swap_twin` gives a
  device a twin of the right stack, with its programming click and that
  click's draws, and returns its old twin, unnamed, to its own stack (a found
  twin to the batch it was entered in). It refuses while the old twin has a
  step recorded after naming, the board's own assembly apart. `twins.relink_run` moves a bench run to the
  right device with the steps it recorded, and refuses a run that named a
  twin or programmed its device, a run of another project (by its batch, its
  deployment or its device), a source twin that is not active, and a step the
  right twin cannot take. Both are on the batch screen: "Swap twin…" and
  "Relink run…".
- **The twin follows the device.** A scrap of a named unit disposes of the
  device (`orders.dispose_device(scrap_twin=False)`), and disposing of a
  device scraps its twin, finished or not (`twins.scrap_disposed`).
  `twins.reopen` sets a finished unit active again with the reason; it ships
  only after a new finish. After a reopen, "already done" counts only what
  the unit did since (`twins.since_reopen`, `needs_met(since=…)`), so its
  steps and its finish can be done again; the needs still read the whole
  history. `device_units` and `device_events` are journalled,
  so the undo of a scrap gives the device back.

## The assembly step

The person records it, from "Record assembly" on Batch → Process (decision
0072). Nothing records it on its own: receiving the boards only counts them,
and applying the JLC order only moves its positions and draws onto the batch.

- **`twins.assembly_draft` pre-fills the form and writes nothing**
  (`GET /runs/{id}/craft/assembly/draft`). It returns the step as it stands
  and every row not in it yet: the `fab:*` and `pcba:*` positions charged to
  the batch and in no step (`kind`: `position`, `supplied_part` for a part the
  assembler bought that is itemised already, `parts_lump` for a parts total
  not split yet), the `measured` draws outside a step with their lots, the JLC
  breakdown of each unsplit parts total (`supplier_parts.itemise`), the
  replacements JLC's BOM shows (`substitutions.detect`), and for a batch with
  no JLC order the design BOM × boards. `header.boards_jlc` is JLC's board
  count (`jlc_import.effective_panels`), which the receive form also starts
  from.
- **`POST /runs/{id}/craft/assembly` applies only the ticked rows**
  (`routers/process._assembly` around `twins.apply_assembly`). It joins every
  received twin not in the step (not the found ones), links the chosen
  positions and draws, writes the draws of our parts another house used from
  the batch company's stock (refused when short), splits a parts total into
  the rows the assembler bought (`run_costs.split_line_core`, `allow_parts`,
  each child linked to the step), and records the replacements with the step
  (`run_costs.new_substitution`, `RunSubstitution.step_run_id`). It refuses a
  batch with no twins ("receive the boards first"), a closed batch, and a row
  that was not offered. `StepRun.assembler` and `StepRun.reference` keep what
  the person typed. `chosen` is `supplier` with a JLC order, else `manual`.
- **A dry run uses a SAVEPOINT** (`db.begin_nested()`), never
  `db.rollback()`: the figures are exact and only the plan is undone.
- **A real write is one journal batch** (`craft.assembly`, `source_ref`
  `run:<id>`), and `step_runs`, `twin_steps` and `twins` are journalled, so
  "Undo assembly" is the Ledger's reverse of that batch. A row that arrives
  later waits outside the step until the person adds it.

`twins.fitted` reads the supplier's own BOM (`supplier_parts.bom_for_order`)
for the device page. Its designators are the supplier's.

## The benches

- **Programming names a twin.** `engine._finalize` calls
  `twins.name_at_bench` only when `mark_produced` returns a NEW event, in a
  savepoint after the event is flushed. The twin is taken with
  `FOR UPDATE SKIP LOCKED`, so two stations finishing at once never name the
  same one, and the program step's inputs, if it lists any, are drawn. It takes the lowest-id twin of the
  batch's `bench_stack` ("<batch id>:<stack key>", which may belong to
  another batch of the project). The twin moves to the programming batch, and
  its origin batch never changes.
- **No stack, or a used-up one:** nothing is invented. The device is recorded
  and shows as a GAP on its batch (`twins.gaps`). `bench_checks` warns at the
  MAC read with `no_stack` or `stack_empty`, and never blocks (decision 0037).
  `twins.merge` closes a gap with a twin from a stack. A gap cannot ship
  (`twins.refuse_unfinished`), is held as `gap` on the shelf, and is uncosted
  on an order.
- **Another batch's stack is said once** (`stack_of_other_batch`): on the
  first board a batch names from another batch's pile. It is allowed (0059
  §12), and it is also what a wrong selection looks like.
- **Each bench step on a twin names its run** (`TwinStep.programming_run_id`)
  **and that run's deployment version** (`deployment_version_id`). The twin
  card shows the version beside the step, and as a reflash every passing
  programming run (action `program`, a flash deployment) that started after
  the run that produced the device. **The run that produced a device** is one
  rule for the bench, a merge and a rebuild (`twins.pick_production_pass`):
  the run the `produced` event's note names ("passed programming run #N", as
  the engine writes it), else the latest passing programming run that started
  at or before that event, else the first of the event's batch. The event
  itself is stamped with the device's FIRST sighting, which can be a trial's,
  so the note goes first.
- **A crafted batch takes its test rule from its process**: a programming run
  copies `test_required` from a required `test` step of the batch's version,
  not from `ProductionRun.requires_test`, so the device verdict and "finish"
  agree.
- **Marking:** when a run's results hold `marked` or `printed`, the engine
  calls `twins.record_marking` with the run's deployment. It records the
  `mark_laser` and `label` steps that name that deployment, or name none
  (`process.step_for_deployment`), where their needs are met.
- **A run that reads no MAC finds its unit by the topic it captures**
  (`engine._register_by_topic`, `engine.devices_by_topic`): the marking and
  test procedures never reach `_register_device`. Only an existing device of
  the run's project, and only one. Only a `flash` pass writes the `produced`
  event, so a test or a mark never names a twin.
- **A passing test run** records the `test` step (`twins.record_test`).
- **A step the bench records draws what it adds** (`twins._bench_step`): one
  label per copy printed (`results.label_copies`) for the label step. When the
  pool holds none, the step is still recorded and its note says so; the bench
  is never blocked. The click names the run's operator.
- **A bench step whose needs were not met yet is caught up later**
  (`twins.catch_up`): when a later step on the batch screen, or a merge,
  meets them, the bench's own run (`marked`/`printed`, or a passing test) is
  the evidence that records it.
- **A rebatch refuses a device with a twin into a batch without a process**
  (`twins.refuse_rebatch`): there it could never be finished, so never ship.
  It also refuses a device whose twin was rebuilt: its origin and its rebuilt
  steps come from the records of the batch it was rebuilt in.
- **The marking bench warns** (`bench_checks._about_the_process`, code
  `process_needs`) when the unit's twin has not done what the step needs. The
  ops the run will execute decide which steps it checks, so "Print label"
  alone does not warn about the enclosure.
- **The bench runs what the process lists** (decision 0076). One page offers
  the process's bench steps in route order (`steps` in
  `GET /runs/{id}/bench-stacks`, from `process.bench_steps`), each with the
  procedure the step names; the operator ticks what this bench does. A
  crafted batch runs only those procedures (`POST /flasher/runs` refuses any
  other), at each one's current version, or another with a reason.

## Money

| What | Where its money goes |
|---|---|
| A click's draws | the batch where the step was done (`run_id`), like any draw, so run figures and the register see them with no new branch. Each twin owns 1/N of them |
| A position linked to clicks (`cost_line_steps`) | still the batch it is charged to. The twins of ALL its clicks share it equally (`twins.line_shares`), valued by `run_actuals.leaf_line_usd` as the register values it. A link counts only while the position is charged to the clicks' batch |
| A prepared part | its stock lot: inputs drawn with no run (`transformation_id`), one positive adjustment as the output, conversion costs added on read (below) |
| Everything else charged to a batch | that batch's ORIGIN BATCH COST: the register's `by_run_usd` total minus every step draw and every linked position charged to it |

**A twin's price is its own parts, plus its step invoices, plus its origin
share** (`twins.prices`). The origin share is the origin batch cost, plus the
own parts and step invoices of that batch's scrapped twins, divided over its
twins that are neither scrapped nor found. A
closed batch answers the share frozen at close
(`ProductionRun.closed_twin_share_usd`, set by `close_run`, cleared by
`reopen_run`). Found twins carry a share of zero; what a batch drew for a
found unit it later scrapped is carried by that batch's good units.
`order_economics` charges a device with a twin its twin's price
(`twins.device_costs`), and a scrapped twin's device zero, because its money
is already in the good units' shares. A gap of a crafted batch is uncosted:
the batch average would count the batch twice. Every other device keeps its
batch's average (decision 0043).

**Origin cost that no twin carries** — a batch with no alive twin of its own,
because its units came from another batch or all broke — is
`origin_shares[…]["uncarried_usd"]`. The batch screen shows it, and
`close_run` refuses while it is not zero.

**A unit on the shelf is available only when its twin is finished, or it has
no twin and its batch is not crafted** (`orders._twin_holds`). An active twin
is held as `in process`, a scrapped one as `scrapped`, a gap as `gap`, beside
the conditions in `devices_held`.

- **A crafted batch takes parts only through its steps.** `consume_from_bom`,
  a hand-typed draw and a typed "used" quantity refuse a batch with a
  `process_version_id` (`run_costs._refuse_crafted`), and a step's draw cannot
  be deleted on its own.
- **A link counts only inside its batch.** A position re-charged elsewhere is
  unlinked again for its new batch (`twins._linked_ids`), and
  `twins.apply_assembly` replaces a stale link instead of adding one.
- **`link_costs` points a position at the clicks it paid for**, one or
  several, or at whole steps by key: the final assembler's invoice pays for programming, the
  enclosure, the laser mark and the label at once. A whole-step link is stored
  (`CostLineStepKey`) and `twins._new_run` links each later click of that step
  in that batch, so a link made while the bench is still programming covers
  every unit. A split position keeps its whole-step links on the header,
  which takes the later clicks too and is valued at zero (`line_shares` leaves
  headers out); each child of its destination gets the links and every click
  of the step (`twins.step_clicks`), a replaced child loses its own, and
  linking or unlinking a split position changes its header with its
  children. The undo of a whole-step link refuses once the position was split
  since, or its link grew onto later clicks: "Unlink…" under Cost by step on
  the batch screen takes a position off its steps (`craft_view.linked`: a split
  one by its highest header whose leaves are all this batch's, a whole-step
  link with no click yet too). An unlink by a header reaches its leaves at any
  depth, every header on the way with them, and clears the links of this
  batch on the voided lines below it. An unlink by this batch's share of a
  split clears the headers above it link by link: a header keeps a step or a
  click only while another leaf of this batch under it holds the same one, so
  a later split cannot copy back what was unlinked. A link that replaces a
  share's links (the API allows it with no unlink first) clears the headers
  above it the same way. A header with another
  batch's leaves lists its step on the leaves that hold it. A click's own links that no
  journal wrote (a split's copies, a bench click's whole-step link) never
  block its undo: the undo deletes them through the session, so it journals
  them and a redo puts them back. A redo puts deleted rows back parents
  first, one table at a time. It refuses a position not
  charged to the batch, a scrap click and a closed batch. A header stands for
  its children, and a split child (`split_line`, the JLC fee backfill) keeps
  its parent's clicks.
- **`cost_by_step`** gives the batch's cost per step, then one row per
  invoice that paid for several steps (never split by a guess), then the
  origin batch cost. The board and its assembly are the assembly step's row.
- **A label is a stock part**: the label step's input is the DYMO Durable
  25 × 54 mm label, keyed `m2112283` in the pool, as the cartons are.
- **A crafted batch holds one assembly order.** The JLC decision endpoint
  refuses a second `link_run` on it.
- **A shipment refuses an unfinished device that has a twin, and a gap**
  (`orders._refuse_unsellable` → `twins.refuse_unfinished`).

## Prepared parts and conversion costs

A prepared-part transformation is written with the two event kinds every
replayer already understands: its inputs are draws (no run,
`transformation_id`), and its output is one positive
`ComponentStockAdjustment`, which `lots.py` treats as a lot (`A<id>`). Do
not add an event kind for process work: that forks `_pool_events`, which
decision 0058 forbids.

- **A prepared part always takes a lot. A bought part takes lots only while
  `lot_pricing` is on.** With the switch off, a bought part takes the moving
  average. With it on, a bought part takes its lots oldest first, like every
  other draw ([production-economics.md](production-economics.md), "Lots and
  FIFO pricing"). A lot's remaining value is what it held minus what the draws
  took at their frozen prices.
- **A conversion cost is an invoice position with `transformation_id`**
  (0058 §4). `run_actuals.conversion_extras_usd` adds it to the output lot on
  read, in `pool_state`, `component_ledger` and `lots.lot_state`, the way
  `surcharge` adds freight to a purchase. `line_destination` ranks it right
  after `excluded`. The register gives it its own bucket
  (`to_transformations_usd`) and `gap_usd` subtracts it. Leave either out and
  every JLC import is refused by `jlc_apply._assert_identities`.
  `_check_transformation` refuses one on a stock step, and `_one_destination`
  keeps a position on exactly one destination.
- **Bank, stocktake, write-off** correct a prepared part's lots. Found work
  enters at zero value (0058, More Information).

## Rebuilding an old batch

`twin_rebuild.rebuild` gives a batch made before twins its twins
(`POST /runs/{id}/rebuild`, dry run by default). It writes everything inside a
savepoint, so the dry run is the real code path. A real write is one journal
batch (`craft.rebuild`, `source_ref` `run:<id>`), and `…/rebuild/undo`
reverses it.

### The rework order of one batch

Do these steps for each batch, in this order. A later step cannot correct an
earlier one.

1. Link the old marking and test runs to their devices with
   `POST /projects/{id}/bench-runs/link-by-topic` (`bench_links.link_by_topic`),
   dry run first. It links a run only when its captured topic names exactly
   one device of the project (`engine.devices_by_topic`).
2. Decide each group of devices with no batch, and do every rebatch, before
   you rebuild the batches concerned. A rebatch after the rebuild is refused
   for a rebuilt twin.
3. While the batch is not crafted, correct its BOM draws to what was really
   used (`PUT /runs/{id}/consumption/for-part`). After the rebuild the batch
   refuses a hand draw.
4. Rebuild first a batch whose boards another batch used. The other batch
   names it in `origins`.
5. Run the dry run. Read the per-device plan, `parts`, `unsettled`, `check`
   and `refusals`. Then write it.
6. Check the batch's twins on the crafting screen.
7. Only then set the bench stack.

### Inputs

| Input | What it says |
|---|---|
| `version_id` | The published process version. Default: the batch's pinned version, else the project's current one. |
| `assume` | The steps that happened though no record proves it, a person's statement. A list states a step for every device. A mapping states it for a selection: `{"label": {"device_ids": [], "codes": [], "since": "", "until": ""}}`. A statement covers only devices with no bench record of that step. |
| `since`, `until` | Step key → ISO date: the short form of a programmed date range for a stated step. Both ends are inclusive. |
| `draw` | The stated steps whose parts came from our stock. Their missing parts are drawn at each click's date. |
| `costs` | Plan key → the step keys a position paid for, other than the assembly. |
| `settle` | `[{"step", "part", "how"}]`: one statement for each difference between drawn and needed parts. `part` is the plan's `c<id>` or `m<MPN>`, or `*`. `how` is `draw` or `short` for a deficit, `return` or `loss` for a surplus. |
| `tolerance` | The difference in pieces that needs no statement. Default 0. |
| `active` | The devices still in progress, as a selection. Their twins stay active. |
| `origins` | `[{"from_run_id", "device_ids" or "codes" or "since"/"until"}]`: devices built on boards of another batch. With `from_run_id` null, the source batch is unknown, and the twin's note says so. |
| `spares` | Unnamed units on the shelf and the steps they took. |
| `append` | Give the devices that joined a rebuilt batch later their twins. |

### Evidence, device by device

- **The assembly and the receipt** go on every twin whose origin is this
  batch. A twin from another batch's boards joins that batch's rebuilt
  assembly and receipt clicks. A batch with no board or assembly position
  says `no_assembly_invoice`.
- **Programming** comes from the device's `produced` event. The twin's step
  names the run that produced the device, and its deployment version, by the
  rule a merge at the bench uses (above, "The benches").
- **A unit that left us stays finished** (shipped, missing). `active` and a
  faulty condition keep only a unit we hold active.
- **A spare carries no bench step**, and no step whose needs it lacks.
- **Parts are matched by pool identity** (as `resolve_pool_identity` does), so
  a draw carrying a component id meets an input named by its MPN.
- **A test, a laser mark and a label** come from the device's own bench runs:
  a passing test run, or a marking run whose results say `marked` (laser) or
  `printed` (label). There is one click per day and deployment version, and
  each twin's step names its run. A failed test, or a marking run that had the
  op and did nothing, is a bench record that is not evidence. A statement does
  not override it (`bench_says_not_done`).
- **Any other step with parts** goes on every device when the batch drew
  those parts (`_input_owner`, prepared recipes included), or on the
  selection that `assume` names.
- **An invoice position is money.** It never proves that a step happened on a
  unit. A position named in `costs` whose steps have no evidence stays in the
  origin batch cost (`lines_whose_steps_were_not_recorded`). A position linked
  to steps is also stored as a whole-step link (`CostLineStepKey`), so a click
  of those steps recorded live later, a spare programmed at the bench,
  shares it.
- **The status** comes from the device: disposed → scrapped, faulty or
  incomplete → active, named in `active` → active, any other → finished. An
  active twin takes later bench and batch steps like a crafted one. A finish
  click names the required steps its twins lack.

### Dates

- A step before programming (what programming needs, and the route's steps
  before it) takes the earlier of `run_date` and the first programming day.
  The assembly takes the earliest of that and its invoice date. `run_date` is
  free text, and a value that is no ISO date is not used.
- A step after programming takes the bench run's date, else the device's
  programming day. There is one click per day.
- The finish takes the device's last step day. A scrap takes the date of the
  device's `disposed` event, and `scrapped_at` is that event's time.
- A draw the rebuild writes takes its click's date, and the shortage check
  uses that date.

### Parts against units

For each step and part, the plan shows `drawn` against `need` (units × input
quantity, label copies for a bench label).

- The batch's draws feed the step's clicks, the oldest draw the earliest
  click. A draw that feeds two clicks is split into pieces at the same unit
  cost, and each piece takes its share of every lot binding.
- A click that used someone else's parts needs none: a stated step not in
  `draw` that the batch drew nothing for.
- A bench click, and a stated step in `draw`, draw their missing parts with
  no statement. `short` stops that.
- Every other difference above `tolerance` needs a statement, or the real
  write is refused (`unsettled`).
- `return` makes the newest draws smaller (`lots.resize_bound` gives back
  their newest bindings, whatever the lot pricing switch says) and voids a
  draw that goes back whole. `loss` leaves the rest unlinked in the origin batch cost
  (`left_in_origin.loss`).

### The check and the plan

- The batches' total moves only by the draws the rebuild wrote, less the
  surplus it returned. The prices of every twin of the batches concerned
  (this batch and each `origins` batch) must add up to their totals, within
  0.05 USD plus half a unit of the fourth decimal per twin. Money those twins
  carry from other batches is subtracted first. Otherwise nothing is kept.
  The dry run reports a failure in `check` and `refusals`. Neither the rebuild
  nor its undo touches a closed batch.
- The answer lists each device with each step, its date, its source, the
  bench run and deployment version behind it, the required steps it lacks
  and its price. It also lists the units of each step by source, the parts
  table, the found units that name the batch, and what stays in the origin
  batch cost.

### Append, undo, found units

- **`append`** takes the batch's own process version. New twins join the
  rebuilt assembly and receipt clicks, and every other step gets new clicks.
  A position linked to a step of the batch is linked to the new clicks of that
  step too. The draws a first rebuild left unlinked feed the new clicks first.
- **The undo** takes back the live clicks on the rebuilt twins and the
  rebuild's own journal batches in one sequence, newest first: a crafting
  write by reversing its journal batch (`journal.reverse`), a bench click by
  deleting it with its draws and their lot bindings. So an append is undone
  before a crafting write older than it. A crafting write found standing on
  the next batch (a whole-step link that an unlink took away, back after the
  unlink's undo) is taken back first. The keys a split copied from the
  rebuild's whole-step links onto the position's children go with the
  rebuild; the split stays. A twin the rebuild made that was finished and
  shipped since goes with it too. When no click is left, the batch is
  unpinned, and a whole-step link made since on a step with no click yet is
  taken back as well. The links the split children made through a copied key
  on a click outside the rebuild go like the position's own. A crafting write
  that linked a bench click the undo takes back is reversed with it, newest
  first. The links and copied keys are taken back again just before each of
  the rebuild's batches is reversed, after its dependents have put rows back.
  A row that a Write-log undo of a cost link or unlink put back is judged by
  who first wrote it: a link the rebuild's key made goes, a person's own link
  stays. Such an undo is never redone by "Undo rebuild": it acts on a whole
  position, not on what stands on the rebuild. A row an undo put back has two writers: the undo reverses the one
  that wrote it, never the reversal. The dry run lists each click it
  takes back. It refuses by name a click with no journal batch that is not a
  bench click, a dependent journal batch that is not a crafting write, and
  the rebuild of a batch built on this batch's boards. A rebuild written
  before the rebuild was journalled is undone the old way.
- **The Ledger refuses a `craft.rebuild` batch** and every redo of one: the
  batch's pinned process version is no journalled row. "Undo rebuild" owns
  it, and puts back the version the batch had pinned before the rebuild
  (`summary.pinned_before`).
- **"Undo rebuild" also takes back** the scrap click a disposal on the device
  page wrote (its note keeps the status the twin had), and the links the
  rebuild's whole-step links made on clicks it does not take back. It refuses
  while the surplus the rebuild returned is drawn again: the rebuild stores
  each returned part's pool before the return, day by day and under every
  name the part has (`summary.returned_low`), and the undo may not take the
  pool on any day below that day's balance (or below zero, whichever is
  lower), whatever was drawn, raised or cut since; while a lot it binds
  again would go lower than it was before the rebuild (`summary.returned_lots`;
  a lot the rebuild did not give back to, lower than before the undo),
  because a draw recorded since took the units or the lot was cut; and while a batch it
  touched (an `origins` batch, a twin's origin, a bench click's batch) is
  closed. An append is refused while another batch's rebuild joined this
  batch's rebuilt assembly or receipt.
- **Counted spares enter by `spares` only.** The rebuild reports found twins
  that name the batch (`found_naming_this_batch`), and refuses `spares` while
  an unnamed active found twin names it.
- **A rebuilt batch may hold the two assembly orders it was built from.** The
  JLC decision endpoint lets each be decided again for the same batch.
- **Not resolved, only reported:** a batch whose devices outnumber its
  order's boards (`more_units_than_boards`), steps with no record, and
  positions left in the origin batch cost.

## What software cannot know

A stack is as true as the pile the operator took it from, and a pick from a
list is as true as the person who made it. A barcode scanner at the station
turns every step after programming into an observation.
