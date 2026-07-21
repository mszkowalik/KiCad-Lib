import { useEffect, useRef, useState } from "react";
import {
  errorMessage,
  getDatasheetFetchStatus,
  getKicadConfig,
  httplibFileUrl,
  isAbortError,
  startDatasheetFetchAll,
  syncScriptUrl,
  ApiError,
  type DatasheetFetchStatus,
  type KicadConfig,
} from "../api";
import { ErrorBanner, Spinner } from "../components/Ui";

const POLL_MS = 2000;

export default function KicadPage() {
  const [config, setConfig] = useState<KicadConfig | null>(null);
  const [status, setStatus] = useState<DatasheetFetchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const loadStatus = () => {
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
  };

  useEffect(() => {
    const ctrl = new AbortController();
    getKicadConfig(ctrl.signal)
      .then(setConfig)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    loadStatus();
    return () => {
      ctrl.abort();
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
      pollRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchAll = (mode: "missing" | "all") => {
    setError(null);
    startDatasheetFetchAll(mode)
      .then(() => loadStatus())
      .catch((err) => {
        // 409 = already running — just start polling
        if (err instanceof ApiError && err.status === 409) loadStatus();
        else setError(errorMessage(err));
      });
  };

  const base = config?.public_base_url ?? "…";

  return (
    <div className="main-solo">
      <div className="page kicad-page">
        <h1>KiCad integration</h1>
        {error ? <ErrorBanner message={error} /> : null}

        <div className="card pad">
          <h2>Install as a KiCad plugin (recommended)</h2>
          <p className="muted">
            The platform serves a Plugin and Content Manager repository. Add it once; the
            library then installs from inside KiCad — no scripts. Three packages:{" "}
            <b>7Sigma Library</b> (the deduplicated base symbol drawings + footprints —
            parts are picked from the live HTTP catalog below, which references these, so
            adding components never requires a library update), <b>7Sigma 3D Models</b>{" "}
            and <b>7Sigma Library Sync</b> — a toolbar button in the PCB and schematic
            editors that pulls updates on click (changed 3D models transfer as a small
            compressed delta, not the full package).
          </p>
          <pre className="code-block">{config?.pcm_repo_url ?? "…"}</pre>
          <ol className="kicad-steps">
            <li>
              KiCad → Tools → <b>Plugin and Content Manager</b> → Manage… (repository icon) →
              add the URL above
            </li>
            <li>
              Select the <b>7Sigma Library Platform</b> repository, install{" "}
              <b>7Sigma Library</b>, <b>7Sigma 3D Models</b> and <b>7Sigma Library Sync</b>
            </li>
            <li>
              When KiCad asks, let it <b>add the libraries to the global tables</b> — they appear
              as <code>PCM_7Sigma_Base</code> (symbol drawings) and <code>PCM_7Sigma</code>{" "}
              (footprints)
            </li>
            <li>
              To pull library updates later, press the <b>Sync 7Sigma Library</b> toolbar
              button in the PCB or schematic editor (or use PCM's Update — both work)
            </li>
          </ol>
        </div>

        <div className="card pad">
          <h2>Live part catalog (HTTP library)</h2>
          <p className="muted">
            KiCad browses parts, fields and prices live from this platform. Symbols and
            footprints still come from the locally synced files (below) — KiCad cannot fetch
            geometry over HTTP.
          </p>
          <a className="btn btn-primary" href={httplibFileUrl} download>
            Download 7Sigma.kicad_httplib
          </a>
          <ol className="kicad-steps">
            <li>
              KiCad → Preferences → <b>Manage Symbol Libraries</b> → Add existing library
            </li>
            <li>Pick the downloaded 7Sigma.kicad_httplib — the type is detected automatically</li>
            <li>Parts appear in the symbol chooser with live fields and pricing</li>
          </ol>
        </div>

        <div className="card pad">
          <h2>Sync via CLI (alternative to the plugin)</h2>
          <p className="muted">
            The sync CLI mirrors the published library files to your machine — incremental,
            checksum-based. Re-run it any time; only changed files are transferred. Use this
            OR the plugin install above, not both (the CLI flow uses unprefixed nicknames —
            set <code>SYMBOL_LIB_NICKNAME_TEMPLATE</code> / <code>FOOTPRINT_LIB_NICKNAME</code>{" "}
            in <code>platform/.env</code> to match your choice).
          </p>
          <a className="btn" href={syncScriptUrl} download>
            Download kicadlib.py
          </a>
          <pre className="code-block">python3 kicadlib.py sync --url {base} --dest ~/7SigmaLib
{"# add --prune to also delete files removed upstream"}</pre>
          <ol className="kicad-steps">
            <li>
              Preferences → Configure Paths: <code>SEVENSIGMA_DIR</code> = your sync directory
            </li>
            <li>
              Manage Symbol Libraries: add each library from <code>&lt;dest&gt;/Symbols/</code>
            </li>
            <li>
              Manage Footprint Libraries: add{" "}
              <code>&lt;dest&gt;/Footprints/7Sigma.pretty</code> with nickname <code>7Sigma</code>
            </li>
            <li>Add the .kicad_httplib (above) for the live catalog</li>
          </ol>
        </div>

        <div className="card pad">
          <h2>Datasheet archive</h2>
          {status === null ? (
            <Spinner label="Loading status" />
          ) : (
            <>
              <p className="mono kicad-ds-stat">
                {status.datasheets_with_local_copy} / {status.datasheets_total} datasheets stored
                locally
                {status.running
                  ? ` — fetching… ${status.done}/${status.total} (${status.new_versions} new)`
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

        <div className="card pad">
          <h2>Configuration</h2>
          <table className="kv">
            <tbody>
              <tr>
                <td>Public base URL</td>
                <td className="mono">{config?.public_base_url ?? "…"}</td>
              </tr>
              <tr>
                <td>HTTP library root</td>
                <td className="mono">{config?.httplib_root_url ?? "…"}</td>
              </tr>
              <tr>
                <td>File mirror</td>
                <td className="mono">{config?.mirror_url ?? "…"}</td>
              </tr>
              <tr>
                <td>Token</td>
                <td className="mono">{config?.token_hint ?? "…"}</td>
              </tr>
            </tbody>
          </table>
          <p className="muted">
            Moving online: set <code>PUBLIC_BASE_URL</code> (e.g.{" "}
            <code>https://disfunction.cc/lib</code>) and <code>HTTPLIB_TOKEN</code> in{" "}
            <code>platform/.env</code>, then re-download the .kicad_httplib — it embeds these
            values.
          </p>
        </div>
      </div>
    </div>
  );
}
