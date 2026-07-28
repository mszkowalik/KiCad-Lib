/** The money answer in one card: what production cost, what it earned, per batch
 *  and in total — and what is still missing before those numbers can be trusted.
 *
 *  Everything is derived from the register (one fetch the page already makes)
 *  plus Parts stock for the consignment gap. Bars are cost-vs-revenue on a
 *  shared scale so batches are comparable at a glance; margin is written as a
 *  number, not encoded in color alone.
 */
import { useEffect, useMemo, useState } from "react";
import {
  getPartsStock,
  isAbortError,
  type InvoiceRegister,
  type PartsStock,
} from "../../api";

function usd(v: number | null | undefined, digits = 0): string {
  if (v == null) return "—";
  return "$" + v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export default function ProductionDashboard({ reg }: { reg: InvoiceRegister }) {
  const [stock, setStock] = useState<PartsStock | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    getPartsStock(ac.signal).then(setStock).catch((e) => { if (!isAbortError(e)) setStock(null); });
    return () => ac.abort();
  }, []);

  const rows = useMemo(() => {
    return Object.entries(reg.by_run_usd)
      .map(([rid, m]) => {
        const info = reg.runs[rid];
        return info ? {
          rid: Number(rid),
          label: `${reg.projects[String(info.project_id)] ?? "?"} · ${info.label}`,
          qty: info.qty,
          cost: m.total_usd ?? 0,
          revenue: m.revenue_usd,
          margin: m.margin_usd,
          marginPct: m.margin_pct,
          perDevice: info.qty ? (m.total_usd ?? 0) / info.qty : null,
          priced: info.sale_unit_price != null,
        } : null;
      })
      .filter((r): r is NonNullable<typeof r> => r !== null)
      .sort((a, b) => a.rid - b.rid);
  }, [reg]);

  const totals = useMemo(() => {
    const cost = rows.reduce((s, r) => s + r.cost, 0);
    const revenue = rows.reduce((s, r) => s + (r.revenue ?? 0), 0);
    const devices = rows.reduce((s, r) => s + r.qty, 0);
    return { cost, revenue, profit: revenue - cost, devices,
             marginPct: revenue ? (100 * (revenue - cost)) / revenue : null };
  }, [rows]);

  const scale = useMemo(
    () => Math.max(...rows.map((r) => Math.max(r.cost, r.revenue ?? 0)), 1),
    [rows]);

  // what is still missing before these numbers are final
  const missing = useMemo(() => {
    const out: string[] = [];
    const placeholders = reg.documents.filter((d) => (d.doc_number || "").includes("PLACEHOLDER"));
    for (const p of placeholders) {
      out.push(`Placeholder document ${p.doc_number} (${usd(p.total_usd, 2)}) — replace with the real invoice when it surfaces.`);
    }
    const unpriced = rows.filter((r) => !r.priced);
    if (unpriced.length) {
      out.push(`No sale price on: ${unpriced.map((r) => r.label).join(", ")} — revenue and margin are blank there.`);
    }
    for (const u of reg.issues.unreconciled) {
      out.push(`${u.supplier} ${u.doc_number}: lines do not add up to the printed total.`);
    }
    for (const u of reg.issues.unassigned) {
      out.push(`${u.supplier} ${u.doc_number}: ${usd(u.amount_usd, 2)} not assigned to anything yet.`);
    }
    for (const n of reg.issues.negative_stock ?? []) {
      out.push(`${n.component_name || n.mpn}: stock goes ${n.min_qty} at ${n.first_short} — a purchase document is missing.`);
    }
    if (stock) {
      const gap = stock.parts
        .filter((p) => p.state === "both" && (p.delta_qty ?? 0) < -0.5)
        .reduce((s, p) => s + Math.abs((p.delta_qty ?? 0) * (p.paid_unit_usd ?? 0)), 0);
      if (gap > 50) {
        out.push(`${usd(gap, 0)} of consigned parts the pool holds but JLC does not — consumed by ` +
                 `builds outside the platform (LIDAR, reworks, the in-flight July 2026 run); ` +
                 `becomes their runs' cost when those invoices are entered.`);
      }
    }
    return out;
  }, [reg, rows, stock]);

  return (
    <div className="card pad">
      <h2 className="card-title">Production economics</h2>
      <p className="card-subtitle">
        All batches, costs from settled invoices and pool draws, revenue at each order's FX date.
      </p>

      <div className="dash-tiles">
        <div className="count-tile"><span className="v">{usd(totals.revenue)}</span><span className="k">revenue</span></div>
        <div className="count-tile"><span className="v">{usd(totals.cost)}</span><span className="k">production cost</span></div>
        <div className="count-tile"><span className="v">{usd(totals.profit)}</span><span className="k">gross profit</span></div>
        <div className="count-tile">
          <span className="v">{totals.marginPct != null ? totals.marginPct.toFixed(1) + "%" : "—"}</span>
          <span className="k">gross margin</span>
        </div>
        <div className="count-tile"><span className="v">{totals.devices.toLocaleString()}</span><span className="k">devices built</span></div>
        <div className="count-tile">
          <span className="v">{totals.devices ? usd(totals.cost / totals.devices, 2) : "—"}</span>
          <span className="k">avg cost / device</span>
        </div>
      </div>

      <div className="dash-bars">
        {rows.map((r) => (
          <div key={r.rid} className="dash-bar-row" title={
            `${r.label}: cost ${usd(r.cost, 2)}, revenue ${usd(r.revenue, 2)}, ` +
            `margin ${r.marginPct != null ? r.marginPct.toFixed(1) + "%" : "—"}, ` +
            `${usd(r.perDevice, 2)}/device over ${r.qty} devices`}>
            <span className="dash-bar-label">{r.label}</span>
            <span className="dash-bar-track">
              <span className="dash-bar rev" style={{ width: `${(100 * (r.revenue ?? 0)) / scale}%` }} />
              <span className="dash-bar cost" style={{ width: `${(100 * r.cost) / scale}%` }} />
            </span>
            <span className="dash-bar-nums num">
              {usd(r.cost)} → {r.revenue != null ? usd(r.revenue) : "—"}
              <span className={"dash-margin" + ((r.margin ?? 0) < 0 ? " err-text" : "")}>
                {r.marginPct != null ? ` ${r.marginPct.toFixed(1)}%` : ""}
              </span>
            </span>
          </div>
        ))}
      </div>
      <p className="muted dash-legend">
        wide bar = revenue, narrow bar = production cost; margin is gross (materials, boards,
        assembly, labour, freight — not firmware, warranty or your time)
      </p>

      {missing.length ? (
        <div className="dash-missing">
          <h3 className="card-subtitle">Before these numbers are final</h3>
          <ul>
            {missing.map((m, i) => <li key={i}>{m}</li>)}
          </ul>
        </div>
      ) : (
        <div className="banner-ok">Nothing known to be missing — every document reconciles and every batch is fully costed.</div>
      )}
    </div>
  );
}
