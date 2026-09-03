/** One customer order: its lines, the invoices that close it, the shipments
 *  that fulfil it, and what it earned once every shipped device — replacements
 *  included — carries its batch's real cost (decision 0003 §9).
 *
 *  The Ship dialog draws devices FIFO from the batches the user ticks (§6);
 *  serials can be pasted instead. Returns, repairs and disposals live on the
 *  device page, because they are events in a device's history.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  addOrderInvoice,
  addOrderLine,
  createShipment,
  deleteOrderInvoice,
  deleteOrderLine,
  deleteShipment,
  errorMessage,
  getOrder,
  getOrderStockOptions,
  isAbortError,
  getProjects,
  updateOrder,
  updateOrderInvoice,
  updateOrderLine,
  type FinishedStockRow,
  type InvoiceIn,
  type OrderInvoiceRow,
  type OrderLineRow,
  type OrderRow,
  type ProjectInfo,
  type ShipmentLineIn,
  type ShipmentRow,
} from "../api";
import { useDialog } from "../components/Dialog";
import { BackLink, ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { amount, plain, usd } from "../format";

const INVOICE_KINDS: OrderInvoiceRow["kind"][] = ["advance", "final", "proforma", "correction"];

export default function OrderDetail() {
  const { id } = useParams();
  const orderId = Number(id);
  const [order, setOrder] = useState<OrderRow | null>(null);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [shipping, setShipping] = useState(false);
  const dialog = useDialog();

  const reload = useCallback(() => {
    const ac = new AbortController();
    getOrder(orderId, ac.signal)
      .then((o) => {
        setOrder(o);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getProjects(ac.signal).then(setProjects).catch(() => setProjects([]));
    return () => ac.abort();
  }, [orderId]);

  useEffect(() => reload(), [reload]);

  const apply = async (work: () => Promise<OrderRow>) => {
    try {
      setOrder(await work());
      setError(null);
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "That did not work" });
    }
  };

  if (error && !order) {
    return (
      <div className="main-solo"><div className="page"><ErrorBanner message={error} /></div></div>
    );
  }
  if (!order) {
    return (
      <div className="main-solo"><div className="page"><Spinner label="Loading order…" /></div></div>
    );
  }
  const cur = order.currency;
  const eco = order.economics;

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <BackLink to="/production/orders">← Orders</BackLink>
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
            className="btn btn-primary btn-sm"
            disabled={order.cancelled}
            onClick={() => setShipping((v) => !v)}
          >
            {shipping ? "Close" : "Ship…"}
          </button>
        </div>
        {error ? <ErrorBanner message={error} /> : null}

        {shipping ? (
          <ShipCard
            order={order}
            onDone={(o) => {
              setOrder(o);
              setShipping(false);
            }}
          />
        ) : null}

        <div className="detail-page">
          <div className="detail-left">
            <LinesCard order={order} projects={projects} apply={apply} />
            <InvoicesCard order={order} apply={apply} />
            <ShipmentsCard order={order} apply={apply} />
          </div>
          <div className="detail-right">
            <div className="card pad">
              <h2 className="card-title">Did this order make money?</h2>
              {eco ? (
                <dl className="kv">
                  <dt>Revenue (net)</dt>
                  <dd title={eco.revenue_basis === "invoices" ? "sum of advance, final and correction invoices" : "no money invoice yet — the order's line totals"}>
                    {amount(eco.revenue_net, eco.currency)}
                    <span className="muted"> · {usd(eco.revenue_usd, 0)}</span>
                    {eco.revenue_basis === "order" ? <span className="muted"> (not invoiced yet)</span> : null}
                  </dd>
                  <dt>Devices shipped</dt>
                  <dd>
                    {(eco.shipped_devices + eco.shipped_unserialized).toLocaleString()}
                    {eco.replacements ? <span className="muted"> · {eco.replacements} replacement{eco.replacements === 1 ? "" : "s"}</span> : null}
                  </dd>
                  <dt>Cost of devices</dt>
                  <dd>{usd(eco.devices_cost_usd, 0)}</dd>
                  <dt>Repairs</dt>
                  <dd>{usd(eco.repair_cost_usd, 0)}</dd>
                  <dt>Margin</dt>
                  <dd className={(eco.margin_usd ?? 0) < 0 ? "err-text" : undefined}>
                    {usd(eco.margin_usd, 0)}
                    {eco.margin_pct != null ? <span className="muted"> · {eco.margin_pct.toFixed(1)}%</span> : null}
                  </dd>
                </dl>
              ) : (
                <Spinner />
              )}
              {eco && eco.uncosted_units ? (
                <div className="banner-warn">
                  {eco.uncosted_units} shipped unit{eco.uncosted_units === 1 ? "" : "s"} carry no batch cost
                  yet — their batch has no priced actuals.
                </div>
              ) : null}
              {eco && eco.unknown_currencies.length ? (
                <div className="banner-warn">
                  No exchange rate stored for {eco.unknown_currencies.join(", ")}; those amounts are
                  not converted. Add it under <Link to="/setup">Setup → Exchange rates</Link>.
                </div>
              ) : null}
              <p className="muted">
                Every shipped device carries the actual per-device cost of the batch it came from,
                replacements included. Revenue converts per invoice at the invoice date.
              </p>
            </div>
            <HeaderCard order={order} apply={apply} />
          </div>
        </div>
      </div>
    </div>
  );
}

function HeaderCard({ order, apply }: { order: OrderRow; apply: (w: () => Promise<OrderRow>) => Promise<void> }) {
  const [ref, setRef] = useState(order.order_ref);
  const [date, setDate] = useState(order.order_date);
  const [notes, setNotes] = useState(order.notes);
  const dialog = useDialog();
  useEffect(() => {
    setRef(order.order_ref);
    setDate(order.order_date);
    setNotes(order.notes);
  }, [order]);
  const dirty = ref !== order.order_ref || date !== order.order_date || notes !== order.notes;
  return (
    <div className="card pad edit-card">
      <h2 className="card-title">Order</h2>
      <div className="edit-grid">
        <label>
          Reference
          <input className="text" value={ref} onChange={(e) => setRef(e.target.value)} />
        </label>
        <label>
          Order date
          <input className="text" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
      </div>
      <label>
        Notes
        <textarea className="note-textarea" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="btn-row">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={!dirty}
          onClick={() => apply(() => updateOrder(order.id, { order_ref: ref, order_date: date, notes }))}
        >
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
      </div>
      <p className="muted">
        Currency {order.currency} · VAT {order.vat_pct}% (printed only; every figure here is net).
      </p>
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

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Products</h2>
        <span className="toolbar-total">{amount(order.total_net, order.currency)} net</span>
        <button type="button" className="btn btn-sm" onClick={() => setAdding((v) => !v)}>
          {adding ? "Close" : "Add a product"}
        </button>
      </div>
      <div className="table-wrap">
        <table className="data data-fixed order-lines-table">
          <thead>
            <tr>
              <th>Product</th>
              <th>Project</th>
              <th className="num">Ordered</th>
              <th className="num">Unit net</th>
              <th className="num">Net total</th>
              <th className="num">Shipped</th>
              <th className="num">Open</th>
              <th className="num">Back</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {order.lines.map((li) => (
              <tr key={li.id}>
                <td className="mono" title={li.product}>{li.product || "—"}</td>
                <td title={li.project}>
                  <Link className="val-link" to={`/projects/${li.project_id}`}>{li.project}</Link>
                  {li.board ? <span className="muted"> {li.board}</span> : null}
                  {li.variant ? <span className="muted"> / {li.variant}</span> : null}
                </td>
                <td className="num">
                  <button type="button" className="val-link" onClick={() => editQty(li)}>
                    {li.qty_ordered.toLocaleString()}
                  </button>
                </td>
                <td className="num">
                  <button type="button" className="val-link" onClick={() => editPrice(li)}>
                    {plain(li.unit_price)}
                  </button>
                </td>
                <td className="num">{plain(li.net_total)}</td>
                <td
                  className="num"
                  title={`${li.qty_shipped_devices} recorded devices + ${li.qty_shipped_unserialized} without a serial${li.qty_replacements ? ` · ${li.qty_replacements} replacement(s) not counted` : ""}`}
                >
                  {li.qty_shipped.toLocaleString()}
                  {li.qty_replacements ? <span className="muted"> +{li.qty_replacements}</span> : null}
                </td>
                <td className={"num" + (li.qty_open ? " warn-text" : "")}>{li.qty_open.toLocaleString()}</td>
                <td className="num" title="devices returned from this line">{li.qty_returned || "—"}</td>
                <td>
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
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {adding ? (
        <div className="edit-grid">
          <label>
            Project
            <select className="text" value={pid} onChange={(e) => setPid(e.target.value)}>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </label>
          <label>
            Product (as invoiced)
            <input className="text" value={product} onChange={(e) => setProduct(e.target.value)} />
          </label>
          <label>
            Quantity
            <input className="text num" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} />
          </label>
          <label>
            Net unit price
            <input className="text num" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
          </label>
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
        </div>
      ) : null}
    </div>
  );
}

function InvoicesCard({ order, apply }: { order: OrderRow; apply: (w: () => Promise<OrderRow>) => Promise<void> }) {
  const dialog = useDialog();
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState<OrderInvoiceRow["kind"]>(order.invoices?.length ? "final" : "advance");
  const [number, setNumber] = useState("");
  const [issue, setIssue] = useState(new Date().toISOString().slice(0, 10));
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
      initial: inv.paid_at || new Date().toISOString().slice(0, 10),
    });
    if (v == null) return;
    await apply(() => updateOrderInvoice(inv.id, { paid_at: v.trim() }));
  };

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
        <div className="table-wrap">
          <table className="data data-fixed order-invoices-table">
            <thead>
              <tr>
                <th>Kind</th>
                <th>Number</th>
                <th>Issued</th>
                <th>Due</th>
                <th className="num">Net</th>
                <th>Paid</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => {
                const overdue = !inv.paid_at && inv.due_date && inv.due_date < new Date().toISOString().slice(0, 10) && inv.kind !== "proforma";
                return (
                  <tr key={inv.id} className={inv.kind === "proforma" ? "dim" : undefined}>
                    <td>{inv.kind}</td>
                    <td className="mono" title={inv.number}>{inv.number}</td>
                    <td className="mono">{inv.issue_date || "—"}</td>
                    <td className={"mono" + (overdue ? " err-text" : "")} title={overdue ? "overdue" : undefined}>{inv.due_date || "—"}</td>
                    <td className="num">{amount(inv.net_amount, inv.currency)}</td>
                    <td>
                      {inv.kind === "proforma" ? (
                        <span className="muted">n/a</span>
                      ) : inv.paid_at ? (
                        <button type="button" className="val-link mono" onClick={() => markPaid(inv)}>{inv.paid_at}</button>
                      ) : (
                        <button type="button" className="btn btn-sm" onClick={() => markPaid(inv)}>mark paid</button>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={async () => {
                          if (await dialog.confirm(`Delete invoice ${inv.number} from the order?`, { tone: "danger" })) {
                            await apply(() => deleteOrderInvoice(inv.id));
                          }
                        }}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {adding ? (
        <div className="edit-grid">
          <label>
            Kind
            <select className="text" value={kind} onChange={(e) => setKind(e.target.value as OrderInvoiceRow["kind"])}>
              {INVOICE_KINDS.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </label>
          <label>
            Number
            <input className="text" value={number} placeholder="ZAL 00001/03/2026" onChange={(e) => setNumber(e.target.value)} />
          </label>
          <label>
            Issued
            <input className="text" value={issue} onChange={(e) => setIssue(e.target.value)} />
          </label>
          <label>
            Due (blank = issue + terms)
            <input className="text" value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
          <label>
            Net amount ({order.currency})
            <input
              className="text num"
              inputMode="decimal"
              value={net}
              placeholder={kind === "advance" && order.total_net ? plain(order.total_net * 0.6) : ""}
              onChange={(e) => setNet(e.target.value)}
            />
          </label>
          <label>
            Paid on (optional)
            <input className="text" value={paid} onChange={(e) => setPaid(e.target.value)} />
          </label>
          <div className="btn-row">
            <button type="button" className="btn btn-primary btn-sm" onClick={submit}>Add</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ShipmentsCard({ order, apply }: { order: OrderRow; apply: (w: () => Promise<OrderRow>) => Promise<void> }) {
  const dialog = useDialog();
  const [open, setOpen] = useState<number | null>(null);
  const shipments = order.shipments ?? [];
  const lineName = (id: number) => {
    const li = order.lines.find((l) => l.id === id);
    return li ? li.product || li.project : `line ${id}`;
  };
  return (
    <div className="card pad">
      <h2 className="card-title">Shipments</h2>
      {shipments.length === 0 ? (
        <p className="muted">Nothing shipped yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="data data-fixed order-shipments-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Kind</th>
                <th>Content</th>
                <th>Delivery note</th>
                <th>Tracking</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shipments.map((sh) => (
                <ShipmentRows
                  key={sh.id}
                  sh={sh}
                  open={open === sh.id}
                  onToggle={() => setOpen((v) => (v === sh.id ? null : sh.id))}
                  lineName={lineName}
                  onDelete={async () => {
                    if (await dialog.confirm("Delete this shipment? Only possible while no device is recorded on it.", { tone: "danger" })) {
                      await apply(() => deleteShipment(sh.id));
                    }
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ShipmentRows({
  sh,
  open,
  onToggle,
  lineName,
  onDelete,
}: {
  sh: ShipmentRow;
  open: boolean;
  onToggle: () => void;
  lineName: (id: number) => string;
  onDelete: () => void;
}) {
  const content = Object.entries(sh.per_line)
    .map(([lid, n]) => `${n} × ${lineName(Number(lid))}`)
    .join(", ");
  return (
    <>
      <tr onClick={onToggle} className="clickable">
        <td className="mono">{sh.shipped_at || "—"}</td>
        <td>{sh.kind === "return" ? <span className="pill warn">return</span> : "delivery"}</td>
        <td title={content}>
          {content}
          {sh.devices.length ? <span className="muted"> · {sh.devices.length} serial{sh.devices.length === 1 ? "" : "s"}</span> : null}
        </td>
        <td title={sh.delivery_note}>{sh.delivery_note || "—"}</td>
        <td title={sh.tracking}>{sh.tracking || "—"}</td>
        <td>
          {sh.devices.length === 0 ? (
            <button
              type="button"
              className="btn btn-sm"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
            >
              ×
            </button>
          ) : null}
        </td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={6} className="expand-cell">
            {sh.unserialized.filter((u) => u.qty_unserialized > 0).map((u, i) => (
              <div key={i} className="muted">
                {u.qty_unserialized} × {lineName(u.order_line_id)} without a serial
                {u.source_run_id ? <> from <Link className="val-link" to={`/runs/${u.source_run_id}`}>batch #{u.source_run_id}</Link></> : null}
              </div>
            ))}
            {sh.devices.length ? (
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
            ) : null}
            {sh.notes ? <p className="muted">{sh.notes}</p> : null}
          </td>
        </tr>
      ) : null}
    </>
  );
}

/** The Ship dialog: per open line, a quantity to draw FIFO from ticked
 *  batches, or pasted serials, or (legacy batches) units without a serial. */
function ShipCard({ order, onDone }: { order: OrderRow; onDone: (o: OrderRow) => void }) {
  const [options, setOptions] = useState<Record<string, FinishedStockRow[]> | null>(null);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("");
  const [tracking, setTracking] = useState("");
  const [rows, setRows] = useState<Record<number, { qty: string; runs: Set<number>; serials: string; unser: string; unserRun: string }>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getOrderStockOptions(order.id, ac.signal)
      .then((o) => {
        setOptions(o);
        const init: typeof rows = {};
        for (const li of order.lines) {
          const opts = o[String(li.id)] ?? [];
          init[li.id] = {
            qty: li.qty_open ? String(li.qty_open) : "",
            runs: new Set(opts.filter((r) => r.devices_in_stock > 0).map((r) => r.run_id)),
            serials: "",
            unser: "",
            unserRun: String(opts.find((r) => r.legacy_stock > 0)?.run_id ?? ""),
          };
        }
        setRows(init);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order.id]);

  const submit = async () => {
    const lines: ShipmentLineIn[] = [];
    for (const li of order.lines) {
      const r = rows[li.id];
      if (!r) continue;
      const serials = r.serials.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
      const qty = Number(r.qty || 0);
      const unser = Number(r.unser || 0);
      if (serials.length) {
        // serials are resolved server-side by device id only; look them up here
        const ids = serials.map((s) => Number(s)).filter((n) => Number.isFinite(n) && n > 0);
        if (ids.length !== serials.length) {
          setError("Paste device IDs (numbers) — serial lookup is on the device list; open a device to see its ID.");
          return;
        }
        lines.push({ order_line_id: li.id, device_ids: ids, note: "" });
      } else if (qty > 0) {
        lines.push({ order_line_id: li.id, qty, run_ids: [...r.runs] });
      }
      if (unser > 0) {
        lines.push({ order_line_id: li.id, qty_unserialized: unser, source_run_id: Number(r.unserRun) || null });
      }
    }
    if (!lines.length) {
      setError("Nothing to ship: give a quantity, serials, or units without a serial on at least one line.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onDone(await createShipment(order.id, { shipped_at: date.trim(), delivery_note: note.trim(), tracking: tracking.trim(), lines }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const set = (lid: number, patch: Partial<(typeof rows)[number]>) =>
    setRows((rs) => ({ ...rs, [lid]: { ...rs[lid], ...patch } }));

  return (
    <div className="card pad edit-card">
      <h2 className="card-title">Ship</h2>
      <p className="card-subtitle">
        Devices are drawn oldest-first from the batches you tick. Untick a batch to keep it back.
        A batch from before device records offers units “without a serial” instead.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      <div className="edit-grid">
        <label>
          Shipped on
          <input className="text" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          Delivery note
          <input className="text" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <label>
          Tracking
          <input className="text" value={tracking} onChange={(e) => setTracking(e.target.value)} />
        </label>
      </div>
      {!options ? (
        <Spinner label="Counting stock…" />
      ) : (
        order.lines.map((li) => {
          const opts = options[String(li.id)] ?? [];
          const r = rows[li.id];
          if (!r) return null;
          const available = opts.filter((o) => r.runs.has(o.run_id)).reduce((s, o) => s + o.devices_in_stock, 0);
          return (
            <div key={li.id} className="ship-line">
              <h3 className="card-subtitle">
                {li.product || li.project} — {li.qty_open.toLocaleString()} open of {li.qty_ordered.toLocaleString()}
              </h3>
              {opts.length === 0 ? (
                <p className="muted">No stock in {li.project}.</p>
              ) : (
                <div className="table-wrap">
                  <table className="data data-fixed ship-batches-table">
                    <thead>
                      <tr>
                        <th />
                        <th>Batch</th>
                        <th className="num">Devices in stock</th>
                        <th className="num">Without a serial</th>
                        <th className="num">Unit cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {opts.map((o) => (
                        <tr key={o.run_id}>
                          <td>
                            <input
                              type="checkbox"
                              disabled={o.devices_in_stock === 0}
                              checked={r.runs.has(o.run_id)}
                              onChange={(e) => {
                                const next = new Set(r.runs);
                                if (e.target.checked) next.add(o.run_id);
                                else next.delete(o.run_id);
                                set(li.id, { runs: next });
                              }}
                            />
                          </td>
                          <td title={o.label}>{o.label} <span className="muted">{o.run_date}</span></td>
                          <td className="num">{o.devices_in_stock.toLocaleString()}</td>
                          <td className="num">{o.legacy_stock.toLocaleString()}</td>
                          <td className="num">{usd(o.unit_cost_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="edit-grid">
                <label>
                  Quantity (FIFO, {available.toLocaleString()} available)
                  <input className="text num" inputMode="numeric" value={r.qty} onChange={(e) => set(li.id, { qty: e.target.value })} />
                </label>
                <label>
                  …or device IDs, pasted
                  <input className="text mono" value={r.serials} placeholder="1234 1235 1236" onChange={(e) => set(li.id, { serials: e.target.value })} />
                </label>
                <label>
                  Units without a serial
                  <input className="text num" inputMode="numeric" value={r.unser} onChange={(e) => set(li.id, { unser: e.target.value })} />
                </label>
                <label>
                  …from batch
                  <select className="text" value={r.unserRun} onChange={(e) => set(li.id, { unserRun: e.target.value })}>
                    <option value="">no batch (built before any run; uncosted)</option>
                    {opts.filter((o) => o.legacy_stock > 0).map((o) => (
                      <option key={o.run_id} value={o.run_id}>{o.label} ({o.legacy_stock})</option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          );
        })
      )}
      <div className="btn-row">
        <button type="button" className="btn btn-primary" disabled={busy || !options} onClick={submit}>
          {busy ? "Shipping…" : "Record shipment"}
        </button>
      </div>
    </div>
  );
}
