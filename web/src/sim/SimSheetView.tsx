/** The drawing with the simulation on top of it.
 *
 *  Three layers share one coordinate space — millimetres, straight out of the
 *  `.kicad_sch` — because kicad-cli's SVG viewBox is in millimetres too. So
 *  nothing here transforms anything:
 *
 *    1. `<img>`   the sheet as KiCad draws it
 *    2. `<svg>`   wires tinted by node voltage, plus the click targets
 *    3. `<canvas>` the moving charge, redrawn every animation frame
 *
 *  The dots live on a canvas rather than in the SVG on purpose: a sheet with a
 *  few hundred wires carries thousands of them, and re-creating that many DOM
 *  nodes sixty times a second is what makes a page like this stutter.
 */
import { useEffect, useMemo, useRef } from "react";
import type { SimGeometry } from "../api";
import { solveSegmentCurrents } from "./currents";
import { eng, type Range, type SampleReader } from "./payload";

interface Props {
  geometry: SimGeometry;
  /** Crop to the drawing instead of showing the whole (mostly empty) page. */
  fit: boolean;
  svgUrl: string;
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
}

/** Millimetres between charge dots along a wire. */
const DOT_SPACING = 3.2;
/** Millimetres a dot travels per second at the peak current of the run. */
const DOT_SPEED = 14;

export default function SimSheetView({
  geometry,
  fit,
  svgUrl,
  reader,
  clock,
  running,
  voltageRange,
  currentPeak,
  selectedNet,
  onPickNet,
  onUnresolved,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [width, height] = geometry.size;

  /** What the sheet actually uses, in millimetres. A KiCad page is mostly
   *  empty paper, and a circuit shown at page scale is unreadable. */
  const content = useMemo(() => {
    let x1 = Infinity;
    let y1 = Infinity;
    let x2 = -Infinity;
    let y2 = -Infinity;
    const add = (x: number, y: number) => {
      if (x < x1) x1 = x;
      if (y < y1) y1 = y;
      if (x > x2) x2 = x;
      if (y > y2) y2 = y;
    };
    for (const wire of geometry.wires) for (const pt of wire.pts) add(pt[0], pt[1]);
    for (const pin of geometry.pins) add(pin.at[0], pin.at[1]);
    for (const label of geometry.labels) add(label.at[0], label.at[1]);
    for (const text of geometry.texts) add(text.at[0], text.at[1]);
    for (const sub of geometry.subsheets) {
      add(sub.at[0], sub.at[1]);
      add(sub.at[0] + sub.size[0], sub.at[1] + sub.size[1]);
    }
    for (const sym of geometry.symbols) {
      if (!sym.bbox) continue;
      add(sym.bbox[0], sym.bbox[1]);
      add(sym.bbox[2], sym.bbox[3]);
    }
    if (!Number.isFinite(x1)) return { x: 0, y: 0, w: width, h: height };
    // Generous, because a text item and a label are anchored at a point and
    // then run past it — the box knows where they start, not how far they go.
    const margin = 14;
    const x = Math.max(0, x1 - margin);
    const y = Math.max(0, y1 - margin);
    return {
      x,
      y,
      w: Math.min(width - x, x2 - x1 + 2 * margin),
      h: Math.min(height - y, y2 - y1 + 2 * margin),
    };
  }, [geometry, width, height]);

  // Percentages, so the crop follows the container without any pixel maths:
  // the inner stage is blown up by `zoom` and slid so the content's corner
  // lands at the top left.
  const zoom = fit ? width / content.w : 1;
  const stage = fit
    ? {
        width: `${zoom * 100}%`,
        left: `${-(content.x / width) * zoom * 100}%`,
        top: `${-(content.y / content.h) * 100}%`,
      }
    : { width: "100%", left: "0%", top: "0%" };
  const frameRatio = fit ? `${content.w} / ${content.h}` : `${width} / ${height}`;

  const groupsById = useMemo(
    () => new Map(geometry.groups.map((g) => [g.id, g])),
    [geometry.groups],
  );

  const solved = useMemo(
    () => (reader ? solveSegmentCurrents(geometry, reader) : null),
    [geometry, reader],
  );

  useEffect(() => {
    onUnresolved(solved?.unresolved ?? []);
  }, [solved, onUnresolved]);

  /** Voltage -> a colour between the cold and hot ends of the palette.
   *  color-mix keeps the two ends as CSS variables, so the overlay follows
   *  the theme instead of carrying its own hex codes. */
  const tint = (group: string): string | null => {
    if (!reader) return null;
    const g = groupsById.get(group);
    const v = reader.voltage(g?.spice, g?.ground);
    if (v === null) return null;
    const span = Math.max(Math.abs(voltageRange.min), Math.abs(voltageRange.max)) || 1;
    const share = Math.min(100, Math.round((Math.abs(v) / span) * 100));
    const end = v >= 0 ? "var(--sim-hot)" : "var(--sim-cold)";
    return `color-mix(in oklab, ${end} ${share}%, var(--sim-zero))`;
  };

  const readout = (net: string | null, group: string): string => {
    if (!net) return "";
    const g = groupsById.get(group);
    if (g?.derived) {
      return `${net} — a label the netlist does not carry, so nothing simulates it`;
    }
    if (!reader) return net;
    const v = reader.voltage(g?.spice, g?.ground);
    return v === null ? `${net} — not in this run` : `${net} = ${eng(v, "V")}`;
  };

  // The dots. An imperative loop keyed on `clock` so React never re-renders
  // for an animation frame.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const ratio = window.devicePixelRatio || 1;
    const box = canvas.getBoundingClientRect();
    if (canvas.width !== Math.round(box.width * ratio)) {
      canvas.width = Math.round(box.width * ratio);
      canvas.height = Math.round(box.height * ratio);
    }
    const scale = (canvas.width / width) || 1;
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (!reader || !solved || currentPeak <= 0) return;

    const style = getComputedStyle(canvas);
    ctx.fillStyle = style.getPropertyValue("--sim-current").trim() || "currentColor";
    const radius = Math.max(0.35, 0.55);

    for (const wire of geometry.wires) {
      const perSegment = solved.segments.get(wire.id);
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
          ctx.arc(ax + dx * t, ay + dy * t, radius, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }, [geometry, reader, solved, clock, currentPeak, width, height, running]);

  return (
    <div className="card schview">
      <div className="sim-frame" style={{ aspectRatio: frameRatio }}>
        <div className="overlay-wrap sim-stage" style={stage}>
          <img src={svgUrl} alt={`Sheet ${geometry.sheet.name}`} />
          <svg
          className="sim-layer"
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {geometry.wires.map((wire) => {
            const colour = tint(wire.group);
            if (!colour) return null;
            return (
              <polyline
                key={`v${wire.id}`}
                className="sim-wire"
                points={wire.pts.map((p) => `${p[0]},${p[1]}`).join(" ")}
                stroke={colour}
              />
            );
          })}
          {geometry.junctions.map((j, i) => {
            const colour = tint(j.group);
            if (!colour) return null;
            return (
              <circle key={`j${i}`} className="sim-junction" cx={j.at[0]} cy={j.at[1]} r={0.6} fill={colour} />
            );
          })}
        </svg>
          <canvas className="sim-layer sim-charge" ref={canvasRef} />
          <svg
          className="sim-layer sim-pick"
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          role="group"
          aria-label="Nets"
        >
          {geometry.wires.map((wire) => (
            <polyline
              key={`p${wire.id}`}
              className={`sim-hit${selectedNet && wire.net === selectedNet ? " on" : ""}`}
              points={wire.pts.map((p) => `${p[0]},${p[1]}`).join(" ")}
              onClick={() => onPickNet(wire.net === selectedNet ? null : wire.net)}
            >
              <title>{readout(wire.net, wire.group)}</title>
            </polyline>
          ))}
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
        </div>
      </div>
      {reader ? (
        <p className="muted sim-caption">
          {reader.scaleType === "time"
            ? `t = ${eng(reader.position, "s")}`
            : `f = ${eng(reader.position, "Hz")}`}
          {" · click a wire to plot it"}
        </p>
      ) : null}
    </div>
  );
}
