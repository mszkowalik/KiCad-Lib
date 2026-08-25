import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createProject,
  errorMessage,
  getProjects,
  isAbortError,
  type ProjectInfo,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

export default function Projects() {
  const navigate = useNavigate();
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

  const cols: Column<ProjectInfo>[] = [
    {
      key: "name",
      label: "Project",
      width: 18,
      get: (p) => p.name,
      render: (p) => (
        <Link className="comp-link" to={`/projects/${p.id}`}>
          {p.name}
        </Link>
      ),
    },
    { key: "git_url", label: "Repository", width: 26, className: "mono", get: (p) => p.git_url },
    {
      key: "snapshot",
      label: "Latest snapshot",
      width: 18,
      get: (p) =>
        p.latest_snapshot
          ? `${p.latest_snapshot.ref_name} ${p.latest_snapshot.status}`
          : p.has_mirror
            ? "not ingested"
            : "not fetched",
      render: (p) =>
        p.latest_snapshot ? (
          <>
            <span className="mono">{p.latest_snapshot.ref_name}</span>{" "}
            <StatusPill status={p.latest_snapshot.status} />
          </>
        ) : (
          <span className="muted">{p.has_mirror ? "not ingested" : "not fetched"}</span>
        ),
    },
    {
      key: "boards",
      label: "Boards",
      width: 16,
      get: (p) =>
        p.latest_snapshot ? p.latest_snapshot.boards.map((b) => b.name).join(", ") || "—" : "—",
    },
    { key: "runs", label: "Batches", width: 7, numeric: true, get: (p) => p.run_count },
    { key: "currency", label: "Currency", width: 7, get: (p) => p.effective_currency },
    {
      key: "created",
      label: "Created",
      width: 8,
      className: "muted",
      get: (p) => p.created_at,
      render: (p) => <>{fmtDate(p.created_at)}</>,
    },
  ];

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
              BOMs priced at any volume, board/schematic previews, production batches.
            </p>
          </div>
        ) : null}

        {list !== null && list.length > 0 ? (
          <div className="card table-wrap">
            <DataTable
              columns={cols}
              rows={list}
              rowKey={(p) => p.id}
              persistKey="projects"
              rowClass={() => "ledger-row"}
              onRowClick={(p) => navigate(`/projects/${p.id}`)}
              empty="No projects yet."
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
