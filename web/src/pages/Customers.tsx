/** Sales → Customers: who an order and an invoice name. An order creates its
 *  customer when the name is new, and this page says the rest: what an invoice
 *  prints for the buyer (decision 0066) and the payment terms.
 */
import { useEffect, useState } from "react";
import {
  createCustomer,
  errorMessage,
  isAbortError,
  listCustomers,
  updateCustomer,
  type CustomerRow,
} from "../api";
import AutoTextarea from "../components/AutoTextarea";
import DataTable from "../components/DataTable";
import Field, { FieldGrid } from "../components/Field";
import NumberInput from "../components/NumberInput";
import { ErrorBanner, Spinner } from "../components/Ui";

type Draft = Omit<CustomerRow, "id" | "created_at">;

const EMPTY: Draft = {
  name: "", tax_id: "", address: "", payment_terms_days: 14, notes: "",
  key: "", legal_name: "", address_l1: "", address_l2: "", country: "PL",
};

function CustomerForm({ start, saveLabel, onSave, onCancel }: {
  start: Draft;
  saveLabel: string;
  onSave: (d: Draft) => Promise<void>;
  onCancel?: () => void;
}) {
  const [d, setD] = useState<Draft>(start);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<Draft>) => setD((x) => ({ ...x, ...patch }));
  const save = async () => {
    setBusy(true);
    try {
      await onSave(d);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      {error ? <ErrorBanner message={error} /> : null}
      <FieldGrid>
        <Field label="Name"><input className="text" value={d.name} onChange={(e) => set({ name: e.target.value })} /></Field>
        <Field label="NIP"><input className="text mono" value={d.tax_id} onChange={(e) => set({ tax_id: e.target.value })} /></Field>
        <Field label="Payment days">
          <NumberInput className="text" value={d.payment_terms_days} min={0} step={1}
            onChange={(v) => set({ payment_terms_days: v ?? 0 })} />
        </Field>
        <Field label="Key" hint="the short name in a document number">
          <input className="text mono" value={d.key ?? ""} onChange={(e) => set({ key: e.target.value })} />
        </Field>
        <Field label="Legal name" hint="what an invoice prints">
          <input className="text" value={d.legal_name ?? ""} onChange={(e) => set({ legal_name: e.target.value })} />
        </Field>
        <Field label="Address, line 1"><input className="text" value={d.address_l1 ?? ""} onChange={(e) => set({ address_l1: e.target.value })} /></Field>
        <Field label="Address, line 2"><input className="text" value={d.address_l2 ?? ""} onChange={(e) => set({ address_l2: e.target.value })} /></Field>
        <Field label="Country"><input className="text mono" value={d.country ?? ""} onChange={(e) => set({ country: e.target.value })} /></Field>
        <Field label="Delivery address" wide><AutoTextarea className="text" value={d.address} onChange={(e) => set({ address: e.target.value })} /></Field>
        <Field label="Notes" wide><AutoTextarea className="text" value={d.notes} onChange={(e) => set({ notes: e.target.value })} /></Field>
      </FieldGrid>
      <div className="btn-row">
        <button type="button" className="btn btn-primary btn-sm" disabled={busy || !d.name.trim()} onClick={() => void save()}>
          {busy ? "Saving…" : saveLabel}
        </button>
        {onCancel ? <button type="button" className="btn btn-sm" onClick={onCancel}>Cancel</button> : null}
      </div>
    </div>
  );
}

export default function Customers() {
  const [rows, setRows] = useState<CustomerRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    const ac = new AbortController();
    listCustomers(ac.signal)
      .then(setRows)
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    return () => ac.abort();
  }, []);

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Customers</h1>
          <span className="toolbar-total">{rows ? `${rows.length} customers` : ""}</span>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setAdding(!adding)}>
            {adding ? "Close" : "New customer"}
          </button>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {adding ? (
          <div className="card pad">
            <h2 className="card-title">New customer</h2>
            <CustomerForm start={EMPTY} saveLabel="Create customer" onCancel={() => setAdding(false)}
              onSave={async (d) => {
                const made = await createCustomer(d);
                setRows((r) => [...(r ?? []), made]);
                setAdding(false);
              }} />
          </div>
        ) : null}
        <div className="card pad">
          {!rows ? <Spinner /> : (
            <DataTable
              rows={rows}
              rowKey={(c) => c.id}
              persistKey="customers"
              empty="No customer yet. An order creates its customer."
              defaultSort={{ key: "name", dir: "asc" }}
              columns={[
                { key: "name", label: "Name", width: 28, get: (c) => c.name },
                { key: "nip", label: "NIP", width: 14, className: "mono", get: (c) => c.tax_id },
                { key: "legal", label: "Legal name", width: 28, get: (c) => c.legal_name ?? "" },
                { key: "country", label: "Country", width: 8, get: (c) => c.country ?? "" },
                { key: "days", label: "Payment days", width: 10, numeric: true, get: (c) => c.payment_terms_days },
                { key: "notes", label: "Notes", width: 12, get: (c) => c.notes },
              ]}
              expand={(c) => (
                <CustomerForm start={c} saveLabel="Save" onSave={async (d) => {
                  const saved = await updateCustomer(c.id, d);
                  setRows((r) => (r ?? []).map((x) => (x.id === c.id ? saved : x)));
                }} />
              )}
            />
          )}
        </div>
      </div>
    </div>
  );
}
