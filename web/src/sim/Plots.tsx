/** The scope: stacked panes on one X axis, drawn by uPlot.
 *
 *  What this replaced was one hand-drawn SVG chart with every trace in it. It
 *  could not stack, could not put current under voltage, redrew the whole path
 *  on every frame, and had no cursor worth the name. uPlot is a canvas plotter
 *  built for exactly this shape of problem — tens of thousands of points, a
 *  synchronised crosshair across several charts, drag to zoom — and it is 45 kB
 *  with no dependencies of its own.
 *
 *  Three things are deliberately ours rather than uPlot's:
 *
 *  1. **The legend.** uPlot's is a table; this one is a row of pills that
 *     carry the statistics, toggle a trace on click and drop it on the ×.
 *  2. **The layout.** Panes are React, so merging and splitting is a change to
 *     a list and not to a chart's internals.
 *  3. **The band.** A live run sends a min-max COLUMN per pixel, not points, so
 *     a live trace is drawn as a band between two series with the middle line
 *     over it. uPlot draws bands natively; the two edge series are hidden from
 *     our legend because they are one reading, not three.
 *
 *  The X window is the PAGE's, not any one chart's: every pane shares one time
 *  axis, so a zoom that moved only the pane under the pointer would break the
 *  single reading that stacking them is for. One range lives here and every
 *  pane is told it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { eng } from "./payload";
import {
  mergeAll, mergeUp, removeTrace, splitAll, splitPane, statsOf, toggleTrace,
  type Pane, type PlotData, type Trace,
} from "./panes";

/** The six trace colours, read from the theme so a plot matches the sheet. */
function traceColour(i: number): string {
  if (typeof window === "undefined") return "#888";
  return getComputedStyle(document.documentElement)
    .getPropertyValue(`--sim-trace-${i % 6}`).trim() || "#888";
}

function themeColour(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

interface Props {
  /** Rendered at the start of the bar row — the scope's own status used to
   *  be a row of its own above the panes. */
  head?: React.ReactNode;
  panes: Pane[];
  onPanes: (next: Pane[]) => void;
  data: PlotData | null;
  /** Sample under the crosshair, shared with the schematic readout. */
  cursor: number;
  onCursor: (index: number) => void;
  /** A live run keeps moving; a finished one is scrubbed. */
  live: boolean;
  /** Panes at double height. Remembered by the page, per source. */
  tall: boolean;
  onTall: (next: boolean) => void;
}

/** Pane heights. Tall is exactly double, because the point of the toggle is to
 *  read a decimated trace that is too fine for the short one — and a trace at
 *  twice the pixels is twice the resolution, which is a claim a reader can
 *  check. */
const PANE_H = 104;
const PANE_H_TALL = 208;
const SYNC = uPlot.sync("sim");

/** How much one wheel notch zooms. 1.25 is about eight notches per decade,
 *  which lands on a decade without feeling slow. */
const ZOOM_STEP = 1.25;

type XRange = [number, number];

/** Two ranges the same, within a millionth of the span on screen. Comparing
 *  floats exactly here would feed the setScale hook back into itself forever. */
function sameRange(a: XRange | null, b: XRange | null): boolean {
  if (!a || !b) return a === b;
  const span = Math.abs(b[1] - b[0]) || 1;
  return Math.abs(a[0] - b[0]) < span * 1e-6 && Math.abs(a[1] - b[1]) < span * 1e-6;
}

export default function Plots({
  panes, onPanes, data, cursor, onCursor, live, tall, onTall, head,
}: Props) {
  /** The X window every pane shows. `null` is "all of it". */
  const [xRange, setXRange] = useState<XRange | null>(null);

  /** The whole run, as the X axis measures it. */
  const full = useMemo<XRange | null>(() => {
    if (!data || data.x.length < 2) return null;
    return [data.x[0], data.x[data.x.length - 1]];
  }, [data]);

  // A new run is a new window. Without this the scope stayed zoomed into a
  // slice of the PREVIOUS result, which looks like a run that produced almost
  // nothing.
  useEffect(() => { setXRange(null); }, [full?.[0], full?.[1]]);

  const zoomed = !!(xRange && full && !sameRange(xRange, full));

  const setRange = useCallback((next: XRange | null) => {
    setXRange((current) => (sameRange(current, next) ? current : next));
  }, []);

  if (!panes.length) {
    return (
      <p className="muted">
        Nothing on the scope. Double-click a wire to plot its voltage, or a pin for
        its current — a single click only selects. Traces stack on one time axis, and
        you can merge them onto one pair of axes below.
      </p>
    );
  }
  return (
    <div className="sim-plots">
      <div className="sim-plots-bar">
        {head}
        <span className="sim-runbar-spacer" />
        {/* What the scope answers to. Drag-to-zoom is uPlot's and is not
            guessable; the wheel and the reset are ours. Said once, here,
            rather than in a tooltip on every pane. */}
        <span className="muted sim-plots-hint">
          drag to zoom · wheel to zoom · shift-wheel to pan
        </span>
        {zoomed ? (
          <button
            type="button"
            className="ghost"
            onClick={() => setRange(null)}
            title="Back to the whole run"
          >
            Reset zoom
          </button>
        ) : null}
        <button
          type="button"
          className="ghost"
          onClick={() => onTall(!tall)}
          title={tall ? "Half height" : "Double height — more pixels for a decimated trace"}
          aria-pressed={tall}
        >
          {tall ? "Shorter" : "Taller"}
        </button>
        {panes.length > 1 ? (
          <button type="button" className="ghost" onClick={() => onPanes(mergeAll(panes))}>
            Merge all
          </button>
        ) : null}
        {panes.some((p) => p.traces.length > 1) ? (
          <button type="button" className="ghost" onClick={() => onPanes(splitAll(panes))}>
            Split all
          </button>
        ) : null}
      </div>
      {panes.map((pane, i) => (
        <PaneChart
          key={pane.id}
          pane={pane}
          data={data}
          cursor={cursor}
          onCursor={onCursor}
          live={live}
          height={tall ? PANE_H_TALL : PANE_H}
          xRange={xRange}
          full={full}
          onXRange={setRange}
          first={i === 0}
          last={i === panes.length - 1}
          onMergeUp={i > 0 ? () => onPanes(mergeUp(panes, pane.id)) : undefined}
          onSplit={pane.traces.length > 1 ? () => onPanes(splitPane(panes, pane.id)) : undefined}
          onToggle={(name) => onPanes(toggleTrace(panes, name))}
          onRemove={(name) => onPanes(removeTrace(panes, name))}
        />
      ))}
    </div>
  );
}

function PaneChart({
  pane, data, cursor, onCursor, live, height, xRange, full, onXRange,
  last, onMergeUp, onSplit, onToggle, onRemove,
}: {
  pane: Pane;
  data: PlotData | null;
  cursor: number;
  onCursor: (index: number) => void;
  live: boolean;
  height: number;
  /** The window every pane shows, or `null` for the whole run. */
  xRange: XRange | null;
  /** The whole run, which a zoom may not reach outside of. */
  full: XRange | null;
  onXRange: (next: XRange | null) => void;
  first: boolean;
  last: boolean;
  onMergeUp?: () => void;
  onSplit?: () => void;
  onToggle: (name: string) => void;
  onRemove: (name: string) => void;
}) {
  const host = useRef<HTMLDivElement | null>(null);
  const chart = useRef<uPlot | null>(null);
  const [width, setWidth] = useState(600);
  /** The window on screen, as sample indices — what the statistics cover. */
  const [window, setWindow] = useState<[number, number]>([0, 0]);

  /** Whether the pointer is over THIS chart. The cursor hook fires for a
   *  crosshair the page moved as well as one the user moved, and reporting the
   *  first back to the page stopped replay the instant it started: play moved
   *  the cursor, the hook reported it as a scrub, and a scrub pauses. */
  const hovering = useRef(false);
  /** The last range this chart PUT ON SCREEN, whoever asked for it. The
   *  setScale hook fires for our own writes as loudly as for a user's drag, so
   *  without this the page and the chart hand the same range back and forth. */
  const applied = useRef<XRange | null>(null);
  /** Read by the wheel listener, which is attached once and must not close
   *  over a stale bound. */
  const bounds = useRef<XRange | null>(full);
  bounds.current = full;
  const report = useRef(onXRange);
  report.current = onXRange;
  const isLive = useRef(live);
  isLive.current = live;
  const shown = useMemo(() => pane.traces.filter((t) => !t.off), [pane.traces]);
  const unit = pane.traces[0]?.unit ?? "";

  /** uPlot wants one array per series, x first. A banded trace contributes
   *  three: the middle line and the two edges the band is drawn between. */
  const built = useMemo(() => {
    if (!data) return null;
    const arrays: (Float64Array | number[])[] = [data.x];
    const opts: uPlot.Series[] = [{}];
    const bands: uPlot.Band[] = [];
    shown.forEach((t, i) => {
      const s = data.series.get(t.name);
      if (!s) return;
      const colour = traceColour(pane.traces.indexOf(t));
      if (s.lo && s.hi) {
        arrays.push(s.hi, s.lo, s.y);
        const top = arrays.length - 3;
        const bottom = arrays.length - 2;
        opts.push({ stroke: colour, width: 0, points: { show: false } });
        opts.push({ stroke: colour, width: 0, points: { show: false } });
        opts.push({ label: t.label, stroke: colour, width: 1.4, points: { show: false } });
        bands.push({ series: [top, bottom], fill: colour + "44" });
      } else {
        arrays.push(s.y);
        opts.push({ label: t.label, stroke: colour, width: 1.4, points: { show: false } });
      }
      void i;
    });
    return { arrays, opts, bands };
  }, [data, shown, pane.traces]);

  // One chart per pane, rebuilt when the SHAPE changes — the series list, not
  // the numbers. Numbers go through setData, which is why a live run at thirty
  // frames a second costs nothing here.
  const shape = built ? built.opts.length + ":" + shown.map((t) => t.name).join(",") : "";
  useEffect(() => {
    const node = host.current;
    if (!node || !built || !data) return;
    const line = themeColour("--line", "#ccc");
    const text = themeColour("--muted", "#888");
    const plot = new uPlot({
      width,
      height,
      cursor: {
        sync: { key: SYNC.key },
        drag: { x: true, y: false, setScale: true },
      },
      legend: { show: false },
      scales: { x: { time: false } },
      axes: [
        {
          show: last,
          stroke: text,
          grid: { stroke: line, width: 1 },
          ticks: { stroke: line },
          values: (_u, splits) => splits.map((v) => eng(v, data.xUnit)),
        },
        {
          stroke: text,
          size: 62,
          grid: { stroke: line, width: 1 },
          ticks: { stroke: line },
          values: (_u, splits) => splits.map((v) => eng(v, unit)),
        },
      ],
      series: built.opts,
      bands: built.bands,
      hooks: {
        setCursor: [(u) => {
          // Only a crosshair the POINTER moved is a scrub. `cursor.event` is
          // null for a programmatic setCursor (the replay driving it), and
          // the hover flag alone was not enough: pressing Run shifts the
          // dock up, the new pane lands under the resting pointer, and the
          // replay paused the instant it started (2026-09-07).
          if (hovering.current && u.cursor.event && u.cursor.idx != null) onCursor(u.cursor.idx);
        }],
        setScale: [(u) => {
          const min = u.scales.x.min ?? 0;
          const max = u.scales.x.max ?? 0;
          setWindow([u.valToIdx(min), u.valToIdx(max)]);
          // Tell the page, so every other pane follows. This fires for a
          // drag-zoom, a double-click reset and our own writes alike; the
          // `applied` guard is what stops the last of those looping.
          const next: XRange = [min, max];
          if (sameRange(applied.current, next)) return;
          applied.current = next;
          if (isLive.current) return;
          const whole = bounds.current;
          report.current(whole && sameRange(next, whole) ? null : next);
        }],
      },
    }, built.arrays as uPlot.AlignedData, node);
    chart.current = plot;
    setWindow([0, data.x.length - 1]);

    // Wheel over the plot: zoom the time axis about the pointer, or pan it
    // with shift held. A trackpad's own horizontal scroll pans too, which is
    // the gesture a Mac user reaches for without being told. Not passive —
    // the page must not scroll under a gesture aimed at the chart.
    const over = plot.over;
    const onWheel = (e: WheelEvent) => {
      const whole = bounds.current;
      if (!whole || isLive.current) return;
      e.preventDefault();
      const min = plot.scales.x.min ?? whole[0];
      const max = plot.scales.x.max ?? whole[1];
      const span = max - min;
      if (!(span > 0)) return;
      const pan = e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY);
      let next: XRange;
      if (pan) {
        const delta = (e.shiftKey ? e.deltaY || e.deltaX : e.deltaX) / Math.max(1, over.clientWidth);
        next = [min + span * delta, max + span * delta];
      } else {
        // Keep the value under the pointer where it is, so the wheel zooms
        // into what is being looked at rather than into the middle.
        const rect = over.getBoundingClientRect();
        const at = Math.min(1, Math.max(0, (e.clientX - rect.left) / (rect.width || 1)));
        const focus = min + span * at;
        const grown = e.deltaY > 0 ? span * ZOOM_STEP : span / ZOOM_STEP;
        next = [focus - grown * at, focus + grown * (1 - at)];
      }
      // Never outside the run, and never so far in that the window is thinner
      // than two samples — there is nothing to see past that and the axis
      // labels collapse.
      const limit = (whole[1] - whole[0]) / 1e6;
      let [lo, hi] = next;
      if (hi - lo < limit) return;
      if (hi - lo >= whole[1] - whole[0]) { lo = whole[0]; hi = whole[1]; }
      else if (lo < whole[0]) { hi += whole[0] - lo; lo = whole[0]; }
      else if (hi > whole[1]) { lo -= hi - whole[1]; hi = whole[1]; }
      plot.setScale("x", { min: lo, max: hi });
    };
    over.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      over.removeEventListener("wheel", onWheel);
      plot.destroy();
      chart.current = null;
      applied.current = null;
    };
    // `width` and `height` are applied through setSize, not by rebuilding.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shape, last, unit]);

  // The page's window, put on this chart. A pane that was just built already
  // carries it through `applied`, so this only moves the ones that did not
  // start the gesture.
  useEffect(() => {
    const plot = chart.current;
    if (!plot || live) return;
    const want: XRange | null = xRange ?? full;
    if (!want || sameRange(applied.current, want)) return;
    applied.current = want;
    plot.setScale("x", { min: want[0], max: want[1] });
  }, [xRange, full, live, shape]);

  // New numbers, same shape.
  useEffect(() => {
    if (chart.current && built) chart.current.setData(built.arrays as uPlot.AlignedData, !live);
  }, [built, live]);

  // A live run scrolls: keep the x scale on the whole of what has arrived.
  useEffect(() => {
    if (live && chart.current && data && data.x.length > 1) {
      chart.current.setScale("x", { min: data.x[0], max: data.x[data.x.length - 1] });
    }
  }, [live, data]);

  useEffect(() => { chart.current?.setSize({ width, height }); }, [width, height]);

  useEffect(() => {
    const node = host.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.max(240, Math.round(entry.contentRect.width));
      setWidth((old) => (Math.abs(old - w) > 2 ? w : old));
    });
    ro.observe(node);
    return () => ro.disconnect();
  }, []);

  // The crosshair follows the page's cursor when the page is driving it —
  // replay, or a click on the schematic — and not while the pointer is here.
  useEffect(() => {
    const plot = chart.current;
    if (!plot || live) return;
    if (plot.cursor.idx === cursor) return;
    const left = plot.valToPos(plot.data[0][cursor] as number, "x");
    if (Number.isFinite(left)) plot.setCursor({ left, top: height / 2 });
  }, [cursor, live, height]);

  return (
    <div className="sim-pane">
      <div
        className="sim-pane-chart"
        ref={host}
        onPointerEnter={() => { hovering.current = true; }}
        onPointerLeave={() => { hovering.current = false; }}
      />
      <div className="sim-legend">
        {pane.traces.map((t) => (
          <LegendPill
            key={t.name}
            trace={t}
            index={pane.traces.indexOf(t)}
            data={data}
            window={window}
            // A live grid is padded with NaN on the left and its newest
            // column is the last one; the page cursor is a replay position
            // and reads 0 there, which showed the OLDEST column as "now".
            cursor={live ? Number.POSITIVE_INFINITY : cursor}
            onToggle={() => onToggle(t.name)}
            onRemove={() => onRemove(t.name)}
          />
        ))}
        <span className="sim-runbar-spacer" />
        {onSplit ? (
          <button type="button" className="ghost sim-pane-act" onClick={onSplit} title="One pane per trace">
            Split
          </button>
        ) : null}
        {onMergeUp ? (
          <button type="button" className="ghost sim-pane-act" onClick={onMergeUp} title="Onto the axes above">
            Merge up
          </button>
        ) : null}
      </div>
    </div>
  );
}

function LegendPill({
  trace, index, data, window, cursor, onToggle, onRemove,
}: {
  trace: Trace;
  index: number;
  data: PlotData | null;
  window: [number, number];
  cursor: number;
  onToggle: () => void;
  onRemove: () => void;
}) {
  const series = data?.series.get(trace.name);
  const stats = useMemo(
    () => (series ? statsOf(series, window[0], window[1], cursor) : null),
    [series, window, cursor],
  );
  const u = trace.unit;
  return (
    <span className={`sim-legend-item sim-trace-${index % 6}${trace.off ? " off" : ""}`}>
      <button type="button" className="sim-legend-name" onClick={onToggle}
        title={trace.off ? "Show this trace" : "Hide this trace"}>
        {trace.label}
      </button>
      {stats && Number.isFinite(stats.now) ? (
        <span className="sim-legend-stats mono">
          <b>{eng(stats.now, u)}</b>
          <span title="minimum / maximum over the window on screen">
            {eng(stats.min, u)}…{eng(stats.max, u)}
          </span>
          <span title="mean">x̄ {eng(stats.mean, u)}</span>
          <span title="root mean square">rms {eng(stats.rms, u)}</span>
          <span title="peak to peak">pp {eng(stats.pp, u)}</span>
        </span>
      ) : null}
      <button type="button" className="sim-legend-x" onClick={onRemove} aria-label={`Remove ${trace.label}`}>
        ×
      </button>
    </span>
  );
}
