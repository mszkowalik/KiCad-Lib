/** Orders — every customer order, and what is asked for against what is held.
 *
 *  Decision record 0003. An order sits above the project (an Aqua and a
 *  dongle on one order), is closed by invoices, and is fulfilled by shipments
 *  whose content is a set of devices. Its status is derived from shipments
 *  and never set by hand. What the shelf holds is on Stock → Finished devices.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  createOrder,
  errorMessage,
  getDemand,
  listCustomers,
  listOrders,
  getProjects,
  type CustomerRow,
  type OrderLineIn,
  type OrderRow,
  type ProjectInfo,
} from "../api";
import AutoTextarea from "../components/AutoTextarea";
import DataTable, { type Column } from "../components/DataTable";
import Field, { FieldGrid } from "../components/Field";
import DemandCard from "../components/DemandCard";
import { NarrowChip } from "../components/FoldSection";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { useAuth } from "../auth";
import { amount, plain, today, plural } from "../format";
import { useLoad } from "../components/useLoad";
import PageShell from "../components/PageShell";

/** One identity, because the new-order form has `projects` in its deps. */
const NO_PROJECTS: ProjectInfo[] = [];

export default function Orders() {
  const { data: orders, error: ordersError } = useLoad(listOrders, []);
  const { data: demand, error: demandError } = useLoad((signal) => getDemand(undefined, signal), []);
  const error = ordersError ?? demandError;
  const customers = useLoad(listCustomers, []).data ?? [];
  const projects = useLoad(getProjects, []).data ?? NO_PROJECTS;
  const [creating, setCreating] = useState(false);
  const [narrow, setNarrow] = useState<"" | "open" | "partial" | "fulfilled" | "unpaid">("");
  const navigate = useNavigate();

  const { companyName } = useAuth();
  const columns = useMemo<Column<OrderRow>[]>(
    () => [
      // A DATE has a hard maximum, so it takes a length rather than a promise
      // about the window: at 8% it was cut to `2026-09-0…` at 1280px, which is
      // exactly the case `Column.width`'s string form exists for.
      { key: "order_date", label: "Date", width: "104px", get: (o) => o.order_date, className: "mono" },
      { key: "customer", label: "Customer", width: 9, get: (o) => o.customer },
      { key: "company", label: "Company", width: 7, get: (o) => companyName(o.company_id) },
      { key: "order_ref", label: "Reference", width: 10, get: (o) => o.order_ref || "—", className: "mono" },
      {
        key: "products",
        // A concatenated list with no maximum — it truncates by design and the
        // cell's title carries the whole of it. Everything else on this row
        // fits, so this is the column that pays for them.
        label: "Products",
        width: 8,
        get: (o) => o.lines.map((l) => `${l.qty_ordered} × ${l.product || l.project}`).join(", "),
      },
      {
        key: "shipped",
        label: "Shipped",
        width: 11,
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
        // An amount with its currency may not be cut, as "300,000.00 PLN" was at 10.
        width: 14,
        numeric: true,
        get: (o) => o.total_net ?? "",
        render: (o) => <>{amount(o.total_net, o.currency)}</>,
      },
      {
        key: "invoiced",
        // Holds an amount AND an "· n unpaid" tail.
        label: "Invoiced",
        width: 20,
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
        // StatusPill is inline-block — an ellipsis cannot shorten it.
        label: "Status",
        width: 11,
        get: (o) => o.status,
        render: (o) => <StatusPill status={o.status} />,
      },
    ],
    [companyName],
  );

  return (
    <PageShell>
      <div className="toolbar">
        <h1>Orders</h1>
        <span className="toolbar-total">
          {orders ? `${plural(orders.length, "order")}` : ""}
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
            navigate(`/sales/orders/${o.id}`);
          }}
        />
      ) : null}

      <DemandCard rows={demand} />

      <div className="card pad">
        <h2 className="card-title">Customer orders</h2>
        <p className="muted dim">
          Status follows the shipments: open, partial, fulfilled. Click a row for its lines,
          invoices and shipments.
        </p>
        {orders === null ? (
          <Spinner label="Loading orders…" />
        ) : (
          <>
          <div className="stat-row">
            <NarrowChip n={orders.filter((o) => o.status === "open").length} tone="acc" value="open" current={narrow} onNarrow={setNarrow}>open</NarrowChip>
            <NarrowChip n={orders.filter((o) => o.status === "partial").length} tone="warn" value="partial" current={narrow} onNarrow={setNarrow}>partly shipped</NarrowChip>
            <NarrowChip n={orders.filter((o) => o.status === "fulfilled").length} tone="ok" value="fulfilled" current={narrow} onNarrow={setNarrow}>fulfilled</NarrowChip>
            <NarrowChip n={orders.filter((o) => o.unpaid_count > 0).length} tone={orders.some((o) => o.unpaid_count > 0) ? "warn" : undefined} value="unpaid" current={narrow} onNarrow={setNarrow}>with unpaid invoices</NarrowChip>
          </div>
          <DataTable
            rows={orders.filter((o) => !narrow || (narrow === "unpaid" ? o.unpaid_count > 0 : o.status === narrow))}
            columns={columns}
            rowKey={(o) => o.id}
            defaultSort={{ key: "order_date", dir: "desc" }}
            onRowClick={(o) => navigate(`/sales/orders/${o.id}`)}
            persistKey="orders"
          />
          </>
        )}
      </div>
    </PageShell>
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
  const [date, setDate] = useState(today);
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
      <FieldGrid>
        <Field label="Customer">
          <input className="text" list="customer-names" value={customer} onChange={(e) => setCustomer(e.target.value)} />
          <datalist id="customer-names">
            {customers.map((c) => (
              <option key={c.id} value={c.name} />
            ))}
          </datalist>
        </Field>
        <Field label="Reference">
          <input className="text" value={ref} placeholder="their PO, or our ZAL number" onChange={(e) => setRef(e.target.value)} />
        </Field>
        <Field label="Order date">
          <input className="text" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Currency">
          <input className="text" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
        </Field>
      </FieldGrid>
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
      <Field label="Notes">
        <AutoTextarea className="text" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
    </div>
  );
}
