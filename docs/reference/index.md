# Reference

Long-form topic documents. A `CLAUDE.md` next to the code links to the page it
needs, so a rule is written once and read where it applies. Keep a page here
when the rule is too long to sit in a `CLAUDE.md` without crowding out
everything else in that directory.

These pages state the current fact. They are not a history: when a rule changes,
edit the sentence. A decision that is expensive to reverse belongs in
[../decisions/](../decisions/) instead, and an accepted decision record is never
edited.

| Page | Holds | Read it before you change |
|---|---|---|
| [glossary.md](glossary.md) | Which "run", which "order" — the two words that each name two unrelated things, every entity once, and what `qty` / `plan_qty` / `qty_good` / `qty_sold` each mean on a production run | saying "run" or "order" to anyone, and any quantity on a batch |
| [writing-instruction-files.md](writing-instruction-files.md) | The six rules for a `CLAUDE.md` or a page here: line budget, the derivability test, link-never-summarise, narrowest file wins, no `@path` imports, no edit narration | any `CLAUDE.md` or a page in this directory |
| [datasheets.md](datasheets.md) | Document identity, the fetch ladder, classification, the page index | `services/datasheet_store.py`, `datasheet_pages.py` |
| [production-economics.md](production-economics.md) | Cost plans, invoices, stock, orders, sales, the built rule | `services/cost_state.py`, `material.py`, `stock.py`, `orders.py` |
| [review-axis.md](review-axis.md) | Production sign-off, verification, the review record and what carries | `services/signoff.py`, `review.py` |
| [publish-sanitization.md](publish-sanitization.md) | What a publish corrects for you, the two rules that decide what may go in, and why one field is emptied where another is deleted | `services/geometry_proposals.py` |
| [what-a-check-can-hold.md](what-a-check-can-hold.md) | Which convention rules a check can enforce, which must stay prose, and the order to move one | `services/validator.py`, the convention skills |
| [projects-module.md](projects-module.md) | Git-tracked designs, mirrors, snapshots, exports, credentials | `services/gitrepo.py`, `project_ops.py` |
| [spice-runs.md](spice-runs.md) | Netlists, ngspice, verdict harnesses, the live sketch | `services/sim_spice.py`, `project_ops.py`, `sch_lib.py` |
| [simulation-models.md](simulation-models.md) | Model storage, generated package wrappers, composition | `services/simmodel.py`, `sim_store.py`, `simcompose.py` |
| [jaravis.md](jaravis.md) | The agent tool implementation | `services/jaravis.py` |
| [pcm-packaging.md](pcm-packaging.md) | Package retention, per-package versioning, the personal repository URL | `services/pcm.py` |
| [kicad-integration.md](kicad-integration.md) | How the library reaches KiCad, the HTTP catalog, field visibility | `services/generator.py`, `mirror.py`, the plugin |
| [deployment.md](deployment.md) | Images, GHCR, the build cache, the server | a Dockerfile, a compose file, the workflow |
| [bench-serial-ports.md](bench-serial-ports.md) | How a bench station is bound to a USB socket — the node name IS the socket, the V2 bridge has no serial number, and why this needs the agent | `web/src/flasher/station.ts`, `SocketPicker.tsx`, the bench port rules |
| [mqtt-presence.md](mqtt-presence.md) | What the fleet MQTT broker carries, why the subscription is LEAF topics only, the three presence states, and the rule that the broker may fill a missing MAC but never change one | `services/mqtt_monitor.py`, `mqtt_config.py`, `routers/mqtt.py`, the topic list |
| [laser-marking.md](laser-marking.md) | Running a marking bench, authoring a marking procedure, what the BSL controller is and why the platform drives LightBurn instead | `api/app/services/bench_agent/`, `mark_laser`, decision 0020 |
| [dongle-stock-reconciliation.md](dongle-stock-reconciliation.md) | **Working file, delete when the clean-up lands.** What was assembled, programmed, shipped and held for CE_Dongle_V2: which batch supplied which order, why boards assembled but never programmed accumulate across sessions, and the four traps the investigation hit | touching CE_Dongle_V2 stock, quantities or deliveries |
| [label-printing.md](label-printing.md) | How a serial becomes a Code 128 label, why the agent lays it out, the roll table, and the four measurements that make a label scannable | `api/app/services/bench_agent/`, `print_label`, decision 0022 |
| [simulator-audits.md](simulator-audits.md) | Two read-throughs of the simulator and what they found | `web/src/sim/` |
| [change-tracking.md](change-tracking.md) | The request log, the audit stamp and the change log: what each records, how they join on `request_id`, and six rules for new code (client-supplied names, threads, Core statements, secrets) | `services/tracking.py`, `authgate.py`, any new who-column, thread or secret column, decision 0050 |
