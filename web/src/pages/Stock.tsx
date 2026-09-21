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
  getPartsStock,
  isAbortError,
  syncJlcStock,
  type PartsStock,
  type PartsStockRow,
  type StockAdjustment,
  bookJlcLedgerRows,
  getJlcLedgerReport,
  type JlcLedgerReport,
  getDetectedSubstitutions,
  type SubstitutionDrift,
} from "../api";
import { useDialog } from "../components/Dialog";
import FinishedProductsCard from "../components/FinishedProductsCard";
import DataTable, { type Column } from "../components/DataTable";
import PartLedgerPanel from "../components/PartLedgerPanel";
import { ErrorBanner, Spinner } from "../components/Ui";
import { plain } from "../format";
import { useStickyState } from "../useStickyState";


function qty(v: number | null | undefined): string {
  if (v == null) return "—";
  return Math.round(v).toLocaleString();
}

/** The table asks ONE question — do the two sides agree, and is it worth money.
 *
 *  Everything else a reader eventually wants (bought, drawn, written off, the
 *  two "ours" figures, JLC's own count, both unit prices, the unrealised
 *  difference) is an operand of that question, and lives in the row's fold.
 *  JLC's count in particular is `ours + Δ qty` — printing all three spends a
 *  column on arithmetic the reader can do. Thirteen columns at
 *  `table-layout: fixed` left every one of them too narrow to read, and the
 *  part name — the thing you scan for — narrowest of all.
 *
 *  `width` on each column below is a PERCENT and the seven must sum to 100 —
 *  `DataTable` builds the <colgroup> from them. There is no width for this
 *  table in `styles.css`; a block that looked like one sat there unused for
 *  months.
 */
type ColKey =
  | "mpn" | "lcsc" | "project_count" | "remaining_at_sync_qty"
  | "delta_qty" | "paid_value_usd";

const COL_LABELS: Record<ColKey, string> = {
  mpn: "Part",
  lcsc: "LCSC",
  project_count: "Projects",
  remaining_at_sync_qty: "Ours",
  delta_qty: "Δ qty",
  paid_value_usd: "At cost",
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
  const [adjs, setAdjs] = useState<StockAdjustment[] | null>(null);
  const [adjTotals, setAdjTotals] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [filter, setFilter] = useStickyState("stock:filter", "");
  // "all" is the default: the page is read to look a part up at least as often
  // as to chase a disagreement, and once the two sides agree the "disagree"
  // default opened on an empty table.
  const [stateFilter, setStateFilter] = useStickyState<StateFilter>("stock:state", "all");
  const [showAdjs, setShowAdjs] = useState(false);
  const [adjBusy, setAdjBusy] = useState<number | null>(null);
  // stock-over-time drill-down: which row's ledger is open (not sticky — a
  // reload should come back to the overview, not a stale expansion)
  const [openLedger, setOpenLedger] = useState<string | null>(null);
  // what JLC's own movement ledger and our events cannot say about each other
  const [recon, setRecon] = useState<JlcLedgerReport | null>(null);
  const [booking, setBooking] = useState(false);
  // substitutions whose design has not caught up — the reason a superseded part
  // gets bought again
  const [drift, setDrift] = useState<SubstitutionDrift[]>([]);

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
    getAllStockAdjustments("", signal)
      .then((a) => {
        setAdjs(a.adjustments);
        setAdjTotals(a.totals as unknown as Record<string, unknown>);
      })
      .catch(() => setAdjs(null));
    getJlcLedgerReport(signal).then(setRecon).catch(() => setRecon(null));
    getDetectedSubstitutions(signal).then((d) => setDrift(d.drift)).catch(() => setDrift([]));
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
        const led = r.ledger && "rows_added" in r.ledger ? r.ledger : null;
        setSyncMsg(
          `Synced ${r.items} part(s), ${r.valued} valued.` +
            (led
              ? ` JLC's ledger: ${led.rows_added} new movement(s) across ${led.parts} part(s)` +
                (led.does_not_replay.length
                  ? `; ${led.does_not_replay.join(", ")} did not replay to JLC's own balance`
                  : "")
              : ""),
        );
        load();
      })
      .catch((err) => {
        setSyncing(false);
        setError(errorMessage(err));
      });
  };

  async function bookLedgerRows() {
    if (!recon || recon.bookable.length === 0) return;
    const lines = recon.bookable
      .map((b) => `  ${b.date}  ${b.qty} × ${b.mpn || b.lcsc}  — ${b.remark}`)
      .join("\n");
    const ok = await dialog.confirm(
      `JLCPCB recorded ${recon.bookable.length} movement(s) that no invoice or BOM ` +
        `reports:\n\n${lines}\n\nRecord each as a draw charged to no batch, priced ` +
        `at the pool's average on JLC's own date? Nothing is estimated — the ` +
        `quantity, the date and the note are JLC's.`,
      { title: "Record JLC's movements", confirmLabel: "Record" },
    );
    if (!ok) return;
    setBooking(true);
    try {
      const res = await bookJlcLedgerRows([], false);
      setSyncMsg(
        `Recorded ${res.totals.rows} movement(s), ${res.totals.qty} piece(s), ` +
          `${plain(res.totals.usd)}. Reversible as batch ${res.batch_id}.`,
      );
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBooking(false);
    }
  }

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

  const anyFilter = filter.trim() !== "" || stateFilter !== "all";

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
      width: 30,
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
    { key: "lcsc", label: COL_LABELS.lcsc, width: 10, className: "mono", get: (r) => r.lcsc || "—" },
    {
      key: "project_count",
      label: COL_LABELS.project_count,
      width: 26,
      // Sorted and filtered on the NAMES, so "show me everything on the dongle"
      // still works from the table; the cell shows them as chips because a
      // count alone makes the reader open every row to find out which.
      get: (r) => [...new Set(r.projects.map((p) => p.project_name))].join(", "),
      title: (r) =>
        r.project_count === 0
          ? "no project's latest snapshot lists this part"
          : `${r.qty_per_device} per device` +
            (r.devices_coverable == null ? "" : ` · stock covers ${r.devices_coverable}`),
      render: (r) => <ProjectChips r={r} />,
    },
    {
      key: "remaining_at_sync_qty",
      label: COL_LABELS.remaining_at_sync_qty,
      width: 11,
      numeric: true,
      // What we hold. For a CONSIGNED part that is the pool as it stood when JLC
      // counted, because that is the only figure Δ qty is about; for a part JLC
      // never sees there is nothing to compare against, so it is today's. The
      // column used to show "—" for those, which reported the enclosures as
      // having no stock at all when the shelf held 227.
      get: (r) => (r.state === "pool_only" ? r.remaining_qty : r.remaining_at_sync_qty),
      title: (r) =>
        r.state === "pool_only"
          ? "our pool today — JLC does not hold this part, so there is nothing to compare"
          : `our pool on the day JLC counted; today it is ${qty(r.remaining_qty)}`,
      render: (r) => <>{qty(r.state === "pool_only" ? r.remaining_qty : r.remaining_at_sync_qty)}</>,
    },
    numCol("delta_qty", 11, (r) => <DeltaCell r={r} />),
    numCol("paid_value_usd", 12, (r) => <>{plain(r.paid_value_usd)}</>),
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

        {/* FINISHED DEVICES FIRST. "Stock" is asked as "how many dongles can we
            sell" far more often than "does the component account close", and
            the component account is the rest of this page. It owns its own
            fetch, so a slow or failing parts sync never hides it. */}
        <FinishedProductsCard />

        {stock && stock.totals.events_since_sync > 0 ? (
          <div className="banner-warn">
            Every quantity below is compared as of{" "}
            <b>{stock.totals.compared_as_of}</b>, the day JLC counted.{" "}
            {stock.totals.events_since_sync} stock event
            {stock.totals.events_since_sync === 1 ? " has" : "s have"} been recorded
            since, so <b>Ours</b> and <b>Δ qty</b> are measuring different moments —
            Δ is the disagreement, Ours is today. Sync the count to close the gap.
          </div>
        ) : null}

        {recon &&
        (recon.totals.unexplained_rows > 0 || recon.totals.unconfirmed_lines > 0) ? (
          <div className="banner-warn">
            <b>JLCPCB&rsquo;s own ledger disagrees with ours.</b>{" "}
            {recon.totals.unexplained_rows > 0 ? (
              <>
                {recon.totals.unexplained_rows} movement
                {recon.totals.unexplained_rows === 1 ? "" : "s"} JLC recorded that no
                document of ours reports.{" "}
              </>
            ) : null}
            {recon.totals.unconfirmed_lines > 0 ? (
              <>
                {recon.totals.unconfirmed_qty.toLocaleString()} piece
                {recon.totals.unconfirmed_qty === 1 ? "" : "s"} we booked as bought that
                JLC never received — refresh that parts order to take their correction.{" "}
              </>
            ) : null}
            <ul className="tight">
              {recon.jlc_rows_we_cannot_explain.slice(0, 8).map((r) => (
                <li key={`${r.lcsc}:${r.changed_at}:${r.change_qty}`}>
                  <span className="mono">{r.changed_at.slice(0, 10)}</span>{" "}
                  {r.change_qty > 0 ? "+" : ""}
                  {r.change_qty} × {r.mpn || r.lcsc} — {r.remark}
                </li>
              ))}
              {recon.our_lines_jlc_never_received.map((r) => (
                <li key={`${r.lcsc}:${r.parts_order}`}>
                  <span className="mono">{r.parts_order}</span> — we hold{" "}
                  {r.booked_qty.toLocaleString()} of {r.lcsc}, JLC received{" "}
                  {r.ledger_receipt_qty.toLocaleString()}
                </li>
              ))}
            </ul>
            {recon.bookable.length > 0 ? (
              <button className="btn" disabled={booking} onClick={bookLedgerRows}
                      title="Write each as a draw charged to no batch, using JLC's quantity, date and wording.">
                {booking ? "Recording…" : `Record ${recon.bookable.length} movement(s) JLC reports`}
              </button>
            ) : null}
          </div>
        ) : null}

        {drift.length > 0 ? (
          <div className="banner-warn">
            <b>A batch was built with a different part, and the design has not caught up.</b>{" "}
            Buying against the design will order the superseded part again — which is how 476
            pieces of one were bought three months after it stopped being fitted.
            <ul className="tight">
              {drift.map((d) => (
                <li key={d.substitution_id}>
                  <Link to={`/runs/${d.run_id}`}>{d.run_label}</Link> fitted{" "}
                  <span className="mono">{d.fitted_lcsc || d.fitted_mpn}</span> at{" "}
                  <span className="mono">{d.designator}</span>, the design still specifies{" "}
                  <span className="mono">{d.specified_lcsc || d.specified_mpn}</span>
                  {d.specified_still_held > 0 ? (
                    <> — <b>{d.specified_still_held.toLocaleString()}</b> still held at JLC</>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

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
                  <PartLedgerPanel row={r} />
                )}
                empty={
                  stateFilter === "disagree"
                    ? "Every part JLC holds agrees with the platform, piece for piece."
                    : "No parts match."
                }
              />
            </div>

          </>
        ) : null}
      </div>
    </div>
  );
}

/** The projects that use a part, as chips rather than a count.
 *
 *  A count alone ("3") makes the reader open every row to learn which three,
 *  which is the work the column exists to save. Chips fit because a part is
 *  rarely on more than three projects; beyond that the rest collapse into a
 *  "+n" the title spells out.
 */
function ProjectChips({ r }: { r: PartsStockRow }) {
  const names = [...new Set(r.projects.map((p) => p.project_name))];
  if (names.length === 0) return <span className="dim">—</span>;
  const SHOWN = 2;
  return (
    <span className="proj-chips">
      {names.slice(0, SHOWN).map((n) => (
        <span key={n} className="pill neutral">{n}</span>
      ))}
      {names.length > SHOWN ? (
        <span className="pill" title={names.join(", ")}>+{names.length - SHOWN}</span>
      ) : null}
    </span>
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
  const honest = r.bought - r.drawn;
  const honestAgrees =
    r.state === "both" && r.lost > 0 && Math.abs(honest - r.held_qty) < 0.5;
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
