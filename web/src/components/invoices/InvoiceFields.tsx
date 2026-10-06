/** The header of a supplier document — supplier, number, date, currency, the
 *  printed total, its type and its notes.
 *
 *  Shared by the New invoice card and the document view's edit mode, so the
 *  fields a document is CREATED with are exactly the fields it can be corrected
 *  with. Until this existed the UI had no way to fix a mistyped supplier, date
 *  or printed total at all: the only editable things on a saved document were
 *  its positions.
 */
import { useState } from "react";
import { errorMessage, getNbpRate } from "../../api";
import { useAuth } from "../../auth";
import AutoTextarea from "../AutoTextarea";
import Field from "../Field";
import InfoTip from "../InfoTip";
import { ChargeToSelect, type RunOption } from "../costs";

export interface InvoiceHeader {
  supplier: string;
  doc_number: string;
  external_id: string;
  doc_date: string;
  currency: string;
  total: string;        // string while typing: "" means "not stated"
  doc_type: string;
  notes: string;
  dest: string;         // create only — a destination for every position at once
  /** the company that was billed (decision 0064); "" = not decided yet */
  company_id: number | "";
  /** Decision 0084, the invoice's tax data. Strings while typing; "" = not stated. */
  tax: string;          // the printed VAT, in the document's currency
  tax_pln: string;      // the VAT in PLN, on a document in another currency
  sale_date: string;
  due_date: string;
  received_date: string;
}

/** The tax fields of a header, shaped for a create or a patch. A PLN
 *  document's VAT is `tax_amount`, so it never sends a VAT in PLN as well. */
export function taxFieldsOf(h: InvoiceHeader) {
  const tax = h.tax.trim();
  const pln = h.tax_pln.trim();
  const isPln = (h.currency.trim() || "USD").toUpperCase() === "PLN";
  return {
    tax_amount: tax === "" ? null : Number(tax),
    tax_amount_pln: isPln || pln === "" ? null : pln,
    sale_date: h.sale_date.trim(),
    due_date: h.due_date.trim(),
    received_date: h.received_date.trim(),
  };
}

/** The header fields a new document starts with that are the same for all. */
export const EMPTY_TAX = { tax: "", tax_pln: "", sale_date: "", due_date: "", received_date: "" };

/** The tax data in one line, for the document view when it is not edited. */
export function taxSummary(d: {
  currency: string; tax_amount: number | null; tax_amount_pln?: string | null;
  sale_date?: string; due_date?: string; received_date?: string;
}): string {
  const parts = [
    d.tax_amount != null ? `VAT ${d.tax_amount.toFixed(2)} ${d.currency}` : "no VAT stated",
    d.tax_amount_pln != null ? `VAT ${d.tax_amount_pln} PLN` : "",
    d.sale_date ? `sale ${d.sale_date}` : "",
    d.received_date ? `received ${d.received_date}` : "",
    d.due_date ? `due ${d.due_date}` : "",
  ];
  return parts.filter(Boolean).join(" · ");
}

export const DOC_TYPES = [
  ["invoice", "invoice"],
  ["proforma", "proforma (not money)"],
  ["receipt", "receipt"],
  ["credit_note", "credit note"],
  // Decision 0044. Written by the `Create correction` button on a document,
  // which also fills in what it corrects — but it is a type like any other, so a
  // correction that arrived as its own printed document can be typed in directly.
  ["correction", "correction (of another document)"],
] as const;

export default function InvoiceFields({
  value, onChange, runs, projects, withDest = false, disabled = false,
}: {
  value: InvoiceHeader;
  onChange: (next: InvoiceHeader) => void;
  runs: RunOption[];
  projects: { id: number; name: string }[];
  /** the create form only: one destination applied to every position */
  withDest?: boolean;
  disabled?: boolean;
}) {
  const [nbp, setNbp] = useState("");
  const { companies } = useAuth();
  const set = (next: Partial<InvoiceHeader>) => onChange({ ...value, ...next });

  /** Invoice-date FX convention: the NBP table-A rate at the document date.
   *  Display-only — the server pins its own when the document is written. */
  const lookupNbp = async () => {
    setNbp("…");
    try {
      const r = await getNbpRate(value.currency.trim(), value.doc_date.trim());
      setNbp(
        `1 ${r.currency} = ${r.rate_usd} USD (NBP table A, ${r.effective_date}` +
          `${r.requested_date_used ? "" : " — previous working day"})`,
      );
    } catch (err) {
      setNbp(errorMessage(err));
    }
  };

  const foreign = value.currency.trim() && value.currency.trim().toUpperCase() !== "USD";
  const isPln = (value.currency.trim() || "USD").toUpperCase() === "PLN";

  return (
    <>
      <div className="field-grid">
        <label>
          Supplier
          <input className="text" value={value.supplier} disabled={disabled}
                 onChange={(e) => set({ supplier: e.target.value })} />
        </label>
        <Field label="Buyer">
          <select
            className="text"
            value={value.company_id}
            disabled={disabled}
            onChange={(e) => set({ company_id: e.target.value === "" ? "" : Number(e.target.value) })}
          >
            <option value="">— not decided —</option>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </Field>
        <label>
          Document number
          <input className="text" value={value.doc_number} disabled={disabled}
                 onChange={(e) => set({ doc_number: e.target.value })} />
        </label>
        <label>
          Supplier order id
          <input className="text" value={value.external_id} disabled={disabled}
                 placeholder="JLC Batch No, POB0…"
                 onChange={(e) => set({ external_id: e.target.value })} />
        </label>
        <label>
          Date
          <input className="text" value={value.doc_date} disabled={disabled}
                 placeholder="2025-04-13"
                 onChange={(e) => set({ doc_date: e.target.value })} />
        </label>
        <label>
          Currency
          <input className="text" value={value.currency} disabled={disabled}
                 onChange={(e) => set({ currency: e.target.value })} />
          {foreign && value.doc_date.trim() ? (
            <span>
              <button type="button" className="btn btn-sm" onClick={lookupNbp} disabled={disabled}>
                NBP rate at this date
              </button>{" "}
              {nbp ? <span className="muted">{nbp}</span> : null}
            </span>
          ) : null}
        </label>
        <label>
          Printed total
          <input className="text num" value={value.total} disabled={disabled}
                 onChange={(e) => set({ total: e.target.value })} />
        </label>
        {/* Decision 0084. The books deduct a purchase's VAT in PLN, in the
            month of the later of the sale date and the receipt date. */}
        <Field label={<>VAT <InfoTip label="About VAT">The printed VAT, in the document's currency. Empty when the invoice charges no Polish VAT (an import, reverse charge).</InfoTip></>}>
          <input className="text num" value={value.tax} disabled={disabled}
                 onChange={(e) => set({ tax: e.target.value })} />
        </Field>
        {isPln ? null : (
          <Field label={<>VAT in PLN <InfoTip label="About VAT in PLN">An invoice in another currency that charges Polish VAT prints it in PLN as well. The books read this figure.</InfoTip></>}>
            <input className="text num" value={value.tax_pln} disabled={disabled}
                   onChange={(e) => set({ tax_pln: e.target.value })} />
          </Field>
        )}
        <Field label={<>Sale date <InfoTip label="About Sale date">The day of the delivery or the service, when the invoice prints one that is not its date.</InfoTip></>}>
          <input className="text" value={value.sale_date} disabled={disabled} placeholder="as the date"
                 onChange={(e) => set({ sale_date: e.target.value })} />
        </Field>
        <Field label={<>Received <InfoTip label="About Received">The day the invoice reached you. Its VAT is deducted no earlier. A KSeF invoice takes the day KSeF numbered it.</InfoTip></>}>
          <input className="text" value={value.received_date} disabled={disabled} placeholder="as the date"
                 onChange={(e) => set({ received_date: e.target.value })} />
        </Field>
        <Field label="Due">
          <input className="text" value={value.due_date} disabled={disabled}
                 onChange={(e) => set({ due_date: e.target.value })} />
        </Field>
        <label>
          Type
          <select className="text" value={value.doc_type} disabled={disabled}
                  onChange={(e) => set({ doc_type: e.target.value })}>
            {DOC_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
        {withDest ? (
          <label>
            {/* The DOCUMENT's default, applied to any position that names no
                destination of its own. Worded like the per-line control it
                backstops (decision 0045). */}
            Every position goes to
            <ChargeToSelect
              className="text"
              runs={runs}
              projects={projects}
              value={value.dest}
              disabled={disabled}
              onChange={(v) => set({ dest: v })}
              emptyLabel="— each position decides —"
              withExcluded={false}
            />
          </label>
        ) : null}
      </div>
      {/* `note-textarea` is `flex: 1` and belongs to `.note-form`; inside a
          plain label it collapses to a stub, which is how the New invoice card
          carried a one-word-wide Notes box. A multi-line value is an
          `AutoTextarea` on `.text` (web/src/components/CLAUDE.md). */}
      <Field label="Notes">
        <AutoTextarea
          className="text"
          value={value.notes}
          disabled={disabled}
          rows={2}
          onChange={(e) => set({ notes: e.target.value })}
          placeholder="What this document covers, and any split arithmetic"
        />
      </Field>
    </>
  );
}
