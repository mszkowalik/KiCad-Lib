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
 *  inline bar column. COSTS ONLY: a batch earns nothing, and revenue and margin
 *  live on the ORDER — a device carries its batch's unit cost there, and that
 *  is the whole link between the two (decision 0043).
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
              produced: m.produced ?? 0,
              unitCost: m.unit_cost_usd,
              date: info.run_date || "",
            }
          : null;
      })
      .filter((r): r is NonNullable<typeof r> => r !== null)
      .sort((a, b) => a.date.localeCompare(b.date) || a.rid - b.rid);
  }, [reg]);

  const totals = useMemo(() => {
    const cost = rows.reduce((s, r) => s + r.cost, 0);
    const devices = rows.reduce((s, r) => s + r.qty, 0);
    const produced = rows.reduce((s, r) => s + r.produced, 0);
    return { cost, devices, produced };
  }, [rows]);

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
        to: "/admin?tab=rates",
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
    // 28, not 24: measured at 1280px, the longest label ("Prototypes 1 —
    // PROFORMA 1/11/2023") needs 26.8% and was the one cell that clipped. The
    // four points come from Produced and Cost/dev, which hold at most
    // "14,263.59" and had room to spare.
    width: 28,
    get: (r) => r.label,
    render: (r) => (
      <Link className="comp-link" to={`/runs/${r.rid}`} onClick={(e) => e.stopPropagation()}>
        {r.label}
      </Link>
    ),
  },
  { key: "project", label: "Project", width: 14, className: "muted", get: (r) => r.project },
  // The batch's start date. It was already on the row and sorted the array; the
  // table now sorts by it, newest first, so the column has to be VISIBLE — a
  // default order nothing on screen explains reads as no order at all.
  { key: "date", label: "Date", width: 12, className: "mono", get: (r) => r.date || "—" },
  { key: "qty", label: "Units", width: 8, numeric: true, get: (r) => r.qty },
  {
    key: "cost",
    label: "Cost USD",
    width: 14,
    numeric: true,
    get: (r) => r.cost,
    title: (r) => `direct ${plain(r.direct)} + components ${plain(r.components)}`,
    render: (r) => <>{plain(r.cost)}</>,
  },
  {
    key: "produced",
    label: "Produced",
    width: 12,
    numeric: true,
    get: (r) => r.produced,
    title: () => "devices recorded as produced on this batch — the denominator of its unit cost",
    render: (r) => <>{r.produced || "—"}</>,
  },
  {
    key: "cost_dev",
    label: "Cost/dev",
    width: 12,
    numeric: true,
    get: (r) => r.unitCost ?? "",
    title: (r) => r.unitCost == null
      ? "No devices are recorded as produced yet, so there is nothing to divide by"
      : "What one device of this batch cost — carried onto whatever order ships it",
    render: (r) => <>{r.unitCost == null ? "—" : plain(r.unitCost)}</>,
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
            costs from settled invoices and pool draws · revenue lives on the orders
          </span>
        </div>
        {error ? <ErrorBanner message={error} /> : null}

        <div className="card pad">
          <div className="dash-tiles">
            {/* COSTS ONLY. A batch earns nothing — revenue and margin live on
                the ORDER, and a device carries its batch's unit cost there
                (decision 0043). */}
            <div className="count-tile">
              <span className="v">{usd(totals.cost, 0)}</span>
              <span className="k">production cost</span>
            </div>
            <div className="count-tile">
              <span className="v">{totals.devices.toLocaleString()}</span>
              <span className="k">boards ordered</span>
            </div>
            <div className="count-tile">
              <span className="v">{totals.produced.toLocaleString()}</span>
              <span className="k">devices produced</span>
            </div>
            <div className="count-tile">
              <span className="v">
                {totals.produced ? usd(totals.cost / totals.produced, 2) : "—"}
              </span>
              <span className="k">avg cost / device produced</span>
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
          <h2 className="card-title">What each batch cost</h2>
          <p className="card-subtitle">Newest batch first</p>
          <p className="muted dim">
            Cost is direct invoice positions plus what the run drew from the component pool
            (materials, boards, assembly, labour, freight — not firmware, warranty or your
            time). Cost/dev divides by the devices recorded as PRODUCED, which is what a
            shipped unit carries onto its order; a batch with no device records yet shows no
            figure rather than an estimate. Revenue and margin are on the orders. Every
            batch links to its own page — click anywhere on its row.
          </p>
          <div className="table-wrap">
            <DataTable
              columns={runCols}
              rows={rows}
              rowKey={(r) => r.rid}
              defaultSort={{ key: "date", dir: "desc" }}
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
                    title={"Charged to nobody on purpose: reclaimable VAT, and prepaid "
                      + "components already in the pool.\n\n"
                      + Object.entries(s.excluded_by_reason_usd || {})
                          .map(([r, v]) => `${r}: ${plain(v)}`).join("\n")}
                  >
                    {plain(s.excluded_usd)}
                    {s.excluded_unstated_usd ? (
                      <>
                        {" "}
                        <span
                          className="pill warn"
                          title={"This much of the excluded money gives no reason. "
                            + "`excluded` is a legal bucket in the identity, so an "
                            + "exclusion is invisible to every other check — which is "
                            + "how $14,443 of manufacturing once sat charged to nobody "
                            + "while this page read clean."}
                        >
                          {plain(s.excluded_unstated_usd)} unstated
                        </span>
                      </>
                    ) : null}
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
                  {/* NO TOLERANCE. This is an invariant on the platform's own
                      arithmetic, so anything but zero is a bug. It used to print
                      a green "0" for anything under 0.05, which is how a
                      permanent 0.0271 stayed invisible for months — the check
                      was rounding away its own alarm (decision 0048). */}
                  <td className="num">
                    {(s.gap_usd ?? 0) === 0 ? (
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
