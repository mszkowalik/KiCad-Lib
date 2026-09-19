/** Everything known about one part, behind its row in the Parts-stock table.
 *
 *  Three boxes of the same height, because they answer three questions a reader
 *  has at once and none of them is worth a scroll of its own: WHERE the part is
 *  used, WHAT moved it, and what the balance has DONE over time. The figures
 *  the table used to carry as columns sit above them — they are the operands of
 *  Δ qty, wanted when the row is open and noise when it is not.
 *
 *  The movements box has two sources behind one control: ours and JLCPCB's. A
 *  disagreement is settled by reading one against the other, so they belong in
 *  the same frame at the same size, never in two places on the page.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getJlcPartLedger,
  getPartsLedger,
  isAbortError,
  type JlcPartLedger,
  type PartLedger,
  type PartsStockRow,
} from "../api";
import { ErrorBanner, Spinner } from "./Ui";

function qty(v: number | null | undefined): string {
  if (v == null) return "—";
  return Math.round(v).toLocaleString();
}

import { plain as usd } from "../format";

const KIND_LABEL: Record<string, string> = { buy: "purchase", use: "draw", adj: "adjust" };

function StepChart({ ledger }: { ledger: PartLedger }) {
  const W = 520, H = 190, PAD_X = 8, PAD_Y = 12;
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

export default function PartLedgerPanel({ row }: { row: PartsStockRow }) {
  const { component_id: componentId, mpn, lcsc } = row;
  const [ledger, setLedger] = useState<PartLedger | null>(null);
  const [jlc, setJlc] = useState<JlcPartLedger | null>(null);
  const [source, setSource] = useState<"ours" | "jlc">("ours");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getPartsLedger({ component_id: componentId, mpn, lcsc }, ctrl.signal)
      .then((l) => { setLedger(l); setError(null); })
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    // JLC's own ledger for the same part, when one has been synced. A 404 means
    // this part is not consigned to JLC, which is ordinary — not an error.
    setJlc(null);
    setSource("ours");
    if (lcsc) getJlcPartLedger(lcsc, ctrl.signal).then(setJlc).catch(() => setJlc(null));
    return () => ctrl.abort();
  }, [componentId, mpn, lcsc]);

  if (error) return <ErrorBanner message={error} />;
  if (!ledger) return <Spinner label="Replaying the ledger…" />;

  return (
    <div className="ledger-panel">
      <PartFigures row={row} />
      <div className="part-boxes">
        <ProjectsBox row={row} />
        <div className="part-box">
          <div className="part-box-head">
            <h3>Stock movements</h3>
            <div className="seg" role="group" aria-label="Whose ledger">
              <button type="button" className={source === "ours" ? "on" : ""}
                      onClick={() => setSource("ours")}>ours</button>
              <button type="button" className={source === "jlc" ? "on" : ""}
                      disabled={!jlc || jlc.rows.length === 0}
                      title={jlc ? "JLCPCB's own ledger for this part"
                                 : "not consigned to JLC, or the ledger is not synced"}
                      onClick={() => setSource("jlc")}>JLCPCB</button>
            </div>
          </div>
          <div className="part-box-body">
            {source === "ours" ? <OurMovements ledger={ledger} />
              : jlc ? <JlcMovements jlc={jlc} /> : null}
          </div>
        </div>
        <div className="part-box">
          <div className="part-box-head"><h3>Balance over time</h3></div>
          <div className="part-box-body part-box-chart">
            {ledger.events.length > 1
              ? <StepChart ledger={ledger} />
              : <p className="muted">One event — nothing to plot yet.</p>}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The operands of the comparison, as figures rather than columns.
 *
 *  "Ours then" and "Ours now" are BOTH here on purpose: the first is what the
 *  pool said at the instant JLC counted and is the only one Δ qty is about, the
 *  second is today. They are equal until a stock event lands after a sync, and
 *  the pair is what stops a reader explaining away a real disagreement as
 *  elapsed time.
 */
function PartFigures({ row }: { row: PartsStockRow }) {
  const consigned = row.state !== "pool_only";
  const stale = Math.round(row.remaining_qty) !== Math.round(row.remaining_at_sync_qty);
  const items: Array<{ label: string; value: string; className?: string; title?: string }> = [
    { label: "bought", value: qty(row.bought) },
    { label: "drawn", value: qty(row.drawn) },
    { label: "written off", value: row.lost ? qty(row.lost) : "—",
      title: "genuine attrition — a defect signal, not another project's draw" },
    { label: "ours when JLC counted", value: consigned ? qty(row.remaining_at_sync_qty) : "—" },
    { label: "ours now", value: qty(row.remaining_qty),
      className: stale ? "warn-text" : undefined,
      title: stale ? "stock has moved since JLC counted — Δ qty is about the earlier figure"
                   : undefined },
    { label: "JLC has", value: consigned ? qty(row.held_qty) : "—" },
    { label: "paid / unit", value: row.paid_unit_usd == null ? "—" : usd(row.paid_unit_usd, 4) },
    { label: "market / unit", value: row.market_unit_usd == null ? "—" : usd(row.market_unit_usd, 4) },
    { label: "at cost", value: usd(row.paid_value_usd) },
    { label: "unrealised", value: row.delta_value_usd == null ? "—" :
        `${row.delta_value_usd >= 0 ? "+" : ""}${usd(row.delta_value_usd)}`,
      className: (row.delta_value_usd ?? 0) < 0 ? "err-text" : undefined,
      title: "the remainder priced at today's market, less what was paid for it" },
  ];
  return (
    <div className="part-figures">
      {items.map((it) => (
        <div key={it.label} className="part-figure" title={it.title}>
          <span className={"part-figure-value " + (it.className ?? "")}>{it.value}</span>
          <span className="part-figure-label">{it.label}</span>
        </div>
      ))}
    </div>
  );
}

/** Where the part is used, one row per project AND board.
 *
 *  It replaces the "Held parts used in projects" card, which listed only parts
 *  JLC holds — so an enclosure, which no supplier consigns and which nothing
 *  else reports the usage of, appeared nowhere.
 */
function ProjectsBox({ row }: { row: PartsStockRow }) {
  return (
    <div className="part-box">
      <div className="part-box-head">
        <h3>Used by</h3>
        <span className="muted">
          {row.project_count === 0 ? "no project" :
            `${row.qty_per_device.toLocaleString()} per device · ` +
            (row.devices_coverable == null ? "" : `covers ${row.devices_coverable.toLocaleString()}`)}
        </span>
      </div>
      <div className="part-box-body">
        {row.projects.length === 0 ? (
          <p className="muted">
            No project&rsquo;s latest snapshot lists this part. It may be obsolete, or its
            board may not have been snapshotted yet.
          </p>
        ) : (
          <table className="data part-box-table">
            <thead>
              <tr><th>Project</th><th className="num">Qty/dev</th><th>Refs</th></tr>
            </thead>
            <tbody>
              {row.projects.map((p) => (
                <tr key={`${p.project_id}:${p.board}`}>
                  {/* board under the project rather than beside it: the box is
                      narrow, and a board name is long enough that its own column
                      truncated both it and the project to three characters */}
                  <td title={p.board}>
                    <Link to={`/projects/${p.project_id}`} onClick={(e) => e.stopPropagation()}>
                      {p.project_name}
                    </Link>
                    {p.board ? <span className="part-box-sub">{p.board}</span> : null}
                  </td>
                  <td className="num">{p.qty_per_device.toLocaleString()}</td>
                  <td className="mono dim" title={p.refs}>{p.refs || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/** Our events, most recent FIRST — the order a reader asks about them in. */
function OurMovements({ ledger }: { ledger: PartLedger }) {
  const rows = useMemo(() => [...ledger.events].reverse(), [ledger]);
  if (rows.length === 0) return <p className="muted">No recorded events for this part.</p>;
  return (
    <table className="data part-box-table">
      <thead>
        <tr>
          <th>Date</th><th>Event</th><th>Reference</th>
          <th className="num">Δ qty</th><th className="num">Balance</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((e, i) => (
          <tr key={i} className={e.short ? "ledger-short-row" : undefined}>
            <td className="mono date-cell">{e.date || "—"}</td>
            <td>
              <span className={"pill " + (e.kind === "buy" ? "ok" : e.kind === "adj" ? "warn" : "neutral")}>
                {KIND_LABEL[e.kind] ?? e.kind}
              </span>
            </td>
            <td title={e.detail ? `${e.ref} — ${e.detail}` : e.ref}>{e.ref || "—"}</td>
            <td className="num">
              {e.qty_delta != null && e.qty_delta > 0 ? "+" : ""}{qty(e.qty_delta)}
            </td>
            <td className={"num" + (e.short ? " err-text" : "")}
                title={e.short ? "stock below zero — missing invoice, unrecorded loss, or a batch that shipped without this part" : undefined}>
              {qty(e.balance_after)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Short on purpose: the cell is narrow and the pill is clipped before the
 *  note is, which is the column worth reading. The full wording is in the
 *  row's title. */
const BT_LABEL: Record<number, string> = {
  4: "SMT", 5: "parts", 10: "shelf",
};

/** What JLCPCB says happened, in their own words and their own order.
 *
 *  A `void` row is one JLC cancelled — it still states a quantity, and reading
 *  it as a movement reports a balance JLC does not agree with.
 */
function JlcMovements({ jlc }: { jlc: JlcPartLedger }) {
  const rows = useMemo(() => [...jlc.rows].reverse(), [jlc]);
  return (
    <table className="data part-box-table">
      <thead>
        <tr>
          <th>Date</th><th>Kind</th><th className="num">Δ qty</th>
          <th className="num">Balance</th><th>JLC&rsquo;s note</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className={r.void ? "dim" : undefined}>
            <td className="mono date-cell">{r.changed_at.slice(0, 10)}</td>
            <td>
              <span className={"pill " + (r.business_type === 10 ? "warn" : "neutral")}>
                {BT_LABEL[r.business_type] ?? "other"}
              </span>
            </td>
            <td className="num">{r.change_qty > 0 ? "+" : ""}{qty(r.change_qty)}</td>
            <td className="num">{r.void ? "—" : qty(r.qty_after)}</td>
            <td title={`${r.business_code}${r.remark ? ` — ${r.remark}` : ""}`}>
              {r.void ? <span className="pill">cancelled by JLC</span> : (r.remark || r.business_code || "—")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
