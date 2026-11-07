/** One customer order: its lines, the invoices that close it, the shipments
 *  that fulfil it, and what it earned once every shipped device — replacements
 *  included — carries its batch's real cost (decision 0003 §9).
 *
 *  Shipping is Pack, then Send (decision 0103): "Pack…" opens a shipment, and a
 *  shipment takes SERIALS ONLY, because a number with no device behind it is a
 *  guess (decisions 0032, 0049). Returns, repairs and disposals live on the
 *  device page, because they are events in a device's history.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  addOrderInvoice,
  addOrderLine,
  allocateOrderDevices,
  releaseOrderDevices,
  openShipment,
  reverseShipment,
  deleteOrder,
  deleteOrderInvoice,
  deleteOrderLine,
  deleteShipment,
  errorMessage,
  getOrder,
  getProjects,
  listCustomers,
  updateOrder,
  updateOrderInvoice,
  updateOrderLine,
  type InvoiceIn,
  type OrderInvoiceRow,
  type OrderLineRow,
  type OrderPatchBody,
  type OrderRow,
  type ProjectInfo,
  type ShipmentRow,
} from "../api";
import AutoTextarea from "../components/AutoTextarea";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import FoldSection, { StatChip } from "../components/FoldSection";
import { useModal } from "../components/modal";
import RowChangesCard from "../components/RowChangesCard";
import { BackLink, ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import Field, { FieldGrid } from "../components/Field";
import { useAuth } from "../auth";
import { amount, plain, plnAmount, today, plural } from "../format";
import { parseScanSheet } from "../scanSheet";
import { SerialsField } from "../components/ScanList";
import { useLoad } from "../components/useLoad";
import PageShell, { PageLoading } from "../components/PageShell";

const INVOICE_KINDS: OrderInvoiceRow["kind"][] = ["advance", "final", "proforma", "correction"];

/** One identity, because the lines card has `projects` in its deps. */
const NO_PROJECTS: ProjectInfo[] = [];

export default function OrderDetail() {
  const { id } = useParams();
  const orderId = Number(id);
  const { data: order, setData: setOrder, error, setError } = useLoad(
    (signal) => getOrder(orderId, signal),
    [orderId],
    { keep: true },
  );
  const projects = useLoad(getProjects, [orderId], { keep: true }).data ?? NO_PROJECTS;
  const dialog = useDialog();
  const navigate = useNavigate();

  const apply = async (work: () => Promise<OrderRow>) => {
    try {
      setOrder(await work());
      setError(null);
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "That did not work" });
    }
  };

  if (!order) return <PageLoading error={error} label="Loading order…" />;
  const cur = order.currency;
  const eco = order.economics;

  return (
    <PageShell>
      <div className="toolbar">
        <BackLink to="/sales/orders">← Orders</BackLink>
        <h1>
          {order.customer}
          {order.order_ref ? <span className="mono"> · {order.order_ref}</span> : null}
        </h1>
        <StatusPill status={order.status} />
        <span className="toolbar-total">
          {order.order_date || "no date"} · {order.qty_shipped.toLocaleString()} of{" "}
          {order.qty_ordered.toLocaleString()} shipped · {amount(order.total_net, cur)} net
        </span>
        <button
          type="button"
          className="btn btn-sm"
          disabled={order.cancelled}
          title="Open a shipment for this order and scan devices into it as they are packed"
          onClick={async () => {
            try {
              const sh = await openShipment({ order_id: order.id });
              navigate(`/sales/shipments/${sh.id}`);
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        >
          Pack…
        </button>
      </div>
      {error ? <ErrorBanner message={error} /> : null}

      <div className="detail-page order-page">
        <div className="detail-left">
          <LinesCard order={order} projects={projects} apply={apply} />
          <InvoicesCard order={order} apply={apply} />
          <ShipmentsCard order={order} apply={apply} />
          <RowChangesCard table="sales_orders" id={order.id} />
        </div>
        <div className="detail-right">
          <div className="card pad">
            <h2 className="card-title">Did this order make money?</h2>
            {eco ? (
              <dl className="kv">
                <dt>Order revenue (net)</dt>
                <dd title={eco.revenue_basis === "invoices" ? "sum of advance, final and correction invoices" : "no money invoice yet — the order's line totals"}>
                  {amount(eco.revenue_net, eco.currency)}
                  {eco.currency !== "PLN" ? <span className="muted"> · {plnAmount(eco.revenue_pln, 0)}</span> : null}
                  {eco.revenue_basis === "order" ? <span className="muted"> (not invoiced yet)</span> : null}
                </dd>
                <dt>Devices shipped</dt>
                <dd>
                  {eco.shipped_units.toLocaleString()} of {eco.ordered_units.toLocaleString()}
                  {eco.replacements ? <span className="muted"> · {plural(eco.replacements, "replacement")}</span> : null}
                </dd>
                <dt>Shipped units earn</dt>
                <dd title="each line's net price for each unit shipped against it, up to the quantity ordered; a fully shipped order earns its whole revenue">
                  {amount(eco.shipped_revenue_net, eco.currency)}
                  {eco.currency !== "PLN" ? <span className="muted"> · {plnAmount(eco.shipped_revenue_pln, 0)}</span> : null}
                </dd>
                {eco.to_ship_units ? (
                  <>
                    <dt>Still to ship</dt>
                    <dd>
                      {plural(eco.to_ship_units, "unit")}
                      <span className="muted"> · {amount(eco.to_ship_net, eco.currency)}</span>
                    </dd>
                  </>
                ) : null}
                <dt>Cost of devices</dt>
                <dd>{plnAmount(eco.devices_cost_pln, 0)}</dd>
                <dt>Repairs</dt>
                <dd>{plnAmount(eco.repair_cost_pln, 0)}</dd>
                <dt>Margin on shipped units</dt>
                {eco.margin_pln == null ? (
                  <dd className="muted">— nothing shipped yet</dd>
                ) : (
                  <dd className={eco.margin_pln < 0 ? "err-text" : undefined}>
                    {plnAmount(eco.margin_pln, 0)}
                    {eco.margin_pct != null ? <span className="muted"> · {eco.margin_pct.toFixed(1)}%</span> : null}
                  </dd>
                )}
              </dl>
            ) : (
              <Spinner />
            )}
            {eco && eco.uncosted_units ? (
              <div className="banner-warn">
                {plural(eco.uncosted_units, "shipped unit")} carry no batch cost
                yet — their batch has no priced actuals.
              </div>
            ) : null}
            {eco && eco.unknown_currencies.length ? (
              <div className="banner-warn">
                No exchange rate stored for {eco.unknown_currencies.join(", ")}; those amounts are
                not converted. Add it under <Link to="/finance/rates">Finance → Exchange rates</Link>.
              </div>
            ) : null}
            <p className="muted">
              Every shipped device carries the actual per-device cost of the batch it came from,
              replacements included. The margin sets the shipped units&apos; revenue against
              that cost. Revenue converts per invoice at the invoice date.
            </p>
          </div>
          <HeaderCard order={order} apply={apply} />
        </div>
      </div>
    </PageShell>
  );
}

function HeaderCard({ order, apply }: { order: OrderRow; apply: (w: () => Promise<OrderRow>) => Promise<void> }) {
  const customers = useLoad(listCustomers, []).data ?? [];
  const [customer, setCustomer] = useState(order.customer);
  const [ref, setRef] = useState(order.order_ref);
  const [date, setDate] = useState(order.order_date);
  const [currency, setCurrency] = useState(order.currency);
  const [vat, setVat] = useState(String(order.vat_pct));
  const [notes, setNotes] = useState(order.notes);
  const { companies } = useAuth();
  const navigate = useNavigate();
  const [companyId, setCompanyId] = useState(order.company_id);
  const dialog = useDialog();
  useEffect(() => {
    setCustomer(order.customer);
    setRef(order.order_ref);
    setDate(order.order_date);
    setCurrency(order.currency);
    setVat(String(order.vat_pct));
    setNotes(order.notes);
    setCompanyId(order.company_id);
  }, [order]);
  const vatNum = Number(vat);
  const vatOk = vat.trim() !== "" && Number.isFinite(vatNum) && vatNum >= 0;
  const dirty =
    customer.trim() !== order.customer ||
    ref !== order.order_ref ||
    date !== order.order_date ||
    currency.trim().toUpperCase() !== order.currency ||
    (vatOk && vatNum !== order.vat_pct) ||
    notes !== order.notes ||
    companyId !== order.company_id;
  const canSave = dirty && customer.trim() !== "" && currency.trim() !== "" && vatOk;
  const save = () => {
    const name = customer.trim();
    const existing = customers.find((c) => c.name === name);
    const body: OrderPatchBody = { order_ref: ref, order_date: date, currency: currency.trim().toUpperCase(), vat_pct: vatNum, notes };
    if (name !== order.customer) {
      if (existing) body.customer_id = existing.id;
      else body.customer = name;
    }
    if (companyId !== null && companyId !== order.company_id) body.company_id = companyId;
    return apply(() => updateOrder(order.id, body));
  };
  return (
    <div className="card pad edit-card">
      <h2 className="card-title">Order</h2>
      <FieldGrid>
        <Field label="Customer" wide>
          <input className="text" list="order-customer-names" value={customer} onChange={(e) => setCustomer(e.target.value)} />
          <datalist id="order-customer-names">
            {customers.map((c) => (
              <option key={c.id} value={c.name} />
            ))}
          </datalist>
        </Field>
        <Field label="Seller">
          <select className="text" value={companyId ?? ""} onChange={(e) => setCompanyId(Number(e.target.value))}>
            {companyId === null ? <option value="">—</option> : null}
            {companies.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Reference">
          <input className="text" value={ref} onChange={(e) => setRef(e.target.value)} />
        </Field>
        <Field label="Order date">
          <input className="text" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Currency">
          <input className="text" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} />
        </Field>
        <Field label="VAT %">
          <input className="text" value={vat} inputMode="decimal" onChange={(e) => setVat(e.target.value)} />
        </Field>
        <Field label="Notes" wide>
          <AutoTextarea className="text" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </FieldGrid>
      <div className="btn-row">
        <button type="button" className="btn btn-primary btn-sm" disabled={!canSave} onClick={save}>
          Save
        </button>
        <button
          type="button"
          className={"btn btn-sm" + (order.cancelled ? "" : " btn-danger")}
          onClick={async () => {
            if (order.cancelled) {
              await apply(() => updateOrder(order.id, { cancelled: false }));
              return;
            }
            if (
              await dialog.confirm("Cancel this order? Nothing is deleted; it stops accepting shipments.", {
                title: "Cancel order",
                confirmLabel: "Cancel order",
                tone: "danger",
              })
            ) {
              await apply(() => updateOrder(order.id, { cancelled: true }));
            }
          }}
        >
          {order.cancelled ? "Reopen" : "Cancel order"}
        </button>
        <button
          type="button"
          className="btn btn-sm btn-danger"
          title="Only an order no device event names can be deleted. Cancel it otherwise."
          onClick={async () => {
            const ok = await dialog.confirm(`Delete this order for ${order.customer}? It cannot be undone here.`, {
              title: "Delete order",
              confirmLabel: "Delete order",
              tone: "danger",
            });
            if (!ok) return;
            try {
              await deleteOrder(order.id);
              navigate("/sales/orders");
            } catch (err) {
              await dialog.alert(errorMessage(err), { title: "Could not delete the order" });
            }
          }}
        >
          Delete order…
        </button>
      </div>
      <p className="muted">
        A new customer name creates the customer. The seller is the company that issues the invoices.
        VAT is printed only; every figure here is net.
      </p>
    </div>
  );
}

/** Reserve devices for one line: reserved, not shipped (decision 0003). The route
 *  has no dry run, and it writes all of them or none, so a refusal names the
 *  device and the list stays here to correct. */
function ReserveDialog({ order, line, onClose }: {
  order: OrderRow;
  line: OrderLineRow;
  onClose: (updated: OrderRow | null) => void;
}) {
  const modal = useModal(() => onClose(null));
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const serials = parseScanSheet(text);
  const reserve = async () => {
    setBusy(true);
    setError(null);
    try {
      onClose(await allocateOrderDevices(order.id, line.id, serials));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">Reserve devices for {line.product || line.project}</h2>
        <p className="muted dim">
          A reserved device stays on the shelf and leaves stock for this line. It must be in stock
          and belong to {line.project}. A shipment of this order can still take it, and Release…
          under the list of products gives it back to stock.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        <SerialsField value={text} onChange={setText} />
        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" onClick={() => onClose(null)}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !serials.length} onClick={() => void reserve()}>
            Reserve {serials.length || ""}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Give reserved devices back to stock. The same form as `ReserveDialog`: the
 *  route writes all of them or none, so a refusal names the device and the list
 *  stays here to correct. The serials are printed here because no other place on
 *  this page names them, and "Release all" sends ids, because a scan list drops a
 *  serial with a dash. */
function ReleaseDialog({ order, line, onClose }: {
  order: OrderRow;
  line: OrderLineRow;
  onClose: (updated: OrderRow | null) => void;
}) {
  const modal = useModal(() => onClose(null));
  const dialog = useDialog();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const serials = parseScanSheet(text);
  const reserved = line.reserved_devices;
  const nameOf = (d: { device_id: number; serial: string }) => d.serial || `#${d.device_id}`;
  const listed = (names: string[], limit: number) =>
    names.length > limit ? `${names.slice(0, limit).join(", ")} and ${names.length - limit} more` : names.join(", ");
  const release = async (devices: { serials?: string[]; device_ids?: number[] }, names: string[]) => {
    const ok = await dialog.confirm(
      `Release ${listed(names, 12)} from ${line.product || line.project}? ${names.length === 1 ? "It goes" : "They go"} back to stock. The device history keeps the reservation and the release.`,
      { title: "Release reservation", confirmLabel: "Release", tone: "danger" },
    );
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      onClose(await releaseOrderDevices(order.id, line.id, devices));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">Release devices reserved for {line.product || line.project}</h2>
        <p className="muted dim">
          A released device goes back to stock. A device packed in a shipment is not released here:
          take it out on the page of that shipment.
        </p>
        <p className="muted dim">
          Reserved now: <span className="mono">{listed(reserved.map(nameOf), 40)}</span>
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        <SerialsField value={text} onChange={setText} />
        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" onClick={() => onClose(null)}>Cancel</button>
          <button type="button" className="btn" disabled={busy}
            onClick={() => void release({ device_ids: reserved.map((d) => d.device_id) }, reserved.map(nameOf))}>
            Release all {reserved.length}
          </button>
          <button type="button" className="btn btn-danger" disabled={busy || !serials.length}
            onClick={() => void release({ serials }, serials)}>
            Release {serials.length || ""}
          </button>
        </div>
      </div>
    </div>
  );
}

function LinesCard({
  order,
  projects,
  apply,
}: {
  order: OrderRow;
  projects: ProjectInfo[];
  apply: (w: () => Promise<OrderRow>) => Promise<void>;
}) {
  const dialog = useDialog();
  const [reserving, setReserving] = useState<OrderLineRow | null>(null);
  const [releasing, setReleasing] = useState<OrderLineRow | null>(null);
  const [adding, setAdding] = useState(false);
  const [pid, setPid] = useState(String(projects[0]?.id ?? ""));
  const [product, setProduct] = useState("");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  useEffect(() => {
    if (!pid && projects[0]) setPid(String(projects[0].id));
  }, [projects, pid]);

  const editQty = async (li: OrderLineRow) => {
    const v = await dialog.prompt(`Quantity ordered for ${li.product || li.project}:`, {
      title: "Edit line",
      initial: String(li.qty_ordered),
    });
    if (v == null) return;
    const n = Number(v);
    if (!Number.isFinite(n) || n < 1) return;
    await apply(() => updateOrderLine(li.id, { qty_ordered: n }));
  };
  const editPrice = async (li: OrderLineRow) => {
    const v = await dialog.prompt(`Net unit price for ${li.product || li.project} (${order.currency}):`, {
      title: "Edit line",
      initial: String(li.unit_price),
    });
    if (v == null) return;
    const n = Number(v);
    if (!Number.isFinite(n)) return;
    await apply(() => updateOrderLine(li.id, { unit_price: n }));
  };

  const lineCols: Column<OrderLineRow>[] = [
    { key: "product", label: "Product", width: 16, className: "mono", get: (li) => li.product || "—" },
    {
      key: "project",
      label: "Project",
      width: 16,
      get: (li) => [li.project, li.board, li.variant].filter(Boolean).join(" / "),
      render: (li) => (
        <>
          <Link className="val-link" to={`/projects/${li.project_id}`}>{li.project}</Link>
          {li.board && li.board !== li.project ? <span className="muted"> {li.board}</span> : null}
          {li.variant ? <span className="muted"> / {li.variant}</span> : null}
        </>
      ),
    },
    {
      key: "ordered",
      label: "Ordered",
      width: 10,
      numeric: true,
      get: (li) => li.qty_ordered,
      title: () => "Click to change the quantity ordered",
      render: (li) => (
        <button type="button" className="linklike" onClick={() => editQty(li)}>
          {li.qty_ordered.toLocaleString()}
        </button>
      ),
    },
    {
      key: "unit",
      label: "Unit net",
      width: 13,
      numeric: true,
      get: (li) => li.unit_price,
      title: () => "Click to change the net unit price",
      render: (li) => (
        <button type="button" className="linklike" onClick={() => editPrice(li)}>
          {plain(li.unit_price)}
        </button>
      ),
    },
    { key: "net", label: "Net total", width: 16, numeric: true, get: (li) => li.net_total, render: (li) => <>{plain(li.net_total)}</> },
    {
      key: "shipped",
      label: "Shipped",
      width: 10,
      numeric: true,
      get: (li) => li.qty_shipped,
      title: (li) => `${plural(li.qty_shipped, "device")} delivered${li.qty_replacements ? ` · ${li.qty_replacements} replacement(s) not counted` : ""}`,
      render: (li) => (
        <>
          {li.qty_shipped.toLocaleString()}
          {li.qty_replacements ? <span className="muted"> +{li.qty_replacements}</span> : null}
        </>
      ),
    },
    {
      key: "open",
      label: "Open",
      width: 11,
      numeric: true,
      get: (li) => li.qty_open,
      title: () => undefined,
      render: (li) => <span className={li.qty_open ? "warn-text" : undefined}>{li.qty_open.toLocaleString()}</span>,
    },
    {
      key: "back",
      label: "Back",
      width: 8,
      numeric: true,
      interactive: false,
      sortable: true,
      get: (li) => li.qty_returned || "—",
      title: () => "devices returned from this line",
    },
    {
      key: "act",
      label: "",
      // Two buttons, and no line of it may be cut.
      width: "150px",
      interactive: false,
      get: () => "",
      title: () => undefined,
      render: (li) => (
        <>
          <button
            type="button"
            className="btn btn-sm"
            disabled={order.cancelled}
            title="Reserve devices from the shelf for this line"
            onClick={() => setReserving(li)}
          >
            Reserve…
          </button>{" "}
          <button
            type="button"
            className="btn btn-sm"
            title="remove this line (only while nothing was shipped against it)"
            disabled={li.qty_shipped > 0 || li.qty_replacements > 0}
            onClick={async () => {
              if (await dialog.confirm(`Remove ${li.product || li.project} from the order?`, { tone: "danger" })) {
                await apply(() => deleteOrderLine(li.id));
              }
            }}
          >
            ×
          </button>
        </>
      ),
    },
  ];

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Products</h2>
        <span className="toolbar-total">{amount(order.total_net, order.currency)} net</span>
        <button type="button" className="btn btn-sm" onClick={() => setAdding((v) => !v)}>
          {adding ? "Close" : "Add a product"}
        </button>
      </div>
      <DataTable rows={order.lines} rowKey={(li) => li.id} columns={lineCols} empty="No products on this order." />
      {/* Under the table, not in it. On a wide window the page has two columns, this
          card gets the narrow one (812 px), and a third button in the row cut the
          numbers. A line can also hold devices in a box, which only count here. */}
      {order.lines.filter((li) => li.qty_allocated).map((li) => {
        const reserved = li.reserved_devices.length;
        const packed = li.qty_allocated - reserved;
        return (
          <div className="toolbar" key={li.id}>
            <span className="muted">
              {li.product || li.project}:{" "}
              {[reserved ? `${reserved} reserved` : "", packed ? `${packed} packed in an open shipment` : ""].filter(Boolean).join(", ")}
            </span>
            {reserved ? (
              <button type="button" className="btn btn-sm" title="Give devices reserved on this line back to stock"
                onClick={() => setReleasing(li)}>
                Release…
              </button>
            ) : null}
          </div>
        );
      })}
      {adding ? (
        <FieldGrid>
          <Field label="Project">
            <select className="text" value={pid} onChange={(e) => setPid(e.target.value)}>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </Field>
          <Field label="Product (as invoiced)">
            <input className="text" value={product} onChange={(e) => setProduct(e.target.value)} />
          </Field>
          <Field label="Quantity">
            <input className="text num" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} />
          </Field>
          <Field label="Net unit price">
            <input className="text num" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
          </Field>
          <div className="btn-row">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={async () => {
                const n = Number(qty);
                const p = Number(price);
                if (!Number(pid) || !Number.isFinite(n) || n < 1 || !Number.isFinite(p)) return;
                await apply(() => addOrderLine(order.id, { project_id: Number(pid), product: product.trim(), qty_ordered: n, unit_price: p }));
                setAdding(false);
                setProduct("");
                setQty("");
                setPrice("");
              }}
            >
              Add
            </button>
          </div>
        </FieldGrid>
      ) : null}
      {reserving ? (
        <ReserveDialog order={order} line={reserving} onClose={(updated) => {
          setReserving(null);
          if (updated) void apply(async () => updated);
        }} />
      ) : null}
      {releasing ? (
        <ReleaseDialog order={order} line={releasing} onClose={(updated) => {
          setReleasing(null);
          if (updated) void apply(async () => updated);
        }} />
      ) : null}
    </div>
  );
}

function InvoicesCard({ order, apply }: { order: OrderRow; apply: (w: () => Promise<OrderRow>) => Promise<void> }) {
  const dialog = useDialog();
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState<OrderInvoiceRow["kind"]>(order.invoices?.length ? "final" : "advance");
  const [number, setNumber] = useState("");
  const [issue, setIssue] = useState(today);
  const [due, setDue] = useState("");
  const [net, setNet] = useState("");
  const [paid, setPaid] = useState("");
  const invoices = order.invoices ?? [];
  const gap = order.invoice_gap ?? 0;

  const submit = async () => {
    const n = Number(net);
    if (!number.trim() || !issue.trim() || !Number.isFinite(n)) return;
    const body: InvoiceIn = { kind, number: number.trim(), issue_date: issue.trim(), due_date: due.trim(), net_amount: n, paid_at: paid.trim() };
    await apply(() => addOrderInvoice(order.id, body));
    setAdding(false);
    setNumber("");
    setNet("");
    setPaid("");
    setDue("");
  };

  const markPaid = async (inv: OrderInvoiceRow) => {
    const v = await dialog.prompt(`Paid on (date) — ${inv.number}:`, {
      title: "Mark paid",
      initial: inv.paid_at || today(),
    });
    if (v == null) return;
    await apply(() => updateOrderInvoice(inv.id, { paid_at: v.trim() }));
  };

  const overdue = (inv: OrderInvoiceRow) =>
    !inv.paid_at && !!inv.due_date && inv.due_date < today() && inv.kind !== "proforma";
  const invoiceCols: Column<OrderInvoiceRow>[] = [
    { key: "kind", label: "Kind", width: 10, get: (inv) => inv.kind },
    { key: "number", label: "Number", width: 24, className: "mono", get: (inv) => inv.number },
    { key: "issued", label: "Issued", width: 12, className: "mono", get: (inv) => inv.issue_date || "—" },
    {
      key: "due",
      label: "Due",
      width: 12,
      className: "mono",
      get: (inv) => inv.due_date || "—",
      title: (inv) => (overdue(inv) ? "overdue" : undefined),
      render: (inv) => <span className={overdue(inv) ? "err-text" : undefined}>{inv.due_date || "—"}</span>,
    },
    { key: "net", label: "Net", width: 16, numeric: true, get: (inv) => inv.net_amount, render: (inv) => <>{amount(inv.net_amount, inv.currency)}</> },
    {
      key: "paid",
      label: "Paid",
      width: 14,
      get: (inv) => (inv.kind === "proforma" ? "n/a" : inv.paid_at || "not paid"),
      title: () => undefined,
      render: (inv) => (inv.kind === "proforma" ? (
        <span className="muted">n/a</span>
      ) : inv.paid_at ? (
        <button type="button" className="linklike mono" title="Change the date" onClick={() => markPaid(inv)}>{inv.paid_at}</button>
      ) : (
        <button type="button" className="btn btn-sm" onClick={() => markPaid(inv)}>mark paid</button>
      )),
    },
    {
      key: "act",
      label: "",
      width: 12,
      interactive: false,
      className: "ctr",
      get: () => "",
      title: () => undefined,
      render: (inv) => (
        <button
          type="button"
          className="btn btn-sm"
          title={`Delete invoice ${inv.number}`}
          onClick={async () => {
            if (await dialog.confirm(`Delete invoice ${inv.number} from the order?`, { tone: "danger" })) {
              await apply(() => deleteOrderInvoice(inv.id));
            }
          }}
        >
          ×
        </button>
      ),
    },
  ];

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Invoices</h2>
        <span className="toolbar-total">
          {plain(order.invoiced_net)} of {plain(order.total_net)} {order.currency} invoiced
        </span>
        <button type="button" className="btn btn-sm" onClick={() => setAdding((v) => !v)}>
          {adding ? "Close" : "Add an invoice"}
        </button>
      </div>
      {Math.abs(gap) >= 0.01 && invoices.some((i) => i.kind !== "proforma") ? (
        <div className="banner-warn">
          Advance, final and correction invoices sum to {plain(order.invoiced_net)} {order.currency};
          the order is {plain(order.total_net)} — {plain(gap)} {order.currency}{" "}
          {gap > 0 ? "still to invoice" : "over-invoiced"}. A proforma does not count.
        </div>
      ) : null}
      {invoices.length === 0 ? (
        <p className="muted">Nothing issued yet.</p>
      ) : (
        <DataTable
          rows={invoices}
          rowKey={(inv) => inv.id}
          rowClass={(inv) => (inv.kind === "proforma" ? "dim" : "")}
          columns={invoiceCols}
        />
      )}
      {adding ? (
        <FieldGrid>
          <Field label="Kind">
            <select className="text" value={kind} onChange={(e) => setKind(e.target.value as OrderInvoiceRow["kind"])}>
              {INVOICE_KINDS.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </Field>
          <Field label="Number">
            <input className="text" value={number} placeholder="ZAL 00001/03/2026" onChange={(e) => setNumber(e.target.value)} />
          </Field>
          <Field label="Issued">
            <input className="text" value={issue} onChange={(e) => setIssue(e.target.value)} />
          </Field>
          <Field label="Due (blank = issue + terms)">
            <input className="text" value={due} onChange={(e) => setDue(e.target.value)} />
          </Field>
          <Field label={`Net amount (${order.currency})`}>
            <input
              className="text num"
              inputMode="decimal"
              value={net}
              placeholder={kind === "advance" && order.total_net ? plain(order.total_net * 0.6) : ""}
              onChange={(e) => setNet(e.target.value)}
            />
          </Field>
          <Field label="Paid on (optional)">
            <input className="text" value={paid} onChange={(e) => setPaid(e.target.value)} />
          </Field>
          <div className="btn-row">
            <button type="button" className="btn btn-primary btn-sm" onClick={submit}>Add</button>
          </div>
        </FieldGrid>
      ) : null}
    </div>
  );
}

function ShipmentsCard({ order, apply }: { order: OrderRow; apply: (w: () => Promise<OrderRow>) => Promise<void> }) {
  const dialog = useDialog();
  const shipments = order.shipments ?? [];
  const lineName = (id: number) => {
    const li = order.lines.find((l) => l.id === id);
    return li ? li.product || li.project : `line ${id}`;
  };
  const contentOf = (sh: ShipmentRow) =>
    Object.entries(sh.per_line).map(([lid, n]) => `${n} × ${lineName(Number(lid))}`).join(", ");
  const remove = async (sh: ShipmentRow) => {
    if (await dialog.confirm("Delete this shipment? Only possible while no device is recorded on it.", { tone: "danger" })) {
      await apply(() => deleteShipment(sh.id));
    }
  };
  const takeBack = async (sh: ShipmentRow) => {
    const plan = await reverseShipment(sh.id, { dry_run: true });
    const what = plan.devices.length
      ? `${plural(plan.devices.length, "device")}`
      : "";
    if (
      await dialog.confirm(
        `Take this shipment back? ${what} return to stock and the order stops counting them as delivered. ` +
          "Use this only for a delivery recorded in error — a shipment the customer received comes back as a return, on the device.",
        { tone: "danger", confirmLabel: "Take it back" },
      )
    ) {
      await apply(async () => {
        await reverseShipment(sh.id, { dry_run: false, note: "" });
        return await getOrder(order.id);
      });
    }
  };
  const columns: Column<ShipmentRow>[] = [
    { key: "date", label: "Date", width: 11, className: "mono", get: (sh) => sh.shipped_at || "—" },
    {
      key: "kind",
      label: "Kind",
      width: 11,
      get: (sh) => (sh.kind === "return" ? "return" : sh.status !== "sent" ? sh.status : "delivery"),
      render: (sh) => (sh.kind === "return" ? (
        <span className="pill warn">return</span>
      ) : sh.status !== "sent" ? (
        <Link to={`/sales/shipments/${sh.id}`} onClick={(e) => e.stopPropagation()} title="Open the packing page">
          <StatusPill status={sh.status} />
        </Link>
      ) : (
        "delivery"
      )),
    },
    {
      key: "content",
      label: "Content",
      width: 39,
      get: (sh) => contentOf(sh),
      // The row is one line, so what it cuts stays readable on the hover.
      title: (sh) => [
        contentOf(sh),
        sh.devices.length ? `${plural(sh.devices.length, "serial")}` : "",
        sh.reversed ? `${sh.reversed} taken back` : "",
      ].filter(Boolean).join(" · "),
      render: (sh) => (
        <>
          {contentOf(sh) || <span className="muted">nothing</span>}
          {sh.devices.length ? <span className="muted"> · {plural(sh.devices.length, "serial")}</span> : null}
          {sh.reversed ? <span className="muted"> · {sh.reversed} taken back</span> : null}
        </>
      ),
    },
    { key: "note", label: "Delivery note", width: 17, get: (sh) => sh.delivery_note || "—" },
    { key: "tracking", label: "Tracking", width: 11, get: (sh) => sh.tracking || "—" },
    {
      key: "act",
      label: "",
      width: 11,
      interactive: false,
      className: "ctr",
      get: () => "",
      title: () => undefined,
      // A reversed shipment carries no device but still carries EVENTS, and
      // `delete_shipment` refuses those — so `deletable` decides the button,
      // never `devices.length`, which would offer a delete the API answers 409 to.
      render: (sh) => (sh.kind === "delivery" && sh.status === "sent" && sh.devices.length > 0 ? (
        <button
          type="button"
          className="btn btn-sm"
          title="Take back a delivery recorded in error"
          onClick={(e) => {
            e.stopPropagation();
            void takeBack(sh);
          }}
        >
          Take back
        </button>
      ) : sh.deletable && sh.status !== "open" ? (
        <button
          type="button"
          className="btn btn-sm"
          title="Delete this shipment"
          onClick={(e) => {
            e.stopPropagation();
            void remove(sh);
          }}
        >
          ×
        </button>
      ) : null),
    },
  ];
  const sent = shipments.filter((s) => s.kind === "delivery" && s.status === "sent").length;
  const boxes = shipments.filter((s) => s.status === "open").length;
  const returns = shipments.filter((s) => s.kind === "return").length;
  const serials = shipments.reduce((a, s) => a + s.devices.length, 0);
  return (
    <FoldSection
      title="Shipments"
      count={shipments.length}
      foldKey={`order:${order.id}:shipments`}
      chips={
        <>
          {boxes ? <StatChip n={boxes} tone="warn" title="Boxes being packed, not sent">open</StatChip> : null}
          {returns ? <StatChip n={returns} tone="warn">returned</StatChip> : null}
          {sent ? <StatChip n={sent} tone="ok">sent</StatChip> : null}
          {serials ? <StatChip n={serials.toLocaleString()}>serials</StatChip> : null}
        </>
      }
    >
      {shipments.length === 0 ? (
        <p className="muted">Nothing shipped yet.</p>
      ) : (
        <DataTable
          rows={shipments}
          rowKey={(sh) => sh.id}
          columns={columns}
          expand={(sh) => <ShipmentSerials sh={sh} />}
        />
      )}
    </FoldSection>
  );
}

/** What one shipment carried, opened under its row. */
function ShipmentSerials({ sh }: { sh: ShipmentRow }) {
  const returned = sh.devices.filter((d) => d.state === "returned").length;
  const disposed = sh.devices.filter((d) => d.state === "disposed").length;
  const replacements = sh.devices.filter((d) => d.replaces_device_id).length;
  return (
    <>
      {sh.devices.length ? (
        <FoldSection
          bare
          title="Serials"
          count={sh.devices.length}
          foldKey={`shipment:${sh.id}:serials`}
          chips={
            <>
              {returned ? <StatChip n={returned} tone="warn">returned</StatChip> : null}
              {disposed ? <StatChip n={disposed} tone="err">disposed</StatChip> : null}
              {replacements ? <StatChip n={replacements}>replacements</StatChip> : null}
            </>
          }
        >
          <div className="serial-cloud">
            {sh.devices.map((d) => (
              <Link
                key={d.device_id}
                className={"pill mono " + (d.state === "returned" ? "warn" : d.state === "disposed" ? "err" : "neutral")}
                to={`/production/devices/${d.device_id}`}
                title={`${d.state}${d.auto ? " · picked FIFO" : ""}${d.replaces_device_id ? " · replacement" : ""}`}
              >
                {d.serial || d.mac}
              </Link>
            ))}
          </div>
        </FoldSection>
      ) : null}
      {sh.notes ? <p className="muted">{sh.notes}</p> : null}
    </>
  );
}
