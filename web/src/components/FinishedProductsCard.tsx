/** Finished devices we hold, one row per PRODUCT.
 *
 *  The Orders page's "Devices on the shelf" is the same shelf cut by BATCH —
 *  "which batch still holds units". This is the cut a person asks for first:
 *  "how many dongles can we sell".
 *
 *  It reads `GET /api/finished-products`, which counts the DEVICE RECORDS, not
 *  `finished-stock`, which counts per batch. The difference is not academic: a
 *  device that names no batch is invisible to every per-batch figure, and 13 of
 *  them were on the real shelf when this was written — the platform reported 93
 *  devices while holding 106. Such a device is stock and is NOT costed, because
 *  per-device cost belongs to a batch, so it is counted in `no_batch` rather
 *  than quietly averaged in.
 *
 *  A row opens into its CONDITIONS, because "in stock" and "sellable" are not
 *  the same number and the difference is the point: a prototype is present,
 *  counted and worth something, and may never leave (decision 0032). Each
 *  condition links to that project's Devices tab, scoped to exactly the devices
 *  the number counted, so the answer to "which ones?" is one click and arrives
 *  as serials.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  errorMessage,
  getProductStock,
  isAbortError,
  type ProductStockRow,
} from "../api";
import { usd } from "../format";
import DataTable, { type Column } from "./DataTable";
import { ErrorBanner, Spinner } from "./Ui";

const CONDITION_WORD: Record<string, string> = {
  ok: "sellable",
  faulty: "faulty",
  prototype: "prototype",
  unidentified: "unidentified",
};

const CONDITION_WHY: Record<string, string> = {
  ok: "On the shelf and may ship. This is the only condition a shipment can draw.",
  faulty: "Present and ours, and it cannot be sold until it is repaired.",
  prototype: "Built to try something. It is counted and it never leaves (decision 0032).",
  unidentified: "On the shelf with nothing saying what it is — worth looking at.",
};

/** `/projects/:id?tab=Devices&state=in_stock&condition=…` — the exact devices
 *  the number counted, as serials. */
function devicesHref(projectId: number, condition: string): string {
  return `/projects/${projectId}?tab=Devices&state=in_stock`
    + `&condition=${encodeURIComponent(condition)}`;
}

export default function FinishedProductsCard() {
  const [stock, setStock] = useState<ProductStockRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getProductStock(ac.signal)
      .then((s) => {
        // A product that never built anything is noise; one whose every unit
        // has shipped is still a fact worth printing.
        setStock(s.products.filter((p) => p.in_stock > 0 || p.shipped > 0));
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  const rows = useMemo(() => stock ?? [], [stock]);
  const totals = useMemo(() => ({
    in_stock: rows.reduce((n, r) => n + r.in_stock, 0),
    available: rows.reduce((n, r) => n + r.available, 0),
    value: rows.reduce((n, r) => n + (r.value_usd ?? 0), 0),
    no_batch: rows.reduce((n, r) => n + r.no_batch, 0),
  }), [rows]);

  const cols: Column<ProductStockRow>[] = [
    {
      key: "project",
      label: "Product",
      width: 26,
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
    { key: "shipped", label: "Shipped", width: 12, numeric: true, get: (r) => r.shipped },
    { key: "batches", label: "Batches", width: 10, numeric: true, get: (r) => r.batches },
    {
      key: "value",
      label: "Value at cost",
      width: 12,
      numeric: true,
      get: (r) => r.value_usd ?? 0,
      title: (r) => "what the shelf cost to make, at each batch's own per-device actual"
        + (r.no_batch
          ? `. ${r.no_batch} device(s) name no batch, so nothing values them`
          : ""),
      render: (r) => <>{usd(r.value_usd ?? 0, 0)}</>,
    },
  ];

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Finished devices we hold</h2>
        {stock ? (
          <span className="toolbar-total">
            {totals.in_stock.toLocaleString()} on the shelf ·{" "}
            {totals.available.toLocaleString()} sellable · {usd(totals.value, 0)} at cost
          </span>
        ) : null}
      </div>
      <p className="card-subtitle">One row per product, open it for the conditions</p>
      <p className="muted dim">
        Only condition <code>ok</code> may ship, so a faulty or prototype unit is counted
        and visible here and can never leave. Open a row to see why, and click a condition
        to list those exact serials. The same devices cut by BATCH are on{" "}
        <Link to="/production/orders">Orders</Link>.
      </p>
      {totals.no_batch ? (
        // A device that names no batch is real stock and nothing values it —
        // and every per-batch figure in the platform is blind to it, which is
        // why it is said here rather than left to be discovered.
        <div className="banner-warn">
          <b>{totals.no_batch} device(s) on the shelf name no batch.</b> They are counted
          here and nothing values them, because per-device cost belongs to a batch. They are
          also invisible to every per-batch figure, including &ldquo;Devices on the
          shelf&rdquo; on <Link to="/production/orders">Orders</Link>. Link each one to the
          batch that made it from its own page.
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
    </div>
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
    <table className="data">
      <thead>
        <tr>
          <th>Condition</th>
          <th className="num">Devices</th>
          <th>What it means</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {parts.map(({ cond, n }) => (
          <tr key={cond}>
            <td>
              {cond === "ok" ? (
                <span className="pill ok">{CONDITION_WORD[cond]}</span>
              ) : (
                <span className="pill warn">{CONDITION_WORD[cond] ?? cond}</span>
              )}
            </td>
            <td className="num">{n.toLocaleString()}</td>
            <td className="muted">{CONDITION_WHY[cond] ?? "No rule recorded for this condition."}</td>
            <td>
              <Link className="btn btn-sm" to={devicesHref(row.project_id, cond)}>
                Show the {n.toLocaleString()} serial{n === 1 ? "" : "s"}
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
