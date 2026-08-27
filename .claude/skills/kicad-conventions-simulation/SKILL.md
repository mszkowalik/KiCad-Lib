---
name: kicad-conventions-simulation
description: "Authoring simulation models and symbol links: the sigma_ namespace, parameter naming from datasheet symbols (V_BR at test current, never V_RWM), mandatory pin maps and the NC sentinel, per-component Sim.Params, switch drive modes (static / alter / PWL), scenario .control blocks, and the ngspice convergence traps. Use when writing a sim model, linking a symbol, or setting Sim.Params."
---
<!-- platform-skill: conventions-simulation v1 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Simulation model conventions

Simulation models are versioned library objects, like symbols and footprints.
A model is one SPICE `.subckt`. A base symbol carries at most ONE link to a
model, with an explicit pin map. The mirror emits every model into
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

## Authoring a model

- The model name IS the `.subckt` name. They must match, and the name must
  match `^sigma_[a-z0-9_]+$` — SPICE names share one flat global namespace
  with every other library the user loads, so the prefix is our namespace.
- `kind: primitive` is a building block (`sigma_opamp`, `sigma_switch`,
  `sigma_diode`). `kind: part` is a wrapper for a specific device
  (`sigma_bts723gw`, `sigma_74hc21`). A symbol may link to either. A part
  model may instantiate primitives by name — everything is emitted into the
  same `.sp` file, so plain SPICE lookup resolves it.
- Declare every adjustable number in `params:` with a safe default. The
  validator checks component `Sim.Params` keys against this declaration.
- Write the datasheet source of each number in the version comment. Mark
  every number you could NOT verify with the word "placeholder" in the
  comment, and name what confirms it (example: sigma_hss ILIM/TON/status
  polarity await the BTS723GW truth table).

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
  datasheet pinout) reviews the map. The rail heuristic flags a `power_in`
  pin on a signal port. `power_out` on a signal port is deliberately allowed
  (high-side switch outputs).

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

## Convergence rules that cost us hours

- Smooth every comparison with `tanh(k*(…))`. A hard ternary in a B-source
  fails the operating point.
- Sequential feedback (a toggle DFF) works. Combinational feedback (a ring
  oscillator) aborts with "Timestep too small" — do not model one.
- A switch model needs `vt={(VON+VOFF)/2} vh={(VON-VOFF)/2}` — `vt=VON`
  puts the closing threshold above the coil voltage and the relay never
  closes.

## Staleness

The link stamps two fingerprints: the symbol's pin numbers + electrical
types, and the model's PORT LIST. Either moving withholds the Sim fields
from the mirror (with a warning) until someone re-confirms the map —
re-saving the link is the confirmation. Editing a model's params or
internals does not flag links. Adding, removing or reordering ports does.
