/** Stock — does the stock account close?
 *
 *  Every part measured BOTH ways on one row: what JLCPCB physically holds on
 *  consignment, next to what the cost pool says was paid and remains
 *  unconsumed. The verdict is the headline because the register's own
 *  identities cannot answer it — `pool.balanced` derives on-hand from
 *  purchases and draws, so it balances by construction whatever the real
 *  quantities are. On 2026-07-28 it read `balanced: true` while the pool held
 *  6,368 units JLC had never had.
 *
 *  The two gaps this view is built around:
 *
 *    Δ qty    held − pool remainder. Negative = the pool still counts parts
 *             JLC no longer has: an unrecorded draw, lost stock, or a draw
 *             counted twice. Positive = a purchase was never entered.
 *    Δ value  the SAME remainder at market vs at cost — what the stockpile
 *             gained or lost. Never "held at market vs remainder at cost",
 *             which would restate the quantity gap as money.
 *
 *  Row states: `jlc_only` = JLC holds it with NO purchase recorded — a
 *  missing invoice, found automatically. `pool_only` = bought somewhere JLC
 *  never saw (DigiKey, TME) — NOT a discrepancy, and excluded from the
 *  verdict so six real disagreements are not buried under seventy false ones.
 *
 *  This page replaced two overlapping surfaces (the old Parts stock page and
 *  the "Does the stock account close?" card on Invoices), which fetched the
 *  same endpoint three times between them.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  deleteStockAdjustment,
  errorMessage,
  getAllStockAdjustments,
  getJlcStock,
  getJlcStockUsage,
  getPartsStock,
  isAbortError,
  syncJlcStock,
  type JlcUsageRow,
  type PartsStock,
  type PartsStockRow,
  type StockAdjustment,
} from "../api";
import { useDialog } from "../components/Dialog";
import DataTable, { type Column } from "../components/DataTable";
import PartLedgerPanel from "../components/PartLedgerPanel";
import { ErrorBanner, Spinner } from "../components/Ui";
import { plain } from "../format";
import { useStickyState } from "../useStickyState";

const unitPrice = (v: number | null | undefined) => plain(v, 4);

function qty(v: number | null | undefined): string {
  if (v == null) return "—";
  return Math.round(v).toLocaleString();
}

type ColKey =
  | "mpn" | "lcsc" | "bought" | "drawn" | "lost" | "remaining_qty" | "held_qty"
  | "delta_qty" | "paid_unit_usd" | "market_unit_usd" | "paid_value_usd" | "delta_value_usd";

const COL_LABELS: Record<ColKey, string> = {
  mpn: "Part",
  lcsc: "LCSC",
  bought: "Bought",
  drawn: "Drawn",
  lost: "Written off",
  remaining_qty: "Ours",
  held_qty: "JLC has",
  delta_qty: "Δ qty",
  paid_unit_usd: "Paid unit",
  market_unit_usd: "Market unit",
  paid_value_usd: "At cost",
  delta_value_usd: "Δ value",
};

/** "disagree" is the working view: only the rows the verdict is about. */
type StateFilter = "disagree" | "all" | "both" | "pool_only" | "jlc_only";

const STATE_LABEL: Record<Exclude<StateFilter, "all" | "disagree">, string> = {
  both: "measured twice",
  pool_only: "not consigned to JLC",
  jlc_only: "at JLC, no invoice",
};

const disagrees = (r: PartsStockRow) => r.state === "both" && Math.abs(r.delta_qty ?? 0) > 0.5;

export default function Stock() {
  const dialog = useDialog();
  const [stock, setStock] = useState<PartsStock | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [usage, setUsage] = useState<JlcUsageRow[] | null>(null);
  const [adjs, setAdjs] = useState<StockAdjustment[] | null>(null);
  const [adjTotals, setAdjTotals] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [filter, setFilter] = useStickyState("stock:filter", "");
  const [stateFilter, setStateFilter] = useStickyState<StateFilter>("stock:state", "disagree");
  const [showAdjs, setShowAdjs] = useState(false);
  const [adjBusy, setAdjBusy] = useState<number | null>(null);
  // stock-over-time drill-down: which row's ledger is open (not sticky — a
  // reload should come back to the overview, not a stale expansion)
  const [openLedger, setOpenLedger] = useState<string | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    getPartsStock(signal)
      .then((s) => {
        setStock(s);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    // only for the credentials banner — every figure comes from /parts-stock
    getJlcStock(undefined, signal).then((s) => setAvailable(s.available)).catch(() => {});
    getJlcStockUsage(signal).then(setUsage).catch(() => setUsage(null));
    getAllStockAdjustments("", signal)
      .then((a) => {
        setAdjs(a.adjustments);
        setAdjTotals(a.totals as unknown as Record<string, unknown>);
      })
      .catch(() => setAdjs(null));
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  // ?q=<mpn or lcsc> is an entry point (the component page links here with
  // it) — applied once on mount, then the filters behave as normal.
  const [searchParams] = useSearchParams();
  useEffect(() => {
    const q = searchParams.get("q");
    if (q) {
      setFilter(q);
      setStateFilter("all");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doSync = () => {
    setSyncing(true);
    setSyncMsg(null);
    syncJlcStock()
      .then((r) => {
        setSyncing(false);
        setSyncMsg(`Synced ${r.items} part(s), ${r.valued} valued.`);
        load();
      })
      .catch((err) => {
        setSyncing(false);
        setError(errorMessage(err));
      });
  };

  async function removeAdj(a: StockAdjustment) {
    const ok = await dialog.confirm(
      `Delete adjustment ${a.id} (${a.qty_delta > 0 ? "+" : ""}${a.qty_delta} of ` +
        `${a.lcsc || a.mpn || `component ${a.component_id}`}, ${a.reason})? ` +
        `The stock balance moves by ${-a.qty_delta} and every batch's cost is replayed ` +
        `from the corrected history.`,
      { title: "Delete adjustment", confirmLabel: "Delete", tone: "danger" },
    );
    if (!ok) return;
    setAdjBusy(a.id);
    try {
      await deleteStockAdjustment(a.id);
      load();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not delete it" });
    } finally {
      setAdjBusy(null);
    }
  }

  const anyFilter = filter.trim() !== "" || stateFilter !== "disagree";

  const rows = useMemo(() => {
    let out = stock?.parts ?? [];
    if (stateFilter === "disagree") out = out.filter(disagrees);
    else if (stateFilter !== "all") out = out.filter((r) => r.state === stateFilter);
    const needle = filter.trim().toLowerCase();
    if (needle) {
      out = out.filter((r) =>
        r.mpn.toLowerCase().includes(needle) ||
        r.lcsc.toLowerCase().includes(needle) ||
        r.description.toLowerCase().includes(needle) ||
        (r.component_name ?? "").toLowerCase().includes(needle));
    }
    if (stateFilter === "disagree") {
      out = [...out].sort(
        (a, b) => Math.abs(b.delta_qty ?? 0) - Math.abs(a.delta_qty ?? 0));
    }
    return out;
  }, [stock, filter, stateFilter]);

  const counts = useMemo(() => {
    const c = { both: 0, pool_only: 0, jlc_only: 0, disagree: 0 };
    for (const r of stock?.parts ?? []) {
      c[r.state] += 1;
      if (disagrees(r)) c.disagree += 1;
    }
    return c;
  }, [stock]);

  const reconciles = counts.disagree === 0;
  const zeroCost = Number(adjTotals?.zero_cost_positive ?? 0);

  const t = stock?.totals;
  const unrealised =
    t && t.comparable_market_usd != null && t.comparable_cost_usd != null
      ? t.comparable_market_usd - t.comparable_cost_usd
      : null;

  // Column defs for the stock table. The toolbar's state chips and search box
  // pre-filter `rows`; sorting, per-column filtering and chunked rendering are
  // DataTable's, like every other list.
  const numCol = (key: ColKey, width: number, fmt: (r: PartsStockRow) => ReactNode): Column<PartsStockRow> => ({
    key,
    label: COL_LABELS[key],
    width,
    numeric: true,
    get: (r) => (r[key] as number | null) ?? "",
    render: fmt,
  });

  const stockCols: Column<PartsStockRow>[] = [
    {
      key: "mpn",
      label: COL_LABELS.mpn,
      width: 20,
      get: (r) => r.mpn || r.lcsc || "—",
      title: (r) =>
        (r.mpn || r.lcsc) +
        " — " +
        (r.description || "") +
        (r.state === "jlc_only"
          ? " — JLC holds this, no purchase recorded"
          : r.state === "pool_only"
            ? " — paid for, JLC does not hold it"
            : ""),
      render: (r) => (
        <>
          <span className="ledger-caret">{openLedger === r.key ? "▾" : "▸"}</span>
          {r.component_id ? (
            <Link
              to={`/library/components/${r.component_id}`}
              className="mono comp-link"
              onClick={(e) => e.stopPropagation()}
            >
              {r.mpn || r.lcsc || "—"}
            </Link>
          ) : (
            <span className="mono">{r.mpn || r.lcsc || "—"}</span>
          )}
          {r.state === "jlc_only" ? <span className="pill warn">no invoice</span> : null}
        </>
      ),
    },
    { key: "lcsc", label: COL_LABELS.lcsc, width: 9, className: "mono", get: (r) => r.lcsc || "—" },
    numCol("bought", 7, (r) => <>{qty(r.bought)}</>),
    numCol("drawn", 7, (r) => <>{qty(r.drawn)}</>),
    numCol("lost", 7, (r) => (r.lost ? <>{qty(r.lost)}</> : <span className="dim">—</span>)),
    numCol("remaining_qty", 7, (r) => <>{qty(r.remaining_qty)}</>),
    numCol("held_qty", 7, (r) => <>{r.state === "pool_only" ? "—" : qty(r.held_qty)}</>),
    numCol("delta_qty", 8, (r) => <DeltaCell r={r} />),
    numCol("paid_unit_usd", 7, (r) => <>{unitPrice(r.paid_unit_usd)}</>),
    numCol("market_unit_usd", 7, (r) => <>{unitPrice(r.market_unit_usd)}</>),
    numCol("paid_value_usd", 7, (r) => <>{plain(r.paid_value_usd)}</>),
    {
      key: "delta_value_usd",
      label: COL_LABELS.delta_value_usd,
      width: 7,
      numeric: true,
      className: "delta-value",
      get: (r) => r.delta_value_usd ?? "",
      title: (r) =>
        r.remaining_at_market_usd != null
          ? `remainder at market ${plain(r.remaining_at_market_usd)} USD`
          : "no market price for this part",
      render: (r) => (
        <span className={(r.delta_value_usd ?? 0) < 0 ? "err-text" : undefined}>
          {r.delta_value_usd == null
            ? "—"
            : `${r.delta_value_usd >= 0 ? "+" : ""}${plain(r.delta_value_usd)}`}
        </span>
      ),
    },
  ];

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Stock</h1>
          <span className="toolbar-total">
            {stock?.last_sync
              ? `JLC counted ${new Date(stock.last_sync).toLocaleString()}`
              : "JLC never synced"}
          </span>
          <button className="btn btn-primary" disabled={syncing} onClick={doSync}
                  title="Fetch JLCPCB's own consigned-stock count — the only external check the register has.">
            {syncing ? "Syncing stock count…" : "Sync stock count"}
          </button>
        </div>

        {error ? <ErrorBanner message={error} /> : null}
        {syncMsg ? <div className="banner-ok">{syncMsg}</div> : null}

        {available === false ? (
          <div className="banner-warn">
            JLCPCB API credentials are not configured, so the physical side is whatever was last
            cached. Apply at{" "}
            <a href="https://api.jlcpcb.com" target="_blank" rel="noreferrer">api.jlcpcb.com</a>,
            then set <span className="mono">JLC_APP_ID</span>,{" "}
            <span className="mono">JLC_ACCESS_KEY</span> and{" "}
            <span className="mono">JLC_SECRET_KEY</span> in <span className="mono">.env</span>{" "}
            and restart the api service.
          </div>
        ) : null}

        {stock === null && !error ? <Spinner label="Loading stock" /> : null}

        {stock && t ? (
          <>
            <div className="toolbar">
              <span className={`pill ${reconciles ? "ok" : "err"}`}>
                {reconciles ? "STOCK RECONCILES" : `${counts.disagree} PARTS DO NOT RECONCILE`}
              </span>
              <span className="pill neutral">{counts.both} parts measured twice</span>
              {counts.pool_only > 0 && (
                <span
                  className="pill neutral"
                  title="Bought somewhere JLC never held it — DigiKey, TME, Mouser, local. Not a discrepancy."
                >
                  {counts.pool_only} not consigned to JLC
                </span>
              )}
              {t.missing_invoice_parts > 0 && (
                <span
                  className="pill err"
                  title="JLC holds these and the platform has no purchase for them — a missing invoice."
                >
                  {t.missing_invoice_parts} held with no purchase
                </span>
              )}
              <span className={`pill ${zeroCost ? "warn" : "neutral"}`} title={ZERO_COST_HINT}>
                {zeroCost} zero-cost stock additions
              </span>
            </div>

            {!reconciles && (
              <div className="banner-warn">
                A positive Δ qty means JLC holds MORE than the platform accounts for — a purchase
                was never entered. A negative Δ qty means the platform still counts parts JLC no
                longer has: boards were built without recording the draw, the stock was lost, or
                a draw was counted twice.
              </div>
            )}

            <div className="card pad">
              <h2 className="card-title">The money in parts</h2>
              <p className="card-subtitle">
                The cost pool: what was paid for components, what batches have drawn from it, and what
                the unconsumed remainder cost — next to what that same remainder is worth today.
                All USD, because the pool's moving average is USD-denominated.
              </p>
              <div className="counts counts-sm">
                <div className="count-tile">
                  <div className="v">{plain(t.spent_usd)}</div>
                  <div className="muted">spent on parts</div>
                </div>
                <div className="count-tile">
                  <div className="v">{plain(t.drawn_usd)}</div>
                  <div className="muted">drawn by batches</div>
                </div>
                <div className="count-tile">
                  <div className="v">{plain(t.adjusted_usd)}</div>
                  <div className="muted">adjustments</div>
                </div>
                <div className="count-tile">
                  <div className="v">{plain(t.remaining_at_cost_usd)}</div>
                  <div className="muted">remainder at cost</div>
                </div>
                <div className="count-tile">
                  <div className="v">{plain(t.comparable_market_usd)}</div>
                  <div className="muted">same remainder at market</div>
                </div>
                <div className="count-tile">
                  <div className={unrealised != null && unrealised < 0 ? "v err-text" : "v"}>
                    {unrealised != null ? `${unrealised >= 0 ? "+" : ""}${plain(unrealised)}` : "—"}
                  </div>
                  <div className="muted">unrealised, priced parts only</div>
                </div>
                <div className="count-tile">
                  <div className="v">{qty(t.jlc_held_qty)}</div>
                  <div className="muted">pieces JLC holds</div>
                </div>
              </div>
              {t.missing_invoice_parts > 0 ? (
                <div className="banner-warn">
                  <strong>
                    {t.missing_invoice_parts} part(s) JLC holds have no purchase in the platform
                  </strong>{" "}
                  — worth {plain(t.missing_invoice_value_usd)} USD at market. Either the invoice is
                  missing, or the part is known here under a different MPN. Filter to “at JLC, no
                  invoice” below.
                </div>
              ) : null}
              {t.over_pool_parts > 0 ? (
                <div className="banner-warn">
                  {t.over_pool_parts} part(s) show a pool remainder larger than JLC now holds —
                  boards built without a recorded draw, or stock lost. Record the loss as a stock
                  adjustment so a run carries it.
                </div>
              ) : null}
            </div>

            <div className="toolbar">
              <input className="text search"
                     placeholder="Filter by MPN / LCSC / description / component…"
                     value={filter} onChange={(e) => setFilter(e.target.value)} />
              {(["disagree", "all", "both", "pool_only", "jlc_only"] as StateFilter[]).map((s) => (
                <button key={s} type="button"
                        className={"btn btn-sm" + (stateFilter === s ? " btn-accent" : "")}
                        onClick={() => setStateFilter(s)}>
                  {s === "disagree"
                    ? `disagreements ${counts.disagree}`
                    : s === "all"
                      ? `all ${stock.parts.length}`
                      : `${STATE_LABEL[s]} ${counts[s]}`}
                </button>
              ))}
              <span className="toolbar-total">{rows.length} / {stock.parts.length}</span>
              <button type="button" className="btn btn-sm" onClick={() => setShowAdjs((v) => !v)}>
                {showAdjs ? "hide adjustments" : `adjustments (${adjs?.length ?? 0})`}
              </button>
              {anyFilter ? (
                <button type="button" className="row-del clear-filters"
                        onClick={() => { setFilter(""); setStateFilter("disagree"); }}
                        title="Clear filters" aria-label="Clear filters">
                  &#x2715;
                </button>
              ) : null}
            </div>

            {showAdjs && adjs && (
              <div className="card pad">
                <h2 className="card-title">Stock adjustments</h2>
                <p className="card-subtitle">
                  The least evidenced write in the system — stock moving with no invoice behind it.
                  Including the ones that belong to no project, which the per-project view cannot
                  show and which is exactly what a reconciliation pass writes.
                </p>
                <div className="table-wrap">
                  <table className="data data-fixed stock-adj-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>part</th>
                        <th className="num">qty</th>
                        <th className="num">unit</th>
                        <th>reason</th>
                        <th>when</th>
                        <th>why</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {adjs.map((a) => {
                        const conjured = a.qty_delta > 0 && !a.unit_cost_usd;
                        return (
                          <tr key={a.id}>
                            <td className="mono">{a.id}</td>
                            <td className="mono" title={a.mpn || ""}>
                              {a.lcsc || a.mpn || `c${a.component_id}`}
                            </td>
                            <td className="num">
                              {a.qty_delta > 0 ? `+${a.qty_delta}` : a.qty_delta}
                            </td>
                            <td className="num">
                              {a.unit_cost_usd == null ? (
                                <span className="dim">avg</span>
                              ) : a.unit_cost_usd === 0 ? (
                                <span className="pill warn" title={ZERO_COST_HINT}>
                                  $0
                                </span>
                              ) : (
                                `$${a.unit_cost_usd}`
                              )}
                            </td>
                            <td>
                              <span className={`pill ${conjured ? "warn" : "neutral"}`}>
                                {a.reason}
                              </span>
                            </td>
                            <td className="muted dim">{a.adjusted_at || "—"}</td>
                            <td className="cell-desc" title={a.note}>
                              {a.note || <span className="dim">no reason given</span>}
                            </td>
                            <td>
                              <button
                                className="btn btn-sm btn-danger"
                                disabled={adjBusy === a.id}
                                onClick={() => removeAdj(a)}
                              >
                                Delete
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div className="card table-wrap">
              <DataTable
                columns={stockCols}
                rows={rows}
                rowKey={(r) => r.key}
                persistKey="stock"
                rowClass={() => "ledger-row"}
                openKey={openLedger}
                onOpenChange={(k) => setOpenLedger(k === null ? null : String(k))}
                expand={(r) => (
                  <PartLedgerPanel componentId={r.component_id} mpn={r.mpn} lcsc={r.lcsc} />
                )}
                empty={
                  stateFilter === "disagree" && !anyFilter
                    ? "Every part JLC holds agrees with the platform, piece for piece."
                    : "No parts match."
                }
              />
            </div>

            {usage && usage.length > 0 ? (
              <div className="card pad">
                <div className="card-title">Held parts used in projects</div>
                {usage.map((u) => (
                  <div key={u.project_id}>
                    <div className="card-subtitle">
                      <Link className="comp-link" to={`/projects/${u.project_id}`}>
                        {u.project_name}
                      </Link>
                    </div>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>LCSC</th>
                          <th>Board</th>
                          <th>Refs</th>
                          <th className="num">Qty / device</th>
                          <th className="num">Held at JLC</th>
                          <th className="num">Devices coverable</th>
                        </tr>
                      </thead>
                      <tbody>
                        {u.parts.map((p, i) => (
                          <tr key={i}>
                            <td className="mono">{p.lcsc}</td>
                            <td className="muted">{p.board}</td>
                            <td className="mono cell-fp">{p.refs}</td>
                            <td className="num">{p.qty_per_device}</td>
                            <td className="num">{p.held.toLocaleString()}</td>
                            <td className="num">
                              {p.qty_per_device > 0
                                ? Math.floor(p.held / p.qty_per_device).toLocaleString()
                                : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

const ZERO_COST_HINT =
  "Positive quantity with no cost attached — stock conjured from nothing. Legitimate for a " +
  "genuine opening balance, and invisible to every value check in the platform, which is how " +
  "6,368 phantom units survived until the quantities were compared against JLC by hand.";

/** The Δ qty cell, with the "adj" marker when `bought − drawn − written off`
 *  equals JLC's count exactly — meaning the WHOLE difference is an adjustment,
 *  which is exactly what the five invented opening balances looked like. */
/** The cell's CONTENT — DataTable owns the <td>. */
function DeltaCell({ r }: { r: PartsStockRow }) {
  const d = r.delta_qty;
  if (d == null) return <>—</>;
  const honest = r.bought - r.drawn - r.lost;
  const honestAgrees = r.state === "both" && Math.abs(honest - r.held_qty) < 0.5;
  return (
    <>
      <span className={`pill ${Math.abs(d) < 0.5 ? "ok" : d > 0 ? "err" : "warn"}`}>
        {d > 0 ? `+${qty(d)}` : qty(d)}
      </span>
      {honestAgrees && Math.abs(d) > 0.5 && (
        <span
          className="muted dim"
          title={
            "bought - drawn - written off equals JLC's count exactly, so the whole " +
            "difference is an adjustment. Check the adjustments list."
          }
        >
          {" "}
          adj
        </span>
      )}
    </>
  );
}
