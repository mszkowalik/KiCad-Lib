# Web circuit simulator — design and implementation plan

A Falstad-style simulator inside the platform: open a schematic in the browser,
see voltages and currents drawn over the real KiCad drawing, poke at parameters
while the simulation runs, and replay the scenarios stored in the sim sheets.

Status (2026-08-29): **slices 1 and 3 are built and running** — a schematic
uploaded or picked from a commit is netlisted, simulated, and drawn with its
own voltages and currents on top of KiCad's own render, in the browser (§2.6,
§5.1, §5.3). Slice 2, live continuous simulation, is not started and is still
the plan below. Nothing is committed.

Read first: root `CLAUDE.md`, `api/CLAUDE.md`, `web/CLAUDE.md`, and the
`kicad-conventions-simulation` skill (call `list_skills` to check the local
copy is current). Never commit without an explicit request.

---

## 1. Decisions (settled, do not reopen)

| Decision | Choice | Why |
|---|---|---|
| Solver | ngspice — batch binary for scenarios, `libngspice` shared library for live mode | The library already stores `sigma_*` SPICE subcircuits (`sim_models`, `SymbolSimLink`). Falstad's engine cannot load a `.subckt`; adopting it discards the model library. Results match eeschema's own simulator. |
| Not Falstad's Java | Copy the **interaction model** (§3), not the code | The value of Falstad is the UI loop, not the solver. circuitjs1 is also GPL — do not embed it. |
| Document format | `.kicad_sch` itself, no internal format, no exporter | The file carries positions, wires and embedded `lib_symbols`, so it renders standalone. Web edits (later) write the same file, and KiCad opens it. |
| Netlisting | `kicad-cli sch export netlist --format spice` in the render container | It flattens the hierarchy, resolves `Sim.*` fields and `.include` paths, and copies sim directives from text items. Do not write a netlister. |
| Rendering | kicad-cli SVG (already used by `SchematicTab`), overlay drawn on top | SVG viewBox is in mm, 1:1 with schematic coordinates (§2.3). A native renderer is only needed for editing, which is out of scope. |
| Where it runs | Server side, in the render container | The render container is the existing boundary for running untrusted KiCad files and already has kicad-cli and `SEVENSIGMA_DIR`. A browser/WASM engine is a later option; the API is shaped so the UI does not change if it moves (§4). |
| Scenario source of truth | The `.control` text item in the sheet, per the simulation skill | Scenarios travel with the schematic through git. No separate scenario store in v1. |
| What a run covers | ALWAYS the whole project, from its root sheet | A simulation is a PROJECT, not a sheet — see §3.4. |
| Two modes | **Live** (endless, streamed) and **Scenario** (finite, replayed) | §3 and §4. Same netlist, geometry and overlay; only the data source differs. |

## 2. What was verified, and how

All checks ran on macOS with KiCad 10.0.5 (`kicad-cli`) and ngspice-47
(Homebrew), against KiCad's own `demos/simulation/sallen_key` files fetched
from GitLab. The render image is `kicad/kicad:10.0`, same major version.

Fixture (fetch it, do not vendor it — the KiCad demos carry their own licence):

```
for f in sallen_key.kicad_sch sallen_key.kicad_pro ad8051.lib; do
  curl -fsSL -o $f "https://gitlab.com/kicad/code/kicad/-/raw/master/demos/simulation/sallen_key/$f"
done
```

### 2.0 What the build then confirmed

Everything in §2.1-§2.5 was measured before any code was written. These came
out of building slice 1, and each one changed the implementation:

| Question | Answer | Where it landed |
|---|---|---|
| Does `kicad-cli … netlist` expand `${SEVENSIGMA_DIR}` in `Sim.Library`? | **Yes**, from the process environment — the render container's existing `SEVENSIGMA_DIR: /data/mirror` is enough | the risk that would have forced a rewrite of `.include` lines is gone |
| Does a relative `Sim.Library` resolve against the sheet or the working directory? | The **working directory wins** when the file is there — measured, two runs, two answers | `project_ops` runs the netlist ops with `cwd` = the sheet's own folder |
| Does hierarchy flatten correctly? | Yes. Sub-sheet nets become `/<sheetname>/<net>`, and a sheet placed twice yields two sets (`/amp_a/…`, `/amp_b/…`) | geometry is keyed by sheet INSTANCE path, never by file |
| Is `ngspice` installable in the render image? | Yes — Debian 13 (trixie) base, `ngspice` 44.2, `spinit` at the standard path, no `SPICE_LIB_DIR` needed | one word in `render/Dockerfile` |
| Do symbol rotations transform as expected? | **No** — the stored angle must be NEGATED once library y-up coordinates are flipped into sheet y-down | `sim_geom._place`; with the naive sign a 270-degree resistor swaps its pins and the overlay colours the wrong wire |
| What does a part with no sim model netlist as? | `REF __REF`, which ngspice warns about and then ignores — a silently wrong circuit | `sim_spice` strips those lines and returns the refs in the payload |

### 2.1 Netlist export

```
kicad-cli sch export netlist --format spice -o out.cir sallen_key.kicad_sch
```

Result, verbatim structure:

```
.title KiCad schematic
.include "/abs/path/ad8051.lib"        <- Sim.Library resolved to an absolute path at export time
.ac dec 10 1 1Meg                      <- copied from a schematic text item
.control
version
.endc                                  <- copied from a schematic text item
R1 Net-_C1-Pad2_ Net-_R1-Pad2_ 1k
V1 Net-_R1-Pad2_ GND DC ac=1 AC 1
C1 /lowpass Net-_C1-Pad2_ 100n
XU1 Net-_U1-+_ /lowpass VDD VSS /lowpass AD8051
...
.end
```

Confirmed: labelled nets are `/name`, power nets are bare (`GND`, `VDD`),
anonymous nets are `Net-_<ref>-Pad<n>_`, subcircuit instances follow the
`Sim.Pins` order. Available formats include `kicadxml`, which lists every net
with its member pins — use it to map nets to pins (§5.2).

### 2.2 Batch run and vectors

```
ngspice -b -r out.raw out.cir            # 20 ms wall clock, 61 AC points, 45 vectors
```

With `.options savecurrents` added before the analysis line: 91 vectors,
including `i(@r1[i])`, `i(@c1[i])`, `i(v1)` — one terminal current per
top-level device. Node voltages are `v(/lowpass)`, `v(vdd)`, `v(net-_c1-pad2_)`
(names are lower-cased in the rawfile).

Transient: `.tran 1u 5m` with a 1 kHz sine source → 5008 points × 91 vectors,
**80 ms wall clock**, 3.6 MB binary rawfile. Rawfile format: ASCII header
(`Variables:` block, `No. Points:`), then `Binary:` followed by float64 rows.

Trap: 40 of the 91 vectors are subcircuit internals (`v(xu1.53)`,
`@q.xu1.q4[ic]`). Filter them out before returning anything: keep `v(<net>)`
for nets that exist in the kicadxml netlist, `i(@<ref>[i])` and `i(<vref>)` for
top-level refs.

### 2.3 Overlay coordinates

`kicad-cli sch export svg` writes `width="297.0022mm" viewBox="0 0 297.0022 210.0072"`.
A wire at `(xy 212.09 125.73)` in the `.kicad_sch` appears as `212.0900` in the
SVG path data. **Schematic mm and SVG user units are the same space** —
`SchematicTab.tsx` already relies on this for hotspots (`pct(x, pageW)`).

### 2.4 Live mode through libngspice (ctypes)

Script: `livetest3.py` (§9). Findings:

| Check | Result |
|---|---|
| `ngSpice_Circ` + `.tran 1u 1000` + `bg_run` | runs on a background thread, main thread free |
| `SendData` callback rate | **95 000 points/s** for the opamp circuit — 95× real time at 1 µs `tstep` |
| `SendInitData` | called once per run with all 91 vector names |
| `alter r1=100k` while running | accepted, points kept flowing with the new value — no restart |
| `bg_halt` / `bg_resume` | pause and continue the endless run |

Traps found:

1. `SPICE_LIB_DIR` must point at the directory holding `scripts/spinit`
   (`/opt/homebrew/share/ngspice` on the Mac, the Debian package's own path in
   the container). Without it XSPICE code models are missing and any model
   using a `poly` source fails with `MIF-ERROR - unable to find definition`.
2. `SendData` fires only when **all** callbacks are registered in
   `ngSpice_Init` (including `SendInitData` and `BGThreadRunning`). With
   `NULL` for the later ones, zero data callbacks arrived.
3. `libngspice` holds **one circuit per process**. A live session needs its
   own worker process.
4. The callback runs on the simulation thread. Blocking inside it throttles
   the solver — that is the pacing mechanism (§3.2). Unverified: measure that
   sleeping in the callback does not upset ngspice's own timing.

### 2.5 Falstad's live loop (from circuitjs1 master)

Verified in source, not from memory:

- `SimulationManager.runCircuit()` runs once per animation frame. It steps
  until sim time keeps pace with wall time at the speed-slider rate, with a
  hard cap of **50 ms of compute per frame** (`frameTimeLimit = 1000/minFrameRate`).
  A heavy circuit slows the simulation, never the frame rate.
- Speed slider: `CirSim.getIterCount() = 0.1·exp((slider−61)/24)` — exponential.
- The animated overlay (voltage colour, current dots) is drawn **once per frame
  from the latest state only**. Intermediate points are discarded.
- Scopes keep a **min/max envelope per pixel column** (`ScopePlot.timeStep()`):
  every point folds into `minValues[ptr]`/`maxValues[ptr]`; the column advances
  every `maxTimeStep × speed` of sim time (`speed` = timesteps per pixel,
  default 64, powers of two).
- Adaptive timestep: three clean Newton solves → double `dt`; non-convergence
  → halve `dt`, restore last node voltages, retry.

Consequence: nothing downstream of the solver is oversampled. We do the same on
the server (§3.2).

### 2.6 Slice 1, measured on the deployed stack

Through the running api container (auth on) to the rebuilt render container,
on KiCad's `sallen_key` demo:

| Step | Result |
|---|---|
| `POST /api/sim/uploads` | 200, root sheet detected without being told |
| `GET  …/geometry` | 200, 13.9 kB — 27 wires, 27 with a net, 29 pins, no warnings |
| `POST …/run` (`.tran 10u 5m`) | 200, 32.8 kB — 508 points, 13 vectors kept out of 91 |
| the join the overlay needs | every non-ground net on the drawing has a vector: `/lowpass`, `net-_c1-pad2_`, … |

`api/cli/simcheck.py` runs the same path plus a hierarchical variant and the
two refusals (shell command in a `.control` block, upload with no schematic):
18 checks, all passing.

## 3. Interaction model

### 3.1 Scenario mode (finite)

1. The sheet's own `.control` block runs verbatim in batch ngspice.
2. The API returns the complete filtered vector set (binary, §4.3).
3. The browser scrubs, plays and loops through the points. Scrub backwards,
   single-step, slow motion. Scope panels plot any returned vector.
4. Edits to the `.control` text in the UI re-run and keep the previous run for
   comparison. Editing does not write to the schematic file in v1.

### 3.2 Live mode (endless) — BUILT

Measured, and the one thing that decides whether this mode can exist at all:

**`alter` on a RUNNING background transient is accepted and does nothing.**
The command returns success, the points keep flowing, and every value stays
exactly as it was. An earlier note in this document claimed the opposite,
on the evidence that points kept flowing — which proves only that the run did
not stop. The values were never checked. They should have been.

What does work, and what the worker therefore does for every knob:

    bg_halt  ->  wait for ngSpice_running() to go false  ->  alter  ->  bg_resume

`bg_resume` continues the SAME transient rather than restarting it, so the
state the circuit had reached survives the edit. Verified on a divider:
`alter v1 = 4` moved the mid-node from 5 V to 2 V and `alter r2 = 3k` moved it
to 3 V, both while the run carried on from where it was. At any speed a person
would watch, the pause is shorter than a frame.

**A source with a waveform cannot be steered at all.** `alter vsi1 dc = 0` and
`alter @vsi1[pwl] = [0 0]` are both accepted and both ignored: a PWL source
keeps its script. A harness that wants an input to be live-controllable should
drive it from a plain DC source, or from a control node — which is what the
`conventions-simulation` skill already says, for the same reason. The
harnesses in EVSE_20_CTRL put a 1 ohm resistor in series with every drive so a
scenario can float it, and raising that resistor IS steerable.



1. One worker process per session holds `libngspice`, loads the same netlist
   with the analysis line replaced by `.tran <tstep> 1e9` plus
   `.options savecurrents`, and calls `bg_run`.
2. The `SendData` callback folds every point into two products, Falstad-style:
   - **snapshot**: latest value of every overlay vector (nets, device currents)
   - **envelope**: min/max per scope column for the vectors the client
     subscribed to; a column closes every `tstep × columns_per_px` of sim time
3. A frame task sends `{sim_t, snapshot, closed_columns}` over the websocket at
   ≤ 60 frames/s. Bandwidth is a few kB/s regardless of solver speed.
4. Pacing: the client's speed setting is a target sim-seconds per wall-second.
   The callback sleeps as needed to hold that rate. If the solver is slower
   than the target, the rate degrades and the frame rate stays.
5. Interaction: `alter <ref>=<value>` and `alter @<dev>[<param>]=<v>` commands
   are forwarded as-is; switch flips use the drive modes from the simulation
   skill. `halt`, `resume`, `reset` (reload the circuit) are explicit messages.
6. Lifecycle: spawn on connect, kill on disconnect, idle timeout (default 10
   min), hard cap on concurrent sessions per container (default 4), CPU
   watchdog. Session state is never persisted.

### 3.4 A simulation is a project, not a sheet

The repositories already work this way, and the platform now follows them.
`EVSE_20_CTRL` keeps six harnesses beside the board — `CP_sim`, `DIN_sim`,
`DOUT_sim`, `RESET_sim`, `SAFETY_sim`, `TEMP_sim`. Each is a real
`.kicad_pro` whose root sheet:

- **includes** the block under test (`SAFETY_sim.kicad_sch` places the real
  `SAFETY.kicad_sch` as a sub-sheet — included, not copied, so the harness
  never drifts from the design), and
- carries the harness as SPICE **text items** beside it: supplies, PWL
  stimulus, coil loads, a `.tran`, and a `.control` block that prints a
  verdict table.

Nothing in the block is edited to make it simulate, and nothing about the
design's own sheet instances moves — which is the point of a separate project.

Two rules follow, and both were learned the hard way (2026-08-29):

1. **A run netlists the project ROOT, never the sheet on screen.** Netlisting
   `SAFETY.kicad_sch` alone drops every source and load, and ngspice answers
   `incomplete or empty netlist`. Simulating a block in isolation is not a
   mode; it is a reason to make a `_sim` project for it. The viewer still
   picks any sheet — that choice is about what to LOOK at.
2. **Open the sheet that is drawn on.** A harness root is a page of SPICE text
   around one sheet box (0 parts, 3 directives), and the leaves are single
   channels (15 parts each). Neither "the first sheet" nor "the deepest sheet"
   finds the circuit under test — `SAFETY`, with 87. `sheets()` returns a part
   count per sheet and the page opens the richest one.

`GET /api/sim/snapshot/{id}/projects` lists a commit's KiCad projects and
marks which are harnesses (a root sheet carrying SPICE directives), so the
page can offer the blocks instead of the board.

### 3.5 The library path a project actually stores

A schematic drawn against the installed library stores
`${KICAD10_3RD_PARTY}/symbols/com_sevensigma_library/7Sigma_sim.sp`, because
that is what the user's KiCad resolves — `pcm.SIM_LIB_INSTALLED`, written by
the two egress points. The mirror's own spelling,
`${SEVENSIGMA_DIR}/Symbols/…`, appears only in server-side files. So the
server saw a variable it did not define and every real project failed to
netlist with `could not find base model 'sigma_diode'`.

`pcm.server_pcm_root()` lays out `DATA_DIR/pcmroot/symbols/<install dir>/` and
puts a RELATIVE symlink to the mirror's `7Sigma_sim.sp` inside it, and both
netlist paths export `KICAD10_3RD_PARTY` pointing at the root. Both spellings
then reach the same file, nothing is rewritten, and a regenerated library is
picked up with no extra step. `kicad-cli sch export netlist` has no
`--define-var`, so the environment is the only way in.

**Only the model file goes in that directory.** Linking the mirror's `Symbols`
FOLDER is the obvious shortcut and it makes kicad-cli 10.0.5 segfault — rc
139, stdout and stderr both empty, so the API could only report "kicad-cli
failed". The trigger is a `.kicad_sym` in the directory a PCM symbol library
resolves to; `7Sigma_Base.kicad_sym` lives beside the model file in the
mirror. Bisected on 2026-08-29: the same schematic exports 512 lines with the
`.sp` alone in the folder, and dies the moment the `.kicad_sym` is copied in
next to it. Worth reporting upstream.

### 3.3 Where a schematic comes from

Three entry points, one pipeline:

1. **Project snapshot**: `(snapshot_id, board, sheet)` — files come from
   `gitrepo.materialize(project_id, sha)` under `/data/checkouts`, already
   visible to the render container (`apidata:/data:ro`).
2. **Upload**: the user drops a `.kicad_sch` (plus subsheets and any local
   `.lib`/`.sp` files) exported from their KiCad. Stored under a per-user
   scratch key in MinIO, materialised to `/data/sim_uploads/<uuid>/`.
3. **Web-drawn** (later): the editor writes a `.kicad_sch` into the same
   scratch area, and the user downloads it to redraw nothing.

## 4. Contracts

### 4.1 Render container

New in `render/server.py` (and its `project_ops.py` copy — the `guard` job
requires byte-identical copies of `project_ops.py` with `api/app/services/`):

| Endpoint | Purpose |
|---|---|
| `POST /sim/netlist` `{path, variant}` → `{spice, kicadxml}` | both formats in one call; `path` relative to `/data` |
| `POST /sim/run` `{path, variant, control_override?, tstep?}` → binary rawfile (filtered) | batch scenario run, 60 s timeout, output cap 64 MB |
| `WS /sim/live` | live session protocol (§4.4) |

Image changes: `apt-get install ngspice libngspice0` (confirm the package names
and the `spinit` path on the image's Debian release), `uvicorn[standard]` so
the websocket route works, `SPICE_LIB_DIR` in the environment.

### 4.2 API

New `api/app/routers/sim_runs.py` + `api/app/services/sim_run.py`:

| Endpoint | Returns |
|---|---|
| `GET /api/sim/sources/snapshot/{snapshot_id}/{board}` | list of sheets with paths |
| `POST /api/sim/uploads` (multipart) | `{source_id}` |
| `GET /api/sim/{source}/geometry?sheet=` | §4.3 geometry JSON, cached by content hash |
| `GET /api/sim/{source}/netlist?sheet=` | `{spice, nets:[{name, pins:[{ref, pin}]}], scenario_text}` |
| `POST /api/sim/{source}/run` `{sheet, control?}` | `application/octet-stream`, §4.3 vectors |
| `WS /api/sim/{source}/live?sheet=` | relayed to the render container's `/sim/live` |

`{source}` is `snap-<id>-<board>` or `up-<uuid>`. Authgate already gates
websocket scopes (`authgate.py`, see the flasher socket for the pattern). The
api → render websocket relay needs a client library: `websockets` comes with
`uvicorn[standard]`, already a dependency.

### 4.3 Payloads

**Geometry** (per sheet, mm, y-down, same space as the SVG):

```json
{
  "size": [297.0, 210.0],
  "wires":     [{"id": "w12", "pts": [[212.09,125.73],[187.96,125.73]], "net": "/lowpass"}],
  "junctions": [{"at": [187.96,125.73], "net": "/lowpass"}],
  "labels":    [{"text": "lowpass", "at": [190,125], "kind": "local|global|hier|power", "net": "/lowpass"}],
  "pins":      [{"ref": "R1", "pin": "1", "at": [187.96,120.65], "net": "/lowpass", "dir": [0,1]}],
  "symbols":   [{"ref": "R1", "at": [...], "bbox": [...], "lib_id": "Device:R", "sim": {"device": "R", "params": {...}}}],
  "texts":     [{"at": [...], "text": ".control\n...", "is_directive": true}]
}
```

Wire → net assignment: a wire segment belongs to the net of any pin, label or
junction it touches (endpoint equality on the 0.01 mm grid, then transitive
closure through touching wires). Cross-check every assigned net against the
kicadxml member list; report unassigned segments in `warnings` instead of
guessing.

**Vectors** (scenario run): custom binary, little-endian —
header JSON `{plot, scale: "time|frequency", vectors: [{name, kind: "v|i", unit}], n}`
followed by `float32[n]` per vector (`float32` × 2 for complex AC data).
Decimate to at most 20 000 points per vector with min/max pairs when the run
is longer; say so in the header (`decimated: true`). Never JSON-encode samples.

### 4.4 Live websocket protocol

Client → server:

```
{"op": "start",  "tstep": 1e-6, "speed": 1.0, "overlay": ["v(/lowpass)", "i(@r1[i])", ...], "scopes": [{"vec": "v(/lowpass)", "sim_s_per_px": 1e-5}]}
{"op": "speed",  "value": 0.1}
{"op": "alter",  "cmd": "alter r1=100k"}          # forwarded verbatim; validate it starts with alter/altermod
{"op": "halt"} {"op": "resume"} {"op": "reset"}
{"op": "scopes", "scopes": [...]}                    # resubscribe
```

Server → client (binary frames, one per animation frame):

```
[u8 kind=1][f64 sim_t][f32 snapshot[len(overlay)]][u16 n_cols]{[u16 scope_idx][f32 min][f32 max]}*
```

plus JSON control frames `{"ev": "ready", "vectors": [...]}`, `{"ev": "error", ...}`,
`{"ev": "rate", "sim_s_per_s": ...}` (measured, so the UI can show when the
solver cannot keep up).

## 5. Implementation slices

Finish a slice, verify it against the running platform, report, wait.

### Slice 1 — scenario pipeline (server) — **DONE**

The simulation turned out to fit the existing render dispatch rather than
needing endpoints of its own: a run is an **op**, like a board render is. So
`RENDER_MODE=local` simulates on the developer's Mac for free, MinIO caching
came with it, and the render container grew no new route.

| File | Change |
|---|---|
| `render/Dockerfile` | installs `ngspice`, copies `sim_spice.py` |
| `api/app/services/sim_spice.py` + `render/sim_spice.py` | **new, byte-identical pair.** Netlist preparation (control block splitting and refusal, `.options savecurrents`, analysis override, dropping unmodelled parts), the ngspice batch call, the rawfile decoder, vector filtering and the 7SIM binary encoder |
| `api/app/services/project_ops.py` + `render/project_ops.py` | ops `sch_spice`, `sch_kicadxml`, `sim_run`; netlist ops run with `cwd` = the sheet's folder |
| `render/server.py` | passes `control`, `analysis` and a clamped `timeout` through `/render-project` |
| `api/app/services/project_render.py` | same three knobs, plus `SPICE_LIB_DIR` on the local path |
| `api/app/services/sim_geom.py` | **new.** Sheet tree, per-instance geometry, connectivity, net assignment from kicadxml, SPICE node naming |
| `api/app/services/sim_run.py` | **new.** Snapshot and upload sources, sheet listing, geometry, netlist, run |
| `api/app/routers/sim_runs.py` | **new.** `/api/sim/{snapshot,upload}/…/{sheets,geometry,netlist,run}` |
| `api/app/config.py` | `ngspice_bin`, `spice_lib_dir`, `sim_timeout_s`, `sim_upload_ttl_h` |
| `api/cli/simcheck.py` | **new.** The end-to-end check, fixtures fetched from KiCad rather than vendored |
| `.github/workflows/images.yml` | the guard now covers three shared files |

Not yet exercised: the **snapshot** source path. It needs a project checkout,
and this machine has none (`/data/git` is empty — the mirrors were pruned).
Every line downstream of the source resolver is shared with the upload path
and is covered; what is untested is `sim_run.snapshot_source` itself. To close
it: fetch a project, then
`GET /api/sim/snapshot/<id>/<board>/sheets`.

### Slice 2 — live session worker

1. `render/sim_worker.py`: standalone process; ctypes bindings from
   `livetest3.py`; folds points per §3.2; talks to the parent over a Unix
   socket or stdio with the binary frame format.
2. `render/server.py` `/sim/live`: session registry, spawn/kill, caps,
   watchdog, relay.
3. `api` websocket relay with the authgate.
4. Measure: pacing accuracy at speeds 0.01–100, callback-sleep behaviour,
   memory of a 10-minute session, kill-on-disconnect.

### Slice 3 — overlay UI — **DONE (scenario mode)**

Built as described, on scenario data. `web/src/sim/payload.ts` decodes the
7SIM buffer into typed-array views (and folds an AC run's complex pairs to
magnitude); `currents.ts` solves the per-segment currents; `SimSheetView.tsx`
draws the three layers; `Scope.tsx` plots the picked traces; `Simulator.tsx`
is the page, at `/sim`, reached from a project's schematic tab or with an
uploaded sheet set. `GET /api/sim/…/sheet.svg` was added for the drawing
itself, and removed again in slice 4 when the browser took the drawing over. Conventions and the traps behind them are in `web/CLAUDE.md`.

Verified in a headless browser against the running stack: geometry renders 27
click targets, the sheet's own AC scenario plots the Sallen-Key roll-off,
clicking a wire adds its trace, scrubbing moves the playhead, no console
errors. One bug the browser found that no server test could: the payload
header has to be padded to a 4-byte boundary or every `Float32Array` view over
the buffer throws.

### Slice 3 — overlay UI (original plan)

1. `web/src/components/sim/SimView.tsx`: the existing `SchematicTab` SVG
   `<img>` replaced by an inline `<svg>` with the page SVG as `<image>` and an
   overlay `<g>` in the same viewBox — voltage colour per wire (diverging scale
   around 0 V, range auto from the run), current as moving dots along wires
   (speed ∝ current, direction from sign and pin `dir`), hover readout.
2. Scope panel: envelope renderer for live, full-vector renderer for scenario;
   click a wire or a device to add a trace.
3. Transport controls: live/scenario switch, play/pause/scrub, speed slider
   (exponential, like Falstad), `Sim.Params` sliders from the geometry
   `symbols[].sim.params`, switch toggles.
4. Entry points: a **Simulate** button on the project schematic tab (snapshot
   source, sheet picker, subsheet navigation reusing the existing
   `sheet-hotspot`s) and a `/sim` page for uploads.

Wire current: the per-segment split inside a net is not a SPICE quantity.
For a net whose wire graph is a tree, KCL fixes every segment current from the
terminal currents at its pins; compute it server-side in the geometry step
(topology only) and evaluate it client-side per frame. For a net with a loop,
animate the whole net with its total terminal current and flag it.

### Slice 4 — the browser draws the schematic — **DONE (2026-08-30)**

kicad-cli's SVG was replaced by a renderer in the browser. Two reasons a
picture could not answer, and both are the whole point of the next slice: a
picture cannot show a switch closing, and an editor needs to know where things
ARE, not what they looked like. It also removes a ~1 s round trip per sheet.

| File | Change |
|---|---|
| `api/app/services/sch_draw.py` | **new.** A `.kicad_sch` -> draw document: library graphics in symbol coordinates, one placement matrix per instance, sheet items. Attached to the geometry response, from the SAME parse, so ids line up |
| `api/app/services/themes/Skyline-7S.json` | the theme kicad-cli renders with, now also served to the browser (`GET /api/sim/theme`) and guarded byte-identical against `render/themes/` |
| `web/src/sim/draw/{types,geom}.ts`, `KicadSheet.tsx`, `SchematicView.tsx` | **new.** THE schematic renderer — one module for the project tab, the simulator and the editor |
| `web/src/components/project/SchematicTab.tsx` | rewritten onto it; the per-page SVG render and the click-map hotspots are gone |

**The schematic image cache went with it.** Nothing rendered a page SVG any
more, so `sch_svg` / `sch_svg_plain`, `project_render.sch_pages_zip`, the two
`/snapshots/…/schematic` endpoints, `/api/sim/…/sheet.svg` and the ingest
warm-up were all removed. Measured on the 87-part sheet: kicad-cli took 0.87 s
and wrote 2.7 MB across 8 files, against 57 ms and 217 kB of JSON for the
parse the browser reads — and the render ran once per board per commit,
kept for good, because a commit is immutable and there is no invalidation path
for a render nobody asks for. `storage.drop_schematic_renders()` deletes what
was already stored; startup calls it once, in the background, behind a marker
object.

Verified side by side against `kicad-cli sch export svg` on a real 87-part
sheet (`SAFETY.kicad_sch`, 10 library symbols, 187 wires, 78 labels). Three
things the comparison corrected that reasoning had got wrong: a field is drawn
at its own angle PLUS the symbol's; a label's stored justification is already
the one for the text as drawn and must not be flipped again for a half-turn;
and body lettering must be drawn after the fills or a gate's `&` is covered by
its own body.

### Slice 5 — drawing a circuit in the browser — **DONE (2026-08-30)**

| File | Change |
|---|---|
| `api/app/services/sch_lib.py` | **new.** R, C, L, D, V, I, switch, ground, rail as real KiCad symbol definitions — because the file the editor saves has to open in KiCad |
| `api/app/services/sch_write.py` | **new.** The editor's document -> a `.kicad_sch` |
| `api/app/routers/sim_runs.py` | `GET /api/sim/palette`, `POST /api/sim/sketch`, `GET /api/sim/upload/{id}/sketch` |
| `web/src/sim/edit/{doc.ts,SchEditor.tsx}` | **new.** The document, its derivations, and the editing surface |
| `web/src/pages/Simulator.tsx` | a Draw mode, and part hotspots in live mode |

A saved sketch becomes an ordinary **upload source**, so a circuit drawn in the
browser runs through exactly the same pipeline as one drawn in KiCad — no
second engine, no second contract.

**It writes new sheets only.** Opening a sheet KiCad wrote would mean writing
it back from a document that does not model every token in it, and the drop
would be silent. The Edit button appears only for a source this editor drew.

**A contact flipped live is flipped on the DRAWING too.** The netlist value
is what `alter` changes, and the file still says what it said, so the blade
would otherwise stay open beside a reading that says closed. A sheet written
by the editor embeds BOTH switch definitions, so this is a swap of `lib_id`
(and the Value that goes with it), not a redraw. The knob panel's value is
owned by the page for the same reason — the drawing and the panel change the
same number.

Verified end to end in a headless browser against the running stack, on
rebuilt local images: five parts placed, wired, a label and a `.tran` typed,
saved, netlisted and run. Then in live mode, the switch clicked ON THE
DRAWING, twice:

| | `/MID` | blade | `rsw1` |
|---|---|---|---|
| open | 50 µV | diagonal | 1G |
| closed | 2.50 V | straight | 10m |
| open again | 50 µV | diagonal | 1G |

all while the same transient carried on.

`api/cli/simcheck.py` covers the new path: the draw document agreeing with the
geometry, a sketch written and run, the `.op` keeping its first column, and
the switch netlisting as `RSW1`.

### Slice 6 — one view — **DONE (2026-08-30)**

Editing was a separate screen. It is now the same view: `sim/SimulatorView.tsx`
absorbed both `SimSheetView` and `SchEditor`, `Edit` is a toolbar toggle, and
the overlay stays on the drawing while the tools are out. `useSimOverlay`
holds the tint, the charge canvas and the click targets so the editable and
read-only paths share one of each.

An edit saves itself 700 ms after the last change — in place, through
`POST /api/sim/sketch?id=…` — and bumps a revision that re-reads the geometry
and the netlist. Verified end to end: a circuit drawn, run (`.op`, switch
open, 100 µV on the divider top), then the contact closed IN THE EDITOR and
run again without leaving the page — 5.00 V and 2.50 V, the answer the closed
circuit has.

### Slice 7 — the scenario, the analysis and the verdict — **DONE (2026-08-30)**

| File | Change |
|---|---|
| `api/app/services/sim_scenario.py` | **new.** Classifies a harness's text items into runs, analysis, stimulus and prose, and declares the analysis forms |
| `api/app/routers/sim_runs.py` | `GET /api/sim/…/scenarios` |
| `web/src/sim/scenario.ts` | reads the PASS/FAIL table out of a run's log |
| `web/src/sim/ScenarioPanel.tsx` | **new.** The runs on offer, the analysis form, the verdict table |
| `sim_spice.run_ngspice` + `project_ops` | a run that PRINTED is a run that succeeded |

The last row is the one that mattered. A verdict harness runs its analysis
inside the `.control` block and echoes a table; ngspice writes the rawfile for
the deck's own analysis, so the run finishes with a result and no vectors.
Calling that "produced no data" made all six of `EVSE_20_CTRL`'s harnesses
unrunnable from the UI.

Verified: `SAFETY_sim` lists its scenario as **"EVSE_20_CTRL SAFETY chain — 100
checks"**, and a circuit drawn in the editor with its own `.control` block runs
and reports `PASS D1 midpoint sits at half the rail` / `FAIL D2 midpoint is the
whole rail`, grouped under the section the harness printed.

### Slice 8 — parts that need a model, and a worked example — **DONE (2026-08-30)**

| File | Change |
|---|---|
| `api/app/services/sch_lib.py` | `_ic`, and four palette parts backed by library models: `OPAMP`, `INV`, `AND`, `DFF` |
| `api/app/services/sim_example.py` | **new.** The worked circuit, as an editor document |
| `api/app/routers/sim_runs.py` | `POST /api/sim/example` |
| `web/src/pages/Simulator.tsx`, `web/src/api.ts` | "Open the example" beside "Draw a circuit" |

The palette used to hold only parts SPICE builds from a Value field. These
four hold the same four link fields the mirror puts on a catalogue part —
`Sim.Device SUBCKT`, `Sim.Name sigma_…`, `Sim.Library`, `Sim.Pins` — pointed at
`7Sigma_sim.sp`, which is where `sigma_opamp`, `sigma_inv`, `sigma_and4` and
`sigma_dff` already lived. `Sim.Pins` is derived from the pin order given to
`_ic`, so the map cannot drift from the picture, and the library path written
is the PCM-installed one, which resolves both on the server and in the user's
own KiCad.

The example is one A3 sheet: +5 V / -5 V rails, a non-inverting amplifier at a
gain of 11, a 1 kHz clock through two inverters (which is what a buffer is,
and drawing them says so), a D flip-flop dividing it by two, and an AND gate
combining the two with its spare inputs on the rail where a reader can see
them. No hidden `X` lines — every block is a placed symbol, as
`conventions-simulation` requires.

**A harness can return waveforms AND verdicts.** Not by relaxing anything: put
`.tran` on the sheet and make `run` the first command in the `.control` block.
ngspice then writes the rawfile `-r` named, because the analysis belongs to the
deck, and the block still echoes its table. With `tran` inside the block it
writes no rawfile at all (measured). `run` also picks up whatever analysis the
Scenario panel injects.

Verified end to end over HTTP: 12 nets and no others, no dangling pin, no wire
through a body, no crossing wires, a 1380-point transient across 17 vectors,
and four checks passing.

### Slice 9 — later, in this order

- Placing parts from the platform library, with `Sim.*` already attached.
- Editing a sheet KiCad wrote: patch the parsed tree (`parse_sexpr` lists
  re-serialised, never kiutils objects) rather than regenerating it.
- Scenario library UI (pick among several `.control` text items, per-sheet).
- A switch that came from KiCad has only one blade position, so its live
  state shows in the readout and not on the drawing. It needs the platform's
  own switch symbol to carry both.
- Engine in the browser (ngspice WASM) behind the same contracts.

## 6. Conventions that apply

- Ground is the power symbol with Value `0`; `GND` is aliased by ngspice, an
  explicit `VGND GND 0` is a short (simulation skill).
- Probe names carry the slash: `v(/sig)`. Pulse width is `tw`, not `pw`.
- `.control` text items need literal `\n` and escaped quotes in the file.
- A component without a linked model gets `exclude_from_sim` from the mirror
  (commits `bafe837`, `c300f10`); the netlister drops it. The UI must show
  which symbols were excluded — a silent gap is a wrong circuit.
- `render/project_ops.py` and `api/app/services/project_ops.py` stay
  byte-identical (CI guard).
- No commits without a request. Report what was verified and how.

## 7. Open questions for the user

1. Upload retention: **built as 24 h** (`SIM_UPLOAD_TTL_H`), swept whenever a
   new upload arrives. Change the setting if that is wrong.
2. Live session caps per container and per user (slice 2). Proposed: 4 / 1.
3. Should a scenario run from the project view be stored with the snapshot so
   a reviewer can open the same numbers later? (Not built.)
4. A component whose `Value` is not a SPICE number (`47uF/20V`, as KiCad's own
   complex_hierarchy demo has) makes ngspice reject the whole circuit. Worth a
   validator rule for parts that carry a sim link?

## 8. Residual risks

| Risk | Size | Status |
|---|---|---|
| `${SEVENSIGMA_DIR}` not expanded by `kicad-cli … netlist` | — | **closed**, it is expanded (§2.0) |
| Hierarchical flatten | — | **closed**, two-sheet fixture passes (§2.0, `simcheck.py`) |
| ngspice missing from the render image | — | **closed**, Debian 13 + ngspice 44.2 (§2.0) |
| Runaway `.control` (infinite loop, huge `wrdata`) | medium | **mitigated**: 60 s timeout clamped to 300 s at the render endpoint, and `BANNED_CONTROL` refuses `shell`, `system`, `source`, `cd`, `write`, `wrdata`, `edit` and friends. No output-size cap yet |
| Sleeping inside `SendData` disturbs ngspice | small | open — measure in slice 2; fallback is `bg_halt`/`bg_resume` duty cycling per frame |
| ngspice 44.2 in the container vs 47 on the Mac | small | open — same rawfile format and `savecurrents`, but a scenario that depends on a newer feature would differ between dev and deployment |
| A parent-sheet wire that reaches only a sheet pin gets no net | small | open — it falls back to the label text and is marked `derived`, which the UI must not plot as a simulated node |

## 9. Reference scripts from the verification session

`livetest3.py` (ctypes streaming test) and the batch commands live in the
session scratchpad, not in the repo. The ctypes layout that worked:

```python
class VecValues(C.Structure):
    _fields_ = [("name", C.c_char_p), ("creal", C.c_double), ("cimag", C.c_double),
                ("is_scale", C.c_bool), ("is_complex", C.c_bool)]
class VecValuesAll(C.Structure):
    _fields_ = [("veccount", C.c_int), ("vecindex", C.c_int),
                ("vecsa", C.POINTER(C.POINTER(VecValues)))]
class VecInfo(C.Structure):
    _fields_ = [("number", C.c_int), ("vecname", C.c_char_p), ("is_real", C.c_bool),
                ("pdvec", C.c_void_p), ("pdvecscale", C.c_void_p)]
class VecInfoAll(C.Structure):
    _fields_ = [("name", C.c_char_p), ("title", C.c_char_p), ("date", C.c_char_p),
                ("type", C.c_char_p), ("veccount", C.c_int),
                ("vecs", C.POINTER(C.POINTER(VecInfo)))]

SENDCHAR = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
EXITCB   = C.CFUNCTYPE(C.c_int, C.c_int, C.c_bool, C.c_bool, C.c_int, C.c_void_p)
SENDDATA = C.CFUNCTYPE(C.c_int, C.POINTER(VecValuesAll), C.c_int, C.c_int, C.c_void_p)
SENDINIT = C.CFUNCTYPE(C.c_int, C.POINTER(VecInfoAll), C.c_int, C.c_void_p)
BGRUN    = C.CFUNCTYPE(C.c_int, C.c_bool, C.c_int, C.c_void_p)
# ngSpice_Init(SendChar, SendStat, ControllerExit, SendData, SendInitData, BGThreadRunning, userdata)
# ngSpice_Circ(char*[] lines, NULL-terminated); ngSpice_Command(b"bg_run" | b"bg_halt" | b"bg_resume" | b"alter r1=100k")
```

Keep the callback objects referenced for the life of the process, or ctypes
frees them under the running thread.
