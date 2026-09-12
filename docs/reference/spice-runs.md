# SPICE runs — netlists, ngspice, harnesses and the live sketch

A simulation is a PROJECT, not a sheet. This page holds the server side: how a
schematic becomes a netlist, how ngspice is driven, what a verdict harness may
do, and the traps that make a run report success when it failed. The services
are `sim_spice.py`, `project_ops.py`, `sch_lib.py`, `sim_scenario.py` and
`sim_example.py`, with `render/sim_worker.py` in the render container.

The browser side is in `web/src/sim/CLAUDE.md`. The model storage rules are in
[simulation-models.md](simulation-models.md). The wider design is in
[docs/simulator/design.md](../simulator/design.md).

- **`alter` does nothing to a RUNNING ngspice transient.** It returns success
  and changes not one value; the live worker therefore wraps every knob in
  `bg_halt` → wait for `ngSpice_running()` → `alter` → `bg_resume`, which does
  take and continues the same transient instead of restarting it
  (`render/sim_worker.py`, measured 2026-08-30). A source with a WAVEFORM
  (PWL, PULSE, SIN) cannot be steered by any spelling of alter — a harness
  that wants a live input drives it from a plain DC source or a control node.
- **A simulation is a PROJECT, not a sheet.** A design repository keeps one
  `_sim` KiCad project per block it exercises (`EVSE_20_CTRL` has six); the
  root sheet includes the real block sheet and adds the harness — supplies,
  PWL stimulus, loads, a `.control` verdict block — as SPICE text. So
  `sim_run.run` ALWAYS netlists the source root, whatever sheet the viewer is
  showing: netlisting the block alone drops the harness and ngspice answers
  `incomplete or empty netlist`.
- **Every `.kicad_pro` is a "board" to discovery, so the ingest classifies
  them.** `project_ingest.classify_board` stamps each record with `kind`:
  `harness` when the root sheet carries a SPICE directive
  (`HARNESS_DIRECTIVE_RE`, the one regex `sim_run` also counts with), else
  `board`. The `_sim` suffix is NOT the rule — a schematic-only design with no
  layout is still a board — and is used only when the sheet cannot be read,
  marked `kind_guessed`. Snapshots from before 2026-09-11 have no `kind`;
  `_snap_json(…, db=db)` back-fills them from the checkout on first read and
  persists. The project view, the project list and `web/src/api.ts
  designBoards()` show `kind != harness` only; the Schematic tab's own
  Simulation picker and the Simulator list the harnesses. A production run or
  BOM never names a harness.
- **Server-side, `Sim.Library` arrives spelled the INSTALLED way.** A project
  schematic stores `${KICAD10_3RD_PARTY}/symbols/com_sevensigma_library/…`
  (`pcm.SIM_LIB_INSTALLED`), not the mirror's `${SEVENSIGMA_DIR}/Symbols/…`,
  so every real project failed to netlist until `pcm.server_pcm_root()` laid
  out a PCM-shaped directory that symlinks to the mirror and both netlist
  paths exported `KICAD10_3RD_PARTY`. `sch export netlist` has no
  `--define-var`; the environment is the only way in. **Expose the model FILE
  there, never the mirror's `Symbols` folder**: kicad-cli 10.0.5 segfaults
  (rc 139, no message at all) when a `.kicad_sym` sits in the directory a PCM
  symbol library resolves to. Measured — the same schematic exports 512 lines
  with `7Sigma_sim.sp` alone beside it and dies the moment
  `7Sigma_Base.kicad_sym` is copied in next to it.
- **Simulation runs as an OP, not as its own service** (`docs/simulator/design.md`).
  `project_ops.sim_run` netlists a sheet with kicad-cli and runs ngspice on the
  result, so it rides the existing render dispatch: `RENDER_MODE=local`
  simulates on a developer Mac with no container, and MinIO caching came free.
  `services/sim_geom.py` extracts the overlay geometry and takes net NAMES from
  the kicadxml netlist rather than deriving them — KiCad's naming rules
  (hierarchy prefixes, power symbols, `Net-(R1-Pad2)` fallbacks) are its own
  business, and an overlay that guessed them would quietly disagree with the
  simulation. Two facts that cost an afternoon each: `kicad-cli` DOES expand
  `${SEVENSIGMA_DIR}` in `Sim.Library` from the environment, and a symbol's
  stored rotation must be NEGATED once library y-up coordinates are flipped
  into sheet y-down (`sim_geom._place`) or a 270-degree part swaps its pins.
- **`(mirror x|y)` is applied AFTER the rotation, in SHEET axes.** Before the
  turn it flips the symbol's own axis, which at 90 or 270 degrees is the other
  sheet axis, so a mirrored resistor lying on its side gets pin 1 at pin 2's
  end. At 0 degrees the two orders agree, which is how the bug survived: it
  showed on exactly one sheet of one project (CP_PWM, nine group-net
  conflicts, 2026-09-12). Test for it by comparing every placed pin's group
  net against the kicadxml netlist across a whole project, not by eye. All
  three implementations move together — `sim_geom._place`,
  `sch_draw.placement_matrix` and `web/src/sim/draw/geom.ts matrixOf`.
- **The browser DRAWS the schematic; the server only parses it.**
  `services/sch_draw.py` turns a `.kicad_sch` into a draw document — library
  graphics in symbol coordinates plus a placement matrix each — and it is
  attached to the geometry response (`geom["draw"]`) so the two come from ONE
  parse and can never disagree about item order. `sch_draw.placement_matrix`
  must stay identical to `sim_geom._place`: the overlay reads a pin the server
  positioned and the renderer draws it from the matrix. Consequence worth
  knowing: the project's schematic tab no longer renders SVGs through
  kicad-cli, so it needs the CHECKOUT rather than a cached render. A pruned
  checkout is re-materialised from the git mirror; a server with no mirror at
  all now fails where a cached render used to answer.
- **There is no schematic IMAGE any more.** `sch_svg`/`sch_svg_plain`,
  `project_render.sch_pages_zip`, the `/snapshots/…/schematic` endpoints,
  `/api/sim/…/sheet.svg` and the ingest pre-render are gone. Component
  previews (`services/render.py`, symbols and footprints from `.kicad_sym` /
  `.kicad_mod`, cached on disk by content hash) are a DIFFERENT path and are
  untouched. Object storage has no invalidation for a render nobody asks for,
  so the deploy that stopped writing them also removes them:
  `storage.drop_schematic_renders()`, called once on startup in a background
  thread behind the marker object `maintenance/schematic-renders-dropped.v1`.
  Listing the bucket is the slow part — a deploy must not wait for it.
- **The schematic palette and writer** (`services/sch_lib.py`,
  `services/sch_write.py`) are how a circuit drawn in the browser becomes a
  real file. Four things KiCad 10 refuses or mis-reads, all found by it
  refusing to load and saying only "Failed to load schematic":
  - a `lib_symbols` entry is named by the FULL library id (`"Simulator:R"`)
    while its unit sub-symbols keep the bare name (`"R_1_1"`);
  - a `wire` has exactly TWO points — a drawn run of several segments is
    several wires;
  - `junction` and `no_connect` take `(at x y)`, with no angle;
  - `(power global)`, not `(power)`.
  Two more that load fine and then lie: a pin name written `"~"` inside a
  `.kicad_sch` is NOT folded away the way it is in a `.kicad_sym`, so every
  generated net becomes `Net-(R1-~-Pad1)` — write an empty name; and
  `Sim.Device R` on a switch makes KiCad PREFIX the reference rather than
  replace it, so `SW1` netlists as `RSW1` and an `alter sw1` is accepted and
  does nothing (`sim_geom.spice_instance` is what the UI must use).
- **The palette's active parts reference the platform's OWN models.** An
  op-amp, an inverter, an AND gate and a D flip-flop are not built from a
  Value field the way R, C, L and the sources are: each carries the same four
  link fields the mirror puts on a catalogue part (`Sim.Device SUBCKT`,
  `Sim.Name sigma_…`, `Sim.Library`, `Sim.Pins`) pointed at
  `7Sigma_sim.sp`, as `conventions-simulation` requires — never a KiCad
  install file. `sch_lib._ic` derives `Sim.Pins` from the pin order it is
  given, so the map cannot drift from the picture. The path written is
  `pcm.SIM_LIB_INSTALLED`, not the mirror's `${SEVENSIGMA_DIR}` form: both
  resolve on the server, and only that one also resolves in the user's own
  KiCad after they install the library package — which a sheet drawn here is
  meant to be opened in.
- **A diode needs `Sim.Device D` and `Sim.Params`.** Without them KiCad emits
  `D1 __D1` — the reference, a model name, and NO NODES. The part vanishes
  from the circuit and nothing says so, which is the silent-disconnection
  failure `conventions-simulation` warns about. With them KiCad writes a real
  `.model` from the parameters. The same mechanism is what gives a part more
  than one number to set: `sch_lib.PARAM_FORMS` declares what each primitive
  is asked for, and the browser fills the template in.
- **A run that PRINTED is a run that succeeded.** A verdict harness executes
  its analysis inside the `.control` block and echoes a PASS/FAIL table;
  ngspice writes the rawfile for the DECK's analysis, so such a run finishes
  with a result and no vectors. `run_ngspice` used to call that "produced no
  data" and fail — which made every one of `EVSE_20_CTRL`'s six harnesses
  unrunnable from the UI. It now returns an empty rawfile when the log holds
  anything the deck itself printed (`_printed_anything`, which discounts
  ngspice's own banner), and `sim_run` encodes a payload with no plots.
- **Trim a run's log by what it SAID, not by where it ends.** ngspice prints
  an operating-point dump — one line per node — when the transient starts, and
  a SECOND one after the control block finishes. On the worked example that is
  179 lines, and a plain `log[-4000:]` tail threw all four PASS lines away: the
  run worked, the answers were printed, and the browser got a wall of node
  voltages with no verdict in it. `sim_spice.trim_log` keeps the tail AND every
  verdict, section heading and error line the tail cut off, and the cap is
  20 kB rather than 4 kB. Measured 2026-08-31.
- **The model library is per-INSTANCE data, not code.** A palette or a harness
  that names `sigma_…` runs only where that model is published. Pointing the
  simulator palette at the `sigma_rail_*` family worked on production and
  failed on a local database that had never seen it — kicad-cli then reports
  `could not find base model` followed by `Unknown simulation model parameter`
  for every param, which reads like a code fault and is not one. Copy the
  models through `POST /api/sim-models/propose` (the name is read out of the
  `.subckt` line), blocks before the wrappers that instantiate them; the mirror
  regenerates on publish.
- **The live endpoint takes a browser-written netlist, gated.** A sketch's
  live session sends `netlist` in the start frame (and in `op: "reload"`)
  instead of a path, and `render/server.py` skips kicad-cli entirely — that is
  most of the instant feel. The gate (`sanitize_browser_netlist`): no
  `.control` block, and no `.include`/`.lib` except the `%SIGMA_SIM_LIB%`
  token, which the server rewrites to the real model-library path. An include
  is a file read with the worker's eyes; the only file a sketch may read is
  ours to name.
- **`sim_worker.py` reloads a circuit without losing component state.**
  `op: "reload"` fills each `IC=%IC_<ref>%` token from the worker's last data
  point (it keeps the WHOLE point in `self.last`, not just the overlay
  subset), halts, `destroy all` + `remcirc`, loads, `bg_run`. Simulated time
  stays continuous via `t_offset` — each new transient starts its own clock at
  zero and the stream's clock must not jump backwards under the scopes. The
  frame format is v2: it carries its own overlay count, because a reload can
  change the overlay while old frames are still in flight.
- **A harness that wants waveforms too says `run`, and leaves `.tran` on the
  sheet.** The rule above is about what ngspice DOES, not what a harness must
  settle for: with the analysis inside the control block ngspice writes no
  rawfile at all, but with `.tran` as a sheet directive and `run` as the first
  command in the block, the deck's analysis goes to the rawfile `-r` named AND
  the block still echoes its PASS/FAIL table. One run, waveforms and verdicts
  (measured 2026-08-30; `services/sim_example.py` is built this way). `run`
  also picks up whatever analysis the Scenario panel injects, so the checks
  survive a user asking for a different sweep.
- **A geometry symbol carries `props`: every field on the placement, hidden
  ones included.** `draw.symbols[].fields` cannot serve that purpose — it drops
  hidden fields, because it exists to DRAW the sheet and a hidden field is
  precisely one that is not drawn. `props` is what a part says about itself
  (footprint, datasheet, description, manufacturer's number, model), and it is
  what the part dialog shows.
- **`services/sim_example.py` is the worked circuit the Simulator offers when
  there is nothing to open** (`POST /api/sim/example`). It is an ordinary
  sketch — stored by `store_sketch` like any drawing, so it is editable and
  re-runnable the moment it opens, and nothing downstream knows where it came
  from. Every coordinate in it is a multiple of 1.27 mm, because a pin off the
  grid does not connect and nothing says so.
- **`services/sim_scenario.py` reads a harness rather than rewriting it.** The
  text items beside the circuit are classified — `.control` blocks are runs,
  a lone `.tran`/`.ac`/`.dc`/`.op` is the analysis, the rest is stimulus or
  prose — and served by `GET /api/sim/…/scenarios`, which also carries the
  analysis forms the run panel builds a directive from. A `.control` block
  names itself with its first `echo`. The PASS/FAIL table it prints is parsed
  in the BROWSER (`web/src/sim/scenario.ts`), from the log the run already
  carries; a second copy here would be a second thing to keep in step.
- **`sanitize_browser_netlist` refuses `.control` ANYWHERE, not "the first
  block".** It used to split with `find_control`, which takes the first block
  only, and test whether that body was empty — so an empty `.control`/`.endc`
  pair followed by a real block, or simply a second block, reached ngspice
  with `shell` and `write` available in the render container. Measured and
  closed 2026-09-07. The gate is a per-line test on the directive, and the
  banned-command list in `check_control` is not the defence for live mode.
- **A hold survives an `alter` and a reload** (`render/sim_worker.py`,
  2026-09-07). `apply_alter` cleared `deliberate_halt` unconditionally, so an
  alter made while holding let the watchdog report a false error 0.45 s
  later; `reload` ended in `bg_run`, so a held run resumed while the page
  still said `halted`. Both now remember whether the run was held and put it
  back. `%IC_<ref>%` tokens are matched case-insensitively — the ref is
  lowercased before the replace, and a literal match zero-filled `%IC_C1%`.
- **A control block arrives WITH its fences, and the injector adds its own.**
  The scenario panel and `sim_run_scenario` send a `.control` text item
  exactly as the sheet holds it; `prepare_netlist` wrapped it in a second
  `.control`/`.endc`, ngspice printed `Nesting of .control statements is not
  allowed!` and quit, and every scenario chosen from the menu ran into that.
  `_bare_control` strips the fences first (2026-09-07, both copies).
- **A run that printed an ERROR is not a run that succeeded.** `run_ngspice`
  took any echoed line as proof the block ran, so a deck that died with
  `Error: …` answered 200 with no plots and the browser showed "no checks in
  this run". `_FATAL_RE` now turns `Error:`, `fatal`, `Simulation interrupted`,
  `timestep too small` and `singular matrix` into a `SimError` with the
  complaints, and an empty rawfile counts only with rc 0 and no such line.
- **ngspice names a diode's current `@d1[id]` and a BJT's `@q1[ic]`**, not
  `[i]`. `_I_DEV_RE` accepted `[i]` alone, so every diode current was dropped
  from every payload and the current solver saw an unknown terminal at each
  one (2026-09-07, ngspice 44.2).
- **A root-sheet wire between two sheet pins is named after the CHILD's
  label** — `/MISC/TEMP`, never `TEMP`. `assign_nets` now tries
  `<prefix>/<sheet name>/<pin name>` for every sheet pin on the group before
  marking it `derived`; on CE_Dongle_V3's root that took 16 untinted nets down
  to one (a sheet pin whose child label is spelled differently).
- **A `text_box` netlists like a `text`.** `sheet_geometry` and
  `_DIRECTIVE_RE` read both, so a harness written in a box is a scenario and
  the project list calls it a simulation.
- **`Sim.Params` is BAKED INTO THE PROJECT'S SCHEMATIC, and a library edit does
  not reach an existing snapshot.** The mirror writes `Sim.*` rows onto the
  generated library symbol, but a project's `.kicad_sch` is a git checkout and
  carries whatever was in it at commit time — `grep "Sim.Params" CP_PWM.kicad_sch`
  shows the values frozen there. kicad-cli netlists that file, so a component
  edit today changes nothing about a harness committed yesterday. Adding `IQ` to
  four op-amps on 2026-09-12 left `XU20 … sigma_opamp POLE=1.4 GAIN=3.16Meg
  VOFF=125u ROUT=25` in the deck with no `IQ` at all. The board owner picks the
  change up with **Tools → Update Symbols from Library** in KiCad and a commit;
  nothing on the platform can do it for them. A MODEL edit does reach every
  snapshot at once, because `Sim.Library` points at the mirror — so the two
  halves of a change like this land at different times, and saying which is
  which is part of reporting it.
- **A run reports its own progress, and the store lives with the solver.**
  ngspice prints `Reference value : <t>` — the simulated time it has reached —
  to stdout during a transient, separated by carriage returns because it means
  to overwrite a terminal line. `sim_spice.run_ngspice` therefore reads the
  child incrementally (`select` on the pipe, stderr merged into stdout) rather
  than with `subprocess.run`, and records the fraction under a `job` name the
  BROWSER invents. The store is per process: in `RENDER_MODE=http` it is the
  render container's and `project_render.sim_progress` proxies to
  `GET /sim/progress/{job}` on it; in local mode the API already has it. Both
  endpoints are sync `def`s, so FastAPI answers the poll on its threadpool
  while the run's own request is still blocking. An empty answer is NO NEWS —
  a job that has not reached the solver, or one whose record expired — and a
  poller that reads it as a failure will lie about runs that are fine.
- **A verdict harness solves its transient twice, and that is on purpose.**
  The deck's `.tran` writes the rawfile the scope plots; the `tran` inside
  `.control` is the run the `meas` verdicts read. Every `_sim` project in
  EVSE_20_CTRL has both, so a scenario costs two sweeps — 27 s rather than
  14 s for CP_sim (measured 2026-09-12). `sim_spice.transient_plan` counts
  them so the progress fraction spans the whole run. Removing either half
  breaks something: drop the deck's line and there are no vectors to plot,
  drop the control block's and there are no verdicts.
- **`httpx` errors are not `RuntimeError`s.** A render container that is down
  used to kill every sim route in ASGI with a bare 500; `run_project_op` now
  re-raises them as `RuntimeError("render service unreachable: …")`. The same
  pass made `/netlist` keep the net list when only the SPICE export fails,
  and `snapshot_projects` say `error` when the checkout is missing instead
  of guessing `directives: 0` with a straight face.
- **The model library is per-instance, and it shows.** A schematic saved
  against production carries `Sim.Name sigma_fuse` etc.; a local database
  that never received those models fails the WHOLE netlist with `could not
  find base model`, and nothing simulates until they are copied over
  (`POST /api/sim-models/propose`, base models before wrappers). Production
  had 57 models and the local database 33 on 2026-09-07.
- **An operating point has no sweep axis.** `sim_spice.encode_payload` drops
  the first vector as the axis for a transient, an AC sweep or a DC sweep —
  but an `.op` writes an ordinary node voltage first, and dropping it loses a
  reading the user asked for. The axis test is `len(scale) > 1 or the first
  vector is time/frequency`.
- **`project_ops.py`, `sim_spice.py`, `board_template.kicad_pcb` and
  `themes/Skyline-7S.json` exist twice** — `api/app/services/` and `render/`
  must stay byte-identical, and the workflow's `guard` job fails the build
  when they are not (same pattern as `render.py`/`server.py`). The theme is on
  that list because kicad-cli reads it AND the browser's own renderer reads it
  through `GET /api/sim/theme`; two copies would put the simulator and the
  schematic tab back into two colour schemes. `project_ops.py` imports
  `sim_spice` through a `try: from . import … except ImportError: import …`
  pair, because the API loads it as a package and the render container as a
  flat module in `/srv`.
