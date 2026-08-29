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

### 3.2 Live mode (endless)

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
itself. Conventions and the traps behind them are in `web/CLAUDE.md`.

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

### Slice 4 — later, in this order

- Scenario library UI (pick among several `.control` text items, per-sheet).
- Editing in the web renderer, writing `.kicad_sch` back (`parse_sexpr` lists
  re-serialised, never kiutils objects, so unknown nodes survive).
- Placing parts from the platform library with `Sim.*` already attached.
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
