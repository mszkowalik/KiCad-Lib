---
status: "accepted"
date: 2026-08-29
decision-makers: Mateusz Kowalik
consulted: —
informed: —
---

# Generate a package simulation wrapper from blocks, instead of writing it

## Context and Problem Statement

KiCad netlists one SPICE element per reference designator. A multi-unit symbol
is one element carrying every pin, so the subcircuit that `Sim.Name` points at
is always package-level: a 74HC21 cannot be two AND gates in a schematic, it
has to be one `.subckt` with all twelve pins.

Those package wrappers were written by hand, one per part. Nine of the
sixty-five models in the library held no behaviour at all — two instance lines
and a parameter pass-through. Two of them, `sigma_74hc21` and `sigma_buf2`,
were written, linked to nothing, and never noticed.

Each hand-written wrapper also carried a hand-typed pin map. `Sim.Pins` is
mandatory and the platform emits whatever the map says, so a swapped pair
reaches a netlist unchallenged. `simmodel.validate_pin_map` states in its own
docstring that it cannot catch this: swapping two entries is a valid
permutation. The library relied on a person reading the map.

Technical detail: [api/CLAUDE.md](../../api/CLAUDE.md), "Composed models".

## Decision Drivers

* A wrapper that holds no behaviour is wiring, and wiring should not be typed.
* A hand-written wrapper has no owner, so it outlives whatever needed it.
* The pin map is the library's one un-checkable artifact, and it is the one
  that mis-wires silently.
* Any change must not move a component's `Sim.Params`, or a rework becomes a
  data migration across every part.

## Considered Options

* **Generate the wrapper from a block design**, stored on the symbol's link.
* **Keep hand-written wrappers**, and add a lint that flags an unused one.
* **Let a symbol link several models, one per unit**, with no wrapper at all.

## Decision Outcome

Chosen option: **generate the wrapper from a block design**, because it
removes the class of defect rather than reporting it. The author says which
block sits on which pin; the platform writes the `.subckt`, names it
`sigma_sym_<symbol>`, and derives the pin map.

The third option is not available. KiCad emits one element per reference
designator, so per-unit models cannot be expressed — this constraint is what
forces a package-level wrapper to exist at all.

The generated text is published as an ordinary `SimModel` row with
`kind="composed"`. Nothing downstream changed: the mirror emits it like any
model, `generator.sim_props` points `Sim.Name` at it, the KiCad HTTP library
and the PCM package are untouched.

**One wrapper port per unique symbol pin, never fewer.** Aliasing a power
MOSFET's three source pins onto one port and dropping the ties is wrong: the
schematic may put those pins on three different nets, and one port carries one
node. Pins are joined by real resistors inside the subcircuit, as
`sigma_nmos_pwr8` already did by hand.

### Consequences

* Good, because the port list is `p1 p2 p4 …` by construction, so `Sim.Pins`
  is derived. The swap the validator admits it cannot catch stops being
  possible in composed mode.
* Good, because a generated wrapper is owned by its link and deleted with it.
  It cannot become another `sigma_74hc21`.
* Good, because a block model's new version rebuilds every wrapper that uses
  it. A hand-written wrapper goes stale and waits for a person; where a
  composition cannot be rebuilt, the failure names the port that lost its node.
* Good, because staleness is computed rather than stamped, so it self-heals
  when the block model is fixed.
* Bad, because two symbols with identical pinouts get one wrapper each rather
  than sharing one. `AON7264E` and `CSD17577Q3A` shared `sigma_nmos_pwr9` and
  now hold a wrapper apiece. Per-symbol is what makes `Sim.Pins` derivable,
  and the two pinouts matched by accident.
* Bad, because generated text must be byte-stable, and that is easy to get
  wrong. `parsed` and `composition` are JSONB, and Postgres reorders an
  object's keys, so anything emitted in dict order differs from itself across a
  round trip. This was found twice — once in the parameter list, once in a
  comment — and the second cost a live regression. Any list `compose()` derives
  from a dict is now ordered explicitly.
* Neutral, because hand-written models remain for anything with behaviour of
  its own: a behavioural source, a `.model` card, an equation. The mode switch
  is permanent, not a migration aid.

### Confirmation

* `sym.sim_link` validates every composed link against the symbol's current
  pins, and the mirror withholds `Sim.*` from any link that does not build.
* `cli/simrecompose.py apply --verify` diffs the declared interface before and
  after a conversion. The production rework reported 0 lost parameters and 0
  moved defaults across 11 links, so no component's `Sim.Params` moved.
* Checked under ngspice against the deployed library, composed wrapper beside
  the hand-written one on the same stimulus: `v(y1) = v(o1) = 3.283582 V`,
  `v(y2) = v(o2) = 0 V`.
* Two consecutive mirror writes must emit no sim-link warning. A wrapper that
  is behind its own block design shows up here.

## Pros and Cons of the Options

### Generate the wrapper from a block design

* Good, because it deletes the failure mode instead of reporting it.
* Good, because the reviewer reads a pin-coverage panel and a generated
  netlist, rather than a table of pin-to-port pairs.
* Bad, because it adds a generator whose output must be deterministic.
* Bad, because a person can no longer hand-tune a package wrapper. Changing the
  block design is the only route, and a hand edit is overwritten.

### Keep hand-written wrappers plus an unused-model lint

* Good, because it is a much smaller change.
* Neutral, because it would have caught `sigma_74hc21` and `sigma_buf2`.
* Bad, because it does nothing about the pin map, which is the defect that
  actually mis-wires a circuit.
* Bad, because it leaves thirteen wrappers to maintain by hand.

### One model per symbol unit, no wrapper

* Good, because it would need no generator.
* Bad, because KiCad cannot express it. Units of one symbol share a reference
  designator and netlist as a single element.

## More Information

* [api/CLAUDE.md](../../api/CLAUDE.md) — "Composed models", the implementation
  facts and the traps.
* `conventions-simulation` skill, v3 — the authoring convention: compose by
  default, write a `.subckt` only for behaviour no block gives you.
* `api/app/services/simcompose.py` — the generator, and the reasoning for the
  one-port-per-pin rule in its module docstring.
* Revisit this if KiCad ever netlists symbol units as separate elements, which
  would make a package-level wrapper unnecessary.
