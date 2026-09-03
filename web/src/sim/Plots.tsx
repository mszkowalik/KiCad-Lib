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
 */
import { useEffect, useMemo, useRef, useState } from "react";
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
}

const PANE_H = 104;
const SYNC = uPlot.sync("sim");

export default function Plots({ panes, onPanes, data, cursor, onCursor, live, head }: Props) {
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
  pane, data, cursor, onCursor, live, last, onMergeUp, onSplit, onToggle, onRemove,
}: {
  pane: Pane;
  data: PlotData | null;
  cursor: number;
  onCursor: (index: number) => void;
  live: boolean;
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
      height: PANE_H,
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
          if (hovering.current && u.cursor.idx != null) onCursor(u.cursor.idx);
        }],
        setScale: [(u) => {
          const from = u.valToIdx(u.scales.x.min ?? 0);
          const to = u.valToIdx(u.scales.x.max ?? 0);
          setWindow([from, to]);
        }],
      },
    }, built.arrays as uPlot.AlignedData, node);
    chart.current = plot;
    setWindow([0, data.x.length - 1]);
    return () => { plot.destroy(); chart.current = null; };
    // `width` is applied through setSize, not by rebuilding.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shape, last, unit]);

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

  useEffect(() => { chart.current?.setSize({ width, height: PANE_H }); }, [width]);

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
    if (Number.isFinite(left)) plot.setCursor({ left, top: PANE_H / 2 });
  }, [cursor, live]);

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
            cursor={cursor}
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
