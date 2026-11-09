/** The lines of a purchase order as rows a person types (decision 0107 item 17).
 *
 *  One editor for "New purchase order" on Stock → Purchase orders and for "Edit
 *  lines" on a draft's own page, so the two cannot drift. A part is named the way
 *  `ComponentPickDialog` names one, or by the code the supplier prints: an MPN, or
 *  an LCSC number (`C` and digits). The picker runs without free text, because a
 *  part we buy belongs in the library (`components/CLAUDE.md`).
 *
 *  A row keeps a line's LCSC number when the box shows its MPN, so editing the
 *  quantity of a JLC line does not drop the code it was bought by.
 */
import { useState } from "react";
import type { PlanPoLine, PurchaseOrderIn } from "../api";
import ComponentPickDialog from "./ComponentPickDialog";

export interface PurchaseLineDraft {
  component_id: number | null;
  /** What the Part button prints once a component is picked. */
  label: string;
  /** The box: an MPN, or an LCSC number. */
  code: string;
  /** An LCSC number the box does not show, kept from the saved line. */
  lcsc: string;
  /** The saved line's name, carried unchanged (a plan proposal names its part). */
  name: string;
  qty: string;
  price: string;
}

type LineIn = NonNullable<PurchaseOrderIn["lines"]>[number];

const LCSC = /^C\d+$/i;

export const blankLine = (): PurchaseLineDraft => ({
  component_id: null, label: "", code: "", lcsc: "", name: "", qty: "", price: "",
});

/** The saved lines of an order as editable rows. */
export function draftsOf(lines: PlanPoLine[]): PurchaseLineDraft[] {
  return lines.map((ln) => ({
    component_id: ln.component_id,
    label: ln.name || ln.mpn || ln.lcsc || (ln.component_id ? `#${ln.component_id}` : ""),
    code: ln.mpn || ln.lcsc,
    lcsc: ln.mpn ? ln.lcsc : "",
    name: ln.name,
    qty: String(ln.qty),
    price: ln.unit_price == null ? "" : String(ln.unit_price),
  }));
}

/** A number as a person types it: a comma is a decimal point too. */
const num = (s: string) => Number(s.trim().replace(",", "."));

/** The rows as the API's `lines`, or the sentence that says what is missing.
 *  A row with nothing typed in it is left out. */
export function linesBody(rows: PurchaseLineDraft[]): { lines: LineIn[]; error: string } {
  const out: LineIn[] = [];
  for (const r of rows) {
    const code = r.code.trim();
    if (!r.component_id && !code && !r.qty.trim() && !r.price.trim()) continue;
    const qty = num(r.qty);
    const price = r.price.trim() === "" ? null : num(r.price);
    if (!(r.component_id || code) || !Number.isFinite(qty) || qty <= 0) {
      return { lines: [], error: "Every line needs a part (picked, or an MPN or LCSC number) and a quantity above 0." };
    }
    if (price !== null && (!Number.isFinite(price) || price < 0)) {
      return { lines: [], error: "A unit price is a number of 0 or more, or empty." };
    }
    const isLcsc = LCSC.test(code);
    out.push({
      component_id: r.component_id,
      mpn: isLcsc ? "" : code,
      lcsc: isLcsc ? code.toUpperCase() : r.lcsc,
      name: r.name,
      qty,
      unit_price: price,
    });
  }
  return { lines: out, error: "" };
}

export default function PurchaseLinesEditor({ rows, onChange, currency }: {
  rows: PurchaseLineDraft[];
  onChange: (rows: PurchaseLineDraft[]) => void;
  currency: string;
}) {
  const [picking, setPicking] = useState<number | null>(null);
  const patch = (i: number, p: Partial<PurchaseLineDraft>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const row = picking === null ? null : rows[picking];
  return (
    <>
      <div className="table-wrap">
        <table className="data data-fixed order-lines-edit-table">
          <thead>
            <tr>
              <th>Part</th>
              <th>MPN or LCSC</th>
              <th className="num">Qty</th>
              <th className="num">Unit price ({currency || "PLN"})</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td title={r.component_id ? `component #${r.component_id}` : "Pick the library component, or type its code"}>
                  <button type="button" className={r.component_id ? "linklike" : "btn btn-sm"} onClick={() => setPicking(i)}>
                    {r.component_id ? r.label || `#${r.component_id}` : "Pick…"}
                  </button>
                </td>
                <td title={r.lcsc && r.lcsc !== r.code ? `LCSC ${r.lcsc}` : undefined}>
                  <input className="row-input mono" value={r.code} placeholder="MPN, or C123456"
                    aria-label={`Line ${i + 1} MPN or LCSC number`}
                    onChange={(e) => patch(i, { code: e.target.value })} />
                </td>
                <td className="num">
                  <input className="row-input num" inputMode="decimal" value={r.qty}
                    aria-label={`Line ${i + 1} quantity`}
                    onChange={(e) => patch(i, { qty: e.target.value })} />
                </td>
                <td className="num">
                  <input className="row-input num" inputMode="decimal" value={r.price}
                    aria-label={`Line ${i + 1} unit price`}
                    onChange={(e) => patch(i, { price: e.target.value })} />
                </td>
                <td>
                  <button type="button" className="row-del" title="Remove this line" aria-label={`Remove line ${i + 1}`}
                    disabled={rows.length === 1} onClick={() => onChange(rows.filter((_, j) => j !== i))}>
                    &#x2715;
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={() => onChange([...rows, blankLine()])}>
          Add a line
        </button>
      </div>
      {row !== null && picking !== null ? (
        <ComponentPickDialog
          line={{ label: row.label || row.code, mpn: LCSC.test(row.code.trim()) ? "" : row.code.trim(),
                  component_id: row.component_id, component_name: row.component_id ? row.label : null,
                  kind: "purchase line" }}
          title="Which part is this line?"
          confirmLabel="Use this part"
          onPick={(componentId, mpn) => {
            patch(picking, {
              component_id: componentId,
              label: componentId ? mpn || `#${componentId}` : "",
              code: row.code.trim() || mpn,
            });
          }}
          onClose={() => setPicking(null)}
        />
      ) : null}
    </>
  );
}
