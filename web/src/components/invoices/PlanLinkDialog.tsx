/** Tie an actual invoice position to the PLANNED cost item it is the actual for.
 *
 *  Two ways, as asked (2026-07-27): point the line at a cost position that
 *  already exists in the project's cost list, or create that position from the
 *  line and link it in one go. Without the link a real figure and its estimate
 *  sit side by side with nothing joining them, and the plan-vs-actual delta can
 *  only ever be a whole-run number.
 *
 *  The link is stored on the line as `plan_kind="cost"` + `plan_key=<item id>` +
 *  `plan_ref=<label>`: `plan_ref` survives a cost-list revision (items are
 *  copy-on-write per commit, so the id can move) — it is the readable anchor.
 */
import { useEffect, useState } from "react";
import {
  addCostItem,
  errorMessage,
  getCostItems,
  isAbortError,
  updateCostLine,
  type CostItem,
  type RunCostLineRow,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";

export default function PlanLinkDialog({
  line, projectId, projectName, currency, supplier, onClose,
}: {
  line: RunCostLineRow;
  projectId: number;
  projectName: string;
  currency: string;
  supplier: string;
  onClose: (changed: boolean) => void;
}) {
  const [items, setItems] = useState<CostItem[] | null>(null);
  const [choice, setChoice] = useState<string>(line.plan_key || "");
  const [newLabel, setNewLabel] = useState(line.label || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getCostItems(projectId, null, ac.signal)
      .then((r) => setItems(r.items))
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [projectId]);

  const amount = line.line_total ?? 0;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (choice === "__new__") {
        // A run-level fee is `per_run`; the line's own basis already says which.
        const created = await addCostItem(projectId, {
          label: newLabel.trim() || line.label,
          basis: line.basis,
          price: line.basis === "per_device" ? line.unit_price : amount,
          steps: [],
          currency,
          company: supplier,
          mpn: line.mpn || "",
          notes: `Created from invoice line ${line.id}`,
          position: (items?.length ?? 0) + 1,
        });
        await updateCostLine(line.id, {
          plan_kind: "cost", plan_key: String(created.id), plan_ref: created.label,
        });
      } else if (choice === "") {
        await updateCostLine(line.id, { plan_kind: "", plan_key: "", plan_ref: "" });
      } else {
        const item = (items || []).find((i) => String(i.id) === choice);
        await updateCostLine(line.id, {
          plan_kind: "cost", plan_key: choice, plan_ref: item?.label || "",
        });
      }
      onClose(true);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose(false)}>
      <div className="card pad modal-card" onMouseDown={(e) => e.stopPropagation()}>
        <h2 className="card-title">Link to a planned cost</h2>
        <p className="card-subtitle">
          “{line.label || line.kind}” — {amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}{" "}
          {currency}, in {projectName}.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        {items === null ? (
          <Spinner label="Loading the cost list…" />
        ) : (
          <>
            <select className="text modal-input" value={choice} onChange={(e) => setChoice(e.target.value)}>
              <option value="">— not linked —</option>
              {items.map((i) => (
                <option key={i.id} value={String(i.id)}>
                  {i.label} · {i.basis === "per_device" ? "per device" : "per run"} {i.price} {i.currency}
                </option>
              ))}
              <option value="__new__">+ Create a new cost position from this line</option>
            </select>
            {choice === "__new__" ? (
              <input
                className="text modal-input"
                value={newLabel}
                placeholder="Cost position label"
                onChange={(e) => setNewLabel(e.target.value)}
              />
            ) : null}
          </>
        )}
        <div className="btn-row modal-actions">
          <button type="button" className="btn" onClick={() => onClose(false)} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={save} disabled={busy || items === null}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
