import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  createProject,
  errorMessage,
  getProjects,
  isAbortError,
  type ProjectInfo,
} from "../api";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

export default function Projects() {
  const [list, setList] = useState<ProjectInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("");
  const [gitUrl, setGitUrl] = useState("");
  const [token, setToken] = useState("");
  const [branch, setBranch] = useState("main");
  const [currency, setCurrency] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const load = (signal?: AbortSignal) => {
    getProjects(signal)
      .then((rows) => {
        setList(rows);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  };

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, []);

  const submit = () => {
    setCreating(true);
    setCreateError(null);
    createProject({
      name: name.trim(),
      git_url: gitUrl.trim(),
      git_token: token || null,
      default_branch: branch.trim() || "main",
      display_currency: currency.trim() || null,
    })
      .then(() => {
        setShowNew(false);
        setName("");
        setGitUrl("");
        setToken("");
        setCreating(false);
        load();
      })
      .catch((err) => {
        setCreateError(errorMessage(err));
        setCreating(false);
      });
  };

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Projects</h1>
          <span className="toolbar-total">
            {list ? `${list.length} tracked` : ""}
          </span>
          <button className="btn btn-primary" onClick={() => setShowNew((v) => !v)}>
            {showNew ? "Cancel" : "New project"}
          </button>
        </div>

        {error ? <ErrorBanner message={error} /> : null}

        {showNew ? (
          <div className="card pad edit-card">
            <div className="card-title">Track a KiCad project from git</div>
            <div className="edit-grid">
              <label>
                Name
                <input className="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="My Board" />
              </label>
              <label>
                Git URL
                <input className="text" value={gitUrl} onChange={(e) => setGitUrl(e.target.value)} placeholder="https://github.com/me/my-board.git" />
              </label>
              <label>
                Access token <span className="muted">(optional, stored encrypted, write-only)</span>
                <input className="text" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="PAT / project token" />
              </label>
              <label>
                Default branch
                <input className="text" value={branch} onChange={(e) => setBranch(e.target.value)} />
              </label>
              <label>
                Display currency <span className="muted">(blank = USD)</span>
                <input className="text" value={currency} onChange={(e) => setCurrency(e.target.value)} placeholder="PLN" />
              </label>
            </div>
            {createError ? <ErrorBanner message={createError} /> : null}
            <div className="btn-row">
              <button
                className="btn btn-primary"
                disabled={creating || !name.trim() || !gitUrl.trim()}
                onClick={submit}
              >
                {creating ? "Creating…" : "Create project"}
              </button>
              <span className="muted">
                After creating, use Fetch to clone the repo and ingest tags + head.
              </span>
            </div>
          </div>
        ) : null}

        {list === null && !error ? <Spinner label="Loading projects" /> : null}

        {list !== null && list.length === 0 && !showNew ? (
          <div className="card pad">
            <p className="muted">
              No projects yet. Track your KiCad designs from their git repositories:
              BOMs priced at any volume, board/schematic previews, production runs.
            </p>
          </div>
        ) : null}

        {list !== null && list.length > 0 ? (
          <div className="card table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Repository</th>
                  <th>Latest snapshot</th>
                  <th>Boards</th>
                  <th className="num">Runs</th>
                  <th>Currency</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {list.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link className="comp-link" to={`/projects/${p.id}`}>
                        {p.name}
                      </Link>
                    </td>
                    <td className="mono cell-desc">{p.git_url}</td>
                    <td>
                      {p.latest_snapshot ? (
                        <>
                          <span className="mono">{p.latest_snapshot.ref_name}</span>{" "}
                          <StatusPill status={p.latest_snapshot.status} />
                        </>
                      ) : (
                        <span className="muted">{p.has_mirror ? "not ingested" : "not fetched"}</span>
                      )}
                    </td>
                    <td>
                      {p.latest_snapshot
                        ? p.latest_snapshot.boards.map((b) => b.name).join(", ") || "—"
                        : "—"}
                    </td>
                    <td className="num">{p.run_count}</td>
                    <td>{p.effective_currency}</td>
                    <td className="muted">{fmtDate(p.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </div>
  );
}
