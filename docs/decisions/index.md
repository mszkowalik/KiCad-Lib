# Decision records

This folder holds architecture and process decisions about the **7Sigma KiCad
Library Platform** itself — deployment, backend/frontend architecture, access
control, the agent workflow. It does not hold component or library
conventions: those live in the platform's **skill documents**, versioned in
Postgres and mirrored to `.claude/skills/` (see the root
[CLAUDE.md](../../CLAUDE.md), section "Skills").

The format is [MADR 4.0.0](https://adr.github.io/madr/). The file name pattern
is `NNNN-title-with-dashes.md`, four digits, no gaps skipped on purpose.

## Rules

1. Write a record when a change adds an external dependency, changes the
   deployment or access-control model, or would be expensive to reverse.
2. Put the record in the same commit as the change it describes.
3. **Never edit an accepted record.** To reverse a decision, write a new
   record and set the old one's `status` to `superseded by NNNN`. Move its row
   to the "Superseded" table below.
4. Copy [adr-template.md](adr-template.md) to start a new record. Before you
   do, check no file already claims the next number:
   `ls docs/decisions/NNNN-*`.
5. Set `status` to `accepted`, or to `proposed` if the decision still needs
   agreement.
6. Add a row to the matching table below in the same commit.

## Accepted

| # | Decision | Area |
|---|---|---|
| [0001](0001-generate-package-sim-wrappers-from-blocks.md) | Generate a package simulation wrapper from blocks, instead of writing it | Backend, simulation |
| [0002](0002-field-solver-in-the-platform.md) | The field solver lives in the platform, and its stackups are project data | Backend, frontend, projects |
| [0003](0003-orders-shipments-and-device-history.md) | Sales orders, shipments and a per-device history replace the sale fields on a run | Backend, frontend, production, flasher |
| [0004](0004-datasheet-identity-and-storage.md) | Store each datasheet once and version it by its text, not its bytes | Backend, datasheets, review |
| [0005](0005-off-board-parts.md) | Treat a part as off-board when its base symbol declares it and it has no land pattern | Backend, KiCad output, review |
| [0006](0006-sync-button-owns-library-updates.md) | Update installed KiCad libraries through the Sync button, and leave the PCM to the plugin | KiCad client, sync plugin, deployment |
| [0007](0007-built-means-finished-and-passed.md) | Count a batch by the devices that passed, not by the quantity typed on it (overrides item 8 of [0003](0003-orders-shipments-and-device-history.md)) | Backend, frontend, production, flasher |
| [0008](0008-a-stackup-is-electrical-only.md) | A stackup describes conduction only; appearance and impedance work are project data (extends [0002](0002-field-solver-in-the-platform.md)) | Backend, frontend, field solver, projects |
| [0009](0009-the-git-mirror-is-the-source-archive.md) | Keep project source in the git mirror only, and stop storing a tarball per snapshot | Backend, projects, storage, deployment |
| [0010](0010-a-git-token-belongs-to-an-account.md) | A git token belongs to an account, and projects point at it by name | Backend, frontend, projects, access control |
| [0011](0011-retire-the-skipped-verification-result.md) | Retire the `skipped` verification result; an unverifiable item is left unanswered and `na` carries a reason | Backend, frontend, review axis, agent tools |
| [0012](0012-rename-a-footprint-or-base-symbol-in-place.md) | Rename a footprint or a base symbol in place, and rewrite every reference with it | Backend, frontend, KiCad output, review axis, agent tools |
| [0013](0013-the-validator-owns-the-automatic-checks.md) | The validator owns the automatic checks, and a checklist switches them on or off per category | Backend, frontend, review axis, agent tools |
| [0014](0014-a-check-carries-its-own-configuration.md) | A check carries its own configuration, and the rules table is retired (completes [0013](0013-the-validator-owns-the-automatic-checks.md)) | Backend, frontend, review axis |
| [0015](0015-a-check-says-which-subjects-it-is-about.md) | A check says which subjects it is about — a `when` predicate that NARROWS, plus named variants on one discriminator (completes [0014](0014-a-check-carries-its-own-configuration.md)) | Backend, frontend, review axis, agent tools |
| [0016](0016-severity-and-standing-exceptions.md) | A check has a severity, and a subject can carry a standing exception — both copied from KiCad's DRC/ERC model | Backend, frontend, review axis, agent tools |
| [0017](0017-conformance-is-computed-not-recorded.md) | Conformance is computed on read and cached against a digest of its inputs, never recorded on publish | Backend, frontend, review axis |
| [0018](0018-does-not-apply-is-an-exception-not-an-answer.md) | "Does not apply" is a standing exception, not a per-version `na` answer — one control, and it works on an item nobody has answered | Backend, frontend, review axis, agent tools |
| [0019](0019-a-classification-carries-the-first-time-it-is-set.md) | A classification key carries the first time it is set — filling in `comp_type` costs no verification, changing one still does | Backend, review axis |
| [0020](0020-marking-goes-through-lightburn.md) | Drive the laser through LightBurn and a local agent, not a direct controller driver — the BSL board's protocol is not the open-source LMC one | Backend, frontend, production, external dependency |
| [0021](0021-a-device-is-judged-by-the-rule-it-was-made-under.md) | Judge a device by the rule its batch carried, and pin that rule on every programming run (refines [0007](0007-built-means-finished-and-passed.md)) | Backend, frontend, production, flasher |
| [0022](0022-labels-are-generated-by-the-bench-agent.md) | Print labels through CUPS and lay them out in the bench agent, with no template file and no vendor software (extends [0020](0020-marking-goes-through-lightburn.md)) | Backend, frontend, production, flasher |
| [0023](0023-the-agent-programs-the-device.md) | Do every byte of bench serial work in the agent, with esptool vendored inside it, and drop Web Serial entirely | Backend, frontend, production, flasher, external dependency |
| [0024](0024-a-version-declares-the-parameters-it-needs.md) | A version declares the parameters it needs, and a parameter set keeps an append-only revision log (supplies the half 2026-07-27 left out) | Backend, frontend, production, flasher |
| [0025](0025-a-device-fetches-from-its-own-address.md) | A device fetches from its own address, and on this deployment that address is plain HTTP — Tasmota completes no TLS against the edge and validates no certificate | Backend, production, flasher, deployment |
| [0027](0027-a-stock-count-corrects-a-fifo-guess.md) | Let a stock count reverse a FIFO guess, and net the reversal out of every fulfilment figure (extends [0003](0003-orders-shipments-and-device-history.md)) | Backend, production, orders |
| [0028](0028-a-shipment-recorded-in-error-is-reversed-not-deleted.md) | Reverse a shipment recorded in error instead of deleting it, and never let a reversed delivery count as a previous one (completes [0027](0027-a-stock-count-corrects-a-fifo-guess.md)) | Backend, production, orders |
| [0029](0029-the-batch-on-a-produced-event-is-correctable.md) | The batch on a `produced` event is the one reference in a device's history a later correction may rewrite — it records a choice made at the bench, not an event (narrows [0003](0003-orders-shipments-and-device-history.md) §5) | Backend, production, flasher, orders |
| [0030](0030-good-units-are-counted-not-typed.md) | Count the devices that passed instead of typing what a batch yielded — every per-device figure divides by the device records, never by the boards ordered from JLC (applies [0007](0007-built-means-finished-and-passed.md) to cost) | Backend, frontend, production, economics |
| [0031](0031-a-batch-that-records-its-devices-has-no-anonymous-units.md) | Refuse an anonymous unit from a batch that records its devices, and drop the option to invent one (narrows [0027](0027-a-stock-count-corrects-a-fifo-guess.md) §5 and [0003](0003-orders-shipments-and-device-history.md) §8) | Backend, frontend, production, orders |
| [0032](0032-a-shipment-names-its-devices.md) | A shipment is a SET OF SERIALS, never a quantity — the FIFO pick, `reconcile_shelf` and the return-swap are gone, and `condition` says a device is here but not sellable. Supersedes [0027](0027-a-stock-count-corrects-a-fifo-guess.md) and narrows [0003](0003-orders-shipments-and-device-history.md) §6 and §8 | accepted |
| [0029](0029-a-release-is-a-file-set.md) | A release is a content-addressed file set, platform wide, and a deployment version pins the set — no per-file versions, no bundle beside the pins (supersedes [0026](0026-a-device-file-carries-its-kind-and-enters-by-upload.md)) | Backend, frontend, production, flasher, storage |
| [0033](0033-the-broker-observes-devices-it-never-commands.md) | Watch the fleet MQTT broker read-only — subscribe to LEAF topics, never publish to a customer device, and let the broker FILL a missing MAC but never CHANGE one | Backend, frontend, production, flasher, access control |
| [0034](0034-stock-moves-when-the-supplier-says-so.md) | Write a consigned draw when the JLC invoice reports it, charged to nobody, and let a later decision say which batch pays — `component_consumptions.run_id` is nullable, and "decided" stops meaning "written" | Backend, frontend, production, economics |
| [0035](0035-a-supplier-bills-what-was-ordered.md) | A supplier's per-board rate is billed on what was ORDERED (`planned_units`), while per-device COST keeps dividing by what passed (`good_units`) — a merged assembler invoice is split, never guessed (narrows [0030](0030-good-units-are-counted-not-typed.md)) | Backend, production, economics |
| [0036](0036-the-dongle-device-log-is-rebuilt-from-the-facts.md) | Rebuild the CE_Dongle_V2 device log from the established facts instead of appending ~4,400 reversals to 4,326 FIFO guesses — a ONE-TIME exception to [0003](0003-orders-shipments-and-device-history.md)'s append-only rule, for one project | Backend, production, orders |
| [0037](0037-the-bench-says-what-it-already-knows.md) | The bench checks what it already knows the moment the MAC is read — exactly one check BLOCKS (the device belongs to another project), every other is a notice the operator takes by name with an optional reason, and the ordinary case stays silent. Blocking on batch `status` was rejected on the data | Backend, frontend, production |
| [0037](0037-the-supplier-keeps-the-receipts.md) | Sync JLCPCB's own per-part inventory ledger with the stock count, reconcile both directions against it, and correct our books only from its rows — a cancelled lot is refreshed into a fee, a warehouse pick is booked as an uncharged draw, and nothing books itself | Backend, frontend, production, economics |
| [0038](0038-a-substitution-belongs-to-the-batch.md) | Record a part fitted in place of the specified one on the BATCH, keyed by designator so it survives a BOM re-export — detected from the supplier's own BOM, never auto-applied, and a design that has not caught up is a standing finding on the Stock page | Backend, frontend, production, economics |
| [0039](0039-a-prototype-is-counted-without-being-named.md) | Count a prototype batch with placeholder units that carry no MAC and no serial, and mark them `condition=prototype` so they can never be sold — narrows [0032](0032-a-shipment-names-its-devices.md) for prototypes only | Backend, production, orders |
| [0040](0040-a-purchase-cannot-be-removed-from-under-its-draws.md) | Refuse a purchase edit that would leave draws with no purchase behind them, and allow every one that stays covered — a date-aware replay through `check_shortages`, not "this part has been consumed" (which measured at 260 of 264 lines locked) | Backend, frontend, production, economics |
| [0041](0041-the-supplier-parts-lump-is-a-small-bom.md) | Itemise the parts a SUPPLIER sourced into ordinary cost-line children charged to the batch and never pooled, and check every position's coverage against the supplier's own BOM — `extPrice` is billed on the shop portion only, and `componentNum` is per PANEL | Backend, production, economics |
| [0042](0042-a-substitution-records-where-the-change-was-defined.md) | A substitution's `source` records WHERE the change was defined — on the supplier's order or here — not who decided it; the common case is us choosing a part on their site while ordering (corrects item 9 of [0038](0038-a-substitution-belongs-to-the-batch.md)) | Backend, frontend, production |
| [0043](0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md) | A batch reports COST only and an order reports revenue; a UNIT carries its batch's per-device cost onto the order that ships it, and that cost divides by devices PRODUCED, not boards ordered (completes [0003](0003-orders-shipments-and-device-history.md), narrows [0030](0030-good-units-are-counted-not-typed.md)) | Backend, frontend, production, economics |
| [0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md) | Closing the books on a batch makes the documents that charge it read-only, and the only way to move its cost afterwards is a CORRECTION document dated when the correction is made — the component half already worked this way, the direct-cost half moved a per-device cost silently on every edit (completes [0040](0040-a-purchase-cannot-be-removed-from-under-its-draws.md), protects [0043](0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md)) | Backend, frontend, production, economics |
| [0045](0045-configuration-is-an-administrators-surface.md) | Put the deployment's own configuration behind the administrator role, and state the admin-only set in a test (extends [0002](0002-field-solver-in-the-platform.md) to field-solver rule sets) | Backend, frontend, access control |
| [0045](0045-a-position-says-where-its-money-goes.md) | An invoice position STATES its destination and how the money gets there, in two controls — `allocate` gains `pooled` so "it is stock" stops being spelled the same as "nobody has decided", and `basis`, `allocate` and `exclude_reason` become settable at all (the empty "— nobody —" resolved to FIVE different destinations from fields that were not on screen) | Backend, frontend, production, economics |
| [0046](0046-the-broker-names-a-device-the-platform-already-counted.md) | Give a counted device its name, do not count it again — 14 prototype-era dongles found on the MQTT broker fill the anonymous `PROTO-xxxx` rows that 0036 already shipped and invoiced, and the two prototype runs created alongside hold COST only, never a second delivery | Production, economics, fleet |
| [0047](0047-the-step-says-what-a-position-is.md) | The production STEP says what an invoice position is and `run_cost_lines.kind` is DROPPED — the coarse bucket is derived from the step (`cost_steps.kind_of`), "is this stock" is asked once via `PART_STEPS`, and the 12 rows where the two disagreed turned out to be one step key standing in for two different things (completes [0045](0045-a-position-says-where-its-money-goes.md)) | Backend, frontend, production, economics |
| [0048](0048-the-gap-is-an-invariant-not-a-tolerance.md) | `gap_usd` measures the platform's own arithmetic and is exactly 0 — it was measured against the PRINTED total, so it read 0.0271 forever while the screen printed a green "0" for anything under 0.05. The facts it was hiding get names: `untranscribed_usd`, `overallocated_usd`, and `excluded_unstated_usd` (51,234 recorded as charged to nobody with no reason given) | Backend, frontend, production, economics |
| [0049](0049-a-delivery-names-its-devices-and-nothing-else.md) | `shipment_lines` is DROPPED and `qty_unserialized` refused — 0032 removed the automatic anonymous delivery and left the manual one, and all three survivors were prototype batches double-counted against their own placeholders. A prototype that really shipped is `ok`; `prototype` now means it never left | Backend, frontend, production, orders |
| [0050](0050-every-change-names-the-person-who-made-it.md) | Every change names the person who made it — the gate binds the signed-in user to the request, `audit_log` gets `user_id`/`request_id` and stays the ONE log: a `request` row per write call and a `row.*` row per ORM row changed, secrets redacted; a name sent by the client is ignored when somebody is signed in, and Admin → Activity reads it, admin-only | Backend, access control, audit |

## Proposed

| # | Decision | Area |
|---|---|---|

## Superseded

| # | Decision | Superseded by |
|---|---|---|
| [0026](0026-a-device-file-carries-its-kind-and-enters-by-upload.md) | A device file carries its kind, enters the pool by upload, and is never deleted while pinned | [0029](0029-a-release-is-a-file-set.md) |
