# Field solver UI (`web/src/sim/field`)

The backend rules are in `api/app/services/fieldsolver/CLAUDE.md`. Decision
[0002](../../../../docs/decisions/0002-field-solver-in-the-platform.md) holds the
reasoning, and
[0008](../../../../docs/decisions/0008-a-stackup-is-electrical-only.md) says a
stackup is electrical only. The rules on who may write a stackup, how profiles
are commit-versioned, and what happens to results when a stackup changes are in
`api/app/services/fieldsolver/CLAUDE.md`.

Simulator → Field solver (`/sim?tab=field`), a subtab beside Circuit. It sizes
controlled-impedance traces against a stackup and draws the solved cross-section.

- **The cross-section is a canvas, and every colour is read from the palette.**
  A solved mesh is 150 000 triangles, which the DOM will not take. `draw.ts`
  resolves `--sim-hot` / `--sim-cold` / `--fs-signal` / `--fs-mask` and the rest
  with `getComputedStyle` on every paint — the same trick `useSimOverlay` uses —
  so the drawing follows the light/dark theme. Never hard-code a colour there.
  `--fs-signal`, `--fs-reference`, `--fs-mask` and `--fs-finish` are its own
  palette entries and have a dark variant.
- **The chart is SVG and takes its colours as `var(...)` strings**, which is why
  it can stay in the stylesheet while the canvas cannot.
- **A solve is a job, not a request** (`useSolverJob.ts`): it polls, streams the
  design-frequency result before the sweep finishes so the field appears early,
  and cancels — both on the Cancel button and when the component goes away.
- **The page calls the single-ended line "single"; the solver calls it
  "microstrip".** `cellParams` maps it. Sending the page's word produced a
  differential geometry with no error at all.
- **Two surfaces write the same project data**: the project's Stackup tab
  (`components/project/StackupTab.tsx`) and the "Save to a project" panel inside
  the solver (`ProjectPanel.tsx`). Both go through the same endpoints, and both
  must keep saying that an assignment applies from the chosen commit forward.
- **Stackup editing is gated on `useAuth().isAdmin`**, matching the API.
