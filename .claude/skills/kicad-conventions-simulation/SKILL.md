---
name: kicad-conventions-simulation
description: "Authoring simulation models and symbol links: the sigma_ namespace, parameter naming from datasheet symbols (V_BR at test current, never V_RWM), mandatory pin maps and the NC sentinel, per-component Sim.Params, switch drive modes (static / alter / PWL), scenario .control blocks, and the ngspice convergence traps. Use when writing a sim model, linking a symbol, or setting Sim.Params."
---
<!-- platform-skill: conventions-simulation v5 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Simulation model conventions

Simulation models are versioned library objects, like symbols and footprints.
A model is one SPICE `.subckt`. A base symbol carries at most ONE link to a
model.

A link has two modes, and the choice is not a preference:

| Mode | You author | The platform derives |
|---|---|---|
| **composed** | which block sits on which pin | the `.subckt`, its ports, and the pin map |
| **model** | the `.subckt` text and the pin map | nothing |

**Compose by default.** Type a `.subckt` only for behaviour no existing block
gives you. The mirror emits every model into
`Symbols/7Sigma_sim.sp` and turns each link into `Sim.Device` / `Sim.Name` /
`Sim.Library` / `Sim.Pins` rows on every component of that symbol. Tools:
`list_sim_models`, `get_sim_model`, `propose_sim_model_edit`,
`set_symbol_sim_link`. Every write publishes immediately.

## Only our models

Reference only models in this library. Never point `Sim.Library` at a KiCad
install file. Copying a topology from a KiCad model into a `sigma_` model is
fine. Referencing their file is not — KiCad 10 ships models that point at
`${KICAD9_SYMBOL_DIR}`, which is already broken. Our path
(`${SEVENSIGMA_DIR}/…`, rewritten to the PCM install path at serve time) is
under our control.

## Ask before you model — and always fill the params

Simulation is not automatic and must not be added silently.

1. **Creating a component, creating a symbol, or editing a symbol, where the
   base symbol has NO sim link** — ask the user whether to add simulation
   capability, and say in one line what a model would cover. Do not add one
   unasked, and do not skip the question because the part looks boring.
2. **The base symbol ALREADY has a link** — do not ask again. Instead do the
   per-component half of the job: read the datasheet and write `Sim.Params`
   for this part. A component with no row silently runs on the model's
   defaults, which belong to whichever part the model was authored against.
   That is how a 3 V Schottky ends up simulated as a 0.9 V silicon diode.
3. **Editing a symbol's pins** — a hand-written link goes stale and the Sim
   fields stop being emitted. Re-save the link to confirm the map still means
   what its author intended. Do not "fix" staleness by deleting the link. A
   composed link is rebuilt against the new pins instead, and only fails when
   a pin the design uses has gone.

## Authoring a model

- The model name IS the `.subckt` name. They must match, and the name must
  match `^sigma_[a-z0-9_]+$` — SPICE names share one flat global namespace
  with every other library the user loads, so the prefix is our namespace.
- `kind: primitive` is a building block (`sigma_opamp`, `sigma_switch`,
  `sigma_diode`). `kind: part` is a hand-written model for a specific device
  (`sigma_hss`, `sigma_amc1311`). `kind: composed` is GENERATED and is never
  written by hand — see the next section. A symbol may link to a primitive or
  a part alike: a diode, a switch or a 5-pin op-amp IS the primitive. Any
  model may instantiate another by name, because everything is emitted into
  the same `.sp` file and plain SPICE lookup resolves it.
- Declare every adjustable number in `params:` with a safe default. The
  validator checks component `Sim.Params` keys against this declaration.
- Write the datasheet source of each number in the version comment. Mark
  every number you could NOT verify with the word "placeholder" in the
  comment, and name what confirms it (example: sigma_hss ILIM/TON/status
  polarity await the BTS723GW truth table).

## Compose the wrapper, do not type it

KiCad netlists one element per reference designator, so the thing `Sim.Name`
points at is always package-level: a 74HC21 cannot be two AND gates in a
schematic, it has to be one subcircuit carrying all twelve pins. That wrapper
is GENERATED. You give the blocks and say which symbol pin each block port
sits on, and the platform writes the `.subckt`, names it
`sigma_sym_<symbol>`, and derives the pin map.

Do this on the symbol page, in the Simulation card, Composed mode. Thirteen
hand-written wrappers were retired this way, two of which had been sitting in
the library linked to nothing at all.

**Compose when the part is wiring around existing blocks.** Two gates in one
package, four legs of a TVS array, a MOSFET die behind five package pins, a
flip-flop with its unused preset tied high. **Write a model by hand only for
new behaviour** — a behavioural source, a `.model` card, an equation.

Rules that follow from how it works:

- **One wrapper port per unique symbol pin, never fewer.** It is tempting to
  put a power MOSFET's three source pins on one port and drop the ties. It is
  wrong: the schematic may put those pins on three different nets, and one
  port carries one node. Join pins with a **tie** — a real resistor, package
  copper being 0.2 mΩ or so — which is also the only form that lets you
  see the tie current.
- **Every pin is answered.** Wire it, or tick it as not modelled. A pin left
  blank blocks the save. This is the composed form of the `-` sentinel, and
  it exists so that a forgotten pin cannot pass as a deliberate one.
- **Read the coverage panel before you save, not the block list.** The block
  list says where a port sits; coverage says what each PIN feeds. A crossed
  rail is visible in one and not the other.
- **Read the generated netlist before you publish.** It is shown under the
  editor. Generation nobody reads is generation nobody checks.
- **Parameters are shared by default**, because both halves of a dual gate
  are one die and take one number. Use `per block` when they genuinely differ
  (a dual TVS with different breakdown per channel). Use `fixed value` to
  bury a number nobody should tune.
- **Set a wrapper default that differs from the block's.** The retired
  `sigma_tvs_bi` wrapper declared `VBR=26.7` while the `sigma_tvs_leg` block
  it wrapped defaults to 13.3, and a
  component with no `Sim.Params` row runs on whichever the wrapper states.
  Getting this wrong halves a clamping voltage silently.
- **Never hand-edit a generated model.** The model page refuses, and the next
  regeneration would overwrite it anyway. Change the block design instead.
- **A block model's new version rebuilds every wrapper that uses it.** Where a
  hand-written wrapper goes stale and waits for a person, a composition is
  simply rebuilt — and where it cannot be, the failure names the port that
  lost its node.

## Parameter naming — datasheet symbols, datasheet conditions

Use the symbol the datasheet uses, at the condition the datasheet states:

- Zener / TVS: `BV` is V_BR at the stated test current I_T — NEVER the
  headline V_RWM. SM712: 13.3 V / 7.5 V, not 12 V / −7 V. Getting this wrong
  makes every clamping sim optimistic.
- Opamps: `GAIN` (V/V, from A_OL), `POLE` (Hz, = GBW / GAIN), `VOFF`, `ROUT`.
- Logic: `TPD` (propagation delay), `VDD`, `ROUT` (the adc/dac bridges have
  no output impedance — a series ROUT is mandatory or every load sim lies).
- Open-drain comparators: `RON`, `VOFF`, `THYST`. Output pulls LOW when
  in− > in+ (the LM393 convention).
- Diodes / LEDs: `IS`, `N`, `RS`, `CJ`; LEDs add the per-colour `VF`.

## Pin maps

**In composed mode there is no pin map to author.** The port list is one port
per pin by construction, so `Sim.Pins` is derived and cannot be mis-written.
The whole of this section is about hand-written models.

- `Sim.Pins` is MANDATORY. Without it KiCad falls back to raw pin order,
  counts hidden stacked pins, and mis-wires silently.
- The map covers every unique pin NUMBER exactly once. Hidden stacked
  duplicates share the visible pin's number — one entry covers them, KiCad
  nets them together.
- Map a pin the model does not represent to the sentinel `-` (NC pins,
  thermal pads that the datasheet says are not ground, status pins you chose
  not to model). Every declared port must be claimed by exactly one pin.
- The validator catches structure only. It CANNOT catch a swap — swapping
  in+ and in− is still a valid permutation. A human (or you, against the
  datasheet pinout) reviews the map. The one semantic check is the rail
  heuristic: a rail-shaped port (`vcc`, `vdd1`, `gnd2`, `vinp`, `vs` — a rail
  stem plus an optional channel number or polarity letter) claimed by a pin
  that is not a power pin. It does NOT flag a power pin on a port with a
  generic name: an LDO's `in`, a regulator's `out` and a flip-flop's `pren`
  tied high are all correct, and no name-based rule can tell them from an
  op-amp's `in+`.

## Sim.Params on components

Topology lives in the model. The part's own numbers live on the COMPONENT as
a `Sim.Params` property (`KEY=value KEY=value`). The link-derived rows are
prepended, so a component's own row always wins. Every key must be declared
by the linked model, or `cmp.sim_params` fails. Components without the row
run on model defaults — acceptable for logic, wrong for a Schottky riding a
0.9 V silicon default. Fill params from the datasheet when you touch a part.

## Switches and buttons

One primitive, three drive modes — pick per scenario, not per model:

1. Static: set `STATE` (or the per-pole `R1..R8` on DIP models) in
   `Sim.Params`.
2. Between runs: `alter @r.<path>.rs<n>[resistance]=50m` in a `.control`
   block — hierarchical alter works on instances inside subcircuits.
3. Mid-run: drive a `.global` control node from a PWL source into
   `sigma_switch_vc`. This also works for DIP switches.

## Scenario blocks in the schematic

- A text item holds the `.control` block. KiCad text needs literal `\n`
  escapes and escaped quotes, or the schematic will not load.
- Ground must be the power symbol whose Value is literally `0`. ngspice
  aliases GND to node 0 by itself, so an explicit `VGND GND 0` source is a
  fatal short.
- KiCad nets are named with a leading slash: probe `v(/sig)`, not `v(sig)`.
- The pulse-source width parameter is `tw` in KiCad, not `pw`. A `pw` is
  silently dropped.

## Every number is read, never inferred

- Take each figure from the part's own datasheet. A sibling variant's row is
  not evidence: the table that says "peak" for one suffix says "continuous"
  for another, and a dual-channel row is not a single-channel rating.
- **Show the arithmetic in the version comment** when a parameter is derived
  rather than quoted. A later reader must be able to redo it.
- Anything you could not confirm carries the word **placeholder** in the
  comment AND names what would confirm it. A default nobody has checked is
  fine; a default nobody knows is unchecked is not.
- State the condition with the value. `TON=55u` is meaningless without
  "max, from the BTS723GW switching table".

## Say what the model does NOT do

The header comment must name every behaviour left out, and why. This is not
politeness — it is the only thing standing between a reader and a confident
wrong answer. Write it for the person who will trust the plot.

Rank what you leave out by how quietly it lies:

| Left out | Consequence |
|---|---|
| A series element deleted | The net silently opens. **Never acceptable** — model it. |
| A current limit | A fault sim reports a current the part cannot deliver. |
| A protection or enable pin | A shutdown the design relies on does nothing. |
| Frequency-dependent behaviour | An EMI or ripple result is meaningless. |
| Self-heating, tolerance, ageing | Usually fine; say so anyway. |

## Prefer a loud failure to a quiet wrong answer

- **Never exclude a two-pin part that sits in series with a net.** Fuses,
  polyfuses, ferrite beads and NTCs are modelled (`sigma_fuse`,
  `sigma_ferrite`, `sigma_ntc`) precisely because excluding one opens a live
  rail with no error at all. A missing model fails loudly; a missing
  connection does not.
- **Do not model a pin whose polarity you cannot confirm.** Guessing an
  enable's sense inverts a shutdown silently. Map it to `-`, and say in the
  header that the pin is not modelled and what would settle it.
- **Do not model current limiting by feeding output current back into the
  source.** That is combinational feedback and the transient aborts. Leave
  the limit out and say so.

## exclude_from_sim is DERIVED — never hand-edit it

The mirror sets `exclude_from_sim` on every generated symbol from the link
set. A symbol is left simulatable when it has a link, or when its reference
prefix is `R`, `C`, `L` or `#PWR` — SPICE builds those from the Value field
with no model, and power symbols are net names, not devices. Everything else
with no link is excluded, because it would otherwise emit `U47 __U47` and
stop the run.

Consequences you must know:

- **Setting the flag by hand in a schematic does not last.** `Update Symbols
  from Library` restores what the library says. Fix it by linking a model.
- A **stale** link still counts as linked, on purpose: its Sim fields are
  withheld, so the netlist fails loudly instead of quietly dropping a part
  that should have been there.

## Comment character: `;`, never `$`

KiCad runs its embedded ngspice with `ngbehavior=ps lt a`. In that mode `$`
is NOT a comment: numparam feeds the text to the expression parser and the
model fails to load with `Undefined parameter [t]` from something as
innocent as `$ V_IN(T+) 1.2..2.2 V`. `;` parses in every mode. Own-line `*`
comments are always safe.

Test a new model BOTH ways before publishing. Put `set ngbehavior=pslta` in
`<dir>/scripts/spinit` and run `SPICE_LIB_DIR=<dir> ngspice -b model.cir` —
that reproduces KiCad's parser without opening KiCad.

## Power modules (DC/DC bricks)

An ideal voltage source is the wrong model for a brick and hides the failure
these parts actually cause. Decide first which kind it is; the datasheet says
so in words.

**Unregulated** (YLPTEC `A_S-2W`, `A_S-1WR3`, `B_S-1WR3` — "isolated
unregulated output"). The output is a winding and a rectifier, so it RISES at
light load and follows the input ratio. Model it as an open-circuit voltage
behind a series resistance, both derived from the load-regulation row:

```
ROUT = VNOM * REGL / (0.9 * IOMAX)      VOC = VNOM * (1 + REGL / 0.9)
```

`REGL` is the 10%-to-100% load regulation, `VNOM` the rated output at full
load, `IOMAX` the rated current PER RAIL. That reproduces the datasheet at
both ends by construction. `KLINE` is the line-regulation slope — fractional
output change per fractional input change — and for an unregulated brick it
is near 1, because the output is the input times a turns ratio.

**Below the stated minimum load the output keeps climbing.** That is real,
and simulating it is the main reason to model the part at all.

**Regulated** (MEAN WELL `NID65`). A stiff source with a small series
resistance from the load-regulation figure, plus the input range as a soft
cutoff.

For every brick, model as well:

- **Input current from the output power**, not a constant:
  `Iin = Pout/EFF/Vin + INL`, with `INL` the no-load input current. Check it
  against the datasheet's own full-load input current row — if the two do not
  agree, one of your numbers is wrong.
- **Isolation** as a large resistance and the stated isolation capacitance
  between input return and output return. Without a path the matrix is
  singular.
- A **soft** input cutoff (`tanh`), so the operating point has no step.

Verify against the datasheet at three points before publishing: full load,
10% load, and open circuit — plus the input current at full load and no load.
Put those measured numbers in the version comment.

## Draw the stimulus. Do not hide it in a text block.

**Every instantiation of a `sigma_` model on a harness is a PLACED SYMBOL.**
Not an `X` line in a `.control` or stimulus text block. This is a rule, not a
preference, and it was set on 2026-08-30 after a pilot harness was found
building a whole vehicle out of hidden text while the component for it already
existed and sat unused.

A hidden `X` line reaches into the design by hierarchical SPICE name —
`XRTD /TEMP/AT1 0 sigma_rtd_ct` — which works in the netlist and is invisible
on the drawing. Nobody can see what is connected where without reading
ngspice, and a reviewer cannot tell a deliberate connection from a typo.

| What it is | Where it goes |
|---|---|
| Anything that instantiates a `sigma_` model | a symbol on the sheet |
| A device the board would really connect to — a vehicle, a sensor, a coil, a field contact | a **Simulation category** part |
| A device that lives on ANOTHER sheet of the same board, rebuilt because that sheet will not converge | the **real catalogue part**, not a stand-in |
| A plain SPICE source — `V`, `I`, a PWL, a PULSE | the stimulus text block |
| A plain passive that is bench wiring, not a modelled device | the stimulus text block |

A source stays text because it is excitation, not a model. It still has to be
legible: give the node a NAME, put a label of that name on the sheet, and the
reader can follow it.

### How a harness reaches a design net

A wire cannot reach a net inside a child sheet. Add a **sheet pin** to the
harness's sheet symbol for every design net the stimulus touches, then join
sheet pin and part pin with matching **local labels**. Local is right: they
connect within the harness root and cannot leak into the design.

Two consequences that bite:

- **A net pulled out to the root is RENAMED.** `/TEMP/AT1` becomes `/AT1`.
  Every probe in the checks has to follow.
- **A root label netlists with a LEADING SLASH.** A source in the text block
  must write `/NTEMP`, not `NTEMP`, or it drives a second floating node and
  the operating point will not solve. Power nets are the exception: `3V3` is
  global and carries no slash.

### When the net is not exposed

Some nets have no hierarchical pin — the poles of a disable bank, an internal
`Net-_xx_`. Do not add pins to the board's schematic to serve a harness.
Two honest ways out, in order:

1. **Give the model a control node.** `sigma_dip8` gained global `SIM_DIP1..8`
   so its poles can be driven without new ports and without touching the
   board. A `.global` inside a `.subckt` parses and works.
2. **Leave it in the text block and SAY SO on the sheet.** A named exception a
   reader can find beats a silent one.

### The control pin is the point

A model whose state is a parse-time PARAMETER forces one simulation run per
value, and a GUI plot keeps only the last. A model whose state arrives on a
CONTROL NODE walks every value inside one transient. That is why
`sigma_rtd_ct`, `sigma_ev_vehicle_st` and `SIM_SWITCH` exist beside the
parameter versions. Prefer the control-node part in a harness; the parameter
part is for a harness that only ever wants one value.

## Convergence rules that cost us hours

- Smooth every comparison with `tanh(k*(…))`. A hard ternary in a B-source
  fails the operating point.
- Sequential feedback (a toggle DFF) works. Combinational feedback (a ring
  oscillator) aborts with "Timestep too small" — do not model one.
- A switch model needs `vt={(VON+VOFF)/2} vh={(VON-VOFF)/2}` — `vt=VON`
  puts the closing threshold above the coil voltage and the relay never
  closes.

## Staleness

**A hand-written link stamps two fingerprints**: the symbol's pin numbers
plus electrical types, and the model's PORT LIST. Either moving withholds the
Sim fields from the mirror (with a warning) until someone re-confirms the map
— re-saving the link is the confirmation. Editing a model's params or
internals does not flag links. Adding, removing or reordering ports does.

**A composed link stamps nothing.** It is unusable only when the block design
no longer builds against today's blocks, or when the published wrapper is not
what the design builds. Both self-heal: fix the block model and the wrapper
rebuilds itself. That is the point of composing — a fingerprint can only say
"ports changed", where this names the port that lost its node.
