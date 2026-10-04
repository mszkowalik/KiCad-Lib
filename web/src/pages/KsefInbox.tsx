/** The invoices KSeF holds for our companies (decision 0067).
 *
 *  Read only: fetching fills this inbox and nothing else. A sales invoice is
 *  linked to the platform's own record of it by the sync. A purchase waits
 *  here until somebody imports it as a supplier document (Production →
 *  Invoices, where its positions get their destinations) or skips it with a
 *  reason.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getKsefInbox,
  importKsefPurchase,
  isAbortError,
  ksefXmlPath,
  skipKsefInvoice,
  type KsefInboxRow,
} from "../api";
import { useAuth } from "../auth";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import { ErrorBanner, Spinner } from "../components/Ui";
import { absoluteFileUrl } from "../viewkind";

const TONE: Record<string, string> = { new: "warn", linked: "ok", imported: "ok", skipped: "neutral" };

function pl(x: string | null): string {
  return x == null ? "—" : Number(x).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function KsefInbox() {
  const dialog = useDialog();
  const { companyName } = useAuth();
  const [rows, setRows] = useState<KsefInboxRow[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    getKsefInbox(signal).then((r) => { setRows(r); setError(""); })
      .catch((e) => { if (!isAbortError(e)) setError(errorMessage(e)); });
  }, []);
  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  const act = async (id: number, fn: () => Promise<unknown>) => {
    setBusy(id);
    setError("");
    try {
      await fn();
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const cols: Column<KsefInboxRow>[] = [
    { key: "date", label: "Date", width: 9, className: "mono", get: (r) => r.issue_date },
    { key: "company", label: "Company", width: 8, get: (r) => companyName(r.company_id) },
    { key: "side", label: "Side", width: 8, get: (r) => (r.side === "sales" ? "sales" : "purchase") },
    { key: "party", label: "Counterparty", width: 22,
      get: (r) => (r.side === "sales" ? r.buyer_name : r.seller_name) || (r.side === "sales" ? r.buyer_nip : r.seller_nip),
      title: (r) => `NIP ${r.side === "sales" ? r.buyer_nip : r.seller_nip}` },
    { key: "number", label: "Number", width: 13, className: "mono", get: (r) => r.invoice_number,
      title: (r) => `KSeF ${r.ksef_number}` },
    { key: "gross", label: "Gross", width: 9, numeric: true, get: (r) => Number(r.gross ?? 0),
      render: (r) => <>{pl(r.gross)} {r.currency !== "PLN" ? r.currency : ""}</> },
    { key: "status", label: "Status", width: 9, get: (r) => r.status,
      render: (r) => <span className={`pill ${TONE[r.status] ?? "neutral"}`}>{r.status}</span> },
    { key: "act", label: "", width: 22, interactive: false, get: () => "",
      render: (r) => (
        <span className="btn-row">
          {r.has_xml ? <a className="btn btn-sm" href={absoluteFileUrl(ksefXmlPath(r.id))}>XML</a> : null}
          {r.document_id ? (
            <Link className="btn btn-sm" to={`/production/invoices?doc=${r.document_id}`}>Document</Link>
          ) : null}
          {r.sales_invoice_id ? <Link className="btn btn-sm" to="/production/sales-invoices">Invoice</Link> : null}
          {r.side === "purchase" && r.status === "new" ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy !== null || !r.has_xml}
                title={r.has_xml ? "Write it as a supplier document" : "Its XML is not downloaded yet"}
                onClick={() => void act(r.id, () => importKsefPurchase(r.id))}>
                {busy === r.id ? "…" : "Import"}
              </button>
              <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={async () => {
                const reason = await dialog.prompt("Why is this invoice skipped?", { title: "Skip" });
                if (reason) await act(r.id, () => skipKsefInvoice(r.id, reason));
              }}>
                Skip…
              </button>
            </>
          ) : null}
        </span>
      ) },
  ];

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1 className="page-title">KSeF</h1>
          {rows ? (
            <span className="toolbar-total">
              {rows.filter((r) => r.side === "purchase" && r.status === "new").length} purchase(s) to import
            </span>
          ) : null}
        </div>
        <p className="muted dim">
          What KSeF holds for our companies. An admin reads it in with "Sync" on Admin → Companies. Sales invoices
          link to their record by themselves; a purchase becomes a supplier document when you import it.
        </p>
        <ErrorBanner message={error} />
        <div className="card pad">
          {rows === null ? (
            <Spinner label="Loading the inbox…" />
          ) : (
            <DataTable rows={rows} rowKey={(r) => r.id} columns={cols} empty="Nothing read from KSeF yet."
                       defaultSort={{ key: "date", dir: "desc" }} />
          )}
        </div>
      </div>
    </div>
  );
}
