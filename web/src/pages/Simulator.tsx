/** Circuit simulator: a schematic with its own simulation drawn on top.
 *
 *  A source is either a board's schematic at an ingested commit (linked from
 *  the project schematic tab) or a sheet set dropped here from KiCad. Both run
 *  the same way: kicad-cli flattens the hierarchy and resolves the Sim.*
 *  fields, ngspice runs the scenario the schematic itself carries, and the
 *  result is drawn back onto the drawing — node voltages as colour, current as
 *  moving charge.
 *
 *  This is the SCENARIO mode: a finite run, returned whole, which the page
 *  replays and scrubs. Live continuous simulation is a separate mode and is
 *  not built yet (docs/simulator/design.md).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  errorMessage,
  getSimGeometry,
  getSimNetlist,
  getSimProjects,
  getSimSheets,
  isAbortError,
  runSimulation,
  simSheetSvgUrl,
  uploadSimSheets,
  type SimGeometry,
  type SimNet,
  type SimProject,
  type SimSheet,
  type SimSourceRef,
} from "../api";
import { ErrorBanner, Spinner } from "../components/Ui";
import Scope, { type Trace } from "../sim/Scope";
import SimSheetView from "../sim/SimSheetView";
import { LiveSession, liveControls, type LiveControl, type LiveState } from "../sim/live";
import {
  decodeSimPayload,
  eng,
  liveReader,
  liveliest,
  peakMagnitude,
  plotReader,
  vectorRange,
  type SimPlot,
  type SimRun,
} from "../sim/payload";

/** How long one replay of a whole run takes, in seconds of wall clock. */
const REPLAY_SECONDS = 5;

/** KiCad's name for a pin nobody wired. They are real nets to the netlister
 *  and noise to a reader — a board sheet can carry more of them than it has
 *  circuit nets. */
const isUnconnected = (n: SimNet): boolean => n.name.startsWith("unconnected-");

export default function Simulator() {
  const [params, setParams] = useSearchParams();
  const snapshotId = Number(params.get("snapshot") || 0);
  const board = params.get("board") || "";
  const uploadId = params.get("upload") || "";

  const source: SimSourceRef | null = useMemo(() => {
    if (snapshotId && board) return { kind: "snapshot", snapshotId, board };
    if (uploadId) return { kind: "upload", uploadId };
    return null;
  }, [snapshotId, board, uploadId]);

  const [projects, setProjects] = useState<SimProject[] | null>(null);
  const [sheets, setSheets] = useState<SimSheet[] | null>(null);
  const [sheetPath, setSheetPath] = useState<string>("");
  const [geometry, setGeometry] = useState<SimGeometry | null>(null);
  const [nets, setNets] = useState<SimNet[] | null>(null);
  const [netlist, setNetlist] = useState<string>("");
  const [showNetlist, setShowNetlist] = useState(false);
  const [run, setRun] = useState<SimRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unresolved, setUnresolved] = useState<{ net: string; reason: string }[]>([]);

  const [useOwnScenario, setUseOwnScenario] = useState(true);
  const [analysis, setAnalysis] = useState(".tran 10u 5m");
  const [traces, setTraces] = useState<Trace[]>([]);
  const [selectedNet, setSelectedNet] = useState<string | null>(null);
  const [fit, setFit] = useState(true);
  const [showUnconnected, setShowUnconnected] = useState(false);

  const [sample, setSample] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [clock, setClock] = useState(0);

  // Live mode: an endless run, streamed, that you change while it runs.
  const [live, setLive] = useState(false);
  const [liveState, setLiveState] = useState<LiveState | null>(null);
  const [liveSpeed, setLiveSpeed] = useState(1e-3);
  const session = useRef<LiveSession | null>(null);
  const [alterText, setAlterText] = useState("");
  const [alterLog, setAlterLog] = useState<string[]>([]);

  const plot: SimPlot | null = run?.plots[0] ?? null;

  /** Vector names the live overlay needs: every net drawn on this sheet, plus
   *  a device current per part on it. Capped — a frame carries one float per
   *  entry, thirty times a second. */
  const liveVectors = useMemo(() => {
    if (!geometry) return [] as string[];
    const names: string[] = [];
    for (const g of geometry.groups) {
      if (g.spice && !g.ground && !g.derived) names.push(`v(${g.spice})`);
    }
    for (const sym of geometry.symbols) {
      if (!sym.power && sym.ref) names.push(`i(@${sym.ref.toLowerCase()}[i])`);
    }
    return names.slice(0, 400);
  }, [geometry]);

  const liveIndex = useMemo(
    () => new Map(liveVectors.map((name, i) => [name, i])),
    [liveVectors],
  );

  const controls: LiveControl[] = useMemo(
    () => (netlist ? liveControls(netlist) : []),
    [netlist],
  );

  // ------------------------------------------------------------- loading

  // A design repository keeps one simulation project per block — CP_sim,
  // SAFETY_sim, TEMP_sim beside the board itself. Offer them, and open one
  // rather than the board, which carries no harness and cannot simulate.
  useEffect(() => {
    if (!snapshotId) return;
    const ctrl = new AbortController();
    getSimProjects(snapshotId, ctrl.signal)
      .then((r) => {
        setProjects(r.projects);
        if (board) return;
        const pick = r.projects.find((x) => x.simulation) ?? r.projects[0];
        if (pick) setParams({ snapshot: String(snapshotId), board: pick.board }, { replace: true });
      })
      .catch(() => setProjects(null));
    return () => ctrl.abort();
  }, [snapshotId, board, setParams]);

  useEffect(() => {
    if (!source) return;
    const ctrl = new AbortController();
    setSheets(null);
    setGeometry(null);
    setRun(null);
    setError(null);
    getSimSheets(source, ctrl.signal)
      .then((r) => {
        setSheets(r.sheets);
        // Open the sheet with the most on it. A harness root is a page of
        // SPICE text around one sheet box, and the leaves are single channels
        // — so neither "first" nor "deepest" finds the circuit under test.
        const drawn = [...r.sheets].sort((a, b) => b.symbols - a.symbols)[0];
        setSheetPath(drawn?.path ?? "");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [source]);

  useEffect(() => {
    if (!source || !sheetPath) return;
    const ctrl = new AbortController();
    setGeometry(null);
    getSimGeometry(source, sheetPath, ctrl.signal)
      .then(setGeometry)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getSimNetlist(source, ctrl.signal)
      .then((r) => {
        setNets(r.nets);
        setNetlist(r.spice);
      })
      .catch(() => setNets(null)); // the net list is an aid, never a blocker
    return () => ctrl.abort();
  }, [source, sheetPath]);

  // --------------------------------------------------------------- replay

  const scale = plot?.scale;
  const duration = scale && scale.length > 1 ? scale[scale.length - 1] - scale[0] : 0;
  const frame = useRef<number>(0);
  const last = useRef<number>(0);

  useEffect(() => {
    if (!playing || !scale || scale.length < 2) return;
    last.current = performance.now();
    const step = (now: number) => {
      const dt = Math.min(0.1, (now - last.current) / 1000);
      last.current = now;
      setClock((c) => c + dt);
      setSample((s) => {
        const advance = Math.max(1, Math.round((scale.length / REPLAY_SECONDS) * dt));
        return (s + advance) % scale.length;
      });
      frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [playing, scale]);

  // Open and close the live session. Changing sheet or project tears it down:
  // the overlay it feeds belongs to one drawing.
  useEffect(() => {
    if (!live || !source || !geometry || !liveVectors.length) return;
    const target =
      source.kind === "snapshot"
        ? { kind: "snapshot", snapshot_id: source.snapshotId, board: source.board }
        : { kind: "upload", upload_id: source.uploadId };
    const s = new LiveSession(
      { target, overlay: liveVectors, scopes: [], speed: liveSpeed, tstep: 1e-5 },
      setLiveState,
    );
    session.current = s;
    s.start();
    return () => {
      s.stop();
      session.current = null;
      setLiveState(null);
    };
    // liveSpeed is steered through the session, not by reconnecting.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, source, geometry, liveVectors]);

  const alter = useCallback((command: string) => {
    session.current?.alter(command);
    setAlterLog((l) => [command, ...l].slice(0, 8));
  }, []);

  // ------------------------------------------------------------- actions

  const doRun = useCallback(async () => {
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      const buffer = await runSimulation(source, {
        control: useOwnScenario ? null : "",
        analysis: useOwnScenario ? "" : analysis,
      });
      const decoded = decodeSimPayload(buffer);
      setRun(decoded);
      setSample(0);
      setClock(0);
      setPlaying(true);
      // Something must be on the scope, or the first run looks like nothing
      // happened — and it has to be a node that MOVES. The first vector of a
      // real board is usually a supply rail, which plots as a flat line.
      const plot0 = decoded.plots[0];
      const first = plot0 ? liveliest(plot0) : null;
      if (first) {
        // Label it the way the drawing spells it — the vector's own key is the
        // lower-cased SPICE node, which is not what the sheet says.
        const named = geometry?.groups.find((g) => g.spice === first.key);
        setTraces([{ name: first.name, label: named?.net ?? first.key, unit: "V" }]);
      }
    } catch (err) {
      if (!isAbortError(err)) setError(errorMessage(err));
      setRun(null);
    } finally {
      setBusy(false);
    }
  }, [source, useOwnScenario, analysis, geometry]);

  const onUpload = async (files: FileList | null) => {
    if (!files || !files.length) return;
    setBusy(true);
    setError(null);
    try {
      const meta = await uploadSimSheets(Array.from(files));
      setParams({ upload: meta.id });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const addTrace = useCallback((name: string, label: string, unit: string) => {
    setTraces((current) =>
      current.some((t) => t.name === name) ? current : [...current, { name, label, unit }],
    );
  }, []);

  const pickNet = useCallback(
    (net: string | null) => {
      setSelectedNet(net);
      if (!net || !geometry) return;
      const group = geometry.groups.find((g) => g.net === net);
      if (group?.spice && !group.ground) addTrace(`v(${group.spice})`, net, "V");
    },
    [geometry, addTrace],
  );

  const reader = useMemo(() => {
    if (live) {
      return liveState && liveState.status !== "connecting"
        ? liveReader(liveState.simTime, liveState.values, liveIndex)
        : null;
    }
    return plot ? plotReader(plot, sample) : null;
  }, [live, liveState, liveIndex, plot, sample]);

  const voltageRange = useMemo(
    () => (plot ? vectorRange(plot.voltages.values()) : { min: -24, max: 24 }),
    [plot],
  );
  const currentPeak = useMemo(
    () => (plot ? peakMagnitude(plot.currents.values()) : 1e-3),
    [plot],
  );

  // ------------------------------------------------------------------ ui

  if (!source) {
    return (
      <div className="page">
        <h1>Simulator</h1>
        <div className="card pad">
          <p className="muted">
            Drop a schematic to simulate it. Send the sheet you want, every sub-sheet it
            uses, and any model file it references next to itself — the netlist resolves
            those relative to the sheet.
          </p>
          <input
            type="file"
            multiple
            accept=".kicad_sch,.kicad_pro,.lib,.sp,.cir,.mod,.sub,.txt"
            onChange={(e) => void onUpload(e.target.files)}
          />
          {busy ? <Spinner label="Uploading" /> : null}
          {error ? <ErrorBanner message={error} /> : null}
          <p className="muted">
            A board already on the platform opens from its project — the schematic tab has
            a Simulate button.
          </p>
        </div>
      </div>
    );
  }

  const drawnSheet = sheets?.find((s) => s.path === sheetPath);

  return (
    <div className="page">
      <h1>Simulator</h1>
      {error ? <ErrorBanner message={error} /> : null}

      <div className="toolbar">
        {/* A dropdown, not a row of buttons: a repository has as many
            simulation blocks as it likes, and a toolbar that grows with the
            data pushes the page sideways. */}
        {projects && projects.length > 1 ? (
          <label className="sim-pick-group">
            <span>Simulation</span>
            <select
              className="text"
              value={board}
              onChange={(e) => setParams({ snapshot: String(snapshotId), board: e.target.value })}
            >
              {projects
                .filter((x) => x.has_schematic)
                .map((x) => (
                  <option key={x.board} value={x.board}>
                    {x.board}
                    {x.simulation ? " · harness" : ""}
                  </option>
                ))}
            </select>
          </label>
        ) : null}
        {sheets && sheets.length > 1 ? (
          <label className="sim-pick-group">
            <span>Sheet</span>
            <select
              className="text"
              value={sheetPath}
              onChange={(e) => setSheetPath(e.target.value)}
              title="What to LOOK at. A run always covers the whole project."
            >
              {sheets.map((s) => (
                <option key={s.path} value={s.path}>
                  {"\u00a0\u00a0".repeat(s.depth)}
                  {s.name} · {s.symbols} parts
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="seg" role="group" aria-label="Mode">
          <button
            type="button"
            className={!live ? "on" : ""}
            onClick={() => setLive(false)}
            title="Run the scenario once and replay it"
          >
            Scenario
          </button>
          <button
            type="button"
            className={live ? "on" : ""}
            onClick={() => setLive(true)}
            title="Run without end and change the circuit while it runs"
          >
            Live
          </button>
        </div>
        {live ? null : (
        <div className="seg" role="group" aria-label="Scenario">
          <button
            type="button"
            className={useOwnScenario ? "on" : ""}
            onClick={() => setUseOwnScenario(true)}
            title="Run the directives the schematic itself carries"
          >
            Sheet scenario
          </button>
          <button
            type="button"
            className={!useOwnScenario ? "on" : ""}
            onClick={() => setUseOwnScenario(false)}
          >
            Transient
          </button>
        </div>
        )}
        {!live && !useOwnScenario ? (
          <input
            className="row-input"
            value={analysis}
            onChange={(e) => setAnalysis(e.target.value)}
            aria-label="Analysis directive"
          />
        ) : null}
        {live ? null : (
          <button type="button" className="primary" onClick={() => void doRun()} disabled={busy}>
            {busy ? "Running…" : "Run"}
          </button>
        )}
        <div className="seg" role="group" aria-label="View">
          <button type="button" className={fit ? "on" : ""} onClick={() => setFit(true)}>
            Fit circuit
          </button>
          <button type="button" className={!fit ? "on" : ""} onClick={() => setFit(false)}>
            Whole sheet
          </button>
        </div>
        {live ? (
          <>
            <button
              type="button"
              onClick={() => {
                if (liveState?.status === "halted") session.current?.resume();
                else session.current?.halt();
              }}
              disabled={!liveState || liveState.status === "connecting"}
            >
              {liveState?.status === "halted" ? "Resume" : "Hold"}
            </button>
            <label className="sim-pick-group">
              <span>Speed</span>
              <select
                className="text"
                value={String(liveSpeed)}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setLiveSpeed(v);
                  session.current?.setSpeed(v);
                }}
              >
                {[1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1].map((v) => (
                  <option key={v} value={String(v)}>
                    {eng(v, "s")} per second
                  </option>
                ))}
              </select>
            </label>
            <span className="pill neutral">
              {liveState?.status ?? "connecting"}
            </span>
            {liveState ? (
              <span className="muted">
                t = {eng(liveState.simTime, "s")} · {liveState.pointsPerSecond} points/s
              </span>
            ) : null}
          </>
        ) : null}
        {!live && plot ? (
          <>
            <button type="button" onClick={() => setPlaying((p) => !p)}>
              {playing ? "Pause" : "Play"}
            </button>
            <span className="pill neutral">{plot.name}</span>
            <span className="muted">
              {plot.scale.length} points · {eng(duration, plot.scaleType === "time" ? "s" : "Hz")}
              {plot.decimated ? " · decimated to a min/max envelope" : ""}
            </span>
          </>
        ) : null}
      </div>

      {projects && board && !projects.find((x) => x.board === board)?.simulation
        && projects.some((x) => x.simulation) ? (
        <p className="muted">
          {board} carries no simulation directives — it is the design, not a harness.
          The projects marked · above are the simulation blocks:{" "}
          {projects.filter((x) => x.simulation).map((x) => x.board).join(", ")}.
        </p>
      ) : null}

      {busy && !geometry ? <Spinner label="Reading the schematic" /> : null}

      {geometry ? (
        <>
          <SimSheetView
            geometry={geometry}
            fit={fit}
            svgUrl={simSheetSvgUrl(source, sheetPath)}
            reader={reader}
            clock={clock}
            running={playing || live}
            voltageRange={voltageRange}
            currentPeak={currentPeak}
            selectedNet={selectedNet}
            onPickNet={pickNet}
            onUnresolved={setUnresolved}
          />

          {live ? (
            <LiveControls
              state={liveState}
              controls={controls}
              onAlter={alter}
              log={alterLog}
              text={alterText}
              onText={setAlterText}
            />
          ) : null}

          {!live && plot ? (
            <div className="card pad">
              <input
                type="range"
                min={0}
                max={Math.max(0, plot.scale.length - 1)}
                value={sample}
                onChange={(e) => {
                  setPlaying(false);
                  setSample(Number(e.target.value));
                }}
                aria-label="Position in the run"
                className="sim-scrub"
              />
              <Scope
                plot={plot}
                traces={traces}
                sample={sample}
                onScrub={(s) => {
                  setPlaying(false);
                  setSample(s);
                }}
                onRemove={(name) => setTraces((t) => t.filter((x) => x.name !== name))}
              />
            </div>
          ) : null}

          <SimNotices
            geometry={geometry}
            run={run}
            unresolved={unresolved}
            sheetName={drawnSheet?.name ?? ""}
          />

          {nets ? (
            <div className="card pad">
              <div className="card-title">Nets</div>
              {/* `unconnected-(U47-A0-Pad2)` is KiCad naming a pin nobody
                  wired. On a real board they outnumber the real nets and
                  bury them. */}
              {nets.some(isUnconnected) ? (
                <p className="muted">
                  <button type="button" onClick={() => setShowUnconnected((v) => !v)}>
                    {showUnconnected ? "Hide" : "Show"} {nets.filter(isUnconnected).length}{" "}
                    unconnected pins
                  </button>
                </p>
              ) : null}
              <div className="sim-nets">
                {nets.filter((n) => showUnconnected || !isUnconnected(n)).map((n) => (
                  <button
                    key={n.code || n.name}
                    type="button"
                    className={`pill ${n.ground ? "neutral" : "info"}`}
                    onClick={() => (n.ground ? undefined : addTrace(`v(${n.spice})`, n.name, "V"))}
                    disabled={n.ground}
                    title={n.ground ? "Ground is node 0 — always 0 V" : `Plot ${n.name}`}
                  >
                    {n.name}
                  </button>
                ))}
              </div>
              <button type="button" onClick={() => setShowNetlist((s) => !s)}>
                {showNetlist ? "Hide" : "Show"} the SPICE netlist
              </button>
              {showNetlist ? <pre className="mono sim-netlist">{netlist}</pre> : null}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

/** The knobs a live run answers to.
 *
 *  Every one of these is an ngspice `alter` on the running circuit, which is
 *  how a switch is thrown here. A switch modelled with a control node is
 *  driven by a source, so toggling a contact and changing a supply are the
 *  same operation — which is why sources come first and are not separated
 *  from "switches" by any guesswork about what a part represents.
 */
function LiveControls({
  state,
  controls,
  onAlter,
  log,
  text,
  onText,
}: {
  state: LiveState | null;
  controls: LiveControl[];
  onAlter: (command: string) => void;
  log: string[];
  text: string;
  onText: (value: string) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const sources = controls.filter((c) => c.kind === "source");
  const passives = controls.filter((c) => c.kind === "passive");
  const scripted = controls.filter((c) => c.kind === "scripted");
  const busy = !state || state.status === "connecting" || state.status === "error";

  const apply = (c: LiveControl, raw: string) => {
    setValues((v) => ({ ...v, [c.ref]: raw }));
    if (raw.trim()) onAlter(`alter ${c.ref} = ${raw.trim()}`);
  };

  return (
    <div className="card pad">
      <div className="card-title">Change it while it runs</div>
      {state?.message ? <p className="muted">{state.message}</p> : null}
      {sources.length ? (
        <>
          <p className="muted">
            Sources. A switch driven by a control node is a source too, so this is where a
            contact is thrown.
          </p>
          <div className="sim-knobs">
            {sources.map((c) => (
              <label key={c.ref} className="sim-knob">
                <span className="mono">{c.ref}</span>
                <input
                  className="text"
                  value={values[c.ref] ?? c.value}
                  disabled={busy}
                  onChange={(e) => setValues((v) => ({ ...v, [c.ref]: e.target.value }))}
                  onBlur={(e) => apply(c, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") apply(c, (e.target as HTMLInputElement).value);
                  }}
                />
                <span className="muted">{c.unit}</span>
                <button type="button" disabled={busy} onClick={() => apply(c, "0")}>
                  0
                </button>
              </label>
            ))}
          </div>
        </>
      ) : null}
      {passives.length ? (
        <>
          <p className="muted">
            Passives. Opening a contact is a big resistance and closing it is a small one —
            `1e9` and `1m` are the two ends.
          </p>
          <div className="sim-knobs">
            {passives.slice(0, 40).map((c) => (
              <label key={c.ref} className="sim-knob">
                <span className="mono">{c.ref}</span>
                <input
                  className="text"
                  value={values[c.ref] ?? c.value}
                  disabled={busy}
                  onChange={(e) => setValues((v) => ({ ...v, [c.ref]: e.target.value }))}
                  onBlur={(e) => apply(c, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") apply(c, (e.target as HTMLInputElement).value);
                  }}
                />
                <span className="muted">{c.unit}</span>
              </label>
            ))}
            {passives.length > 40 ? (
              <span className="muted">and {passives.length - 40} more — use the box below</span>
            ) : null}
          </div>
        </>
      ) : null}
      {scripted.length ? (
        <p className="muted">
          Driven by the harness, and not steerable while the run continues:{" "}
          <span className="mono">{scripted.map((c) => c.ref).join(", ")}</span>. ngspice keeps
          a source's waveform whatever you alter it to. To take one over, raise the series
          resistor the harness put in its path — that is what it is for — and drive the node
          from a source of your own.
        </p>
      ) : null}
      <p className="muted">
        Anything else, in ngspice's own words. A pole inside a subcircuit takes the
        hierarchical form: <span className="mono">alter @r.xu28.rs1[resistance] = 1e9</span>.
      </p>
      <div className="sim-knobs">
        <input
          className="text sim-alter"
          value={text}
          disabled={busy}
          placeholder="alter v3v3 = 3.3"
          onChange={(e) => onText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && text.trim()) {
              onAlter(text.trim());
              onText("");
            }
          }}
        />
        <button
          type="button"
          disabled={busy || !text.trim()}
          onClick={() => {
            onAlter(text.trim());
            onText("");
          }}
        >
          Apply
        </button>
      </div>
      {log.length ? (
        <p className="muted mono">{log.join("  ·  ")}</p>
      ) : null}
    </div>
  );
}

function SimNotices({
  geometry,
  run,
  unresolved,
  sheetName,
}: {
  geometry: SimGeometry;
  run: SimRun | null;
  unresolved: { net: string; reason: string }[];
  sheetName: string;
}) {
  const unmodelled = run?.header.unmodelled ?? [];
  if (!geometry.warnings.length && !unmodelled.length && !unresolved.length) return null;
  return (
    <div className="card pad">
      <div className="card-title">What this run does not show</div>
      {unmodelled.length ? (
        <p>
          <span className="pill warn">not simulated</span>{" "}
          {unmodelled.join(", ")} — these parts carry no simulation model, so they were
          left out of the circuit entirely. Everything around them ran without them.
        </p>
      ) : null}
      {unresolved.length ? (
        <p className="muted">
          No charge is drawn on {unresolved.length === 1 ? "one net" : `${unresolved.length} nets`}
          {" — "}
          {unresolved.slice(0, 6).map((u) => u.net).join(", ")}
          {unresolved.length > 6 ? `, and ${unresolved.length - 6} more` : ""}. A net needs all
          but one of its terminal currents to be known before the split between its wires can
          be worked out, and a subcircuit does not report the current at its pins.
        </p>
      ) : null}
      {geometry.warnings.map((w) => (
        <p key={w} className="muted">
          {sheetName}: {w}
        </p>
      ))}
    </div>
  );
}
