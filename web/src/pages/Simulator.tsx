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
  getSimSheets,
  isAbortError,
  runSimulation,
  simSheetSvgUrl,
  uploadSimSheets,
  type SimGeometry,
  type SimNet,
  type SimSheet,
  type SimSourceRef,
} from "../api";
import { ErrorBanner, Spinner } from "../components/Ui";
import Scope, { type Trace } from "../sim/Scope";
import SimSheetView from "../sim/SimSheetView";
import {
  decodeSimPayload,
  eng,
  peakMagnitude,
  vectorRange,
  type SimPlot,
  type SimRun,
} from "../sim/payload";

/** How long one replay of a whole run takes, in seconds of wall clock. */
const REPLAY_SECONDS = 5;

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

  const [sample, setSample] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [clock, setClock] = useState(0);

  const plot: SimPlot | null = run?.plots[0] ?? null;

  // ------------------------------------------------------------- loading

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
        // The deepest sheet is the one with a circuit on it; a root that only
        // holds sub-sheet boxes has nothing to draw.
        const drawn = [...r.sheets].sort((a, b) => b.depth - a.depth)[0];
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

  // ------------------------------------------------------------- actions

  const doRun = useCallback(async () => {
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      const buffer = await runSimulation(source, {
        sheet: sheetPath,
        control: useOwnScenario ? null : "",
        analysis: useOwnScenario ? "" : analysis,
      });
      const decoded = decodeSimPayload(buffer);
      setRun(decoded);
      setSample(0);
      setClock(0);
      setPlaying(true);
      // Something must be on the scope, or the first run looks like nothing
      // happened. The first non-ground node voltage is a fair guess.
      const first = decoded.plots[0]?.vectors.find((v) => v.kind === "v");
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
  }, [source, sheetPath, useOwnScenario, analysis, geometry]);

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

  const voltageRange = useMemo(
    () => (plot ? vectorRange(plot.voltages.values()) : { min: -1, max: 1 }),
    [plot],
  );
  const currentPeak = useMemo(() => (plot ? peakMagnitude(plot.currents.values()) : 0), [plot]);

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
        {sheets && sheets.length > 1 ? (
          <div className="seg" role="group" aria-label="Sheets">
            {sheets.map((s) => (
              <button
                key={s.path}
                type="button"
                className={s.path === sheetPath ? "on" : ""}
                onClick={() => setSheetPath(s.path)}
                title={s.path}
              >
                {"· ".repeat(s.depth)}
                {s.name}
              </button>
            ))}
          </div>
        ) : null}
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
        {!useOwnScenario ? (
          <input
            className="row-input"
            value={analysis}
            onChange={(e) => setAnalysis(e.target.value)}
            aria-label="Analysis directive"
          />
        ) : null}
        <button type="button" className="primary" onClick={() => void doRun()} disabled={busy}>
          {busy ? "Running…" : "Run"}
        </button>
        <div className="seg" role="group" aria-label="View">
          <button type="button" className={fit ? "on" : ""} onClick={() => setFit(true)}>
            Fit circuit
          </button>
          <button type="button" className={!fit ? "on" : ""} onClick={() => setFit(false)}>
            Whole sheet
          </button>
        </div>
        {plot ? (
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

      {busy && !geometry ? <Spinner label="Reading the schematic" /> : null}

      {geometry ? (
        <>
          <SimSheetView
            geometry={geometry}
            fit={fit}
            svgUrl={simSheetSvgUrl(source, sheetPath)}
            plot={plot}
            sample={sample}
            clock={clock}
            running={playing}
            voltageRange={voltageRange}
            currentPeak={currentPeak}
            selectedNet={selectedNet}
            onPickNet={pickNet}
            onUnresolved={setUnresolved}
          />

          {plot ? (
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
              <div className="sim-nets">
                {nets.map((n) => (
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
      {unresolved.map((u) => (
        <p key={u.net} className="muted">
          No charge is drawn on <strong>{u.net}</strong>: {u.reason}.
        </p>
      ))}
      {geometry.warnings.map((w) => (
        <p key={w} className="muted">
          {sheetName}: {w}
        </p>
      ))}
    </div>
  );
}
