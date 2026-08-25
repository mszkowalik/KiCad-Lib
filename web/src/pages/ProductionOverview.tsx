/** Production — the money answer in one place, and the trust checklist.
 *
 *  Everything here is a summary that links to the page that owns the detail:
 *  runs link to their own pages, the conservation row links to Invoices, the
 *  pool line links to Stock. The "before these numbers are final" list is the
 *  SINGLE home for open issues — it used to exist twice with different
 *  wording (dashboard bullets + register banners).
 *
 *  The per-run bars and the per-run table used to be two renderings of the
 *  same `by_run_usd` stacked on one page; here they are one table with an
 *  inline bar column (cost vs revenue on a shared scale, margin written as a
 *  number, never encoded in color alone).
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  errorMessage,
  getInvoiceRegister,
  getPartsStock,
  isAbortError,
  type InvoiceRegister,
  type PartsStock,
} from "../api";
import { ErrorBanner, Spinner } from "../components/Ui";
import { plain, usd } from "../format";
import DataTable, { type Column } from "../components/DataTable";

interface Issue {
  text: string;
  to: string;
}

export default function ProductionOverview() {
  const navigate = useNavigate();
  const [reg, setReg] = useState<InvoiceRegister | null>(null);
  const [stock, setStock] = useState<PartsStock | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getInvoiceRegister(ac.signal)
      .then((r) => {
        setReg(r);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getPartsStock(ac.signal)
      .then(setStock)
      .catch(() => setStock(null));
    return () => ac.abort();
  }, []);

  const rows = useMemo(() => {
    if (!reg) return [];
    return Object.entries(reg.by_run_usd)
      .map(([rid, m]) => {
        const info = reg.runs[rid];
        return info
          ? {
              rid: Number(rid),
              label: info.label,
              project: reg.projects[String(info.project_id)] ?? "?",
              qty: info.qty,
              cost: m.total_usd ?? 0,
              direct: m.direct_usd,
              components: m.components_usd,
              revenue: m.revenue_usd,
              margin: m.margin_usd,
              marginPct: m.margin_pct,
              salePrice: info.sale_unit_price,
              saleCurrency: info.sale_currency,
              customer: info.customer,
              orderRef: info.order_ref,
              date: info.run_date || "",
              priced: info.sale_unit_price != null,
            }
          : null;
      })
      .filter((r): r is NonNullable<typeof r> => r !== null)
      .sort((a, b) => a.date.localeCompare(b.date) || a.rid - b.rid);
  }, [reg]);

  const totals = useMemo(() => {
    const cost = rows.reduce((s, r) => s + r.cost, 0);
    const revenue = rows.reduce((s, r) => s + (r.revenue ?? 0), 0);
    const devices = rows.reduce((s, r) => s + r.qty, 0);
    return {
      cost,
      revenue,
      profit: revenue - cost,
      devices,
      marginPct: revenue ? (100 * (revenue - cost)) / revenue : null,
    };
  }, [rows]);

  const scale = useMemo(
    () => Math.max(...rows.map((r) => Math.max(r.cost, r.revenue ?? 0)), 1),
    [rows],
  );

  // The single home for "what is still missing before these numbers are
  // final" — every entry links to the page that fixes it.
  const issues = useMemo<Issue[]>(() => {
    if (!reg) return [];
    const out: Issue[] = [];
    for (const p of reg.documents.filter((d) => (d.doc_number || "").includes("PLACEHOLDER"))) {
      out.push({
        text: `Placeholder document ${p.doc_number} (${usd(p.total_usd, 2)}) — replace with the real invoice when it surfaces.`,
        to: "/production/invoices",
      });
    }
    for (const r of rows.filter((r) => !r.priced)) {
      out.push({
        text: `No sale price on ${r.project} · ${r.label} — revenue and margin are blank there.`,
        to: `/runs/${r.rid}`,
      });
    }
    for (const u of reg.issues.unreconciled) {
      out.push({
        text: `${u.supplier} ${u.doc_number}: lines (${plain(u.lines_total)}) do not add up to the printed total (${plain(u.total_amount)} ${u.currency}).`,
        to: "/production/invoices",
      });
    }
    for (const u of reg.issues.unassigned) {
      out.push({
        text: `${u.supplier} ${u.doc_number}: ${usd(u.amount_usd, 2)} not assigned to anything yet.`,
        to: "/production/invoices",
      });
    }
    for (const n of reg.issues.negative_stock ?? []) {
      out.push({
        text: `${n.component_name || n.mpn}: stock goes ${n.min_qty} at ${n.first_short} — a purchase document is missing.`,
        to: "/production/stock",
      });
    }
    if (reg.summary.unknown_rates.length) {
      out.push({
        text: `No exchange rate for ${reg.summary.unknown_rates.join(", ")} — those documents count at face value, so the totals are understated.`,
        to: "/setup",
      });
    }
    if (stock) {
      const disagree = stock.parts.filter(
        (p) => p.state === "both" && Math.abs(p.delta_qty ?? 0) > 0.5,
      );
      if (disagree.length) {
        const gap = disagree.reduce(
          (s, p) => s + Math.abs((p.delta_qty ?? 0) * (p.paid_unit_usd ?? 0)),
          0,
        );
        out.push({
          text: `${disagree.length} part(s) disagree with JLCPCB's consigned count (${usd(gap, 0)} at cost) — a purchase, a draw or a write-off is missing.`,
          to: "/production/stock",
        });
      }
      if (stock.totals.missing_invoice_parts > 0) {
        out.push({
          text: `${stock.totals.missing_invoice_parts} part(s) JLC holds have no purchase in the platform — a missing invoice.`,
          to: "/production/stock",
        });
      }
    }
    return out;
  }, [reg, rows, stock]);

  const runCols: Column<(typeof rows)[number]>[] = [
  {
    key: "label",
    label: "Batch",
    width: 16,
    get: (r) => r.label,
    render: (r) => (
      <Link className="comp-link" to={`/runs/${r.rid}`} onClick={(e) => e.stopPropagation()}>
        {r.label}
      </Link>
    ),
  },
  { key: "project", label: "Project", width: 12, className: "muted", get: (r) => r.project },
  { key: "qty", label: "Units", width: 6, numeric: true, get: (r) => r.qty },
  {
    key: "cost",
    label: "Cost USD",
    width: 8,
    numeric: true,
    get: (r) => r.cost,
    title: (r) => `direct ${plain(r.direct)} + components ${plain(r.components)}`,
    render: (r) => <>{plain(r.cost)}</>,
  },
  {
    key: "cost_dev",
    label: "Cost/dev",
    width: 7,
    numeric: true,
    get: (r) => (r.qty ? r.cost / r.qty : ""),
    render: (r) => <>{r.qty ? plain(r.cost / r.qty) : "—"}</>,
  },
  {
    key: "sale",
    label: "Sale",
    width: 9,
    numeric: true,
    interactive: false,
    get: (r) => r.salePrice ?? "",
    render: (r) => (
      <Link
        className="btn btn-sm"
        to={`/runs/${r.rid}`}
        title="The sale is edited on the batch's own page"
        onClick={(e) => e.stopPropagation()}
      >
        {r.salePrice != null ? `${r.salePrice} ${r.saleCurrency || ""}`.trim() : "set price"}
      </Link>
    ),
  },
  {
    key: "revenue",
    label: "Revenue USD",
    width: 9,
    numeric: true,
    get: (r) => r.revenue ?? "",
    render: (r) => <>{plain(r.revenue)}</>,
  },
  {
    key: "rev_dev",
    label: "Rev/dev",
    width: 7,
    numeric: true,
    get: (r) => (r.revenue != null && r.qty ? r.revenue / r.qty : ""),
    title: () => "revenue over the devices built in this batch",
    render: (r) => <>{r.revenue != null && r.qty ? plain(r.revenue / r.qty) : "—"}</>,
  },
  {
    key: "margin",
    label: "Margin USD",
    width: 8,
    numeric: true,
    get: (r) => r.margin ?? "",
    render: (r) => (
      <span className={(r.margin ?? 0) < 0 ? "err-text" : undefined}>{plain(r.margin)}</span>
    ),
  },
  {
    key: "margin_pct",
    label: "Margin %",
    width: 7,
    numeric: true,
    get: (r) => r.marginPct ?? "",
    title: (r) =>
      r.customer || r.orderRef
        ? `${r.customer}${r.orderRef ? ` · ${r.orderRef}` : ""}`
        : "no customer recorded",
    render: (r) => (
      <span className={(r.marginPct ?? 0) < 0 ? "err-text" : undefined}>
        {r.marginPct == null ? "—" : `${r.marginPct.toFixed(1)}%`}
      </span>
    ),
  },
  {
    key: "bar",
    label: "cost → revenue",
    width: 11,
    interactive: false,
    get: () => "",
    title: (r) =>
      `wide bar = revenue ${usd(r.revenue ?? 0, 0)} · narrow bar = cost ${usd(r.cost, 0)} — both drawn on one scale shared by every batch, so bar lengths compare across rows`,
    render: (r) => (
      <span className="dash-bar-track">
        <span className="dash-bar rev" style={{ width: `${(100 * (r.revenue ?? 0)) / scale}%` }} />
        <span className="dash-bar cost" style={{ width: `${(100 * r.cost) / scale}%` }} />
      </span>
    ),
  },
];


  if (error && !reg) {
  return (
      <div className="main-solo">
        <div className="page">
          <ErrorBanner message={error} />
        </div>
      </div>
    );
  }
  if (!reg) {
    return (
      <div className="main-solo">
        <div className="page">
          <Spinner label="Loading production economics" />
        </div>
      </div>
    );
  }

  const s = reg.summary;

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Production</h1>
          <span className="toolbar-total">
            costs from settled invoices and pool draws · revenue at each order&apos;s FX date
          </span>
        </div>
        {error ? <ErrorBanner message={error} /> : null}

        <div className="card pad">
          <div className="dash-tiles">
            <div className="count-tile">
              <span className="v">{usd(totals.revenue, 0)}</span>
              <span className="k">revenue</span>
            </div>
            <div className="count-tile">
              <span className="v">{usd(totals.cost, 0)}</span>
              <span className="k">production cost</span>
            </div>
            <div className="count-tile">
              <span className="v">{usd(totals.profit, 0)}</span>
              <span className="k">gross profit</span>
            </div>
            <div className="count-tile">
              <span className="v">
                {totals.marginPct != null ? totals.marginPct.toFixed(1) + "%" : "—"}
              </span>
              <span className="k">gross margin</span>
            </div>
            <div className="count-tile">
              <span className="v">{totals.devices.toLocaleString()}</span>
              <span className="k">devices built</span>
            </div>
            <div className="count-tile">
              <span className="v">
                {totals.devices ? usd(totals.cost / totals.devices, 2) : "—"}
              </span>
              <span className="k">avg cost / device</span>
            </div>
            <div className="count-tile">
              <span className="v">
                {totals.devices ? usd(totals.revenue / totals.devices, 2) : "—"}
              </span>
              <span className="k">avg revenue / device</span>
            </div>
          </div>

          {issues.length ? (
            <div className="dash-missing">
              <h3 className="card-subtitle">Before these numbers are final</h3>
              <ul>
                {issues.map((m, i) => (
                  <li key={i}>
                    {m.text} <Link to={m.to}>fix →</Link>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="banner-ok">
              Nothing known to be missing — every document reconciles, every batch is fully
              costed, and the stock agrees with JLCPCB.
            </div>
          )}
        </div>

        <div className="card pad">
          <h2 className="card-title">What each batch cost, and what it earned</h2>
          <p className="card-subtitle">
            Cost is direct invoice positions plus what the run drew from the component pool.
            Revenue is the price per device times the units billed, converted at the order
            date. Wide bar = revenue, narrow bar = cost, shared scale. Margin is gross
            (materials, boards, assembly, labour, freight — not firmware, warranty or your
            time). Every batch links to its own page — click anywhere on its row.
          </p>
          <div className="table-wrap">
            <DataTable
              columns={runCols}
              rows={rows}
              rowKey={(r) => r.rid}
              persistKey="production-runs"
              rowClass={() => "ledger-row"}
              onRowClick={(r) => navigate(`/runs/${r.rid}`)}
              empty="No batch has been charged yet."
            />
          </div>
        </div>

        <div className="card pad">
          <h2 className="card-title">Where the money went</h2>
          <p className="card-subtitle">
            Every document&apos;s total lands in exactly one bucket — the conservation check.
            Assign and split positions on <Link to="/production/invoices">Invoices</Link>; the
            pool reconciles part by part on <Link to="/production/stock">Stock</Link>.
          </p>
          <div className="table-wrap">
            <table className="data data-fixed invoice-sum-table">
              <thead>
                <tr>
                  <th className="num">Invoiced</th>
                  <th className="num">To runs</th>
                  <th className="num">To projects</th>
                  <th className="num">To the pool</th>
                  <th className="num">Excluded</th>
                  <th className="num">Unassigned</th>
                  <th className="num">Residual</th>
                  <th className="num">Gap</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="num">{plain(s.total_usd)}</td>
                  <td className="num">{plain(s.to_runs_usd)}</td>
                  <td className="num">{plain(s.to_projects_usd)}</td>
                  <td className="num">{plain(s.to_pool_usd)}</td>
                  <td
                    className="num muted"
                    title="reclaimable VAT and prepaid components already in the pool"
                  >
                    {plain(s.excluded_usd)}
                  </td>
                  <td className={s.unassigned_usd ? "num" : "num muted"}>
                    {s.unassigned_usd ? (
                      <span className="pill warn">{plain(s.unassigned_usd)}</span>
                    ) : (
                      plain(s.unassigned_usd)
                    )}
                  </td>
                  <td className={s.residual_usd ? "num" : "num muted"}>
                    {s.residual_usd ? (
                      <span className="pill warn">{plain(s.residual_usd)}</span>
                    ) : (
                      plain(s.residual_usd)
                    )}
                  </td>
                  <td className="num">
                    {Math.abs(s.gap_usd ?? 0) < 0.05 ? (
                      <span className="pill ok">0</span>
                    ) : (
                      <span className="pill err">{plain(s.gap_usd)}</span>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="muted">
            Component pool: purchased {plain(reg.pool.purchased_usd)} ± adjustments{" "}
            {plain(reg.pool.adjustments_usd)} − drawn {plain(reg.pool.drawn_usd)} ={" "}
            {plain(reg.pool.on_hand_usd)} on hand across {reg.pool.part_count} parts —{" "}
            <span className={reg.pool.balanced ? "pill ok" : "pill err"}>
              {reg.pool.balanced ? "balanced" : "does not balance"}
            </span>{" "}
            <span
              className="dim"
              title="Balanced by construction — on-hand is derived from the other three. The real check is the quantity comparison against JLCPCB on the Stock page."
            >
              (identity — the real check is <Link to="/production/stock">Stock</Link>)
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}
