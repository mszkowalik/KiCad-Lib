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
| [writing-instruction-files.md](writing-instruction-files.md) | The six rules for a `CLAUDE.md` or a page here: line budget, the derivability test, link-never-summarise, narrowest file wins, no `@path` imports, no edit narration | any `CLAUDE.md` or a page in this directory |
| [datasheets.md](datasheets.md) | Document identity, the fetch ladder, classification, the page index | `services/datasheet_store.py`, `datasheet_pages.py` |
| [production-economics.md](production-economics.md) | Cost plans, invoices, stock, orders, sales, the built rule | `services/cost_state.py`, `material.py`, `stock.py`, `orders.py` |
| [review-axis.md](review-axis.md) | Production sign-off, verification, the review record and what carries | `services/signoff.py`, `review.py` |
| [projects-module.md](projects-module.md) | Git-tracked designs, mirrors, snapshots, exports, credentials | `services/gitrepo.py`, `project_ops.py` |
| [spice-runs.md](spice-runs.md) | Netlists, ngspice, verdict harnesses, the live sketch | `services/sim_spice.py`, `project_ops.py`, `sch_lib.py` |
| [simulation-models.md](simulation-models.md) | Model storage, generated package wrappers, composition | `services/simmodel.py`, `sim_store.py`, `simcompose.py` |
| [jaravis.md](jaravis.md) | The agent tool implementation | `services/jaravis.py` |
| [pcm-packaging.md](pcm-packaging.md) | Package retention, per-package versioning, the personal repository URL | `services/pcm.py` |
| [kicad-integration.md](kicad-integration.md) | How the library reaches KiCad, the HTTP catalog, field visibility | `services/generator.py`, `mirror.py`, the plugin |
| [deployment.md](deployment.md) | Images, GHCR, the build cache, the server | a Dockerfile, a compose file, the workflow |
| [simulator-audits.md](simulator-audits.md) | Two read-throughs of the simulator and what they found | `web/src/sim/` |
