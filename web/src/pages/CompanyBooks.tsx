/** A company's books, month by month (decision 0068): the platform's ESTIMATE
 *  beside the accountant's figures, the way a batch has a planned and an
 *  actual cost. Every figure the platform computes is an estimate; the
 *  accountant's are the ones that count.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getCompanyBooks,
  deleteTaxPeriod,
  isAbortError,
  listTaxEntryFiles,
  putTaxEntry,
  putTaxPeriod,
  TAX_FORM_TEXT,
  taxEntryFilePath,
  uploadTaxEntryFile,
  type BooksMonth,
  type TaxPeriod,
  type CompanyBooks as Books,
} from "../api";
import { useAuth } from "../auth";
import DataTable, { type Column } from "../components/DataTable";
import RecordFiles from "../components/RecordFiles";
import SiInput from "../components/SiInput";
import { useDialog } from "../components/Dialog";
import Field, { FieldRow } from "../components/Field";
import { ErrorBanner, Spinner } from "../components/Ui";

const BUCKET_TEXT: Record<string, string> = {
  stock: "Stock bought", batches: "Batch costs", projects: "Project costs", prepared: "Prepared parts",
  overhead: "Company overhead", unassigned: "Not assigned yet",
};
const KIND_TEXT: Record<string, string> = { vat: "VAT", pit: "PIT", cit: "CIT", zus: "ZUS", health: "Health", other: "Other" };

function pl(x: string | null | undefined): string {
  if (x == null) return "—";
  return Number(x).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function acc(m: BooksMonth, kind: string): string {
  const e = m.accountant[kind];
  return e ? `${pl(e.amount)}${e.status === "final" ? "" : " (est.)"}` : "";
}

function MonthPanel({ companyId, m, onSaved }: { companyId: number; m: BooksMonth; onSaved: () => void }) {
  const [kind, setKind] = useState("vat");
  const [amount, setAmount] = useState("");
  const [status, setStatus] = useState("final");
  const [due, setDue] = useState("");
  const [paid, setPaid] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const e = m.accountant[kind];
    setAmount(e ? e.amount : "");
    setStatus(e ? e.status : "final");
    setDue(e?.due_date ?? "");
    setPaid(e?.paid_date ?? "");
    setNote(e?.note ?? "");
  }, [kind, m]);
  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      await putTaxEntry(companyId, { period: m.month, kind, amount: Number(amount), status, due_date: due, paid_date: paid, note });
      onSaved();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="user-detail">
      <p className="muted">
        Costs: {Object.entries(m.costs).filter(([, v]) => Number(v)).map(([k, v]) => `${BUCKET_TEXT[k] ?? k} ${pl(v)}`).join(" · ") || "none"}
        {Number(m.advances_net) ? ` · advances received ${pl(m.advances_net)} net (VAT only)` : ""}
        {" · "}VAT on sales {pl(m.sales_vat)}, on purchases {pl(m.purchase_vat)}
      </p>
      <ErrorBanner message={err} />
      <FieldRow>
        <Field label="The accountant's figure">
          <select className="text" value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(KIND_TEXT).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select>
        </Field>
        <Field label="Amount (PLN)">
          <input className="text num-input" value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <Field label="Status">
          <select className="text" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="final">final</option>
            <option value="estimated">estimated</option>
          </select>
        </Field>
        <Field label="Due">
          <input className="text" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </Field>
        <Field label="Paid">
          <input className="text" type="date" value={paid} onChange={(e) => setPaid(e.target.value)} />
        </Field>
        <Field label="Note" wide>
          <input className="text" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy || amount === ""} onClick={() => void save()}>
          Save
        </button>
      </FieldRow>
      {m.accountant[kind] ? (
        <div className="btn-row">
          <EntryFiles companyId={companyId} entryId={m.accountant[kind].id} onChange={onSaved} />
        </div>
      ) : null}
    </div>
  );
}

/** The accountant's notices filed with one tax figure (decision 0077). */
function EntryFiles({ companyId, entryId, onChange }: { companyId: number; entryId: number; onChange: () => void }) {
  const list = useCallback((signal?: AbortSignal) => listTaxEntryFiles(companyId, entryId, signal), [companyId, entryId]);
  const upload = useCallback((file: File) => uploadTaxEntryFile(companyId, entryId, file), [companyId, entryId]);
  return (
    <RecordFiles list={list} upload={upload} pathOf={(fileId) => taxEntryFilePath(companyId, entryId, fileId)}
                 label="Notices" onChange={onChange} />
  );
}

/** The income-tax form from a quarter on (decision 0078). The law sets the
 *  form for a whole year; the quarter is the user's choice of granularity.
 *  Everybody reads it; an admin changes it, as the company's one form. */
function TaxPeriodsCard({ companyId, periods, onSaved }: { companyId: number; periods: TaxPeriod[]; onSaved: () => void }) {
  const { isAdmin } = useAuth();
  const dialog = useDialog();
  const [quarter, setQuarter] = useState("");
  const [form, setForm] = useState("pit_linear");
  const [rate, setRate] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr("");
    try {
      await fn();
      onSaved();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const cols: Column<TaxPeriod>[] = [
    { key: "q", label: "From quarter", width: 14, className: "mono", get: (p) => p.from_quarter },
    { key: "form", label: "Form", width: 26, get: (p) => TAX_FORM_TEXT[p.form] ?? p.form },
    { key: "rate", label: "Effective rate", width: 14, numeric: true, get: (p) => Number(p.rate ?? -1),
      render: (p) => <>{p.rate == null ? "statutory" : `${Number(p.rate).toLocaleString("pl-PL")} %`}</> },
    { key: "note", label: "Note", width: isAdmin ? 36 : 46, get: (p) => p.note, title: (p) => p.note },
    ...(isAdmin ? [{ key: "x", label: "", width: 10, interactive: false, get: () => "",
      render: (p: TaxPeriod) => (
        <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={async () => {
          if (await dialog.confirm(`Remove the tax form from ${p.from_quarter}? The months fall back to the period before it.`,
            { title: "Remove tax period", confirmLabel: "Remove", tone: "danger" })) {
            await act(() => deleteTaxPeriod(companyId, p.id));
          }
        }}>Remove</button>
      ) } as Column<TaxPeriod>] : []),
  ];
  return (
    <div className="card pad">
      <h2 className="card-title">Tax form by quarter</h2>
      <p className="muted dim">
        Each row applies from its quarter until the next row. An effective rate replaces the statutory computation, for a
        year whose return shows the real tax (IP BOX, deductions). By law the form is chosen for a whole year, by the 20th
        of the month after the year's first revenue.
      </p>
      <ErrorBanner message={err} />
      <DataTable rows={periods} rowKey={(p) => p.id} columns={cols} empty="No form by quarter: the company's one form applies." />
      {isAdmin ? (
        <FieldRow>
          <Field label="From quarter">
            <input className="text mono" value={quarter} placeholder="2024-Q1" onChange={(e) => setQuarter(e.target.value.trim().toUpperCase())} />
          </Field>
          <Field label="Form">
            <select className="text" value={form} onChange={(e) => setForm(e.target.value)}>
              {Object.entries(TAX_FORM_TEXT).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select>
          </Field>
          <Field label="Effective rate" hint="Optional. Empty means the statutory rates.">
            <SiInput quantity="percent" value={rate} onChange={setRate} onEmpty={() => setRate(null)} />
          </Field>
          <Field label="Note" wide>
            <input className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <button type="button" className="btn btn-primary btn-sm" disabled={busy || !/^\d{4}-Q[1-4]$/.test(quarter)}
                  onClick={() => void act(() => putTaxPeriod(companyId, { from_quarter: quarter, form, rate, note }))}>
            Save
          </button>
        </FieldRow>
      ) : null}
    </div>
  );
}

export default function CompanyBooks() {
  const { companies, scope } = useAuth();
  const [companyId, setCompanyId] = useState<number>(scope !== "all" ? Number(scope) : companies[0]?.id ?? 0);
  const [year, setYear] = useState(new Date().getFullYear());
  const [books, setBooks] = useState<Books | null>(null);
  const [error, setError] = useState("");

  const load = useCallback((signal?: AbortSignal) => {
    if (!companyId) return;
    getCompanyBooks(companyId, year, signal).then((b) => { setBooks(b); setError(""); })
      .catch((e) => { if (!isAbortError(e)) setError(errorMessage(e)); });
  }, [companyId, year]);
  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  const taxLabel = books?.tax_form?.startsWith("cit") ? "cit" : "pit";
  const cols = useMemo<Column<BooksMonth>[]>(() => [
    { key: "month", label: "Month", width: 8, className: "mono", get: (m) => m.month },
    { key: "rev", label: "Revenue", width: 11, numeric: true, get: (m) => Number(m.revenue_net), render: (m) => <>{pl(m.revenue_net)}</> },
    { key: "cost", label: "Costs", width: 11, numeric: true, get: (m) => Number(m.costs_net), render: (m) => <>{pl(m.costs_net)}</> },
    { key: "inc", label: "Income", width: 11, numeric: true, get: (m) => Number(m.income), render: (m) => <>{pl(m.income)}</> },
    { key: "vat", label: "VAT est.", width: 10, numeric: true, get: (m) => Number(m.vat_estimate), render: (m) => <>{pl(m.vat_estimate)}</> },
    { key: "vat_a", label: "VAT (acct.)", width: 11, numeric: true, get: (m) => Number(m.accountant.vat?.amount ?? 0), render: (m) => <>{acc(m, "vat")}</> },
    { key: "tax", label: `${taxLabel.toUpperCase()} est.`, width: 9, numeric: true,
      get: (m) => Number(m.income_tax_estimate ?? 0), render: (m) => <>{pl(m.income_tax_estimate)}</>,
      title: (m) => m.tax_form ? `${TAX_FORM_TEXT[m.tax_form] ?? m.tax_form}${m.tax_rate ? `, effective ${m.tax_rate} %` : ""}` : "no tax form" },
    { key: "tax_a", label: `${taxLabel.toUpperCase()} (acct.)`, width: 11, numeric: true,
      get: (m) => Number(m.accountant[taxLabel]?.amount ?? 0), render: (m) => <>{acc(m, taxLabel)}</> },
    { key: "zus", label: "ZUS (acct.)", width: 9, numeric: true, get: (m) => Number(m.accountant.zus?.amount ?? 0), render: (m) => <>{acc(m, "zus")}</> },
    { key: "hl", label: "Health", width: 9, numeric: true, get: (m) => Number(m.accountant.health?.amount ?? 0), render: (m) => <>{acc(m, "health")}</> },
  ], [taxLabel]);

  const overhead = books ? Object.entries(books.overhead).map(([k, v]) => ({ key: k, label: books.overhead_labels[k] ?? k, amount: v })) : [];
  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1 className="page-title">Company books</h1>
          {books ? (
            <span className="toolbar-total">
              {books.year}: revenue {pl(books.totals.revenue_net)} · costs {pl(books.totals.costs_net)} · income {pl(books.totals.income)} PLN
            </span>
          ) : null}
        </div>
        <p className="muted dim">
          The platform's estimate from the sales invoices and the supplier documents billed to the company, beside the
          accountant's figures. Open a month to enter them.{" "}
          {books && !books.tax_form && !books.tax_periods?.length ? <>No income tax is estimated until the tax form is set on <Link className="comp-link" to="/admin?tab=companies">Admin → Companies</Link>.</> : null}
        </p>
        <FieldRow>
          {companies.length > 1 ? (
            <Field label="Company">
              <select className="text" value={companyId} onChange={(e) => setCompanyId(Number(e.target.value))}>
                {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
          ) : null}
          <Field label="Year">
            <select className="text" value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {[0, 1, 2, 3, 4, 5].map((d) => new Date().getFullYear() - d).map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </Field>
        </FieldRow>
        <ErrorBanner message={error} />
        <div className="card pad">
          <h2 className="card-title">Months</h2>
          {books === null ? <Spinner label="Computing…" /> : (
            <DataTable rows={books.months} rowKey={(m) => m.month} columns={cols} empty="—"
              expand={(m) => <MonthPanel companyId={companyId} m={m} onSaved={() => load()} />} />
          )}
        </div>
        {books ? <TaxPeriodsCard companyId={companyId} periods={books.tax_periods ?? []} onSaved={() => load()} /> : null}
        {overhead.length ? (
          <div className="card pad">
            <h2 className="card-title">Company overhead</h2>
            <DataTable rows={overhead} rowKey={(r) => r.key} empty="—" columns={[
              { key: "cat", label: "Category", width: 70, get: (r) => r.label },
              { key: "amt", label: "Net (PLN)", width: 30, numeric: true, get: (r) => Number(r.amount), render: (r) => <>{pl(r.amount)}</> },
            ]} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
