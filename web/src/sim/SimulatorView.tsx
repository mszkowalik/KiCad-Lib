/** The schematic, its simulation and its editing tools — one view.
 *
 *  Editing used to be a separate screen you left the simulation to reach. It
 *  is the same drawing, so it is now the same view: the tools appear on the
 *  toolbar, the overlay stays underneath them, and a circuit can be changed
 *  while its readings are on screen.
 *
 *  Two sources of the DRAWING, and the difference matters:
 *
 *  · a document being edited draws from the document, so a dragged part
 *    follows the pointer instead of waiting for a round trip;
 *  · anything else draws from the geometry the server parsed.
 *
 *  The overlay is matched to the document's wires BY POSITION, which holds
 *  because the writer emits one `(wire)` per document wire in order. When the
 *  counts disagree — a save has not landed yet — the overlay is dropped rather
 *  than drawn on the wrong wire.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SimGeometry } from "../api";
import SchematicView, { type View } from "./draw/SchematicView";
import type { LibSymbol, Pt, SchTheme } from "./draw/types";
import { eng, type Range, type SampleReader } from "./payload";
import useSimOverlay from "./useSimOverlay";
import {
  GRID, autoJunctions, distanceToWire, docToDrawing, newId, nextRef, orthoRun,
  pointInBox, snapPt, spiceName, symbolBox, symbolPins,
  type DocSymbol, type PaletteEntry, type SchDoc,
} from "./edit/doc";
import PartPopup, { type PartFacts } from "./PartPopup";
import type { ParamField, ParamForm } from "./edit/params";

export type Tool = "select" | "wire" | "label" | "text";

interface Selection {
  kind: "symbol" | "wire" | "label" | "text";
  id: string;
}

export interface EditProps {
  doc: SchDoc;
  onChange: (next: SchDoc, coalesce?: boolean) => void;
  palette: PaletteEntry[];
  libs: Record<string, LibSymbol>;
  /** The two library ids a switch has. Its state is which one it is drawn as,
   *  so that the picture and the netlist can never disagree. */
  switchPair: { open: string; closed: string };
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** Tools on, or just the drawing. */
  active: boolean;
}

interface Props {
  theme: SchTheme;
  fit: boolean;
  geometry: SimGeometry | null;
  reader: SampleReader | null;
  clock: number;
  running: boolean;
  voltageRange: Range;
  currentPeak: number;
  /** How fast the charge dots travel, as a multiple of the default. */
  currentSpeed?: number;
  /** Volts at which the tint saturates. 0 means "use the run's own range". */
  voltRef?: number;
  selectedNet: string | null;
  onPickNet: (net: string | null, wireId?: string) => void;
  /** Add the chosen reading(s) to the scope — the double-click chooser. */
  onProbeNet?: (net: string, wireId: string | undefined, what: "v" | "i" | "both") => void;
  onProbePin?: (pin: { ref: string; pin: string; group: string }, what: "v" | "i" | "both") => void;
  onUnresolved: (items: { net: string; reason: string }[]) => void;
  parts?: Map<number, { title: string; kind: string; on?: boolean }>;
  onPickPart?: (index: number) => void;
  /** A terminal picked on the drawing: its voltage and its current. */
  onPickPin?: (pin: { ref: string; pin: string; group: string }) => void;
  /** What the netlist says a part is worth, by SPICE instance name. It is what
   *  a sheet KiCad wrote can offer: that file is never rewritten, so the
   *  popup's one value box steers the RUN and says so. */
  controls?: Map<string, { value: string; unit: string; kind: string }>;
  /** Flip a contact drawn as a switch, in a live run. */
  onFlip?: (index: number) => void;
  /** Symbols to draw as a different library part — a contact flipped live. */
  partSwap?: Map<number, string>;
  /** Absent for a schematic that came from KiCad: that file carries tokens the
   *  document does not model, so it is shown and never rewritten. */
  edit?: EditProps;
  /** Steer the RUNNING transient. Absent when nothing is running. */
  onAlter?: (command: string) => void;
}

/** How close a click must be to a wire to pick it, in millimetres. */
const WIRE_PICK = 1.2;
/** How close a wire end must be to a pin to snap onto it. */
const PIN_SNAP = 2.0;
const PAPER: [number, number] = [297, 210];
/** The window a drawing opens on. A whole A4 page on a screen draws a
 *  resistor four pixels tall, which is a picture of a schematic rather than
 *  something anyone can edit. */
const OPENING_VIEW = { x: 55, y: 45, w: 150, h: 106 };
/** Grid dots at twice the placement grid, which is what KiCad shows too —
 *  a dot every 1.27 mm is a grey wash. */
const GRID_DOTS = GRID * 2;

export default function SimulatorView({
  theme, fit, geometry, reader, clock, running, voltageRange, currentPeak, currentSpeed, voltRef,
  selectedNet, onPickNet, onProbeNet, onProbePin, onUnresolved, parts, onPickPart, onPickPin, controls, onFlip,
  partSwap, edit, onAlter,
}: Props) {
  const [tool, setTool] = useState<Tool>("select");
  const [placing, setPlacing] = useState<PaletteEntry | null>(null);
  const [ghostAngle, setGhostAngle] = useState(0);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [cursor, setCursor] = useState<Pt>([0, 0]);
  const [run, setRun] = useState<Pt[] | null>(null);
  const moving = useRef<{ id: string; from: Pt; at: Pt } | null>(null);
  /** The part dialog: WHICH part, and where it opened. `id` names a symbol in
   *  the editor's document, `index` one on a sheet that came from KiCad — a
   *  sheet has one or the other, never both. */
  const [popup, setPopup] = useState<{ index: number | null; id: string | null; x: number; y: number } | null>(null);
  /** The right-click menu: where it opened (px for the box, mm for Paste). */
  const [menu, setMenu] = useState<{ x: number; y: number; mm: Pt; sel: Selection | null } | null>(null);
  /** The double-click chooser: which readings of this wire or pin to plot. */
  const [probe, setProbe] = useState<{
    x: number; y: number;
    net: string | null; wireId?: string;
    pin?: { ref: string; pin: string; group: string };
  } | null>(null);
  /** One copied symbol. A ref, not state — nothing draws it. */
  const clipboard = useRef<DocSymbol | null>(null);
  const viewRef = useRef<View | null>(null);
  /** What the last pointer-down hit, so a click that SELECTS a part does not
   *  also probe the pin dot under the same pixels. */
  const downHit = useRef<Selection | null>(null);
  const frame = useRef<HTMLDivElement | null>(null);

  /** A pointer position as pixels inside the drawing's own box, clamped so
   *  the dialog opens beside the part rather than off the edge. */
  const framePoint = (e: { clientX: number; clientY: number }) => {
    const box = frame.current?.getBoundingClientRect();
    if (!box) return { x: 16, y: 16 };
    return {
      x: Math.max(8, Math.min(e.clientX - box.left + 18, box.width - 356)),
      y: Math.max(8, Math.min(e.clientY - box.top - 16, Math.max(8, box.height - 120))),
    };
  };

  const editing = !!edit?.active;
  const doc = edit?.doc;
  /* A sketch with a circuit on it opens FITTED, like Falstad — the fixed
   * working window is for an EMPTY sheet. Decided once per document, so
   * placing the first part never yanks the viewport. */
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const openFit = useMemo(() => !!doc && doc.symbols.length > 0, [doc?.uuid]);
  const libs = edit?.libs;

  // A tool that is no longer reachable must not stay armed under the drawing.
  useEffect(() => {
    if (!editing) { setPlacing(null); setRun(null); setTool("select"); setSelected(null); }
    setPopup(null);
  }, [editing]);

  /** Junctions are DERIVED. Nobody places a junction dot in KiCad either — it
   *  appears where wires actually meet, and one a user could place by hand
   *  would be a short they could not see. */
  const onChangeRef = useRef(edit?.onChange);
  onChangeRef.current = edit?.onChange;
  useEffect(() => {
    if (!doc || !libs) return;
    const next = autoJunctions(doc, libs);
    const same = next.length === doc.junctions.length
      && next.every((p, i) => p[0] === doc.junctions[i]?.[0] && p[1] === doc.junctions[i]?.[1]);
    if (!same) onChangeRef.current?.({ ...doc, junctions: next }, true);
    // NOT on `edit`: the page rebuilds that object every render, and under a
    // live run that is thirty times a second — each one recomputing the
    // junctions and racing whatever the user is typing.
  }, [doc, libs]);

  const overlay = useSimOverlay({
    geometry, reader, clock, running, voltageRange, currentPeak, currentSpeed, voltRef,
    selectedNet, onPickNet, onUnresolved, parts,
    // A click that lands on a part's BODY is a selection, not a probe — the
    // pin dots overlap the outline, and selecting a part must not fill the
    // scope with its terminals.
    onPickPin: (pin: { ref: string; pin: string; group: string }) => {
      if (editing && downHit.current?.kind === "symbol") return;
      onPickPin?.(pin);
    },
    // Double-click: a small chooser at the pointer, not an immediate trace.
    onProbe: ({ net, wireId, pin, e }) => {
      if (editing && pin && downHit.current?.kind === "symbol") return;
      setProbe({ ...framePoint(e), net, wireId, pin });
    },
    // In edit mode the editor hit-tests the document itself, and a second
    // set of click targets over the same parts would fight it.
    onPickPart: editing ? undefined : (index: number, e: React.MouseEvent) => {
      onPickPart?.(index);
      setPopup({ index, id: null, ...framePoint(e) });
    },
    // While a tool has the pointer, the net targets must not swallow clicks.
    interactive: !editing || (tool === "select" && !placing),
    wires: doc?.wires,
  });

  // ------------------------------------------------------------- drawing

  const drawing = useMemo(() => {
    if (doc && libs) return docToDrawing(doc, libs);
    if (!geometry) return null;
    if (!partSwap?.size) return geometry.draw;
    return {
      ...geometry.draw,
      symbols: geometry.draw.symbols.map((s) => {
        const swap = partSwap.get(s.index);
        const lib = swap ? geometry.draw.libs[swap] : undefined;
        if (!swap || !lib) return s;
        // The Value is the state in words, and it is stored on the PLACEMENT
        // — swapping the graphics alone leaves a closed blade labelled "open".
        const value = lib.props.find((f) => f.k === "Value")?.v;
        return {
          ...s,
          lib_id: swap,
          fields: value === undefined
            ? s.fields
            : s.fields.map((f) => (f.k === "Value" ? { ...f, v: value } : f)),
        };
      }),
    };
  }, [doc, libs, geometry, partSwap]);

  const extraBounds = useMemo<Pt[]>(
    () => (geometry && !doc ? geometry.pins.map((p) => [p.at[0], p.at[1]] as Pt) : []),
    [geometry, doc],
  );

  /** Every pin on the sheet, for snapping a wire end and for showing where a
   *  connection can be made. */
  const pins = useMemo(() => {
    if (!doc || !libs) return [] as { at: Pt }[];
    const out: { at: Pt }[] = [];
    for (const s of doc.symbols) for (const p of symbolPins(s, libs)) out.push({ at: p.at });
    return out;
  }, [doc, libs]);

  const snapToPin = useCallback((p: Pt): Pt => {
    let best: Pt | null = null;
    let bestD = PIN_SNAP;
    for (const pin of pins) {
      const d = Math.hypot(pin.at[0] - p[0], pin.at[1] - p[1]);
      if (d < bestD) { bestD = d; best = pin.at; }
    }
    return best ?? snapPt(p);
  }, [pins]);

  const hitSymbol = useCallback((mm: Pt): DocSymbol | null => {
    if (!doc || !libs) return null;
    // Last placed wins, which is what a user expects of the thing on top.
    for (let i = doc.symbols.length - 1; i >= 0; i -= 1) {
      const box = symbolBox(doc.symbols[i], libs);
      if (box && pointInBox(mm, box)) return doc.symbols[i];
    }
    return null;
  }, [doc, libs]);

  const hitAnything = useCallback((mm: Pt): Selection | null => {
    if (!doc) return null;
    const sym = hitSymbol(mm);
    if (sym) return { kind: "symbol", id: sym.id };
    for (const l of doc.labels) {
      if (Math.hypot(l.at[0] - mm[0], l.at[1] - mm[1]) < 1.5) return { kind: "label", id: l.id };
    }
    for (const t of doc.texts) {
      if (Math.abs(t.at[0] - mm[0]) < 30 && Math.abs(t.at[1] - mm[1]) < 3) {
        return { kind: "text", id: t.id };
      }
    }
    for (const w of doc.wires) {
      if (distanceToWire(mm, w.pts) < WIRE_PICK) return { kind: "wire", id: w.id };
    }
    return null;
  }, [doc, hitSymbol]);

  // ------------------------------------------------------------- editing

  const place = (entry: PaletteEntry, at: Pt, angle: number) => {
    if (!doc || !edit) return;
    const sym: DocSymbol = {
      id: newId(),
      lib_id: entry.lib_id,
      at: [at[0], at[1], angle],
      mirror: "",
      unit: 1,
      // An entry with no default value keeps the library's own — which is how
      // a switch's state stays tied to the definition it is drawn as.
      fields: entry.value
        ? { Reference: nextRef(doc, entry.prefix), Value: entry.value }
        : { Reference: nextRef(doc, entry.prefix) },
    };
    edit.onChange({ ...doc, symbols: [...doc.symbols, sym] });
    setSelected({ kind: "symbol", id: sym.id });
  };

  const patchSymbol = (id: string, patch: Partial<DocSymbol>, coalesce = false) => {
    if (!doc || !edit) return;
    edit.onChange({
      ...doc,
      symbols: doc.symbols.map((s) => (s.id === id ? { ...s, ...patch } : s)),
    }, coalesce);
  };

  const setField = (id: string, key: string, value: string) => {
    if (!doc || !edit) return;
    edit.onChange({
      ...doc,
      symbols: doc.symbols.map((s) => (
        s.id === id ? { ...s, fields: { ...s.fields, [key]: value } } : s
      )),
    }, true);
  };

  const remove = (sel: Selection) => {
    if (!doc || !edit) return;
    if (sel.kind === "symbol") edit.onChange({ ...doc, symbols: doc.symbols.filter((s) => s.id !== sel.id) });
    else if (sel.kind === "wire") edit.onChange({ ...doc, wires: doc.wires.filter((w) => w.id !== sel.id) });
    else if (sel.kind === "label") edit.onChange({ ...doc, labels: doc.labels.filter((l) => l.id !== sel.id) });
    else edit.onChange({ ...doc, texts: doc.texts.filter((t) => t.id !== sel.id) });
    setSelected(null);
  };

  const rotate = () => {
    if (placing) { setGhostAngle((a) => (a + 90) % 360); return; }
    if (selected?.kind !== "symbol" || !doc) return;
    const s = doc.symbols.find((x) => x.id === selected.id);
    if (s) patchSymbol(s.id, { at: [s.at[0], s.at[1], (s.at[2] + 90) % 360] });
  };

  const mirror = (axis: "x" | "y") => {
    if (selected?.kind !== "symbol" || !doc) return;
    const s = doc.symbols.find((x) => x.id === selected.id);
    if (s) patchSymbol(s.id, { mirror: s.mirror === axis ? "" : axis });
  };

  /** A drawn run becomes ONE WIRE PER SEGMENT. KiCad's wires are two-point,
   *  and keeping the document the same shape as the file is what lets the
   *  overlay find a wire's net by position. */
  const commitRun = (pts: Pt[]) => {
    if (!doc || !edit) return;
    const made = [];
    for (let i = 0; i + 1 < pts.length; i += 1) {
      const [a, b] = [pts[i], pts[i + 1]];
      if (a[0] === b[0] && a[1] === b[1]) continue;
      made.push({ id: newId(), pts: [a, b] });
    }
    if (made.length) edit.onChange({ ...doc, wires: [...doc.wires, ...made] });
  };

  const onDown = (mm: Pt) => {
    // A press on empty paper dismisses the dialog. The overlay's own click
    // lands AFTER this one, so picking a different part still opens it.
    setPopup(null);
    setMenu(null);
    setProbe(null);
    downHit.current = null;
    if (!editing || !doc) return;
    if (placing) { place(placing, snapPt(mm), ghostAngle); return; }
    if (tool === "wire") {
      const at = snapToPin(mm);
      if (!run) setRun([at]);
      else {
        const pts = [...run.slice(0, -1), ...orthoRun(run[run.length - 1], at)];
        // A wire that reached a pin is finished; one that reached open paper
        // carries on, the way KiCad's wire tool does.
        const onPin = pins.some((p) => p.at[0] === at[0] && p.at[1] === at[1]);
        commitRun(pts);
        setRun(onPin ? null : [at]);
      }
      return;
    }
    if (tool === "label") {
      const at = snapToPin(mm);
      const id = newId();
      edit?.onChange({
        ...doc,
        labels: [...doc.labels, { id, text: `NET${doc.labels.length + 1}`, at: [at[0], at[1], 0], kind: "local" }],
      });
      setSelected({ kind: "label", id });
      setTool("select");
      return;
    }
    if (tool === "text") {
      const at = snapPt(mm);
      const id = newId();
      edit?.onChange({
        ...doc,
        texts: [...doc.texts, { id, at: [at[0], at[1], 0], text: ".tran 10u 5m", h: 1.27 }],
      });
      setSelected({ kind: "text", id });
      setTool("select");
      return;
    }
    const hit = hitAnything(mm);
    setSelected(hit);
    downHit.current = hit;
    if (hit?.kind === "symbol") {
      const s = doc.symbols.find((x) => x.id === hit.id);
      if (s) moving.current = { id: s.id, from: mm, at: [s.at[0], s.at[1]] };
    }
  };

  const onMove = (mm: Pt) => {
    setCursor(mm);
    const m = moving.current;
    if (!m || !doc) return;
    const dx = snapPt([mm[0] - m.from[0], mm[1] - m.from[1]]);
    const s = doc.symbols.find((x) => x.id === m.id);
    if (!s) return;
    const at: [number, number, number] = [m.at[0] + dx[0], m.at[1] + dx[1], s.at[2]];
    if (at[0] !== s.at[0] || at[1] !== s.at[1]) patchSymbol(m.id, { at }, true);
  };

  const copySel = () => {
    const sym = selected?.kind === "symbol" && doc
      ? doc.symbols.find((x) => x.id === selected.id) : null;
    if (sym) clipboard.current = { ...sym, fields: { ...sym.fields } };
  };

  const pasteAt = (p: Pt) => {
    const clip = clipboard.current;
    if (!clip || !doc || !edit) return;
    const at = snapPt(p);
    const prefix = (clip.fields.Reference ?? "").match(/^#?[A-Za-z]+/)?.[0] ?? "U";
    const sym: DocSymbol = {
      ...clip,
      id: newId(),
      at: [at[0], at[1], clip.at[2]],
      fields: { ...clip.fields, Reference: nextRef(doc, prefix) },
    };
    edit.onChange({ ...doc, symbols: [...doc.symbols, sym] });
    setSelected({ kind: "symbol", id: sym.id });
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!editing || !edit) return;
    const meta = e.metaKey || e.ctrlKey;
    if (meta && e.key.toLowerCase() === "z") {
      e.preventDefault();
      if (e.shiftKey) edit.onRedo(); else edit.onUndo();
      return;
    }
    if (meta && e.key.toLowerCase() === "c") { e.preventDefault(); copySel(); return; }
    if (meta && e.key.toLowerCase() === "x") {
      e.preventDefault();
      copySel();
      if (selected?.kind === "symbol") remove(selected);
      return;
    }
    // Pasted under the pointer, which is where the eye already is.
    if (meta && e.key.toLowerCase() === "v") { e.preventDefault(); pasteAt(cursor); return; }
    if (meta) return;
    switch (e.key) {
      case "Escape":
        e.preventDefault();
        setPlacing(null); setRun(null); setTool("select"); setSelected(null); setMenu(null); setProbe(null);
        break;
      case "Delete":
      case "Backspace":
        if (selected) { e.preventDefault(); remove(selected); }
        break;
      case "r": case "R": e.preventDefault(); rotate(); break;
      case "m": case "M": e.preventDefault(); mirror("y"); break;
      case "w": case "W": e.preventDefault(); setPlacing(null); setTool("wire"); break;
      case "l": case "L": e.preventDefault(); setPlacing(null); setTool("label"); break;
      case "t": case "T": e.preventDefault(); setPlacing(null); setTool("text"); break;
      default: {
        const entry = edit.palette.find((p) => p.key === e.key.toLowerCase());
        if (entry) { e.preventDefault(); setTool("select"); setPlacing(entry); }
        break;
      }
    }
  };

  // ------------------------------------------------------------ rendering

  if (!drawing) return null;

  const preview = editing && run
    ? [...run.slice(0, -1), ...orthoRun(run[run.length - 1], snapToPin(cursor))]
    : null;
  const selectedSymbol = selected?.kind === "symbol" && doc
    ? doc.symbols.find((s) => s.id === selected.id) ?? null : null;
  const selectedLabel = selected?.kind === "label" && doc
    ? doc.labels.find((l) => l.id === selected.id) ?? null : null;
  const selectedText = selected?.kind === "text" && doc
    ? doc.texts.find((t) => t.id === selected.id) ?? null : null;
  const selectedBox = selectedSymbol && libs ? symbolBox(selectedSymbol, libs) : null;

  // ------------------------------------------------------- the part dialog

  /** The part the dialog is about. A sketch answers from the document, so a
   *  change writes to the file; a sheet KiCad wrote answers from the parsed
   *  geometry, and only the RUN follows what is typed. */
  const popSym = popup?.id && doc ? doc.symbols.find((x) => x.id === popup.id) ?? null : null;
  const popGeom = popup && popup.index !== null && geometry
    ? geometry.symbols.find((x) => x.index === popup.index) ?? null : null;

  const libProps = popSym && libs ? libs[popSym.lib_id]?.props ?? [] : [];
  const popFacts: PartFacts | null = popSym
    ? {
      ref: popSym.fields.Reference ?? "",
      value: popSym.fields.Value ?? libProps.find((f) => f.k === "Value")?.v ?? "",
      libId: popSym.lib_id,
      // The library's defaults, with whatever this placement overrides on top.
      props: [
        ...libProps.map((f) => ({ k: f.k, v: popSym.fields[f.k] ?? f.v })),
        ...Object.entries(popSym.fields)
          .filter(([k]) => !libProps.some((f) => f.k === k))
          .map(([k, v]) => ({ k, v })),
      ],
      spice: libs ? spiceName(popSym, libs) : "",
    }
    : popGeom
      ? { ref: popGeom.ref, value: popGeom.value, libId: popGeom.lib_id,
          props: popGeom.props ?? [], spice: popGeom.spice }
      : null;

  const popControl = popGeom && controls ? controls.get(popGeom.spice) : undefined;
  const popForms: ParamForm[] = popSym
    ? edit?.palette.find((x) => x.lib_id === popSym.lib_id)?.forms
      // A switch is drawn as one of two definitions, and only one is in the
      // palette.
      ?? edit?.palette.find((x) => x.lib_id === edit.switchPair.open)?.forms
      ?? []
    : popControl
      ? [{
        id: "value",
        label: "Value",
        target: "value",
        template: "{v}",
        fields: [{
          key: "v",
          label: popControl.kind === "source" ? "Source" : "Value",
          unit: popControl.unit,
          default: popControl.value,
          scale: "text",
          min: 0,
          max: 0,
          // ngspice accepts `alter` on a waveform and silently keeps the old
          // script, so a harness-driven source is marked as needing a re-run
          // rather than pretending to move.
          live: popControl.kind !== "scripted",
        }],
      }]
      : [];

  const popLive = onAlter && popFacts?.spice
    ? (_f: ParamField, v: string) => onAlter(`alter ${popFacts.spice} = ${v}`)
    : undefined;

  /** Right-click: select what is under the pointer and offer its verbs. */
  const onMenu = (e: React.MouseEvent) => {
    if (!editing || !doc) return;
    e.preventDefault();
    const box = frame.current?.getBoundingClientRect();
    const view = viewRef.current;
    if (!box || !view || !box.width || !box.height) return;
    const mm: Pt = [
      view.x + ((e.clientX - box.left) / box.width) * view.w,
      view.y + ((e.clientY - box.top) / box.height) * view.h,
    ];
    const hit = hitAnything(mm);
    setSelected(hit);
    setPopup(null);
    setMenu({ ...framePoint(e), mm, sel: hit });
  };

  const ghostLib = placing && libs ? libs[placing.lib_id] : null;
  const size: [number, number] = doc ? PAPER : [geometry!.size[0], geometry!.size[1]];

  return (
    <>
      {editing && edit ? (
        <div className="toolbar sch-tools">
          <div className="seg">
            {(["select", "wire", "label", "text"] as Tool[]).map((t) => (
              <button
                key={t}
                type="button"
                className={tool === t && !placing ? "on" : ""}
                onClick={() => { setPlacing(null); setRun(null); setTool(t); }}
                title={t === "wire" ? "Draw wires (W)" : t === "label" ? "Name a net (L)"
                  : t === "text" ? "SPICE directive (T)" : "Select and move"}
              >
                {t === "select" ? "Select" : t === "wire" ? "Wire" : t === "label" ? "Label" : "Directive"}
              </button>
            ))}
          </div>
          <div className="seg sch-palette">
            {edit.palette.map((p) => (
              <button
                key={p.lib_id}
                type="button"
                className={placing?.lib_id === p.lib_id ? "on" : ""}
                // Always arm, never toggle: after dropping a part the tool
                // stays armed the way KiCad's does, so reaching for the same
                // button again means "another one", not "stop".
                onClick={() => { setTool("select"); setRun(null); setPlacing(p); }}
                title={`${p.label} (${p.key.toUpperCase()})`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button type="button" className="ghost" onClick={edit.onUndo} disabled={!edit.canUndo} title="Undo (Ctrl+Z)">Undo</button>
          <button type="button" className="ghost" onClick={edit.onRedo} disabled={!edit.canRedo} title="Redo (Ctrl+Shift+Z)">Redo</button>
        </div>
      ) : null}

      <div className="card schview" ref={frame} onContextMenu={onMenu}>
        <SchematicView
          fill
          drawing={drawing}
          theme={theme}
          size={size}
          fit={doc ? openFit : fit}
          initialView={doc && !openFit ? OPENING_VIEW : undefined}
          resetKey={doc ? doc.uuid : geometry?.instance_path ?? ""}
          extraBounds={extraBounds}
          tabIndex={editing ? 0 : undefined}
          cursor={editing && (placing || tool !== "select") ? "crosshair" : "default"}
          leftPan={editing ? (mm) => !placing && tool === "select" && !hitAnything(mm) : true}
          onPointerDownMm={onDown}
          onPointerMoveMm={onMove}
          onPointerUpMm={(_mm, _e, moved) => {
            moving.current = null;
            overlay.dragged.current = moved;
          }}
          onDoubleClickMm={(mm, e) => {
            if (run) { commitRun(preview ?? []); setRun(null); return; }
            // Falstad's grammar: click selects, double-click opens the part.
            if (editing && doc && tool === "select" && !placing) {
              const hit = hitAnything(mm);
              if (hit?.kind === "symbol") setPopup({ index: null, id: hit.id, ...framePoint(e) });
            }
          }}
          onKeyDown={onKey}
          onView={(v) => { viewRef.current = v; overlay.onView(v); }}
          layers={overlay.layers}
          underlay={(view) => {
            // Only when a dot is far enough apart to read. Zoomed out they
            // merge into a fog that hides the circuit.
            if (!editing || view.w > 220) return null;
            const dots = [];
            const x0 = Math.ceil(view.x / GRID_DOTS) * GRID_DOTS;
            const y0 = Math.ceil(view.y / GRID_DOTS) * GRID_DOTS;
            for (let x = x0; x < view.x + view.w; x += GRID_DOTS) {
              for (let y = y0; y < view.y + view.h; y += GRID_DOTS) {
                dots.push(<circle key={`${x},${y}`} cx={x} cy={y} r={0.12} />);
              }
            }
            return <g className="sch-grid">{dots}</g>;
          }}
        >
          {overlay.inside}
          {/* Where a wire can attach. Drawn only while wiring, because a pin
              dot on every part is noise once the circuit is joined up. */}
          {editing && tool === "wire" ? pins.map((p, i) => (
            <circle key={i} className="sch-pinspot" cx={p.at[0]} cy={p.at[1]} r={0.55} />
          )) : null}
          {preview ? (
            <polyline className="sch-preview" points={preview.map((p) => `${p[0]},${p[1]}`).join(" ")} />
          ) : null}
          {popGeom?.bbox ? (
            <rect
              className="sim-part-open"
              x={popGeom.bbox[0]}
              y={popGeom.bbox[1]}
              width={popGeom.bbox[2] - popGeom.bbox[0]}
              height={popGeom.bbox[3] - popGeom.bbox[1]}
            />
          ) : null}
          {selectedBox ? (
            <rect
              className="sch-selected"
              x={selectedBox[0]}
              y={selectedBox[1]}
              width={selectedBox[2] - selectedBox[0]}
              height={selectedBox[3] - selectedBox[1]}
            />
          ) : null}
          {selected?.kind === "wire" && doc ? doc.wires.filter((w) => w.id === selected.id).map((w) => (
            <polyline key={w.id} className="sch-selected-wire" points={w.pts.map((p) => `${p[0]},${p[1]}`).join(" ")} />
          )) : null}
          {ghostLib ? (
            <g className="sch-ghost" transform={`translate(${snapPt(cursor)[0]} ${snapPt(cursor)[1]}) rotate(${-ghostAngle})`}>
              <circle cx={0} cy={0} r={1} />
              {ghostLib.pins.map((p, i) => (
                <line key={i} x1={p.at[0]} y1={-p.at[1]} x2={0} y2={0} />
              ))}
            </g>
          ) : null}
        </SchematicView>
        {reader ? (
          <p className="muted sim-caption">
            {/* An operating point has no sweep axis at all: its "scale" is
                whichever vector ngspice listed first, so printing a position
                for one invents a frequency out of a node voltage. */}
            {reader.scaleType === "time"
              ? `t = ${eng(reader.position, "s")}`
              : reader.scaleType === "frequency"
                ? `f = ${eng(reader.position, "Hz")}`
                : "one operating point"}
            {" · click selects a net, double-click plots it · scroll to zoom, drag to pan"}
          </p>
        ) : null}

        {popup && popFacts ? (
          <PartPopup
            key={popup.id ?? popup.index ?? "part"}
            part={popFacts}
            at={{ x: popup.x, y: popup.y }}
            forms={popForms}
            value={popSym
              ? popSym.fields.Value ?? libProps.find((f) => f.k === "Value")?.v ?? ""
              : popGeom?.value ?? ""}
            params={popSym
              ? popSym.fields["Sim.Params"] ?? libProps.find((f) => f.k === "Sim.Params")?.v ?? ""
              : popGeom?.sim?.params ?? ""}
            onValue={popSym ? (v: string) => setField(popSym.id, "Value", v) : undefined}
            onParams={popSym ? (v: string) => setField(popSym.id, "Sim.Params", v) : undefined}
            onLive={popLive}
            readOnly={!popSym}
            onClose={() => setPopup(null)}
          >
            {popSym && doc && edit ? (
              <>
                {edit.palette.find((x) => x.lib_id === popSym.lib_id)?.sim === "power"
                  || libs?.[popSym.lib_id]?.power ? (
                  /* A power symbol IS its net: the editable thing is the net
                     it drives, not the #PWR bookkeeping reference. */
                    <label className="sim-knob">
                      <span>Net</span>
                      <input
                        className="text"
                        value={popSym.fields.Value ?? libProps.find((f) => f.k === "Value")?.v ?? ""}
                        onChange={(e) => setField(popSym.id, "Value", e.target.value)}
                      />
                    </label>
                  ) : (
                    <label className="sim-knob">
                      <span>Reference</span>
                      <input
                        className="text"
                        value={popSym.fields.Reference ?? ""}
                        onChange={(e) => setField(popSym.id, "Reference", e.target.value)}
                      />
                    </label>
                  )}
                <div className="sim-knobs part-popup-actions">
                  {popSym.lib_id === edit.switchPair.open
                    || popSym.lib_id === edit.switchPair.closed ? (
                    <div className="seg" role="group" aria-label="Contact">
                      {([["closed", edit.switchPair.closed], ["open", edit.switchPair.open]] as const).map(([name, id]) => (
                        <button
                          key={name}
                          type="button"
                          className={popSym.lib_id === id ? "on" : ""}
                          // Drop the overrides with the swap: the state lives in
                          // the library definition, so the drawing, the Value and
                          // the resistance move together or not at all.
                          onClick={() => edit.onChange({
                            ...doc,
                            symbols: doc.symbols.map((x) => (x.id === popSym.id
                              ? { ...x, lib_id: id, fields: { Reference: x.fields.Reference ?? "" } }
                              : x)),
                          })}
                        >
                          {name}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {onPickPart && popSym && geometry ? (() => {
                    const geomSym = geometry.symbols.find(
                      (x) => x.ref === (popSym.fields.Reference ?? "") && !x.power,
                    );
                    return geomSym ? (
                      <button type="button" onClick={() => onPickPart(geomSym.index)}>
                        Plot current
                      </button>
                    ) : null;
                  })() : null}
                  {editing ? (
                    <>
                      <button type="button" className="ghost" onClick={rotate}>Rotate</button>
                      <button type="button" className="ghost" onClick={() => mirror("y")}>Mirror</button>
                      <button
                        type="button"
                        className="ghost"
                        onClick={() => { remove({ kind: "symbol", id: popSym.id }); setPopup(null); }}
                      >
                        Delete
                      </button>
                    </>
                  ) : null}
                </div>
              </>
            ) : null}
            {/* A contact on a sheet KiCad wrote has no second definition to be
                drawn as, so it is thrown by resistance instead. */}
            {!popSym && popGeom && onFlip && parts?.get(popGeom.index)?.kind === "switch" ? (
              <div className="sim-knobs part-popup-actions">
                <button type="button" onClick={() => onFlip(popGeom.index)}>
                  {parts.get(popGeom.index)?.on ? "Open the contact" : "Close the contact"}
                </button>
              </div>
            ) : null}
          </PartPopup>
        ) : null}
        {probe ? (
          <div className="sim-menu" style={{ left: probe.x, top: probe.y }}>
            {probe.pin ? (
              <>
                <button
                  type="button"
                  onClick={() => { if (probe.pin) onProbePin?.(probe.pin, "v"); setProbe(null); }}
                >
                  Plot voltage
                </button>
                <button
                  type="button"
                  onClick={() => { if (probe.pin) onProbePin?.(probe.pin, "i"); setProbe(null); }}
                >
                  Plot pin current
                </button>
                <button
                  type="button"
                  onClick={() => { if (probe.pin) onProbePin?.(probe.pin, "both"); setProbe(null); }}
                >
                  Plot both
                </button>
              </>
            ) : probe.net ? (
              <>
                <button
                  type="button"
                  onClick={() => { if (probe.net) onProbeNet?.(probe.net, probe.wireId, "v"); setProbe(null); }}
                >
                  Plot voltage
                </button>
                <button
                  type="button"
                  disabled={!probe.wireId}
                  onClick={() => { if (probe.net) onProbeNet?.(probe.net, probe.wireId, "i"); setProbe(null); }}
                >
                  Plot wire current
                </button>
                <button
                  type="button"
                  onClick={() => { if (probe.net) onProbeNet?.(probe.net, probe.wireId, "both"); setProbe(null); }}
                >
                  Plot both
                </button>
              </>
            ) : null}
          </div>
        ) : null}
        {menu && editing && doc ? (
          <div className="sim-menu" style={{ left: menu.x, top: menu.y }}>
            {menu.sel?.kind === "symbol" ? (
              <>
                <button type="button" onClick={() => { copySel(); setMenu(null); }}>Copy</button>
                <button type="button" onClick={() => { copySel(); if (menu.sel) remove(menu.sel); setMenu(null); }}>Cut</button>
                <button type="button" onClick={() => { rotate(); setMenu(null); }}>Rotate</button>
                <button type="button" onClick={() => { mirror("y"); setMenu(null); }}>Mirror</button>
                <button type="button" onClick={() => { if (menu.sel) remove(menu.sel); setMenu(null); }}>Delete</button>
                <button
                  type="button"
                  onClick={() => { setPopup({ index: null, id: menu.sel?.id ?? null, x: menu.x, y: menu.y }); setMenu(null); }}
                >
                  Properties…
                </button>
              </>
            ) : menu.sel ? (
              <button type="button" onClick={() => { if (menu.sel) remove(menu.sel); setMenu(null); }}>Delete</button>
            ) : null}
            <button
              type="button"
              disabled={!clipboard.current}
              onClick={() => { pasteAt(menu.mm); setMenu(null); }}
            >
              Paste
            </button>
          </div>
        ) : null}
      </div>

      {/* Only when it has something to SAY: a label or directive being
          edited, or the how-to on an empty sheet. A part's dialog opens on
          the part, and a standing hint under a working circuit was the
          tallest decoration on the page. */}
      {editing && edit && doc && (selectedLabel || selectedText || !doc.symbols.length) ? (
        <div className="card pad sch-props">
          {selectedLabel ? (
            <label className="sim-knob">
              <span>Net name</span>
              <input
                className="text"
                value={selectedLabel.text}
                onChange={(e) => edit.onChange({
                  ...doc,
                  labels: doc.labels.map((l) => (l.id === selectedLabel.id ? { ...l, text: e.target.value } : l)),
                }, true)}
              />
            </label>
          ) : selectedText ? (
            <label className="sim-knob sch-directive">
              <span>SPICE directive</span>
              <textarea
                className="text"
                rows={4}
                value={selectedText.text}
                onChange={(e) => edit.onChange({
                  ...doc,
                  texts: doc.texts.map((t) => (t.id === selectedText.id ? { ...t, text: e.target.value } : t)),
                }, true)}
              />
            </label>
          ) : (
            <p className="muted">
              Click the drawing, then a part key to place it — {edit.palette.map((p) => p.key.toUpperCase()).join(" ")} —
              or <span className="mono">W</span> to wire, <span className="mono">L</span> to name a net,{" "}
              <span className="mono">T</span> for a SPICE directive. <span className="mono">R</span> rotates,{" "}
              <span className="mono">M</span> mirrors, Delete removes. Ground is the part that makes a circuit
              solvable — every schematic needs one.
            </p>
          )}
        </div>
      ) : null}
    </>
  );
}
