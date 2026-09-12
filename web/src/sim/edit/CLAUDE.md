# The sketch editor (`web/src/sim/edit`)

## A sketch has no edit mode, and it opens RUNNING

Falstad has no Edit button, and neither does a sketch any more: the tools are
always out, the page opens in Live, and Scenario is the mode you switch to
deliberately — the formal run, the harness, the verdicts. A project sheet's
schematic tab offers both doors: **Simulate** (scenario) and **Play live**
(`?mode=live`).

The click grammar that makes always-editing coherent (Falstad's own):

- **click** selects — a wire click also plots it, a pin click plots the
  terminal; neither has a drag gesture to collide with;
- **drag** moves;
- **double-click** opens the part dialog (Plot current lives in there now —
  plotting on every selection put a trace on the scope each time a part was
  picked up to move it).

Two rules with teeth:

- **Live edits never write a project file.** A sketch is scratch space in
  `sim_uploads/`; a sheet from a git project is read-only in live, knobs only.
  Download is the only way out of the playground, by design — the git checkout
  is the source of truth.
- **A pin dropped on the MIDDLE of a wire is connected** (`attach()` in the
  netlister, same rule as labels and junctions). That is what makes dragging a
  part onto a live circuit join it mid-gesture; the reload pipeline needs no
  drag-special-casing at all, because a reload only fires when the netlist
  STRUCTURALLY changed — a part floating in space between two connections
  produces no reloads, severing and rejoining each produce exactly one.

## Sketch live mode is a RELOAD, never a restart (`sim/edit/netlist.ts`)

The Falstad feel — edit the circuit while it runs, parts keep their state —
rests on three pieces, and each exists for latency:

1. **The browser netlists the document itself.** For a sketch we own every
   byte, so `netlistDoc` writes the SPICE netlist in under a millisecond and
   the start frame carries it — kicad-cli (the slowest step, QEMU-emulated on
   a Mac) is not in the path at all. Project sheets still go through
   kicad-cli; that file is not ours to reinterpret.
2. **An edit is `session.reload(...)`, debounced 120 ms.** Same worker, same
   websocket; the worker halts, swaps the circuit, and resumes. The session is
   created ONCE per live toggle — geometry refreshes and vector changes must
   not tear it down, or every autosave would restart the run.
3. **State travels on the components.** Each C and L card in a reload carries
   `IC=%IC_<ref>%`; the WORKER fills the token from its own last data point
   (cap voltage across its OLD nodes, inductor branch current) and `.tran uic`
   starts from there. Keyed to the reference, not the node — a charged cap
   unwired, dragged away and rewired elsewhere is still charged. `rshunt=1e12`
   keeps the floating island solvable in between.

Rules that were paid for:

- **Node names are lowercase from birth, and an edit REUSES the running run's
  names** (`reuse` callback: last netlist first, server geometry second — the
  geometry is a save behind during a burst of edits). One vocabulary across
  the netlist, the frames and the overlay, or traces die on every edit.
- **A name is claimed ONCE per build, biggest net first.** Reuse works by pin
  membership, and a pin that LEFT a net still remembers it — so a severed
  op-amp's floating output pin reclaimed `/ampout` while the labelled wire
  kept it too, SPICE merged the two same-named nodes, and the part went on
  driving a wire it was visibly not connected to (the drawing said severed,
  the voltage kept swinging). Labels and power names are claimed first; then
  nets in descending pin count, so the net that kept most of the membership —
  not a lone runaway pin — carries the name forward.
- **A label names the wire it sits ON, not the endpoint it touches.** People
  put labels mid-segment; joining labels only by endpoint coordinates renamed
  `/in` to `net-_u1-pad1_` silently — measured on the worked example itself.
- **Frame v2 carries its own overlay count.** A reload changes the overlay
  while frames closed against the old list are in flight; a frame must be
  sliced by what IT holds, not by what the config now says.
- The netlist names the model library by token (`%SIGMA_SIM_LIB%`); the render
  server substitutes the real path and refuses any other `.include`.

