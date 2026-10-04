/** The companies the platform keeps books for, and what each prints as a seller
 *  (decision 0063). Admin only: the API sends the seller data to an admin alone,
 *  and refuses an edit from anyone else.
 *
 *  The NIP is the company's identity, so it is shown and never edited here — a
 *  different NIP is a different company.
 */
import { useEffect, useState } from "react";
import {
  errorMessage,
  isAbortError,
  listCompanies,
  updateCompany,
  type CompanyDetail,
} from "../api";
import DataTable, { type Column } from "./DataTable";
import Field, { FieldGrid } from "./Field";
import NumberInput from "./NumberInput";
import { ErrorBanner, Spinner } from "./Ui";

/** The text fields an admin may change, in the order the form draws them. */
const TEXT_FIELDS: { key: keyof CompanyDetail; label: string; wide?: boolean }[] = [
  { key: "name", label: "Short name" },
  { key: "legal_name", label: "Legal name", wide: true },
  { key: "address_l1", label: "Address, line 1", wide: true },
  { key: "address_l2", label: "Address, line 2", wide: true },
  { key: "country", label: "Country code" },
  { key: "email", label: "Email" },
  { key: "place_of_issue", label: "Place of issue" },
  { key: "issuer_name", label: "Issued by" },
  { key: "bank_name", label: "Bank" },
  { key: "bank_account", label: "Bank account (IBAN)", wide: true },
  { key: "swift", label: "SWIFT" },
];

const COLUMNS: Column<CompanyDetail>[] = [
  { key: "name", label: "Company", width: 22, get: (c) => c.name },
  { key: "legal_name", label: "Legal name", width: 38, get: (c) => c.legal_name },
  { key: "nip", label: "NIP", width: 16, className: "mono", get: (c) => c.nip },
  { key: "started", label: "Started", width: 12, className: "mono", get: (c) => c.started_on ?? "" },
  { key: "terms", label: "Terms (days)", width: 12, numeric: true, get: (c) => c.payment_terms_days },
];

function CompanyForm({ company, onSaved }: { company: CompanyDetail; onSaved: (c: CompanyDetail) => void }) {
  const [draft, setDraft] = useState<CompanyDetail>(company);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => setDraft(company), [company]);
  const changed = (Object.keys(draft) as (keyof CompanyDetail)[]).filter((k) => draft[k] !== company[k]);

  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      const patch: Partial<CompanyDetail> = {};
      for (const k of changed) (patch as Record<string, unknown>)[k] = draft[k];
      onSaved(await updateCompany(company.id, patch));
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="user-detail">
      <ErrorBanner message={err} />
      <FieldGrid>
        {TEXT_FIELDS.map((f) => (
          <Field key={f.key} label={f.label} wide={f.wide}>
            <input
              className="text"
              value={String(draft[f.key] ?? "")}
              onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
            />
          </Field>
        ))}
        <Field label="Payment terms (days)">
          <NumberInput
            className="text"
            value={draft.payment_terms_days}
            min={0}
            step={1}
            onChange={(v) => setDraft((d) => ({ ...d, payment_terms_days: v }))}
          />
        </Field>
      </FieldGrid>
      <div className="btn-row">
        <button type="button" className="btn btn-primary btn-sm" disabled={busy || !changed.length} onClick={() => void save()}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" className="btn btn-sm" disabled={busy || !changed.length} onClick={() => setDraft(company)}>
          Discard
        </button>
      </div>
    </div>
  );
}

export default function CompaniesCard() {
  const [rows, setRows] = useState<CompanyDetail[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const ac = new AbortController();
    listCompanies(ac.signal)
      .then(setRows)
      .catch((err) => {
        if (isAbortError(err)) return;
        setRows([]);
        setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  if (rows === null) return <Spinner label="Loading companies…" />;
  return (
    <div className="card pad">
      <h2>Companies</h2>
      <p className="muted dim">
        Each project, batch and order belongs to one of these. Open a row to change what the company
        prints as a seller. The NIP is the company itself and does not change.
      </p>
      <ErrorBanner message={error} />
      <DataTable
        rows={rows}
        rowKey={(c) => c.id}
        columns={COLUMNS}
        empty="No companies."
        expand={(c) => (
          <CompanyForm company={c} onSaved={(n) => setRows((rs) => (rs ?? []).map((r) => (r.id === n.id ? n : r)))} />
        )}
      />
    </div>
  );
}
