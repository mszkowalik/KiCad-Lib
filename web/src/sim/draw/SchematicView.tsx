/** The one schematic view in the platform.
 *
 *  Every place that shows a schematic goes through here — the project's
 *  schematic tab, the simulator's overlay and the editor — so a change to how
 *  a sheet looks or how it is navigated lands in all three at once, and so
 *  there is only ever one answer to "what colour is a wire".
 *
 *  It owns three things and nothing else:
 *
 *    1. the fit box — a KiCad page is mostly empty paper, and a circuit shown
 *       at page scale is unreadable
 *    2. the viewport — wheel to zoom, drag to pan, in millimetres throughout
 *    3. the base drawing, through `KicadSheet`
 *
 *  What each caller ADDS is passed in: SVG children are drawn in the sheet's
 *  own millimetre space, and `layers` gets the live viewport for anything that
 *  cannot live inside an SVG (the simulator's charge canvas).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import KicadSheet, { type View } from "./KicadSheet";
import type { Pt, SchTheme, SheetDrawing } from "./types";

export type { View } from "./KicadSheet";

/** How far a pointer may move and still count as a click, in pixels. */
export const CLICK_SLOP = 4;
/** Most of the window the drawing may take, so the panels under it stay in
 *  sight on a wide monitor. */
const MAX_HEIGHT_VH = 74;

function round(v: number): number {
  return Math.round(v * 1000) / 1000;
}

export interface Props {
  drawing: SheetDrawing;
  theme: SchTheme;
  /** Paper size in millimetres. */
  size: [number, number];
  /** Crop to the drawing instead of showing the whole page. */
  fit?: boolean;
  /** What the viewport belongs to. It resets when this changes — a different
   *  sheet, a different document. It must NOT reset when the drawing merely
   *  changes: an editor that re-fits the page every time a part is placed
   *  moves the circuit out from under the pointer between two clicks. */
  resetKey?: string;
  /** Points the fit box must also cover — pins and labels the caller knows
   *  about but the drawing does not carry. */
  extraBounds?: Pt[];
  /** Where to open, when neither the fit box nor the whole page is right. An
   *  editor wants a working window: a whole A4 page on a screen puts a
   *  resistor at four pixels, which is not a drawing anyone can edit. */
  initialView?: View;
  /** Drawn inside the sheet's SVG, in millimetres, beneath the drawing. */
  underlay?: (view: View) => React.ReactNode;
  /** Drawn inside the sheet's SVG, in millimetres, above the drawing. */
  children?: React.ReactNode;
  /** Stacked over the frame as DOM, given the live viewport. */
  layers?: (view: View) => React.ReactNode;
  /** The viewport, after every pan and zoom. For a caller that draws on a
   *  canvas rather than into the SVG and so cannot inherit the viewBox. */
  onView?: (view: View) => void;
  /** Pan with the left button as well as the middle one. A viewer always
   *  should. An editor answers per press, because the left button is how you
   *  move a part — but dragging empty paper should still pan. */
  leftPan?: boolean | ((mm: Pt) => boolean);
  /** A press that was not a pan. Millimetres, plus the original event. */
  onPointerDownMm?: (mm: Pt, e: React.PointerEvent) => void;
  onPointerMoveMm?: (mm: Pt, e: React.PointerEvent) => void;
  onPointerUpMm?: (mm: Pt, e: React.PointerEvent, dragged: boolean) => void;
  onDoubleClickMm?: (mm: Pt, e: React.MouseEvent) => void;
  onKeyDown?: (e: React.KeyboardEvent) => void;
  className?: string;
  /** Focusable, so the editor can take keyboard shortcuts. */
  tabIndex?: number;
  cursor?: string;
}

export function contentBox(
  drawing: SheetDrawing,
  size: [number, number],
  extra: Pt[] = [],
): View {
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
  for (const w of drawing.wires) for (const p of w.pts) add(p[0], p[1]);
  for (const b of drawing.buses) for (const p of b.pts) add(p[0], p[1]);
  for (const l of drawing.labels) add(l.at[0], l.at[1]);
  for (const t of drawing.texts) add(t.at[0], t.at[1]);
  for (const j of drawing.junctions) add(j.at[0], j.at[1]);
  for (const s of drawing.sheets) {
    add(s.at[0], s.at[1]);
    add(s.at[0] + s.size[0], s.at[1] + s.size[1]);
  }
  for (const s of drawing.symbols) {
    add(s.at[0], s.at[1]);
    for (const f of s.fields) add(f.at[0], f.at[1]);
  }
  for (const p of extra) add(p[0], p[1]);
  if (!Number.isFinite(x1)) return { x: 0, y: 0, w: size[0], h: size[1] };
  // Generous, because a text item and a label are anchored at a point and then
  // run past it — the box knows where they start, not how far they go.
  const margin = 14;
  const x = Math.max(0, x1 - margin);
  const y = Math.max(0, y1 - margin);
  return {
    x,
    y,
    w: Math.min(size[0] - x, x2 - x1 + 2 * margin),
    h: Math.min(size[1] - y, y2 - y1 + 2 * margin),
  };
}

export default function SchematicView({
  drawing,
  theme,
  size,
  fit = true,
  resetKey = "",
  extraBounds,
  initialView,
  underlay,
  children,
  layers,
  onView,
  leftPan = true,
  onPointerDownMm,
  onPointerMoveMm,
  onPointerUpMm,
  onDoubleClickMm,
  onKeyDown,
  className,
  tabIndex,
  cursor,
}: Props) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const content = useMemo(
    () => contentBox(drawing, size, extraBounds ?? []),
    [drawing, size, extraBounds],
  );
  const base = fit ? content : (initialView ?? { x: 0, y: 0, w: size[0], h: size[1] });
  const [view, setView] = useState<View>(base);
  const baseRef = useRef(base);
  baseRef.current = base;
  // A new sheet, or a switch between fitted and whole-page, resets the
  // viewport; panning within one does not, and neither does editing it.
  useEffect(() => setView(baseRef.current), [resetKey, fit]);
  useEffect(() => onView?.(view), [view, onView]);

  const drag = useRef<{ x: number; y: number; view: View; moved: number; panning: boolean } | null>(null);

  const toMm = useCallback((clientX: number, clientY: number): Pt | null => {
    const box = frameRef.current?.getBoundingClientRect();
    if (!box || !box.width || !box.height) return null;
    return [
      view.x + ((clientX - box.left) / box.width) * view.w,
      view.y + ((clientY - box.top) / box.height) * view.h,
    ];
  }, [view]);

  const onWheel = useCallback((e: React.WheelEvent) => {
    const at = toMm(e.clientX, e.clientY);
    if (!at) return;
    const factor = Math.exp(e.deltaY * 0.0015);
    const w = Math.min(Math.max(view.w * factor, 2), Math.max(size[0], size[1]) * 2);
    const scale = w / view.w;
    setView({
      x: at[0] - (at[0] - view.x) * scale,
      y: at[1] - (at[1] - view.y) * scale,
      w,
      h: view.h * scale,
    });
  }, [toMm, view, size]);

  const down = (e: React.PointerEvent) => {
    const mm = toMm(e.clientX, e.clientY);
    const panning = e.button === 1
      || (e.button === 0 && (typeof leftPan === "function" ? (mm ? leftPan(mm) : false) : leftPan));
    drag.current = { x: e.clientX, y: e.clientY, view, moved: 0, panning };
    if (mm && e.button === 0) onPointerDownMm?.(mm, e);
  };

  const move = (e: React.PointerEvent) => {
    const mm = toMm(e.clientX, e.clientY);
    const d = drag.current;
    if (d) {
      const dx = e.clientX - d.x;
      const dy = e.clientY - d.y;
      d.moved = Math.max(d.moved, Math.hypot(dx, dy));
      if (d.panning && d.moved >= CLICK_SLOP) {
        const box = frameRef.current?.getBoundingClientRect();
        if (box?.width) {
          (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
          setView({
            ...d.view,
            x: d.view.x - (dx / box.width) * d.view.w,
            y: d.view.y - (dy / box.height) * d.view.h,
          });
          return;
        }
      }
    }
    if (mm) onPointerMoveMm?.(mm, e);
  };

  const up = (e: React.PointerEvent) => {
    const mm = toMm(e.clientX, e.clientY);
    const dragged = (drag.current?.moved ?? 0) >= CLICK_SLOP;
    drag.current = null;
    if (mm) onPointerUpMm?.(mm, e, dragged);
  };

  return (
    <div
      className={`sim-frame${className ? ` ${className}` : ""}`}
      ref={frameRef}
      // The aspect ratio must stay EXACT — every layer maps client pixels
      // across this box assuming the viewBox fills it, so letterboxing would
      // put the charge canvas and the click targets off the wires. So the
      // height budget caps the WIDTH instead.
      style={{
        aspectRatio: `${view.w} / ${view.h}`,
        maxWidth: `calc(${MAX_HEIGHT_VH}vh * ${round(view.w / view.h)})`,
        cursor,
      }}
      tabIndex={tabIndex}
      onKeyDown={onKeyDown}
      onWheel={onWheel}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerLeave={() => { drag.current = null; }}
      onDoubleClick={(e) => {
        const mm = toMm(e.clientX, e.clientY);
        if (mm) onDoubleClickMm?.(mm, e);
      }}
    >
      <KicadSheet
        className="sim-layer"
        drawing={drawing}
        theme={theme}
        view={view}
        underlay={underlay?.(view)}
      >
        {children}
      </KicadSheet>
      {layers?.(view)}
    </div>
  );
}
