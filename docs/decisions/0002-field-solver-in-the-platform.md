# 2. The field solver lives in the platform, and its stackups are project data

Date: 2026-08-31

## Status

Accepted

## Context

Controlled-impedance geometry was worked out in a standalone prototype
(`fieldsolver/`, port 8765): a 2D quasi-TEM FEM solver for microstrip, stripline,
coplanar and differential lines, with JLCPCB stackups and production rules as
presets. It proved the physics — validated against closed forms and against the
fab's own calculator — but it kept its data in JSON files beside the code, so a
stackup somebody built was invisible to every other person and to every project.

At the same time the platform already answers "what is this board made of" for
the BOM and for the cost plan, and answers it PER COMMIT: assigned at one commit,
carried forward until somebody changes it. Impedance work belongs to the same
question. A board's controlled-impedance geometry is not a scratch calculation —
it is a fact about the design that has to survive the next commit, the next
person and the next review.

## Decision

1. **The solver moves into the platform** as `api/app/services/fieldsolver/` (a
   self-contained FEM package with no platform imports) behind
   `api/app/routers/field_solver.py`, and the UI becomes a subtab of the
   Simulator (`/sim?tab=field`). The standalone prototype is deleted.
2. **Stackups are a shared library, written by administrators only.** They
   describe how a fab builds boards, so they are not per-user scratch data.
   Everyone may read them and assign them; only an admin may create or edit one.
3. **A board's stackup and its impedance profiles are commit-versioned**, using
   the same copy-on-write revision rule as the manual cost data
   (`services/field_state.py`, mirroring `services/cost_state.py`): assigned at
   commit X, applies from X forward, an edit at Y forks a revision at Y, earlier
   commits keep what they had.
4. **Changing the stackup never deletes a profile.** Profiles and their results
   are carried onto the new revision; a result computed against a different
   stackup is reported as OUTDATED and stays readable. Losing the numbers would
   punish the user for recording the change.
5. **A stored result holds numbers, not fields.** Summary, sweep, C/L, notes and
   the geometry outline are kept in Postgres; the solved mesh is not, because it
   is tens of megabytes per frequency frame. Reopening a profile shows every
   figure at once and only the field picture needs a re-solve.
6. **The board file and the assigned stackup may disagree, and the platform says
   so.** A `.kicad_pcb` need not declare the fab's stackup; where it does, the
   copper count and total thickness are compared and any difference is reported.
   Nothing is blocked — the impedance numbers are computed against the ASSIGNED
   stackup, which is what the fab will build.
7. **The model is floored at 1 MHz.** Below that the perfect-conductor
   assumption stops describing a real board. An eddy-current solver that covered
   DC through the skin-effect transition was written and validated (it reproduced
   the analytic loop resistance exactly at DC) and then deliberately REMOVED: the
   product is the quasi-TEM solver, and a second physics model with its own
   validity window was more surface than the question justified.

## Consequences

- `numpy`, `scipy`, `shapely` and `triangle` become API dependencies.
  **`triangle` is licensed for personal and research use, not for commercial
  distribution** — fine for this in-house platform, but the mesher has to be
  replaced before any commercial release. It is also amd64-only in practice
  (no sdist that builds on Python 3.12), so it carries a platform marker and
  `mesh.py` imports it lazily; an arm64 dev box runs the whole platform and
  answers 503 for solver calls alone.
- A solve is a background job with progress, cancellation, and a reaper that
  cancels a job whose browser stopped polling — a solve holds a core and
  hundreds of megabytes. The search pool is capped at four workers for the same
  reason (an unbounded pool once orphaned 40 GB of workers and swapped the
  machine).
- Two surfaces write the same data: the project's own **Stackup** tab, and a
  **Save to a project** panel inside the field solver — the second exists because
  the common way in is sideways, working something out first and needing
  somewhere to keep it afterwards.
