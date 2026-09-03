/** Orders — every customer order, and the finished devices on the shelf.
 *
 *  Decision record 0003. An order sits above the project (an Aqua and a
 *  dongle on one order), is closed by invoices, and is fulfilled by shipments
 *  whose content is a set of devices. Its status is derived from shipments
 *  and never set by hand. The stock card is this number's ONE home: a count
 *  of devices in `in_stock` per batch, plus the units of legacy batches that
 *  were never recorded as devices (§8).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createOrder,
  errorMessage,
  getFinishedStock,
  isAbortError,
  listCustomers,
  listOrders,
  getProjects,
  type CustomerRow,
  type FinishedStock,
  type OrderLineIn,
  type OrderRow,
  type ProjectInfo,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { amount, plain, usd } from "../format";

export default function Orders() {
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const [stock, setStock] = useState<FinishedStock | null>(null);
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  const reload = useCallback(() => {
    const ac = new AbortController();
    listOrders(ac.signal)
      .then((rows) => {
        setOrders(rows);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getFinishedStock(undefined, ac.signal)
      .then(setStock)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    listCustomers(ac.signal).then(setCustomers).catch(() => setCustomers([]));
    getProjects(ac.signal).then(setProjects).catch(() => setProjects([]));
    return () => ac.abort();
  }, []);

  useEffect(() => reload(), [reload]);

  const columns = useMemo<Column<OrderRow>[]>(
    () => [
      { key: "order_date", label: "Date", width: 9, get: (o) => o.order_date, className: "mono" },
      { key: "customer", label: "Customer", width: 16, get: (o) => o.customer },
      { key: "order_ref", label: "Reference", width: 16, get: (o) => o.order_ref || "—", className: "mono" },
      {
        key: "products",
        label: "Products",
        width: 22,
        get: (o) => o.lines.map((l) => `${l.qty_ordered} × ${l.product || l.project}`).join(", "),
      },
      {
        key: "shipped",
        label: "Shipped",
        width: 9,
        numeric: true,
        get: (o) => o.qty_shipped,
        render: (o) => (
          <span className={o.qty_shipped < o.qty_ordered ? "warn-text" : undefined}>
            {o.qty_shipped.toLocaleString()} / {o.qty_ordered.toLocaleString()}
          </span>
        ),
      },
      {
        key: "total",
        label: "Net total",
        width: 11,
        numeric: true,
        get: (o) => o.total_net ?? "",
        render: (o) => <>{amount(o.total_net, o.currency)}</>,
      },
      {
        key: "invoiced",
        label: "Invoiced",
        width: 9,
        numeric: true,
        get: (o) => o.invoiced_net ?? "",
        title: (o) =>
          o.invoice_gap && Math.abs(o.invoice_gap) >= 0.01
            ? `${amount(o.invoice_gap, o.currency)} of the order total is not yet invoiced`
            : undefined,
        render: (o) => (
          <span className={o.invoice_gap && Math.abs(o.invoice_gap) >= 0.01 ? "warn-text" : undefined}>
            {o.invoice_count ? plain(o.invoiced_net) : "—"}
            {o.unpaid_count ? <span className="muted"> · {o.unpaid_count} unpaid</span> : null}
          </span>
        ),
      },
      {
        key: "status",
        label: "Status",
        width: 8,
        get: (o) => o.status,
        render: (o) => <StatusPill status={o.status} />,
      },
    ],
    [],
  );

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Orders</h1>
          <span className="toolbar-total">
            {orders ? `${orders.length} order${orders.length === 1 ? "" : "s"}` : ""}
          </span>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setCreating((v) => !v)}>
            {creating ? "Close" : "New order"}
          </button>
        </div>
        {error ? <ErrorBanner message={error} /> : null}

        {creating ? (
          <NewOrderCard
            customers={customers}
            projects={projects}
            onCreated={(o) => {
              setCreating(false);
              navigate(`/production/orders/${o.id}`);
            }}
          />
        ) : null}

        <StockCard stock={stock} />

        <div className="card pad">
          <h2 className="card-title">Customer orders</h2>
          <p className="card-subtitle">
            Status follows the shipments: open, partial, fulfilled. Click a row for its lines,
            invoices and shipments.
          </p>
          {orders === null ? (
            <Spinner label="Loading orders…" />
          ) : (
            <DataTable
              rows={orders}
              columns={columns}
              rowKey={(o) => o.id}
              defaultSort={{ key: "order_date", dir: "desc" }}
              onRowClick={(o) => navigate(`/production/orders/${o.id}`)}
              persistKey="orders"
            />
          )}
        </div>
      </div>
    </div>
  );
}

/** Finished devices per batch: recorded devices next to legacy units. */
function StockCard({ stock }: { stock: FinishedStock | null }) {
  const rows = useMemo(() => (stock ? stock.runs.filter((r) => r.stock > 0 || r.overdrawn > 0) : []), [stock]);
  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Devices on the shelf</h2>
        {stock ? (
          <span className="toolbar-total">
            {stock.totals.stock.toLocaleString()} devices
            {stock.totals.stock_value_usd != null ? ` · ${usd(stock.totals.stock_value_usd, 0)} at cost` : ""}
            {stock.totals.legacy_stock ? ` · ${stock.totals.legacy_stock.toLocaleString()} without a serial` : ""}
          </span>
        ) : null}
      </div>
      <p className="card-subtitle">
        A device enters the shelf when it passes programming in a batch and leaves it on a
        shipment. Units from batches that predate device records are counted from the batch
        quantity (“no serial”); a return can name one of them later.
      </p>
      {!stock ? (
        <Spinner label="Counting…" />
      ) : rows.length === 0 ? (
        <p className="muted">Nothing on the shelf.</p>
      ) : (
        <div className="table-wrap">
          <table className="data data-fixed finished-stock-table">
            <thead>
              <tr>
                <th>Project</th>
                <th>Batch</th>
                <th className="num">Built</th>
                <th className="num">Devices</th>
                <th className="num">Shipped</th>
                <th className="num">In stock</th>
                <th className="num">No serial</th>
                <th className="num">Unit cost</th>
                <th className="num">Value</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.run_id} className={r.overdrawn ? "err-text" : undefined}>
                  <td title={r.project}>{r.project}</td>
                  <td title={r.label}>
                    <Link className="comp-link" to={`/runs/${r.run_id}`}>{r.label}</Link>
                  </td>
                  <td className="num">{r.built.toLocaleString()}</td>
                  <td className="num" title="devices recorded in this batch">{r.devices_produced.toLocaleString()}</td>
                  <td className="num">{(r.devices_shipped + r.unserialized_shipped).toLocaleString()}</td>
                  <td className="num">{r.devices_in_stock.toLocaleString()}</td>
                  <td
                    className="num"
                    title={
                      r.overdrawn
                        ? `${r.overdrawn} more units were shipped from this batch than it is recorded to hold`
                        : "units counted from the batch quantity, not from device records"
                    }
                  >
                    {r.overdrawn ? `−${r.overdrawn}` : r.legacy_stock.toLocaleString()}
                  </td>
                  <td className="num">{usd(r.unit_cost_usd)}</td>
                  <td className="num">{usd(r.stock_value_usd, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function NewOrderCard({
  customers,
  projects,
  onCreated,
}: {
  customers: CustomerRow[];
  projects: ProjectInfo[];
  onCreated: (o: OrderRow) => void;
}) {
  const [customer, setCustomer] = useState(customers[0]?.name ?? "");
  const [ref, setRef] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [currency, setCurrency] = useState("PLN");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<{ project_id: string; product: string; qty: string; price: string }[]>([
    { project_id: String(projects[0]?.id ?? ""), product: "", qty: "", price: "" },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!customer && customers[0]) setCustomer(customers[0].name);
  }, [customers, customer]);
  useEffect(() => {
    setLines((ls) => ls.map((l) => (l.project_id ? l : { ...l, project_id: String(projects[0]?.id ?? "") })));
  }, [projects]);

  const submit = async () => {
    const body: OrderLineIn[] = [];
    for (const l of lines) {
      const pid = Number(l.project_id);
      const qty = Number(l.qty);
      const price = Number(l.price);
      if (!pid || !Number.isFinite(qty) || qty < 1 || !Number.isFinite(price)) {
        setError("Every line needs a project, a quantity and a net unit price.");
        return;
      }
      body.push({ project_id: pid, product: l.product.trim(), qty_ordered: qty, unit_price: price });
    }
    if (!customer.trim()) {
      setError("Name the customer.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const existing = customers.find((c) => c.name === customer.trim());
      const o = await createOrder({
        customer_id: existing?.id ?? null,
        customer: customer.trim(),
        order_ref: ref.trim(),
        order_date: date.trim(),
        currency: currency.trim().toUpperCase() || "PLN",
        notes,
        lines: body,
      });
      onCreated(o);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card pad edit-card">
      <h2 className="card-title">New order</h2>
      {error ? <ErrorBanner message={error} /> : null}
      <div className="edit-grid">
        <label>
          Customer
          <input className="text" list="customer-names" value={customer} onChange={(e) => setCustomer(e.target.value)} />
          <datalist id="customer-names">
            {customers.map((c) => (
              <option key={c.id} value={c.name} />
            ))}
          </datalist>
        </label>
        <label>
          Reference
          <input className="text" value={ref} placeholder="their PO, or our ZAL number" onChange={(e) => setRef(e.target.value)} />
        </label>
        <label>
          Order date
          <input className="text" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          Currency
          <input className="text" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
        </label>
      </div>
      <div className="table-wrap">
        <table className="data data-fixed order-lines-edit-table">
          <thead>
            <tr>
              <th>Project</th>
              <th>Product (as invoiced)</th>
              <th className="num">Qty</th>
              <th className="num">Net unit price</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td>
                  <select
                    className="row-input"
                    value={l.project_id}
                    onChange={(e) => setLines((ls) => ls.map((x, j) => (j === i ? { ...x, project_id: e.target.value } : x)))}
                  >
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    className="row-input"
                    value={l.product}
                    placeholder="CE_DONGLE_V2"
                    onChange={(e) => setLines((ls) => ls.map((x, j) => (j === i ? { ...x, product: e.target.value } : x)))}
                  />
                </td>
                <td className="num">
                  <input
                    className="row-input num"
                    inputMode="numeric"
                    value={l.qty}
                    onChange={(e) => setLines((ls) => ls.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))}
                  />
                </td>
                <td className="num">
                  <input
                    className="row-input num"
                    inputMode="decimal"
                    value={l.price}
                    onChange={(e) => setLines((ls) => ls.map((x, j) => (j === i ? { ...x, price: e.target.value } : x)))}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={lines.length === 1}
                    onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="btn-row">
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => setLines((ls) => [...ls, { project_id: String(projects[0]?.id ?? ""), product: "", qty: "", price: "" }])}
        >
          Add a product
        </button>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={submit}>
          {busy ? "Creating…" : "Create order"}
        </button>
      </div>
      <label>
        Notes
        <textarea className="note-textarea" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
    </div>
  );
}
