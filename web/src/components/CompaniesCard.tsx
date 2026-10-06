/** The companies the platform keeps books for, and what each prints as a seller
 *  (decision 0063). Admin only: the API sends the seller data to an admin alone,
 *  and refuses an edit from anyone else.
 *
 *  The NIP is the company's identity, so it is shown and never edited here — a
 *  different NIP is a different company.
 */
import { useEffect, useState } from "react";
import {
  applyHistory,
  getKsefStatus,
  runKsefSync,
  setKsefToken,
  type KsefStatus,
  errorMessage,
  isAbortError,
  listCompanies,
  lotHistory,
  setDrawCompany,
  stockBackfill,
  TAX_FORM_TEXT,
  updateCompany,
  type CompanyDetail,
  type HistoryPlan,
  type LotHistoryResult,
  type StockBackfillResult,
} from "../api";
import { useAuth } from "../auth";
import { plain } from "../format";
import DataTable, { type Column } from "./DataTable";
import { useDialog } from "./Dialog";
import Field, { CheckField, FieldGrid } from "./Field";
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
        <Field label="Sales invoices">
          <CheckField checked={!!draft.issues_invoices}
            onChange={(v) => setDraft((d) => ({ ...d, issues_invoices: v }))}>
            The platform writes this company's invoices
          </CheckField>
        </Field>
        <Field label="Income tax form" hint="Only for the estimate on the company page. A form by quarter (Company books) wins over this one.">
          <select className="text" value={draft.tax_form ?? ""}
            onChange={(e) => setDraft((d) => ({ ...d, tax_form: e.target.value }))}>
            <option value="">not stated (no estimate)</option>
            {Object.entries(TAX_FORM_TEXT).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select>
        </Field>
        {draft.tax_form === "lump" ? (
          <Field label="Lump sum rate (%)">
            <NumberInput className="text" value={draft.lump_rate ?? 0} min={0} step={0.5}
              onChange={(v) => setDraft((d) => ({ ...d, lump_rate: v }))} />
          </Field>
        ) : null}
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

/** Decision 0067: each company's KSeF token, for READING its invoices. The
 *  token is write-only: the API says whether one is set, never what it is. */
function KsefCard() {
  const dialog = useDialog();
  const [rows, setRows] = useState<KsefStatus[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [result, setResult] = useState("");
  const load = () => getKsefStatus().then(setRows).catch((e) => setErr(errorMessage(e)));
  useEffect(() => { void load(); }, []);

  const cols: Column<KsefStatus>[] = [
    { key: "company", label: "Company", width: 14, get: (r) => r.company },
    { key: "token", label: "Token", width: 9, get: (r) => (r.configured ? "set" : "none") },
    { key: "last", label: "Last sync", width: 17, className: "mono", get: (r) => r.last_sync_at?.slice(0, 16) ?? "never" },
    { key: "read", label: "Read up to", width: 18, className: "mono",
      get: (r) => [r.sales_read_to && `sales ${r.sales_read_to}`, r.purchases_read_to && `purch. ${r.purchases_read_to}`]
        .filter(Boolean).join(" · ") },
    { key: "error", label: "Last problem", width: 20, className: "muted", get: (r) => r.last_error },
    { key: "act", label: "", width: 22, interactive: false, get: () => "",
      render: (r) => (
        <span className="btn-row">
          <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={async () => {
            const token = await dialog.prompt(`KSeF token for ${r.company} (read-only token from the KSeF application):`,
              { title: r.configured ? "Replace the KSeF token" : "Set the KSeF token", secret: true });
            if (!token) return;
            setBusy(r.company_id);
            try { await setKsefToken(r.company_id, token); await load(); } catch (e) { setErr(errorMessage(e)); }
            finally { setBusy(null); }
          }}>
            {r.configured ? "Replace token…" : "Set token…"}
          </button>
          {r.configured ? (
            <button type="button" className="btn btn-primary btn-sm" disabled={busy !== null} onClick={async () => {
              setBusy(r.company_id);
              setErr("");
              try {
                const res = await runKsefSync(r.company_id);
                setResult(`${r.company}: ` + Object.entries(res.fetched).map(([k, v]) => `${k} ${v.listed} (${v.new} new)`).join(", ")
                  + `; ${res.downloaded} XML downloaded, ${res.linked} linked, ${res.recorded} recorded`
                  + (res.limit ? ` — ${res.limit}` : "")
                  + (res.refused?.length ? ` — refused: ${res.refused.map((x) => `${x.number}: ${x.why}`).join("; ")}` : ""));
                await load();
              } catch (e) { setErr(errorMessage(e)); }
              finally { setBusy(null); }
            }}>
              {busy === r.company_id ? "Syncing…" : "Sync now"}
            </button>
          ) : null}
        </span>
      ) },
  ];
  return (
    <div className="card pad">
      <h2>KSeF</h2>
      <p className="muted dim">
        Each company's read-only KSeF token. A sync reads its sales and purchase invoices into Production → KSeF,
        links the sales ones to their records and spends one or two of KSeF's 20 hourly queries.
      </p>
      <ErrorBanner message={err} />
      {result ? <div className="banner-ok">{result}</div> : null}
      {rows === null ? <Spinner label="Loading…" /> : (
        <DataTable rows={rows} rowKey={(r) => r.company_id} columns={cols} empty="No companies." />
      )}
    </div>
  );
}

type Unresolved = StockBackfillResult["unresolved_documents"][number];
const UNRESOLVED_COLUMNS: Column<Unresolved>[] = [
  { key: "date", label: "Date", width: 14, className: "mono", get: (d) => d.doc_date || "—" },
  { key: "supplier", label: "Supplier", width: 26, get: (d) => d.supplier },
  { key: "number", label: "Number", width: 30, className: "mono", get: (d) => d.doc_number || `#${d.document_id}` },
  { key: "why", label: "Why not decided", width: 30, className: "muted",
    get: (d) => (d.source === "conflict" ? `sources disagree: ${JSON.stringify(d.evidence)}`
      : d.has_text ? "no NIP or company name in the text" : "no PDF text and no JLC billing data") },
];

type UnresolvedDraw = StockBackfillResult["unresolved_draws"][number];

/** Names the company of one uncharged draw nothing else decides — a JLC
 *  warehouse pick or an external order's stock (decision 0064). */
function DrawCompanyPick({ draw, onDone }: { draw: UnresolvedDraw; onDone: () => void }) {
  const { companies } = useAuth();
  const dialog = useDialog();
  const [busy, setBusy] = useState(false);
  const pick = async (id: string) => {
    if (!id) return;
    const name = companies.find((c) => String(c.id) === id)?.name ?? id;
    if (!(await dialog.confirm(
      `Draw ${draw.id} (${draw.qty} × ${draw.lcsc || draw.mpn}) took ${name}'s stock? With stock per company, `
        + "units of the other company's lots move by in-house transfer.",
      { title: "Name whose stock", confirmLabel: "Write" }))) return;
    setBusy(true);
    try {
      await setDrawCompany(draw.id, Number(id), false);
      onDone();
    } catch (e) {
      await dialog.alert(errorMessage(e), { title: "Naming the company failed" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <select className="row-input" value="" disabled={busy} onChange={(e) => void pick(e.target.value)}>
      <option value="">{busy ? "Writing…" : "— whose stock —"}</option>
      {companies.map((c) => <option key={c.id} value={String(c.id)}>{c.name}</option>)}
    </select>
  );
}

type Proposed = HistoryPlan["transfers"][number];
const PROPOSED_COLUMNS: Column<Proposed>[] = [
  { key: "date", label: "Date", width: 12, className: "mono", get: (t) => t.date },
  { key: "dir", label: "Direction", width: 20, get: (t) => `${t.sender} → ${t.receiver}` },
  { key: "batch", label: "Receiving batch", width: 30, get: (t) => t.batch || "—" },
  { key: "ev", label: "Evidence", width: 12, get: (t) => (t.evidence === "lot" ? "JLC lot" : "balance") },
  { key: "lines", label: "Parts", width: 10, numeric: true, get: (t) => t.lines.length },
  { key: "value", label: "USD", width: 16, numeric: true, get: (t) => t.value_usd,
    render: (t) => <>{plain(t.value_usd)}</> },
];

/** Decision 0064: getting every stock record a company, then moving the
 *  history between the companies, then — on the Configuration tab — turning
 *  stock per company on. Each step is a dry run first. */
function StockSplitCard() {
  const dialog = useDialog();
  const [fill, setFill] = useState<StockBackfillResult | null>(null);
  const [fetchJlc, setFetchJlc] = useState(false);
  const [history, setHistory] = useState<HistoryPlan | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  const runFill = async (dryRun: boolean) => {
    if (!dryRun && !(await dialog.confirm(
      "Write the buyer of every document the evidence decides, and the company of every draw and adjustment?",
      { title: "Fill the companies", confirmLabel: "Write" }))) return;
    setBusy("fill");
    setErr("");
    try {
      setFill(await stockBackfill(dryRun, fetchJlc));
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy("");
    }
  };
  const runHistory = async (dryRun: boolean) => {
    if (!dryRun && !(await dialog.confirm(
      `Write ${history?.totals.transfers ?? 0} in-house transfers? Each one can be reversed on Production → Transfers.`,
      { title: "Write the history", confirmLabel: "Write" }))) return;
    setBusy("history");
    setErr("");
    try {
      setHistory(await applyHistory(dryRun));
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy("");
    }
  };
  const left = fill ? Object.entries(fill.still_without_company).filter(([, n]) => n > 0) : [];

  return (
    <div className="card pad">
      <h2>Stock per company</h2>
      <p className="muted dim">
        Each company draws parts only from its own stock once <b>Stock per company</b> is on
        (Configuration tab). First every purchase, draw and adjustment needs its company. Then the
        history needs the in-house transfers that moved stock between the companies.
      </p>
      <ErrorBanner message={err} />
      <h3>1. Name the companies</h3>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" disabled={!!busy} onClick={() => void runFill(true)}>
          {busy === "fill" ? "Checking…" : "Check"}
        </button>
        <button type="button" className="btn btn-primary btn-sm" disabled={!!busy || !fill}
          onClick={() => void runFill(false)}>
          Write what the evidence decides
        </button>
        <CheckField checked={fetchJlc} onChange={setFetchJlc}
          title="Reads the invoice of each JLC parts order with no stored billing data, through the stored JLC session">
          Ask JLC about parts orders
        </CheckField>
      </div>
      {fill ? (
        <>
          <p className="muted">
            {fill.dry_run ? "Would name" : "Named"} {fill.totals.documents} document(s) (
            {Object.entries(fill.totals.by_source).map(([k, n]) => `${n} by ${k}`).join(", ") || "none"}),{" "}
            {fill.totals.draws} draw(s) and {fill.totals.adjustments} adjustment(s).{" "}
            {left.length ? `Still without a company: ${left.map(([k, n]) => `${n} ${k}`).join(", ")}.`
              : "Every stock record names its company."}
          </p>
          {fill.unresolved_documents.length ? (
            <>
              <p className="muted dim">
                Set the buyer of these on Production → Invoices (open the document, Edit, Buyer).
              </p>
              <DataTable rows={fill.unresolved_documents} rowKey={(d) => d.document_id}
                columns={UNRESOLVED_COLUMNS} empty="None." />
            </>
          ) : null}
          {fill.unresolved_draws.length ? (
            <>
              <p className="muted dim">
                These draws are charged to no batch and bound to no lot of one company, so nothing says whose
                stock they took. Name it for each.
              </p>
              <DataTable rows={fill.unresolved_draws} rowKey={(d) => d.id}
                columns={[
                  { key: "date", label: "Date", width: 14, className: "mono", get: (d) => d.date || "—" },
                  { key: "part", label: "Part", width: 22, className: "mono", get: (d) => d.lcsc || d.mpn },
                  { key: "qty", label: "Qty", width: 10, numeric: true, get: (d) => d.qty },
                  { key: "note", label: "Note", width: 34, className: "muted", get: (d) => d.note },
                  { key: "pick", label: "Company", width: 20, interactive: false, get: () => "",
                    render: (d) => <DrawCompanyPick draw={d} onDone={() => void runFill(true)} /> },
                ]}
                empty="None." />
            </>
          ) : null}
        </>
      ) : null}
      <h3>2. Move the history</h3>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" disabled={!!busy} onClick={() => void runHistory(true)}>
          {busy === "history" ? "Planning…" : "Plan the transfers"}
        </button>
        <button type="button" className="btn btn-primary btn-sm" disabled={!!busy || !history || !history.transfers.length}
          onClick={() => void runHistory(false)}>
          Write them
        </button>
      </div>
      {history ? (
        <>
          <p className="muted">
            {history.written ? `Wrote ${history.written.length}, refused ${history.refused?.length ?? 0}. `
              : history.totals.transfers === 0 ? "Nothing to move. "
              : `${history.totals.transfers} transfer(s), ${history.totals.lines} part(s) (${history.totals.from_lots} from JLC lots), `
                + `${plain(history.totals.value_usd)} USD: `
                + Object.entries(history.totals.by_direction).map(([k, v]) => `${k} ${plain(v)}`).join(", ") + ". "}
            {history.totals.unexplained
              ? `${history.totals.unexplained} shortfall(s) neither company covers — usually a document with no buyer yet.`
              : ""}
          </p>
          {!history.written ? (
            <DataTable rows={history.transfers} rowKey={(t) => `${t.date}-${t.batch}-${t.evidence}-${t.sender}`}
              columns={PROPOSED_COLUMNS} empty="Nothing to move." />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

type LotBatch = LotHistoryResult["batches"][number];
const LOT_BATCH_COLUMNS: Column<LotBatch>[] = [
  { key: "batch", label: "Batch", width: 40, get: (b) => b.batch ?? (b.run_id ? `#${b.run_id}` : "no batch") },
  { key: "closed", label: "State", width: 14, get: (b) => (b.closed ? "closed" : "open"),
    render: (b) => (b.closed ? <span className="pill warn">closed</span> : <span className="muted">open</span>) },
  { key: "closed_cost", label: "Closed cost USD", width: 22, numeric: true, get: (b) => b.closed_cost_usd ?? 0,
    render: (b) => <>{b.closed ? plain(b.closed_cost_usd) : "—"}</> },
  { key: "change", label: "Change USD", width: 24, numeric: true, get: (b) => b.change_usd,
    render: (b) => <>{plain(b.change_usd)}</> },
];

type LotUncovered = LotHistoryResult["uncovered"][number];
const LOT_UNCOVERED_COLUMNS: Column<LotUncovered>[] = [
  { key: "date", label: "Date", width: 13, className: "mono", get: (u) => (u.date ?? "").slice(0, 10) || "—" },
  { key: "batch", label: "Batch", width: 25, get: (u) => u.batch ?? "no batch" },
  { key: "part", label: "Part", width: 26, className: "mono", get: (u) => u.label },
  { key: "qty", label: "Qty", width: 12, numeric: true, get: (u) => u.qty },
  { key: "uncovered", label: "In no lot", width: 12, numeric: true, get: (u) => u.uncovered },
  { key: "draw", label: "Draw", width: 12, className: "mono", get: (u) => `#${u.consumption_id}` },
];

/** Decision 0073: bind every live draw to the lots it came from, oldest
 *  first, and price it at their cost. A check first; the write changes
 *  closed batches too, so its confirmation is a danger one. */
function LotHistoryCard() {
  const dialog = useDialog();
  const [res, setRes] = useState<LotHistoryResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async (dryRun: boolean) => {
    if (!dryRun) {
      const closed = res?.batches.filter((b) => b.closed).length ?? 0;
      if (!(await dialog.confirm(
        `Bind ${res?.draws_bound ?? 0} draw(s) to their lots and give them the lots' cost? The cost of `
          + `${res?.batches.length ?? 0} batch(es) changes by ${plain(res?.change_usd ?? 0)} USD in total. `
          + `${closed} of these batches are closed, and their cost changes too.`,
        { title: "Bind draws to lots", confirmLabel: "Write", tone: "danger" }))) return;
    }
    setBusy(true);
    setErr("");
    try {
      setRes(await lotHistory(dryRun));
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const closed = res ? res.batches.filter((b) => b.closed).length : 0;

  return (
    <div className="card pad">
      <h2>Bind draws to lots</h2>
      <p className="muted dim">
        Each draw takes its parts from the purchase lots, oldest first, and takes their cost (decision 0073).
        This job binds the draws that have no lots yet, in date order. It changes the cost of closed batches too.
      </p>
      <ErrorBanner message={err} />
      <div className="btn-row">
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void run(true)}>
          {busy ? "Working…" : "Check"}
        </button>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy || !res || !res.dry_run || !res.draws_bound}
          onClick={() => void run(false)}>
          Write
        </button>
      </div>
      <p className="muted dim">
        You can turn on <b>Lot pricing (FIFO)</b> on the Configuration tab only when no draw is left without lots.
      </p>
      {res ? (
        <>
          <p className="muted">
            {res.dry_run ? "Would bind" : "Bound"} {res.draws_bound} draw(s). Total change {plain(res.change_usd)} USD
            over {res.batches.length} batch(es), {closed} closed.
            {res.batch_id ? ` Journal entry #${res.batch_id}.` : ""}
            {res.uncovered.length ? ` ${res.uncovered.length} draw(s) are in no lot.` : " Every draw is in a lot."}
          </p>
          {res.batches.length ? (
            <>
              <p className="muted dim">
                Change per batch. A closed batch keeps its closed cost, so its change shows as a variance.
              </p>
              <DataTable rows={res.batches} rowKey={(b) => String(b.run_id ?? "none")} columns={LOT_BATCH_COLUMNS}
                empty="No change." />
            </>
          ) : null}
          {res.uncovered.length ? (
            <>
              <p className="muted dim">
                No lot holds these draws. They keep their price. Enter the missing purchase, then check again.
              </p>
              <DataTable rows={res.uncovered} rowKey={(u) => u.consumption_id} columns={LOT_UNCOVERED_COLUMNS}
                empty="None." />
            </>
          ) : null}
        </>
      ) : null}
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
    <>
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
      <KsefCard />
      <StockSplitCard />
      <LotHistoryCard />
    </>
  );
}
