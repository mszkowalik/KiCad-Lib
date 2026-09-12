# Field solver (`api/app/services/fieldsolver`)

The 2D quasi-TEM solver behind Simulator to Field solver. Decision
[0002](../../../../docs/decisions/0002-field-solver-in-the-platform.md) holds the
reasoning. The UI rules are in `web/src/sim/field/CLAUDE.md`.

A 2D quasi-TEM FEM solver for controlled-impedance geometry — microstrip,
stripline, coplanar and differential, with via fences. `services/fieldsolver/` is
a self-contained package (P1 triangles on a Triangle mesh, scipy sparse solves)
that imports nothing from the platform; the router is the platform half. Design
record: `docs/decisions/0002-field-solver-in-the-platform.md`.

- **Its dependencies are new and one of them is licence-constrained.** numpy,
  scipy, shapely and `triangle`; Triangle is free for personal and research use
  but NOT for commercial distribution. It also needs TWO requirements for one
  package, both in `pyproject.toml`: release 20250106 publishes a manylinux
  x86_64 wheel but no manylinux aarch64 wheel and no sdist, and the last sdist
  cannot compile on Python 3.12. So amd64 installs the wheel and arm64 builds
  tag `v20250106` from upstream git, for which `api/Dockerfile` adds gcc and
  removes it in the same layer. The import in `mesh.py::_tr()` stays LAZY, so a
  machine that somehow lacks the mesher still starts and answers 503 for solver
  calls alone.
- **User-defined stackups and rule sets live in Postgres** (`FieldStackup`,
  `FieldRuleSet`), never in JSON beside the code. The solver keeps them in
  module state because it is a pure library, so every request that reads or
  solves calls `_sync_library(db)` first — two small selects. Stackup writes are
  **admin-only** (`require_admin`), because a stackup is a shared fact about how
  boards are made.
- **A board's stackup and profiles are commit-versioned** in
  `services/field_state.py`, which mirrors `services/cost_state.py` exactly:
  `revision_for` selects by commit date, `revision_for_edit` copies on write, and
  the profile COPIES carry their results. Never delete a profile because the
  stackup changed — `is_outdated` compares the stored `stackup_sha` against the
  board's current one and the UI says so.
- **`stackup_sha` hashes layers, coating and finish only.** Renaming a stackup
  must not invalidate anybody's numbers.
- **A stackup carries only what changes a field** (decision
  [0008](../../../../docs/decisions/0008-a-stackup-is-electrical-only.md)). No colour, ever:
  `JLC06121H-3313A` in seven mask colours is fourteen library rows the solver cannot
  tell apart. Board colour is PROJECT data — `mask_color` / `silk_color` on
  `ProjectFieldRevision`, versioned like the assignment, written by
  `POST /projects/{id}/appearance`, and the choices come from
  `GET /api/fieldsolver/colors` (JLCPCB's own list; the legend follows the mask).
- **`soldermask`, `finish` and `silkscreen` on a stackup mean the TOP FACE.** The
  per-face truth is `faces: {top, bottom}`; those three are kept because
  `templates.py` guards every mask region with `outer_top` and only ever coats the
  top, so redefining them would silently change every solved geometry. `_face_of`
  reads either shape — a bare value means both faces, which is what every stackup
  written before faces said, so nothing needed migrating.
- **`StackupLibrary.normalise` runs on every save and refuses an unbuildable stack.**
  Copper is renamed `L1`…`Ln` by position and a dielectric's label is generated from
  its material and the copper pair it lies between — neither is typed, so a stackup
  cannot claim its third copper layer is `L5`. Copper against copper is rejected
  (nothing insulates them, and the solver would model a different board without
  complaining); several dielectrics in a row are fine, because a fab lists each
  prepreg sheet and `JLC06121H-3313A` has three in one gap.
- **`field_state.stack_rows` is the ONE place the two sides are aligned.** It reduces
  a `.kicad_pcb` and a stackup to the same normal form — the ordered copper layers and
  the dielectric GAP between each neighbouring pair — and every view of a stackup in
  the browser draws that list. Aligning in the page instead would let the picture
  drift from the verdict. KiCad allows only `copper - 1` dielectric layers, so a fab
  gap of three prepreg sheets is one KiCad dielectric with `addsublayer` sub-layers;
  reading only the first `(thickness)` of such a layer silently loses the rest.
- **The comparison reports and refuses nothing.** A board file is allowed to disagree
  with the stackup it is solved against (decision 0002). `severity` separates a
  difference that decides the verdict from one that is shown and does not — the
  surface finish is the latter, because it is a separate order option at the fab.
- **Profiles saved to a board go through `POST /projects/{id}/profiles/batch`**, not N
  calls to `save_profile`: `revision_for_edit` is copy-on-write, so the first call
  would create the revision and a failure halfway would leave a partial save. It
  refuses — writing nothing — when the board's assigned stackup is not the one the
  profiles were built on, server-side, because the agent tools use the same path.
- **`field_workspaces` is scratch space, one row per person**, holding the solver
  page's own state banked BY STACKUP. A profile's cells are keyed by copper layer
  name, so a set built on a six-layer board describes nothing on a two-layer one;
  switching stackups parks one bench and picks up another. No history — the moment
  work matters it is saved to a project, which is versioned.
- **A stored result holds numbers, not fields.** Summary, sweep, C/L, notes and
  the geometry outline; never the solved mesh (tens of megabytes per frequency
  frame). That is what makes reopening a profile instant and why the field
  picture alone needs a re-solve.
- **Jobs are cancellable and abandoned jobs cancel themselves.** The progress
  callback raises on a cancel flag; `DELETE /api/fieldsolver/jobs/{id}` sets it,
  and a reaper cancels any job whose client has not polled for 20 s. A solve
  holds a core and hundreds of megabytes, so a closed tab must not keep one.
- **The search pool is capped** (`design.WORKERS`, default 4,
  `FIELDSOLVER_WORKERS` to override) and `design.kill_stray_workers()` sweeps
  orphans when nothing is running. An unbounded pool once left 40 GB of workers
  behind and pushed the machine into swap.
- **One factorisation per run.** `fem.Solver(mesh, K, pre)` reuses the
  design-frequency LU as a CG preconditioner for every sweep point, because Dk
  dispersion moves K by only a few percent: a 31-point sweep on a 78k-node mesh
  went from 12.1 s to 4.9 s with results identical to 7e-13 %.
- **The model is floored at 1 MHz** (`F_MIN_HZ`). Below that the
  perfect-conductor assumption stops describing a board. An eddy-current solver
  covering DC through the skin-effect transition was written, validated against
  the analytic DC loop resistance and then removed on purpose — do not
  reintroduce a current-distribution view without reinstating it.
- Physics tests live in `api/tests/fieldsolver/` (`python -m pytest
  tests/fieldsolver -q` from `api/`): a parallel-plate line with exact C, Z0 and
  eps_eff, its analytic conductor loss, plus `validate.py` for the closed-form
  comparisons (microstrip Hammerstad-Jensen, stripline Wheeler, CPWG conformal).

## Stackups and profiles are project data

These three rules are expensive to get wrong. Decision
[0002](../../../../docs/decisions/0002-field-solver-in-the-platform.md) holds the
reasoning.

- **Stackups are written by administrators only** — they describe how the fab
  builds boards and everyone shares them. Anyone may assign one to a board.
- **A board's stackup and its impedance profiles are commit-versioned**, with the
  same copy-on-write rule as the cost plan: assigned at a commit, carried forward
  by later commits until changed, and earlier commits keep what they had.
- **Changing the stackup keeps every profile and every result** and marks the
  results outdated. The stored result holds the numbers, never the solved mesh.

The solver is quasi-TEM and floored at **1 MHz**; `triangle`, its mesher, is
free for personal and research use only and must be replaced before any

The solver is quasi-TEM and floored at **1 MHz**; `triangle`, its mesher, is
free for personal and research use only and must be replaced before any
commercial release.
