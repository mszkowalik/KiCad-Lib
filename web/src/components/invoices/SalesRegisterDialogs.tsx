/** The two ways an administrator writes a company's past sales: a document it
 *  issued elsewhere (decision 0077), and the old script's register (decision 0066).
 *  The API gates both, because they write past revenue.
 */
import { useState } from "react";
import {
  errorMessage,
  importSalesRegister,
  listOrders,
  recordSalesHistory,
  type CustomerRow,
  type SalesHistoryIn,
  type SalesImportPlan,
} from "../../api";
import { useAuth } from "../../auth";
import AutoTextarea from "../AutoTextarea";
import Field, { CheckField, FieldGrid, FieldRow } from "../Field";
import FilePick from "../FilePick";
import { useModal } from "../modal";
import { pl } from "../../format";
import { VAT_RATES } from "../PrintedInvoice";
import { DryRunDialog } from "../process/StageDialogs";
import { ErrorBanner, Spinner } from "../Ui";
import { CustomerSelect } from "./SalesLines";
import { useLoad } from "../useLoad";

const HISTORY_KINDS = [
  { value: "vat", label: "VAT invoice" },
  { value: "advance", label: "Advance" },
  { value: "settlement", label: "Settlement" },
  { value: "correction", label: "Correction" },
  { value: "proforma", label: "Proforma" },
];

interface PositionDraft { name: string; qty: string; unit: string; unit_net: string; vat_rate: string; net: string; vat: string }
const blankPosition = (): PositionDraft => ({ name: "", qty: "1", unit: "szt.", unit_net: "", vat_rate: "23", net: "", vat: "" });

const num = (s: string) => { const n = Number(s.replace(",", ".")); return Number.isFinite(n) ? n : 0; };
const money = (n: number) => n.toFixed(2);

/** The net a position computes to, when the box is left empty. */
const computedNet = (p: PositionDraft) => num(p.qty) * num(p.unit_net);
/** Its VAT. A rate with no number in it (zw, np, oo) carries none. */
const computedVat = (p: PositionDraft, net: number) => (/^\d+$/.test(p.vat_rate) ? (net * Number(p.vat_rate)) / 100 : 0);

/** A sales document a company issued elsewhere, as printed. Any company may have
 *  history, also one that does not issue here. It is recorded once per number, it
 *  never goes to KSeF and it takes no number from a series. Its PDF goes on the
 *  invoice afterwards, under Documents. */
export function RecordHistoryDialog({ customers, onClose }: {
  customers: CustomerRow[];
  onClose: (changed: boolean) => void;
}) {
  const { companies } = useAuth();
  const modal = useModal(() => onClose(false));
  const [companyId, setCompanyId] = useState<number | null>(companies[0]?.id ?? null);
  const [kind, setKind] = useState("vat");
  const [number, setNumber] = useState("");
  const [issue, setIssue] = useState("");
  const [sale, setSale] = useState("");
  const [due, setDue] = useState("");
  const [buyer, setBuyer] = useState({ name: "", address_l1: "", address_l2: "", nip: "", country: "PL" });
  const [currency, setCurrency] = useState("PLN");
  const [lines, setLines] = useState<PositionDraft[]>([blankPosition()]);
  const [totals, setTotals] = useState({ net: "", vat: "", gross: "" });
  const [advances, setAdvances] = useState("");
  const [corrects, setCorrects] = useState("");
  const [paid, setPaid] = useState(false);
  const [paidDate, setPaidDate] = useState("");
  const [orderId, setOrderId] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const orders = useLoad(listOrders, []).data ?? [];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const typed = lines.filter((l) => l.name.trim());
  const shaped = typed.map((l) => {
    const net = l.net.trim() ? num(l.net) : computedNet(l);
    const vat = l.vat.trim() ? num(l.vat) : computedVat(l, net);
    return { ...l, net: money(net), vat: money(vat), qty: l.qty.trim(), unit_net: l.unit_net.trim() };
  });
  const byRate: Record<string, { net: number; vat: number }> = {};
  for (const l of shaped) {
    const k = (byRate[l.vat_rate] ??= { net: 0, vat: 0 });
    k.net += num(l.net);
    k.vat += num(l.vat);
  }
  const sum = Object.values(byRate).reduce((s, r) => ({ net: s.net + r.net, vat: s.vat + r.vat }), { net: 0, vat: 0 });

  // An advance states the advance, and a settlement what is left to pay. Their
  // positions are the whole order, so the two figures are never the same one.
  const statesOwnTotals = kind === "advance" || kind === "settlement";
  const net = totals.net.trim() ? num(totals.net) : statesOwnTotals ? 0 : sum.net;
  const vat = totals.vat.trim() ? num(totals.vat) : statesOwnTotals ? 0 : sum.vat;
  const gross = totals.gross.trim() ? num(totals.gross) : net + vat;
  const rates = Object.keys(byRate);
  const totalsReady = totals.net.trim() !== "" || (!statesOwnTotals && shaped.length > 0);
  const ready = companyId !== null && number.trim() !== "" && issue !== "" && buyer.name.trim() !== "" && totalsReady;

  const setLine = (i: number, patch: Partial<PositionDraft>) =>
    setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const fillBuyer = (id: number) => {
    const c = customers.find((x) => x.id === id);
    if (c) {
      setBuyer({ name: c.legal_name || c.name, address_l1: c.address_l1 ?? "", address_l2: c.address_l2 ?? "",
                 nip: c.tax_id ?? "", country: c.country || "PL" });
    }
  };

  const save = async () => {
    if (companyId === null) return;
    setBusy(true);
    setError(null);
    const body: SalesHistoryIn = {
      company_id: companyId, kind, number: number.trim(), issue_date: issue, sale_date: sale, due_date: due, buyer,
      currency: currency.trim().toUpperCase() || "PLN", lines: shaped,
      totals: {
        net: money(net), vat: money(vat), gross: money(gross),
        // One rate: the totals are that rate's. Several, on figures of their
        // own: the page's split is not known here, and the books read the totals.
        rates: statesOwnTotals
          ? (rates.length === 1 ? { [rates[0]]: { net: money(net), vat: money(vat) } } : {})
          : Object.fromEntries(Object.entries(byRate).map(([r, v]) => [r, { net: money(v.net), vat: money(v.vat) }])),
      },
      advance_numbers: advances.split(/[\n,;]+/).map((x) => x.trim()).filter(Boolean),
      corrects_number: corrects.trim(), paid, paid_date: paid ? paidDate : "", order_id: orderId, note,
    };
    try {
      await recordSalesHistory(body);
      onClose(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">Record a document issued elsewhere</h2>
        <p className="muted dim">
          For a document the company issued before the platform or KSeF wrote its invoices. It is kept as
          printed: status issued, no KSeF, no number from a series. It enters the company's books. Each number
          is recorded once. Add its PDF on the invoice afterwards, under Documents.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        <FieldGrid>
          <Field label="Company">
            <select className="text" value={companyId ?? ""} onChange={(e) => setCompanyId(Number(e.target.value) || null)}>
              {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Kind">
            <select className="text" value={kind} onChange={(e) => setKind(e.target.value)}>
              {HISTORY_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </Field>
          <Field label="Number">
            <input className="text mono" value={number} maxLength={60} onChange={(e) => setNumber(e.target.value)} />
          </Field>
          <Field label="Currency">
            <input className="text num-input" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} />
          </Field>
          <Field label="Issue date">
            <input className="text" type="date" value={issue} onChange={(e) => setIssue(e.target.value)} />
          </Field>
          <Field label="Sale date" hint="Empty: the issue date.">
            <input className="text" type="date" value={sale} onChange={(e) => setSale(e.target.value)} />
          </Field>
          <Field label="Due date">
            <input className="text" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </Field>
          <Field label="Order" hint="Optional. The order it belongs to.">
            <select className="text" value={orderId ?? ""} onChange={(e) => setOrderId(Number(e.target.value) || null)}>
              <option value="">none</option>
              {orders.filter((o) => o.company_id === companyId || o.company_id === null).map((o) => (
                <option key={o.id} value={o.id}>{o.customer}{o.order_ref ? ` · ${o.order_ref}` : ""}{o.order_date ? ` · ${o.order_date}` : ""}</option>
              ))}
            </select>
          </Field>
          <Field label="Fill the buyer from a customer">
            <CustomerSelect customers={customers} value="" empty="choose" onChange={(id) => { if (id !== "") fillBuyer(id); }} />
          </Field>
          <Field label="Buyer">
            <input className="text" value={buyer.name} onChange={(e) => setBuyer({ ...buyer, name: e.target.value })} />
          </Field>
          <Field label="Buyer's NIP">
            <input className="text mono" value={buyer.nip} onChange={(e) => setBuyer({ ...buyer, nip: e.target.value })} />
          </Field>
          <Field label="Country">
            <input className="text num-input" value={buyer.country} onChange={(e) => setBuyer({ ...buyer, country: e.target.value })} />
          </Field>
          <Field label="Address, line 1">
            <input className="text" value={buyer.address_l1} onChange={(e) => setBuyer({ ...buyer, address_l1: e.target.value })} />
          </Field>
          <Field label="Address, line 2">
            <input className="text" value={buyer.address_l2} onChange={(e) => setBuyer({ ...buyer, address_l2: e.target.value })} />
          </Field>
        </FieldGrid>
        <p className="muted dim">
          {kind === "advance" ? "The order the advance is paid against:"
            : kind === "settlement" ? "The whole order:" : "Positions:"} an empty net or VAT is computed from the quantity,
          the unit price and the rate.
        </p>
        {lines.map((l, i) => {
          const lineNet = computedNet(l);
          return (
            <FieldRow key={i}>
              <Field label={i === 0 ? "Name" : undefined} wide>
                <input className="text" value={l.name} onChange={(e) => setLine(i, { name: e.target.value })} />
              </Field>
              <Field className="field-narrow" label={i === 0 ? "Qty" : undefined}>
                <input className="text num-input" value={l.qty} inputMode="decimal" onChange={(e) => setLine(i, { qty: e.target.value })} />
              </Field>
              <Field className="field-narrow" label={i === 0 ? "Unit" : undefined}>
                <input className="text num-input" value={l.unit} onChange={(e) => setLine(i, { unit: e.target.value })} />
              </Field>
              <Field className="field-narrow" label={i === 0 ? "Unit net" : undefined}>
                <input className="text num-input" value={l.unit_net} inputMode="decimal" onChange={(e) => setLine(i, { unit_net: e.target.value })} />
              </Field>
              <Field className="field-narrow" label={i === 0 ? "VAT" : undefined}>
                <select className="text" value={l.vat_rate} onChange={(e) => setLine(i, { vat_rate: e.target.value })}>
                  {VAT_RATES.map((r) => <option key={r} value={r}>{/^\d+$/.test(r) ? `${r}%` : r}</option>)}
                </select>
              </Field>
              <Field className="field-narrow" label={i === 0 ? "Net" : undefined}>
                <input className="text num-input" value={l.net} inputMode="decimal" placeholder={money(lineNet)}
                  onChange={(e) => setLine(i, { net: e.target.value })} />
              </Field>
              <Field className="field-narrow" label={i === 0 ? "VAT amount" : undefined}>
                <input className="text num-input" value={l.vat} inputMode="decimal"
                  placeholder={money(computedVat(l, l.net.trim() ? num(l.net) : lineNet))}
                  onChange={(e) => setLine(i, { vat: e.target.value })} />
              </Field>
              {lines.length > 1 ? (
                <button type="button" className="btn btn-sm" onClick={() => setLines(lines.filter((_x, j) => j !== i))}>Remove</button>
              ) : null}
            </FieldRow>
          );
        })}
        <div className="btn-row">
          <button type="button" className="btn btn-sm" onClick={() => setLines([...lines, blankPosition()])}>Add a position</button>
        </div>
        <FieldGrid>
          <Field label={kind === "advance" ? "Advance, net" : kind === "settlement" ? "Left to pay, net" : "Total net"}
            hint={statesOwnTotals ? "As the document prints it. Required." : "Empty: the sum of the positions."}>
            <input className="text num-input" value={totals.net} inputMode="decimal" placeholder={statesOwnTotals ? "" : money(sum.net)}
              onChange={(e) => setTotals({ ...totals, net: e.target.value })} />
          </Field>
          <Field label="VAT">
            <input className="text num-input" value={totals.vat} inputMode="decimal" placeholder={statesOwnTotals ? "" : money(sum.vat)}
              onChange={(e) => setTotals({ ...totals, vat: e.target.value })} />
          </Field>
          <Field label="Gross" hint={`Empty: net + VAT = ${pl(net + vat)}.`}>
            <input className="text num-input" value={totals.gross} inputMode="decimal"
              onChange={(e) => setTotals({ ...totals, gross: e.target.value })} />
          </Field>
          {kind === "settlement" ? (
            <Field label="Advances it settles" hint="Their numbers, one per line." wide>
              <AutoTextarea className="text mono" value={advances} onChange={(e) => setAdvances(e.target.value)} />
            </Field>
          ) : null}
          {kind === "correction" ? (
            <Field label="Number it corrects" wide>
              <input className="text mono" value={corrects} onChange={(e) => setCorrects(e.target.value)} />
            </Field>
          ) : null}
          <Field group label="Paid">
            <CheckField checked={paid} onChange={setPaid}>The buyer paid it</CheckField>
          </Field>
          {paid ? (
            <Field label="Paid on">
              <input className="text" type="date" value={paidDate} onChange={(e) => setPaidDate(e.target.value)} />
            </Field>
          ) : null}
          <Field label="Note" wide hint="Printed in the notes of the record.">
            <AutoTextarea className="text" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" onClick={() => onClose(false)}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !ready} onClick={() => void save()}>Record</button>
        </div>
      </div>
    </div>
  );
}

const REGISTER_FILES = [
  { key: "register_file", label: "Register", name: "rejestr.json" },
  { key: "clients_file", label: "Buyers", name: "klienci.json" },
  { key: "recurring_file", label: "Recurring invoices", name: "cykliczne.json" },
  { key: "products_file", label: "Price list", name: "produkty.json" },
] as const;
type RegisterKey = (typeof REGISTER_FILES)[number]["key"];

/** The old script's files, into the platform. It can run again: a document that
 *  is here (same kind, number and date) is skipped, and a buyer is matched by NIP,
 *  then by name. */
export function ImportRegisterDialog({ onClose }: { onClose: (changed: boolean) => void }) {
  const { companies } = useAuth();
  const sellers = companies.filter((c) => c.issues_invoices);
  const [companyId, setCompanyId] = useState<number | null>(sellers[0]?.id ?? null);
  const [files, setFiles] = useState<Partial<Record<RegisterKey, File>>>({});
  const run = async (dry: boolean): Promise<SalesImportPlan> => {
    if (companyId === null) throw new Error("No company issues its invoices on this platform.");
    const chosen = Object.values(files);
    if (!chosen.length) throw new Error("Choose at least one file.");
    // The route reads each file as JSON and answers 500 when it is not.
    for (const f of chosen) {
      try {
        JSON.parse(await f.text());
      } catch {
        throw new Error(`${f.name} is not valid JSON.`);
      }
    }
    return importSalesRegister(companyId, files, dry);
  };
  return (
    <DryRunDialog<SalesImportPlan>
      title="Import the register"
      intro="This reads the files of the old invoicing script: its buyers, its price list, its recurring invoices and every document of its register. You can run it again: a document that is here (same kind, number and date) is skipped, and a buyer is matched by NIP, then by name."
      onClose={onClose}
      run={run}
      canApply={(p) => p.documents.created + p.customers.created.length + p.templates.length + p.products.length > 0}
      applyLabel={() => "Import"}
      describe={(p) => (
        <>
          {p.documents.created} document(s) to add, {p.documents.skipped} already here.
          {" "}{p.customers.created.length} buyer(s) to add, {p.customers.matched.length} matched.
          {" "}{p.templates.length} recurring invoice(s), {p.products.length} product(s) read.
        </>
      )}
      fields={
        <FieldGrid>
          <Field label="Company" wide hint="A company that issues its invoices on this platform.">
            <select className="text" value={companyId ?? ""} onChange={(e) => setCompanyId(Number(e.target.value) || null)}>
              {sellers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          {REGISTER_FILES.map((f) => (
            <Field key={f.key} group label={f.label} hint={f.name}>
              <FilePick accept=".json" onPick={(picked) => setFiles((was) => ({ ...was, [f.key]: picked[0] }))}>
                {files[f.key]?.name ?? "Choose the file…"}
              </FilePick>
            </Field>
          ))}
        </FieldGrid>
      }
    />
  );
}
