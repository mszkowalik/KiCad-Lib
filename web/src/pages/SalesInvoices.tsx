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
  listSalesProducts,
  listSalesTemplates,
  markSalesInvoicePaid,
  nextSalesNumber,
  salesInvoicePdfPath,
  salesInvoiceXmlPath,
  updateSalesInvoice,
  type CustomerRow,
  type SalesInvoiceRow,
  type SalesLine,
  type SalesProductRow,
  type SalesTemplate,
} from "../api";
import { useAuth } from "../auth";
import AutoTextarea from "../components/AutoTextarea";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import Field, { CheckField, FieldGrid, FieldRow } from "../components/Field";
import FilePick from "../components/FilePick";
import { ErrorBanner, Spinner } from "../components/Ui";
import { absoluteFileUrl, fileHref } from "../viewkind";

const KIND_TEXT: Record<string, string> = {
  vat: "VAT", proforma: "proforma", correction: "correction", advance: "advance", settlement: "settlement",
};
const RATES = ["23", "8", "5", "0 KR", "0 WDT", "0 EX", "zw", "oo", "np I", "np II"];

function pl(amount: string | number | null | undefined): string {
  const n = Number(amount ?? 0);
  return n.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

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

const STATE_TONE: Record<string, string> = {
  draft: "warn", cancelled: "neutral", proforma: "neutral", paid: "ok", overdue: "err", unpaid: "warn",
  "not recorded": "neutral",
};

const COLUMNS: Column<SalesInvoiceRow>[] = [
  { key: "date", label: "Date", width: 9, className: "mono", get: (r) => r.issue_date },
  { key: "number", label: "Number", width: 13, className: "mono", get: (r) => r.number },
  { key: "kind", label: "Kind", width: 8, get: (r) => KIND_TEXT[r.kind] ?? r.kind },
  { key: "buyer", label: "Buyer", width: 26, get: (r) => r.buyer_name },
  { key: "net", label: "Net (PLN)", width: 10, numeric: true, get: (r) => Number(r.net_total),
    render: (r) => <>{pl(r.net_total)}</> },
  { key: "gross", label: "Gross (PLN)", width: 10, numeric: true, get: (r) => Number(r.gross_total),
    render: (r) => <>{pl(r.gross_total)}</> },
  { key: "due", label: "Due", width: 9, className: "mono", get: (r) => (r.paid ? r.paid_date : r.due_date) || "" },
  { key: "state", label: "State", width: 9, get: stateOf,
    title: (r) => (stateOf(r) === "not recorded" ? "Imported from the old register, which did not record the payment" : stateOf(r)),
    render: (r) => <span className={`pill ${STATE_TONE[stateOf(r)] ?? "neutral"}`}>{stateOf(r)}</span> },
  { key: "ksef", label: "KSeF", width: 6, get: (r) => (r.ksef_number ? (r.has_qr ? "QR" : "yes") : ""),
    title: (r) => r.ksef_number || "not in KSeF" },
];

const LINE_COLUMNS: Column<SalesLine>[] = [
  { key: "pos", label: "Lp.", width: 5, numeric: true, get: (l) => l.position ?? 0 },
  { key: "name", label: "Name", width: 39, get: (l) => l.name },
  { key: "qty", label: "Qty", width: 8, numeric: true, get: (l) => Number(l.qty) },
  { key: "unit", label: "Unit", width: 6, get: (l) => l.unit },
  { key: "unit_net", label: "Unit net", width: 11, numeric: true, get: (l) => Number(l.unit_net),
    render: (l) => <>{pl(l.unit_net)}</> },
  { key: "net", label: "Net", width: 11, numeric: true, get: (l) => Number(l.net ?? 0), render: (l) => <>{pl(l.net)}</> },
  { key: "rate", label: "VAT", width: 7, get: (l) => l.vat_rate },
  { key: "gross", label: "Gross", width: 13, numeric: true, get: (l) => Number(l.gross ?? 0),
    render: (l) => <>{pl(l.gross)}</> },
];

/** One invoice, opened under its row. */
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
      <div className="btn-row">
        <a className="btn btn-sm" href={fileHref(salesInvoicePdfPath(inv.id), pdfName)} target="_blank" rel="noreferrer">
          PDF
        </a>
        {inv.kind !== "proforma" ? (
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
        {inv.status === "issued" && (inv.kind === "vat" || inv.kind === "advance") ? (
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
          <Field label="Official XML from KSeF" hint="Optional. Its hash puts the QR code on the PDF.">
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
      {inv.status === "draft" ? (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={async () => {
          const day = await dialog.prompt("New issue date (YYYY-MM-DD):", { title: "Re-date the draft" });
          if (day) await act(() => updateSalesInvoice(inv.id, { issue_date: day, sale_date: day }));
        }}>
          Re-date…
        </button>
      ) : null}
    </div>
  );
}

interface DraftLine { name: string; qty: string; unit_net: string; vat_rate: string; unit: string }
const blank = (): DraftLine => ({ name: "", qty: "1", unit_net: "", vat_rate: "23", unit: "szt." });

function NewInvoiceCard({ customers, products, onDone, version }: {
  customers: CustomerRow[]; products: SalesProductRow[]; onDone: () => void; version: number;
}) {
  const { companies } = useAuth();
  const sellers = companies.filter((c) => c.issues_invoices);
  const [companyId, setCompanyId] = useState<number | "">(sellers[0]?.id ?? "");
  const [kind, setKind] = useState<"vat" | "proforma" | "advance">("vat");
  const [customerId, setCustomerId] = useState<number | "">("");
  const today = new Date().toISOString().slice(0, 10);
  const [issue, setIssue] = useState(today);
  const [sale, setSale] = useState(today);
  const [lines, setLines] = useState<DraftLine[]>([blank()]);
  const [advance, setAdvance] = useState("");
  const [paid, setPaid] = useState(false);
  const [extra, setExtra] = useState("");
  const [number, setNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (companyId === "") return;
    nextSalesNumber(Number(companyId), kind, issue).then((r) => setNumber(r.number)).catch(() => setNumber(""));
  }, [companyId, kind, issue, version]);

  if (!sellers.length) return null;
  const setLine = (i: number, patch: Partial<DraftLine>) =>
    setLines(lines.map((l, j) => {
      if (j !== i) return l;
      const next = { ...l, ...patch };
      const p = patch.name !== undefined ? products.find((x) => x.name === patch.name) : undefined;
      return p ? { ...next, unit_net: p.unit_net, vat_rate: p.vat_rate, unit: p.unit } : next;
    }));
  const typed = lines.filter((l) => l.name.trim() && l.unit_net !== "");
  const ready = companyId !== "" && customerId !== "" && typed.length > 0 && (kind !== "advance" || advance !== "");

  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      const body = typed.map((l) => ({ ...l, qty: l.qty || "1" }));
      await createSalesInvoice({
        company_id: Number(companyId), kind, customer_id: Number(customerId), issue_date: issue, sale_date: sale,
        ...(kind === "advance" ? { order_lines: body, advance_gross: advance } : { lines: body }),
        payment: { paid, paid_date: paid ? sale : null },
        extra_info: extra.split("\n").map((x) => x.trim()).filter(Boolean),
      });
      setLines([blank()]);
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
          <select className="text" value={customerId} onChange={(e) => setCustomerId(e.target.value === "" ? "" : Number(e.target.value))}>
            <option value="">—</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>{c.legal_name || c.name}{c.tax_id ? ` · ${c.tax_id}` : ""}</option>
            ))}
          </select>
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
      <datalist id="sales-products">
        {products.map((p) => <option key={p.id} value={p.name} />)}
      </datalist>
      {lines.map((l, i) => (
        <FieldRow key={i}>
          <Field label={i === 0 ? "Name" : undefined} wide>
            <input className="text" list="sales-products" value={l.name} onChange={(e) => setLine(i, { name: e.target.value })} />
          </Field>
          <Field label={i === 0 ? "Qty" : undefined}>
            <input className="text num-input" value={l.qty} inputMode="decimal" onChange={(e) => setLine(i, { qty: e.target.value })} />
          </Field>
          <Field label={i === 0 ? "Unit net (PLN)" : undefined}>
            <input className="text num-input" value={l.unit_net} inputMode="decimal" onChange={(e) => setLine(i, { unit_net: e.target.value })} />
          </Field>
          <Field label={i === 0 ? "VAT" : undefined}>
            <select className="text" value={l.vat_rate} onChange={(e) => setLine(i, { vat_rate: e.target.value })}>
              {RATES.map((r) => <option key={r} value={r}>{/^\d+$/.test(r) ? `${r}%` : r}</option>)}
            </select>
          </Field>
          <Field label={i === 0 ? "Unit" : undefined}>
            <input className="text num-input" value={l.unit} onChange={(e) => setLine(i, { unit: e.target.value })} />
          </Field>
          {lines.length > 1 ? (
            <button type="button" className="btn btn-sm" onClick={() => setLines(lines.filter((_x, j) => j !== i))}>
              Remove
            </button>
          ) : null}
        </FieldRow>
      ))}
      <FieldGrid>
        <Field label="Extra lines on the invoice" hint="One per line, e.g. the contract it is issued under." wide>
          <AutoTextarea className="text" rows={2} value={extra} onChange={(e) => setExtra(e.target.value)} />
        </Field>
      </FieldGrid>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={() => setLines([...lines, blank()])}>Add a position</button>
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

function RecurringCard({ templates, customers, onDone }: {
  templates: SalesTemplate[]; customers: CustomerRow[]; onDone: () => void;
}) {
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const name = (id: number | null) => customers.find((c) => c.id === id)?.name ?? "—";
  const cols: Column<SalesTemplate>[] = [
    { key: "key", label: "Key", width: 12, className: "mono", get: (t) => t.key },
    { key: "buyer", label: "Buyer", width: 22, get: (t) => name(t.customer_id) },
    { key: "what", label: "Positions", width: 34, get: (t) => t.lines.map((l) => `${l.name} × ${l.qty}`).join("; ") },
    { key: "day", label: "Day", width: 8, get: (t) => t.day },
    { key: "active", label: "Active", width: 8, get: (t) => (t.active ? "yes" : "no") },
    { key: "go", label: "", width: 16, interactive: false, get: () => "",
      render: (t) => t.active ? (
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
      ) : null },
  ];
  if (!templates.length) return null;
  return (
    <div className="card pad">
      <h2 className="card-title">Recurring invoices</h2>
      <p className="muted dim">A draft dated the template's day of the month, with the next number.</p>
      <ErrorBanner message={err} />
      <FieldRow>
        <Field label="Month">
          <input className="text" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
        </Field>
      </FieldRow>
      <DataTable rows={templates} rowKey={(t) => t.id} columns={cols} empty="No recurring invoices." />
    </div>
  );
}

export default function SalesInvoices() {
  const [rows, setRows] = useState<SalesInvoiceRow[] | null>(null);
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [products, setProducts] = useState<SalesProductRow[]>([]);
  const [templates, setTemplates] = useState<SalesTemplate[]>([]);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);

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
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1 className="page-title">Sales invoices</h1>
          {rows ? (
            <span className="toolbar-total">
              {rows.length} documents · {totals.drafts} draft(s) · {pl(totals.open)} PLN unpaid on the platform
            </span>
          ) : null}
        </div>
        <ErrorBanner message={error} />
        <NewInvoiceCard customers={customers} products={products} onDone={() => load()} version={version} />
        <RecurringCard templates={templates} customers={customers} onDone={() => load()} />
        <div className="card pad">
          <h2 className="card-title">Register</h2>
          {rows === null ? (
            <Spinner label="Loading invoices…" />
          ) : (
            <DataTable
              rows={rows}
              rowKey={(r) => r.id}
              columns={COLUMNS}
              empty="No invoices."
              defaultSort={{ key: "date", dir: "desc" }}
              expand={(r) => <InvoicePanel id={r.id} onChanged={() => load()} />}
            />
          )}
        </div>
      </div>
    </div>
  );
}
