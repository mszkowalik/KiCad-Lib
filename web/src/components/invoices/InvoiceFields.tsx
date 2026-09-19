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
import AutoTextarea from "../AutoTextarea";
import Field from "../Field";
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

  return (
    <>
      <div className="field-grid">
        <label>
          Supplier
          <input className="text" value={value.supplier} disabled={disabled}
                 onChange={(e) => set({ supplier: e.target.value })} />
        </label>
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
