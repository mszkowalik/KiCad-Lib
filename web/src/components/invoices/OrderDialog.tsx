/** The sale side of a batch: what a device was sold for, and to whom.
 *
 *  A price PER DEVICE, never a batch total — the total is derived, and a per-device
 *  figure survives a later quantity correction (user decision 2026-07-27). Revenue
 *  uses `qty_sold`, the units the customer was actually billed for, because that is
 *  routinely neither the planned quantity nor the number that passed test: samples,
 *  held-back stock and scrap all move it.
 *
 *  Margin shown here is gross margin over revenue — the figure a price decision is
 *  made against — and the cost side is whatever the run's actuals currently say.
 */
import { useState } from "react";
import { errorMessage, updateRun, type RunActuals, type RunInfo } from "../../api";
import { ErrorBanner } from "../Ui";

function num(s: string): number | null {
  const t = s.trim();
  if (t === "") return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}

function money(v: number | null | undefined, cur: string): string {
  if (v == null) return "—";
  return `${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${cur}`;
}

export default function OrderDialog({
  run, actuals, onClose,
}: {
  run: RunInfo;
  /** current cost side, so the margin preview is live while typing */
  actuals: RunActuals | null;
  onClose: (changed: boolean) => void;
}) {
  const [price, setPrice] = useState(run.sale_unit_price != null ? String(run.sale_unit_price) : "");
  const [currency, setCurrency] = useState(run.sale_currency || "");
  const [qtySold, setQtySold] = useState(run.qty_sold != null ? String(run.qty_sold) : "");
  const [qtyGood, setQtyGood] = useState(run.qty_good != null ? String(run.qty_good) : "");
  const [customer, setCustomer] = useState(run.customer || "");
  const [orderRef, setOrderRef] = useState(run.order_ref || "");
  const [orderDate, setOrderDate] = useState(run.order_date || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const costCur = actuals?.currency || "USD";
  const saleCur = (currency || costCur).toUpperCase();
  const unit = num(price);
  // mirrors the server: billed units, else good, else planned, else ordered
  const units = num(qtySold) ?? num(qtyGood) ?? run.qty;
  const revenue = unit != null ? unit * units : null;
  const cost = actuals?.total ?? null;
  const comparable = saleCur === costCur.toUpperCase();
  const margin = revenue != null && cost != null && comparable ? revenue - cost : null;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await updateRun(run.id, {
        sale_unit_price: unit,
        sale_currency: currency.trim().toUpperCase(),
        qty_sold: num(qtySold),
        qty_good: num(qtyGood),
        customer: customer.trim(),
        order_ref: orderRef.trim(),
        order_date: orderDate.trim(),
      });
      onClose(true);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose(false)}>
      <div className="card pad modal-card modal-card-mid" onMouseDown={(e) => e.stopPropagation()}>
        <h2 className="card-title">Order &amp; price — {run.label}</h2>
        <p className="card-subtitle">
          Price per device, not a batch total. Revenue is charged on the units billed, so a
          batch that shipped short still reads correctly.
        </p>
        {error ? <ErrorBanner message={error} /> : null}

        <div className="edit-grid">
          <label>
            Price per device
            <input className="text num" inputMode="decimal" value={price}
                   onChange={(e) => setPrice(e.target.value)} />
          </label>
          <label>
            Sale currency
            <input className="text" value={currency} placeholder={costCur} maxLength={3}
                   onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
          </label>
          <label>
            Units billed
            <input className="text num" inputMode="numeric" value={qtySold}
                   placeholder={String(run.qty_good ?? run.qty)}
                   onChange={(e) => setQtySold(e.target.value)} />
          </label>
          <label>
            Units good
            <input className="text num" inputMode="numeric" value={qtyGood}
                   placeholder={String(run.qty)}
                   onChange={(e) => setQtyGood(e.target.value)} />
          </label>
          <label>
            Customer
            <input className="text" value={customer} onChange={(e) => setCustomer(e.target.value)} />
          </label>
          <label>
            Order reference
            <input className="text" value={orderRef} placeholder="their PO number"
                   onChange={(e) => setOrderRef(e.target.value)} />
          </label>
          <label>
            Order date
            <input className="text" value={orderDate} placeholder="2025-09-20"
                   onChange={(e) => setOrderDate(e.target.value)} />
          </label>
        </div>

        <div className="table-wrap">
          <table className="data data-fixed order-preview-table">
            <thead>
              <tr>
                <th className="num">Units billed</th>
                <th className="num">Revenue</th>
                <th className="num">Cost (actual)</th>
                <th className="num">Margin</th>
                <th className="num">Margin %</th>
                <th className="num">Per device</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="num">{units.toLocaleString()}</td>
                <td className="num">{money(revenue, saleCur)}</td>
                <td className="num">{money(cost, costCur)}</td>
                <td className={"num" + (margin != null && margin < 0 ? " err-text" : "")}>
                  {money(margin, costCur)}
                </td>
                <td className={"num" + (margin != null && margin < 0 ? " err-text" : "")}>
                  {margin != null && revenue ? `${(margin / revenue * 100).toFixed(1)}%` : "—"}
                </td>
                <td className={"num" + (margin != null && margin < 0 ? " err-text" : "")}>
                  {margin != null ? money(margin / Math.max(units, 1), costCur) : "—"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        {!comparable && unit != null ? (
          <div className="banner-warn">
            The sale is in {saleCur} and the cost in {costCur}. The margin above is left blank
            rather than mixing units; the register converts both to USD at the order date.
          </div>
        ) : null}
        {cost == null && unit != null ? (
          <div className="banner-warn">
            This run has no actual cost yet, so there is nothing to compare the price against.
          </div>
        ) : null}

        <div className="btn-row modal-actions">
          <button type="button" className="btn" onClick={() => onClose(false)} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
