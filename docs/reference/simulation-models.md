# Simulation models — storage, wrappers and composition

Backend rules. The services are `simmodel.py`, `sim_store.py` and
`simcompose.py`, with `routers/sim_models.py` on top. Decision
[0001](../decisions/0001-generate-package-sim-wrappers-from-blocks.md) covers the
generated package wrappers.

The wider design is in [docs/simulator/design.md](../simulator/design.md).

Versioned SPICE subcircuits (`SimModel`/`SimModelVersion`, auto-publish like
everything else) plus ONE link per base symbol (`SymbolSimLink`: model +
`{pin number: port}` map). The mirror emits every model into
`Symbols/7Sigma_sim.sp` and turns each link into four `Sim.*` property rows on
every component of that symbol.

A link has **two modes**, and the switch is permanent rather than a migration
aid:

| `SymbolSimLink.mode` | Authored | Derived |
|---|---|---|
| `model` | the subcircuit text, and the `{pin: port}` map | nothing |
| `composed` | `composition`: blocks, their nodes, ties, unmodelled pins | the `.subckt`, its port list, and the pin map |

Facts that are not obvious from the code:

- **`Sim.*` rows land on COMPONENT instances, never only in `lib_symbols`** —
  KiCad's netlister ignores library-level sim properties. `Sim.Pins` is
  mandatory: without it KiCad falls back to raw pin order, counts hidden
  stacked pins and silently mis-wires.
- **The link is keyed on the Symbol, unversioned** (like
  `Footprint.display_name`), so linking sixty symbols does not bump sixty
  symbol versions. Staleness is two fingerprints: the symbol side hashes pin
  numbers + electrical types ONLY (`simmodel.link_material_sha` — a cosmetic
  pin-length edit must not flag links), the model side hashes the PORT LIST
  only (param/topology edits carry links untouched). A stale link's Sim fields
  are WITHHELD from the mirror, with a warning, until re-confirmed —
  re-saving the map in the UI or via `set_symbol_sim_link` is the confirm.
- **Path rewrite at egress**: the mirror writes the canonical
  `${SEVENSIGMA_DIR}/Symbols/7Sigma_sim.sp`; `kicad_http.part_payload` and the
  PCM library zip substitute the installed path
  (`pcm.SIM_LIB_INSTALLED`, under `${KICAD10_3RD_PARTY}`). The `.sp` file is
  part of the library package's subtree hash — dropping it from that tuple
  makes model edits a silent PCM no-op.
- **A component's own `Sim.Params` row rides on top**: link-derived rows are
  prepended in the generator, so a per-component property with the same key
  wins. Datasheet numbers (GAIN, V_BR at test current, TPD…) belong on
  components as `Sim.Params`; topology belongs in the model.
- **`exclude_from_sim` is DERIVED, never authored** — emitted in THREE places, and
  the HTTP one is the only one an existing schematic ever sees:
  `generator.set_exclude_from_sim` for the base library and the per-category libs,
  and `kicad_http.part_payload` for the catalog record. KiCad places parts by their
  HTTP `lib_id`, and **`Update Symbols from Library` rewrites the instance from the
  HTTP record, not from the base `.kicad_sym`** — with an ABSENT flag read as "not
  excluded", so the payload must state it explicitly. Patching only the `.kicad_sym`
  looks right in the package and changes nothing in anyone's schematic. A generated symbol
  stays simulatable when it has a link, or when its reference prefix is `R`, `C`,
  `L` or `#PWR` — SPICE builds those from the Value field with no model at all
  (`R116 … 100k` is a complete element), and power symbols are net names, not
  devices. Everything else with no link is excluded, because it would otherwise
  emit `U47 __U47` and stop the run. Three consequences:
  - **`_base_symbol_fingerprint` hashes the LINK SET as well as symbol versions.**
    Without that the base library is skipped when only a link moved, and the flag
    lags until some unrelated symbol is edited.
  - **A stale link still counts as linked.** Its Sim fields are withheld, so the
    netlist fails loudly rather than quietly dropping a part that belongs there.
  - **Never exclude a two-pin part in series with a net.** A fuse, polyfuse,
    ferrite bead or NTC that is excluded opens a live rail with NO error, which is
    worse than the loud failure a missing model gives — hence `sigma_fuse`,
    `sigma_ferrite` and `sigma_ntc`, which are one resistor each and exist purely
    to keep the net connected.
- **`in_bom` and `on_board` are DERIVED the same way, from the top-level
  category `Simulation`** — `generator.set_build_exclusions`, applied in
  `mirror.write_symbol_libs` (both the per-category libs and the base lib) and in
  `kicad_http.part_payload`. That category holds parts that exist ONLY to drive a
  simulation: a PT1000 stimulus, a vehicle emulator, a load. A harness sheet lives
  in the same project as the board, so a stimulus part that does not say it is off
  the BOM lands in the purchase order and on the layout. Same must-be-stated
  argument as `exclude_from_sim`: KiCad reads an absent attribute as "included".
  Two details that are easy to miss:
  - **A base symbol has no category.** `set_build_exclusions` is given
    `Simulation` for a template only when EVERY component drawn from it is a
    simulation part. A template shared with a real part stays on the board — the
    per-category library and the HTTP record carry the exact per-component answer,
    and `7Sigma_Base.kicad_sym` is only the fallback drawing.
  - **`_base_symbol_fingerprint` therefore hashes every published component's
    category too**, next to the symbol versions and the link set. Moving the last
    component out of `Simulation` changes the base library with no symbol version
    touched, and without the categories in the hash the flag lags.
- **`on_board` has a SECOND source: an off-board part** (`generator.off_board`,
  2026-09-11). The category rule above covers a part that is not built at all;
  this one covers a part that IS built and bought but has no land pattern — a
  cabled antenna, an RF pigtail, an enclosure with no drawn outline. It is
  off-board when **the base symbol declares `(on_board no)` AND the component has
  no footprint**, and both halves are load-bearing:
  - Without the declaration, a component whose `Footprint` is merely FORGOTTEN
    would silently drop off the board — exactly the defect `cmp.footprint_ref`
    exists to catch.
  - Without the footprint test, the 17 `TERMINAL_BLOCK_PLUG` components would
    drop off too. That symbol declares `(on_board no)` while every component on
    it carries the deliberate `TerminalBlock_Plug_Invisible` land, which has been
    placed on real boards for as long as the generator was overriding the
    declaration. Honouring the declaration alone would make the next
    `Update PCB from Schematic` DELETE those footprints from existing boards.

  **Before this, `set_build_exclusions` forced `on_board = True` for everything
  outside `Simulation`, so a base symbol's `(on_board no)` was silently thrown
  away** — verified on the live mirror 2026-09-10: `Antenna_Cabled` and
  `RF_Pigtail` were emitted `(on_board yes)` despite both sources saying `no`,
  and the `Antenna_Cabled` v1 comment's claim that this is what stops KiCad
  reporting a missing footprint was simply not in force for six parts.

  Three things follow. **`off_board` is called by BOTH writers of KiCad data** —
  the mirror through `set_build_exclusions(…, has_footprint=bool)` and
  `kicad_http.part_payload` for `exclude_from_board` — because KiCad places from
  the HTTP record, so patching only the `.kicad_sym` changes nothing in anyone's
  schematic (the same trap `exclude_from_sim` documents above). **The base
  library passes `has_footprint=None`**, which means "keep the drawing's own
  declaration": there is no component there and so no footprint to test, and the
  drawing is the only place that intent is authored. And **`in_bom` is
  deliberately NOT derived from the base symbol**: several carry an `(in_bom no)`
  this library does not mean — `RPi_CM5` is a Compute Module 5, a real purchased
  part — so honouring that token would drop the most expensive line on the board
  out of every BOM. Whether a part is bought is `Component.purchasable`.
- **`validator.validate_component` shares that predicate**, so what the validator
  forgives and what KiCad is told cannot drift. An off-board part answers
  `cmp.required_props` / `cmp.footprint_ref` as `na`, alongside the existing
  BOM-only (`in_library=False`) and simulation-only branches. It was the third
  class of footprint-less part and the only one with no branch, so both machine
  items **failed by construction** on every cabled antenna, pigtail and
  footprint-less enclosure, and a human had to answer `na` by hand on each. The
  safety net survives because the predicate needs the symbol's declaration: an
  empty `Footprint` on an ordinary part still fails.
- **KiCad's embedded ngspice runs `ngbehavior=ps lt a`** (Compatibility mode
  "PSpice and LTSpice", `schematic.ngspice.model_mode` 4 in the `.kicad_pro`; 0 is
  "User configuration" and applies no flags). In that mode `$` is NOT a comment —
  numparam feeds the text to the expression parser and the model fails to load —
  and an XSPICE `.model … adc_bridge` inside a subcircuit does not resolve. Use
  `;` for in-line comments, and reproduce that parser without KiCad by writing
  `set ngbehavior=pslta` into a `.spiceinit` file in the working directory
  and running `ngspice -b …` there. Do NOT put it in a private
  `<dir>/scripts/spinit` with `SPICE_LIB_DIR=<dir>`: that REPLACES the stock
  `spinit`, which is what loads the XSPICE code models, and every model with
  an `adc_bridge` then fails with `MIF-ERROR - unable to find definition`
  — a false failure that the earlier form of this recipe produced on
  `sigma_and4`, `sigma_dff`, `sigma_inv` and `sigma_sym_sn74hc21`
  (2026-09-07). KiCad's bundled ngspice is 45.2, not whatever is on PATH;
  the render container has 44.2. Measured on 2026-09-07: all 33 local models
  pass `.op` in default mode, and in `pslta` mode `sigma_hss` (and the
  `sigma_sym_bts723gw` wrapper on it) fail on `$` comments — the exact trap
  this bullet describes, in a published model. `propose_sim_model_version`
  now refuses a `$` outside column 1.
- **Model names are the namespace**: `sigma_` prefix enforced
  (`sim_store.NAME_RE`), and the row name must equal the `.subckt` name.
  `kind` is `primitive` (a building block), `part` (a hand-written wrapper for
  one device) or `composed` (generated — see below). A symbol may link to ANY
  of the first two: a diode, a switch or a 5-pin op-amp IS the primitive, and
  a picker that filtered primitives out would hide most working links from
  their own editor (`routers/sim_models.get_symbol_sim_link`). `kind` is
  otherwise cosmetic — it orders `write_sim_lib`'s output and nothing else.

## Composed models (`services/simcompose.py`)

A wrapper whose whole body is instance lines and tie resistors holds no
behaviour, so it is generated rather than typed. `simcompose.compose()` turns a
block design into a `.subckt`; `sim_store.set_symbol_sim_composition` publishes
it as a normal `SimModel` row with `kind="composed"` and name
`sigma_sym_<symbol slug>`. Everything downstream was therefore untouched — the
mirror emits it like any model, `generator.sim_props` points `Sim.Name` at it,
`Sim.Pins` comes off the same derived map.

- **One wrapper port per unique symbol pin, never fewer.** It is tempting to
  alias a power MOSFET's three source pins onto one port and drop the ties. It
  is wrong: the schematic may put those pins on three different nets, and one
  port carries one node. Ties are real resistors inside the subcircuit, which
  is also what `sigma_nmos_pwr8` did by hand. The payoff is that the port list
  is `p1 p2 p4 …` by construction, so **`Sim.Pins` is derived and cannot be
  mis-authored** — the swap `validate_pin_map` openly cannot catch stops being
  possible in this mode.
- **Staleness is computed, not stamped** (`sim_store.composed_stale_reasons`,
  one implementation, three callers: mirror, link editor, validator). A
  composed link is unusable when its design no longer builds against today's
  block models, or when the published wrapper is not what the design builds.
  Both self-heal; a stamped fingerprint never does.
- **A block model's publish REGENERATES its dependents**
  (`sim_store.recompose_dependents`, called from `propose_sim_model_version`
  and guarded on `kind != composed` so a wrapper's own publish cannot recurse).
  Where a hand-written wrapper would go stale and wait for a person, a
  composition is rebuilt — and when it cannot be, the failure names the port
  that lost its node.
- **Generated text must be byte-stable, so parameters are emitted SORTED.**
  `SimModelVersion.parsed` is a JSONB cache and Postgres reorders a jsonb
  object's keys (shortest first, then bytewise), so the same model yields one
  key order in the session that parsed it and another after a round trip.
  Emitting in dict order made every mirror write report the wrapper as behind
  its own design.
- **The wrapper is owned by its link.** Removing the link, or switching back to
  `model` mode, deletes it (`sim_store._drop_generated`). Hand-written wrappers
  had no such owner, which is how `sigma_74hc21` and `sigma_buf2` sat in the
  library linked to nothing.
- **Parameter bindings** are per block: `$shared` (default — every dual-gate
  package here passes one value to both halves, because both halves are one
  die), `$shared:NAME` to share under another name, `$own` for one wrapper
  parameter per block (`G1_TPD`), or a literal. `composition.defaults`
  overrides a wrapper default where it differs from the block model's own —
  `sigma_tvs_bi` declared `VBR=26.7` while its `sigma_tvs_leg` block defaults
  to 13.3, and a component with no `Sim.Params` row runs on whichever the
  wrapper states.
- **`cli/simrecompose.py`** converts the hand-written wrappers, then prunes
  them: `plan`, `apply --verify`, `prune`, `orphans`. The conversion is
  interface-preserving by construction (`$shared:NAME` keeps every parameter
  name, `defaults` keeps every default), so no component's `Sim.Params` row
  moves. `--verify` proves it by diffing the declared interface. `orphans`
  reports building blocks no symbol can reach and never deletes: an unused
  primitive is library surface someone put there on purpose.
- **The rail heuristic has ONE half, and the other was deleted, not widened.**
  What survives is "a rail-shaped port claimed by a pin that is not a power
  pin" (`simmodel.is_rail_port` — a rail stem plus an optional channel number
  or polarity letter, so `vdd1`, `gnd2`, `vinp` and `vs` count, which a flat
  list of eleven names did not). What went was the mirror check, "a `power_in`
  pin on a port that is not rail-shaped": it cannot tell an LDO's `in` from an
  op-amp's `in+`, because the difference lives in the model and not in the
  name, so no widening could fix it. It reported sixteen correctly wired links
  in this library and not one real fault. Nothing is lost — each port takes
  exactly ONE pin, so a supply pin landing on a signal port displaces another
  pin onto the real rail port, and that pin is not a power pin, which is what
  the surviving half tests.
- Validator machine items: `sym.sim_link` (map errors / stale / composition
  errors / the rail warning above) and `cmp.sim_params` (keys must be declared
  by the linked model). Deliberately NOT checklist-seeded — seeding un-answers every
  existing subject (the `cmp.datasheet_text` incident); the user decides.
- **`kiutils` is patched locally**: upstream ran `Sim.Library` values through
  `PureWindowsPath`, turning `/` into `\\` (`api/kiutils/items/common.py`,
  marked with a comment). Keep the patch when vendoring a newer kiutils.
- The UI lives on Templates → "Sim models" (list + new-model paste,
  `pages/SimModelDetail.tsx` — which refuses to hand-edit a generated model and
  offers deletion only while nothing links it) and on each symbol template page
  (`components/SimLinkCard.tsx`). That card carries both modes. The composed
  editor assigns **port → node**, not pin → port: a block has a short list of
  named ports (`a b c d y vcc vee`) while the symbol has twelve unnamed pins,
  and "gate 1 input A comes from pin 1" is the only direction that survives
  past one block. Beside it sits the **pin coverage** panel, the inverse view,
  which is where a missed pin or a crossed rail is visible — and under both,
  the generated netlist itself, because generation nobody reads is generation
  nobody checks.

