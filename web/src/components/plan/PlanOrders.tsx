/** The plan's orders (decision 0107 items 2 to 4): draft sales orders the plan
 *  owns, each with one or more lines and a delivery schedule per line.
 *
 *  A draft order's date IS the move: change it here and every date that
 *  follows it moves on the next read. A confirmed order keeps its date, because
 *  the customer placed it; its deliveries can still be planned. */
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  addPlanOrder,
  deletePlanOrder,
  setLineDeliveries,
  updatePlanOrder,
  type PlanDeliveryIn,
  type PlanFull,
  type PlanLagUnit,
  type PlanOrder,
  type PlanOrderLine,
  type ProjectInfo as ApiProject,
} from "../../api";
import DataTable from "../DataTable";
import { useDialog } from "../Dialog";
import Field, { FieldGrid } from "../Field";
import FoldSection, { StatChip } from "../FoldSection";
import { useModal } from "../modal";
import NumberInput from "../NumberInput";
import { StatusPill } from "../Ui";
import { amount, plural } from "../../format";
import { LAG_UNITS, RefsPicker } from "./NodeEditor";
import { fitColumns, refOptions, units, useNarrow, WEEKDAY_NAMES, type Apply, type PlanColumn } from "./planUtil";

// ------------------------------------------------------------------ deliveries

/** One delivery row of the form. `advance` follows the order's advance, `fixed`
 *  is a day, `other` follows dates the person chose on the date dialog. */
interface DeliveryRow {
  qty: number;
  how: "advance" | "fixed" | "other";
  day: string;
  lag: number;
  lag_unit: PlanLagUnit;
  snap: number | null;
  after: string[];
  source: string;
  source_text: string;
  done_on: string;
}

function newDelivery(full: PlanFull, qty: number): DeliveryRow {
  return {
    qty,
    how: "advance",
    day: "",
    lag: full.plan.min_lead_months || 0,
    lag_unit: "months",
    snap: full.plan.delivery_weekday,
    after: [],
    source: "",
    source_text: "",
    done_on: "",
  };
}

function rowsOf(full: PlanFull, o: PlanOrder, line: PlanOrderLine): DeliveryRow[] {
  const nodes = new Map(full.nodes.map((n) => [n.id, n]));
  return line.deliveries.map((d) => {
    const n = d.node_id ? nodes.get(d.node_id) : undefined;
    const after = n?.after ?? [];
    const how: DeliveryRow["how"] =
      n?.mode === "fixed" ? "fixed" : after.length === 1 && after[0] === `advance:${o.id}` ? "advance" : "other";
    return {
      qty: d.qty,
      how,
      day: n?.mode === "fixed" ? n.day : d.day,
      lag: n?.lag ?? 0,
      lag_unit: n?.lag_unit ?? "days",
      snap: n?.snap_weekday ?? null,
      after,
      source: n?.source ?? "",
      source_text: n?.source_text ?? "",
      done_on: n?.done_on ?? "",
    };
  });
}

function bodyOf(r: DeliveryRow, orderId: number | null): PlanDeliveryIn {
  const base = {
    qty: r.qty,
    snap_weekday: r.snap,
    ...(r.source ? { source: r.source as PlanDeliveryIn["source"] } : {}),
    ...(r.source_text ? { source_text: r.source_text } : {}),
    ...(r.done_on ? { done_on: r.done_on } : {}),
  };
  if (r.how === "fixed") return { ...base, mode: "fixed", day: r.day };
  if (r.how === "advance")
    return { ...base, mode: "after", lag: r.lag, lag_unit: r.lag_unit, ...(orderId ? { after: [`advance:${orderId}`] } : {}) };
  return { ...base, mode: "after", after: r.after, lag: r.lag, lag_unit: r.lag_unit };
}

function deliveryProblem(rows: DeliveryRow[], qty: number): string {
  if (rows.some((r) => !(r.qty >= 1))) return "Each delivery needs a quantity.";
  if (rows.some((r) => r.how === "fixed" && !r.day)) return "A fixed delivery needs a day.";
  if (rows.some((r) => r.how === "other" && !r.after.length)) return "A delivery that follows other dates needs one.";
  const sum = rows.reduce((a, r) => a + r.qty, 0);
  if (rows.length && sum !== qty) return `${MISMATCH}${units(sum)}, the line orders ${units(qty)}.`;
  return "";
}

const MISMATCH = "The deliveries add up to ";
/** A schedule that does not add up to the line is saved, and the plan flags it:
 *  the customer may not have split the last units yet. Every other problem
 *  stops the save. */
const blocks = (problem: string) => !!problem && !problem.startsWith(MISMATCH);

/** The rows of a delivery schedule, as a small form: one line per delivery. */
function DeliveryRows({ full, rows, onChange, qty, allowOther }: {
  full: PlanFull;
  rows: DeliveryRow[];
  onChange: (rows: DeliveryRow[]) => void;
  qty: number;
  /** an existing order: a delivery may follow any date of the plan */
  allowOther: boolean;
}) {
  const set = (i: number, p: Partial<DeliveryRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const left = qty - rows.reduce((a, r) => a + r.qty, 0);
  return (
    <div className="plan-dels">
      {rows.map((r, i) => (
        <div key={i} className="plan-del-row">
          <Field label="Units">
            <NumberInput className="text" value={r.qty} min={1} onChange={(v) => set(i, { qty: Math.round(v) })} />
          </Field>
          <Field label="Delivered">
            <select className="text" value={r.how} onChange={(e) => set(i, { how: e.target.value as DeliveryRow["how"] })}>
              <option value="advance">after the advance</option>
              <option value="fixed">on a fixed day</option>
              {allowOther || r.how === "other" ? <option value="other">after other dates</option> : null}
            </select>
          </Field>
          {r.how === "fixed" ? (
            <Field label="Day">
              <input className="text" type="date" value={r.day} onChange={(e) => set(i, { day: e.target.value })} />
            </Field>
          ) : (
            <>
              <Field label="Lag">
                <NumberInput className="text" value={r.lag} onChange={(v) => set(i, { lag: Math.round(v) })}
                  onEmpty={() => set(i, { lag: 0 })} />
              </Field>
              <Field label="Unit">
                <select className="text" value={r.lag_unit} onChange={(e) => set(i, { lag_unit: e.target.value as PlanLagUnit })}>
                  {LAG_UNITS.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
                </select>
              </Field>
            </>
          )}
          {r.how === "fixed" ? null : (
            <Field label="Then the next">
              <select className="text" value={r.snap ?? ""}
                onChange={(e) => set(i, { snap: e.target.value === "" ? null : Number(e.target.value) })}>
                <option value="">no weekday</option>
                {WEEKDAY_NAMES.map((w, k) => <option key={w} value={k}>{w}</option>)}
              </select>
            </Field>
          )}
          <button type="button" className="row-del" title="Remove this delivery" aria-label="Remove this delivery"
            onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            &#x2715;
          </button>
          {r.how === "other" ? (
            <div className="plan-del-refs">
              <RefsPicker value={r.after} onChange={(after) => set(i, { after })} options={refOptions(full)} />
            </div>
          ) : null}
        </div>
      ))}
      <div className="btn-row">
        <button type="button" className="btn btn-sm"
          onClick={() => onChange([...rows, newDelivery(full, Math.max(left, 1))])}>
          Add a delivery
        </button>
        {left !== 0 && rows.length ? (
          <StatChip tone="warn">{left > 0 ? `${units(left)} not scheduled` : `${units(-left)} too many`}</StatChip>
        ) : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ new order

export function AddOrderDialog({ full, projects, onClose, apply }: {
  full: PlanFull;
  /** every project; the plan's own designs come first */
  projects: ApiProject[];
  onClose: () => void;
  apply: Apply;
}) {
  const modal = useModal(onClose);
  const designs = full.plan.projects;
  const [key, setKey] = useState("");
  const [orderDate, setOrderDate] = useState("");
  const [advanceDue, setAdvanceDue] = useState("");
  const [projectId, setProjectId] = useState<number | null>(designs[0]?.project_id ?? null);
  const [product, setProduct] = useState("");
  const [qty, setQty] = useState(100);
  const [price, setPrice] = useState<number | null>(null);
  const [rows, setRows] = useState<DeliveryRow[]>(() => [newDelivery(full, 100)]);
  const [busy, setBusy] = useState(false);
  const problem = !orderDate
    ? "Choose the order date."
    : projectId == null
      ? "Choose the project."
      : !(qty >= 1)
        ? "Enter the quantity."
        : deliveryProblem(rows, qty);
  const save = async () => {
    if (projectId == null) return;
    setBusy(true);
    const ok = await apply(`the order ${key || orderDate}`, () =>
      addPlanOrder(full.plan.id, {
        plan_key: key.trim(),
        order_date: orderDate,
        ...(advanceDue ? { advance_due: advanceDue } : {}),
        lines: [{
          project_id: projectId,
          product: product.trim(),
          qty_ordered: qty,
          unit_price: price ?? 0,
          deliveries: rows.map((r) => bodyOf(r, null)),
        }],
      }),
    );
    setBusy(false);
    if (ok) onClose();
  };
  const others = projects.filter((p) => !designs.some((d) => d.project_id === p.id));
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">Add a draft order</h2>
        <p className="muted dim">
          A draft order counts in no demand, revenue or invoice register until the customer places it.
          A delivery after the advance moves when the order date moves.
        </p>
        <FieldGrid>
          <Field label="Key in the plan" hint="A short name, e.g. V3-4.">
            <input className="text" value={key} maxLength={40} onChange={(e) => setKey(e.target.value)} />
          </Field>
          <Field label="Order date">
            <input className="text" type="date" value={orderDate} onChange={(e) => setOrderDate(e.target.value)} />
          </Field>
          <Field label="Advance due" hint={`Empty: the order date plus ${full.plan.advance_days} days.`}>
            <input className="text" type="date" value={advanceDue} onChange={(e) => setAdvanceDue(e.target.value)} />
          </Field>
          <Field label="Project">
            <select className="text" value={projectId ?? ""} onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Choose…</option>
              {designs.map((d) => <option key={d.project_id} value={d.project_id}>{d.project}</option>)}
              {others.length ? (
                <optgroup label="Not in the plan's designs">
                  {others.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </optgroup>
              ) : null}
            </select>
          </Field>
          <Field label="Product, as invoiced">
            <input className="text" value={product} onChange={(e) => setProduct(e.target.value)} />
          </Field>
          <Field label="Units">
            <NumberInput className="text" value={qty} min={1} onChange={(v) => {
              const q = Math.round(v);
              setQty(q);
              if (rows.length === 1) setRows([{ ...rows[0], qty: q }]);
            }} />
          </Field>
          <Field label={`Net unit price (${full.plan.currency})`}>
            <NumberInput className="text" value={price} onChange={setPrice} onEmpty={() => setPrice(null)} />
          </Field>
        </FieldGrid>
        <h3 className="plan-sub">Deliveries</h3>
        <DeliveryRows full={full} rows={rows} onChange={setRows} qty={qty} allowOther={false} />
        <div className="btn-row modal-actions">
          {problem ? <StatChip tone="warn">{problem}</StatChip> : null}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || blocks(problem)} onClick={() => void save()}>
            Add the order
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ one order

/** One order of the plan: its key, its date and its advance. The deliveries of
 *  each line open their own dialog. */
export function OrderDialog({ full, orderId, onClose, apply }: {
  full: PlanFull;
  orderId: number;
  onClose: () => void;
  apply: Apply;
}) {
  const modal = useModal(onClose);
  const dialog = useDialog();
  const o = full.schedule.orders.find((x) => x.id === orderId);
  const [key, setKey] = useState(o?.key ?? "");
  const [orderDate, setOrderDate] = useState(o?.order_date ?? "");
  const [advanceDue, setAdvanceDue] = useState(o?.advance_due_override ?? "");
  const [busy, setBusy] = useState(false);
  const [lineId, setLineId] = useState<number | null>(null);
  if (!o) return null;
  const dirty = key.trim() !== o.key || orderDate !== o.order_date || advanceDue !== o.advance_due_override;
  const save = async () => {
    const body: { plan_key?: string; order_date?: string; advance_due?: string } = {};
    if (key.trim() !== o.key) body.plan_key = key.trim();
    if (orderDate !== o.order_date) body.order_date = orderDate;
    if (advanceDue !== o.advance_due_override) body.advance_due = advanceDue;
    setBusy(true);
    const ok = await apply(`the order ${o.key}`, () => updatePlanOrder(full.plan.id, o.id, body));
    setBusy(false);
    if (ok) onClose();
  };
  const remove = async () => {
    const ok = await dialog.confirm(
      `Delete the draft order ${o.key}? Its ${o.lines.reduce((a, l) => a + l.deliveries.length, 0)} deliveries go with it. `
      + "History → Write batches can undo it.",
      { title: "Delete draft order", confirmLabel: "Delete", tone: "danger" },
    );
    if (!ok) return;
    if (await apply(`the deletion of ${o.key}`, () => deletePlanOrder(full.plan.id, o.id))) onClose();
  };
  const line = o.lines.find((l) => l.id === lineId);
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">
          Order {o.key} <StatusPill status={o.draft ? "draft" : o.status} />
        </h2>
        <p className="muted dim">
          {o.draft
            ? "Move the order date and every date that follows it moves. A date fixed by a supplier or the customer stays."
            : "The customer placed this order, so its date is fixed. Its deliveries can still change."}
        </p>
        {o.flags.length ? (
          <div className="banner-warn">{o.flags.map((f) => f.text).join(" ")}</div>
        ) : null}
        <FieldGrid>
          <Field label="Key in the plan">
            <input className="text" value={key} maxLength={40} onChange={(e) => setKey(e.target.value)} />
          </Field>
          <Field label="Order date" hint={o.draft ? undefined : "Fixed: the customer placed the order."}>
            <input className="text" type="date" value={orderDate} disabled={!o.draft}
              onChange={(e) => setOrderDate(e.target.value)} />
          </Field>
          <Field label="Advance due" hint={advanceDue ? "Set by hand." : `Computed: ${o.advance_due || "—"}. Set a day to override it.`}>
            <input className="text" type="date" value={advanceDue} onChange={(e) => setAdvanceDue(e.target.value)} />
          </Field>
        </FieldGrid>
        <dl className="kv">
          <dt>Net</dt>
          <dd>{amount(o.net, full.plan.currency)}</dd>
          <dt>Advance</dt>
          <dd>
            {amount(o.advance_gross, full.plan.currency)} gross,{" "}
            {o.advance_state === "paid" ? `paid on ${o.advance_paid_on}` : o.advance_state === "late"
              ? `late: it was due on ${o.advance_due}` : `due ${o.advance_due || "—"}`}
          </dd>
          <dt>Final invoice</dt>
          <dd>{amount(o.final_gross, full.plan.currency)} gross, due {o.final_due || "—"}</dd>
          <dt>Deliveries</dt>
          <dd>{o.first_delivery ? `${o.first_delivery} to ${o.last_delivery}` : "none planned"}</dd>
        </dl>
        <h3 className="plan-sub">Lines</h3>
        {o.lines.map((l) => (
          <div key={l.id} className="plan-line">
            <span>{l.product || l.project} · {units(l.qty)} × {amount(l.unit_price, full.plan.currency)}</span>
            <span className="muted">{plural(l.deliveries.length, "delivery", "deliveries")}{l.mismatch ? `, ${units(l.planned_qty)} planned` : ""}</span>
            <button type="button" className="btn btn-sm" onClick={() => setLineId(l.id)}>Deliveries…</button>
          </div>
        ))}
        <div className="btn-row modal-actions">
          <Link className="comp-link" to={`/sales/orders/${o.id}`}>Open the order page</Link>
          {o.draft ? <button type="button" className="btn btn-danger" onClick={() => void remove()}>Delete…</button> : null}
          <button type="button" className="btn" onClick={onClose}>Close</button>
          <button type="button" className="btn btn-primary" disabled={busy || !dirty || !orderDate} onClick={() => void save()}>
            Save
          </button>
        </div>
      </div>
      {line ? (
        <DeliveriesDialog full={full} order={o} line={line} onClose={() => setLineId(null)} apply={apply} />
      ) : null}
    </div>
  );
}

function DeliveriesDialog({ full, order, line, onClose, apply }: {
  full: PlanFull;
  order: PlanOrder;
  line: PlanOrderLine;
  onClose: () => void;
  apply: Apply;
}) {
  const modal = useModal(onClose);
  const [rows, setRows] = useState<DeliveryRow[]>(() => rowsOf(full, order, line));
  const [busy, setBusy] = useState(false);
  const problem = deliveryProblem(rows, line.qty);
  const save = async () => {
    setBusy(true);
    const ok = await apply(`the deliveries of ${order.key}`, () =>
      setLineDeliveries(line.id, rows.map((r) => bodyOf(r, order.id))));
    setBusy(false);
    if (ok) onClose();
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">Deliveries of {order.key}: {line.product || line.project}</h2>
        <p className="muted dim">
          {units(line.qty)} units ordered. A delivery after the advance moves with the order date and
          with a late payment. A fixed delivery never moves by itself.
        </p>
        <DeliveryRows full={full} rows={rows} onChange={setRows} qty={line.qty} allowOther />
        <div className="btn-row modal-actions">
          {problem ? <StatChip tone="warn">{problem}</StatChip> : null}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || blocks(problem)}
            onClick={() => void save()}>
            Save the deliveries
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the card

export function OrdersCard({ full, projects, apply, onOpen }: {
  full: PlanFull;
  projects: ApiProject[];
  apply: Apply;
  onOpen: (orderId: number) => void;
}) {
  const [adding, setAdding] = useState(false);
  const narrow = useNarrow();
  const orders = full.schedule.orders;
  const cur = full.plan.currency;
  const flagged = orders.filter((o) => o.flags.length).length;
  const cols: PlanColumn<PlanOrder>[] = [
    { key: "key", label: "Key", width: 12, narrow: 40, get: (o) => o.key, className: "mono" },
    { key: "date", label: "Order date", width: "104px", narrow: "104px", get: (o) => o.order_date, className: "mono" },
    { key: "advance", label: "Advance due", width: "104px", get: (o) => o.advance_due, className: "mono" },
    { key: "product", label: "Product", width: 22, get: (o) => o.lines.map((l) => l.product || l.project).join(", ") },
    { key: "qty", label: "Units", width: 9, numeric: true, get: (o) => o.lines.reduce((a, l) => a + l.qty, 0) },
    { key: "net", label: `Net ${cur}`, width: 14, numeric: true, get: (o) => o.net,
      render: (o) => o.net.toLocaleString(undefined, { maximumFractionDigits: 0 }) },
    { key: "deliveries", label: "Deliveries", width: 29,
      get: (o) => (o.first_delivery ? `${o.first_delivery} to ${o.last_delivery}` : "none") },
    { key: "state", label: "State", width: 14, narrow: 60, get: (o) => (o.flags.length ? "problem" : o.draft ? "draft" : o.status),
      render: (o) => o.flags.length
        ? <span className="pill err" title={o.flags.map((f) => f.text).join(" ")}>{o.flags.length} {o.flags.length === 1 ? "problem" : "problems"}</span>
        : <StatusPill status={o.draft ? "draft" : o.status} /> },
  ];
  return (
    <FoldSection
      title="Orders"
      count={orders.length}
      foldKey={`plan-${full.plan.id}-orders`}
      chips={flagged ? <StatChip n={flagged} tone="err">with problems</StatChip> : null}
      actions={<button type="button" className="btn btn-sm btn-primary" onClick={() => setAdding(true)}>Add order…</button>}
    >
      <p className="muted dim">Click an order to move its date, change its advance or plan its deliveries.</p>
      <DataTable columns={fitColumns(cols, narrow)} rows={orders} rowKey={(o) => o.id} onRowClick={(o) => onOpen(o.id)}
        empty="No orders yet. Add the first one." />
      {adding ? <AddOrderDialog full={full} projects={projects} onClose={() => setAdding(false)} apply={apply} /> : null}
    </FoldSection>
  );
}
