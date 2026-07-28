/** A part's stock over time, from events — the drill-down behind a Parts-stock row.
 *
 *  Two views of the same ledger: a step chart of the running balance (time on x,
 *  so a year with no movement LOOKS like a year with no movement), and the event
 *  table with the running balance and moving average after every row. Negative
 *  stretches are the interesting part — each one is a missing invoice, an
 *  unrecorded loss, or a batch that shipped without the part — so they are
 *  marked on both views.
 */
import { useEffect, useMemo, useState } from "react";
import {
  errorMessage,
  getPartsLedger,
  isAbortError,
  type PartLedger,
} from "../api";
import { ErrorBanner, Spinner } from "./Ui";

function qty(v: number | null | undefined): string {
  if (v == null) return "—";
  return Math.round(v).toLocaleString();
}

function usd(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

const KIND_LABEL: Record<string, string> = { buy: "purchase", use: "draw", adj: "adjust" };

function StepChart({ ledger }: { ledger: PartLedger }) {
  const W = 860, H = 150, PAD_X = 8, PAD_Y = 12;
  const model = useMemo(() => {
    const evs = ledger.events.filter((e) => e.date && e.balance_after != null);
    if (evs.length < 2) return null;
    const ts = evs.map((e) => new Date(e.date).getTime());
    const t0 = Math.min(...ts), t1 = Math.max(...ts);
    if (!(t1 > t0)) return null;
    const balances = evs.map((e) => e.balance_after as number);
    const lo = Math.min(0, ...balances), hi = Math.max(0, ...balances);
    const x = (t: number) => PAD_X + ((t - t0) / (t1 - t0)) * (W - 2 * PAD_X);
    const y = (b: number) => PAD_Y + ((hi - b) / (hi - lo || 1)) * (H - 2 * PAD_Y);
    // step-after: stock holds its level until the next event
    let d = `M ${x(ts[0]).toFixed(1)} ${y(0).toFixed(1)}`;
    let prevY = y(0);
    evs.forEach((e, i) => {
      const px = x(ts[i]);
      d += ` L ${px.toFixed(1)} ${prevY.toFixed(1)}`;
      prevY = y(e.balance_after as number);
      d += ` L ${px.toFixed(1)} ${prevY.toFixed(1)}`;
    });
    d += ` L ${(W - PAD_X).toFixed(1)} ${prevY.toFixed(1)}`;
    return {
      path: d,
      zeroY: y(0),
      dots: evs.map((e, i) => ({
        cx: x(ts[i]), cy: y(e.balance_after as number), short: e.short,
        label: `${e.date} · ${KIND_LABEL[e.kind] ?? e.kind} ${qty(e.qty_delta)} → ${qty(e.balance_after)}`,
      })),
      years: yearTicks(t0, t1).map((t) => ({ x: x(t.t), label: t.label })),
    };
  }, [ledger]);

  if (!model) return null;
  return (
    <svg className="ledger-chart" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Stock balance over time">
      <line x1={PAD_X} y1={model.zeroY} x2={W - PAD_X} y2={model.zeroY} className="ledger-zero" />
      {model.years.map((yr) => (
        <g key={yr.label}>
          <line x1={yr.x} y1={PAD_Y} x2={yr.x} y2={H - PAD_Y} className="ledger-grid" />
          <text x={yr.x + 3} y={H - 2} className="ledger-tick">{yr.label}</text>
        </g>
      ))}
      <path d={model.path} className="ledger-line" />
      {model.dots.map((p, i) => (
        <circle key={i} cx={p.cx} cy={p.cy} r={3}
                className={p.short ? "ledger-dot short" : "ledger-dot"}>
          <title>{p.label}</title>
        </circle>
      ))}
    </svg>
  );
}

function yearTicks(t0: number, t1: number): Array<{ t: number; label: string }> {
  const out: Array<{ t: number; label: string }> = [];
  for (let y = new Date(t0).getFullYear() + 1; y <= new Date(t1).getFullYear(); y++) {
    out.push({ t: new Date(`${y}-01-01`).getTime(), label: String(y) });
  }
  return out;
}

export default function PartLedgerPanel({
  componentId, mpn, lcsc,
}: {
  componentId: number | null;
  mpn: string;
  lcsc: string;
}) {
  const [ledger, setLedger] = useState<PartLedger | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getPartsLedger({ component_id: componentId, mpn, lcsc }, ctrl.signal)
      .then((l) => { setLedger(l); setError(null); })
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    return () => ctrl.abort();
  }, [componentId, mpn, lcsc]);

  if (error) return <ErrorBanner message={error} />;
  if (!ledger) return <Spinner label="Replaying the ledger…" />;
  if (ledger.events.length === 0) {
    return <p className="muted">No recorded events for this part.</p>;
  }

  return (
    <div className="ledger-panel">
      <StepChart ledger={ledger} />
      <div className="table-wrap">
        <table className="data data-fixed ledger-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Event</th>
              <th>Reference</th>
              <th className="num">Δ qty</th>
              <th className="num">Unit USD</th>
              <th className="num">Δ value</th>
              <th className="num">Balance</th>
              <th className="num">Avg USD</th>
            </tr>
          </thead>
          <tbody>
            {ledger.events.map((e, i) => (
              <tr key={i} className={e.short ? "ledger-short-row" : undefined}>
                <td className="mono">{e.date || "—"}</td>
                <td>
                  <span className={"pill " + (e.kind === "buy" ? "ok" : e.kind === "adj" ? "warn" : "neutral")}>
                    {KIND_LABEL[e.kind] ?? e.kind}
                  </span>
                </td>
                <td title={e.detail ? `${e.ref} — ${e.detail}` : e.ref}>{e.ref || "—"}</td>
                <td className="num">
                  {e.qty_delta != null && e.qty_delta > 0 ? "+" : ""}{qty(e.qty_delta)}
                </td>
                <td className="num">{e.unit_usd != null ? usd(e.unit_usd, 4) : "—"}</td>
                <td className="num">{usd(e.value_delta_usd)}</td>
                <td className={"num" + (e.short ? " err-text" : "")}
                    title={e.short ? "stock below zero — missing invoice, unrecorded loss, or a batch that shipped without this part" : undefined}>
                  {qty(e.balance_after)}
                </td>
                <td className="num">{usd(e.avg_usd_after, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
