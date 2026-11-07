/** The position rows and the buyer picker of a sales document. The invoice draft
 *  and the recurring invoice use one copy, so they agree on what a position is.
 *
 *  The API reads a number with a dot and answers 500 to anything else, and a
 *  Polish keyboard types a comma. So `linesBody` writes the dot, and `linesReady`
 *  holds back a form with a half-typed row. A row with a name and no price must
 *  not vanish from the document on Save.
 */
import { useId } from "react";

import type { CustomerRow, SalesLine, SalesProductRow } from "../../api";
import Field, { FieldRow } from "../Field";
import { VAT_RATES } from "../PrintedInvoice";

export interface DraftLine { name: string; qty: string; unit_net: string; vat_rate: string; unit: string }

export const blankLine = (): DraftLine => ({ name: "", qty: "1", unit_net: "", vat_rate: "23", unit: "szt." });

/** A saved position, as the boxes show it. */
export const draftLineOf = (l: SalesLine): DraftLine => ({
  name: l.name, qty: String(l.qty), unit_net: String(l.unit_net), vat_rate: l.vat_rate, unit: l.unit,
});

const dotted = (s: string) => s.trim().replace(",", ".");
const isNumber = (s: string) => s.trim() !== "" && Number.isFinite(Number(dotted(s)));
const isEmpty = (l: DraftLine) => !l.name.trim() && !l.unit_net.trim();
const isComplete = (l: DraftLine) =>
  l.name.trim() !== "" && isNumber(l.unit_net) && (!l.qty.trim() || isNumber(l.qty));

/** At least one whole position, and no row left half-typed. An empty row is only
 *  a row nobody used. */
export const linesReady = (lines: DraftLine[]) =>
  lines.some(isComplete) && lines.every((l) => isEmpty(l) || isComplete(l));

/** The positions as the API takes them. */
export const linesBody = (lines: DraftLine[]): DraftLine[] =>
  lines.filter(isComplete).map((l) => ({
    ...l, name: l.name.trim(), qty: dotted(l.qty) || "1", unit_net: dotted(l.unit_net),
  }));

/** The rows, with a price list on the name box. Naming a product fills its price,
 *  its rate and its unit. A rate the list does not hold (an imported `22`) stays
 *  an option, or the box would show a rate the position does not have. */
export function SalesLinesEditor({ lines, products, onChange }: {
  lines: DraftLine[];
  products: SalesProductRow[];
  onChange: (next: DraftLine[]) => void;
}) {
  const listId = useId();
  const setLine = (i: number, patch: Partial<DraftLine>) =>
    onChange(lines.map((l, j) => {
      if (j !== i) return l;
      const next = { ...l, ...patch };
      const p = patch.name !== undefined ? products.find((x) => x.name === patch.name) : undefined;
      return p ? { ...next, unit_net: p.unit_net, vat_rate: p.vat_rate, unit: p.unit } : next;
    }));
  return (
    <>
      <datalist id={listId}>
        {products.map((p) => <option key={p.id} value={p.name} />)}
      </datalist>
      {lines.map((l, i) => (
        <FieldRow key={i}>
          <Field label={i === 0 ? "Name" : undefined} wide>
            <input className="text" list={listId} value={l.name} onChange={(e) => setLine(i, { name: e.target.value })} />
          </Field>
          <Field label={i === 0 ? "Qty" : undefined}>
            <input className="text num-input" value={l.qty} inputMode="decimal" onChange={(e) => setLine(i, { qty: e.target.value })} />
          </Field>
          <Field label={i === 0 ? "Unit net (PLN)" : undefined}>
            <input className="text num-input" value={l.unit_net} inputMode="decimal" onChange={(e) => setLine(i, { unit_net: e.target.value })} />
          </Field>
          <Field label={i === 0 ? "VAT" : undefined}>
            <select className="text" value={l.vat_rate} onChange={(e) => setLine(i, { vat_rate: e.target.value })}>
              {(VAT_RATES.includes(l.vat_rate) ? VAT_RATES : [l.vat_rate, ...VAT_RATES]).map((r) => (
                <option key={r} value={r}>{/^\d+$/.test(r) ? `${r}%` : r}</option>
              ))}
            </select>
          </Field>
          <Field label={i === 0 ? "Unit" : undefined}>
            <input className="text num-input" value={l.unit} onChange={(e) => setLine(i, { unit: e.target.value })} />
          </Field>
          {lines.length > 1 ? (
            <button type="button" className="btn btn-sm" onClick={() => onChange(lines.filter((_x, j) => j !== i))}>
              Remove
            </button>
          ) : null}
        </FieldRow>
      ))}
    </>
  );
}

/** A customer, by its legal name and tax number. */
export function CustomerSelect({ customers, value, onChange, empty = "—" }: {
  customers: CustomerRow[];
  value: number | "";
  onChange: (id: number | "") => void;
  /** the word for "no customer" */
  empty?: string;
}) {
  return (
    <select className="text" value={value} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}>
      <option value="">{empty}</option>
      {customers.map((c) => (
        <option key={c.id} value={c.id}>{c.legal_name || c.name}{c.tax_id ? ` · ${c.tax_id}` : ""}</option>
      ))}
    </select>
  );
}
