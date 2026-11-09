/** One purchase order (decision 0107 item 17): what we asked a supplier for,
 *  its lines and its dates.
 *
 *  A plan's order has its order and arrival days computed by the plan, so the
 *  page prints them and never asks for them. Its own dates are the facts:
 *  ordered on, expected on, received on. A plan never rewrites a draft: when the
 *  plan's proposal changed, the page says so and offers the new quantity, and
 *  the person takes it or deletes the draft. An ordered purchase is the
 *  supplier's, so its lines no longer change.
 *
 *  Marking it received records the day only. It moves no stock: the stock comes
 *  with the supplier's document on Finance → Purchase invoices, which this page
 *  can link.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  deletePurchaseOrder,
  errorMessage,
  getInvoiceRegister,
  getPlan,
  getPurchaseOrder,
  getSuppliers,
  updatePurchaseOrder,
  type PlanPoLine,
  type PurchaseOrderRow,
} from "../api";
import AutoTextarea from "../components/AutoTextarea";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import Field, { CheckField, FieldGrid } from "../components/Field";
import { useModal } from "../components/modal";
import PageShell, { PageLoading } from "../components/PageShell";
import PurchaseLinesEditor, { blankLine, draftsOf, linesBody, type PurchaseLineDraft } from "../components/PurchaseLinesEditor";
import RowChangesCard from "../components/RowChangesCard";
import { BackLink, ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { useLoad } from "../components/useLoad";
import { amount, localWhen, plain, plural, price, today } from "../format";

export default function PurchaseOrderDetail() {
  const { id } = useParams();
  const poId = Number(id);
  const { data: po, setData: setPo, error, setError } = useLoad(
    (signal) => getPurchaseOrder(poId, signal), [poId], { keep: true },
  );
  const planId = po?.plan_id ?? null;
  // The plan says whether a draft is out of date, and what it now needs.
  const plan = useLoad((signal) => getPlan(planId as number, signal), [planId], { enabled: planId != null, keep: true });
  const planRow = plan.data?.schedule.purchase_orders.find((x) => x.id === poId) ?? null;
  const dialog = useDialog();
  const navigate = useNavigate();
  const [editingLines, setEditingLines] = useState(false);
  const [linking, setLinking] = useState(false);

  const apply = async (work: () => Promise<PurchaseOrderRow>, title = "That did not work") => {
    try {
      setPo(await work());
      setError(null);
      if (planId != null) void plan.reload();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title });
    }
  };

  if (!po) return <PageLoading error={error} label="Loading purchase order…" />;

  const markDay = async (status: "ordered" | "received") => {
    const v = await dialog.prompt(
      status === "ordered" ? "Ordered on (YYYY-MM-DD):" : "Received on (YYYY-MM-DD):",
      { title: status === "ordered" ? "Mark ordered" : "Mark received", initial: today(), confirmLabel: "Save" },
    );
    if (v == null) return;
    await apply(() => updatePurchaseOrder(po.id, { status, status_day: v.trim() }));
  };
  const cancel = async () => {
    const ok = await dialog.confirm(
      `Cancel the purchase order to ${po.supplier}? Nothing is deleted. A plan stops counting it as supply.`,
      { title: "Cancel purchase order", confirmLabel: "Cancel the order", cancelLabel: "Keep it", tone: "danger" },
    );
    if (ok) await apply(() => updatePurchaseOrder(po.id, { status: "cancelled" }));
  };
  const remove = async () => {
    const ok = await dialog.confirm(
      `Delete the ${po.status} purchase order to ${po.supplier}${po.reference ? ` (${po.reference})` : ""} with its ` +
        `${plural(po.lines.length, "line")}?${po.plan_id ? " Its dates leave the plan too." : ""}`,
      { title: "Delete purchase order", confirmLabel: "Delete", tone: "danger" },
    );
    if (!ok) return;
    try {
      await deletePurchaseOrder(po.id);
      navigate("/stock/purchase-orders");
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not delete the purchase order" });
    }
  };
  const takeProposal = () => apply(() => updatePurchaseOrder(po.id, { take_proposal: true }), "The plan's quantity was not taken");

  const draft = po.status === "draft";
  const outOfDate = draft && planRow?.out_of_date ? planRow : null;

  return (
    <PageShell>
      <div className="toolbar">
        <BackLink to="/stock/purchase-orders">← Purchase orders</BackLink>
        <h1>
          {po.supplier}
          {po.reference ? <span className="mono"> · {po.reference}</span> : null}
        </h1>
        <StatusPill status={po.status} />
        <span className="toolbar-total">
          #{po.id} · {plural(po.lines.length, "line")} · {amount(po.amount, po.currency)}
        </span>
        {draft ? (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => void markDay("ordered")}>Mark ordered…</button>
        ) : null}
        {po.status === "ordered" ? (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => void markDay("received")}>Mark received…</button>
        ) : null}
        {draft || po.status === "ordered" ? (
          <button type="button" className="btn btn-sm btn-danger" onClick={() => void cancel()}>Cancel…</button>
        ) : null}
        {po.status === "cancelled" ? (
          <button type="button" className="btn btn-sm" onClick={() => void apply(() => updatePurchaseOrder(po.id, { status: "draft" }))}>
            Back to draft
          </button>
        ) : null}
        {draft || po.status === "cancelled" ? (
          <button type="button" className="btn btn-sm btn-danger" onClick={() => void remove()}>Delete…</button>
        ) : null}
      </div>
      <ErrorBanner message={error} />
      <ErrorBanner message={plan.error ? `The plan did not load: ${plan.error}` : null} />

      {outOfDate ? (
        <div className="banner-warn">
          The plan changed since this draft was made. {outOfDate.out_of_date}{" "}
          {(outOfDate.suggested_qty ?? 0) > 0 ? (
            <>
              <button type="button" className="btn btn-sm" onClick={() => void takeProposal()}>
                Take the plan&apos;s quantity: {plain(outOfDate.suggested_qty, 0)}
              </button>{" "}
            </>
          ) : null}
          <button type="button" className="btn btn-sm btn-danger" onClick={() => void remove()}>Delete the draft…</button>
        </div>
      ) : null}
      {planRow?.surplus?.length ? (
        <div className="banner-warn">
          The plan no longer uses all of this purchase:{" "}
          {planRow.surplus.map((s) => `${plain(s.qty, 0)} × ${s.name || s.key} (${amount(s.value, "PLN")})`).join(", ")}.
        </div>
      ) : null}

      {/* One column: the facts first, because a purchase order is read for its
          state and dates, and its few lines fit the full width. */}
      <FactsCard po={po} lateOrder={planRow?.order_late_days ?? 0} lateArrival={planRow?.arrival_late_days ?? 0}
        apply={apply} onLink={() => setLinking(true)} />
      <LinesCard po={po} onEdit={draft ? () => setEditingLines(true) : null} />
      <RowChangesCard table="purchase_orders" id={po.id} />

      {editingLines ? (
        <EditLinesDialog po={po} onClose={() => setEditingLines(false)}
          onSaved={(next) => { setEditingLines(false); void apply(async () => next); }} />
      ) : null}
      {linking ? (
        <LinkDocumentDialog po={po} onClose={() => setLinking(false)}
          onPick={(docId) => { setLinking(false); void apply(() => updatePurchaseOrder(po.id, { document_id: docId })); }} />
      ) : null}
    </PageShell>
  );
}

function LinesCard({ po, onEdit }: { po: PurchaseOrderRow; onEdit: (() => void) | null }) {
  const cols = useMemo<Column<PlanPoLine>[]>(() => [
    {
      // The name a plan gave the part, and the MPN it is bought by.
      key: "part", label: "Part", width: 40,
      get: (ln) => [ln.name, ln.mpn].filter(Boolean).join(" · ") || ln.lcsc || (ln.component_id ? `#${ln.component_id}` : "—"),
      render: (ln) => {
        const text = [ln.name, ln.mpn].filter(Boolean).join(" · ") || ln.lcsc || `#${ln.component_id}`;
        return ln.component_id
          ? <Link className="comp-link" to={`/library/components/${ln.component_id}`}>{text}</Link>
          : <>{text}</>;
      },
    },
    { key: "lcsc", label: "LCSC", width: 14, className: "mono", get: (ln) => ln.lcsc || "—" },
    { key: "qty", label: "Qty", width: 13, numeric: true, get: (ln) => ln.qty, render: (ln) => <>{plain(ln.qty, 0)}</> },
    { key: "unit", label: "Unit price", width: 15, numeric: true, get: (ln) => ln.unit_price ?? "",
      render: (ln) => <>{price(ln.unit_price)}</> },
    { key: "total", label: `Total (${po.currency})`, width: 18, numeric: true,
      get: (ln) => (ln.unit_price == null ? "" : ln.qty * ln.unit_price),
      render: (ln) => <>{ln.unit_price == null ? "—" : plain(ln.qty * ln.unit_price)}</> },
  ], [po.currency]);
  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Lines</h2>
        <span className="toolbar-total">{amount(po.amount, po.currency)}</span>
        {onEdit ? <button type="button" className="btn btn-sm" onClick={onEdit}>Edit lines…</button> : null}
      </div>
      {onEdit ? null : <p className="muted dim">Only a draft&apos;s lines change: an ordered purchase is the supplier&apos;s.</p>}
      <DataTable rows={po.lines} rowKey={(ln) => ln.id} columns={cols} empty="No lines yet." />
    </div>
  );
}

/** The facts, and the fields a person may correct. Behind Edit…, with Save and
 *  Cancel, so nothing is written while the reader tabs past a box. */
function FactsCard({ po, lateOrder, lateArrival, apply, onLink }: {
  po: PurchaseOrderRow;
  lateOrder: number;
  lateArrival: number;
  apply: (work: () => Promise<PurchaseOrderRow>) => Promise<void>;
  onLink: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const suppliers = useLoad(getSuppliers, [], { enabled: editing, once: true }).data ?? [];
  const [supplier, setSupplier] = useState(po.supplier);
  const [reference, setReference] = useState(po.reference);
  const [currency, setCurrency] = useState(po.currency);
  const [expected, setExpected] = useState(po.expected_on);
  const [notes, setNotes] = useState(po.notes);
  useEffect(() => {
    setSupplier(po.supplier);
    setReference(po.reference);
    setCurrency(po.currency);
    setExpected(po.expected_on);
    setNotes(po.notes);
  }, [po]);
  const dirty = supplier.trim() !== po.supplier || reference !== po.reference
    || currency.trim().toUpperCase() !== po.currency || expected !== po.expected_on || notes !== po.notes;
  const save = async () => {
    const name = supplier.trim();
    const known = suppliers.find((s) => s.name.toLowerCase() === name.toLowerCase());
    const body: Parameters<typeof updatePurchaseOrder>[1] = {};
    if (name !== po.supplier) {
      body.supplier = known ? known.name : name;
      body.supplier_id = known?.id ?? null;
    }
    if (reference !== po.reference) body.reference = reference;
    if (currency.trim().toUpperCase() !== po.currency) body.currency = currency.trim().toUpperCase();
    if (expected !== po.expected_on) body.expected_on = expected;
    if (notes !== po.notes) body.notes = notes;
    await apply(() => updatePurchaseOrder(po.id, body));
    setEditing(false);
  };
  const planned = po.plan_id != null;
  const late = (n: number) => (n > 0 ? <span className="warn-text"> · {plural(n, "day")} late</span> : null);
  return (
    <div className={editing ? "card pad edit-card" : "card pad"}>
      <div className="toolbar">
        <h2 className="card-title">Purchase order</h2>
        {editing ? null : <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>Edit…</button>}
      </div>
      {editing ? (
        <>
          <FieldGrid>
            <Field label="Supplier" wide>
              <input className="text" list="po-edit-supplier-names" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
              <datalist id="po-edit-supplier-names">
                {suppliers.map((s) => <option key={s.id} value={s.name} />)}
              </datalist>
            </Field>
            <Field label="Reference">
              <input className="text" value={reference} onChange={(e) => setReference(e.target.value)} />
            </Field>
            <Field label="Currency">
              <input className="text" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
            </Field>
            <Field label="Expected on" hint={planned ? "The plan computes the arrival. This is the supplier's word." : undefined}>
              <input className="text" type="date" value={expected} onChange={(e) => setExpected(e.target.value)} />
            </Field>
            <Field label="Notes" wide>
              <AutoTextarea className="text" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </Field>
          </FieldGrid>
          <div className="btn-row">
            <button type="button" className="btn btn-primary btn-sm" disabled={!dirty || !supplier.trim()} onClick={() => void save()}>
              Save
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </>
      ) : (
        <dl className="kv">
          <dt>Supplier</dt>
          <dd>{po.supplier}{po.supplier_id ? null : <span className="muted"> · not in the register</span>}</dd>
          <dt>Reference</dt>
          <dd className="mono">{po.reference || "—"}</dd>
          <dt>Plan</dt>
          <dd>
            {po.plan_id ? <Link className="comp-link" to={`/sales/plans/${po.plan_id}`}>{po.plan || `plan ${po.plan_id}`}</Link> : "—"}
          </dd>
          {planned ? (
            <>
              <dt>Order day</dt>
              <dd><span className="mono">{po.order_day || "—"}</span>{late(lateOrder)}<span className="muted"> · from the plan</span></dd>
              <dt>Arrival day</dt>
              <dd><span className="mono">{po.arrival_day || "—"}</span>{late(lateArrival)}<span className="muted"> · from the plan</span></dd>
            </>
          ) : null}
          <dt>Ordered on</dt>
          <dd className="mono">{po.ordered_on || "—"}</dd>
          <dt>Expected on</dt>
          <dd className="mono">{po.expected_on || "—"}</dd>
          <dt>Received on</dt>
          <dd className="mono">{po.received_on || "—"}</dd>
          <dt>Document</dt>
          <dd>
            {po.document_id ? (
              <>
                <Link className="comp-link" to={`/finance/invoices?doc=${po.document_id}`}>document {po.document_id}</Link>{" "}
                <button type="button" className="btn btn-sm" onClick={onLink}>Change…</button>{" "}
                <button type="button" className="btn btn-sm" onClick={() => void apply(() => updatePurchaseOrder(po.id, { document_id: null }))}>
                  Unlink
                </button>
              </>
            ) : (
              <button type="button" className="btn btn-sm" onClick={onLink}>Link a document…</button>
            )}
          </dd>
          <dt>Made by</dt>
          <dd>{po.created_by || "—"}{po.created_at ? <span className="muted"> · {localWhen(po.created_at)}</span> : null}</dd>
          {po.notes ? (
            <>
              <dt>Notes</dt>
              <dd>{po.notes}</dd>
            </>
          ) : null}
        </dl>
      )}
      <p className="muted dim">
        Marking it received records the day. It moves no stock: the stock comes with the supplier&apos;s
        document on Finance → Purchase invoices.
      </p>
    </div>
  );
}

function EditLinesDialog({ po, onClose, onSaved }: {
  po: PurchaseOrderRow;
  onClose: () => void;
  onSaved: (po: PurchaseOrderRow) => void;
}) {
  const modal = useModal(onClose);
  const [rows, setRows] = useState<PurchaseLineDraft[]>(() => (po.lines.length ? draftsOf(po.lines) : [blankLine()]));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    const body = linesBody(rows);
    if (body.error) {
      setError(body.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onSaved(await updatePurchaseOrder(po.id, { lines: body.lines }));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">Lines of the draft to {po.supplier}</h2>
        {po.proposal_key ? (
          <p className="muted dim">
            A plan made this draft. A changed quantity keeps it, and the plan marks the draft out of date when its
            own proposal differs.
          </p>
        ) : null}
        <ErrorBanner message={error} />
        <PurchaseLinesEditor rows={rows} onChange={setRows} currency={po.currency} />
        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void save()}>Save the lines</button>
        </div>
      </div>
    </div>
  );
}

/** Link the supplier's document: the invoice or proforma the purchase became.
 *  The register's documents of the same supplier come first. */
function LinkDocumentDialog({ po, onClose, onPick }: {
  po: PurchaseOrderRow;
  onClose: () => void;
  onPick: (docId: number) => void;
}) {
  const modal = useModal(onClose);
  const { data: reg, error } = useLoad(getInvoiceRegister, []);
  const [every, setEvery] = useState(false);
  const [chosen, setChosen] = useState<string>(po.document_id ? String(po.document_id) : "");
  const docs = useMemo(() => {
    const all = [...(reg?.documents ?? [])].sort((a, b) => (b.doc_date || "").localeCompare(a.doc_date || ""));
    const mine = all.filter((d) => d.supplier.toLowerCase().includes(po.supplier.toLowerCase())
      || po.supplier.toLowerCase().includes(d.supplier.toLowerCase()));
    return every || mine.length === 0 ? all : mine;
  }, [reg, every, po.supplier]);
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">Link a supplier document</h2>
        <p className="muted dim">The document is the invoice or proforma this purchase became. Linking moves no money.</p>
        <ErrorBanner message={error} />
        {reg === null ? <Spinner label="Loading documents…" /> : (
          <>
            <Field label="Document">
              <select className="text" value={chosen} onChange={(e) => setChosen(e.target.value)}>
                <option value="">— choose —</option>
                {docs.map((d) => (
                  <option key={d.id} value={d.id}>
                    {[d.doc_date || "no date", d.supplier, d.doc_number || d.external_id || `#${d.id}`,
                      d.total_amount == null ? "" : amount(d.total_amount, d.currency)].filter(Boolean).join(" · ")}
                  </option>
                ))}
              </select>
            </Field>
            <CheckField checked={every} onChange={setEvery}>Show the documents of every supplier</CheckField>
          </>
        )}
        <div className="btn-row modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={!chosen} onClick={() => onPick(Number(chosen))}>Link</button>
        </div>
      </div>
    </div>
  );
}
