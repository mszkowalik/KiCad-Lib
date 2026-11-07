import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  errorMessage,
  getDatasheetFetchStatus,
  startDatasheetFetchAll,
  type DatasheetFetchStatus,
} from "../api";
import { useAuth } from "../auth";
import { ErrorBanner, Spinner } from "./Ui";
import { localWhen, plural } from "../format";

const POLL_MS = 2000;

export default function DatasheetArchiveCard() {
  // The READOUT is for everybody — what the archive holds and when the nightly
  // runs is ordinary library information. The two buttons start a job that
  // walks every document and can bump component versions, so the API refuses
  // them to a non-admin (decision 0045) and the page does not offer them.
  const { isAdmin } = useAuth();
  const [status, setStatus] = useState<DatasheetFetchStatus | null>(null);
  const [error, setError] = useState("");
  const pollRef = useRef<number | null>(null);

  const loadStatus = useCallback(() => {
    getDatasheetFetchStatus()
      .then((s) => {
        setStatus(s);
        if (s.running && pollRef.current === null) {
          pollRef.current = window.setInterval(() => {
            getDatasheetFetchStatus()
              .then((s2) => {
                setStatus(s2);
                if (!s2.running && pollRef.current !== null) {
                  window.clearInterval(pollRef.current);
                  pollRef.current = null;
                }
              })
              .catch(() => {});
          }, POLL_MS);
        }
      })
      .catch((err) => setError(errorMessage(err)));
  }, []);

  useEffect(() => {
    loadStatus();
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [loadStatus]);

  const fetchAll = (mode: "missing" | "all") => {
    setError("");
    startDatasheetFetchAll(mode)
      .then(() => loadStatus())
      .catch((err) => {
        // 409 = already running — just start polling
        if (err instanceof ApiError && err.status === 409) loadStatus();
        else setError(errorMessage(err));
      });
  };

  return (
    <div className="card pad">
      <h2 className="card-title">Datasheet archive</h2>
      <ErrorBanner message={error} />
      {status === null ? (
        <Spinner label="Loading status" />
      ) : (
        <>
          <p className="mono kicad-ds-stat">
            {/* Both figures count one set, the rows a component lists. A stored
                web page is a copy KiCad does not open, so it is named apart. */}
            {status.datasheets_with_local_copy} / {status.datasheets_total} datasheets stored
            locally — KiCad opens the stored copy of {status.datasheets_kicad_local}
            {status.datasheets_kicad_live
              ? `, and the live link of ${status.datasheets_kicad_live} web page(s)`
              : ""}
            {status.running
              ? ` — fetching… ${status.done}/${status.total} (${status.new_versions} new, ${status.restamped} re-signed)`
              : ""}
            {status.storage
              ? ` — ${status.storage.documents} distinct files, ${Math.round(
                  status.storage.document_bytes / 1048576,
                )} MB, ${status.storage.documents_shared_by_several_datasheets} shared between parts`
              : ""}
          </p>
          <p className="muted">
            {status.next_nightly_at
              ? `Nightly re-check of every source URL at ${localWhen(
                  status.next_nightly_at,
                )} — unchanged documents answer 304 and are not downloaded.`
              : "Nightly re-check disabled (DATASHEET_RECHECK_NIGHTLY=false)."}
            {status.last_nightly_at
              ? ` Last ran ${localWhen(status.last_nightly_at)}.`
              : ""}
          </p>
          {status.errors > 0 ? (
            <p className="muted">
              {plural(status.errors, "fetch error")}
              {status.last_error ? ` — last: ${status.last_error}` : ""}
            </p>
          ) : null}
          {isAdmin ? (
            <div className="btn-row">
              <button
                type="button"
                className="btn"
                disabled={status.running}
                onClick={() => fetchAll("missing")}
              >
                Fetch missing
              </button>
              <button
                type="button"
                className="btn"
                disabled={status.running}
                title="Re-downloads every datasheet and creates new PDF versions when content changed (auto-bumps affected components)"
                onClick={() => fetchAll("all")}
              >
                Re-check all (detect changed PDFs)
              </button>
            </div>
          ) : null}
          <p className="muted">
            PDFs are stored versioned — a changed document creates a new PDF version and
            automatically records a new component version pinning it. Web-page "datasheets"
            (e.g. LCSC product pages) keep a single local copy and are never versioned.
          </p>
        </>
      )}
    </div>
  );
}
