/** Parts stock — every part measured BOTH ways, on one row.
 *
 *  Two questions that look like one and are routinely different:
 *
 *    physical  what JLCPCB holds on consignment, at today's market price
 *    money     what the cost pool says was PAID, and how much is still unconsumed
 *
 *  Showing them apart hides the interesting number, so this view is built around
 *  the two gaps (user asked for the pool "in the same view", 2026-07-27):
 *
 *    Δ qty    held − pool remainder. Negative = the pool still counts parts JLC
 *             no longer has: boards were built without recording the draw, or
 *             stock was lost and needs a write-off.
 *    Δ value  the SAME remainder at market vs at cost — what the stockpile has
 *             gained or lost. Never "held at market vs remainder at cost", which
 *             would just restate the quantity gap as money.
 *
 *  And the row state earns its keep: `jlc_only` means JLC is holding parts the
 *  platform has no purchase for — i.e. a MISSING INVOICE, found automatically.
 *
 *  Everything is USD: the pool's moving average is USD-denominated, so a
 *  per-currency toggle would only apply to half the columns.
 */
import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getJlcStock,
  getJlcStockUsage,
  getPartsStock,
  isAbortError,
  syncJlcStock,
  type JlcUsageRow,
  type PartsStock,
  type PartsStockRow,
} from "../api";
import PartLedgerPanel from "../components/PartLedgerPanel";
import { ErrorBanner, Spinner } from "../components/Ui";
import { useStickyState } from "../useStickyState";

function usd(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function unitPrice(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 });
}

function qty(v: number | null | undefined): string {
  if (v == null) return "—";
  return Math.round(v).toLocaleString();
}

type ColKey =
  | "mpn" | "lcsc" | "description" | "held_qty" | "remaining_qty" | "delta_qty"
  | "paid_unit_usd" | "market_unit_usd" | "paid_value_usd" | "delta_value_usd";

const COL_LABELS: Record<ColKey, string> = {
  mpn: "Mfg PN",
  lcsc: "LCSC",
  description: "Description",
  held_qty: "Held @ JLC",
  remaining_qty: "Pool left",
  delta_qty: "Δ qty",
  paid_unit_usd: "Paid unit",
  market_unit_usd: "Market unit",
  paid_value_usd: "At cost",
  delta_value_usd: "Δ value",
};

const NUMERIC: ReadonlySet<ColKey> = new Set<ColKey>([
  "held_qty", "remaining_qty", "delta_qty", "paid_unit_usd",
  "market_unit_usd", "paid_value_usd", "delta_value_usd",
]);

function colValue(r: PartsStockRow, col: ColKey): string {
  const v = r[col];
  return v == null ? "" : String(v);
}

function sortRows(rows: PartsStockRow[], sort: { col: ColKey; dir: "asc" | "desc" }) {
  const mul = sort.dir === "asc" ? 1 : -1;
  const out = [...rows];
  if (NUMERIC.has(sort.col)) {
    const col = sort.col;
    out.sort((a, b) => {
      const av = a[col] as number | null;
      const bv = b[col] as number | null;
      // missing values last regardless of direction
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * mul;
    });
  } else {
    const col = sort.col;
    out.sort((a, b) =>
      colValue(a, col).toLowerCase().localeCompare(colValue(b, col).toLowerCase()) * mul);
  }
  return out;
}

type StateFilter = "all" | "both" | "pool_only" | "jlc_only";

const STATE_LABEL: Record<Exclude<StateFilter, "all">, string> = {
  both: "measured twice",
  pool_only: "paid for, not at JLC",
  jlc_only: "at JLC, no invoice",
};

export default function JlcStock() {
  const [stock, setStock] = useState<PartsStock | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [usage, setUsage] = useState<JlcUsageRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [filter, setFilter] = useStickyState("jlc:filter", "");
  const [stateFilter, setStateFilter] = useStickyState<StateFilter>("jlc:state", "all");
  const [sort, setSort] = useStickyState<{ col: ColKey; dir: "asc" | "desc" } | null>(
    "jlc:sort2", null);
  const [colFilters, setColFilters] = useStickyState<Partial<Record<ColKey, string>>>(
    "jlc:colFilters2", {});
  // stock-over-time drill-down: which row's ledger is open (not sticky — a
  // reload should come back to the overview, not a stale expansion)
  const [openLedger, setOpenLedger] = useState<string | null>(null);

  const load = (signal?: AbortSignal) => {
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
  };

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
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

  const anyFilter =
    filter.trim() !== "" || stateFilter !== "all" ||
    Object.values(colFilters).some((v) => v !== undefined && v.trim() !== "");

  const rows = useMemo(() => {
    let out = stock?.parts ?? [];
    if (stateFilter !== "all") out = out.filter((r) => r.state === stateFilter);
    const needle = filter.trim().toLowerCase();
    if (needle) {
      out = out.filter((r) =>
        r.mpn.toLowerCase().includes(needle) ||
        r.lcsc.toLowerCase().includes(needle) ||
        r.description.toLowerCase().includes(needle) ||
        (r.component_name ?? "").toLowerCase().includes(needle));
    }
    const active = (Object.entries(colFilters) as Array<[ColKey, string]>)
      .filter(([, v]) => v.trim() !== "");
    if (active.length) {
      out = out.filter((r) => active.every(([col, v]) =>
        colValue(r, col).toLowerCase().includes(v.trim().toLowerCase())));
    }
    if (sort) out = sortRows(out, sort);
    return out;
  }, [stock, filter, stateFilter, colFilters, sort]);

  const counts = useMemo(() => {
    const c = { both: 0, pool_only: 0, jlc_only: 0 };
    for (const r of stock?.parts ?? []) c[r.state] += 1;
    return c;
  }, [stock]);

  const cycleSort = (col: ColKey) =>
    setSort((prev) =>
      prev === null || prev.col !== col
        ? { col, dir: "asc" }
        : prev.dir === "asc" ? { col, dir: "desc" } : null);

  const sortTh = (col: ColKey) => (
    <th className={NUMERIC.has(col) ? "num" : undefined}>
      <button type="button" className="th-sort" onClick={() => cycleSort(col)}
              title={`Sort by ${COL_LABELS[col]}`}>
        {COL_LABELS[col]}
        {sort?.col === col ? (
          <span className="sort-ind">{sort.dir === "asc" ? "▲" : "▼"}</span>
        ) : null}
      </button>
    </th>
  );

  const filterTd = (col: ColKey) => (
    <td>
      <input type="text" className="text filter-input" placeholder="filter…"
             value={colFilters[col] ?? ""}
             onChange={(e) => setColFilters((f) => ({ ...f, [col]: e.target.value }))}
             aria-label={`Filter ${COL_LABELS[col]}`} />
    </td>
  );

  const t = stock?.totals;
  const unrealised =
    t && t.comparable_market_usd != null && t.comparable_cost_usd != null
      ? t.comparable_market_usd - t.comparable_cost_usd
      : null;

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Parts stock</h1>
          <span className="toolbar-total">
            {stock?.last_sync
              ? `JLC synced ${new Date(stock.last_sync).toLocaleString()}`
              : "JLC never synced"}
          </span>
          <button className="btn btn-primary" disabled={syncing} onClick={doSync}>
            {syncing ? "Syncing from JLCPCB…" : "Sync from JLCPCB"}
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

        {stock === null && !error ? <Spinner label="Loading parts stock" /> : null}

        {stock && t ? (
          <>
            <div className="card pad">
              <h2 className="card-title">The money in parts</h2>
              <p className="card-subtitle">
                The cost pool: what was paid for components, what runs have drawn from it, and what
                the unconsumed remainder cost — next to what that same remainder is worth today.
                All USD, because the pool's moving average is USD-denominated.
              </p>
              <div className="counts counts-sm">
                <div className="count-tile">
                  <div className="v">{usd(t.spent_usd)}</div>
                  <div className="muted">spent on parts</div>
                </div>
                <div className="count-tile">
                  <div className="v">{usd(t.drawn_usd)}</div>
                  <div className="muted">drawn by runs</div>
                </div>
                <div className="count-tile">
                  <div className="v">{usd(t.remaining_at_cost_usd)}</div>
                  <div className="muted">remainder at cost</div>
                </div>
                <div className="count-tile">
                  <div className="v">{usd(t.comparable_market_usd)}</div>
                  <div className="muted">same remainder at market</div>
                </div>
                <div className="count-tile">
                  <div className={unrealised != null && unrealised < 0 ? "v err-text" : "v"}>
                    {unrealised != null ? `${unrealised >= 0 ? "+" : ""}${usd(unrealised)}` : "—"}
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
                  — worth {usd(t.missing_invoice_value_usd)} USD at market. Either the invoice is
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
              {(["all", "both", "pool_only", "jlc_only"] as StateFilter[]).map((s) => (
                <button key={s} type="button"
                        className={"btn btn-sm" + (stateFilter === s ? " btn-accent" : "")}
                        onClick={() => setStateFilter(s)}>
                  {s === "all" ? `all ${stock.parts.length}` : `${STATE_LABEL[s]} ${counts[s]}`}
                </button>
              ))}
              <span className="toolbar-total">{rows.length} / {stock.parts.length}</span>
              {anyFilter ? (
                <button type="button" className="row-del clear-filters"
                        onClick={() => { setColFilters({}); setFilter(""); setStateFilter("all"); }}
                        title="Clear filters" aria-label="Clear filters">
                  &#x2715;
                </button>
              ) : null}
            </div>

            <div className="card table-wrap">
              <table className="data data-fixed parts-stock-table">
                <thead>
                  <tr>
                    {sortTh("mpn")}
                    {sortTh("lcsc")}
                    {sortTh("description")}
                    {sortTh("held_qty")}
                    {sortTh("remaining_qty")}
                    {sortTh("delta_qty")}
                    {sortTh("paid_unit_usd")}
                    {sortTh("market_unit_usd")}
                    {sortTh("paid_value_usd")}
                    {sortTh("delta_value_usd")}
                  </tr>
                  <tr className="filter-row">
                    {filterTd("mpn")}
                    {filterTd("lcsc")}
                    {filterTd("description")}
                    {filterTd("held_qty")}
                    {filterTd("remaining_qty")}
                    {filterTd("delta_qty")}
                    {filterTd("paid_unit_usd")}
                    {filterTd("market_unit_usd")}
                    {filterTd("paid_value_usd")}
                    {filterTd("delta_value_usd")}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <Fragment key={r.key}>
                    <tr className="ledger-row"
                        onClick={() => setOpenLedger(openLedger === r.key ? null : r.key)}
                        title="Click for the stock-over-time ledger">
                      <td title={r.mpn + (r.state === "jlc_only"
                        ? " — JLC holds this, no purchase recorded"
                        : r.state === "pool_only" ? " — paid for, JLC does not hold it" : "")}>
                        <span className="ledger-caret">{openLedger === r.key ? "▾" : "▸"}</span>
                        {r.component_id ? (
                          <Link to={`/components/${r.component_id}`} className="mono comp-link"
                                onClick={(e) => e.stopPropagation()}>
                            {r.mpn || r.lcsc || "—"}
                          </Link>
                        ) : (
                          <span className="mono">{r.mpn || r.lcsc || "—"}</span>
                        )}
                        {r.state === "jlc_only" ? (
                          <span className="pill warn">no invoice</span>
                        ) : null}
                      </td>
                      <td className="mono" title={r.lcsc}>{r.lcsc || "—"}</td>
                      <td title={r.description}>{r.description || "—"}</td>
                      <td className="num">{r.state === "pool_only" ? "—" : qty(r.held_qty)}</td>
                      <td className="num" title={`bought ${qty(r.bought)}, drawn ${qty(r.drawn)}`}>
                        {qty(r.remaining_qty)}
                      </td>
                      <td className={"num" + ((r.delta_qty ?? 0) < 0 ? " err-text" : "")}>
                        {r.delta_qty == null ? "—" : qty(r.delta_qty)}
                      </td>
                      <td className="num">{unitPrice(r.paid_unit_usd)}</td>
                      <td className="num">{unitPrice(r.market_unit_usd)}</td>
                      <td className="num">{usd(r.paid_value_usd)}</td>
                      <td className={"num" + ((r.delta_value_usd ?? 0) < 0 ? " err-text" : "")}
                          title={r.remaining_at_market_usd != null
                            ? `remainder at market ${usd(r.remaining_at_market_usd)} USD`
                            : "no market price for this part"}>
                        {r.delta_value_usd == null
                          ? "—"
                          : `${r.delta_value_usd >= 0 ? "+" : ""}${usd(r.delta_value_usd)}`}
                      </td>
                    </tr>
                    {openLedger === r.key ? (
                      <tr>
                        <td colSpan={10} className="ledger-cell">
                          <PartLedgerPanel componentId={r.component_id}
                                           mpn={r.mpn} lcsc={r.lcsc} />
                        </td>
                      </tr>
                    ) : null}
                    </Fragment>
                  ))}
                  {rows.length === 0 ? (
                    <tr><td colSpan={10} className="empty">No parts match.</td></tr>
                  ) : null}
                </tbody>
              </table>
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
