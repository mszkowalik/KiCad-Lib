# Simulator audits — what the code did wrong, and what it looks like when fixed

Two read-throughs of `web/src/sim/`. Both found bugs that had shipped, so the
findings stay written down: the same seams keep producing the same class of
defect. The live rules are in `web/src/sim/CLAUDE.md`.

## Audit findings, 2026-09-07 — the animation was never drawn

A full pass over the simulator after "errors everywhere". Fixed, with the rule
each one leaves behind:

- **The charge canvas was 1474 x 0 for the life of the page.** `paint` in
  `useSimOverlay` resized the bitmap only when its WIDTH changed; the first
  paint lands before the split has a height, so the height stayed 0 and no
  dot was ever drawn, in any mode. Compare both sides before resizing a
  canvas bitmap.
- **Live mode never advanced the clock.** The only writer of `clock` was the
  replay loop, which runs when `playing` is true — and a live run never plays.
  The loop now runs for a replay OR a running live session, and only a replay
  steps the sample. The dots moving on a sketch before this was the auto-run
  race leaving `playing` true.
- **A live legend showed the OLDEST column as "now".** The page cursor is a
  replay position and reads 0; a live grid is NaN-padded on the left, so
  `statsOf` read the left edge. `LegendPill` takes `+Infinity` when live.
- **A stopped session wrote into the page.** `stop()` closed the socket and
  left `onclose` attached, which fired after the page had replaced the
  session. Null every handler before `close()`.
- **A live vector the worker could not resolve read 0 A, not null.** The
  `ready` event's `missing` list is now kept on `LiveState` and left out of
  `liveIndex`, so the reader answers null and the current solver counts an
  unknown terminal, as it does for a finished run.
- **The previous board's sheet path survived a source change** and could
  leave a stale "no such sheet instance" banner. The sheets effect resets it.
- **Pressing Run paused the replay it started.** The dock grows when the
  scope card appears, the new pane lands under the pointer resting on Run,
  `pointerenter` set the hover flag, and the replay's own programmatic
  `setCursor` was reported as a scrub. The hook now also requires
  `u.cursor.event`, which uPlot leaves null for a cursor the page set.
- The scratch files `src/sim/__net.mts` / `__repro.mts` imported JSON that
  does not exist and broke `npm run build` (`tsc --noEmit`). Do not leave
  `__*.mts` probes in `src/`.

Server-side fixes from the same pass are in
[spice-runs.md](spice-runs.md) (a control block
sent with its own fences, ngspice errors reported as success, diode currents
named `[id]`, sheet-pin nets on a root sheet).

Still open, found and not fixed (2026-09-07): wire probes are keyed by file
index (`iw(w12)`), which shifts when an earlier wire is deleted; a net split
into two wire groups joined only by labels solves each group as closed, so its
segment currents are wrong; a run with both `.op` and `.tran` shows the
one-point `.op` plot first; `GET …/sketch` answers 404 on every KiCad upload,
which is one console error per open.

## Audit findings, 2026-09-01 — the naming seams are where the bugs live

A sweep after the severed-op-amp bug, looking for the same disease elsewhere.
Fixed:

- **The diode card doubled its element letter.** `spiceName("D1")` is already
  `d1`; the card prepended another `d`. `dd1` ran fine — under a name the
  geometry does not know, so the diode's current, charge dots and alter were
  all dead. Any card built from `spiceName` must NOT re-prefix.
- **`liveReader.current` tried only the savecurrents spelling.** A source's
  current is its own branch (`i(v1)`), so every source read null in live
  mode, every source pin became an "unknown terminal", and the charge overlay
  and probe fallback quietly degraded.
- **Adding a capacitor or inductor mid-run killed the reload.** The browser
  measures carry-state on the circuit being REPLACED, so a brand-new part's
  `%IC_<ref>%` token had no state entry, reached ngspice unfilled, and the
  whole edited netlist was refused ("error" banner). The worker
  (`render/sim_worker.py`) now zero-fills every leftover token — a new part
  arrives uncharged, which is what adding it mid-run means.
- **A switch on a net zeroed every wire current on it.** The drawing says
  `SW1`; the run's element is `rsw1` (`Sim.Device` prefix). The current
  solver asked the run for `sw1`, got null, counted the switch an unknown
  terminal — two unknowns with the op-amp, and the whole net's segments came
  back 0. `currents.ts` now translates ref → element (`elementOf`, from
  `sym.spice`) everywhere it reads or names a current, `probeTerms` counts
  unknown terminals up front (a coefficient read off a pre-zeroed unresolved
  net is a silent 0, not a NaN), and the KiCad-sourced live overlay list asks
  for element-named currents too.
- **A dying transient froze the page at RUNNING.** ngspice aborts a
  background run (timestep too small, singular matrix) with no callback the
  worker listened to — frames just stopped. `sim_worker.py` now keeps
  ngspice's own output in a ring (`_on_char`) and a watchdog thread turns an
  unexpected `ngSpice_running() == False` into an `error` event carrying the
  last error lines. Deliberate halts (Hold, an alter's pause, a reload's
  swap) set `deliberate_halt` and stay silent; bg_run re-arms the watch, so
  fixing the circuit and reloading recovers the same session.
- **A severed terminal's current vanished instead of reading zero.**
  `solveSegmentCurrents` skipped wireless groups entirely, so a pin left on a
  floating one-pin net had no entry and its probe drew gaps. The injection
  accounting now runs for pin-only groups too — a lone unknown pin reads 0 by
  conservation, a pin-to-pin contact still resolves — so a disconnected
  current drops to zero the way a floating node's voltage does.
- **A speed change kept history at the old timebase.** Carried columns are
  sim-seconds-per-column; the carry now requires the pitch to match, and the
  worker's backlog (which resets on the same change) reseeds.

The circuit tab is a SPLIT that fills the window: `.sim-split` (height
measured from its top edge to the viewport bottom) holds the canvas slot
(flex:1) over `.sim-dock` (run bar + scope, natural height, scope card
scrolling internally past ~36vh) — schematic and waveform share one screen,
Falstad's one-window reading. `SchematicView` gained a `fill` prop for this:
instead of sizing the frame by the view's aspect (which shrank the drawing to
a stamp in a fixed-height slot), the frame fills the box and the VIEW is
padded to the box's aspect around its centre — the viewBox always fills the
frame, so the pixel-mapping layers (charge canvas, click targets) stay honest.
Wheel, pan and all mm mapping work in that `shown` window. The reference
drawer still sits below the split in page flow. The pixels go to the drawing,
Falstad's proportions: no page `<h1>`, the Circuit/Field-solver tabs share
the topbar row, `.page-sim` compacts card padding/margins and gaps to
hairlines, panes are 104px with the scope's status folded into the Plots bar row
(`head` prop — the `.sim-scope-head` row is gone) and a hairline legend, the
scope card caps at 34vh (sized so TWO compact panes fit unscrolled at 1080p), the canvas slot
never drops under 300px, and a sketch that already carries a circuit opens
FITTED (`openFit`, decided once per document uuid) instead of on the fixed
`OPENING_VIEW` working window. In LIVE mode the run controls (Hold, status,
Speed, the t/points readout) render `bare` inside the topbar beside the volt
scale and current slider — the dock carries a run bar only in scenario mode.
The `.sch-props` card under the canvas renders
only when it has something to say (a label/directive editor, or the how-to on
an EMPTY sheet) — as a standing hint it was the tallest decoration on the
page.

The measurement setup is STICKY per circuit: the scope panes, the picked net
and the live speed are `useStickyState` under `sim:<source>:*`, so a refresh
restores them (volt-ref and current-speed were already sticky, globally). The
post-run default trace seeds only an EMPTY scope for the same reason.

Editor interactions (SimulatorView): right-click opens `.sim-menu` (Copy /
Cut / Rotate / Mirror / Delete / Properties / Paste — Paste lands at the
click's mm, converted through `viewRef`); Ctrl/Cmd-C/X/V copy, cut and paste
the selected symbol (paste under the pointer, next free reference for its
prefix). A pointer-down that hits a part's body suppresses the pin-dot probe
under the same pixels (`downHit`), and `unconnected-*` nets are never added
to the scope — both stop an edit session flooding the plots. The probe
grammar is two-tier: a SINGLE click on a wire or pin only selects its net
(toggle); a DOUBLE click opens a chooser (`.sim-menu`) at the pointer —
Plot voltage / wire or pin current / both — wired overlay `onProbe` →
SimulatorView `probe` state → page `pickNet`/`pickPin` with a
`"v" | "i" | "both"` selector. A power
symbol's dialog edits its NET (the Value field), not the #PWR reference.

Known and accepted, so nobody re-finds them as surprises:

- Two different labels on one net: the browser picks the first in document
  order, kicad-cli may pick the other — that net's overlay readings can go
  dead until the names agree. Label a net once.
- A trace whose WIRE is deleted outright keeps its carried history as a
  frozen band until removed by hand (a severed wire or pin reads 0 instead).
- The overlay's net map (groups, pin membership) comes from the SERVER
  geometry, refreshed by the sketch autosave + re-parse — about a second
  behind the run. After a reconnect, current cannot be routed into the
  segment that ends at the rejoined pin until the map knows the pin is back,
  so charge beads there lag the rest of the sheet by that round trip.
- The raw `alter` box steers the RUN only; a sketch reload rebuilds from the
  document, so raw alters do not survive an edit (dialog edits do — they
  write the document).
- A subckt part's `i(@u1[i])` overlay vector never exists (subcircuits have
  no branch current); it is requested and ignored, by design.

