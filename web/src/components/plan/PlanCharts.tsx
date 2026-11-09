/** The plan's charts (decision 0107), hand-written SVG on a viewBox scaled to
 *  the data: deliveries by week, a part's supply against its need, and the
 *  advances against the purchases. Every colour is a theme token, so the
 *  charts follow the theme; the axis text reuses `.chart-tick`.
 *
 *  The viewBox is as wide as the chart's box in pixels (`useBoxWidth`), so the
 *  text is drawn at its own size in a half card, a whole card and a phone. A
 *  fixed viewBox scaled 10 px labels to 17 px in a wide card and to 5 px on a
 *  phone. */
import { useLayoutEffect, useRef, useState, type RefObject } from "react";

import type { PlanCash, PlanCoverage, PlanPart, PlanSchedule } from "../../api";
import {
  dayNo,
  kilo,
  longDay,
  monthLabel,
  monthStarts,
  shortDay,
  units,
  weekStart,
  type ProjectInfo,
} from "./planUtil";

/** The pixel width of a box, followed as it changes. */
function useBoxWidth(): [RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(640);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(Math.max(280, Math.round(el.clientWidth)));
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** A round step for about five grid lines up to `max`. */
function niceStep(max: number): number {
  if (max <= 0) return 1;
  const raw = max / 5;
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}

function niceMax(max: number): { top: number; step: number } {
  const step = niceStep(max);
  return { top: Math.max(step, Math.ceil(max / step) * step), step };
}

// ------------------------------------------------------------------ deliveries

export function DeliveriesChart({ weeks, projects, coverage }: {
  weeks: PlanSchedule["weeks"];
  projects: ProjectInfo[];
  coverage: PlanCoverage[];
}) {
  const [box, W] = useBoxWidth();
  interface WeekRow { first: number; per: Map<number, number>; total: number; keys: string[] }
  const byWeek = new Map<number, WeekRow>();
  for (const w of weeks) {
    const d = dayNo(w.day);
    if (d == null) continue;
    const k = weekStart(d);
    const e: WeekRow = byWeek.get(k) ?? { first: d, per: new Map<number, number>(), total: 0, keys: [] };
    e.first = Math.min(e.first, d);
    for (const [pid, q] of Object.entries(w.by_project)) e.per.set(Number(pid), (e.per.get(Number(pid)) ?? 0) + q);
    e.total += w.total;
    for (const o of w.orders) e.keys.push(`${o.key} ${o.qty}`);
    byWeek.set(k, e);
  }
  const rows = [...byWeek.entries()].sort((a, b) => a[0] - b[0]).map(([, v]) => v);
  const rates = coverage.filter((c) => c.line_rate_week);
  const H = 250, L = 42, R = 10, T = 18, B = 34;
  const pw = W - L - R, ph = H - T - B;
  const { top, step } = niceMax(Math.max(...rows.map((r) => r.total), ...rates.map((c) => c.line_rate_week ?? 0)) * 1.08);
  const y = (v: number) => T + ph - (v / top) * ph;
  const bw = pw / rows.length;
  const colorOf = new Map(projects.map((p) => [p.id, p.color]));
  const order = projects.map((p) => p.id);
  const grid: number[] = [];
  for (let v = 0; v <= top + 1e-9; v += step) grid.push(v);
  let lastMonth = -1;
  if (!rows.length) return <div ref={box} />;
  return (
    <div ref={box}>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Units delivered per week">
        {grid.map((v) => (
          <g key={v}>
            <line className="chart-grid" x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
            <text className="chart-tick" x={L - 6} y={y(v) + 3.5} textAnchor="end">{kilo(v)}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const w = Math.min(bw * 0.68, 48);
          const x = L + i * bw + (bw - w) / 2;
          let acc = 0;
          const month = new Date(r.first * 864e5).getUTCMonth();
          const showMonth = month !== lastMonth;
          lastMonth = month;
          return (
            <g key={r.first}>
              {order.filter((pid) => r.per.get(pid)).map((pid) => {
                const q = r.per.get(pid) as number;
                const y0 = y(acc), y1 = y(acc + q);
                acc += q;
                return (
                  <rect key={pid} x={x} y={y1} width={w} height={Math.max(y0 - y1, 0.5)} rx={2} fill={colorOf.get(pid)}>
                    <title>{`${shortDay(r.first)}: ${projects.find((p) => p.id === pid)?.name} ${units(q)} (${r.keys.join(", ")})`}</title>
                  </rect>
                );
              })}
              {bw >= 16 ? (
                <text className="chart-endlabel plan-halo" x={x + w / 2} y={y(r.total) - 4} textAnchor="middle">{units(r.total)}</text>
              ) : null}
              {bw >= 12 || i % Math.ceil(12 / bw) === 0 ? (
                <text className="chart-tick" x={x + w / 2} y={H - B + 13} textAnchor="middle">
                  {new Date(r.first * 864e5).getUTCDate()}
                </text>
              ) : null}
              {showMonth ? (
                <text className="chart-tick" x={x + w / 2} y={H - B + 26} textAnchor="middle">
                  {monthLabel(r.first, false)}
                </text>
              ) : null}
            </g>
          );
        })}
        {rates.map((c) => (
          <line key={c.project_id} x1={L} x2={W - R} y1={y(c.line_rate_week as number)} y2={y(c.line_rate_week as number)}
            stroke={colorOf.get(c.project_id)} strokeWidth={1.5} strokeDasharray="5 4">
            <title>{`${c.project}: the line makes ${c.line_rate_week} a week`}</title>
          </line>
        ))}
      </svg>
      <div className="plan-legend">
        {projects.filter((p) => rows.some((r) => r.per.get(p.id))).map((p) => (
          <span key={p.id}><i className="plan-sw" style={{ background: p.color }} />{p.name}</span>
        ))}
        {rates.map((c) => (
          <span key={`r${c.project_id}`}>
            <i className="plan-sw dash" style={{ borderColor: colorOf.get(c.project_id) }} />
            {c.project}: {units(c.line_rate_week)} a week
          </span>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ a part

/** Supply on hand and arriving, added up, against the need added up. The gap
 *  where the need is above the supply is filled red. */
export function PartBalanceChart({ part, today }: { part: PlanPart; today: string }) {
  const [box, W] = useBoxWidth();
  const t = dayNo(today) ?? 0;
  const start = (part.reserved || 0) + (part.free || 0);
  const needs = part.needs.map((n) => ({ d: dayNo(n.day), q: n.qty })).filter((n) => n.d != null) as { d: number; q: number }[];
  const sups = part.supplies.map((s) => ({ d: dayNo(s.day), q: s.qty })).filter((s) => s.d != null) as { d: number; q: number }[];
  const days = [...new Set([t, ...needs.map((n) => n.d), ...sups.map((s) => s.d)])].sort((a, b) => a - b);
  if (days.length < 2) return <div ref={box} />;
  const x0 = days[0];
  const x1 = days[days.length - 1] + 7;
  // cumulative values at each event day
  const steps = days.map((d) => ({
    d,
    need: needs.filter((n) => n.d <= d).reduce((a, n) => a + n.q, 0),
    supply: start + sups.filter((s) => s.d <= d).reduce((a, s) => a + s.q, 0),
  }));
  const H = 230, L = 46, R = 12, T = 12, B = 26;
  const pw = W - L - R, ph = H - T - B;
  const { top, step } = niceMax(Math.max(...steps.map((s) => Math.max(s.need, s.supply)), 1) * 1.05);
  const X = (n: number) => L + ((n - x0) / (x1 - x0)) * pw;
  const Y = (v: number) => T + ph - (v / top) * ph;
  const path = (key: "need" | "supply") => {
    let d = `M ${X(x0).toFixed(1)} ${Y(key === "need" ? 0 : start).toFixed(1)}`;
    let prev = key === "need" ? 0 : start;
    for (const s of steps) {
      d += ` L ${X(s.d).toFixed(1)} ${Y(prev).toFixed(1)} L ${X(s.d).toFixed(1)} ${Y(s[key]).toFixed(1)}`;
      prev = s[key];
    }
    return `${d} L ${X(x1).toFixed(1)} ${Y(prev).toFixed(1)}`;
  };
  const gaps = steps.map((s, i) => ({ s, end: i + 1 < steps.length ? steps[i + 1].d : x1 })).filter((g) => g.s.need > g.s.supply);
  const grid: number[] = [];
  for (let v = 0; v <= top + 1e-9; v += step) grid.push(v);
  return (
    <div ref={box}>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${part.name}: supply against need`}>
        {grid.map((v) => (
          <g key={v}>
            <line className="chart-grid" x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} />
            <text className="chart-tick" x={L - 6} y={Y(v) + 3.5} textAnchor="end">{kilo(v)}</text>
          </g>
        ))}
        {monthStarts(x0, x1).map((n) => (
          <g key={n}>
            <line className="chart-grid" x1={X(n)} x2={X(n)} y1={T} y2={T + ph} strokeDasharray="2 3" />
            <text className="chart-tick" x={X(n) + 3} y={H - 8}>{monthLabel(n, false)}</text>
          </g>
        ))}
        {gaps.map((g) => (
          <rect key={g.s.d} x={X(g.s.d)} y={Y(g.s.need)} width={Math.max(X(g.end) - X(g.s.d), 1)}
            height={Math.max(Y(g.s.supply) - Y(g.s.need), 0.5)} fill="var(--err-soft)">
            <title>{`${longDay(g.s.d)}: need ${units(g.s.need)}, supply ${units(g.s.supply)}, short ${units(g.s.need - g.s.supply)}`}</title>
          </rect>
        ))}
        <line x1={X(t)} x2={X(t)} y1={T} y2={T + ph} stroke="var(--accent)" strokeWidth={1} strokeDasharray="3 3" />
        <path d={path("supply")} fill="none" stroke="var(--ok)" strokeWidth={2} />
        <path d={path("need")} fill="none" stroke="var(--accent)" strokeWidth={2} />
      </svg>
      <div className="plan-legend">
        <span><i className="plan-sw ok" />Supply: stock for the plan, then what arrives</span>
        <span><i className="plan-sw acc" />Need, added up</span>
        <span><i className="plan-sw short" />Short</span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ cash

/** The advances received against the purchases paid from them, both added
 *  up over time, with the smallest margin marked. */
export function CashChart({ cash, currency }: { cash: PlanCash; currency: string }) {
  const [box, W] = useBoxWidth();
  const ins = cash.inflows.map((i) => ({ d: dayNo(i.day), v: i.net })).filter((i) => i.d != null) as { d: number; v: number }[];
  const outs = cash.steps.map((s) => ({ d: dayNo(s.day), v: s.cum_out })).filter((s) => s.d != null) as { d: number; v: number }[];
  if (!ins.length && !outs.length) return <div ref={box} />;
  ins.sort((a, b) => a.d - b.d);
  let acc = 0;
  const inCum = ins.map((i) => ({ d: i.d, v: (acc += i.v) }));
  const all = [...inCum.map((i) => i.d), ...outs.map((o) => o.d)];
  const x0 = Math.min(...all) - 4;
  const x1 = Math.max(...all) + 8;
  const H = 250, L = 52, R = 12, T = 14, B = 26;
  const pw = W - L - R, ph = H - T - B;
  const { top, step } = niceMax(Math.max(acc, ...outs.map((o) => o.v), 1) * 1.05);
  const X = (n: number) => L + ((n - x0) / (x1 - x0)) * pw;
  const Y = (v: number) => T + ph - (v / top) * ph;
  const stepPath = (pts: { d: number; v: number }[]) => {
    let p = `M ${X(x0).toFixed(1)} ${Y(0).toFixed(1)}`;
    let c = 0;
    for (const q of pts) {
      p += ` L ${X(q.d).toFixed(1)} ${Y(c).toFixed(1)} L ${X(q.d).toFixed(1)} ${Y(q.v).toFixed(1)}`;
      c = q.v;
    }
    return `${p} L ${X(x1).toFixed(1)} ${Y(c).toFixed(1)}`;
  };
  const low = cash.lowest;
  const lowD = low ? dayNo(low.day) : null;
  const grid: number[] = [];
  for (let v = 0; v <= top + 1e-9; v += step) grid.push(v);
  const lowLabel = low ? `Smallest margin ${kilo(low.margin)} ${currency}, ${shortDay(lowD)}` : "";
  // The label goes where it fits: after the point, else before it.
  const lowLeft = lowD != null && X(lowD) + 8 + lowLabel.length * 6.6 > W - R;
  return (
    <div ref={box}>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Advances received against purchases">
        {grid.map((v) => (
          <g key={v}>
            <line className="chart-grid" x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} />
            <text className="chart-tick" x={L - 6} y={Y(v) + 3.5} textAnchor="end">{kilo(v)}</text>
          </g>
        ))}
        {monthStarts(x0, x1).map((n) => (
          <g key={n}>
            <line className="chart-grid" x1={X(n)} x2={X(n)} y1={T} y2={T + ph} strokeDasharray="2 3" />
            <text className="chart-tick" x={X(n) + 3} y={H - 8}>{monthLabel(n, false)}</text>
          </g>
        ))}
        <path d={stepPath(inCum)} fill="none" stroke="var(--ok)" strokeWidth={2} />
        <path d={stepPath(outs)} fill="none" stroke="var(--accent)" strokeWidth={2} />
        {low && lowD != null ? (
          <g>
            <circle cx={X(lowD)} cy={Y(low.cum_out)} r={4} fill={low.margin < 0 ? "var(--err)" : "var(--warn)"} />
            <text className="chart-endlabel plan-halo" x={X(lowD) + (lowLeft ? -8 : 8)} y={Y(low.cum_out) - 8}
              textAnchor={lowLeft ? "end" : "start"}>
              {lowLabel}
            </text>
          </g>
        ) : null}
      </svg>
      <div className="plan-legend">
        <span><i className="plan-sw ok" />Advances received, added up</span>
        <span><i className="plan-sw acc" />Purchases, added up</span>
      </div>
    </div>
  );
}
