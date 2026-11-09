/** Stock → Purchase orders: what we asked a supplier for, and when it comes
 *  (decision 0107 item 17).
 *
 *  A plan makes its drafts from its purchase proposals, on the plan's page. This
 *  list holds every purchase order of the company, a plan's or not, and it starts
 *  one by hand. A plan's order and arrival days are computed by the plan, so the
 *  list prints what the server computed and never a date of its own.
 */
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createPurchaseOrder,
  errorMessage,
  getSuppliers,
  listPurchaseOrders,
  type PurchaseOrderListRow,
} from "../api";
import AutoTextarea from "../components/AutoTextarea";
import DataTable, { type Column } from "../components/DataTable";
import Field, { FieldGrid } from "../components/Field";
import { NarrowChip } from "../components/FoldSection";
import { useModal } from "../components/modal";
import PageShell from "../components/PageShell";
import PurchaseLinesEditor, { blankLine, linesBody, type PurchaseLineDraft } from "../components/PurchaseLinesEditor";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { useLoad } from "../components/useLoad";
import { amount, plural } from "../format";

type Narrow = "" | PurchaseOrderListRow["status"];

export default function PurchaseOrders() {
  const { data: rows, error, reload } = useLoad((signal) => listPurchaseOrders(signal), [], { keep: true });
  const [creating, setCreating] = useState(false);
  const [narrow, setNarrow] = useState<Narrow>("");
  const navigate = useNavigate();

  const columns = useMemo<Column<PurchaseOrderListRow>[]>(() => [
    {
      key: "id", label: "Order", width: 11, className: "mono",
      get: (r) => (r.reference ? `#${r.id} ${r.reference}` : `#${r.id}`),
      sortValue: (r) => r.id,
    },
    { key: "supplier", label: "Supplier", width: 15, get: (r) => r.supplier },
    {
      key: "plan", label: "Plan", width: 15, get: (r) => r.plan || "—",
      render: (r) => (r.plan_id ? (
        <Link className="val-link" to={`/sales/plans/${r.plan_id}`} onClick={(e) => e.stopPropagation()}>
          {r.plan || `plan ${r.plan_id}`}
        </Link>
      ) : <span className="muted">—</span>),
    },
    // A pill is not cut by an ellipsis: "cancelled" needs this much.
    { key: "status", label: "Status", width: 10, get: (r) => r.status, render: (r) => <StatusPill status={r.status} /> },
    {
      key: "names", label: "Parts", width: 25,
      get: (r) => (r.lines > 3 ? `${r.names} and ${r.lines - 3} more` : r.names || "—"),
    },
    {
      key: "amount", label: "Amount", width: 15, numeric: true, get: (r) => r.amount,
      render: (r) => <>{amount(r.amount, r.currency)}</>,
    },
    // A date has a hard maximum, so it takes a length (web/CLAUDE.md).
    { key: "order_day", label: "Order day", width: "104px", className: "mono", get: (r) => r.order_day || "—" },
    { key: "arrival_day", label: "Arrives", width: "104px", className: "mono", get: (r) => r.arrival_day || "—" },
    // Sortable with no filter box: a 9 % column has no room for one.
    { key: "lines", label: "Lines", width: 9, numeric: true, interactive: false, sortable: true, get: (r) => r.lines },
  ], []);

  const all = rows ?? [];
  const count = (s: Narrow) => all.filter((r) => r.status === s).length;

  return (
    <PageShell>
      <div className="toolbar">
        <h1>Purchase orders</h1>
        <span className="toolbar-total">{rows ? plural(all.length, "purchase order") : ""}</span>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
          New purchase order
        </button>
      </div>
      <ErrorBanner message={error} />

      <div className="card pad">
        <h2 className="card-title">Orders to suppliers</h2>
        <p className="muted dim">
          A plan makes its drafts from its purchase proposals, and it computes their dates. Click a row for its
          lines and to mark it ordered or received.
        </p>
        {rows === null ? (
          <Spinner label="Loading purchase orders…" />
        ) : (
          <>
            <div className="stat-row">
              <NarrowChip n={count("draft")} tone={count("draft") ? "warn" : undefined} value="draft" current={narrow} onNarrow={setNarrow}>draft</NarrowChip>
              <NarrowChip n={count("ordered")} tone="acc" value="ordered" current={narrow} onNarrow={setNarrow}>ordered</NarrowChip>
              <NarrowChip n={count("received")} tone="ok" value="received" current={narrow} onNarrow={setNarrow}>received</NarrowChip>
              <NarrowChip n={count("cancelled")} value="cancelled" current={narrow} onNarrow={setNarrow}>cancelled</NarrowChip>
            </div>
            <DataTable
              rows={narrow ? all.filter((r) => r.status === narrow) : all}
              columns={columns}
              rowKey={(r) => r.id}
              rowClass={(r) => (r.status === "cancelled" ? "dim" : "")}
              defaultSort={{ key: "id", dir: "desc" }}
              onRowClick={(r) => navigate(`/stock/purchase-orders/${r.id}`)}
              persistKey="purchase-orders"
              empty={narrow ? "No purchase order in this state." : "No purchase orders yet. A plan makes drafts from its proposals, or start one with New purchase order."}
            />
          </>
        )}
      </div>

      {creating ? (
        <NewPurchaseOrderDialog
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            void reload();
            navigate(`/stock/purchase-orders/${id}`);
          }}
        />
      ) : null}
    </PageShell>
  );
}

/** A purchase order started by hand. A plan's drafts come from the plan page. */
function NewPurchaseOrderDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const modal = useModal(onClose);
  const suppliers = useLoad(getSuppliers, []).data ?? [];
  const [supplier, setSupplier] = useState("");
  const [reference, setReference] = useState("");
  const [currency, setCurrency] = useState("PLN");
  const [expected, setExpected] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<PurchaseLineDraft[]>([blankLine()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const name = supplier.trim();
    if (!name) {
      setError("Name the supplier.");
      return;
    }
    const body = linesBody(lines);
    if (body.error) {
      setError(body.error);
      return;
    }
    const known = suppliers.find((s) => s.name.toLowerCase() === name.toLowerCase());
    setBusy(true);
    setError(null);
    try {
      const po = await createPurchaseOrder({
        supplier_id: known?.id ?? null,
        supplier: known ? known.name : name,
        reference: reference.trim(),
        currency: currency.trim().toUpperCase() || "PLN",
        expected_on: expected,
        notes,
        lines: body.lines,
      });
      onCreated(po.id);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">New purchase order</h2>
        <p className="muted dim">
          It starts as a draft. Nothing is ordered until you mark it ordered on its page.
        </p>
        <ErrorBanner message={error} />
        <FieldGrid>
          <Field label="Supplier" hint="From the supplier register, or a new name">
            <input className="text" list="po-supplier-names" value={supplier} autoFocus
              onChange={(e) => setSupplier(e.target.value)} />
            <datalist id="po-supplier-names">
              {suppliers.map((s) => <option key={s.id} value={s.name} />)}
            </datalist>
          </Field>
          <Field label="Reference" hint="Their quote or order number">
            <input className="text" value={reference} onChange={(e) => setReference(e.target.value)} />
          </Field>
          <Field label="Currency">
            <input className="text" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
          </Field>
          <Field label="Expected on">
            <input className="text" type="date" value={expected} onChange={(e) => setExpected(e.target.value)} />
          </Field>
        </FieldGrid>
        <PurchaseLinesEditor rows={lines} onChange={setLines} currency={currency} />
        <Field label="Notes">
          <AutoTextarea className="text" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void submit()}>
            Create the draft
          </button>
        </div>
      </div>
    </div>
  );
}
