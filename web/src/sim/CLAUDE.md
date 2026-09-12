# The simulator (`web/src/sim`)

The simulator overlay, the scope and the live run. The wider design is in
[docs/simulator/design.md](../../../docs/simulator/design.md), the backend rules are in
[docs/reference/spice-runs.md](../../../docs/reference/spice-runs.md) and
[docs/reference/simulation-models.md](../../../docs/reference/simulation-models.md),
and two past audits of this code are in
[docs/reference/simulator-audits.md](../../../docs/reference/simulator-audits.md).

Every parameter the server gives a unit is drawn by `components/SiInput.tsx`,
not a plain box — the part inspector, the run bar's analysis fields and the live
knobs alike. The unit-to-quantity map and the `M`/`MEG` trap are in
`web/CLAUDE.md` under the style system.

Sub-directories carry their own rules: `draw/` (the schematic renderer), `edit/`
(the sketch editor), `field/` (the field solver UI).

## The simulator overlay (`src/sim/`, `pages/Simulator.tsx`)

Layers share ONE coordinate space — millimetres, exactly as the `.kicad_sch`
stores them. Nothing here converts, scales or offsets a coordinate, and nothing
should start: the moment a transform appears, the current dots stop sitting on
the wires.

1. `SchematicView` — the sheet, with wires tinted by node voltage drawn into it
2. `<canvas class="sim-charge">` — the moving charge
3. `<svg class="sim-pick">` — the invisible thick click targets
   (`.sim-hit`, `pointer-events: stroke`) and, in live mode, the steerable
   parts (`.sim-part`)

**The charge is on a canvas on purpose.** A sheet with a few hundred wires
carries thousands of dots, and re-creating that many DOM nodes sixty times a
second is exactly what makes a page like this stutter. The canvas is redrawn
imperatively from a `clock` prop; React never re-renders for an animation
frame.

**Colours come from `color-mix`, not from arithmetic.** `--sim-hot`,
`--sim-cold` and `--sim-zero` are palette variables like everything else, and
a wire's tint is `color-mix(in oklab, var(--sim-hot) N%, var(--sim-zero))`.
That keeps the overlay theme-aware without a hex code in a component.

**`.pill` uppercases its text, and net names are data.** `/lowpass` is not
`/LOWPASS`, and the transform also turns the SI micro prefix into a capital M
(`204 µV` became `204 ΜV`). Any readout showing a net name or a measured value
opts out with `text-transform: none` — `.sim-legend-item` and `.sim-nets .pill`
already do.

**Crop to the drawing, not the page.** A KiCad sheet is mostly empty paper, so
`SchematicView` measures what the sheet actually uses and opens on that.
"Whole sheet" turns it off. Wheel zooms, drag pans, everywhere.

**In live mode you reach for the thing on the drawing.** A switch clicked on
the schematic flips there and then; anything else moves onto the knob panel
with its box focused. That is the point of the mode — a list of SPICE
instance names beside a circuit is not an interactive circuit.

**A flipped contact changes the drawing, not only the netlist.** `alter`
changes the run; the file still says what it said. `SimSheetView`'s `partSwap`
therefore swaps the symbol's `lib_id` AND the Value that goes with it — a
sheet the editor wrote embeds both blade positions, so the graphics are
already there. The altered values live on the page, not inside
`LiveControls`, because the drawing and the panel change the same number.


## The scope: stacked panes on one X axis (`sim/Plots.tsx`, `sim/panes.ts`)

Drawn by **uPlot** — 45 kB, no dependencies, canvas, built for tens of
thousands of points with a synchronised crosshair across several charts. The
hand-drawn SVG scope it replaced could not stack, redrew every path on every
frame, and had no cursor worth the name.

`sim/panes.ts` is the model and holds no React: a pane is one pair of axes, a
trace belongs to exactly one pane, and merge/split are list operations. Three
things are deliberately ours rather than uPlot's:

1. **The legend.** A row of pills carrying the statistics — value at the
   cursor, min…max, mean, rms, peak-to-peak, over the window ON SCREEN. Click
   the name to hide a trace, the × to drop it. Hiding is not removing: reading
   the trace underneath is not the same as being done with this one.
2. **The layout.** Panes are React, so stacking is a list and not a chart's
   internals.
3. **The band.** A live run sends a min-max COLUMN per pixel, so a live trace is
   a band between two hidden series with the mid-line over it.
4. **The X window.** It belongs to `Plots`, not to any one chart. Every pane
   shares one time axis, so a zoom that moved only the pane under the pointer
   would break the single reading that stacking them is for.

Three traps, all measured:

- **A new trace goes in with its own UNIT.** Volts and amps on one pair of axes
  is a chart with two meanings and one scale, and the number that gets squashed
  is always the interesting one. Merge them by hand if that is what you want.
- **The cursor hook fires for a crosshair the PAGE moved too.** Reporting that
  back as a scrub stopped replay the instant it started — play moved the
  cursor, the hook called it a scrub, and a scrub pauses. It reports only while
  the pointer is over that chart.
- **`setScale` fires for OUR OWN writes as loudly as for a user's drag.** The
  page tells every pane the shared window, each pane's hook reports what it was
  given, and without a guard the two hand the same range back and forth for
  ever. `applied` holds the last range a chart actually put on screen and
  `sameRange` compares with a tolerance — comparing floats exactly here is the
  same bug with extra steps. Zoom is off while LIVE: that run owns its own x
  scale and re-sets it on every frame.

**What the scope answers to**, said once in its own bar because none of it is
guessable: drag selects a window (uPlot's own), the wheel zooms about the
pointer, shift-wheel and a trackpad's horizontal scroll pan, Reset zoom appears
only once the view is not the whole run, and Taller doubles the pane height.
Taller also widens the scope card's own `max-height` — a taller plot inside a
card that still caps at 34vh buys pixels the reader has to scroll to reach.

## Voltage colour is a SCALE, not an autorange

Green above ground, red below, nothing at zero — Falstad's convention, and the
one every reader of a simulated schematic already knows. It saturates at a
reference the user picks (±10 V by default), NOT at the run's own extremes.
Autoscaling reads well on one circuit and lies on the next: a board whose
largest excursion is 40 mV of noise gets drawn in full colour, and the same
green then means 5 V on the sheet beside it.

`--sim-pos` / `--sim-neg` are that pair. They are not `--sim-hot` / `--sim-cold`,
which belong to the field solver and mean something else.

## Click a wire, a pin or a part — and get BOTH readings

A net has no current: ngspice reports device branches, never wires. A **wire**
does have one, and so does a **pin**, and both are reconstructed from the
currents around them (`sim/currents.ts`). So:

| Click | Voltage | Current |
|---|---|---|
| a wire | its net | that SEGMENT's own, `iw(<wire id>)` |
| a pin | the net it sits on | that terminal's, `ip(<ref>.<pin>)` |
| a part body | — | its branch, `i(@r1[i])` or `i(v1)` |

The two land in separate panes on one time axis, because volts and amps do not
share a scale. `Merge up` overlays them when that is what you want.

**A pin on a part with more than two legs is the interesting case.** SPICE
reports no per-terminal current for one, so an op-amp output would otherwise be
unplottable. The net around it names it: where a terminal is the only one on
its net whose current is unknown, conservation fixes it exactly. Where two are
unknown it cannot be named, and the pin plots its voltage alone rather than a
number nobody can stand behind — the same rule the charge animation already
followed.

Verified numerically on the worked example at one sample: `v(/ampout)` 0.9805 V,
`i(@r2[i])` −89.136 uA, the wire on that net +89.136 uA, and **U1 pin 5**
−89.136 uA — a reading that is in no rawfile.

These are not SPICE vectors and the names say so: `iw(` is a wire, `ip(` is a
terminal, `i(` is a device. On a finished run they are solved across the whole
of it, once, and only when one is on the scope; over a budget the run is sampled
at a stride and the gaps are straight lines. On a live run there is no history
to solve over, so one is kept: a probe is solved per FRAME into a ring buffer
the width of the scope, then put on the worker's column grid by time.

## Two bars, one drawing, and everything else closed

The simulator page is: a bar that says what you are looking at, the drawing, a
bar that says what will run and what it said, the waveform, and then reference
material behind disclosures.

It was not. There was ONE toolbar carrying the simulation, the sheet, the mode,
the view, the speed, the status, the plot name, the point count and Play — it
grew with the data and wrapped onto three lines — and under the drawing came
four full-width cards in a row: the knobs, "What to run" (a row of big buttons
per scenario, a second row per analysis, a form, Run, a verdict table and a
textarea), the scope, and the net list with the whole SPICE netlist inside it.

Rules that came out of fixing it:

- **A choice among a handful of named things is a menu, not a row of buttons.**
  The scenario and the analysis are `<select>`s in `sim/RunBar.tsx`, on one
  line with Run and the directive they build.
- **A form row appears only for an analysis someone chose.** "From the sheet"
  has no numbers to ask for, and an empty form under every run is furniture.
- **The verdict summary belongs on the run bar; the table belongs under the
  waveform** (`sim/Verdicts.tsx`). One is the answer at a glance, the other is
  the working.
- **Reference goes in `<details>`** (`sim/Disclosure.tsx`): the net list, the
  SPICE netlist, the control block, the off-drawing knobs. Each is something a
  person wants twice a day and never while reading a waveform.
- **Plot metadata sits with the plot.** Play, the point count and the duration
  moved off the top toolbar into the scope card's own head.

## The overlay is matched to the file by POSITION, never by list index

`useSimOverlay` draws the editor's own wires when there is a document, so the
tint lands on the wire the user is looking at rather than on the last save. It
used to pair the document's wires to the file's **by list index**, and drop the
whole overlay when the two lengths disagreed.

They always disagree. A document holds RUNS; a `.kicad_sch` holds one two-point
wire per segment (`sch_write._wires`), so one bend is enough to break the count.
On the worked example it is 26 runs against 36 wires — and "drop the overlay"
means **no tint, no charge dots and no clickable wires at all**, on every
circuit drawn in the browser, in every mode. That is what "nothing is animated
and I cannot select a net" was.

Match by position instead: a segment's two endpoints name exactly one wire in
the file. A segment the file has not caught up with goes untinted on its own
rather than taking the overlay with it.

## A live command sent before the socket opens is QUEUED, not dropped

`LiveSession.send` used to drop a command while the socket was still
connecting — and that is exactly when the page sends. The effect that creates
the session and the effect that tells it which scopes to watch run in the same
commit, microseconds apart and long before the handshake finishes. So a live
run opened with a trace already picked watched nothing at all.

Commands are now queued and flushed on open, after the start frame — the worker
reads that one first and refuses anything before it. It fixes `setSpeed` and
`alter` on the same path.

The other half of the same bug is in `render/sim_worker.py`: `set_scopes`
resolves its vector names against the run's index. A frame is keyed by the
run's own bare names (`/in`) while the rest of the platform speaks the wrapped
form (`v(/in)`), and only `on_init` used to resolve — so a scope set at START
worked and a scope set LATER, which is every trace the user clicks mid-run,
matched nothing and closed no columns. No error, just an empty plot.


## A trace opened late is seeded with its own PAST

The run has been solving since the session opened; only the scope was
forgetting it. The worker keeps a rolling one-window min/max history for every
overlay vector (`HISTORY_COLS` in `sim_worker.py`, a couple of MB at worst),
and a newly opened scope is seeded from it — so clicking a net five seconds in
shows the full window immediately, on the fixed time base, instead of a band
that takes one window-length to arrive.

The parts that keep it honest:

- **`backlog` is per scope and set by the browser** ("I hold no columns for
  this one"): re-sent scope lists — a speed change, a pane merge — keep their
  columns browser-side and must not receive them twice.
- **The speed knob changes the pixel pitch**, so a new `history_span` resets
  the history; old columns are at the wrong timebase.
- **Terms scopes (wire and pin probes) are seeded by interval arithmetic**
  over their components' rings — a positive coefficient maps lo->lo, a
  negative one swaps them. Conservative (a sum's true envelope can be
  narrower), but a column is microseconds of simulated time, the components
  move together at that scale, and an envelope a hair wide beats a current
  pane arriving one window after the voltage beside it. The rings share one
  edge grid, so aligning from the newest end is exact.
- `render/server.py` rebuilds the worker's start frame field by field;
  forgetting to forward a new field there disables a feature silently — that
  is exactly how this one shipped broken the first time.

## Live current names are RAW; a scope keeps WALL pace

Two defects that presented together as "the plot takes seconds to appear, and
two panes drift apart":

- **`LiveState.vectors` holds raw ngspice names** — `@r2[i]`, `v1#branch` —
  never the wrapped `i(...)` a rawfile speaks. `hasCurrent` tested the wrapped
  form, returned false for every device in live mode, and every wire/pin probe
  silently fell back to the 30 Hz reconstruction while the voltage beside it
  ran at full column rate: one pane visibly sparser than the other. The
  worker's `resolve` now tries all three spellings of a current, and the
  browser tests the raw ones.
- **A scope closed at most one column per solver point.** At the default speed
  the point rate (~110/s) is below the 150 columns/s a 4-second window needs,
  so every plot crept slower than wall clock — the band "took seconds to start
  showing". The worker now closes EVERY edge a data point crossed; when the
  solver's step is larger than a pixel the extra columns repeat the last
  value, which is what a scope showing a signal slower than its beam has
  always drawn. Measured 153/153/153 columns per second — identical to the frame —
  across a voltage, a wire probe and a source pin after the fix.

## Send the worker the SUM, not the answer

A wire's current and a terminal's are not vectors — they are reconstructed from
the device currents around them. Reconstructing one in the browser means doing
it once per FRAME, thirty times a second, and the result is a staircase drawn
next to a smooth voltage on the very same net: the worker closes a column every
few microseconds of simulated time, the browser can only supply a value every
thirty milliseconds of wall clock.

The reconstruction is LINEAR in the terminal currents, so it can be sent instead
of computed. `probeTerms` reads the coefficients off by solving once per device
with a reader that says "this one is 1 A, everything else is 0" — no algebra to
get wrong, and it is the same solver either way. A live scope then carries
`terms: [{vec, coeff}]` and the worker closes its columns like any other.

Two rules that follow:

- **The basis must keep the run's NULLS.** A device the run reports no branch
  current for is what makes a terminal the unknown one; answering 0 for it
  instead solves a different circuit. `probeTerms` takes a `hasCurrent`
  predicate for exactly that, and it comes from the run — `LiveState.vectors`
  live, `plot.byName` for a finished one — never from a guess about naming.
- **`liveState` changes thirty times a second and its vector LIST does not.**
  Depend on `liveState.vectors`, or the scope list is re-sent every frame.

Measured on the worked example: the terms are exact — `iw(w10)` is `-i(r2)`,
U1 pin 5 is `+i(r2)`, and the sum matches the direct solve to 0.00e+0 A across
the whole run. Live, a summed scope closed 946 columns against the voltage
scope's 946 over the same ten seconds.

The frame-rate reconstruction is still there, as a fallback for a probe that
cannot be expressed at all — a net with two unknown terminals, or a loop. That
one is a staircase by nature.

## A live scope's columns are addressed by POSITION — carry them by NAME

`LiveState.columns[i]` belongs to `config.scopes[i]`, so changing the scope list
moves every trace's history one slot along. `setScopes` used to answer that by
clearing the lot, which meant **removing one trace blanked every other trace on
the page**: the whole scope went back to zero columns and the plots had nothing
left to draw.

It now carries each surviving trace's columns across by vec name; only a new
trace starts empty. Frames already in flight were closed against the old list,
so for about one round trip a column can land in the wrong slot — one or two out
of six hundred, against a history that would otherwise be thrown away.

The other half was in the page: live `plotData` returned **null** when no
columns had arrived, and a null there destroys every chart and rebuilds it when
data returns. The live grid is now always the full width, padded with NaN, so a
moment with no columns is an empty scope rather than no scope.

## The charge-dot speed is a knob, and it says nothing about the simulation

The dots on a wire move at a speed proportional to that wire's share of the
run's peak current. How fast the whole picture runs is a viewing preference —
too fast to follow on one circuit is too slow to see on another — so it is a
slider in the top bar, remembered for the session.

Two things it is NOT: it does not change the simulation, and it is not the live
run's `speed` (simulated seconds per second of wall clock), which lives on the
run bar in live mode. Keep them apart in any wording — a user who confuses them
will think a slower picture is a more accurate one.

The mapping is logarithmic with 1x in the middle, because the useful range is a
factor of sixty and a linear slider spends four fifths of its travel above "too
fast to follow". Zero stops the dots where they are; the tint still says what
every net is worth, which is the right picture for a screenshot.

## A live run learns its own scale

`voltageRange` and `currentPeak` come from a finished run's extremes, which a
live run does not have — it has the latest frame. Left at their defaults a 5 V
circuit tinted against ±24 V and every dot ran at the wrong speed.

The live scale is learned from the frames and only ever GROWS. A peak that
tracked the instant would change the tint and the dot speed thirty times a
second, which reads as noise rather than as current. The effect returns the
same object when nothing grew, or it would re-render the page every frame for
no change.

## A live run has a scope too (now `sim/Plots.tsx`)

Live mode drew a circuit and no waveform, and clicking a net appeared to do
nothing — because the scope card was rendered only for a FINISHED run, so
`pickNet` was adding traces to something that was not on the page.

The whole path existed except the browser end. The worker has accepted a scope
list since it was written, closes one min/max COLUMN per pixel of scope, and
ships the closed columns in every frame; `LiveState.columns` has always carried
them. The page passed `scopes: []` and never called anything to change it.

- `LiveSession.setScopes` is new. Changing what a scope watches must NOT go
  through the session config — rebuilding that restarts the simulation, so a
  new trace would throw the run away.
- Columns already closed belong to the OLD scope list and are dropped with it.
  Keeping them would draw one trace's history under another's name.
- A live trace is a **band** between a column's min and max, not a line. That
  is honest: one column of a 1 kHz square sampled over 10 ms really does span
  both rails.
- `sim_s_per_px` is tied to the speed, so a scope shows the same few seconds of
  WALL clock at every setting — which is what a person means by "the last few
  seconds".

## Click the part, not a table (`sim/PartPopup.tsx`)

A part is set in a dialog that opens ON the part. What this replaced listed
every steerable part in the design under the drawing — forty text boxes in a
grid, in an order nobody chose, for a circuit three inches above them. Falstad
has always done it the other way, and so has every schematic editor: click the
component, get a dialog about that component.

The dialog is deliberately two halves, and only the second is about simulation:

1. **What the part is** — reference, value, the library part behind it, and
   whatever the placement carries: footprint, datasheet, description, the
   manufacturer's number, the model it is simulated as. This half is the reason
   the component is a separate file: the same dialog is meant to open on a
   project's schematic tab and answer "what IS this?" out of the catalogue.
2. **What it can be set to** — `ComponentInspector`, unchanged.

Rules that follow from how it works:

- **Every part gets a hit target, in every mode**, and the target is invisible
  until hovered. A hotspot that appeared only during a live run would make the
  same part clickable and then not; 87 accent boxes on a real sheet would be a
  diagram of the hit targets rather than of the circuit.
- **A sheet KiCad wrote is never rewritten**, so its dialog is `readOnly` and
  steers the RUN through `onLive`. The dialog says so rather than looking
  broken. A sketch's dialog writes to the document like the editor always did.
- **The dialog is dragged by its title bar**, because the part it describes is
  underneath it.
- **It stops its own pointer events.** The drawing under it listens for clicks
  on wires and parts, and without that every click inside the dialog would also
  pick whatever is behind it.
- The panel under the drawing kept only what a drawing CANNOT show: a source
  living in a SPICE text block, and the parts on OTHER sheets of the design —
  those by a search box, not a grid.

## An upload runs itself once, a snapshot does not

Every measurement in the simulator reads from a run: the scope, the readout,
the value beside a probed net. So a source that has not been run shows no
plot, no scope card and no reading — and clicking a net does nothing VISIBLE,
because `pickNet` adds a trace to a scope that is not rendered. That reads as
a broken page, not as "press Run", and it is exactly what the example did
before this.

`Simulator.tsx` therefore runs an **upload** source once when its geometry
arrives — a sketch, the worked example, a dropped sheet: all small, and all
opened in order to be simulated. A **snapshot** board is left alone, because
those runs are long and a reviewer picks the scenario before spending one.
The guard is a ref holding the upload id, not the effect's dependency list:
`doRun` is rebuilt whenever the chosen scenario changes.

## What to run, and what it said (now `sim/RunBar.tsx` + `sim/Verdicts.tsx`)

A harness carries its scenario as SPICE text beside the circuit. Left as text
it is a wall the user is asked to take on faith before pressing Run, so the
panel turns it into three things:

- **the runs it offers** — every `.control` block, named by its own first
  `echo`, with how many PASS/FAIL lines it prints. "The sheet's own" is the
  default and leaves the harness alone.
- **the analysis** — Transient / AC / DC / Operating point as a form that
  builds the directive, or "From the sheet" to use the one it carries. Same
  `params.ts` machinery the component inspector uses.
- **the verdicts** — `scenario.ts` reads the PASS/FAIL table out of the run's
  own log. That convention is already in every harness in `EVSE_20_CTRL`;
  nothing new is asked of anyone.

**A verdict run has no waveform, and that is not a failure.** It runs its
analysis inside the `.control` block, so ngspice writes no rawfile. The payload
comes back with zero plots and a log — render the verdicts, not an error.

**An unlabelled net cannot be probed from a `.control` block.** KiCad names it
`Net-(R1-Pad2)`, which SPICE reads as an expression with a minus in it. Put a
label on any net a check measures.

## Editing and simulating are ONE view (`sim/SimulatorView.tsx`)

There is no separate editor screen and there must not be one again. The
schematic, its readings and its drawing tools are the same surface: `Edit` on
the toolbar reveals the tools, and the overlay stays underneath them. A user
asked for this in exactly those words — "all in one place" — after having to
leave the simulation to change a resistor.

`sim/edit/doc.ts` holds the document and every derivation from it
(`docToDrawing`, `autoJunctions`, `symbolPins`, `orthoRun`). The document is
the ONLY state that is mutated — everything drawn comes from `docToDrawing`,
so there is never a second copy of the circuit to keep in step.

Three things hold it together:

- **A document draws from itself, anything else from the geometry.** A dragged
  part must follow the pointer, not a round trip. The overlay is matched to
  the document's wires BY POSITION — which holds because `sch_write` emits one
  `(wire)` per document wire in order, and because a drawn run is stored as
  one wire PER SEGMENT, the shape KiCad uses. When the counts disagree (a save
  has not landed), the overlay is dropped rather than drawn on the wrong wire.
- **The file follows the drawing without being asked.** An edit saves 700 ms
  after the last change, in place (`POST /api/sim/sketch?id=…`), then bumps a
  revision so the geometry and the netlist are read again. A new source per
  keystroke would fill the disk and move the address bar under the user.
- **`useSimOverlay` is the overlay, once.** Tint, charge canvas, click targets
  and live part hotspots. Both the editable and the read-only paths use it, so
  they cannot disagree about what a wire is worth.

- **Junctions are derived, never placed.** `autoJunctions` puts a dot where
  three wire ends meet or a wire end lands inside another wire. A dot a user
  could place by hand would be a short nobody can see.
- **The keyboard is KiCad's**: `w` wire, `r` rotate, `m` mirror, `l` label,
  `t` directive, Delete, Escape, Ctrl+Z. The people using this already know
  that keyboard.
- **A part's Value IS its SPICE value.** `10k`, `DC 5`, `PULSE(0 5 0 1u 1u 1m
  2m)`. Nothing translates it, and nothing should start — but nothing asks the
  user to type it either. `edit/ComponentInspector.tsx` shows a form per shape
  a part can take and a row per number, and fills the template in
  (`sch_lib.PARAM_FORMS` declares them, `edit/params.ts` builds and parses).
  A raw form is always the last option, because a value the fields cannot
  express is still a value.
- **A row that a running transient cannot follow says so.** ngspice accepts
  `alter` on a waveform and silently keeps the old script, and a `.model`
  parameter cannot be altered at all — those rows are marked "needs a re-run",
  which the auto-save then does. A knob that does nothing is worse than no
  knob.
- **The knob panel lists what the DRAWING cannot.** A harness source in a
  SPICE text block has no symbol to click. A part that has one is set in its
  inspector; listing it in both is two boxes for one number, and the second
  goes stale the moment the first is used.
- **Saving is `POST /api/sim/sketch`**, which writes a real `.kicad_sch` and
  returns an upload id — the source kind the simulator already runs. A circuit
  drawn here goes through exactly the same pipeline as one drawn in KiCad.
  Pass `?id=` to rewrite one in place; uploads are not cached, so the next
  netlist reads the file that is there now.
- **It opens what it drew, not what KiCad wrote.** A KiCad file carries tokens
  the document does not model, and writing it back would drop them silently.
  The Edit button appears only when `/upload/{id}/sketch` answers.

**An AC run is complex.** The payload stores real/imaginary in pairs and
`decodeSimPayload` folds them to magnitude — the thing a scope shows and the
thing that can colour a wire. A transient is real and passes straight through.

