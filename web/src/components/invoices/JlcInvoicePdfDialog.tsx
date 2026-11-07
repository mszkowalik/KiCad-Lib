/** Draw JLCPCB's invoice for chosen documents and file each PDF with its document
 *  (decisions 0082, 0086). JLCPCB keeps no file of either kind: its DOWNLOAD button
 *  screenshots the page, so the platform draws the page from JLC's own data.
 *
 *  The route has no dry run, so this picks from the register, asks, then shows one
 *  answer per document. A dead session stops the run and `detail.results` holds what
 *  was done before it, so the dialog prints both.
 */
import { useMemo, useState } from "react";
import {
  ApiError,
  attachmentPath,
  drawJlcInvoicePdfs,
  errorMessage,
  getInvoiceRegister,
  type JlcInvoicePdfResult,
  type RunCostDocumentRow,
} from "../../api";
import { plain } from "../../format";
import { fileHref } from "../../viewkind";
import DataTable, { type Column } from "../DataTable";
import { useDialog } from "../Dialog";
import { CheckField } from "../Field";
import { useModal } from "../modal";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { useLoad } from "../useLoad";

/** The route's own cap on one request. */
const MAX_DOCUMENTS = 200;

/** The route draws a W… or a POB… and refuses the rest. */
function isJlcInvoice(d: RunCostDocumentRow): boolean {
  const ext = (d.external_id ?? "").toUpperCase();
  return /jlc/i.test(d.supplier) && (ext.startsWith("W") || ext.startsWith("POB"));
}

export default function JlcInvoicePdfDialog({ onClose }: { onClose: () => void }) {
  const dialog = useDialog();
  const [showFiled, setShowFiled] = useState(false);
  const [force, setForce] = useState(false);
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [visible, setVisible] = useState<RunCostDocumentRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<JlcInvoicePdfResult[] | null>(null);
  const modal = useModal(onClose);

  const { data: docs, error, setError, reload: load } = useLoad(
    (signal) => getInvoiceRegister(signal).then((r) => r.documents.filter(isJlcInvoice)),
    [],
  );

  const rows = useMemo(
    () => (docs ?? []).filter((d) => showFiled || !(d.attachment_count ?? 0)),
    [docs, showFiled],
  );
  const byId = useMemo(() => new Map((docs ?? []).map((d) => [d.id, d])), [docs]);
  const allTicked = visible.length > 0 && visible.every((d) => ticked.has(d.id));

  const toggle = (id: number, on: boolean) =>
    setTicked((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const columns: Column<RunCostDocumentRow>[] = [
    { key: "sel", width: 5, interactive: false, sortable: true, className: "ctr",
      label: (
        <input type="checkbox" checked={allTicked} disabled={!visible.length}
          aria-label={allTicked ? "Untick every document shown" : "Tick every document shown"}
          onChange={() => {
            setTicked((s) => {
              const next = new Set(s);
              for (const d of visible) {
                if (allTicked) next.delete(d.id);
                else next.add(d.id);
              }
              return next;
            });
          }} />
      ),
      get: (d) => (ticked.has(d.id) ? 1 : 0),
      sortValue: (d) => (ticked.has(d.id) ? 0 : 1),
      render: (d) => (
        <input type="checkbox" checked={ticked.has(d.id)} aria-label={`Tick ${d.external_id}`}
          onChange={(e) => toggle(d.id, e.target.checked)} />
      ) },
    { key: "ext", label: "JLC number", width: 32, className: "mono", get: (d) => d.external_id },
    { key: "kind", label: "Kind", width: 13,
      get: (d) => (d.external_id.toUpperCase().startsWith("W") ? "assembly" : "parts") },
    { key: "date", label: "Date", width: 14, className: "mono", get: (d) => d.doc_date },
    { key: "total", label: "Total", width: 16, numeric: true, get: (d) => d.total_amount,
      render: (d) => `${plain(d.total_amount)} ${d.currency}` },
    { key: "files", label: "Files", width: 20, numeric: true, get: (d) => d.attachment_count ?? 0 },
  ];

  const resultColumns: Column<JlcInvoicePdfResult>[] = [
    { key: "ext", label: "JLC number", width: 30, className: "mono",
      get: (r) => byId.get(r.document_id)?.external_id ?? "" },
    { key: "status", label: "Result", width: 12, get: (r) => r.status,
      render: (r) => <StatusPill status={r.status} /> },
    { key: "file", label: "File", width: 28, get: (r) => r.filename ?? "",
      render: (r) => (r.attachment_id && r.filename
        ? (
          <a className="comp-link" target="_blank" rel="noreferrer"
            href={fileHref(attachmentPath(r.attachment_id), r.filename)}>
            {r.filename}
          </a>
        )
        : "—") },
    { key: "note", label: "Note", width: 30, className: "muted",
      get: (r) => [r.reason, r.error, ...(r.warnings ?? [])].filter(Boolean).join(". ") },
  ];

  const draw = async () => {
    const ids = [...ticked];
    if (!(await dialog.confirm(
      `Draw ${ids.length} invoice PDF(s) from JLCPCB's data, and file each one with its document?` +
        (force
          ? " A document that has a PDF gets one more. The new file becomes the headline file, and the old file stays."
          : " A document that has a PDF is skipped.") +
        " There is no dry run.",
      { title: "Draw invoice PDFs", confirmLabel: "Draw" },
    ))) return;
    setBusy(true);
    setError("");
    setResults(null);
    try {
      const r = await drawJlcInvoicePdfs(ids, force);
      setResults(r.results);
    } catch (err) {
      setError(errorMessage(err));
      // The route stops at a dead session and names what it did before that.
      const detail = err instanceof ApiError ? (err.detail as { results?: JlcInvoicePdfResult[] } | undefined) : undefined;
      if (detail?.results) setResults(detail.results);
    } finally {
      setBusy(false);
      setTicked(new Set());
      void load();
    }
  };

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">Draw invoice PDFs</h2>
        <p className="muted dim">
          JLCPCB keeps no PDF of its invoices. Its DOWNLOAD button only prints the page. This job reads the invoice data
          through the JLC session, draws the page with the same figures and files the PDF with the document. It needs a
          live session. If the session stops part way, the PDFs drawn before that stay.
        </p>
        <div className="btn-row">
          <CheckField checked={showFiled} onChange={setShowFiled}>Show documents that have a file</CheckField>
          <CheckField checked={force} onChange={setForce}
            title="The new file is added. It does not take the place of the old file.">
            Draw again if the document has a PDF
          </CheckField>
        </div>
        {docs === null && !error ? <Spinner label="Reading the register…" /> : null}
        {docs !== null ? (
          <DataTable<RunCostDocumentRow>
            rows={rows}
            rowKey={(d) => d.id}
            columns={columns}
            defaultSort={{ key: "date", dir: "desc" }}
            empty="No JLCPCB document without a file."
            onVisibleChange={setVisible}
          />
        ) : null}
        {/* Beside the button that was pressed: the table above can be 50 rows long. */}
        <ErrorBanner message={error} />
        {results ? (
          <>
            <h3 className="card-title">Result</h3>
            <DataTable<JlcInvoicePdfResult>
              rows={results}
              rowKey={(r) => r.document_id}
              columns={resultColumns}
              empty="No document was drawn before the job stopped."
            />
          </>
        ) : null}
        {ticked.size > MAX_DOCUMENTS ? (
          <div className="banner-warn">One run takes {MAX_DOCUMENTS} documents. Untick some of them.</div>
        ) : null}
        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" disabled={busy} onClick={onClose}>Close</button>
          <button type="button" className="btn btn-primary" disabled={busy || !ticked.size || ticked.size > MAX_DOCUMENTS}
            onClick={() => void draw()}>
            Draw {ticked.size || ""} PDF(s)…
          </button>
        </div>
      </div>
    </div>
  );
}
