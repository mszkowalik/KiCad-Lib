/** Stock → Finished devices: the shelf, in its two cuts on one page.
 *
 *  Per PRODUCT it counts the device records (`GET /api/finished-products`). Per
 *  BATCH it counts per run (`GET /api/finished-stock`). Neither re-derives the
 *  other, and the difference is load-bearing: a device that names no batch is
 *  invisible to every per-batch figure, and both cards say so in a banner.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getFinishedStock,
  isAbortError,
  type FinishedStock,
  type FinishedStockRow,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import FinishedProductsCard from "../components/FinishedProductsCard";
import FoldSection, { StatChip } from "../components/FoldSection";
import { ErrorBanner, Spinner } from "../components/Ui";
import { plnAmount } from "../format";

/** More devices passed programming than the batch is recorded to hold. The one
 *  arithmetic in the card that is impossible rather than merely unlucky: the run
 *  quantity is wrong, or devices were filed under the wrong batch. Under-building
 *  is normal attrition and is not flagged. */
function overbuilt(r: FinishedStockRow): boolean {
  return r.devices_produced > 0 && r.qty_recorded > 0 && r.built > r.qty_recorded;
}

/* Was a hand-rolled `<table className="data">` — the same header font as the
   DataTables around it, but no sort control and no filter row, so it read as a
   different kind of table (reported 2026-09-12). Every `title` the hand-rolled
   version carried is kept: they are the only place the arithmetic is
   explained. */
const shelfCols: Column<FinishedStockRow>[] = [
  { key: "project", label: "Project", width: 12, get: (r) => r.project },
  {
    key: "label",
    label: "Batch",
    // 21, so the nine widths sum to 100. `Prototypes 1 — PROFORMA 1/11/2023`
    // still clips by ~20px and keeps its full text in the cell title: the
    // remaining width is in eight columns of figures, which is what this card
    // is for, and none of them has room to give.
    width: 18,
    get: (r) => r.label,
    render: (r) => (
      <Link className="comp-link" to={`/production/batches/${r.run_id}`} onClick={(e) => e.stopPropagation()}>
        {r.label}
      </Link>
    ),
  },
  // The batch's own date, so the shelf reads newest batch first like every
  // other batch list. It was sorted by whatever order the API returned.
  { key: "date", label: "Date", width: 10, className: "mono", get: (r) => r.run_date || "—" },
  {
    key: "recorded",
    label: "Recorded",
    width: 9,
    numeric: true,
    get: (r) => r.qty_recorded,
    title: () => "the quantity on the production run — boards ordered or assembled",
    render: (r) => (
      <span className={overbuilt(r) ? "err-text" : undefined}>{r.qty_recorded.toLocaleString()}</span>
    ),
  },
  {
    key: "built",
    label: "Built",
    width: 9,
    numeric: true,
    get: (r) => r.built,
    title: (r) =>
      overbuilt(r)
        ? `${r.built} devices passed programming but the batch is recorded as ${r.qty_recorded} boards — the run quantity is wrong, or devices from another batch were filed here`
        : r.devices_produced
          ? `${r.built} devices passed programming; ${r.qty_recorded - r.built} of the recorded boards never did`
          : "no device records on this batch — record them, as placeholders if the units were never serialised",
    render: (r) => (
      <span className={overbuilt(r) ? "err-text" : undefined}>{r.built.toLocaleString()}</span>
    ),
  },
  {
    key: "shipped",
    label: "Shipped",
    width: 9,
    numeric: true,
    get: (r) => r.devices_shipped,
    render: (r) => <>{r.devices_shipped.toLocaleString()}</>,
  },
  {
    key: "in_stock",
    label: "In stock",
    width: 9,
    numeric: true,
    get: (r) => r.devices_in_stock,
    render: (r) => <>{r.devices_in_stock.toLocaleString()}</>,
  },
  {
    key: "unit_cost",
    label: "Unit cost",
    width: 12,
    numeric: true,
    get: (r) => r.unit_cost_pln ?? "",
    render: (r) =>
      r.unit_cost_pln == null ? <span className="muted">—</span> : <>{plnAmount(r.unit_cost_pln)}</>,
  },
  {
    key: "value",
    label: "Value",
    width: 12,
    numeric: true,
    get: (r) => r.stock_value_pln ?? "",
    render: (r) =>
      r.devices_in_stock ? <>{plnAmount(r.stock_value_pln, 0)}</> : <span className="muted">—</span>,
  },
];


/** Finished devices per batch.
 *
 *  Every batch that was actually built gets a row, empty or not. Filtering by
 *  what is LEFT deleted a batch from the card the moment its last device
 *  shipped — six of seven dongle batches vanished the day `built` started
 *  counting passed devices instead of the typed quantity (2026-09-10). A batch
 *  is a fact; its remaining stock is a number on it. Planned batches hold
 *  nothing yet and stay out. */
function ShelfByBatchCard({ stock }: { stock: FinishedStock | null }) {
  const rows = useMemo(
    () => (stock ? stock.runs.filter((r) => (r.status || "").trim().toLowerCase() !== "planned") : []),
    [stock],
  );
  return (
    <FoldSection
      title="Devices on the shelf, by batch"
      count={rows.length}
      foldKey="stock:shelf-by-batch"
      chips={stock ? (
        <>
          {rows.some(overbuilt) ? <StatChip n={rows.filter(overbuilt).length} tone="err">built above recorded</StatChip> : null}
          {stock.totals.no_batch ? <StatChip n={stock.totals.no_batch} tone="warn">name no batch</StatChip> : null}
          <StatChip n={stock.totals.stock.toLocaleString()}>on the shelf</StatChip>
          {stock.totals.stock_value_pln != null ? <StatChip n={plnAmount(stock.totals.stock_value_pln, 0)}>at cost</StatChip> : null}
        </>
      ) : undefined}
    >
      <p className="muted dim">
        Recorded is the quantity on the production run — boards ordered or assembled. Built
        counts the devices that passed, so it is normally the smaller of the two; built
        above recorded is impossible and is marked in red. Every batch stays listed after
        its last device ships. The shelf by PRODUCT, and what is sellable, is the card above.
      </p>
      {stock?.totals.no_batch ? (
        <div className="banner-warn">
          <b>{stock.totals.no_batch} device(s) on the shelf name no batch</b>, so no row
          below holds them and this card&rsquo;s total is that many short of what we
          actually have. The card above counts them.
        </div>
      ) : null}
      {!stock ? (
        <Spinner label="Counting…" />
      ) : rows.length === 0 ? (
        <p className="muted">Nothing on the shelf.</p>
      ) : (
        <div className="table-wrap">
          <DataTable
            columns={shelfCols}
            rows={rows}
            rowKey={(r) => r.run_id}
            defaultSort={{ key: "date", dir: "desc" }}
            persistKey="finished-stock"
            empty="No batch has been built yet."
          />
        </div>
      )}
    </FoldSection>
  );
}

export default function FinishedDevices() {
  const [stock, setStock] = useState<FinishedStock | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    getFinishedStock(undefined, ac.signal)
      .then(setStock)
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    return () => ac.abort();
  }, []);
  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Finished devices</h1>
          <span className="toolbar-total">What we hold, per product and per batch.</span>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        <FinishedProductsCard />
        <ShelfByBatchCard stock={stock} />
      </div>
    </div>
  );
}
