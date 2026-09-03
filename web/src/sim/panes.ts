/** What the scope is asked to draw, and the arithmetic under it.
 *
 *  A pane is one set of axes; every pane on the page shares the X axis, which
 *  is what makes two stacked panes readable as one measurement. A trace can be
 *  moved between panes, so "show these together" and "show these apart" are
 *  the same operation from two directions.
 *
 *  Traces are grouped by UNIT when they arrive. Volts and amps on one pair of
 *  axes is a chart with two meanings and one scale, and the number that gets
 *  squashed is always the interesting one.
 */

export interface Trace {
  /** Vector name in the run — `v(/in)`, `i(@r1[i])`. */
  name: string;
  /** What the sheet calls it. */
  label: string;
  unit: string;
  /** Hidden by a click on its legend pill. It stays in the pane, because
   *  hiding a trace to read the one under it is not the same as throwing it
   *  away, and Falstad's scopes have always kept it. */
  off?: boolean;
}

export interface Pane {
  id: string;
  traces: Trace[];
}

/** One trace's numbers. `lo`/`hi` are a min-max envelope where the source has
 *  one — a live run sends columns, not points. */
export interface Series {
  y: Float64Array;
  lo?: Float64Array;
  hi?: Float64Array;
}

export interface PlotData {
  x: Float64Array;
  xUnit: string;
  xLabel: string;
  series: Map<string, Series>;
}

export function paneId(): string {
  return `p${Math.random().toString(36).slice(2, 9)}`;
}

/** Where a newly picked trace goes: beside the ones it shares a unit with,
 *  else in a pane of its own. */
export function addTrace(panes: Pane[], trace: Trace): Pane[] {
  if (panes.some((p) => p.traces.some((t) => t.name === trace.name))) return panes;
  const home = panes.findIndex((p) => p.traces.length && p.traces[0].unit === trace.unit);
  if (home < 0) return [...panes, { id: paneId(), traces: [trace] }];
  return panes.map((p, i) => (i === home ? { ...p, traces: [...p.traces, trace] } : p));
}

export function removeTrace(panes: Pane[], name: string): Pane[] {
  return panes
    .map((p) => ({ ...p, traces: p.traces.filter((t) => t.name !== name) }))
    .filter((p) => p.traces.length);
}

export function toggleTrace(panes: Pane[], name: string): Pane[] {
  return panes.map((p) => ({
    ...p,
    traces: p.traces.map((t) => (t.name === name ? { ...t, off: !t.off } : t)),
  }));
}

/** Everything on one pair of axes. */
export function mergeAll(panes: Pane[]): Pane[] {
  const all = panes.flatMap((p) => p.traces);
  return all.length ? [{ id: paneId(), traces: all }] : [];
}

/** One trace per pane. */
export function splitAll(panes: Pane[]): Pane[] {
  return panes.flatMap((p) => p.traces.map((t) => ({ id: paneId(), traces: [t] })));
}

/** Fold a pane into the one above it. */
export function mergeUp(panes: Pane[], id: string): Pane[] {
  const at = panes.findIndex((p) => p.id === id);
  if (at <= 0) return panes;
  const moved = panes[at].traces;
  return panes
    .map((p, i) => (i === at - 1 ? { ...p, traces: [...p.traces, ...moved] } : p))
    .filter((_, i) => i !== at);
}

/** Break one pane into one pane per trace, in place. */
export function splitPane(panes: Pane[], id: string): Pane[] {
  const at = panes.findIndex((p) => p.id === id);
  if (at < 0 || panes[at].traces.length < 2) return panes;
  const made = panes[at].traces.map((t) => ({ id: paneId(), traces: [t] }));
  return [...panes.slice(0, at), ...made, ...panes.slice(at + 1)];
}

// --------------------------------------------------------------- statistics

export interface Stats {
  now: number;
  min: number;
  max: number;
  mean: number;
  rms: number;
  /** Peak to peak. */
  pp: number;
}

/** What a trace is doing, over the window on screen.
 *
 *  `at` is the cursor sample, so `now` is the reading under the crosshair
 *  rather than the last point of the run — a value nobody was looking at.
 */
export function statsOf(series: Series, from: number, to: number, at: number): Stats {
  const lo = Math.max(0, Math.min(from, series.y.length - 1));
  const hi = Math.max(lo, Math.min(to, series.y.length - 1));
  let min = Infinity;
  let max = -Infinity;
  let sum = 0;
  let sq = 0;
  let n = 0;
  for (let i = lo; i <= hi; i += 1) {
    const bottom = series.lo ? series.lo[i] : series.y[i];
    const top = series.hi ? series.hi[i] : series.y[i];
    if (!Number.isFinite(bottom) || !Number.isFinite(top)) continue;
    if (bottom < min) min = bottom;
    if (top > max) max = top;
    const mid = series.y[i];
    sum += mid;
    sq += mid * mid;
    n += 1;
  }
  if (!n) return { now: NaN, min: NaN, max: NaN, mean: NaN, rms: NaN, pp: NaN };
  const index = Math.max(lo, Math.min(at, hi));
  return {
    now: series.y[index],
    min,
    max,
    mean: sum / n,
    rms: Math.sqrt(sq / n),
    pp: max - min,
  };
}
