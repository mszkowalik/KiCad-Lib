/** A company's books, month by month (decision 0068): the platform's ESTIMATE
 *  beside the accountant's figures, the way a batch has a planned and an
 *  actual cost. Every figure the platform computes is an estimate; the
 *  accountant's are the ones that count.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  createOverheadCategory,
  deleteOverheadCategory,
  errorMessage,
  getCompanyBooks,
  listOverheadCategories,
  overheadCategoryDocuments,
  relabelOverheadCategory,
  deleteTaxPeriod,
  accountantFilesUrl,
  getAccountantToSend,
  markAccountant,
  isAbortError,
  listTaxEntryFiles,
  putTaxEntry,
  putTaxPeriod,
  TAX_FORM_TEXT,
  taxFormsFor,
  taxEntryFilePath,
  uploadTaxEntryFile,
  type AccountantRow,
  type AccountantToSend,
  type BooksMonth,
  type TaxPeriod,
  type CompanyBooks as Books,
  type OverheadCategory,
  type OverheadCategoryDocument,
} from "../api";
import { useAuth } from "../auth";
import { askNotSentReason } from "../components/AccountantMark";
import { forgetOverheadCategories } from "../components/costs";
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
/** The health contribution is paid with ZUS and entered as ZUS (decision 0081). */
const KIND_TEXT: Record<string, string> = { vat: "VAT", pit: "PIT", cit: "CIT", zus: "ZUS", other: "Other" };

function pl(x: string | null | undefined): string {
  if (x == null) return "—";
  return Number(x).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function acc(m: BooksMonth, kind: string): string {
  const e = m.accountant[kind];
  return e ? `${pl(e.amount)}${e.status === "final" ? "" : " (est.)"}` : "";
}

function MonthPanel({ companyId, m, incomeTax, onSaved }: {
  companyId: number; m: BooksMonth; incomeTax: "pit" | "cit"; onSaved: () => void;
}) {
  const [kind, setKind] = useState("vat");
  const [amount, setAmount] = useState("");
  const [interest, setInterest] = useState("");
  const [status, setStatus] = useState("final");
  const [due, setDue] = useState("");
  const [paid, setPaid] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const e = m.accountant[kind];
    setAmount(e ? e.amount : "");
    setInterest(e?.interest && Number(e.interest) ? e.interest : "");
    setStatus(e ? e.status : "final");
    setDue(e?.due_date ?? "");
    setPaid(e?.paid_date ?? "");
    setNote(e?.note ?? "");
  }, [kind, m]);
  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      await putTaxEntry(companyId, {
        period: m.month, kind, amount: Number(amount), interest: Number(interest || 0), status, due_date: due, paid_date: paid, note,
      });
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
        {Number(m.purchase_vat_excluded) ? ` (${pl(m.purchase_vat_excluded)} more not deductible)` : ""}
      </p>
      <ErrorBanner message={err} />
      <FieldRow>
        <Field label="The accountant's figure">
          <select className="text" value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(KIND_TEXT).filter(([k]) => k !== (incomeTax === "cit" ? "pit" : "cit"))
              .map(([k, t]) => <option key={k} value={k}>{t}</option>)}
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
        <Field label="Interest (PLN)" hint="Late-payment interest paid on top of the amount. It is never a cost and never enters a tax estimate.">
          <input className="text num-input" value={interest} inputMode="decimal" placeholder="0" onChange={(e) => setInterest(e.target.value)} />
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
function TaxPeriodsCard({ companyId, periods, incomeTax, onSaved }: {
  companyId: number; periods: TaxPeriod[]; incomeTax?: "pit" | "cit"; onSaved: () => void;
}) {
  const { isAdmin } = useAuth();
  const dialog = useDialog();
  const [quarter, setQuarter] = useState("");
  const [form, setForm] = useState(incomeTax === "cit" ? "cit_9" : "pit_linear");
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
              {taxFormsFor(incomeTax).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
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

/** What the accountant does not have yet, month by month, each month due by
 *  the 10th of the next one (decision 0079). KSeF documents, proformas and
 *  transfers are not listed. Tick rows and record that they were sent, or
 *  that she will never get them, with the reason (decision 0080). Download
 *  gives their files as one ZIP: the ticked rows, or the whole list. */
function AccountantCard({ companyId }: { companyId: number }) {
  const dialog = useDialog();
  const [data, setData] = useState<AccountantToSend | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback((signal?: AbortSignal) => {
    getAccountantToSend(companyId, signal).then((d) => { setData(d); setErr(""); setPicked(new Set()); })
      .catch((e) => { if (!isAbortError(e)) setErr(errorMessage(e)); });
  }, [companyId]);
  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);
  const keyOf = (r: AccountantRow) => `${r.kind}:${r.id}`;
  const toggle = (r: AccountantRow) => setPicked((p) => {
    const n = new Set(p);
    if (n.has(keyOf(r))) n.delete(keyOf(r)); else n.add(keyOf(r));
    return n;
  });
  const recordPicked = async (day: string, via: string, ref = "") => {
    const ids = [...picked].map((k) => k.split(":"));
    setBusy(true);
    try {
      await markAccountant(companyId, {
        document_ids: ids.filter(([k]) => k === "document").map(([, i]) => Number(i)),
        sales_invoice_ids: ids.filter(([k]) => k === "sales_invoice").map(([, i]) => Number(i)),
        sent_at: day, via, ref,
      });
      load();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const markPicked = async () => {
    const day = await dialog.prompt("Sent to the accountant on (YYYY-MM-DD):",
      { title: "Mark as sent", initial: new Date().toISOString().slice(0, 10) });
    if (day) await recordPicked(day, "manual");
  };
  const keepPicked = async () => {
    const reason = await askNotSentReason(dialog, picked.size);
    if (reason) await recordPicked(new Date().toISOString().slice(0, 10), "not_sent", reason);
  };
  const cols: Column<AccountantRow>[] = [
    { key: "pick", label: "", width: 4, className: "ctr", interactive: false, get: () => "",
      render: (r) => <input type="checkbox" checked={picked.has(keyOf(r))} onChange={() => toggle(r)} aria-label="Select" /> },
    { key: "date", label: "Date", width: 11, className: "mono", get: (r) => r.date },
    { key: "kind", label: "Kind", width: 10, get: (r) => (r.kind === "document" ? "purchase" : "sales") },
    { key: "party", label: "Supplier / buyer", width: 32, get: (r) => r.party, title: (r) => r.party },
    { key: "number", label: "Number", width: 20, className: "mono", get: (r) => r.number, title: (r) => r.number },
    { key: "net", label: "Net", width: 13, numeric: true, get: (r) => Number(r.net ?? 0),
      render: (r) => <>{pl(r.net == null ? null : String(r.net))} {r.currency !== "PLN" ? r.currency : ""}</> },
    { key: "files", label: "PDF", width: 10, get: (r) => r.files, render: (r) => <>{r.files ? "yes" : "none"}</> },
  ];
  return (
    <div className="card pad">
      <h2 className="card-title">For the accountant</h2>
      <p className="muted dim">
        Documents the accountant does not have yet. Each month is due by the 10th of the next month. KSeF documents
        reach her by themselves. A document she will never get (lost, private, too late) can be marked "not for the
        accountant": it leaves this list and the books above, and batch costs keep it.
      </p>
      <ErrorBanner message={err} />
      {data === null ? <Spinner label="Loading…" /> : data.count === 0 ? (
        <p className="muted">Nothing to send: the accountant has every document.</p>
      ) : (
        <>
          <div className="btn-row">
            <button type="button" className="btn btn-primary btn-sm" disabled={busy || !picked.size} onClick={() => void markPicked()}>
              Mark {picked.size || ""} sent…
            </button>
            <button type="button" className="btn btn-sm" disabled={busy || !picked.size} onClick={() => void keepPicked()}>
              Not for the accountant…
            </button>
            <a className="btn btn-sm" href={accountantFilesUrl(companyId, [...picked])} download
              title="One ZIP, a folder per month. A document without a file is named in _missing-files.txt.">
              Download {picked.size ? `${picked.size} selected` : "all"} (ZIP)
            </a>
            <span className="muted">{data.count} document(s) to send</span>
          </div>
          {[...data.months].reverse().map((m) => (
            <div key={m.month}>
              <h3 className="card-subtitle">
                {m.month} · send by {m.deadline}{" "}
                <span className={`pill ${m.overdue ? "err" : "warn"}`}>{m.overdue ? "late" : "due"}</span>
              </h3>
              <DataTable rows={m.rows} rowKey={keyOf} columns={cols} empty="—" />
            </div>
          ))}
        </>
      )}
    </div>
  );
}

/** The documents whose live positions name one category, so they can be moved
 *  before the category is removed. Each opens on the Invoices page. */
function CategoryDocuments({ categoryKey }: { categoryKey: string }) {
  const [docs, setDocs] = useState<OverheadCategoryDocument[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    const ac = new AbortController();
    overheadCategoryDocuments(categoryKey, ac.signal).then(setDocs)
      .catch((e) => { if (!isAbortError(e)) setErr(errorMessage(e)); });
    return () => ac.abort();
  }, [categoryKey]);
  if (err) return <ErrorBanner message={err} />;
  if (docs === null) return <Spinner label="Loading documents" />;
  return (
    <DataTable rows={docs} rowKey={(d) => d.id} empty="No document names this category." columns={[
      { key: "date", label: "Date", width: 14, className: "mono", get: (d) => d.doc_date },
      { key: "supplier", label: "Supplier", width: 36, get: (d) => d.supplier, title: (d) => d.supplier },
      { key: "number", label: "Number", width: 24, className: "mono", get: (d) => d.doc_number,
        render: (d) => <Link className="comp-link" to={`/production/invoices?doc=${d.id}`}>{d.doc_number || "no number"}</Link> },
      { key: "pos", label: "Positions", width: 10, numeric: true, get: (d) => d.positions },
      { key: "net", label: "Net", width: 16, numeric: true, get: (d) => d.net,
        render: (d) => <>{pl(String(d.net))} {d.currency !== "PLN" ? d.currency : ""}</> },
    ]} />
  );
}

/** The overhead categories (decision 0091), with what the selected company's
 *  year put into each. Everybody reads it; an admin adds, renames and removes,
 *  and the API refuses otherwise. A category is removed only when no live
 *  position names it — open its row to see the documents that still do. */
function OverheadTab({ books }: { books: Books | null }) {
  const { isAdmin } = useAuth();
  const dialog = useDialog();
  const [rows, setRows] = useState<OverheadCategory[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState("");
  const [key, setKey] = useState("");
  const load = useCallback((signal?: AbortSignal) => {
    listOverheadCategories(signal).then((r) => { setRows(r); setErr(""); })
      .catch((e) => { if (!isAbortError(e)) setErr(errorMessage(e)); });
  }, []);
  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr("");
    try {
      await fn();
      forgetOverheadCategories();
      load();
      return true;
    } catch (e) {
      setErr(errorMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const add = async () => {
    if (await act(() => createOverheadCategory({ label: label.trim(), key: key.trim() }))) {
      setLabel("");
      setKey("");
    }
  };
  const rename = async (c: OverheadCategory) => {
    const next = await dialog.prompt(`New label for ${c.label}. The key ${c.key} stays: positions store it.`,
      { title: "Rename category", initial: c.label });
    if (next !== null && next.trim() && next.trim() !== c.label) await act(() => relabelOverheadCategory(c.key, next.trim()));
  };
  const remove = async (c: OverheadCategory) => {
    if (await dialog.confirm(`Remove the overhead category ${c.label}?`,
      { title: "Remove category", confirmLabel: "Remove", tone: "danger" })) {
      await act(() => deleteOverheadCategory(c.key));
    }
  };
  const net = (k: string) => Number(books?.overhead[k] ?? 0);
  const year = books?.year ?? "";
  const cols: Column<OverheadCategory>[] = [
    { key: "label", label: "Category", width: isAdmin ? 32 : 38, get: (c) => c.label,
      render: (c) => <>{c.label}{c.registered ? null : <> <span className="pill warn" title="Positions name this key, but it is not on the list. Add it again with this key.">not on the list</span></>}</> },
    { key: "key", label: "Key", width: isAdmin ? 20 : 22, className: "mono", get: (c) => c.key },
    { key: "net", label: `Net ${year} (PLN)`, width: 18, numeric: true, get: (c) => net(c.key),
      render: (c) => <>{net(c.key) ? pl(books?.overhead[c.key]) : "—"}</> },
    { key: "pos", label: "Positions", width: isAdmin ? 14 : 22, numeric: true, get: (c) => c.positions,
      title: () => "Live overhead positions that name it, in every company and year" },
    ...(isAdmin ? [{ key: "x", label: "", width: 16, className: "ctr", interactive: false, get: () => "",
      render: (c: OverheadCategory) => c.registered ? (
        <>
          <button type="button" className="icon-btn" title="Rename" disabled={busy}
            onClick={(e) => { e.stopPropagation(); void rename(c); }}>✎</button>
          {c.fallback ? null : (
            <button type="button" className="row-del" disabled={busy || c.positions > 0}
              title={c.positions > 0 ? `${c.positions} position(s) name it. Move them to another category first.` : `Remove ${c.label}`}
              onClick={(e) => { e.stopPropagation(); void remove(c); }}>&#x2715;</button>
          )}
        </>
      ) : null } as Column<OverheadCategory>] : []),
  ];
  return (
    <div className="card pad">
      <h2 className="card-title">Overhead categories</h2>
      <p className="muted dim">
        A position sent to company overhead names one of these. The net is this company's {year}; the positions
        are counted over every company and year. Open a row to see the documents that use it. A category is removed
        only when no position names it: move those positions on their invoices first. Other is where a position
        without a category goes, and stays.
      </p>
      <ErrorBanner message={err} />
      {rows === null && !err ? <Spinner label="Loading categories" /> : null}
      {rows !== null ? (
        <DataTable rows={rows} rowKey={(c) => c.key} columns={cols} empty="No categories."
          defaultSort={{ key: "net", dir: "desc" }}
          expand={(c) => <CategoryDocuments categoryKey={c.key} />} />
      ) : null}
      {isAdmin ? (
        <FieldRow>
          <Field label="New category">
            <input className="text" value={label} placeholder="e.g. Tools" onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label="Key" hint="What a position stores. It never changes. Empty: made from the label.">
            <input className="text mono" value={key} placeholder="tools"
              onChange={(e) => setKey(e.target.value.trim().toLowerCase())} />
          </Field>
          <button type="button" className="btn btn-primary btn-sm" disabled={busy || label.trim() === ""}
            onClick={() => void add()}>
            ＋ Add category
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
  // Two tabs, so the books stay one screen (user request 2026-10-15). The
  // tab is in the URL, as on every tabbed page.
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") === "overhead" ? "overhead" : "books";
  const setTab = (t: string) => setSearchParams(t === "books" ? {} : { tab: t }, { replace: true });

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

  const taxLabel = books?.income_tax ?? (books?.tax_form?.startsWith("cit") ? "cit" : "pit");
  // A company pays ZUS only as an employer (its sole shareholder pays his own,
  // outside the company), so its ZUS column shows only when it has a figure.
  const showZus = books?.income_tax !== "cit" || !!books?.months.some((m) => m.accountant.zus);
  const cols = useMemo<Column<BooksMonth>[]>(() => [
    { key: "month", label: "Month", width: 8, className: "mono", get: (m) => m.month },
    { key: "rev", label: "Revenue", width: showZus ? 11 : 16, numeric: true, get: (m) => Number(m.revenue_net), render: (m) => <>{pl(m.revenue_net)}</> },
    { key: "cost", label: "Costs", width: showZus ? 11 : 15, numeric: true, get: (m) => Number(m.costs_net), render: (m) => <>{pl(m.costs_net)}</> },
    { key: "inc", label: "Income", width: 11, numeric: true, get: (m) => Number(m.income), render: (m) => <>{pl(m.income)}</> },
    { key: "vat", label: "VAT est.", width: 10, numeric: true, get: (m) => Number(m.vat_estimate), render: (m) => <>{pl(m.vat_estimate)}</> },
    { key: "vat_a", label: "VAT (acct.)", width: 11, numeric: true, get: (m) => Number(m.accountant.vat?.amount ?? 0), render: (m) => <>{acc(m, "vat")}</> },
    { key: "tax", label: `${taxLabel.toUpperCase()} est.`, width: 9, numeric: true,
      get: (m) => Number(m.income_tax_estimate ?? 0), render: (m) => <>{pl(m.income_tax_estimate)}</>,
      title: (m) => m.tax_form ? `${TAX_FORM_TEXT[m.tax_form] ?? m.tax_form}${m.tax_rate ? `, effective ${m.tax_rate} %` : ""}` : "no tax form" },
    { key: "tax_a", label: `${taxLabel.toUpperCase()} (acct.)`, width: 11, numeric: true,
      get: (m) => Number(m.accountant[taxLabel]?.amount ?? 0), render: (m) => <>{acc(m, taxLabel)}</> },
    ...(showZus ? [{ key: "zus", label: "ZUS (acct.)", width: 9, numeric: true, get: (m: BooksMonth) => Number(m.accountant.zus?.amount ?? 0),
      render: (m: BooksMonth) => <>{acc(m, "zus")}</> } as Column<BooksMonth>] : []),
    { key: "int", label: "Interest", width: 9, numeric: true, get: (m) => Number(m.interest ?? 0),
      render: (m) => <>{Number(m.interest) ? pl(m.interest) : ""}</>,
      title: () => "Late-payment interest paid with the month's taxes. Never a cost." },
  ], [taxLabel, showZus]);

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1 className="page-title">Company books</h1>
          {books ? (
            <span className="toolbar-total">
              {books.year}: revenue {pl(books.totals.revenue_net)} · costs {pl(books.totals.costs_net)} · income {pl(books.totals.income)} PLN
              {Number(books.totals.interest) ? <> · interest paid {pl(books.totals.interest)} PLN</> : null}
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
        <div className="seg proj-tabs" role="tablist" aria-label="Company books section">
          {([["books", "Books"], ["overhead", "Overhead"]] as const).map(([t, text]) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""}
              onClick={() => setTab(t)}>
              {text}
            </button>
          ))}
        </div>
        {tab === "books" ? (
          <>
            <div className="card pad">
              <h2 className="card-title">Months</h2>
              {books === null ? <Spinner label="Computing…" /> : (
                <DataTable rows={books.months} rowKey={(m) => m.month} columns={cols} empty="—"
                  expand={(m) => <MonthPanel companyId={companyId} m={m} incomeTax={taxLabel} onSaved={() => load()} />} />
              )}
            </div>
            {companyId ? <AccountantCard companyId={companyId} /> : null}
            {books ? <TaxPeriodsCard key={`${companyId}-${books.income_tax}`} companyId={companyId} periods={books.tax_periods ?? []}
              incomeTax={books.income_tax} onSaved={() => load()} /> : null}
          </>
        ) : (
          <OverheadTab books={books} />
        )}
      </div>
    </div>
  );
}
