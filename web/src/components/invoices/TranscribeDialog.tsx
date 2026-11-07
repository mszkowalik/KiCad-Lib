/** Store what one of a document's own files prints (decision 0085).
 *
 *  The page goes in as JSON because it has the shape of `SalesInvoice.body`: two
 *  parties, positions with their rates, totals per rate. It stays a transcription
 *  of one named file, and the platform checks it before it stores it. A page that
 *  does not add up, or that disagrees with the document, is refused with the
 *  problems named. A reason then stores it anyway, and the problems and the reason
 *  stay with the page. It moves no money: the net, the positions, the currency and
 *  the date of the document never change. So there is no dry run to read first.
 */
import { useState } from "react";
import {
  errorMessage,
  getDocumentAttachments,
  putPrintedInvoice,
  type RunCostDocumentRow,
} from "../../api";
import AutoTextarea from "../AutoTextarea";
import Field, { FieldGrid } from "../Field";
import InfoTip from "../InfoTip";
import { useModal } from "../modal";
import { ErrorBanner, Spinner } from "../Ui";
import { useLoad } from "../useLoad";

const PARTY = { name: "", nip: "", address_l1: "", address_l2: "", country: "" };

/** A page to fill in. Every key is one the server reads. */
const BLANK_PAGE = {
  title: "",
  seller: PARTY,
  buyer: PARTY,
  lines: [{ position: 1, name: "", qty: 1, unit: "szt.", unit_net: 0, net: 0, vat_rate: "23", vat: 0, gross: 0 }],
  totals: { net: 0, vat: 0, gross: 0, rates: { 23: { net: 0, vat: 0 } }, vat_pln: null },
  payment: { due_date: null, method: "", paid: false, paid_date: null },
  extra_info: [],
  notes: [],
};

/** What the box starts with: the page this document holds, or a blank one. */
function initialPage(doc: RunCostDocumentRow): string {
  if (!doc.body) return JSON.stringify(BLANK_PAGE, null, 2);
  const { source: _source, ...page } = doc.body;
  return JSON.stringify(page, null, 2);
}

export default function TranscribeDialog({ doc, onClose }: {
  doc: RunCostDocumentRow;
  onClose: (changed: boolean) => void;
}) {
  const modal = useModal(() => onClose(false));
  const [fileId, setFileId] = useState<number | null>(null);
  const [number, setNumber] = useState(doc.doc_number ?? "");
  const [issue, setIssue] = useState(doc.doc_date ?? "");
  const [sale, setSale] = useState(doc.sale_date ?? "");
  const [currency, setCurrency] = useState(doc.currency ?? "PLN");
  const [page, setPage] = useState(() => initialPage(doc));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: fileRows, error, setError } = useLoad(
    (signal) =>
      getDocumentAttachments(doc.id, signal).then((f) => {
        const read = doc.body?.source?.kind === "file" ? doc.body.source.attachment_id : null;
        setFileId(f.find((x) => x.id === read)?.id ?? f[0]?.id ?? null);
        return f;
      }),
    [doc],
    { keep: true },
  );
  const files = fileRows ?? (error ? [] : null);

  let parsed: unknown = null;
  let pageError = "";
  try {
    parsed = JSON.parse(page);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) pageError = "Write one JSON object, in braces.";
  } catch (err) {
    pageError = `This is not valid JSON: ${errorMessage(err)}`;
  }

  const store = async () => {
    if (fileId === null) return;
    setBusy(true);
    setError(null);
    try {
      await putPrintedInvoice(doc.id, {
        attachment_id: fileId, number, issue_date: issue, sale_date: sale,
        currency: currency.trim().toUpperCase(), body: parsed, reason,
      });
      onClose(true);
    } catch (err) {
      // A refusal names every problem, and the form stays as it is: the answer
      // is a corrected figure, or a reason.
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">Transcribe the printed invoice</h2>
        <p className="muted dim">
          Copy what one of this document's files prints. The platform checks that the positions and the
          rates add up to the net and the VAT, and compares the page with the document. The net, the
          positions, the currency and the date of the document do not change. The printed VAT replaces
          the typed VAT.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        {files && !files.length ? (
          <p className="banner-warn">This document has no file. Add its original first.</p>
        ) : null}
        <FieldGrid>
          <Field label="Read from" hint="One of this document's own files.">
            <select className="text" value={fileId ?? ""} onChange={(e) => setFileId(Number(e.target.value) || null)}>
              {files === null ? <option value="">Loading…</option> : null}
              {(files ?? []).map((f) => <option key={f.id} value={f.id}>{f.filename}</option>)}
            </select>
          </Field>
          <Field label="Number" hint="As the page prints it.">
            <input className="text mono" value={number} maxLength={256} onChange={(e) => setNumber(e.target.value)} />
          </Field>
          <Field label="Issue date">
            <input className="text" type="date" value={issue} onChange={(e) => setIssue(e.target.value)} />
          </Field>
          <Field label="Sale date" hint="Empty: the issue date.">
            <input className="text" type="date" value={sale} onChange={(e) => setSale(e.target.value)} />
          </Field>
          <Field label="Currency">
            <input className="text num-input" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} />
          </Field>
          <Field wide
            label={<>The page (JSON) <InfoTip label="About the page">
              <b>seller, buyer</b>: name, nip, address_l1, address_l2, country.<br />
              <b>lines</b>: position, name, qty, unit, unit_net, net, vat_rate, vat, gross. A position needs its
              position and its net. vat_rate is the rate as printed: 23, 8, 5, 0, zw, np or oo.<br />
              <b>totals</b>: net, vat, gross, and rates: one entry per rate, with net and vat. vat_pln is the VAT in
              PLN that an invoice in another currency prints.<br />
              <b>payment</b>: due_date, method, paid, paid_date.<br />
              <b>extra_info, notes</b>: lists of lines.
            </InfoTip></>}
            error={pageError}
            hint="Amounts are numbers in the invoice's currency. A date is YYYY-MM-DD or null.">
            <AutoTextarea className="text mono" rows={12} maxRows={28} value={page} onChange={(e) => setPage(e.target.value)} />
          </Field>
          <Field wide label="Reason" hint="Needed only when the page disagrees with itself or with the document. It stays with the page.">
            <AutoTextarea className="text" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        </FieldGrid>
        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" onClick={() => onClose(false)}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || fileId === null || !!pageError || !number.trim() || !issue}
            onClick={() => void store()}>
            Check and store
          </button>
        </div>
      </div>
    </div>
  );
}
