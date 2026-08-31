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
  getSimPalette,
  getSimProjects,
  getSimScenarios,
  getSimSheets,
  getSimTheme,
  getSketch,
  isAbortError,
  runSimulation,
  saveSketch,
  openSimExample,
  uploadSimSheets,
  type SimGeometry,
  type SimNet,
  type SimProject,
  type SimScenarios,
  type SimSheet,
  type SimSourceRef,
} from "../api";
import { ErrorBanner, Spinner } from "../components/Ui";
import Scope, { type Trace } from "../sim/Scope";
import SimulatorView from "../sim/SimulatorView";
import FieldSolver from "../sim/field/FieldSolver";
import ScenarioPanel from "../sim/ScenarioPanel";
import { FALLBACK_THEME, type LibSymbol, type SchTheme } from "../sim/draw/types";
import { emptyDoc, type PaletteEntry, type SchDoc } from "../sim/edit/doc";
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
  // Two things live under Simulator: the circuit simulation, and the field solver
  // that sizes controlled-impedance traces. ?tab= keeps each one linkable.
  const tab = params.get("tab") === "field" ? "field" : "circuit";

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

  /** The `.control` block to run. Empty means the sheet's own, whatever the
   *  harness does by default. */
  const [control, setControl] = useState("");
  /** The analysis directive to force. Empty leaves the sheet's alone. */
  const [analysis, setAnalysis] = useState("");
  const [scenarios, setScenarios] = useState<SimScenarios | null>(null);
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
  /** Contacts the user has flipped this session, by SPICE instance name. The
   *  netlist's own value is the starting position. */
  const [switchState, setSwitchState] = useState<Record<string, boolean>>({});
  /** The part the knob panel is pointed at, picked on the drawing. */
  const [knob, setKnob] = useState<string | null>(null);
  /** Values altered this session, by SPICE instance name. Held here, not in
   *  the knob panel, because a switch flipped on the DRAWING changes the same
   *  value — and a panel showing the netlist's original figure beside a
   *  circuit that no longer has it is a contradiction the user has to
   *  resolve. */
  const [knobValues, setKnobValues] = useState<Record<string, string>>({});

  // The schematic palette. The same theme file kicad-cli renders the
  // project's schematic tab with, so one circuit never has two colour
  // schemes; the fallback is that theme's own values, not a second palette.
  // Drawing a schematic in the browser. The document is the editor's whole
  // state; `past`/`future` are the undo stack, kept here because leaving the
  // editor and coming back should not lose it.
  const [editing, setEditing] = useState(false);
  /** Bumped when a sketch is saved, so the geometry and the netlist are read
   *  again. The drawing does not wait for it — an editor draws from its own
   *  document — but the READINGS do, and they must never be a save behind. */
  const [revision, setRevision] = useState(0);
  const [sketch, setSketch] = useState<{ past: SchDoc[]; now: SchDoc; future: SchDoc[] } | null>(null);
  const [palette, setPalette] = useState<{
    parts: PaletteEntry[];
    libs: Record<string, LibSymbol>;
    switch: { open: string; closed: string; open_r: string; closed_r: string };
  } | null>(null);
  const [editable, setEditable] = useState(false);

  const [theme, setTheme] = useState<SchTheme>(FALLBACK_THEME);
  useEffect(() => {
    const ctrl = new AbortController();
    getSimTheme(ctrl.signal)
      .then((r) => setTheme({ ...FALLBACK_THEME, ...r.schematic }))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, []);

  // The palette is the parts an empty sheet starts with. Fetched once, and
  // only when the editor is actually wanted.
  useEffect(() => {
    if (!(editing || live) || palette) return;
    const ctrl = new AbortController();
    getSimPalette(ctrl.signal).then(setPalette).catch((e) => {
      if (!isAbortError(e)) setError(errorMessage(e));
    });
    return () => ctrl.abort();
  }, [editing, live, palette]);

  // A source this editor drew can be reopened in it. One that came from KiCad
  // cannot: that file carries tokens the editor does not model, and writing it
  // back from the document would drop them without saying so.
  useEffect(() => {
    setEditable(false);
    if (!uploadId) return;
    const ctrl = new AbortController();
    getSketch(uploadId, ctrl.signal)
      .then((doc) => {
        setEditable(true);
        setSketch((s) => {
          if (s) return s;
          savedDoc.current = JSON.stringify(doc);
          return { past: [], now: doc, future: [] };
        });
      })
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [uploadId]);

  /** One edit. `coalesce` folds a drag or a keystroke into the previous step,
   *  so undo goes back a move rather than a millimetre. */
  const editDoc = useCallback((next: SchDoc, coalesce = false) => {
    setSketch((s) => {
      const now = s?.now ?? emptyDoc();
      const past = coalesce ? (s?.past ?? []) : [...(s?.past ?? []), now].slice(-100);
      return { past, now: next, future: [] };
    });
  }, []);

  const undoDoc = useCallback(() => {
    setSketch((s) => {
      if (!s?.past.length) return s;
      return { past: s.past.slice(0, -1), now: s.past[s.past.length - 1], future: [s.now, ...s.future] };
    });
  }, []);

  const redoDoc = useCallback(() => {
    setSketch((s) => {
      if (!s?.future.length) return s;
      return { past: [...s.past, s.now], now: s.future[0], future: s.future.slice(1) };
    });
  }, []);

  /** The document as last written to disk. Editing and simulating are one
   *  view now, so the file has to follow the drawing without being asked —
   *  but only when it actually changed, or the junction pass alone would
   *  save in a loop. */
  const savedDoc = useRef<string>("");

  useEffect(() => {
    if (!sketch || !editable || !uploadId) return;
    const json = JSON.stringify(sketch.now);
    if (json === savedDoc.current) return;
    // On a pause in typing, not on a keystroke: a save is a netlist and a
    // parse, and nobody wants one per character.
    const timer = setTimeout(() => {
      saveSketch(sketch.now, uploadId)
        .then(() => {
          savedDoc.current = json;
          setRevision((r) => r + 1);
        })
        .catch((e) => setError(errorMessage(e)));
    }, 700);
    return () => clearTimeout(timer);
  }, [sketch, editable, uploadId]);

  /** Start a new drawing. It is saved at once, because a sketch IS an upload
   *  source — that is what gives it nets, a netlist and somewhere to run. */
  const startSketch = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const doc = emptyDoc();
      const saved = await saveSketch(doc);
      savedDoc.current = JSON.stringify(doc);
      setSketch({ past: [], now: doc, future: [] });
      setEditing(true);
      setParams({ upload: saved.id });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }, [setParams]);

  /** Open the worked example. It is stored as an ordinary sketch, so it is
   *  editable and re-runnable the moment it opens — nothing about it is a
   *  read-only demo. */
  const openExample = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const saved = await openSimExample();
      setParams({ upload: saved.id });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }, [setParams]);

  const downloadSketch = useCallback(async () => {
    if (!sketch) return;
    try {
      const saved = await saveSketch(sketch.now, uploadId);
      const blob = new Blob([saved.sch], { type: "application/octet-stream" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = saved.root;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [sketch, uploadId]);

  /** Rebuilt only when something in it changed. A fresh object on every
   *  render re-runs every effect in the editor — thirty times a second while
   *  a live run streams frames, which is enough to take a field away from
   *  someone typing in it. */
  const editProps = useMemo(
    () => (editable && sketch && palette ? {
      doc: sketch.now,
      onChange: editDoc,
      palette: palette.parts,
      libs: palette.libs,
      switchPair: palette.switch,
      onUndo: undoDoc,
      onRedo: redoDoc,
      canUndo: sketch.past.length > 0,
      canRedo: sketch.future.length > 0,
      active: editing,
    } : undefined),
    [editable, sketch, palette, editDoc, undoDoc, redoDoc, editing],
  );

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

  const controlByRef = useMemo(
    () => new Map(controls.map((c) => [c.ref, c])),
    [controls],
  );

  /** The knob panel lists what the DRAWING cannot: a harness source that
   *  lives in a SPICE text block has no symbol to click. A part that does
   *  have one is set in its own inspector, and listing it twice means two
   *  boxes for one number — with the second one showing the netlist's
   *  original value long after the first changed it. */
  const offSheet = useMemo(() => {
    const drawn = new Set((geometry?.symbols ?? []).map((s) => s.spice).filter(Boolean));
    return controls.filter((c) => !drawn.has(c.ref));
  }, [controls, geometry]);

  /** Is this part a contact rather than a component? A switch drawn in the
   *  editor netlists as a resistor (`Sim.Device R`), so the netlist alone
   *  cannot tell one from a real resistor — the reference can. */
  const isSwitch = (ref: string) => ref.toUpperCase().startsWith("SW");
  const closedR = palette?.switch.closed_r ?? "10m";
  const openR = palette?.switch.open_r ?? "1G";

  /** Switches whose live state no longer matches the drawing. The editor's
   *  sheets embed both blade positions, so this is a swap, not a redraw. */
  const partSwap = useMemo(() => {
    const map = new Map<number, string>();
    if (!live || !geometry || !palette) return map;
    for (const sym of geometry.symbols) {
      if (!sym.spice || !isSwitch(sym.ref)) continue;
      const state = switchState[sym.spice];
      if (state === undefined) continue;
      map.set(sym.index, state ? palette.switch.closed : palette.switch.open);
    }
    return map;
  }, [live, geometry, palette, switchState]);

  /** Everything on the drawing a live run can steer. */
  const liveParts = useMemo(() => {
    if (!live || !geometry) return undefined;
    const map = new Map<number, { title: string; kind: string; on?: boolean }>();
    for (const sym of geometry.symbols) {
      if (sym.power || !sym.spice) continue;
      const c = controlByRef.get(sym.spice);
      if (!c) continue;
      if (isSwitch(sym.ref)) {
        const closed = switchState[sym.spice] ?? ((c.numeric ?? 1) < 1e6);
        map.set(sym.index, {
          kind: "switch",
          on: closed,
          title: `${sym.ref} — ${closed ? "closed" : "open"}. Click to ${closed ? "open" : "close"} it.`,
        });
      } else {
        map.set(sym.index, {
          kind: c.kind,
          on: knob === sym.spice,
          title: c.kind === "scripted"
            ? `${sym.ref} runs a ${c.value} waveform — ngspice will not let one be steered mid-run`
            : `${sym.ref} = ${c.value}${c.unit}. Click to put it on the knobs.`,
        });
      }
    }
    return map;
  }, [live, geometry, controlByRef, switchState, knob, palette]);

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

  // The harness is text ON the sheet, so an edit changes what there is to run.
  // Re-read it with the geometry, not once per source.
  useEffect(() => {
    if (!source) return;
    const ctrl = new AbortController();
    getSimScenarios(source, ctrl.signal).then(setScenarios).catch(() => undefined);
    return () => ctrl.abort();
  }, [source, revision]);

  const geometryKey = `${JSON.stringify(source)}|${sheetPath}`;
  const lastGeometryKey = useRef("");
  useEffect(() => {
    if (!source || !sheetPath) return;
    const ctrl = new AbortController();
    // A different sheet starts blank; a re-read after a save keeps the last
    // one on screen, because blanking it would flash the overlay off every
    // time the user stops typing.
    if (lastGeometryKey.current !== geometryKey) {
      setGeometry(null);
      lastGeometryKey.current = geometryKey;
    }
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
  }, [source, sheetPath, revision, geometryKey]);

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

  /** A click on a part, in live mode. A switch flips there and then, because
   *  that is what a switch is for; anything else moves onto the knobs, which
   *  is where a value gets typed. */
  const pickPart = useCallback((index: number) => {
    const sym = geometry?.symbols.find((s) => s.index === index);
    if (!sym) return;
    const c = controlByRef.get(sym.spice);
    if (!c) return;
    if (isSwitch(sym.ref)) {
      const closed = switchState[sym.spice] ?? ((c.numeric ?? 1) < 1e6);
      const next = closed ? openR : closedR;
      setSwitchState((s) => ({ ...s, [sym.spice]: !closed }));
      setKnobValues((v) => ({ ...v, [sym.spice]: next }));
      alter(`alter ${sym.spice} = ${next}`);
    } else {
      setKnob(sym.spice);
    }
  }, [geometry, controlByRef, switchState, alter, openR, closedR]);

  // ------------------------------------------------------------- actions

  const doRun = useCallback(async () => {
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      const buffer = await runSimulation(source, {
        // `null` keeps the sheet's own block; a string replaces it, and an
        // empty string is a run with no control block at all.
        control: control ? control : null,
        analysis,
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
  }, [source, control, analysis, geometry]);

  /** A source the user just opened runs itself, once.
   *
   *  Without it the first screen carries no plot, no readout and no scope —
   *  and clicking a net does nothing VISIBLE, because every measurement reads
   *  from a run that has not happened. That reads as a broken page rather
   *  than as "press Run".
   *
   *  Uploads only: a sketch, the example or a dropped sheet is small and was
   *  opened to be simulated. A snapshot board is left alone — those runs are
   *  long, and a reviewer picks the scenario before spending one. */
  const autoRan = useRef("");
  useEffect(() => {
    if (!source || source.kind !== "upload" || !geometry || busy) return;
    if (autoRan.current === source.uploadId) return;
    autoRan.current = source.uploadId;
    void doRun();
    // doRun is rebuilt whenever the chosen scenario changes; the guard above
    // is what keeps this to one run per source, not the dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, geometry, busy]);

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
      // A derived name is a label the netlist does not know — adding it as a
      // trace would put a row on the scope that can never draw anything.
      if (group?.spice && !group.ground && !group.derived) {
        addTrace(`v(${group.spice})`, net, "V");
      }
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


  const tabBar = (
    <div className="seg proj-tabs" role="tablist" aria-label="Simulator tool">
      <button
        type="button"
        role="tab"
        aria-selected={tab === "circuit"}
        className={tab === "circuit" ? "on" : ""}
        onClick={() => {
          const next = new URLSearchParams(params);
          next.delete("tab");
          setParams(next, { replace: true });
        }}
      >
        Circuit
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={tab === "field"}
        className={tab === "field" ? "on" : ""}
        onClick={() => {
          const next = new URLSearchParams(params);
          next.set("tab", "field");
          setParams(next, { replace: true });
        }}
      >
        Field solver
      </button>
    </div>
  );

  if (tab === "field") {
    return (
      <div className="page page-wide">
        <h1>Simulator</h1>
        {tabBar}
        <FieldSolver />
      </div>
    );
  }

  if (!source) {
    return (
      <div className="page page-wide">
        <h1>Simulator</h1>
        {tabBar}
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
          <hr />
          <p className="muted">
            Or draw one here. It saves as a real <span className="mono">.kicad_sch</span>,
            so the circuit you sketch opens in KiCad afterwards.
          </p>
          <div className="toolbar">
            <button type="button" className="primary" onClick={() => void startSketch()} disabled={busy}>
              {busy ? "Starting…" : "Draw a circuit"}
            </button>
            <button type="button" onClick={() => void openExample()} disabled={busy}>
              Open the example
            </button>
          </div>
          <p className="muted">
            The example is an amplifier, two inverters wired as a buffer, an AND gate and a
            D flip-flop dividing the clock by two. It runs as it opens, so there are
            waveforms to click on straight away — and it is an ordinary drawing, so edit
            it, add to it and run it again.
          </p>
        </div>
      </div>
    );
  }

  const drawnSheet = sheets?.find((s) => s.path === sheetPath);

  return (
    <div className="page page-wide">
      <h1>Simulator</h1>
      {tabBar}
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
        {editable ? (
          <>
            <button
              type="button"
              className={editing ? "on" : ""}
              onClick={() => setEditing((v) => !v)}
              title="Change the circuit without leaving the simulation"
            >
              Edit
            </button>
            {editing ? (
              <button type="button" onClick={() => void downloadSketch()}>
                Download .kicad_sch
              </button>
            ) : null}
          </>
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
        {/* What to run, and what it said, live below the drawing in their
            own panel — a scenario is a menu, not two words on a toolbar. */}
        {/* A drawing has no page to fit to and no page to show whole: it opens
            on a working window and the wheel does the rest. */}
        {editable ? null : (
          <div className="seg" role="group" aria-label="View">
            <button type="button" className={fit ? "on" : ""} onClick={() => setFit(true)}>
              Fit circuit
            </button>
            <button type="button" className={!fit ? "on" : ""} onClick={() => setFit(false)}>
              Whole sheet
            </button>
          </div>
        )}
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
            {plot.scale.length > 1 ? (
              <button type="button" onClick={() => setPlaying((p) => !p)}>
                {playing ? "Pause" : "Play"}
              </button>
            ) : null}
            <span className="pill neutral">{plot.name}</span>
            <span className="muted">
              {plot.scale.length === 1
                ? "a single solution"
                : `${plot.scale.length} points · ${eng(
                    duration,
                    plot.scaleType === "time" ? "s" : "Hz",
                  )}`}
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
          <SimulatorView
            geometry={geometry}
            theme={theme}
            fit={fit}
            reader={reader}
            clock={clock}
            running={playing || live}
            voltageRange={voltageRange}
            currentPeak={currentPeak}
            selectedNet={selectedNet}
            onPickNet={pickNet}
            parts={liveParts}
            onPickPart={pickPart}
            partSwap={partSwap}
            onUnresolved={setUnresolved}
            onAlter={live ? alter : undefined}
            edit={editProps}
          />

          {live ? (
            <LiveControls
              state={liveState}
              controls={offSheet}
              focus={knob}
              values={knobValues}
              onValues={setKnobValues}
              onAlter={alter}
              log={alterLog}
              text={alterText}
              onText={setAlterText}
            />
          ) : null}

          {!live ? (
            <ScenarioPanel
              scenarios={scenarios}
              control={control}
              onControl={setControl}
              analysis={analysis}
              onAnalysis={setAnalysis}
              log={run?.header.log ?? ""}
              busy={busy}
              onRun={() => void doRun()}
            />
          ) : null}

          {!live && plot ? (
            <div className="card pad">
              {plot.scale.length > 1 ? (
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
              ) : null}
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
  focus,
  state,
  controls,
  values,
  onValues,
  onAlter,
  log,
  text,
  onText,
}: {
  /** The part picked on the drawing. Its knob is highlighted and focused, so
   *  clicking a resistor in the circuit puts the cursor in its value box. */
  focus: string | null;
  state: LiveState | null;
  controls: LiveControl[];
  /** Values altered this session, by ref. Owned by the page — a contact
   *  flipped on the drawing changes one of these too. */
  values: Record<string, string>;
  onValues: (next: (v: Record<string, string>) => Record<string, string>) => void;
  onAlter: (command: string) => void;
  log: string[];
  text: string;
  onText: (value: string) => void;
}) {
  const setValues = onValues;
  const nothingOffSheet = controls.length === 0;
  /** Which knob has already been given the cursor. A ref callback runs on
   *  EVERY render, and a live run renders thirty times a second — focusing
   *  from one would take the cursor back off whatever the user moved it to,
   *  continuously. Focus follows a CHANGE of pick, once. */
  const focusedOnce = useRef<string | null>(null);
  useEffect(() => { focusedOnce.current = null; }, [focus]);
  const takeFocus = (el: HTMLInputElement | null, ref: string) => {
    if (!el || focus !== ref || focusedOnce.current === ref) return;
    focusedOnce.current = ref;
    el.focus();
  };
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
      {nothingOffSheet ? (
        <p className="muted">
          Every part in this circuit is on the drawing — click one to set it there.
          This panel is for what the drawing cannot show: a source that lives in a
          SPICE text block has no symbol to click.
        </p>
      ) : null}
      {sources.length ? (
        <>
          <p className="muted">
            Sources. A switch driven by a control node is a source too, so this is where a
            contact is thrown.
          </p>
          <div className="sim-knobs">
            {sources.map((c) => (
              <label key={c.ref} className={`sim-knob${focus === c.ref ? " on" : ""}`}>
                <span className="mono">{c.ref}</span>
                <input
                  className="text"
                  ref={(el) => takeFocus(el, c.ref)}
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
              <label key={c.ref} className={`sim-knob${focus === c.ref ? " on" : ""}`}>
                <span className="mono">{c.ref}</span>
                <input
                  className="text"
                  ref={(el) => takeFocus(el, c.ref)}
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
