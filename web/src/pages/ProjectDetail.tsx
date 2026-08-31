import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  deleteProject,
  errorMessage,
  fetchProject,
  getProject,
  getSnapshots,
  isAbortError,
  updateProject,
  type ProjectInfo,
  type SnapshotInfo,
} from "../api";
import { BackLink, ErrorBanner, Spinner } from "../components/Ui";
import { useStickyState } from "../useStickyState";
import BomTab from "../components/project/BomTab";
import BoardTab from "../components/project/BoardTab";
import CostsTab from "../components/project/CostsTab";
import StackupTab from "../components/project/StackupTab";
import HistoryTab from "../components/project/HistoryTab";
import NotesTab from "../components/project/NotesTab";
import RunsTab from "../components/project/RunsTab";
import ReviewTab from "../components/project/ReviewTab";
import SchematicTab from "../components/project/SchematicTab";

const TABS = ["BOM", "Board", "Schematic", "Stackup", "History", "Review", "Costs", "Runs", "Notes", "Settings"] as const;
type Tab = (typeof TABS)[number];

/** Visible labels; the keys stay stable so sticky tab state survives. */
const TAB_LABEL: Partial<Record<Tab, string>> = { Costs: "Cost plan", Runs: "Batches" };

export default function ProjectDetail() {
  const { id } = useParams();
  const projectId = Number(id);

  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [snapshots, setSnapshots] = useState<SnapshotInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Remembered per project across navigation (see useStickyState).
  const [tab, setTab] = useStickyState<Tab>(`project:${projectId}:tab`, "BOM");
  const [snapshotId, setSnapshotId] = useStickyState<number | null>(`project:${projectId}:snapshotId`, null);
  const [boardName, setBoardName] = useStickyState<string>(`project:${projectId}:board`, "");
  const [variant, setVariant] = useStickyState<string>(`project:${projectId}:variant`, "");
  const [fetching, setFetching] = useState(false);
  const [fetchNote, setFetchNote] = useState<string | null>(null);

  // Settings tab state
  const [settingsDraft, setSettingsDraft] = useState<{
    name: string; git_url: string; default_branch: string;
    display_currency: string; description: string; token: string;
  } | null>(null);
  const [settingsMsg, setSettingsMsg] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState("");

  const loadProject = useCallback((signal?: AbortSignal) => {
    getProject(projectId, signal)
      .then((p) => {
        setProject(p);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  }, [projectId]);

  const loadSnapshots = useCallback((signal?: AbortSignal) => {
    getSnapshots(projectId, signal)
      .then((rows) => {
        setSnapshots(rows);
        setSnapshotId((prev) => {
          if (prev !== null && rows.some((s) => s.id === prev && s.status === "ready")) return prev;
          const ready = rows.find((s) => s.status === "ready");
          return ready ? ready.id : null;
        });
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  }, [projectId]);

  useEffect(() => {
    const ctrl = new AbortController();
    loadProject(ctrl.signal);
    loadSnapshots(ctrl.signal);
    return () => ctrl.abort();
  }, [loadProject, loadSnapshots]);

  // Poll while anything is ingesting.
  const anyBusy = snapshots.some((s) => s.status === "ingesting" || s.status === "pending");
  useEffect(() => {
    if (!anyBusy) return;
    const t = setInterval(() => loadSnapshots(), 3000);
    return () => clearInterval(t);
  }, [anyBusy, loadSnapshots]);

  const snapshot = useMemo(
    () => snapshots.find((s) => s.id === snapshotId) ?? null,
    [snapshots, snapshotId],
  );

  // Keep board/variant valid for the selected snapshot.
  useEffect(() => {
    if (!snapshot) return;
    const boards = snapshot.boards ?? [];
    if (!boards.some((b) => b.name === boardName)) {
      setBoardName(boards[0]?.name ?? "");
      setVariant("");
      return;
    }
    const b = boards.find((x) => x.name === boardName);
    if (variant && !b?.variants.some((v) => v.name === variant)) setVariant("");
  }, [snapshot, boardName, variant]);

  const board = snapshot?.boards.find((b) => b.name === boardName) ?? null;

  const doFetch = () => {
    setFetching(true);
    setFetchNote(null);
    fetchProject(projectId)
      .then((r) => {
        setFetching(false);
        setFetchNote(
          r.queued.length > 0
            ? `Fetched. Ingesting: ${r.queued.map((q) => q.ref).join(", ")}`
            : "Fetched — nothing new to ingest.",
        );
        loadProject();
        loadSnapshots();
      })
      .catch((err) => {
        setFetching(false);
        setFetchNote(null);
        setError(errorMessage(err));
      });
  };

  if (error && !project) {
    return (
      <div className="main-solo">
        <div className="page">
          <ErrorBanner message={error} />
          <BackLink to="/projects">← All projects</BackLink>
        </div>
      </div>
    );
  }
  if (!project) {
    return (
      <div className="main-solo">
        <div className="page"><Spinner label="Loading project" /></div>
      </div>
    );
  }

  return (
    <div className="main-solo">
      <div className="page">
        <div className="detail-top">
          <div>
            <BackLink to="/projects">← All projects</BackLink>
            <h1>{project.name}</h1>
            <div className="muted mono">{project.git_url}</div>
          </div>
          <div className="btn-row">
            <button className="btn btn-primary" disabled={fetching} onClick={doFetch}>
              {fetching ? "Fetching…" : "Fetch"}
            </button>
          </div>
        </div>

        {fetchNote ? <div className="banner-ok">{fetchNote}</div> : null}
        {error ? <ErrorBanner message={error} /> : null}

        <div className="toolbar">
          <label className="proj-inline-field">
            Snapshot
            <select
              className="text"
              value={snapshotId ?? ""}
              onChange={(e) => setSnapshotId(e.target.value === "" ? null : Number(e.target.value))}
            >
              {snapshots.length === 0 ? <option value="">none ingested</option> : null}
              {snapshots.map((s) => (
                <option key={s.id} value={s.id} disabled={s.status !== "ready"}>
                  {s.is_tag ? "🏷 " : ""}{s.ref_name} ({s.sha.slice(0, 8)}) {s.status !== "ready" ? `— ${s.status}` : ""}
                </option>
              ))}
            </select>
          </label>
          {snapshot && snapshot.boards.length > 1 ? (
            <label className="proj-inline-field">
              Board
              <select className="text" value={boardName} onChange={(e) => setBoardName(e.target.value)}>
                {snapshot.boards.map((b) => (
                  <option key={b.name} value={b.name}>{b.name}</option>
                ))}
              </select>
            </label>
          ) : null}
          {board && board.variants.length > 0 ? (
            <label className="proj-inline-field">
              Variant
              <select className="text" value={variant} onChange={(e) => setVariant(e.target.value)}>
                <option value="">default</option>
                {board.variants.map((v) => (
                  <option key={v.name} value={v.name} title={v.description}>{v.name}</option>
                ))}
              </select>
            </label>
          ) : null}
          {snapshot ? (
            <span className="muted">
              {snapshot.commit_message.slice(0, 60)}
              {snapshot.report?.warnings?.length ? ` · ${snapshot.report.warnings.length} warning(s)` : ""}
            </span>
          ) : null}
          {anyBusy ? <Spinner label="ingesting" /> : null}
        </div>

        <div className="seg proj-tabs" role="tablist" aria-label="Project sections">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              className={tab === t ? "on" : ""}
              onClick={() => setTab(t)}
            >
              {TAB_LABEL[t] ?? t}
            </button>
          ))}
        </div>

        {tab === "BOM" ? (
          snapshot && board ? (
            <BomTab project={project} snapshot={snapshot} snapshots={snapshots} board={board.name} variant={variant} />
          ) : (
            <p className="muted">No ready snapshot — fetch the repo, then ingest a commit in History.</p>
          )
        ) : null}
        {tab === "Board" ? (
          snapshot && board ? (
            <BoardTab snapshot={snapshot} board={board} />
          ) : (
            <p className="muted">No ready snapshot.</p>
          )
        ) : null}
        {tab === "Schematic" ? (
          snapshot && board ? (
            <SchematicTab snapshot={snapshot} board={board} variant={variant} />
          ) : (
            <p className="muted">No ready snapshot.</p>
          )
        ) : null}
        {tab === "History" ? (
          <HistoryTab
            project={project}
            snapshots={snapshots}
            selectedSnapshotId={snapshotId}
            onSelectSnapshot={(sid) => setSnapshotId(sid)}
            onIngested={() => loadSnapshots()}
          />
        ) : null}
        {tab === "Stackup" ? (
          <StackupTab projectId={project.id} snapshot={snapshot} board={board?.name ?? ""} />
        ) : null}
        {tab === "Review" ? <ReviewTab project={project} snapshot={snapshot} /> : null}
        {tab === "Costs" ? <CostsTab projectId={project.id} snapshot={snapshot} /> : null}
        {tab === "Runs" ? (
          <RunsTab project={project} snapshots={snapshots} snapshot={snapshot} board={boardName} variant={variant} />
        ) : null}
        {tab === "Notes" ? <NotesTab projectId={project.id} snapshotId={snapshotId} /> : null}

        {tab === "Settings" ? (
          <div className="card pad edit-card">
            <div className="card-title">Project settings</div>
            {settingsDraft === null ? (
              <div className="btn-row">
                <button
                  className="btn"
                  onClick={() =>
                    setSettingsDraft({
                      name: project.name,
                      git_url: project.git_url,
                      default_branch: project.default_branch,
                      display_currency: project.display_currency ?? "",
                      description: project.description,
                      token: "",
                    })
                  }
                >
                  Edit settings
                </button>
                <dl className="kv">
                  <dt>Default branch</dt><dd className="mono">{project.default_branch}</dd>
                  <dt>Display currency</dt><dd>{project.effective_currency}</dd>
                  <dt>Token</dt><dd>{project.has_token ? "stored (encrypted)" : "none"}</dd>
                  <dt>Description</dt><dd>{project.description || <span className="muted">—</span>}</dd>
                </dl>
              </div>
            ) : (
              <>
                <div className="edit-grid">
                  <label>
                    Name
                    <input className="text" value={settingsDraft.name}
                      onChange={(e) => setSettingsDraft({ ...settingsDraft, name: e.target.value })} />
                  </label>
                  <label>
                    Git URL
                    <input className="text" value={settingsDraft.git_url}
                      onChange={(e) => setSettingsDraft({ ...settingsDraft, git_url: e.target.value })} />
                  </label>
                  <label>
                    Access token <span className="muted">(blank = keep; "clear" to remove)</span>
                    <input className="text" type="password" value={settingsDraft.token}
                      onChange={(e) => setSettingsDraft({ ...settingsDraft, token: e.target.value })} />
                  </label>
                  <label>
                    Default branch
                    <input className="text" value={settingsDraft.default_branch}
                      onChange={(e) => setSettingsDraft({ ...settingsDraft, default_branch: e.target.value })} />
                  </label>
                  <label>
                    Display currency
                    <input className="text" value={settingsDraft.display_currency} maxLength={3}
                      onChange={(e) => setSettingsDraft({ ...settingsDraft, display_currency: e.target.value.toUpperCase() })} />
                  </label>
                  <label>
                    Description
                    <input className="text" value={settingsDraft.description}
                      onChange={(e) => setSettingsDraft({ ...settingsDraft, description: e.target.value })} />
                  </label>
                </div>
                {settingsMsg ? <div className="banner-ok">{settingsMsg}</div> : null}
                <div className="btn-row">
                  <button className="btn btn-primary"
                    onClick={() => {
                      const body: Record<string, string> = {
                        name: settingsDraft.name,
                        git_url: settingsDraft.git_url,
                        default_branch: settingsDraft.default_branch,
                        display_currency: settingsDraft.display_currency,
                        description: settingsDraft.description,
                      };
                      if (settingsDraft.token === "clear") body.git_token = "";
                      else if (settingsDraft.token) body.git_token = settingsDraft.token;
                      updateProject(project.id, body)
                        .then((p) => {
                          setProject(p);
                          setSettingsDraft(null);
                          setSettingsMsg("Saved.");
                        })
                        .catch((err) => setSettingsMsg(errorMessage(err)));
                    }}>
                    Save
                  </button>
                  <button className="btn" onClick={() => setSettingsDraft(null)}>Cancel</button>
                </div>
              </>
            )}

            <div className="danger-card">
              <div className="card-title">Delete project</div>
              <p className="muted">
                Removes the project, snapshots, runs, notes, its render cache and the git
                mirror. The remote repository is untouched. Type the project name to confirm.
              </p>
              <div className="confirm-row">
                <input className="text confirm-word" value={confirmDelete}
                  placeholder={project.name}
                  onChange={(e) => setConfirmDelete(e.target.value)} />
                <button className="btn btn-danger" disabled={confirmDelete !== project.name}
                  onClick={() =>
                    deleteProject(project.id).then(() => {
                      window.location.href = "/projects";
                    })
                  }>
                  Delete permanently
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
