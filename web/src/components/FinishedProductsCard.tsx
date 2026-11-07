/** Finished devices we hold, one row per PRODUCT.
 *
 *  "Devices on the shelf, by batch", on the same page, is that shelf cut by BATCH —
 *  "which batch still holds units". This is the cut a person asks for first:
 *  "how many dongles can we sell".
 *
 *  It reads `GET /api/finished-products`, which counts the DEVICE RECORDS, not
 *  `finished-stock`, which counts per batch. The difference is not academic: a
 *  device that names no batch is invisible to every per-batch figure, and 13 of
 *  them were on the real shelf when this was written — the platform reported 93
 *  devices while holding 106. Such a device is stock and is NOT costed, because
 *  per-device cost belongs to a batch, so it is counted in `no_batch` rather
 *  than quietly averaged in. `no_batch` counts every state, shipped and missing
 *  too, so this card and the next one reconcile: 51 CE_Dongle_V2 devices named
 *  no batch (2026-11-07), and this card read 40 more shipped and 11 more
 *  missing than the next one with nothing to say why.
 *
 *  A row opens into its CONDITIONS, because "in stock" and "sellable" are not
 *  the same number and the difference is the point: a prototype is present,
 *  counted and worth something, and may never leave (decision 0032). Each
 *  condition links to that project's Devices tab, scoped to exactly the devices
 *  the number counted, so the answer to "which ones?" is one click and arrives
 *  as serials.
 */
import { useMemo } from "react";
import { Link } from "react-router-dom";

import {
  getProductStock,
  type ProductStockRow,
} from "../api";
import { plnAmount } from "../format";
import DataTable, { type Column } from "./DataTable";
import FoldSection, { StatChip } from "./FoldSection";
import { ErrorBanner, Spinner } from "./Ui";
import { useLoad } from "./useLoad";

export const CONDITION_WORD: Record<string, string> = {
  ok: "sellable",
  faulty: "faulty",
  prototype: "prototype",
  unidentified: "unidentified",
  incomplete: "incomplete",
};

const STATE_WORD: Record<string, string> = {
  in_stock: "on the shelf",
  allocated: "reserved",
  shipped: "shipped",
  missing: "missing",
  returned: "returned",
  disposed: "disposed",
};

/** "3 on the shelf, 40 shipped, 11 missing" — the devices that name no batch, by state. */
export function noBatchWords(states: Record<string, number>): string {
  return Object.entries(states)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([state, n]) => `${n.toLocaleString()} ${STATE_WORD[state] ?? (state || "with no state")}`)
    .join(", ");
}

const CONDITION_WHY: Record<string, string> = {
  ok: "On the shelf and may ship. This is the only condition a shipment can draw.",
  faulty: "Present and ours, and it cannot be sold until it is repaired.",
  prototype: "Built to try something. It is counted and it never leaves (decision 0032).",
  unidentified: "On the shelf with nothing saying what it is — worth looking at.",
  incomplete: "Programmed and working, and missing parts to finish — an enclosure, an antenna. It cannot ship until it is completed.",
};

/** `/projects/:id?tab=Devices&state=in_stock&condition=…` — the exact devices
 *  the number counted, as serials. */
function devicesHref(projectId: number, condition: string): string {
  return `/projects/${projectId}?tab=Devices&state=in_stock`
    + `&condition=${encodeURIComponent(condition)}`;
}

export default function FinishedProductsCard() {
  const { data: stock, error } = useLoad(
    (signal) =>
      // A product that never built anything is noise; one whose every unit
      // has shipped is still a fact worth printing.
      getProductStock(signal).then((s) => s.products.filter((p) => p.in_stock > 0 || p.shipped > 0)),
    [],
  );

  const rows = useMemo(() => stock ?? [], [stock]);
  const totals = useMemo(() => ({
    in_stock: rows.reduce((n, r) => n + r.in_stock, 0),
    available: rows.reduce((n, r) => n + r.available, 0),
    value: rows.reduce((n, r) => n + (r.value_pln ?? 0), 0),
    no_batch: rows.reduce((n, r) => n + r.no_batch, 0),
    no_batch_states: rows.reduce<Record<string, number>>((acc, r) => {
      for (const [state, n] of Object.entries(r.no_batch_states ?? {})) acc[state] = (acc[state] ?? 0) + n;
      return acc;
    }, {}),
    missing: rows.reduce((n, r) => n + r.missing, 0),
  }), [rows]);

  const cols: Column<ProductStockRow>[] = [
    {
      key: "project",
      label: "Product",
      width: 20,
      get: (r) => r.project,
      render: (r) => (
        <Link className="comp-link" to={`/projects/${r.project_id}?tab=Devices`}
              onClick={(e) => e.stopPropagation()}>
          {r.project}
        </Link>
      ),
    },
    {
      key: "in_stock",
      label: "On the shelf",
      width: 14,
      numeric: true,
      get: (r) => r.in_stock,
      title: () => "every device we hold, whatever condition it is in",
    },
    {
      key: "available",
      label: "Sellable",
      width: 12,
      numeric: true,
      get: (r) => r.available,
      title: () => "condition `ok` — the only devices a shipment may draw",
    },
    {
      key: "held",
      label: "Held back",
      width: 14,
      numeric: true,
      get: (r) => r.in_stock - r.available,
      title: (r) =>
        Object.entries(r.held).map(([c, n]) => `${n} ${CONDITION_WORD[c] ?? c}`).join(" · ")
        || "nothing held back",
      render: (r) => {
        const held = r.in_stock - r.available;
        return held ? <span className="pill warn">{held.toLocaleString()}</span> : <span className="muted">—</span>;
      },
    },
    { key: "shipped", label: "Shipped", width: 10, numeric: true, get: (r) => r.shipped },
    {
      // Off the shelf with no known location (decision 0057). Counted in no
      // stock figure above, so it is shown here or nowhere.
      key: "missing",
      label: "Missing",
      width: 10,
      numeric: true,
      interactive: false,
      get: (r) => r.missing,
      title: () => "not found at a stock count — in no stock figure; ship one from its order once it is located",
      render: (r) =>
        r.missing ? (
          <Link className="val-link" to={`/projects/${r.project_id}?tab=Devices&state=missing`}
                onClick={(e) => e.stopPropagation()}>
            {r.missing.toLocaleString()}
          </Link>
        ) : (
          <span className="muted">—</span>
        ),
    },
    { key: "batches", label: "Batches", width: 8, numeric: true, get: (r) => r.batches },
    {
      key: "value",
      label: "Value at cost",
      width: 12,
      numeric: true,
      get: (r) => r.value_pln ?? 0,
      title: (r) => "what the shelf cost to make: a unit with a twin at its twin's price, any other "
        + "at its batch's own per-device actual"
        + (r.uncosted
          ? `. ${r.uncosted} device(s) on the shelf have no price: no batch, or a gap of a crafted batch`
          : ""),
      render: (r) => <>{plnAmount(r.value_pln ?? 0, 0)}</>,
    },
  ];

  return (
    <FoldSection
      title="Finished devices we hold"
      count={rows.length}
      foldKey="stock:finished-products"
      chips={stock ? (
        <>
          {totals.missing ? <StatChip n={totals.missing.toLocaleString()} tone="warn">missing</StatChip> : null}
          {totals.no_batch ? <StatChip n={totals.no_batch.toLocaleString()} tone="warn">name no batch</StatChip> : null}
          <StatChip n={totals.in_stock.toLocaleString()}>on the shelf</StatChip>
          <StatChip n={totals.available.toLocaleString()} tone="ok">sellable</StatChip>
          {totals.missing && totals.no_batch ? null : <StatChip n={plnAmount(totals.value, 0)}>at cost</StatChip>}
        </>
      ) : undefined}
    >
      <p className="card-subtitle">One row per product, open it for the conditions</p>
      <p className="muted dim">
        Only condition <code>ok</code> may ship, so a faulty or prototype unit is counted
        and visible here and can never leave. Open a row to see why, and click a condition
        to list those exact serials. The next card shows the same devices cut by batch, except
        the devices that name no batch.
      </p>
      {totals.no_batch ? (
        // A device that names no batch is real stock and nothing values it —
        // and every per-batch figure in the platform is blind to it, which is
        // why it is said here rather than left to be discovered.
        <div className="banner-warn">
          <b>{totals.no_batch} device(s) name no batch</b>: {noBatchWords(totals.no_batch_states)}.
          They are counted here and in no per-batch figure, so the next card is that many short.
          Those on the shelf have no value, because per-device cost belongs to a batch. Link each
          one to the batch that made it from its own page.
        </div>
      ) : null}
      {error ? <ErrorBanner message={error} /> : null}
      {!stock ? (
        <Spinner label="Counting the shelf…" />
      ) : (
        <div className="table-wrap">
          <DataTable
            columns={cols}
            rows={rows}
            rowKey={(r) => r.project_id}
            persistKey="finished-products"
            defaultSort={{ key: "in_stock", dir: "desc" }}
            expand={(r) => <ConditionBreakdown row={r} />}
            empty="No finished devices are recorded yet."
          />
        </div>
      )}
    </FoldSection>
  );
}

/** The conditions behind one product's shelf count. */
function ConditionBreakdown({ row }: { row: ProductStockRow }) {
  const parts: { cond: string; n: number }[] = [
    ...(row.available ? [{ cond: "ok", n: row.available }] : []),
    ...Object.entries(row.held)
      .filter(([, n]) => n > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([cond, n]) => ({ cond, n })),
  ];
  if (!parts.length) {
    return <p className="muted">Nothing on the shelf for {row.project} — every device has shipped.</p>;
  }
  return (
    <DataTable
      rows={parts}
      rowKey={(p) => p.cond}
      columns={[
        { key: "cond", label: "Condition", width: 16, get: (p) => CONDITION_WORD[p.cond] ?? p.cond,
          render: (p) => <span className={`pill ${p.cond === "ok" ? "ok" : "warn"}`}>{CONDITION_WORD[p.cond] ?? p.cond}</span> },
        { key: "n", label: "Devices", width: 10, numeric: true, get: (p) => p.n },
        { key: "why", label: "What it means", width: 54, className: "muted",
          get: (p) => CONDITION_WHY[p.cond] ?? "No rule recorded for this condition." },
        { key: "act", label: "", width: 20, interactive: false, get: () => "",
          render: (p) => (
            <Link className="btn btn-sm" to={devicesHref(row.project_id, p.cond)} onClick={(e) => e.stopPropagation()}>
              Show the {p.n.toLocaleString()} serial{p.n === 1 ? "" : "s"}
            </Link>
          ) },
      ]}
    />
  );
}
