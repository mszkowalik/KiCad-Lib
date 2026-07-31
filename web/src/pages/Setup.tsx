import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  API_URL,
  errorMessage,
  getDatasheetFetchStatus,
  getFxRates,
  getKicadConfig,
  getSchemaHealth,
  httplibFileUrl,
  isAbortError,
  refreshFxRates,
  setFxRate,
  startDatasheetFetchAll,
  syncScriptUrl,
  type DatasheetFetchStatus,
  type FxRate,
  type KicadConfig,
} from "../api";
import { useAuth } from "../auth";
import SettingsCard from "../components/SettingsCard";
import UsersCard from "../components/UsersCard";
import { useDialog } from "../components/Dialog";
import { ErrorBanner, Spinner } from "../components/Ui";

const POLL_MS = 2000;

/**
 * One page for everything that is configured once and then only checked:
 * KiCad clients, Claude Code / MCP, the datasheet archive job, exchange
 * rates, and schema health. Previously spread over the KiCad page and a
 * collapsed block at the bottom of Skills.
 */
export default function Setup() {
  const [config, setConfig] = useState<KicadConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { isAdmin } = useAuth();

  useEffect(() => {
    const ctrl = new AbortController();
    getKicadConfig(ctrl.signal)
      .then(setConfig)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, []);

  const base = config?.public_base_url ?? "…";

  return (
    <div className="main-solo">
      <div className="page kicad-page">
        <h1>Setup</h1>
        <ErrorBanner message={error ?? ""} />

        {/* Configuration first: it is what a visit to this page is usually for. */}
        <SettingsCard />

        {/* Admin only. The API refuses a non-admin anyway (403 from
            /api/users) — hiding the card keeps the page from showing a
            control that can only fail. */}
        {isAdmin ? <UsersCard /> : null}

        <div className="card pad">
          <h2>Effective URLs</h2>
          <p className="muted">
            Derived from <code>Public base URL</code> above — these are what KiCad clients use.
            Change the setting and re-download the .kicad_httplib, which embeds them.
          </p>
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
                <td>PCM repository</td>
                <td className="mono">{config?.pcm_repo_url ?? "…"}</td>
              </tr>
              <tr>
                <td>Token</td>
                <td className="mono">{config?.token_hint ?? "…"}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="card pad">
          <h2>KiCad — install as a plugin (recommended)</h2>
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
          <pre className="code-block code-block-wrap">{config?.pcm_repo_url ?? "…"}</pre>
          {config?.personalised ? (
            <p className="muted dim">
              This URL is <b>yours</b> — it carries your API token, and the sync plugin it
              installs arrives with that token already inside it. Do not share it; give a
              colleague their own account instead.
            </p>
          ) : (
            <p className="muted dim">
              This URL carries no token. Sign in, or have an administrator issue you one on
              the Users card, to get a personal URL that also authenticates the sync plugin.
            </p>
          )}
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
          <h2>KiCad — live part catalog (HTTP library)</h2>
          <p className="muted">
            KiCad browses parts, fields and prices live from this platform. Symbols and
            footprints still come from the locally synced files — KiCad cannot fetch
            geometry over HTTP.
          </p>
          {/* The personalised link when we have one: the file's `token` field is
              then the signed-in user's own, not the shared fallback. */}
          <a className="btn btn-primary" href={config?.httplib_url || httplibFileUrl} download>
            Download 7Sigma.kicad_httplib
          </a>
          <ol className="kicad-steps">
            <li>
              KiCad → Preferences → <b>Manage Symbol Libraries</b> → Add existing library
            </li>
            <li>Pick the downloaded 7Sigma.kicad_httplib — the type is detected automatically</li>
            <li>Parts appear in the symbol chooser with live fields and pricing</li>
          </ol>
          <details>
            <summary className="muted">Sync via CLI instead of the plugin</summary>
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
          </details>
        </div>

        <div className="card pad">
          <h2>Claude Code / MCP</h2>
          <p className="muted">
            The platform's agent tools reach Claude Code over MCP (the{" "}
            <span className="mono">mcp/</span> server in the repo). The skill documents live
            here in the database, and copies are committed to{" "}
            <span className="mono">.claude/skills/</span> — Claude Code only discovers a skill
            as a file on disk, and that is what makes it trigger on the right task by itself.
            There is no sync script and no hook: keeping the copies current is the agent's job,
            and it costs one tool call.
          </p>
          <ol className="skill-claude-steps">
            <li>
              <strong>Point it at this API —</strong> set{" "}
              <span className="mono">KICAD_API_URL</span> (this UI is talking to{" "}
              <span className="mono">{API_URL || window.location.origin}</span>), plus{" "}
              <span className="mono">KICAD_MCP_TOKEN</span> if the API requires a bearer token.
            </li>
            <li>
              <strong>Check currency —</strong> <span className="mono">list_skills</span> returns
              every skill with its version number and no bodies. Each{" "}
              <span className="mono">SKILL.md</span> carries the version it was written from in a
              stamp under its frontmatter, so comparing them is one call.
            </li>
            <li>
              <strong>Refresh a stale copy —</strong>{" "}
              <span className="mono">get_skill(name)</span>, then rewrite the file and update its
              stamp. Agents are expected to edit these files.
            </li>
            <li>
              <strong>Change a convention —</strong>{" "}
              <span className="mono">propose_skill_update</span> files a draft you approve in
              Proposals. Approval is what moves the version number that{" "}
              <span className="mono">list_skills</span> reports; never record a rule only in the
              local file, or the next refresh drops it.
            </li>
          </ol>
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
              ? ` — fetching… ${status.done}/${status.total} (${status.new_versions} new)`
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
          <table className="data data-fixed fx-table">
            <thead>
              <tr>
                <th>currency</th>
                <th className="num">rate_usd</th>
                <th>source</th>
                <th>updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rates.map((r) => (
                <tr key={r.currency}>
                  <td className="mono">{r.currency}</td>
                  <td className="num mono">{r.rate_usd}</td>
                  <td>
                    <span className={`pill ${r.source === "manual" ? "warn" : "neutral"}`}>
                      {r.source}
                    </span>
                  </td>
                  <td className="muted dim" title={r.updated_at}>
                    {r.updated_at ? new Date(r.updated_at).toLocaleDateString() : "—"}
                  </td>
                  <td>
                    <button type="button" className="btn btn-sm" onClick={() => override(r)}>
                      Override
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
