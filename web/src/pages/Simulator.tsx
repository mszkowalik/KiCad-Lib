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
import { useStickyState } from "../useStickyState";
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
import Plots from "../sim/Plots";
import { netlistDoc, type DocNetlist } from "../sim/edit/netlist";
import {
  pinTrace, probeOf, probeTerms, readProbe, solveProbeSeries, solveSegmentCurrents, wireTrace,
  type Probe,
} from "../sim/currents";
import { addTrace as addToPanes, paneId, type Pane, type PlotData } from "../sim/panes";
import SimulatorView from "../sim/SimulatorView";
import FieldSolver from "../sim/field/FieldSolver";
import RunBar from "../sim/RunBar";
import Verdicts from "../sim/Verdicts";
import Disclosure from "../sim/Disclosure";
import { readVerdicts } from "../sim/scenario";
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

/** Is this part a contact rather than a component? A switch drawn in the
 *  editor netlists as a resistor (`Sim.Device R`), so the netlist alone
 *  cannot tell one from a real resistor — the reference can. Outside the
 *  component: a new function every render would defeat every memo that
 *  depends on it. */
/** How much WALL clock a live scope shows, and in how many columns. The
 *  worker caps its own history at the same number. */
/** The charge-dot speed knob. Slider 0..100 -> a multiple of the default,
 *  logarithmically, with 1x in the middle and 0 meaning stopped. Logarithmic
 *  because the useful range is a factor of sixty and a linear slider spends
 *  four fifths of its travel above "too fast to follow". */
const CURRENT_SLIDER_MID = 50;
const CURRENT_SLIDER_DECADE = 16.6;

function currentSpeedOf(slider: number): number {
  if (slider <= 0) return 0;
  return 2 ** ((slider - CURRENT_SLIDER_MID) / CURRENT_SLIDER_DECADE);
}

/** What a live run's scale starts at, before it has seen anything. Small, so
 *  the first frame sets it rather than being lost inside it. */
const LIVE_SCALE_START = { min: -1, max: 1, peak: 1e-6 };

const LIVE_WINDOW_S = 4;
const LIVE_COLUMNS = 600;

const isSwitch = (ref: string) => ref.toUpperCase().startsWith("SW");

export default function Simulator() {
  const [params, setParams] = useSearchParams();
  const snapshotId = Number(params.get("snapshot") || 0);
  const board = params.get("board") || "";
  const uploadId = params.get("upload") || "";
  /** `?mode=live` (a project's Play-live button) or `?mode=scenario`. A
   *  sketch defaults to live; a project sheet to scenario. */
  const modeParam = params.get("mode") || "";
  // Two things live under Simulator: the circuit simulation, and the field solver
  // that sizes controlled-impedance traces. ?tab= keeps each one linkable.
  const tab = params.get("tab") === "field" ? "field" : "circuit";

  const source: SimSourceRef | null = useMemo(() => {
    if (snapshotId && board) return { kind: "snapshot", snapshotId, board };
    if (uploadId) return { kind: "upload", uploadId };
    return null;
  }, [snapshotId, board, uploadId]);
  /** One key per circuit for the remembered measurement setup — a refresh (or
   *  a return to the same sheet) restores the scope as it was, per source. */
  const sourceKey = snapshotId && board ? `snap:${snapshotId}:${board}` : uploadId ? `up:${uploadId}` : "none";

  const [projects, setProjects] = useState<SimProject[] | null>(null);
  const [sheets, setSheets] = useState<SimSheet[] | null>(null);
  const [sheetPath, setSheetPath] = useState<string>("");
  const [geometry, setGeometry] = useState<SimGeometry | null>(null);
  const geometryRef = useRef<SimGeometry | null>(null);
  geometryRef.current = geometry;
  const [nets, setNets] = useState<SimNet[] | null>(null);
  const [netlist, setNetlist] = useState<string>("");
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
  /** What is on the scope. A pane is one pair of axes; every pane shares the
   *  X axis, and traces move between them (`sim/plots.ts`). */
  // Sticky: the traces on the scope and the picked net survive a refresh —
  // setting the measurements up is work, and F5 must not throw it away.
  const [panes, setPanes] = useStickyState<Pane[]>(`sim:${sourceKey}:panes`, []);
  const [selectedNet, setSelectedNet] = useStickyState<string | null>(`sim:${sourceKey}:net`, null);
  const [fit, setFit] = useState(true);
  const [showUnconnected, setShowUnconnected] = useState(false);

  const [sample, setSample] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [clock, setClock] = useState(0);

  /** Sketch live mode: the browser netlists the document itself and the run
   *  is RELOADED in place on every edit, state carried on the components.
   *  Everything here exists to keep one vocabulary of names across edits. */
  const lastNetlist = useRef<DocNetlist | null>(null);
  const [sketchVectors, setSketchVectors] = useState<string[] | null>(null);

  // Live mode: an endless run, streamed, that you change while it runs.
  const [live, setLive] = useState(false);
  const [liveState, setLiveState] = useState<LiveState | null>(null);
  const [liveSpeed, setLiveSpeed] = useStickyState(`sim:${sourceKey}:speed`, 1e-3);
  const session = useRef<LiveSession | null>(null);
  const [alterText, setAlterText] = useState("");
  const [alterLog, setAlterLog] = useState<string[]>([]);
  /** Contacts the user has flipped this session, by SPICE instance name. The
   *  netlist's own value is the starting position. */
  const [switchState, setSwitchState] = useState<Record<string, boolean>>({});
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
  const sketchRef = useRef<{ past: SchDoc[]; now: SchDoc; future: SchDoc[] } | null>(null);
  sketchRef.current = sketch;
  const [palette, setPalette] = useState<{
    parts: PaletteEntry[];
    libs: Record<string, LibSymbol>;
    switch: { open: string; closed: string; open_r: string; closed_r: string };
  } | null>(null);
  const [editable, setEditable] = useState(false);

  useEffect(() => {
    if (modeParam === "live" && snapshotId) setLive(true);
    // Read once, at arrival — the toggle is the user's after that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
        // Falstad has no edit mode, and neither does a sketch any more: the
        // tools are always out, and the page opens RUNNING. Scenario is the
        // mode you switch to deliberately, for the formal run.
        setEditing(true);
        if (modeParam !== "scenario") setLive(true);
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
      setLive(true);
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
    // A sketch's live session runs on the browser's own netlist, so the
    // vector list comes from that netlist, not from the (asynchronously
    // refreshed) server geometry. Names still line up: the netlister reuses
    // the geometry's net names wherever the net survived.
    if (sketchVectors) return sketchVectors;
    if (!geometry) return [] as string[];
    const names: string[] = [];
    for (const g of geometry.groups) {
      if (g.spice && !g.ground && !g.derived) names.push(`v(${g.spice})`);
    }
    for (const sym of geometry.symbols) {
      if (sym.power || !sym.ref) continue;
      // The run reports currents under the ELEMENT name — `rsw1`, not `SW1`.
      const ref = (sym.spice || sym.ref).toLowerCase();
      // A source's current is its own branch; everything else answers to the
      // savecurrents form. Asking for both costs one float per frame and saves
      // a reading that would otherwise silently be missing.
      names.push(`i(@${ref}[i])`);
      if (/^[vi]/.test(ref)) names.push(`i(${ref})`);
    }
    return names.slice(0, 400);
  }, [geometry, sketchVectors]);

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

  /** The knob panel lists what THIS SHEET cannot: a harness source that lives
   *  in a SPICE text block has no symbol at all, and a part on another sheet
   *  of the design has one you cannot reach from here. A part on the drawing
   *  is set in its own dialog, and listing it twice means two boxes for one
   *  number — with the second one showing the netlist's original value long
   *  after the first changed it. */
  const offSheet = useMemo(() => {
    const drawn = new Set((geometry?.symbols ?? []).map((s) => s.spice).filter(Boolean));
    return controls.filter((c) => !drawn.has(c.ref));
  }, [controls, geometry]);

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

  /** How each part on the drawing is decorated and described. Built in EVERY
   *  mode, not only during a live run: clicking a part opens its dialog, and
   *  a hotspot that appears only while something is running would make the
   *  same part clickable and then not. A contact still draws as open or
   *  closed, which only a live run knows. */
  const liveParts = useMemo(() => {
    if (!geometry) return undefined;
    const map = new Map<number, { title: string; kind: string; on?: boolean }>();
    for (const sym of geometry.symbols) {
      if (sym.power) continue;
      const c = sym.spice ? controlByRef.get(sym.spice) : undefined;
      if (live && c && isSwitch(sym.ref)) {
        const closed = switchState[sym.spice] ?? ((c.numeric ?? 1) < 1e6);
        map.set(sym.index, {
          kind: "switch",
          on: closed,
          title: `${sym.ref} — ${closed ? "closed" : "open"}. Click to open it.`,
        });
      } else {
        map.set(sym.index, {
          kind: c?.kind ?? "device",
          on: false,
          title: c
            ? c.kind === "scripted"
              ? `${sym.ref} runs a ${c.value} waveform — ngspice will not let one be steered mid-run`
              : `${sym.ref} = ${c.value}${c.unit}`
            : `${sym.ref} ${sym.value}`.trim(),
        });
      }
    }
    return map;
  }, [live, geometry, controlByRef, switchState, isSwitch]);

  /** What the netlist says each drawn part is worth, for the dialog on a
   *  sheet the editor may not rewrite. */
  const controlsBySpice = useMemo(
    () => new Map(controls.map((c) => [c.ref, { value: c.value, unit: c.unit, kind: c.kind }])),
    [controls],
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
  const sketchLive = editable && sketch !== null;

  /** Netlist the current document, keeping every surviving net's name.
   *
   *  The reuse order matters: the netlist we LAST SENT wins over the server
   *  geometry, because during a burst of edits the geometry is a save behind
   *  and the run is not. */
  const buildNetlist = useCallback((doc: SchDoc, carryState: boolean): DocNetlist | null => {
    if (!palette) return null;
    const geo = geometryRef.current;
    const geoPin = new Map<string, string>();
    if (geo) {
      const groupSpice = new Map(geo.groups.map((g) => [g.id, g.spice]));
      for (const pin of geo.pins) {
        const spice = groupSpice.get(pin.group);
        if (spice) geoPin.set(`${pin.ref}.${pin.pin}`, spice);
      }
    }
    return netlistDoc(doc, palette.libs, {
      tstep: 1e-5,
      tstop: 1000,
      carryState,
      reuse: (pins) => {
        for (const p of pins) {
          const kept = lastNetlist.current?.pinNode.get(`${p.ref}.${p.pin}`)
            ?? geoPin.get(`${p.ref}.${p.pin}`);
          if (kept && kept !== "0") return kept;
        }
        return null;
      },
    });
  }, [palette]);

  /** The vectors a browser netlist offers: every net's voltage, every
   *  element's current — the same shape the geometry-derived list has. */
  const vectorsOf = useCallback((built: DocNetlist): string[] => {
    const names = built.nets.map((n) => `v(${n})`);
    for (const el of built.nodesOf.keys()) {
      names.push(`i(@${el}[i])`);
      if (/^[vi]/.test(el)) names.push(`i(${el})`);
    }
    return names.slice(0, 400);
  }, []);

  // A schematic that came from KiCad: the session restarts when the sheet or
  // its vector list changes, exactly as before.
  useEffect(() => {
    if (sketchLive) return;
    if (!live || !source || !geometry || !liveVectors.length) return;
    const target =
      source.kind === "snapshot"
        ? { kind: "snapshot", snapshot_id: source.snapshotId, board: source.board }
        : { kind: "upload", upload_id: source.uploadId };
    const s = new LiveSession(
      // The scopes the user has open at the moment the run starts. Later
      // changes go through `setScopes`, NOT through this config: rebuilding
      // it would restart the simulation every time a trace was added.
      { target, overlay: liveVectors, scopes: scopesRef.current, speed: liveSpeed, tstep: 1e-5,
        historySpan: (liveSpeed * LIVE_WINDOW_S) / LIVE_COLUMNS },
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
  }, [live, source, geometry, liveVectors, sketchLive]);

  // A sketch: ONE session for as long as live stays on. The browser writes
  // the netlist (no kicad-cli anywhere in the path), and every edit after
  // this is a reload of the same worker, not a new one — that is where the
  // instant feel and the carried state both come from.
  useEffect(() => {
    if (!sketchLive || !live || !source || source.kind !== "upload" || !palette) return;
    const doc = sketchRef.current?.now;
    if (!doc) return;
    const built = buildNetlist(doc, false);
    if (!built) return;
    lastNetlist.current = built;
    const overlay = vectorsOf(built);
    setSketchVectors(overlay);
    const s = new LiveSession(
      {
        target: { kind: "upload", upload_id: source.uploadId },
        netlist: built.text,
        overlay,
        scopes: scopesRef.current,
        speed: liveSpeed,
        tstep: 1e-5,
        historySpan: (liveSpeed * LIVE_WINDOW_S) / LIVE_COLUMNS,
      },
      setLiveState,
    );
    session.current = s;
    s.start();
    return () => {
      s.stop();
      session.current = null;
      setLiveState(null);
      setSketchVectors(null);
      lastNetlist.current = null;
    };
    // liveSpeed is steered through the session; the document through reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sketchLive, live, source, palette]);

  /** The edit -> reload pipeline. Debounced just enough to coalesce a drag;
   *  value edits, deletions and new wires land in ~150 ms with every cap's
   *  charge and every inductor's flux carried across. */
  const docJson = sketch ? JSON.stringify(sketch.now) : "";
  useEffect(() => {
    if (!live || !sketchLive || !session.current || !lastNetlist.current) return;
    const timer = setTimeout(() => {
      const doc = sketchRef.current?.now;
      const prev = lastNetlist.current;
      if (!doc || !prev || !session.current) return;
      const built = buildNetlist(doc, true);
      if (!built) return;
      // Same circuit, ignoring the state tokens? Then there is nothing to
      // reload — the run is already right, and alter handled any live value.
      const normalize = (t: string) => t.replace(/ IC=%IC_[^%]+%/g, "").replace(" uic", "");
      if (normalize(built.text) === normalize(prev.text)) return;
      const overlay = vectorsOf(built);
      setSketchVectors(overlay);
      session.current.reload({
        netlist: built.text,
        // The OLD nodes: state is measured on the circuit that is running,
        // not the one about to load.
        state: prev.state,
        overlay,
        scopes: scopesRef.current,
      });
      lastNetlist.current = built;
    }, 120);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docJson, live, sketchLive]);

  /** What each open trace asks the worker to watch.
   *
   *  A live scope is fed CLOSED COLUMNS, one per pixel, so the browser says
   *  how much simulated time a pixel is worth. Tie it to the speed and a
   *  scope is the same few seconds of WALL clock at every setting — which is
   *  what a person means by "the last few seconds".
   */
  /** Which devices this run reports a branch current for. It decides how a
   *  wire's or a terminal's current can be written, so it has to come from the
   *  run itself and not from a guess about naming. */
  const runVectors = liveState?.vectors;
  const hasCurrent = useCallback((ref: string) => {
    if (live) {
      // A live run's vector list is RAW ngspice names — `@r2[i]`,
      // `v1#branch` — never the wrapped `i(...)` a rawfile speaks. Testing
      // the wrapped form here returned false for every device, which turned
      // every wire and pin probe into the 30 Hz fallback and desynchronised
      // its pane from the voltage beside it.
      return (runVectors?.includes(`@${ref}[i]`) ?? false)
        || (runVectors?.includes(`${ref}#branch`) ?? false);
    }
    const names = [`i(@${ref}[i])`, `i(${ref})`];
    return plot ? names.some((n) => plot.byName.has(n)) : false;
  }, [live, runVectors, plot]);

  const liveScopes = useMemo(
    () => panes.flatMap((p) => p.traces).map((t) => {
      const span = (liveSpeed * LIVE_WINDOW_S) / LIVE_COLUMNS;
      const probe = probeOf(t.name);
      if (!probe || !geometry) return { vec: t.name, sim_s_per_px: span };
      // A wire or a terminal has no vector of its own, so the worker is given
      // the combination that makes it. Then it is closed at the SOLVER's rate
      // like every other trace, instead of being rebuilt one frame at a time —
      // which drew a staircase beside a smooth voltage on the same net.
      const terms = probeTerms(geometry, probe, hasCurrent);
      if (!terms) return { vec: t.name, sim_s_per_px: span };
      return {
        vec: t.name,
        sim_s_per_px: span,
        // The worker's `resolve` tries every spelling of a current, so the
        // wrapped form is always safe to send.
        terms: terms.map((x) => ({ vec: `i(${x.ref})`, coeff: x.coeff })),
      };
    }),
    [panes, liveSpeed, geometry, hasCurrent, runVectors],
  );
  const scopesRef = useRef(liveScopes);
  scopesRef.current = liveScopes;

  useEffect(() => {
    if (live) session.current?.setScopes(liveScopes);
  }, [live, liveScopes]);

  const alter = useCallback((command: string) => {
    session.current?.alter(command);
    setAlterLog((l) => [command, ...l].slice(0, 8));
  }, []);

  /** Throw a contact in a live run. A switch is a resistance, so this is an
   *  `alter` like any other — and the drawing swaps to the other blade
   *  position, because a reading that says "closed" over a picture of an open
   *  contact is worse than no picture. */
  const flipPart = useCallback((index: number) => {
    const sym = geometry?.symbols.find((s) => s.index === index);
    if (!sym) return;
    const c = controlByRef.get(sym.spice);
    if (!c || !isSwitch(sym.ref)) return;
    const closed = switchState[sym.spice] ?? ((c.numeric ?? 1) < 1e6);
    const next = closed ? openR : closedR;
    setSwitchState((s) => ({ ...s, [sym.spice]: !closed }));
    setKnobValues((v) => ({ ...v, [sym.spice]: next }));
    alter(`alter ${sym.spice} = ${next}`);
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
        // Only onto an EMPTY scope: a remembered setup (sticky across refresh)
        // beats the guess about what is worth watching.
        setPanes((cur) => (cur.length ? cur
          : [{ id: paneId(), traces: [{ name: first.name, label: named?.net ?? first.key, unit: "V" }] }]));
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
    // A sketch opens LIVE and is running already; the scenario auto-run is
    // for a sheet dropped from KiCad, which has nothing on screen until a
    // run exists. `editable || live` rather than a settled flag: the sketch
    // probe answers fast, and a doubled run costs a second, not a state.
    if (editable || live) return;
    if (autoRan.current === source.uploadId) return;
    autoRan.current = source.uploadId;
    void doRun();
    // doRun is rebuilt whenever the chosen scenario changes; the guard above
    // is what keeps this to one run per source, not the dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, geometry, busy, editable, live]);

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
    setPanes((current) => addToPanes(current, { name, label, unit }));
  }, []);

  /** A part picked on the drawing puts its CURRENT on the scope, beside the
   *  voltage of whatever wire was picked before it. That is what Falstad does
   *  and it is the reading a person is after: a net says what a node is at, a
   *  part says what is going through it, and the two only mean something
   *  together. The dialog opens on the same click; this is the plot half. */
  const plotPart = useCallback((index: number) => {
    const sym = geometry?.symbols.find((x) => x.index === index);
    if (!sym || sym.power || !sym.spice) return;
    // ngspice spells a device current two ways and the choice is not ours: a
    // source's is its own branch, `i(v1)`, and everything else answers to
    // `i(@r1[i])` under `.options savecurrents`. Ask the run which it has.
    const names = [`i(@${sym.spice}[i])`, `i(${sym.spice})`];
    const name = live ? names[0] : names.find((n) => plot?.byName.has(n)) ?? names[0];
    addTrace(name, sym.ref || sym.spice, "A");
  }, [geometry, addTrace, live, plot]);

  /** A wire picked on the drawing: BOTH of its readings.
   *
   *  A net has no current — SPICE knows device branches, not wires — but the
   *  WIRE the user clicked does, and it is reconstructed from the currents
   *  around it. So a click gives the voltage of the net and the current of
   *  that segment, which is the pair a person is actually after; they land in
   *  separate panes on one time axis, because volts and amps do not share a
   *  scale.
   */
  const pickNet = useCallback(
    (net: string | null, wireId?: string, what?: "v" | "i" | "both") => {
      setSelectedNet(net);
      // A single click SELECTS — the readout and the highlight. The traces
      // come from the double-click chooser, which says WHICH readings.
      if (!what || !net || !geometry) return;
      // KiCad's name for a pin nobody wired. Its "net" is one floating pin —
      // plotting it is how an edit session fills the scope with junk rows.
      if (net.startsWith("unconnected-")) return;
      const group = geometry.groups.find((g) => g.net === net);
      // A derived name is a label the netlist does not know — adding it as a
      // trace would put a row on the scope that can never draw anything.
      if (what !== "i" && group?.spice && !group.ground && !group.derived) {
        addTrace(`v(${group.spice})`, net, "V");
      }
      if (what !== "v" && wireId && !group?.ground) addTrace(wireTrace(wireId), `${net} wire`, "A");
    },
    [geometry, addTrace],
  );

  /** A terminal picked on the drawing: its voltage and its current.
   *
   *  On a two-pin part the current is the part's own. On anything else — an
   *  op-amp output, a regulator pin, any leg of a subcircuit — SPICE reports
   *  no per-terminal current at all, and the only way to one is the net around
   *  it: where this pin is the single terminal on its net whose current is
   *  unknown, conservation names it. Where two are unknown it cannot be named,
   *  and the pin plots its voltage alone rather than a number nobody can
   *  stand behind.
   */
  const pickPin = useCallback(
    (pin: { ref: string; pin: string; group: string }, what?: "v" | "i" | "both") => {
      if (!geometry) return;
      const group = geometry.groups.find((g) => g.id === pin.group);
      if (group?.net && !group.ground) setSelectedNet(group.net);
      if (!what || group?.net?.startsWith("unconnected-")) return;
      if (what !== "i" && group?.spice && !group.ground && !group.derived && group.net) {
        addTrace(`v(${group.spice})`, group.net, "V");
      }
      if (what !== "v") addTrace(pinTrace(pin.ref, pin.pin), `${pin.ref}.${pin.pin}`, "A");
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

  /** How big the numbers get in a LIVE run.
   *
   *  A finished run knows its own extremes, because every point of it is in
   *  hand. A live one has only the latest frame, so the scale is learned as
   *  the run goes and only ever GROWS: a peak that tracked the instant would
   *  make the tint flicker and the charge dots change speed thirty times a
   *  second, which reads as noise rather than as current.
   */
  /** How fast the charge moves on the drawing. A viewing preference, so it is
   *  remembered for the session like the other selections on this page. */
  const [currentSlider, setCurrentSlider] = useStickyState("sim:current-speed", CURRENT_SLIDER_MID);
  /** Volts at which the tint saturates. A SCALE, not an autorange: the same
   *  green has to mean the same voltage on two sheets, or the picture is
   *  decoration. 0 falls back to the run's own extremes for anyone who wants
   *  that instead. */
  const [voltRef, setVoltRef] = useStickyState("sim:volt-ref", 10);
  const currentSpeed = currentSpeedOf(currentSlider);

  /** The split fills the window from its own top edge down: canvas takes
   *  what the dock leaves. Measured, because the chrome above it (title,
   *  tabs, top bar, banners) has no fixed height. */
  const splitRef = useRef<HTMLDivElement | null>(null);
  const [splitH, setSplitH] = useState(0);
  const hasGeometry = !!geometry;
  useEffect(() => {
    const measure = () => {
      const el = splitRef.current;
      if (!el) return;
      setSplitH(Math.max(420, window.innerHeight - el.getBoundingClientRect().top - 14));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [hasGeometry]);

  const [liveScale, setLiveScale] = useState(LIVE_SCALE_START);
  useEffect(() => { setLiveScale(LIVE_SCALE_START); }, [live, source]);
  useEffect(() => {
    if (!live || !liveState) return;
    let min = 0;
    let max = 0;
    let peak = 0;
    for (let i = 0; i < liveVectors.length; i += 1) {
      const v = liveState.values[i];
      if (!Number.isFinite(v)) continue;
      if (liveVectors[i].startsWith("i(")) peak = Math.max(peak, Math.abs(v));
      else if (v < min) min = v;
      else if (v > max) max = v;
    }
    setLiveScale((s) => {
      const next = {
        min: Math.min(s.min, min),
        max: Math.max(s.max, max),
        peak: Math.max(s.peak, peak),
      };
      // The same object when nothing grew, or this effect would re-render the
      // page on every frame for no change at all.
      return next.min === s.min && next.max === s.max && next.peak === s.peak ? s : next;
    });
  }, [live, liveState, liveVectors]);

  /** The traces on the scope that are NOT vectors in the run: a wire's own
   *  current, and a terminal's. ngspice reports neither — both are worked out
   *  from the currents around them (`sim/currents.ts`). */
  const probes: Probe[] = useMemo(
    () => panes.flatMap((p) => p.traces)
      .map((t) => probeOf(t.name))
      .filter((x): x is Probe => x !== null),
    [panes],
  );

  /** A finished run: solve every probe across the whole of it, once, and only
   *  when one is actually on the scope. */
  const probeSeries = useMemo(
    () => (!live && plot && geometry && probes.length
      ? solveProbeSeries(geometry, plot, probes)
      : new Map<string, Float64Array>()),
    [live, plot, geometry, probes],
  );

  /** A live run has no history to solve over, so one is kept: a probe is
   *  solved on each frame that arrives and pushed into a ring buffer the width
   *  of the scope. Frame rate, not solver rate — a reconstruction sampled
   *  thirty times a second is what a scope showing four seconds can draw
   *  anyway. */
  const liveProbes = useRef<{ t: number[]; v: Map<string, number[]> }>({ t: [], v: new Map() });
  const probeKey = probes.map((x) => x.name).join(",");
  useEffect(() => { liveProbes.current = { t: [], v: new Map() }; }, [probeKey, live, source]);
  useEffect(() => {
    if (!live || !geometry || !liveState || !probes.length || !reader) return;
    // Only for probes the worker is not already closing columns for.
    const done = new Set(liveScopes.filter((x) => x.terms?.length).map((x) => x.vec));
    if (probes.every((x) => done.has(x.name))) return;
    const solved = solveSegmentCurrents(geometry, reader);
    const buf = liveProbes.current;
    buf.t.push(liveState.simTime);
    for (const probe of probes) {
      const list = buf.v.get(probe.name) ?? [];
      list.push(readProbe(solved, probe));
      buf.v.set(probe.name, list);
    }
    if (buf.t.length > LIVE_COLUMNS) {
      const drop = buf.t.length - LIVE_COLUMNS;
      buf.t.splice(0, drop);
      for (const list of buf.v.values()) list.splice(0, drop);
    }
    // `reader` is rebuilt for every frame, which is what makes this fire once
    // per frame rather than once per render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, geometry, liveState, probeKey, reader, liveScopes]);

  /** The numbers the scope draws, whichever kind of run made them.
   *
   *  uPlot wants Float64Array per series and one shared X, so the conversion
   *  happens once here rather than inside every pane. A live run has no points
   *  to convert: it has closed min-max COLUMNS, so each trace becomes a band
   *  and the middle line is the average of the two edges — which is what a
   *  scope drawing one pixel per column has always shown.
   */
  const plotData: PlotData | null = useMemo(() => {
    if (live) {
      const cols = liveState?.columns ?? [];
      const traces = panes.flatMap((p) => p.traces);
      // A FIXED time base: the grid is always the whole window, samples enter
      // at the right edge and roll leftwards, and the void on the left fills
      // as the run reaches it. The axis never rescales under a moving trace —
      // a stretchy time base was tried and read worse than the void. Fixed
      // width also means never null: a null destroys every chart on the page
      // and rebuilds it when data returns.
      const width = LIVE_COLUMNS;
      const span = (liveSpeed * LIVE_WINDOW_S) / LIVE_COLUMNS;
      const x = new Float64Array(width);
      // Time backwards from now: the newest column is at the right edge, and
      // the axis reads as "seconds ago", which is what a scrolling scope means.
      for (let i = 0; i < width; i += 1) x[i] = (i - width + 1) * span;
      const series = new Map<string, { y: Float64Array; lo: Float64Array; hi: Float64Array }>();
      traces.forEach((t, i) => {
        const list = cols[i] ?? [];
        const y = new Float64Array(width);
        const lo = new Float64Array(width);
        const hi = new Float64Array(width);
        const pad = width - list.length;
        for (let k = 0; k < width; k += 1) {
          const c = k >= pad ? list[k - pad] : undefined;
          if (!c) { y[k] = NaN; lo[k] = NaN; hi[k] = NaN; continue; }
          lo[k] = c.min;
          hi[k] = c.max;
          y[k] = (c.min + c.max) / 2;
        }
        series.set(t.name, { y, lo, hi });
      });
      // A probe has no columns from the worker — it was solved here, one point
      // per frame. Put those on the same grid by TIME, so a wire current and a
      // node voltage share the axis instead of merely sitting near each other.
      const buf = liveProbes.current;
      const now = liveState?.simTime ?? 0;
      // Which probes the worker is closing columns for NOW. Keyed on the
      // current scope list, never on whether the slot holds columns: after a
      // topology edit takes a probe's terms away (an op-amp dragged off its
      // net), the slot still holds the CARRIED history — judging by length
      // suppressed the fallback forever, and the pane simply froze while the
      // voltage beside it went on. Measured as exactly that complaint.
      const termed = new Set(liveScopes.filter((x) => x.terms?.length).map((x) => x.vec));
      for (const probe of probes) {
        // The worker closes a probe's columns itself when it was given the
        // terms that make it. Only a probe it could NOT be given — a severed
        // pin, a net with two unknown terminals, a loop — falls back to the
        // frame-rate reconstruction, and that one is a staircase by nature.
        if (termed.has(probe.name)) continue;
        const values = buf.v.get(probe.name);
        if (!values || !values.length) continue;
        const y = new Float64Array(width).fill(NaN);
        let at = 0;
        for (let k = 0; k < width; k += 1) {
          const want = now + x[k];
          while (at + 1 < buf.t.length && buf.t[at + 1] <= want) at += 1;
          y[k] = buf.t[at] <= want + span ? values[at] : NaN;
        }
        series.set(probe.name, { y } as { y: Float64Array; lo: Float64Array; hi: Float64Array });
      }
      return { x, xUnit: "s", xLabel: "time", series };
    }
    if (!plot) return null;
    const x = Float64Array.from(plot.scale);
    const series = new Map<string, { y: Float64Array }>();
    for (const t of panes.flatMap((p) => p.traces)) {
      const solvedProbe = probeSeries.get(t.name);
      if (solvedProbe) { series.set(t.name, { y: solvedProbe }); continue; }
      const raw = plot.byName.get(t.name);
      if (raw) series.set(t.name, { y: Float64Array.from(raw) });
    }
    return {
      x,
      xUnit: plot.scaleType === "time" ? "s" : plot.scaleType === "frequency" ? "Hz" : "",
      xLabel: plot.scaleName,
      series,
    };
  }, [live, liveState, panes, plot, liveSpeed, probes, probeSeries, liveScopes]);

  const voltageRange = useMemo(
    () => (live ? { min: liveScale.min, max: liveScale.max }
      : plot ? vectorRange(plot.voltages.values()) : { min: -24, max: 24 }),
    [live, liveScale, plot],
  );
  const currentPeak = useMemo(
    () => (live ? liveScale.peak : plot ? peakMagnitude(plot.currents.values()) : 1e-3),
    [live, liveScale, plot],
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
  const verdicts = readVerdicts(run?.header.log ?? "");
  const sheetOwn = scenarios?.scenarios?.[0]?.text ?? "";

  return (
    <div className="page page-wide page-sim">
      {error ? <ErrorBanner message={error} /> : null}

      {/* ONE bar, and it answers one question: what am I looking at, and in
          which mode. What to RUN is a separate bar under the drawing, next to
          the waveform it produces — the two used to be interleaved in a single
          toolbar that grew with the data and read as a pile of buttons. */}
      <div className="sim-topbar">
        {tabBar}
        {/* A dropdown, not a row of buttons: a repository has as many
            simulation blocks as it likes. */}
        {projects && projects.length > 1 ? (
          <label className="sim-runbar-pick">
            <span>Simulation</span>
            <select
              className="text"
              value={board}
              onChange={(e) => setParams({ snapshot: String(snapshotId), board: e.target.value })}
            >
              {projects.filter((x) => x.has_schematic).map((x) => (
                <option key={x.board} value={x.board}>
                  {x.board}{x.simulation ? " · harness" : ""}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {sheets && sheets.length > 1 ? (
          <label className="sim-runbar-pick">
            <span>Sheet</span>
            <select
              className="text"
              value={sheetPath}
              onChange={(e) => setSheetPath(e.target.value)}
              title="What to LOOK at. A run always covers the whole project."
            >
              {sheets.map((x) => (
                <option key={x.path} value={x.path}>
                  {"\u00a0\u00a0".repeat(x.depth)}{x.name} · {x.symbols} parts
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <span className="sim-runbar-spacer" />

        {live && geometry ? <RunBar
            bare
            live={live}
            scenarios={scenarios}
            control={control}
            onControl={setControl}
            analysis={analysis}
            onAnalysis={setAnalysis}
            busy={busy}
            onRun={() => void doRun()}
            verdicts={verdicts}
            ran={!!run}
            state={liveState}
            speed={liveSpeed}
            onSpeed={(v) => { setLiveSpeed(v); session.current?.setSpeed(v); }}
            onHold={() => {
              if (liveState?.status === "halted") session.current?.resume();
              else session.current?.halt();
            }}
          /> : null}

        {/* A drawing has no page to fit to and no page to show whole: it opens
            on a working window and the wheel does the rest. */}
        {/* How fast the charge moves. It says nothing about the simulation —
            the dots are drawn at a speed proportional to each wire's share of
            the peak current, and this is the constant of proportionality. Zero
            stops them, which is what a screenshot wants. */}
        {/* The volt scale the colours mean. Falstad's convention: green above
            ground, red below, nothing at zero. */}
        <label className="sim-runbar-pick" title="The voltage at which the wire colour saturates">
          <span>Volts</span>
          <select
            className="text"
            value={String(voltRef)}
            onChange={(e) => setVoltRef(Number(e.target.value))}
          >
            {[1, 2, 5, 10, 20, 50, 100].map((v) => (
              <option key={v} value={String(v)}>&plusmn;{v} V</option>
            ))}
            <option value="0">auto</option>
          </select>
        </label>
        <label className="sim-runbar-pick sim-speed" title="How fast the charge dots travel">
          <span>Current</span>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={currentSlider}
            onChange={(e) => setCurrentSlider(Number(e.target.value))}
            aria-label="Current flow speed"
          />
          <span className="mono sim-speed-read">
            {currentSpeed === 0 ? "off" : `${currentSpeed < 1 ? currentSpeed.toFixed(2) : currentSpeed.toFixed(1)}\u00d7`}
          </span>
        </label>
        {editable ? null : (
          <div className="seg" role="group" aria-label="View">
            <button type="button" className={fit ? "on" : ""} onClick={() => setFit(true)}>Fit</button>
            <button type="button" className={!fit ? "on" : ""} onClick={() => setFit(false)}>Sheet</button>
          </div>
        )}
        {/* No Edit toggle: a sketch's tools are always out, like Falstad's.
            Download is the way OUT of the playground — live edits never write
            a project file, so the file in hand is the only artefact. */}
        {editable ? (
          <button type="button" className="ghost" onClick={() => void downloadSketch()}>
            Download
          </button>
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
          <div className="sim-split" ref={splitRef} style={splitH ? { height: splitH } : undefined}>
          <div className="sim-canvas-slot">
          <SimulatorView
            geometry={geometry}
            theme={theme}
            fit={fit}
            reader={reader}
            clock={clock}
            running={playing || live}
            voltageRange={voltageRange}
            currentPeak={currentPeak}
            currentSpeed={currentSpeed}
            voltRef={voltRef}
            selectedNet={selectedNet}
            onPickNet={pickNet}
            onProbeNet={(net, wireId, what) => pickNet(net, wireId, what)}
            onProbePin={(pin, what) => pickPin(pin, what)}
            parts={liveParts}
            onPickPart={plotPart}
            onPickPin={pickPin}
            controls={controlsBySpice}
            onFlip={live ? flipPart : undefined}
            partSwap={partSwap}
            onUnresolved={setUnresolved}
            onAlter={live ? alter : undefined}
            edit={editProps}
          />
          </div>

          {/* The dock: what runs and what it shows, pinned to the bottom of
              the window so the drawing and the waveform share one screen —
              Falstad's one-window feel. The page can still scroll for the
              reference drawer underneath. */}
          <div className="sim-dock">
          {!live && geometry ? <RunBar
            live={live}
            scenarios={scenarios}
            control={control}
            onControl={setControl}
            analysis={analysis}
            onAnalysis={setAnalysis}
            busy={busy}
            onRun={() => void doRun()}
            verdicts={verdicts}
            ran={!!run}
            state={liveState}
            speed={liveSpeed}
            onSpeed={(v) => { setLiveSpeed(v); session.current?.setSpeed(v); }}
            onHold={() => {
              if (liveState?.status === "halted") session.current?.resume();
              else session.current?.halt();
            }}
          /> : null}

          {/* The waveform, whichever kind of run made it. One scope, stacked
              panes, one X axis — a live run and a finished one differ only in
              where the numbers come from. */}
          <div className="card pad sim-scope-card">
            <Plots
              panes={panes}
              onPanes={setPanes}
              data={plotData}
              cursor={sample}
              onCursor={(i) => { setPlaying(false); setSample(i); }}
              live={live}
              head={(
                <>
                  {!live && plot && plot.scale.length > 1 ? (
                    <button type="button" onClick={() => setPlaying((x) => !x)}>
                      {playing ? "Pause" : "Play"}
                    </button>
                  ) : null}
                  {live ? (
                    <span className="pill neutral">live</span>
                  ) : plot ? (
                    <span className="pill neutral">{plot.name}</span>
                  ) : null}
                  <span className="muted">
                    {live
                      ? `the last ${LIVE_WINDOW_S} s of wall clock`
                      : plot
                        ? plot.scale.length === 1
                          ? "a single solution"
                          : `${plot.scale.length} points · ${eng(
                            duration, plot.scaleType === "time" ? "s" : "Hz")}`
                        : "nothing has run yet"}
                    {!live && plot?.decimated ? " · decimated to a min/max envelope" : ""}
                  </span>
                </>
              )}
            />
          </div>
          </div>
          </div>

          {!live ? <Verdicts verdicts={verdicts} /> : null}

          <SimNotices
            geometry={geometry}
            run={run}
            unresolved={unresolved}
            sheetName={drawnSheet?.name ?? ""}
          />

          {/* Reference, closed. Every one of these is something a person wants
              twice a day and never while reading a waveform; open, they used to
              push the circuit off the screen. */}
          <div className="sim-drawer">
            {live ? (
              <Disclosure title="Knobs off the drawing" note="sources and other sheets">
                <LiveControls
                  state={liveState}
                  controls={offSheet}
                  values={knobValues}
                  onValues={setKnobValues}
                  onAlter={alter}
                  log={alterLog}
                  text={alterText}
                  onText={setAlterText}
                />
              </Disclosure>
            ) : null}
            {!live && (control || sheetOwn) ? (
              <Disclosure title="Control block" note={control ? "edited here" : "the sheet's own"}>
                <textarea
                  className="text sim-control"
                  rows={14}
                  value={control || sheetOwn}
                  onChange={(e) => setControl(e.target.value)}
                  spellCheck={false}
                />
                {control ? (
                  <button type="button" className="ghost" onClick={() => setControl("")}>
                    Revert to the sheet&apos;s own
                  </button>
                ) : null}
              </Disclosure>
            ) : null}
            {nets ? (
              <Disclosure title="Nets" note={`${nets.filter((n) => !isUnconnected(n)).length} named`}>
                {/* `unconnected-(U47-A0-Pad2)` is KiCad naming a pin nobody
                    wired. On a real board they outnumber the real nets. */}
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
              </Disclosure>
            ) : null}
            {netlist ? (
              <Disclosure title="SPICE netlist" note="what ngspice was given">
                <pre className="mono sim-netlist">{netlist}</pre>
              </Disclosure>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

/** The knobs a live run answers to that are NOT on the drawing.
 *
 *  Every part with a symbol is set in the dialog that opens on it — click the
 *  part, get its numbers. What is left over is what a drawing cannot show:
 *
 *  - a source that lives in a SPICE text block and has no symbol at all;
 *  - a part on ANOTHER sheet of the design, which has a symbol you cannot
 *    reach from the sheet on screen.
 *
 *  The second kind used to be printed as forty text boxes in a grid, under a
 *  drawing the user was looking at. It is a search box now: name the part, set
 *  the part. Each of these is an ngspice `alter` on the running circuit.
 */
function LiveControls({
  state, controls, values, onValues, onAlter, log, text, onText,
}: {
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
  const [find, setFind] = useState("");
  const sources = controls.filter((c) => c.kind === "source");
  const passives = controls.filter((c) => c.kind === "passive");
  const scripted = controls.filter((c) => c.kind === "scripted");
  const busy = !state || state.status === "connecting" || state.status === "error";

  const needle = find.trim().toLowerCase();
  const found = needle ? passives.filter((c) => c.ref.includes(needle)).slice(0, 12) : [];

  const apply = (c: LiveControl, raw: string) => {
    setValues((v) => ({ ...v, [c.ref]: raw }));
    if (raw.trim()) onAlter(`alter ${c.ref} = ${raw.trim()}`);
  };

  const knob = (c: LiveControl, zero = false) => (
    <label key={c.ref} className="sim-knob">
      <span className="mono">{c.ref}</span>
      <input
        className="text"
        value={values[c.ref] ?? c.value}
        disabled={busy}
        onChange={(e) => setValues((v) => ({ ...v, [c.ref]: e.target.value }))}
        onBlur={(e) => apply(c, e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") apply(c, (e.target as HTMLInputElement).value); }}
      />
      <span className="muted">{c.unit}</span>
      {zero ? <button type="button" disabled={busy} onClick={() => apply(c, "0")}>0</button> : null}
    </label>
  );

  return (
    <>
      {!controls.length ? (
        <p className="muted">Every part in this circuit is on the drawing — click one to set it.</p>
      ) : null}
      {sources.length ? (
        <>
          <p className="muted">
            Sources with no symbol. A switch driven by a control node is a source too, so
            this is where such a contact is thrown.
          </p>
          <div className="sim-knobs">{sources.map((c) => knob(c, true))}</div>
        </>
      ) : null}
      {passives.length ? (
        <>
          <p className="muted">
            {passives.length} more part{passives.length === 1 ? "" : "s"} sit on other sheets
            of this design. Open the sheet to click one, or name it here.
          </p>
          <div className="sim-knobs">
            <label className="sim-knob">
              <span>Find</span>
              <input
                className="text"
                value={find}
                placeholder="r95"
                onChange={(e) => setFind(e.target.value)}
              />
            </label>
            {found.map((c) => knob(c))}
            {needle && !found.length ? <span className="muted">nothing here is called that</span> : null}
          </div>
        </>
      ) : null}
      {scripted.length ? (
        <p className="muted">
          Driven by the harness, and not steerable while the run continues:{" "}
          <span className="mono">{scripted.map((c) => c.ref).join(", ")}</span>. ngspice keeps
          a source&apos;s waveform whatever you alter it to. To take one over, raise the series
          resistor the harness put in its path — that is what it is for — and drive the node
          from a source of your own.
        </p>
      ) : null}
      <p className="muted">
        Anything else, in ngspice&apos;s own words. A pole inside a subcircuit takes the
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
            if (e.key === "Enter" && text.trim()) { onAlter(text.trim()); onText(""); }
          }}
        />
        <button
          type="button"
          disabled={busy || !text.trim()}
          onClick={() => { onAlter(text.trim()); onText(""); }}
        >
          Apply
        </button>
      </div>
      {log.length ? <p className="muted mono">{log.join("  ·  ")}</p> : null}
    </>
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
