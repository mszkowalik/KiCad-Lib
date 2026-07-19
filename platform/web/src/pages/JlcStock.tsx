/** Private JLCPCB parts library: components JLC holds on consignment —
 *  quantities, valuation at current LCSC pricing, and where each held part
 *  is used across tracked projects. */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getJlcStock,
  getJlcStockUsage,
  isAbortError,
  syncJlcStock,
  type JlcStock,
  type JlcStockRow,
  type JlcUsageRow,
} from "../api";
import { ErrorBanner, Spinner } from "../components/Ui";
import { useStickyState } from "../useStickyState";

function money(v: number | null, currency: string): string {
  if (v == null) return "—";
  return `${v.toLocaleString(undefined, { maximumFractionDigits: v < 1 ? 4 : 2 })} ${currency}`;
}

// ------------------------------------------- client-side sort/filter (as Browse)

type ColKey = "manufacturer" | "mpn" | "lcsc" | "description" | "qty" | "value";

const COL_LABELS: Record<ColKey, string> = {
  manufacturer: "Mfg",
  mpn: "Mfg PN",
  lcsc: "LCSC",
  description: "Description",
  qty: "Held qty",
  value: "Value",
};

function colValue(i: JlcStockRow, col: ColKey): string {
  if (col === "qty") return String(i.qty);
  if (col === "value") return i.value != null ? String(i.value) : "";
  return i[col];
}

function sortRows(
  rows: JlcStockRow[],
  sort: { col: ColKey; dir: "asc" | "desc" },
): JlcStockRow[] {
  const mul = sort.dir === "asc" ? 1 : -1;
  const out = [...rows];
  if (sort.col === "qty" || sort.col === "value") {
    // numeric; missing values always last regardless of direction
    const num = (r: JlcStockRow) => (sort.col === "qty" ? r.qty : r.value);
    out.sort((a, b) => {
      const av = num(a);
      const bv = num(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * mul;
    });
  } else {
    const col = sort.col;
    out.sort(
      (a, b) => colValue(a, col).toLowerCase().localeCompare(colValue(b, col).toLowerCase()) * mul,
    );
  }
  return out;
}

export default function JlcStock() {
  const [stock, setStock] = useState<JlcStock | null>(null);
  const [usage, setUsage] = useState<JlcUsageRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [currency, setCurrency] = useStickyState("jlc:currency", "");
  const [filter, setFilter] = useStickyState("jlc:filter", "");

  const load = (signal?: AbortSignal, cur?: string) => {
    getJlcStock(cur || undefined, signal)
      .then((s) => {
        setStock(s);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getJlcStockUsage(signal)
      .then(setUsage)
      .catch(() => setUsage(null));
  };

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal, currency);
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currency]);

  const doSync = () => {
    setSyncing(true);
    setSyncMsg(null);
    syncJlcStock()
      .then((r) => {
        setSyncing(false);
        setSyncMsg(`Synced ${r.items} part(s), ${r.valued} valued.`);
        load(undefined, currency);
      })
      .catch((err) => {
        setSyncing(false);
        setError(errorMessage(err));
      });
  };

  // Column sort + per-column filters — client-side, remembered across navigation.
  const [sort, setSort] = useStickyState<{ col: ColKey; dir: "asc" | "desc" } | null>(
    "jlc:sort",
    null,
  );
  const [colFilters, setColFilters] = useStickyState<Partial<Record<ColKey, string>>>(
    "jlc:colFilters",
    {},
  );

  const anyFilter =
    filter.trim() !== "" ||
    Object.values(colFilters).some((v) => v !== undefined && v.trim() !== "");

  const items = useMemo(() => {
    let rows = stock?.items ?? [];
    const needle = filter.trim().toLowerCase();
    if (needle) {
      rows = rows.filter(
        (i) =>
          i.lcsc.toLowerCase().includes(needle) ||
          i.description.toLowerCase().includes(needle) ||
          i.mpn.toLowerCase().includes(needle) ||
          i.manufacturer.toLowerCase().includes(needle) ||
          (i.component_name ?? "").toLowerCase().includes(needle),
      );
    }
    const active = (Object.entries(colFilters) as Array<[ColKey, string]>).filter(
      ([, v]) => v.trim() !== "",
    );
    if (active.length > 0) {
      rows = rows.filter((i) =>
        active.every(([col, v]) =>
          colValue(i, col).toLowerCase().includes(v.trim().toLowerCase()),
        ),
      );
    }
    if (sort !== null) rows = sortRows(rows, sort);
    return rows;
  }, [stock, filter, colFilters, sort]);

  const cycleSort = (col: ColKey) =>
    setSort((prev) =>
      prev === null || prev.col !== col
        ? { col, dir: "asc" }
        : prev.dir === "asc"
          ? { col, dir: "desc" }
          : null,
    );

  const setColFilter = (col: ColKey, v: string) => setColFilters((f) => ({ ...f, [col]: v }));

  const colLabel = (col: ColKey) =>
    col === "value" ? `Value (${stock?.currency ?? "USD"})` : COL_LABELS[col];

  const sortTh = (col: ColKey, className?: string) => (
    <th className={className}>
      <button
        type="button"
        className="th-sort"
        onClick={() => cycleSort(col)}
        title={`Sort by ${colLabel(col)}`}
      >
        {colLabel(col)}
        {sort?.col === col ? (
          <span className="sort-ind">{sort.dir === "asc" ? "▲" : "▼"}</span>
        ) : null}
      </button>
    </th>
  );

  const filterTd = (col: ColKey) => (
    <td>
      <input
        type="text"
        className="text filter-input"
        placeholder="filter…"
        value={colFilters[col] ?? ""}
        onChange={(e) => setColFilter(col, e.target.value)}
        aria-label={`Filter ${colLabel(col)}`}
      />
    </td>
  );

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>JLC private stock</h1>
          <span className="toolbar-total">
            {stock?.last_sync
              ? `last sync ${new Date(stock.last_sync).toLocaleString()}`
              : "never synced"}
          </span>
          <label className="proj-inline-field">
            Currency
            <input
              className="text num-input"
              value={currency}
              placeholder={stock?.currency ?? "USD"}
              maxLength={3}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            />
          </label>
          <button className="btn btn-primary" disabled={syncing} onClick={doSync}>
            {syncing ? "Syncing from JLCPCB…" : "Sync from JLCPCB"}
          </button>
        </div>

        {error ? <ErrorBanner message={error} /> : null}
        {syncMsg ? <div className="banner-ok">{syncMsg}</div> : null}

        {stock && !stock.available ? (
          <div className="banner-warn">
            JLCPCB API credentials are not configured. Apply for API access at{" "}
            <a href="https://api.jlcpcb.com" target="_blank" rel="noreferrer">
              api.jlcpcb.com
            </a>
            , create an app, then set <span className="mono">JLC_APP_ID</span>,{" "}
            <span className="mono">JLC_ACCESS_KEY</span> and{" "}
            <span className="mono">JLC_SECRET_KEY</span> in <span className="mono">platform/.env</span>{" "}
            and restart the api service.
          </div>
        ) : null}

        {stock === null && !error ? <Spinner label="Loading stock" /> : null}

        {stock ? (
          <>
            <div className="counts counts-sm">
              <div className="count-tile">
                <div className="v">{stock.totals.parts}</div>
                <div className="muted">distinct parts held</div>
              </div>
              <div className="count-tile">
                <div className="v">{stock.totals.quantity.toLocaleString()}</div>
                <div className="muted">total pieces</div>
              </div>
              <div className="count-tile">
                <div className="v">{money(stock.totals.value, stock.currency)}</div>
                <div className="muted">value at current LCSC pricing</div>
              </div>
              <div className="count-tile">
                <div className="v">{money(stock.totals.value_usd, "USD")}</div>
                <div className="muted">value (USD)</div>
              </div>
            </div>
            {stock.totals.unvalued_parts > 0 ? (
              <div className="banner-warn">
                {stock.totals.unvalued_parts} part(s) have no LCSC price — their value counts
                as 0.
              </div>
            ) : null}

            {stock.items.length > 0 ? (
              <div className="toolbar">
                <input
                  className="text search"
                  placeholder="Filter by LCSC / description / MPN / component…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
                <span className="toolbar-total">
                  {items.length} / {stock.items.length}
                </span>
                {anyFilter ? (
                  <button
                    type="button"
                    className="row-del clear-filters"
                    onClick={() => {
                      setColFilters({});
                      setFilter("");
                    }}
                    title="Clear filters"
                    aria-label="Clear filters"
                  >
                    &#x2715;
                  </button>
                ) : null}
              </div>
            ) : null}

            {stock.items.length === 0 ? (
              <div className="card pad">
                <p className="muted">
                  No parts cached yet.{" "}
                  {stock.available
                    ? "Press “Sync from JLCPCB” to fetch your private parts library."
                    : "Configure the API credentials, then sync."}
                </p>
              </div>
            ) : (
              <div className="card table-wrap">
                <table className="data jlc-stock-table">
                  <thead>
                    <tr>
                      {sortTh("manufacturer")}
                      {sortTh("mpn")}
                      {sortTh("lcsc")}
                      {sortTh("description")}
                      {sortTh("qty", "num")}
                      {sortTh("value", "num")}
                    </tr>
                    <tr className="filter-row">
                      {filterTd("manufacturer")}
                      {filterTd("mpn")}
                      {filterTd("lcsc")}
                      {filterTd("description")}
                      {filterTd("qty")}
                      {filterTd("value")}
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((i) => (
                      <tr key={i.id}>
                        <td title={i.manufacturer}>{i.manufacturer || "—"}</td>
                        <td title={i.mpn}>
                          {i.component_id ? (
                            <Link to={`/components/${i.component_id}`} className="mono comp-link">
                              {i.mpn || "—"}
                            </Link>
                          ) : (
                            <span className="mono">{i.mpn || "—"}</span>
                          )}
                        </td>
                        <td className="mono" title={i.lcsc}>
                          {i.lcsc || "—"}
                        </td>
                        <td title={i.description}>{i.description}</td>
                        <td className="num">{i.qty.toLocaleString()}</td>
                        <td className="num">{money(i.value, stock.currency)}</td>
                      </tr>
                    ))}
                    {items.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="empty">
                          No parts match.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            )}

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
