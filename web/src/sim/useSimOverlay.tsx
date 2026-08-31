/** The simulation drawn on top of a schematic, as layers anyone can reuse.
 *
 *  It exists because two views need the same overlay: the read-only simulator
 *  (a schematic that came from KiCad) and the editor (one being drawn). A
 *  second copy of the tint, the charge and the click targets would be a second
 *  chance for them to disagree about what a wire is worth.
 *
 *  Everything is in the sheet's millimetres. `inside` goes into the sheet's
 *  own SVG; `layers` is stacked over the frame and is given the live viewport,
 *  because a canvas cannot inherit a viewBox.
 */
import { useCallback, useEffect, useMemo, useRef } from "react";
import type { SimGeometry } from "../api";
import { solveSegmentCurrents } from "./currents";
import { eng, type Range, type SampleReader } from "./payload";
import type { View } from "./draw/SchematicView";

/** Millimetres between charge dots along a wire. */
const DOT_SPACING = 3.2;
/** Millimetres a dot travels per second at the peak current of the run. */
const DOT_SPEED = 14;
/** Below this peak there is no current worth drawing, in amps. Every dot is
 *  sized against the largest current in the run, so a circuit whose biggest
 *  current is the leakage through an open contact would otherwise be drawn
 *  flowing at full speed everywhere. */
const CURRENT_FLOOR = 1e-9;

export interface Options {
  geometry: SimGeometry | null;
  /** Where the values come from — a finished run, or a live frame. */
  reader: SampleReader | null;
  /** Seconds of wall clock since the run started playing; drives the dots. */
  clock: number;
  running: boolean;
  voltageRange: Range;
  currentPeak: number;
  selectedNet: string | null;
  onPickNet: (net: string | null) => void;
  onUnresolved: (items: { net: string; reason: string }[]) => void;
  /** Parts a live run can steer, by geometry symbol index. */
  parts?: Map<number, { title: string; kind: string; on?: boolean }>;
  onPickPart?: (index: number) => void;
  /** Nothing is clickable while a drawing tool has the pointer. */
  interactive?: boolean;
  /** Draw the wires of THIS document instead of the geometry's own — the
   *  editor's document is ahead of the last save, and the tint has to land on
   *  the wire the user is looking at. Index-aligned, or the overlay is
   *  dropped rather than drawn in the wrong place. */
  wires?: { id: string; pts: number[][] }[];
}

export interface Overlay {
  /** Drawn inside the sheet's SVG. */
  inside: React.ReactNode;
  /** Stacked over the frame; takes the live viewport. */
  layers: (view: View) => React.ReactNode;
  onView: (view: View) => void;
  /** True when a click that moved should not count as a pick. */
  dragged: React.MutableRefObject<boolean>;
}

export default function useSimOverlay({
  geometry, reader, clock, running, voltageRange, currentPeak,
  selectedNet, onPickNet, onUnresolved, parts, onPickPart,
  interactive = true, wires,
}: Options): Overlay {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const viewRef = useRef<View | null>(null);
  const dragged = useRef(false);

  const groupsById = useMemo(
    () => new Map((geometry?.groups ?? []).map((g) => [g.id, g])),
    [geometry],
  );

  const solved = useMemo(
    () => (geometry && reader ? solveSegmentCurrents(geometry, reader) : null),
    [geometry, reader],
  );

  useEffect(() => {
    onUnresolved(solved?.unresolved ?? []);
  }, [solved, onUnresolved]);

  /** The wires to draw on. The editor's document leads the last save, so the
   *  geometry's own wires would be a frame behind — but only a document whose
   *  wire COUNT still matches can be trusted to line up, because the tint is
   *  matched by position in the list. */
  const drawn = useMemo(() => {
    const own = geometry?.wires ?? [];
    if (!wires) return own.map((w, i) => ({ pts: w.pts, geom: own[i] }));
    if (wires.length !== own.length) return null;
    return wires.map((w, i) => ({ pts: w.pts, geom: own[i] }));
  }, [geometry, wires]);

  /** Voltage -> a colour between the cold and hot ends of the palette.
   *  color-mix keeps the two ends as CSS variables, so the overlay follows
   *  the theme instead of carrying its own hex codes. */
  const tint = useCallback((group: string): string | null => {
    if (!reader) return null;
    const g = groupsById.get(group);
    const v = reader.voltage(g?.spice, g?.ground);
    if (v === null) return null;
    const span = Math.max(Math.abs(voltageRange.min), Math.abs(voltageRange.max)) || 1;
    const share = Math.min(100, Math.round((Math.abs(v) / span) * 100));
    const end = v >= 0 ? "var(--sim-hot)" : "var(--sim-cold)";
    return `color-mix(in oklab, ${end} ${share}%, var(--sim-zero))`;
  }, [reader, groupsById, voltageRange]);

  const readout = useCallback((net: string | null, group: string): string => {
    if (!net) return "";
    const g = groupsById.get(group);
    if (g?.derived) {
      return `${net} — a label the netlist does not carry, so nothing simulates it`;
    }
    if (!reader) return net;
    const v = reader.voltage(g?.spice, g?.ground);
    return v === null ? `${net} — not in this run` : `${net} = ${eng(v, "V")}`;
  }, [groupsById, reader]);

  // The dots. An imperative loop keyed on `clock` so React never re-renders
  // for an animation frame.
  const paint = useCallback((view: View | null) => {
    const canvas = canvasRef.current;
    if (!canvas || !view) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const ratio = window.devicePixelRatio || 1;
    const box = canvas.getBoundingClientRect();
    if (canvas.width !== Math.round(box.width * ratio)) {
      canvas.width = Math.round(box.width * ratio);
      canvas.height = Math.round(box.height * ratio);
    }
    const scale = (canvas.width / view.w) || 1;
    ctx.setTransform(scale, 0, 0, scale, -view.x * scale, -view.y * scale);
    ctx.clearRect(view.x, view.y, view.w, view.h);
    if (!reader || !solved || !drawn || currentPeak < CURRENT_FLOOR) return;

    const style = getComputedStyle(canvas);
    ctx.fillStyle = style.getPropertyValue("--sim-current").trim() || "currentColor";

    for (const wire of drawn) {
      const perSegment = solved.segments.get(wire.geom.id);
      if (!perSegment) continue;
      for (let i = 0; i + 1 < wire.pts.length; i += 1) {
        const current = perSegment[i] ?? 0;
        const share = Math.abs(current) / currentPeak;
        if (share < 0.004) continue;
        const [ax, ay] = wire.pts[i];
        const [bx, by] = wire.pts[i + 1];
        const dx = bx - ax;
        const dy = by - ay;
        const length = Math.hypot(dx, dy);
        if (length < 0.01) continue;
        const direction = current >= 0 ? 1 : -1;
        const travel = clock * DOT_SPEED * share * direction;
        let offset = travel % DOT_SPACING;
        if (offset < 0) offset += DOT_SPACING;
        for (let d = offset; d < length; d += DOT_SPACING) {
          const t = d / length;
          ctx.beginPath();
          ctx.arc(ax + dx * t, ay + dy * t, 0.55, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }, [drawn, reader, solved, clock, currentPeak]);

  useEffect(() => {
    paint(viewRef.current);
  }, [paint, running]);

  const onView = useCallback((view: View) => {
    viewRef.current = view;
    paint(view);
  }, [paint]);

  const pick = (net: string | null) => {
    if (dragged.current) return;
    onPickNet(net === selectedNet ? null : net);
  };

  const inside = !geometry || !drawn ? null : (
    <g className="sim-tint">
      {drawn.map((wire) => {
        const colour = tint(wire.geom.group);
        if (!colour) return null;
        return (
          <polyline
            key={`v${wire.geom.id}`}
            className="sim-wire"
            points={wire.pts.map((p) => `${p[0]},${p[1]}`).join(" ")}
            stroke={colour}
          />
        );
      })}
      {wires ? null : geometry.junctions.map((j, i) => {
        const colour = tint(j.group);
        if (!colour) return null;
        return (
          <circle key={`j${i}`} className="sim-junction" cx={j.at[0]} cy={j.at[1]} r={0.6} fill={colour} />
        );
      })}
    </g>
  );

  const layers = (view: View) => (
    <>
      <canvas className="sim-layer sim-charge" ref={canvasRef} />
      {geometry && drawn ? (
        <svg
          className="sim-layer sim-pick"
          viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
          preserveAspectRatio="xMidYMid meet"
          role="group"
          aria-label="Nets"
          style={interactive ? undefined : { pointerEvents: "none" }}
        >
          {drawn.map((wire) => (
            <polyline
              key={`p${wire.geom.id}`}
              className={`sim-hit${selectedNet && wire.geom.net === selectedNet ? " on" : ""}`}
              points={wire.pts.map((p) => `${p[0]},${p[1]}`).join(" ")}
              onClick={() => pick(wire.geom.net)}
            >
              <title>{readout(wire.geom.net, wire.geom.group)}</title>
            </polyline>
          ))}
          {parts ? geometry.symbols.map((sym) => {
            const part = parts.get(sym.index);
            if (!part || !sym.bbox) return null;
            return (
              <rect
                key={`part${sym.index}`}
                className={`sim-part${part.on ? " on" : ""} ${part.kind}`}
                x={sym.bbox[0]}
                y={sym.bbox[1]}
                width={sym.bbox[2] - sym.bbox[0]}
                height={sym.bbox[3] - sym.bbox[1]}
                onClick={() => { if (!dragged.current) onPickPart?.(sym.index); }}
              >
                <title>{part.title}</title>
              </rect>
            );
          }) : null}
          {geometry.pins.map((pin) => {
            const current = solved?.pins.get(`${pin.ref}.${pin.pin}`);
            if (current === undefined) return null;
            return (
              <circle
                key={`pin${pin.ref}.${pin.pin}`}
                className="sim-pin"
                cx={pin.at[0]}
                cy={pin.at[1]}
                r={0.9}
              >
                <title>{`${pin.ref} pin ${pin.pin} — ${eng(current, "A")} into the part`}</title>
              </circle>
            );
          })}
        </svg>
      ) : null}
    </>
  );

  return { inside, layers, onView, dragged };
}
