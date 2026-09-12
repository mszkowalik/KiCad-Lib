import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  errorMessage,
  getDatasheetFetchStatus,
  getFxRates,
  getSchemaHealth,
  isAbortError,
  refreshFxRates,
  setFxRate,
  startDatasheetFetchAll,
  type DatasheetFetchStatus,
  type FxRate,
} from "../api";
import { useAuth } from "../auth";
import SettingsCard from "../components/SettingsCard";
import UsersCard from "../components/UsersCard";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import { ErrorBanner, Spinner } from "../components/Ui";

const POLL_MS = 2000;

/** Administration of the DEPLOYMENT: its shared configuration, other people's
 * accounts, and the jobs and health readouts nobody owns personally. It was
 * called "Setup" until 2026-09-12; anything that belongs to the signed-in user
 * rather than to the deployment lives on `/account` instead.
 *
 * One page for everything that is configured once and then only checked:
 * KiCad clients, Claude Code / MCP, the datasheet archive job, exchange
 * rates, and schema health. Previously spread over the KiCad page and a
 * collapsed block at the bottom of Skills.
 */
export default function Admin() {
  const { isAdmin } = useAuth();

  return (
    <div className="main-solo">
      <div className="page admin-page">
        <h1>Admin</h1>

        {/* Configuration first: it is what a visit to this page is usually for. */}
        <SettingsCard />

        {/* Admin only. The API refuses a non-admin anyway (403 from
            /api/users) — hiding the card keeps the page from showing a
            control that can only fail. */}
        {isAdmin ? <UsersCard /> : null}

        <div className="card pad">
          <h2>KiCad clients and your API token</h2>
          <p className="muted">
            The install links, the .kicad_httplib download, the MCP settings and the
            effective URLs are on your{" "}
            <Link className="comp-link" to="/account">Account</Link> page. They carry YOUR
            token, so they differ per person — this page is the deployment's shared
            configuration.
          </p>
        </div>

        <DatasheetCard />
        <FxCard />
        <HealthCard />

      </div>
    </div>
  );
}

function DatasheetCard() {
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
      <h2>Datasheet archive</h2>
      <ErrorBanner message={error} />
      {status === null ? (
        <Spinner label="Loading status" />
      ) : (
        <>
          <p className="mono kicad-ds-stat">
            {status.datasheets_with_local_copy} / {status.datasheets_total} datasheets stored
            locally
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
              ? `Nightly re-check of every source URL at ${new Date(
                  status.next_nightly_at,
                ).toLocaleString()} — unchanged documents answer 304 and are not downloaded.`
              : "Nightly re-check disabled (DATASHEET_RECHECK_NIGHTLY=false)."}
            {status.last_nightly_at
              ? ` Last ran ${new Date(status.last_nightly_at).toLocaleString()}.`
              : ""}
          </p>
          {status.errors > 0 ? (
            <p className="muted">
              {status.errors} fetch error{status.errors === 1 ? "" : "s"}
              {status.last_error ? ` — last: ${status.last_error}` : ""}
            </p>
          ) : null}
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

/* Was a hand-rolled `<table className="data">` — the same header font as every
   other table, but no sort control and no filter row, so it read as a different
   kind of table. 29 currencies is a list, and a list is sorted and filtered
   (2026-09-12). `override` is passed in because the action column calls it. */
function fxCols(override: (r: FxRate) => void): Column<FxRate>[] {
  return [
    { key: "currency", label: "Currency", width: 16, className: "mono", get: (r) => r.currency },
    { key: "rate", label: "Rate USD", width: 22, numeric: true, className: "mono", get: (r) => r.rate_usd },
    {
      key: "source",
      label: "Source",
      width: 20,
      get: (r) => r.source,
      render: (r) => (
        <span className={`pill ${r.source === "manual" ? "warn" : "neutral"}`}>{r.source}</span>
      ),
    },
    {
      key: "updated",
      label: "Updated",
      width: 24,
      className: "muted dim",
      get: (r) => r.updated_at ?? "",
      title: (r) => r.updated_at ?? undefined,
      render: (r) => <>{r.updated_at ? new Date(r.updated_at).toLocaleDateString() : "—"}</>,
    },
    {
      key: "override",
      label: "",
      width: 18,
      interactive: false,
      get: () => "",
      render: (r) => (
        <button
          type="button"
          className="btn btn-sm"
          onClick={(e) => {
            e.stopPropagation();
            override(r);
          }}
        >
          Override
        </button>
      ),
    },
  ];
}

function FxCard() {
  const dialog = useDialog();
  const [rates, setRates] = useState<FxRate[] | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback((signal?: AbortSignal) => {
    getFxRates(signal)
      .then((r) => {
        setRates(r);
        setError("");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  async function refresh() {
    setBusy(true);
    setNote("");
    try {
      const r = await refreshFxRates();
      setNote(`Updated ${r.updated} rate(s) across ${r.currencies} currencies.`);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function override(row: FxRate) {
    const v = await dialog.prompt(
      `New rate_usd value for ${row.currency} (currently ${row.rate_usd}):`,
      { title: "Override exchange rate" },
    );
    if (v === null) return;
    const num = Number(v);
    if (!Number.isFinite(num) || num <= 0) {
      await dialog.alert(`"${v}" is not a positive number.`, { title: "Bad rate" });
      return;
    }
    try {
      await setFxRate(row.currency, num);
      load();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not save the rate" });
    }
  }

  return (
    <div className="card pad">
      <h2>Exchange rates</h2>
      <p className="muted">
        The register converts every document to USD with these rates. An "unknown FX rate"
        warning anywhere in the app means a currency is missing here.
      </p>
      <ErrorBanner message={error} />
      {note ? <div className="banner-ok">{note}</div> : null}
      <div className="btn-row">
        <button type="button" className="btn" disabled={busy} onClick={refresh}>
          Refresh rates
        </button>
      </div>
      {rates === null ? (
        <Spinner label="loading rates" />
      ) : rates.length === 0 ? (
        <p className="muted">No rates stored yet — press Refresh rates.</p>
      ) : (
        <div className="table-wrap">
          <DataTable
            columns={fxCols(override)}
            rows={rates}
            rowKey={(r) => r.currency}
            persistKey="fx-rates"
            empty="No exchange rates yet."
          />
        </div>
      )}
    </div>
  );
}

function HealthCard() {
  const [health, setHealth] = useState<Awaited<ReturnType<typeof getSchemaHealth>> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const ac = new AbortController();
    getSchemaHealth(ac.signal)
      .then(setHealth)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  const failedCount = health ? Object.keys(health.failed).length : 0;

  return (
    <div className="card pad">
      <h2>Schema health</h2>
      <p className="muted">
        Which additive startup migrations landed. A feature that depends on a missing column
        fails far from the cause — this is where to look first.
      </p>
      <ErrorBanner message={error} />
      {health === null ? (
        !error && <Spinner label="checking schema" />
      ) : (
        <>
          <div className="toolbar">
            <span className={`pill ${health.ok ? "ok" : "err"}`}>
              {health.ok ? "all statements applied" : `${failedCount} failed`}
            </span>
            <span className="muted">{Object.keys(health.statements).length} statements</span>
          </div>
          {failedCount > 0 && (
            <div className="table-wrap">
              <table className="data data-fixed schema-table">
                <thead>
                  <tr>
                    <th>statement</th>
                    <th>result</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(health.failed).map(([name, result]) => (
                    <tr key={name}>
                      <td className="mono" title={name}>
                        {name}
                      </td>
                      <td className="cell-desc" title={result}>
                        {result}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {health.note ? <p className="muted dim">{health.note}</p> : null}
        </>
      )}
    </div>
  );
}
