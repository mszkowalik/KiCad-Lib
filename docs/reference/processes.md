# Production processes and twins

How decisions
[0058](../decisions/0058-a-process-is-versioned-stages-over-the-pool.md),
[0059](../decisions/0059-every-unit-has-a-twin-and-programming-names-it.md) and
[0060](../decisions/0060-the-process-is-the-one-source-of-history-materials-and-cost.md)
and [0061](../decisions/0061-an-invoice-can-pay-for-several-steps-and-the-benches-record-theirs.md)
are built. Code: `api/app/services/process.py` (the document, prepared parts,
the project's materials), `api/app/services/twins.py` (twins, crafting, the
assembly step, step costs, prices), `api/app/services/twin_rebuild.py` (old
batches into twins),
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
  `finish` step. The assembly lists no parts: its parts and fees come from
  the batch's assembly order.
  `finish` needs every required step by itself (`process.required_terms`). A
  choice is satisfied by any one of its options, and once one option is done
  the others are refused.
- An input names a library part (`component_id`), or a part the library does
  not hold by the MPN its purchases carry (`mpn`). The shipping cartons are
  the case: the pool keys them `m<MPN>`, so a step draws them from there.
- **A bench step names a deployment of its kind** (`process.DEPLOYMENT_KIND_FOR`:
  `program` → `flash`, `test` → `test`, `mark_laser` and `label` → `mark`),
  of the same project. `check` refuses another kind and warns when a bench step names
  none.
- **The project's materials are the process inputs** (`process_materials`):
  every input of every `step` on the main route, a prepared part expanded into
  its recipe. `project_bom` prices them in place of the extra BOM items, and
  `POST /projects/{id}/extra-items` refuses a new item.
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
  device a batch already produced: rebuild that batch instead.
- **Every step draw goes through `twins.write_draws`**, which binds a
  prepared part to its lot. A bought part is drawn on the pool entry its
  purchases sit under (`run_actuals.resolve_pool_identity`), as the shortage
  check finds it.
- **After programming, a twin is addressed by its DEVICE**, which can be
  chosen by a scanned code or picked from a list. `StepRun.chosen` records
  which: `stack`, `scanned`, `list`, `bench`, `merge`, `found`, `supplier`
  (the assembly order), `rebuilt` (an old batch's records). A scan is an
  observation; a pick from a list is a person's statement.
- **Programming and marking are refused on the batch screen.** Their benches
  read the device and record them.

## The assembly step

`twins.record_assembly` makes or extends the batch's ONE assembly click. It
links every twin received in the batch (not the found ones), the batch's
`measured` draws, and every leaf position charged to the batch whose step is
`fab:*` or `pcba:*` (`twins.charged_lines` decides "charged to" with
`run_actuals.line_destination`, as the register does). It runs from
`twins.receive`, from the JLC decision apply (`routers/jlc_import.py`) on a
crafted batch, and from `POST /runs/{id}/craft/assembly`. It links nothing
while the batch has no twins: a cost on a click with no units is carried by
nobody, and the twins' prices would stop adding up.

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
  `twins.merge` closes a gap with a twin from a stack.
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
- **The marking bench warns** (`bench_checks._about_the_process`, code
  `process_needs`) when the unit's twin has not done what the step needs. The
  ops the run will execute decide which steps it checks, so "Print label"
  alone does not warn about the enclosure.
- **The programming bench** starts on the current version of the deployment
  the program step names (`program_deployment` in
  `GET /runs/{id}/bench-stacks`).

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
is already in the good units' shares. Every other device keeps its batch's
average (decision 0043).

- **A crafted batch takes parts only through its steps.** `consume_from_bom`,
  a hand-typed draw and a typed "used" quantity refuse a batch with a
  `process_version_id` (`run_costs._refuse_crafted`), and a step's draw cannot
  be deleted on its own.
- **A link counts only inside its batch.** A position re-charged elsewhere is
  unlinked again for its new batch (`twins._linked_ids`), and
  `record_assembly` replaces a stale link instead of adding one.
- **`link_costs` points a position at the clicks it paid for**, one or
  several, or at whole steps by key (every click of them): the final assembler's invoice pays for programming, the
  enclosure, the laser mark and the label at once. It refuses a position not
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
- **A shipment refuses an unfinished device that has a twin**
  (`orders._refuse_unsellable` → `twins.refuse_unfinished`).

## Prepared parts and conversion costs

A prepared-part transformation is written with the two event kinds every
replayer already understands: its inputs are draws (no run,
`transformation_id`), and its output is one positive
`ComponentStockAdjustment`, which `lots.py` treats as a lot (`A<id>`). Do
not add an event kind for process work: that forks `_pool_events`, which
decision 0058 forbids.

- **Lots matter for internal parts only.** Bought parts are priced at the
  moving average, as everywhere in the platform. A lot's remaining value is
  what it held minus what the draws took at their frozen prices.
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
(`POST /runs/{id}/rebuild`, dry run by default; `…/rebuild/undo`). It writes
everything inside a savepoint, so the dry run is the real code path.

- **Inputs:** the process version; `costs` (plan key → the step keys a
  position paid for, other than the assembly); `assume` (steps that happened
  though no record proves it — a person's statement); `draw` (the stated
  steps whose parts came from OUR stock: their draws are written at the
  batch's date and refused when the pool did not hold them; a stated step not
  in `draw` used someone else's parts and draws nothing); `spares` (unnamed
  units on the shelf and the steps they took).
- **Evidence per step:** the assembly and the receipt are always recorded
  (a batch with no board or assembly position says `no_assembly_invoice`); a
  step with parts from the batch's draws of those parts (`_input_owner`,
  prepared recipes included); programming from each device's `produced`
  event, one click per day; finish per the device record, one click per day;
  a stated step on every device, or with `since` only on the devices
  programmed on or after a date (the leaflet). Any other step without
  evidence is reported, not recorded.
- **The check:** the batch's total may grow only by the stated draws, and the
  twins' prices must add up to it, within 0.05 USD plus half a unit of the
  fourth decimal per twin. Otherwise nothing is kept. Neither the rebuild nor
  its undo touches a closed batch.
- **A rebuilt batch may hold the two assembly orders it was built from**; the
  JLC decision endpoint lets each be decided again for the same batch.
- **Not resolved, only reported:** a batch whose devices outnumber its
  order's boards, steps with no record, and positions left in the origin
  batch cost.

## What software cannot know

A stack is as true as the pile the operator took it from, and a pick from a
list is as true as the person who made it. A barcode scanner at the station
turns every step after programming into an observation.
