/** Sales invoices of a company that issues them (decision 0066).
 *
 *  The flow is 7Sigma's script's, with the platform as the register:
 *  1. A VAT, advance or correction invoice is written as a DRAFT with the next
 *     number of its series. Its XML is checked against the FA(3) schema when
 *     it is downloaded.
 *  2. The XML is uploaded in the KSeF Taxpayer Application on the invoice's
 *     date.
 *  3. "Issued in KSeF" records the KSeF number; with the official XML from
 *     KSeF the PDF carries the verification QR code.
 *  A proforma never goes to KSeF and is issued when it is written.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  cancelSalesInvoice,
  correctSalesInvoice,
  createSalesInvoice,
  errorMessage,
  generateFromTemplate,
  getSalesInvoice,
  isAbortError,
  issueSalesInvoice,
  listCustomers,
  listSalesInvoices,
  listSalesInvoiceFiles,
  listSalesProducts,
  listSalesTemplates,
  markSalesInvoicePaid,
  nextSalesNumber,
  salesInvoiceFilePath,
  salesInvoicePdfPath,
  salesInvoiceXmlPath,
  updateSalesInvoice,
  uploadSalesInvoiceFile,
  type CustomerRow,
  type SalesInvoiceRow,
  type SalesProductRow,
  type SalesTemplate,
} from "../api";
import { useAuth } from "../auth";
import AutoTextarea from "../components/AutoTextarea";
import DataTable, { type Column } from "../components/DataTable";
import FoldSection, { StatChip, NarrowChip } from "../components/FoldSection";
import { useDialog } from "../components/Dialog";
import Field, { CheckField, FieldGrid, FieldRow } from "../components/Field";
import FilePick from "../components/FilePick";
import { blankLine, CustomerSelect, linesBody, linesReady, SalesLinesEditor, type DraftLine } from "../components/invoices/SalesLines";
import { ImportRegisterDialog, RecordHistoryDialog } from "../components/invoices/SalesRegisterDialogs";
import SalesTemplateDialog from "../components/invoices/SalesTemplateDialog";
import { INVOICE_LINE_COLUMNS as LINE_COLUMNS } from "../components/PrintedInvoice";
import RecordFiles from "../components/RecordFiles";
import AccountantMark from "../components/AccountantMark";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { pl, today } from "../format";
import { absoluteFileUrl, fileHref } from "../viewkind";
import PageShell from "../components/PageShell";

const KIND_TEXT: Record<string, string> = {
  vat: "VAT", proforma: "proforma", correction: "correction", advance: "advance", settlement: "settlement",
};

/** An imported document's payment is what the old register said, and it
 *  rarely said: "payment not recorded" is the honest word, never "overdue". */
const imported = (r: SalesInvoiceRow) => r.source.startsWith("script");

function stateOf(r: SalesInvoiceRow): string {
  if (r.status === "draft") return "draft";
  if (r.status === "cancelled") return "cancelled";
  if (r.kind === "proforma") return "proforma";
  if (r.paid) return "paid";
  if (imported(r)) return "not recorded";
  return r.overdue ? "overdue" : "unpaid";
}

const COLUMNS: Column<SalesInvoiceRow>[] = [
  { key: "date", label: "Date", width: 9, className: "mono", get: (r) => r.issue_date },
  { key: "number", label: "Number", width: 13, className: "mono", get: (r) => r.number },
  { key: "kind", label: "Kind", width: 8, get: (r) => KIND_TEXT[r.kind] ?? r.kind },
  { key: "buyer", label: "Buyer", width: 21, get: (r) => r.buyer_name },
  { key: "net", label: "Net (PLN)", width: 10, numeric: true, get: (r) => Number(r.net_total),
    render: (r) => <>{pl(r.net_total)}</> },
  { key: "gross", label: "Gross (PLN)", width: 10, numeric: true, get: (r) => Number(r.gross_total),
    render: (r) => <>{pl(r.gross_total)}</> },
  { key: "due", label: "Due", width: 9, className: "mono", get: (r) => (r.paid ? r.paid_date : r.due_date) || "" },
  { key: "state", label: "State", width: 14, get: stateOf,
    title: (r) => (stateOf(r) === "not recorded" ? "Imported from the old register, which did not record the payment" : stateOf(r)),
    render: (r) => <StatusPill status={stateOf(r)} /> },
  { key: "ksef", label: "KSeF", width: 6, get: (r) => (r.ksef_number ? (r.has_qr ? "QR" : "yes") : ""),
    title: (r) => r.ksef_number || "not in KSeF" },
];

/** The printed documents filed with an invoice (decision 0077). */
function InvoiceFiles({ id }: { id: number }) {
  const list = useCallback((signal?: AbortSignal) => listSalesInvoiceFiles(id, signal), [id]);
  const upload = useCallback((file: File) => uploadSalesInvoiceFile(id, file), [id]);
  return <RecordFiles list={list} upload={upload} pathOf={(fileId) => salesInvoiceFilePath(id, fileId)} label="Documents" />;
}

/** One invoice, opened under its row. Its positions use the columns of the
 *  supplier document's printed invoice (decision 0084). */
function InvoicePanel({ id, onChanged }: { id: number; onChanged: () => void }) {
  const dialog = useDialog();
  const [inv, setInv] = useState<SalesInvoiceRow | null>(null);
  const [err, setErr] = useState("");
  const [ksef, setKsef] = useState("");
  const [xml, setXml] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    getSalesInvoice(id).then(setInv).catch((e) => setErr(errorMessage(e)));
  }, [id]);
  useEffect(load, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr("");
    try {
      await fn();
      load();
      onChanged();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!inv) return <div className="user-detail">{err ? <ErrorBanner message={err} /> : <Spinner label="Loading…" />}</div>;
  const b = inv.body;
  const pdfName = `${inv.number.replace(/[^0-9A-Za-z]+/g, "-")}.pdf`;
  const before = b?.correction?.before_lines ?? [];
  // A document issued elsewhere, recorded as printed (decision 0077): the
  // platform never sends it to KSeF and never corrects it.
  const recorded = inv.source.startsWith("import: document");
  return (
    <div className="user-detail">
      <ErrorBanner message={err} />
      <p className="muted">
        {b?.buyer.name} · NIP {b?.buyer.nip || "—"} · {b?.buyer.address_l1} {b?.buyer.address_l2}
        {inv.ksef_number ? <> · KSeF <span className="mono">{inv.ksef_number}</span></> : null}
        {b?.correction ? <> · corrects {b.correction.of_number} ({b.correction.reason || "no reason given"})</> : null}
      </p>
      {before.length ? (
        <>
          <p className="muted dim">Before the correction</p>
          <DataTable rows={before} rowKey={(l) => `b${l.position}`} columns={LINE_COLUMNS} empty="—" />
          <p className="muted dim">After the correction</p>
        </>
      ) : null}
      {inv.kind === "advance" && b?.order ? (
        <>
          <p className="muted dim">The order the advance is paid against</p>
          <DataTable rows={b.order.lines} rowKey={(l) => `o${l.position}`} columns={LINE_COLUMNS} empty="—" />
          <p className="muted">
            Advance received: {pl(b.totals.gross)} PLN gross ({pl(b.totals.net)} net, {pl(b.totals.vat)} VAT)
          </p>
        </>
      ) : (
        <DataTable rows={b?.lines ?? []} rowKey={(l) => `l${l.position}`} columns={LINE_COLUMNS} empty="No positions." />
      )}
      {(b?.notes ?? []).length ? <p className="muted dim">Notes: {(b?.notes ?? []).join("; ")}</p> : null}
      {recorded ? (
        <p className="muted dim">Issued outside the platform; recorded from the printed document filed below.</p>
      ) : null}
      <div className="btn-row">
        <AccountantMark companyId={inv.company_id} kind="sales_invoice" id={inv.id} state={inv.accountant}
                        onChange={() => { load(); onChanged(); }} />
      </div>
      <div className="btn-row">
        <InvoiceFiles id={inv.id} />
      </div>
      <div className="btn-row">
        <a className="btn btn-sm" href={fileHref(salesInvoicePdfPath(inv.id), pdfName)} target="_blank" rel="noreferrer">
          PDF
        </a>
        {inv.kind !== "proforma" && !recorded ? (
          <a className="btn btn-sm" href={absoluteFileUrl(salesInvoiceXmlPath(inv.id))}>
            XML for KSeF
          </a>
        ) : null}
        {inv.status === "issued" && !inv.paid && inv.kind !== "proforma" ? (
          <button type="button" className="btn btn-sm" disabled={busy} onClick={async () => {
            const day = await dialog.prompt("Paid on (YYYY-MM-DD):", { title: "Mark paid" });
            if (day) await act(() => markSalesInvoicePaid(inv.id, day));
          }}>
            Mark paid…
          </button>
        ) : null}
        {inv.status === "issued" && !recorded && (inv.kind === "vat" || inv.kind === "advance") ? (
          <button type="button" className="btn btn-sm" disabled={busy} onClick={async () => {
            const reason = await dialog.prompt("Why is it corrected?", { title: "Correction" });
            if (reason) await act(() => correctSalesInvoice(inv.id, reason));
          }}>
            Correction…
          </button>
        ) : null}
        {inv.status === "draft" ? (
          <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={async () => {
            if (await dialog.confirm(`Cancel the draft ${inv.number}? It was never sent to KSeF, and its number is freed.`,
              { title: "Cancel draft", confirmLabel: "Cancel draft", tone: "danger" })) {
              await act(() => cancelSalesInvoice(inv.id));
            }
          }}>
            Cancel draft
          </button>
        ) : null}
      </div>
      {inv.kind !== "proforma" && (inv.status === "draft" || (inv.status === "issued" && !inv.has_qr)) ? (
        <FieldRow>
          <Field label="KSeF number" hint="From the KSeF Taxpayer Application, once it accepted the XML.">
            <input className="text mono" value={ksef} onChange={(e) => setKsef(e.target.value.trim())}
                   placeholder="8513262910-20261004-0123456789AB-CD" />
          </Field>
          <Field group label="Official XML from KSeF" hint="Optional. Its hash puts the QR code on the PDF.">
            <FilePick accept=".xml" onPick={(files) => setXml(files[0] ?? null)}>
              {xml ? xml.name : "Choose the XML…"}
            </FilePick>
          </Field>
          <button type="button" className="btn btn-primary btn-sm" disabled={busy || !ksef}
                  onClick={() => void act(() => issueSalesInvoice(inv.id, ksef, xml))}>
            Issued in KSeF
          </button>
        </FieldRow>
      ) : null}
      {inv.status === "draft" && inv.kind === "vat" ? (
        <p className="muted dim">
          Upload the XML in the KSeF Taxpayer Application on {inv.issue_date}, the invoice's date. Sent later,
          KSeF marks it as an offline invoice.
        </p>
      ) : null}
      {inv.status === "draft" && b?.lines.some((l) => l.vat_rate === "zw") ? (
        <div className="btn-row">
          {b.exemption?.basis ? (
            <span className="muted dim">Legal basis of the exemption: {b.exemption.basis}.</span>
          ) : (
            <span className="pill warn">KSeF refuses a zw position with no legal basis</span>
          )}
          <button type="button" className="btn btn-sm" disabled={busy} onClick={async () => {
            const basis = await dialog.prompt("The legal basis of the exemption, e.g. art. 113 ust. 1 ustawy o VAT:", {
              title: "Legal basis of the exemption", initial: b.exemption?.basis ?? "", maxLength: 240,
            });
            if (basis?.trim()) await act(() => updateSalesInvoice(inv.id, { exemption_basis: basis.trim() }));
          }}>
            {b.exemption?.basis ? "Change basis…" : "Set basis…"}
          </button>
        </div>
      ) : null}
      {inv.status === "draft" ? (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={async () => {
          const day = await dialog.prompt("New issue date (YYYY-MM-DD):", { title: "Re-date the draft" });
          // The issue date only. The server moves a VAT draft's sale date with
          // it when they were the same day, keeps a correction's and an
          // advance's, and gives the draft the new month's number.
          if (day) await act(() => updateSalesInvoice(inv.id, { issue_date: day }));
        }}>
          Re-date…
        </button>
      ) : null}
    </div>
  );
}

function NewInvoiceCard({ customers, products, onDone, version }: {
  customers: CustomerRow[]; products: SalesProductRow[]; onDone: () => void; version: number;
}) {
  const { companies } = useAuth();
  const sellers = companies.filter((c) => c.issues_invoices);
  const [companyId, setCompanyId] = useState<number | "">(sellers[0]?.id ?? "");
  const [kind, setKind] = useState<"vat" | "proforma" | "advance">("vat");
  const [customerId, setCustomerId] = useState<number | "">("");
  const [issue, setIssue] = useState(today);
  const [sale, setSale] = useState(today);
  const [lines, setLines] = useState<DraftLine[]>([blankLine()]);
  const [advance, setAdvance] = useState("");
  const [paid, setPaid] = useState(false);
  const [extra, setExtra] = useState("");
  const [exemption, setExemption] = useState("");
  const [number, setNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (companyId === "") return;
    nextSalesNumber(Number(companyId), kind, issue).then((r) => setNumber(r.number)).catch(() => setNumber(""));
  }, [companyId, kind, issue, version]);

  if (!sellers.length) return null;
  const body = linesBody(lines);
  // An exempt position (zw) names the legal basis; FA(3) refuses it without.
  const exempt = body.some((l) => l.vat_rate === "zw");
  const ready = companyId !== "" && customerId !== "" && linesReady(lines) && (kind !== "advance" || advance !== "")
    && (!exempt || exemption.trim() !== "");

  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      await createSalesInvoice({
        company_id: Number(companyId), kind, customer_id: Number(customerId), issue_date: issue, sale_date: sale,
        ...(kind === "advance" ? { order_lines: body, advance_gross: advance } : { lines: body }),
        payment: { paid, paid_date: paid ? sale : null },
        extra_info: extra.split("\n").map((x) => x.trim()).filter(Boolean),
        ...(exempt ? { exemption_basis: exemption.trim() } : {}),
      });
      setLines([blankLine()]);
      setAdvance("");
      setExtra("");
      onDone();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card pad edit-card">
      <h2 className="card-title">New invoice</h2>
      <p className="muted dim">
        A VAT or advance invoice is saved as a draft for KSeF. A proforma is issued at once and never goes to KSeF.
        Next number: <b className="mono">{number || "—"}</b>
      </p>
      <ErrorBanner message={err} />
      <FieldGrid>
        {sellers.length > 1 ? (
          <Field label="Seller">
            <select className="text" value={companyId} onChange={(e) => setCompanyId(Number(e.target.value))}>
              {sellers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        ) : null}
        <Field label="Kind">
          <select className="text" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            <option value="vat">VAT invoice</option>
            <option value="proforma">Proforma</option>
            <option value="advance">Advance (ZAL)</option>
          </select>
        </Field>
        <Field label="Buyer">
          <CustomerSelect customers={customers} value={customerId} onChange={setCustomerId} />
        </Field>
        <Field label="Issue date" hint="Upload the VAT XML to KSeF on this day.">
          <input className="text" type="date" value={issue} onChange={(e) => setIssue(e.target.value)} />
        </Field>
        <Field label={kind === "advance" ? "Advance received on" : "Sale date"}>
          <input className="text" type="date" value={sale} onChange={(e) => setSale(e.target.value)} />
        </Field>
        {kind === "advance" ? (
          <Field label="Advance received (gross PLN)">
            <input className="text num" value={advance} inputMode="decimal" onChange={(e) => setAdvance(e.target.value)} />
          </Field>
        ) : null}
      </FieldGrid>
      <p className="muted dim">{kind === "advance" ? "The order the advance is paid against:" : "Positions:"}</p>
      <SalesLinesEditor lines={lines} products={products} onChange={setLines} />
      <FieldGrid>
        {exempt ? (
          <Field label="Legal basis of the exemption" hint="Printed for a zw position, e.g. art. 113 ust. 1 ustawy o VAT." wide>
            <input className="text" value={exemption} maxLength={240} onChange={(e) => setExemption(e.target.value)} />
          </Field>
        ) : null}
        <Field label="Extra lines on the invoice" hint="One per line, e.g. the contract it is issued under." wide>
          <AutoTextarea className="text" rows={2} value={extra} onChange={(e) => setExtra(e.target.value)} />
        </Field>
      </FieldGrid>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={() => setLines([...lines, blankLine()])}>Add a position</button>
        {kind !== "advance" ? (
          <CheckField checked={paid} onChange={setPaid}>Already paid</CheckField>
        ) : null}
        <button type="button" className="btn btn-primary btn-sm" disabled={!ready || busy} onClick={() => void save()}>
          {busy ? "Saving…" : kind === "proforma" ? "Issue the proforma" : "Save the draft"}
        </button>
      </div>
    </div>
  );
}

function RecurringCard({ templates, customers, products, onDone }: {
  templates: SalesTemplate[]; customers: CustomerRow[]; products: SalesProductRow[]; onDone: () => void;
}) {
  const { companies } = useAuth();
  const [month, setMonth] = useState(() => today().slice(0, 7));
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [writing, setWriting] = useState<SalesTemplate | "new" | null>(null);
  const name = (id: number | null) => customers.find((c) => c.id === id)?.name ?? "—";
  const cols: Column<SalesTemplate>[] = [
    { key: "key", label: "Key", width: 12, className: "mono", get: (t) => t.key },
    { key: "buyer", label: "Buyer", width: 22, get: (t) => name(t.customer_id) },
    { key: "what", label: "Positions", width: 30, get: (t) => t.lines.map((l) => `${l.name} × ${l.qty}`).join("; ") },
    { key: "day", label: "Day", width: 8, get: (t) => t.day },
    { key: "active", label: "Active", width: 8, get: (t) => (t.active ? "yes" : "no") },
    { key: "go", label: "", width: 20, interactive: false, get: () => "",
      render: (t) => (
        <>
          {t.active ? (
            <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={async (e) => {
              e.stopPropagation();
              setBusy(t.id);
              setErr("");
              try {
                await generateFromTemplate(t.id, month);
                onDone();
              } catch (ex) {
                setErr(errorMessage(ex));
              } finally {
                setBusy(null);
              }
            }}>
              {busy === t.id ? "…" : `Draft for ${month}`}
            </button>
          ) : null}
          {" "}
          <button type="button" className="btn btn-sm" onClick={() => setWriting(t)}>Edit</button>
        </>
      ) },
  ];
  // A company that issues nothing here has no recurring invoices either.
  const canWrite = companies.some((c) => c.issues_invoices);
  if (!templates.length && !canWrite) return null;
  return (
    <>
      <FoldSection
        title="Recurring invoices"
        count={templates.length}
        foldKey="sales:recurring"
        chips={<StatChip n={templates.filter((t) => t.active).length} tone="ok">active</StatChip>}
        actions={canWrite ? (
          <button type="button" className="btn btn-sm" onClick={() => setWriting("new")}>New template…</button>
        ) : null}
      >
        <p className="muted dim">A draft dated the template's day of the month, with the next number.</p>
        <ErrorBanner message={err} />
        <FieldRow>
          <Field label="Month">
            <input className="text" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
          </Field>
        </FieldRow>
        <DataTable rows={templates} rowKey={(t) => t.id} columns={cols} empty="No recurring invoices." />
      </FoldSection>
      {writing ? (
        <SalesTemplateDialog
          template={writing === "new" ? null : writing}
          customers={customers}
          products={products}
          onClose={(changed) => {
            setWriting(null);
            if (changed) onDone();
          }}
        />
      ) : null}
    </>
  );
}

export default function SalesInvoices() {
  const [rows, setRows] = useState<SalesInvoiceRow[] | null>(null);
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [products, setProducts] = useState<SalesProductRow[]>([]);
  const [templates, setTemplates] = useState<SalesTemplate[]>([]);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [narrow, setNarrow] = useState("");
  const { isAdmin } = useAuth();
  const [writing, setWriting] = useState<"history" | "import" | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    setVersion((v) => v + 1);
    listSalesInvoices(signal).then((r) => { setRows(r); setError(""); })
      .catch((e) => { if (!isAbortError(e)) setError(errorMessage(e)); });
    listCustomers(signal).then(setCustomers).catch(() => {});
    listSalesProducts(signal).then(setProducts).catch(() => {});
    listSalesTemplates(signal).then(setTemplates).catch(() => {});
  }, []);
  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  const totals = useMemo(() => {
    const open = (rows ?? []).filter((r) => r.status === "issued" && r.kind !== "proforma" && !r.paid
                                     && !imported(r));
    return { drafts: (rows ?? []).filter((r) => r.status === "draft").length,
             open: open.reduce((s, r) => s + Number(r.amount_due), 0) };
  }, [rows]);

  return (
    <PageShell>
      <div className="toolbar">
        <h1>Sales invoices</h1>
        {rows ? (
          <span className="toolbar-total">
            {rows.length} documents · {totals.drafts} draft(s) · {pl(totals.open)} PLN unpaid on the platform
          </span>
        ) : null}
        {isAdmin ? (
          <>
            <button type="button" className="btn btn-sm" onClick={() => setWriting("history")}
              title="A document a company issued before the platform or KSeF wrote its invoices">
              Record issued elsewhere…
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setWriting("import")}
              title="The files of the old invoicing script">
              Import register…
            </button>
          </>
        ) : null}
      </div>
      <ErrorBanner message={error} />
      {writing === "history" ? (
        <RecordHistoryDialog customers={customers}
          onClose={(c) => { setWriting(null); if (c) load(); }} />
      ) : null}
      {writing === "import" ? (
        <ImportRegisterDialog onClose={(c) => { setWriting(null); if (c) load(); }} />
      ) : null}
      <NewInvoiceCard customers={customers} products={products} onDone={() => load()} version={version} />
      <RecurringCard templates={templates} customers={customers} products={products} onDone={() => load()} />
      <div className="card pad">
        <h2 className="card-title">Register</h2>
        {rows === null ? (
          <Spinner label="Loading invoices…" />
        ) : (
          <>
            <div className="stat-row">
              {([["overdue", "err"], ["unpaid", "warn"], ["draft", "warn"], ["paid", "ok"]] as const).map(([word, tone]) => (
                <NarrowChip key={word} n={rows.filter((r) => stateOf(r) === word).length}
                  tone={tone} value={word} current={narrow} onNarrow={setNarrow}>{word}</NarrowChip>
              ))}
            </div>
            <DataTable
              rows={narrow ? rows.filter((r) => stateOf(r) === narrow) : rows}
              rowKey={(r) => r.id}
              columns={COLUMNS}
              empty={narrow ? "No invoice in this state." : "No invoices."}
              defaultSort={{ key: "date", dir: "desc" }}
              expand={(r) => <InvoicePanel id={r.id} onChanged={() => load()} />}
            />
          </>
        )}
      </div>
    </PageShell>
  );
}
