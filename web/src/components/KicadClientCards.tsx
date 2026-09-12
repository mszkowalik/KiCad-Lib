/** The KiCad and MCP client setup — every box on it carries the SIGNED-IN
 *  user's own token, which is why it lives on the Account page rather than on
 *  Setup.
 *
 *  The PCM repository URL installs a sync plugin with that token already inside
 *  it, and the `.kicad_httplib` download embeds it too, so these links are
 *  personal credentials in URL form: two people looking at this page must see
 *  two different strings. Admin is the deployment's SHARED configuration —
 *  `PUBLIC_BASE_URL` and the rest — and keeps only a pointer here.
 *
 *  `GET /api/kicad/config` already personalises itself from the caller's
 *  session (`personalised`, `httplib_url`, `pcm_repo_url`), so this component
 *  needs no user id and no new endpoint.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  API_URL,
  errorMessage,
  getKicadConfig,
  httplibFileUrl,
  isAbortError,
  syncScriptUrl,
  type KicadConfig,
} from "../api";
import { ErrorBanner } from "./Ui";

export default function KicadClientCards() {
  const [config, setConfig] = useState<KicadConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    <>
      <ErrorBanner message={error ?? ""} />
      <div className="card pad">
        <h2>Effective URLs</h2>
        <p className="muted">
          Derived from the deployment's <code>Public base URL</code> (an administrator sets it
          on <Link className="comp-link" to="/admin">Admin</Link>) — these are what KiCad
          clients use. Change the setting and re-download the .kicad_httplib, which
          embeds them.
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
          and <b>7Sigma Library Sync</b> — a toolbar button in the PCB editor that pulls
          updates on click (changed 3D models transfer as a small compressed delta, not
          the full package) and records them in the Plugin and Content Manager, so
          the PCM is only needed to update the plugin itself.
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
            button in the PCB editor. It marks the library and 3D-model packages as
            current and pinned in the PCM, so PCM's Update is only for the Sync plugin
            itself. Parts already placed on a board or schematic are copies: run Tools
            → Update Footprints / Symbols from Library after a sync.
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
            <span className="mono">propose_skill_update</span> publishes a new version at once
            (no approval step since 2026-08-24) and that is what{" "}
            <span className="mono">list_skills</span> reports from then on. Never record a rule
            only in the local file, or the next refresh drops it. To undo one, open the
            previous version on this page and restore it.
          </li>
        </ol>
      </div>
    </>
  );
}
