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
/** Millimetres a dot travels per second at the peak current of the run, at
 *  the speed the user has the knob on. */
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
  /** Volts at which the tint saturates. 0 means "use the run's own range". */
  voltRef?: number;
  selectedNet: string | null;
  /** `wireId` is the SEGMENT that was clicked, so its own current can go on the
   *  scope beside the net's voltage. A net has no current; a wire does. */
  /** A single click: select/deselect only. */
  onPickNet: (net: string | null, wireId?: string) => void;
  /** A DOUBLE click on a wire or pin: the caller opens a chooser at the
   *  pointer and decides what lands on the scope. */
  onProbe?: (probe: {
    net: string | null;
    wireId?: string;
    pin?: { ref: string; pin: string; group: string };
    e: React.MouseEvent;
  }) => void;
  onUnresolved: (items: { net: string; reason: string }[]) => void;
  /** Parts a live run can steer, by geometry symbol index. */
  parts?: Map<number, { title: string; kind: string; on?: boolean }>;
  /** Clicking a part opens its dialog, so the hotspot exists for EVERY part
   *  with a body — not only for the ones a live run can steer. `parts` only
   *  decorates it (a contact draws as open or closed, and says so). */
  onPickPart?: (index: number, e: React.MouseEvent) => void;
  /** A terminal picked on the drawing. A pin has BOTH a voltage and a current
   *  — the net it sits on says the first, the net around it says the second —
   *  and on a part with more than two legs it is the only place either can be
   *  asked for. */
  onPickPin?: (pin: { ref: string; pin: string; group: string }) => void;
  /** How fast the charge dots travel, as a multiple of the default. Zero
   *  stops them where they are — the tint still says what every net is
   *  worth, and a still picture is the right one for a screenshot. */
  currentSpeed?: number;
  /** Nothing is clickable while a drawing tool has the pointer. */
  interactive?: boolean;
  /** Draw the wires of THIS document instead of the geometry's own — the
   *  editor's document is ahead of the last save, and the tint has to land on
   *  the wire the user is looking at. Matched to the file BY POSITION, never
   *  by list index: see `drawn`. */
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
  geometry, reader, clock, running, voltageRange, currentPeak, voltRef = 0,
  selectedNet, onPickNet, onProbe, onUnresolved, parts, onPickPart, onPickPin,
  currentSpeed = 1, interactive = true, wires,
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

  /** The wires to draw on, each paired with the net the file says it carries.
   *
   *  The editor's document leads the last save, so the geometry's own wires
   *  would be a frame behind. But the two lists have DIFFERENT SHAPES: a
   *  document holds runs, a `.kicad_sch` holds one two-point wire per segment
   *  (`sch_write._wires`), so a run with a single bend already makes the
   *  counts differ. Pairing them by list index and dropping the overlay when
   *  the lengths disagree therefore dropped it always — no tint, no charge, and
   *  no click targets on any circuit drawn here with a bent wire. Measured on
   *  the worked example: 26 runs against 36 wires.
   *
   *  So match by POSITION. A segment's two endpoints name exactly one wire in
   *  the file, and a segment the file has not caught up with simply goes
   *  untinted instead of taking the whole overlay with it.
   */
  const drawn = useMemo(() => {
    const own = geometry?.wires ?? [];
    if (!wires) return own.map((w) => ({ pts: w.pts, geom: w }));
    const at = (v: number) => Math.round(v * 1000);
    const key = (a: number[], b: number[]) => {
      const flip = at(a[0]) > at(b[0]) || (at(a[0]) === at(b[0]) && at(a[1]) > at(b[1]));
      const [p, q] = flip ? [b, a] : [a, b];
      return `${at(p[0])},${at(p[1])}|${at(q[0])},${at(q[1])}`;
    };
    const byEnds = new Map<string, (typeof own)[number]>();
    for (const w of own) {
      if (w.pts.length === 2) byEnds.set(key(w.pts[0], w.pts[1]), w);
    }
    const out: { pts: number[][]; geom: (typeof own)[number] }[] = [];
    for (const run of wires) {
      for (let i = 0; i + 1 < run.pts.length; i += 1) {
        const geom = byEnds.get(key(run.pts[i], run.pts[i + 1]));
        if (geom) out.push({ pts: [run.pts[i], run.pts[i + 1]], geom });
      }
    }
    return out;
  }, [geometry, wires]);

  /** Voltage -> a colour, on Falstad's convention: GREEN above ground, RED
   *  below it, and nothing at all at zero.
   *
   *  The scale saturates at a reference the user sets, not at the run's own
   *  extremes. Autoscaling reads well on one circuit and lies on the next: a
   *  board whose largest excursion is 40 mV of noise gets drawn in full colour,
   *  and the same green then means 5 V on the sheet beside it. A fixed volt
   *  scale is a scale; the run's own maximum is not.
   *
   *  color-mix keeps the ends as CSS variables, so the overlay follows the
   *  theme instead of carrying its own hex codes.
   */
  const tint = useCallback((group: string): string | null => {
    if (!reader) return null;
    const g = groupsById.get(group);
    const v = reader.voltage(g?.spice, g?.ground);
    if (v === null) return null;
    const span = voltRef > 0
      ? voltRef
      : Math.max(Math.abs(voltageRange.min), Math.abs(voltageRange.max)) || 1;
    const share = Math.min(100, Math.round((Math.abs(v) / span) * 100));
    const end = v >= 0 ? "var(--sim-pos)" : "var(--sim-neg)";
    return `color-mix(in oklab, ${end} ${share}%, var(--sim-zero))`;
  }, [reader, groupsById, voltageRange, voltRef]);

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
        const travel = clock * DOT_SPEED * currentSpeed * share * direction;
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
  }, [drawn, reader, solved, clock, currentPeak, currentSpeed]);

  useEffect(() => {
    paint(viewRef.current);
  }, [paint, running]);

  const onView = useCallback((view: View) => {
    viewRef.current = view;
    paint(view);
  }, [paint]);

  const pick = (net: string | null, wireId?: string) => {
    if (dragged.current) return;
    onPickNet(net === selectedNet ? null : net, wireId);
  };

  const inside = !geometry || !drawn ? null : (
    <g className="sim-tint">
      {drawn.map((wire, i) => {
        const colour = tint(wire.geom.group);
        if (!colour) return null;
        return (
          <polyline
            key={`v${wire.geom.id}:${i}`}
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
          {drawn.map((wire, i) => (
            <polyline
              key={`p${wire.geom.id}:${i}`}
              className={`sim-hit${selectedNet && wire.geom.net === selectedNet ? " on" : ""}`}
              points={wire.pts.map((p) => `${p[0]},${p[1]}`).join(" ")}
              onClick={() => pick(wire.geom.net, wire.geom.id)}
              onDoubleClick={(e) => {
                if (!dragged.current) onProbe?.({ net: wire.geom.net, wireId: wire.geom.id, e });
              }}
            >
              <title>{`${readout(wire.geom.net, wire.geom.group)} — double-click to plot`}</title>
            </polyline>
          ))}
          {onPickPart ? geometry.symbols.map((sym) => {
            // A power flag is a net name, not a component: there is nothing
            // to say about one that the net readout does not already say.
            if (sym.power || !sym.bbox) return null;
            const part = parts?.get(sym.index);
            return (
              <rect
                key={`part${sym.index}`}
                className={`sim-part${part?.on ? " on" : ""} ${part?.kind ?? "device"}`}
                x={sym.bbox[0]}
                y={sym.bbox[1]}
                width={sym.bbox[2] - sym.bbox[0]}
                height={sym.bbox[3] - sym.bbox[1]}
                onClick={(e) => { if (!dragged.current) onPickPart(sym.index, e); }}
              >
                <title>{part?.title ?? `${sym.ref} ${sym.value}`.trim()}</title>
              </rect>
            );
          }) : null}
          {geometry.pins.map((pin) => {
            if (pin.power) return null;
            const current = solved?.pins.get(`${pin.ref}.${pin.pin}`);
            // Every pin is a target, whether or not its current is known: a
            // pin also carries a VOLTAGE, and a target that appears only when
            // the maths worked out is a target nobody learns to aim for.
            return (
              <circle
                key={`pin${pin.ref}.${pin.pin}`}
                className={`sim-pin${current === undefined ? " sim-pin-plain" : ""}`}
                cx={pin.at[0]}
                cy={pin.at[1]}
                // The DOT is small — its diameter stays under the voltage
                // tint's 0.75 mm stroke, so a pin reads as a point on the
                // wire, not a ring around it. The CLICK area is the wide
                // transparent stroke the stylesheet puts on top; shrinking
                // the picture must not shrink the target.
                r={0.3}
                onClick={() => {
                  if (!dragged.current) onPickPin?.({ ref: pin.ref, pin: pin.pin, group: pin.group });
                }}
                onDoubleClick={(e) => {
                  if (!dragged.current) {
                    onProbe?.({ net: null, pin: { ref: pin.ref, pin: pin.pin, group: pin.group }, e });
                  }
                }}
              >
                <title>
                  {`${pin.ref} pin ${pin.pin}${pin.name ? ` (${pin.name})` : ""}`}
                  {current === undefined
                    ? " — double-click to plot its voltage"
                    : ` — ${eng(current, "A")} into the part. Double-click to plot it.`}
                </title>
              </circle>
            );
          })}
        </svg>
      ) : null}
    </>
  );

  return { inside, layers, onView, dragged };
}
