/** What a document is in law, on a document whose batch is closed (decision 0087).
 *  The kind moves no money, so the API takes it on a closed batch's document, where
 *  "Edit this invoice" is off. */
import { useState } from "react";
import { errorMessage, setDocumentKind, type RunCostDocumentRow } from "../../api";
import Field, { FieldGrid } from "../Field";
import { useModal } from "../modal";
import { ErrorBanner } from "../Ui";
import { useDocumentKinds } from "./InvoiceFields";

export default function DocumentKindDialog({ doc, onClose }: {
  doc: RunCostDocumentRow;
  onClose: (changed: boolean) => void;
}) {
  const modal = useModal(() => onClose(false));
  const kinds = useDocumentKinds();
  const [kind, setKind] = useState(doc.kind ?? "");
  const [rule, setRule] = useState(doc.vat_rule ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    try {
      await setDocumentKind(doc.id, kind, rule);
      onClose(true);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card" {...modal.cardProps}>
        <h2 className="card-title">Legal kind of {doc.doc_number || `document ${doc.id}`}</h2>
        <p className="muted dim">This changes no cost, so a closed batch's document takes it.</p>
        {error ? <ErrorBanner message={error} /> : null}
        <FieldGrid>
          <Field label="Legal kind">
            <select className="text" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">not decided</option>
              {kinds?.kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </Field>
          <Field label="VAT limit">
            <select className="text" value={rule} onChange={(e) => setRule(e.target.value)}>
              <option value="">none</option>
              {kinds?.vat_rules.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </Field>
        </FieldGrid>
        <div className="btn-row">
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void save()}>Save</button>
          <button type="button" className="btn" onClick={() => onClose(false)}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
