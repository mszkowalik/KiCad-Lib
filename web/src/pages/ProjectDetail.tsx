import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  deleteProject,
  designBoards,
  errorMessage,
  fetchProject,
  getGitCredentials,
  getProject,
  getSnapshots,
  isAbortError,
  updateProject,
  type ProjectInfo,
  type ProjectPatchBody,
  type SnapshotInfo,
} from "../api";
import { BackLink, ErrorBanner, Spinner } from "../components/Ui";
import Field, { FieldGrid } from "../components/Field";
import { useStickyState } from "../useStickyState";
import BomTab from "../components/project/BomTab";
import BoardTab from "../components/project/BoardTab";
import CostsTab from "../components/project/CostsTab";
import StackupTab from "../components/project/StackupTab";
import HistoryTab from "../components/project/HistoryTab";
import NotesTab from "../components/project/NotesTab";
import RunsTab from "../components/project/RunsTab";
import ProcessTab from "../components/project/ProcessTab";
import OrdersTab from "../components/project/OrdersTab";
import DevicesTab from "../components/project/DevicesTab";
import ReviewTab from "../components/project/ReviewTab";
import SchematicTab from "../components/project/SchematicTab";
import OwnershipCard from "../components/project/OwnershipCard";
import TabStrip, { type TabDef } from "../components/TabStrip";
import { useLoad } from "../components/useLoad";
import PageShell, { PageLoading } from "../components/PageShell";

const TABS = ["BOM", "Board", "Schematic", "Stackup", "History", "Review", "Costs", "Process", "Runs", "Orders", "Devices", "Notes", "Settings"] as const;
type Tab = (typeof TABS)[number];

/** The strip, by job. The ids stay stable, so `?tab=` links and the sticky tab
 *  survive, and `Costs` and `Runs` only read differently. */
const TAB_STRIP: TabDef<Tab>[] = [
  { id: "BOM", label: "BOM", group: "Design" },
  { id: "Board", label: "Board" },
  { id: "Schematic", label: "Schematic" },
  { id: "Stackup", label: "Stackup" },
  { id: "Review", label: "Review" },
  { id: "History", label: "History" },
  { id: "Process", label: "Process", group: "Make" },
  { id: "Runs", label: "Batches" },
  { id: "Devices", label: "Devices" },
  { id: "Costs", label: "Cost plan" },
  { id: "Orders", label: "Orders", group: "Sell" },
  { id: "Notes", label: "Notes", group: "Project" },
  { id: "Settings", label: "Settings" },
];

export default function ProjectDetail() {
  const { id } = useParams();
  const projectId = Number(id);

  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [snapshots, setSnapshots] = useState<SnapshotInfo[]>([]);
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  // THE URL WINS, and the sticky value is the fallback for a bare visit — the
  // rule every other tabbed page here follows. It had no URL form at all, so a
  // link from elsewhere could not say which tab it meant: the finished-stock
  // card on Stock → Finished devices links straight at this project's Devices tab
  // with the condition it was counting.
  const [searchParams, setSearchParams] = useSearchParams();
  const [stickyTab, setStickyTab] = useStickyState<Tab>(`project:${projectId}:tab`, "BOM");
  const urlTab = searchParams.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(urlTab ?? "")
    ? (urlTab as Tab)
    : stickyTab;
  // Arriving by link makes that tab the remembered one too, so coming back to
  // the project without a query does not snap to whatever was open last week.
  useEffect(() => {
    if (urlTab && (TABS as readonly string[]).includes(urlTab) && urlTab !== stickyTab) {
      setStickyTab(urlTab as Tab);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlTab]);
  const setTab = (t: Tab) => {
    setStickyTab(t);
    const next = new URLSearchParams(searchParams);
    next.set("tab", t);
    // `state` and `condition` belong to the Devices tab. Carrying them onto
    // another tab would leave a filter in the URL that nothing on screen
    // explains, and put it back the moment the reader returns.
    if (t !== "Devices") {
      next.delete("state");
      next.delete("condition");
    }
    setSearchParams(next, { replace: true });
  };
  const [snapshotId, setSnapshotId] = useStickyState<number | null>(`project:${projectId}:snapshotId`, null);
  const [boardName, setBoardName] = useStickyState<string>(`project:${projectId}:board`, "");
  const [variant, setVariant] = useStickyState<string>(`project:${projectId}:variant`, "");
  const [fetching, setFetching] = useState(false);
  const [fetchNote, setFetchNote] = useState<string | null>(null);

  // Settings tab state
  const [settingsDraft, setSettingsDraft] = useState<{
    name: string; git_url: string; default_branch: string;
    description: string; token: string;
    credId: number | "";
  } | null>(null);
  // Without an answer the picker shows "none", and editing still works.
  const creds = useLoad(getGitCredentials, []).data ?? [];
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
    const boards = designBoards(snapshot);
    if (!boards.some((b) => b.name === boardName)) {
      setBoardName(boards[0]?.name ?? "");
      setVariant("");
      return;
    }
    const b = boards.find((x) => x.name === boardName);
    if (variant && !b?.variants.some((v) => v.name === variant)) setVariant("");
  }, [snapshot, boardName, variant]);

  const boards = designBoards(snapshot);
  const board = boards.find((b) => b.name === boardName) ?? null;

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
      <PageShell>
        <ErrorBanner message={error} />
        <BackLink to="/projects">← All projects</BackLink>
      </PageShell>
    );
  }
  if (!project) return <PageLoading label="Loading project" />;

  return (
    <PageShell>
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
        <Field inline label="Snapshot">
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
        </Field>
        {/* Design boards only. A repository also carries one simulation
            harness per block (CP_sim, TEMP_sim, …); those are projects too,
            but they are the Simulator's to list, not a board to build. */}
        {snapshot && boards.length > 1 ? (
          <Field inline label="Board">
            <select className="text" value={boardName} onChange={(e) => setBoardName(e.target.value)}>
              {boards.map((b) => (
                <option key={b.name} value={b.name}>{b.name}</option>
              ))}
            </select>
          </Field>
        ) : null}
        {board && board.variants.length > 0 ? (
          <Field inline label="Variant">
            <select className="text" value={variant} onChange={(e) => setVariant(e.target.value)}>
              <option value="">default</option>
              {board.variants.map((v) => (
                <option key={v.name} value={v.name} title={v.description}>{v.name}</option>
              ))}
            </select>
          </Field>
        ) : null}
        {snapshot ? (
          <span className="muted">
            {snapshot.commit_message.slice(0, 60)}
            {snapshot.report?.warnings?.length ? ` · ${snapshot.report.warnings.length} warning(s)` : ""}
          </span>
        ) : null}
        {anyBusy ? <Spinner label="ingesting" /> : null}
      </div>

      <TabStrip tabs={TAB_STRIP} value={tab} onChange={setTab} label="Project sections" />

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
      {tab === "Process" ? <ProcessTab project={project} /> : null}
      {tab === "Orders" ? <OrdersTab project={project} /> : null}
      {tab === "Devices" ? <DevicesTab project={project} /> : null}
      {tab === "Notes" ? <NotesTab projectId={project.id} snapshotId={snapshotId} /> : null}

      {tab === "Settings" ? (
        <OwnershipCard
          project={project}
          onMoved={() => getProject(project.id).then(setProject).catch((err) => setSettingsMsg(errorMessage(err)))}
        />
      ) : null}
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
                    description: project.description,
                    token: "",
                    credId: project.git_credential_id ?? "",
                  })
                }
              >
                Edit settings
              </button>
              <dl className="kv">
                <dt>Default branch</dt><dd className="mono">{project.default_branch}</dd>
                <dt>Git account</dt>
                <dd>
                  {project.git_credential ? (
                    <Link className="comp-link" to="/account">{project.git_credential.name}</Link>
                  ) : (
                    <span className="muted">none</span>
                  )}
                </dd>
                <dt>Token</dt>
                <dd>
                  {/* Name the SOURCE, not just "stored". A project carrying
                      both a credential and its own token is legal, and the
                      credential wins — saying only "stored (encrypted)"
                      is exactly how a stale copy hid before. */}
                  {project.token_source === "credential"
                    ? `from the account "${project.git_credential?.name ?? ""}"`
                    : project.token_source === "project"
                      ? "stored on this project (encrypted)"
                      : "none"}
                </dd>
                <dt>Description</dt><dd>{project.description || <span className="muted">—</span>}</dd>
              </dl>
            </div>
          ) : (
            <>
              <FieldGrid>
                <Field label="Name">
                  <input className="text" value={settingsDraft.name}
                    onChange={(e) => setSettingsDraft({ ...settingsDraft, name: e.target.value })} />
                </Field>
                <Field label="Git URL">
                  <input className="text" value={settingsDraft.git_url}
                    onChange={(e) => setSettingsDraft({ ...settingsDraft, git_url: e.target.value })} />
                </Field>
                <Field label="Git account">
                  <select
                    className="text"
                    value={settingsDraft.credId}
                    onChange={(e) =>
                      setSettingsDraft({
                        ...settingsDraft,
                        credId: e.target.value === "" ? "" : Number(e.target.value),
                      })
                    }
                  >
                    <option value="">none — public repo, or the token below</option>
                    {creds.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </Field>
                <Field label={'Access token (blank = keep; "clear" to remove)'}>
                  <input className="text" type="password" autoComplete="new-password"
                    value={settingsDraft.token}
                    onChange={(e) => setSettingsDraft({ ...settingsDraft, token: e.target.value })} />
                </Field>
                <Field label="Default branch">
                  <input className="text" value={settingsDraft.default_branch}
                    onChange={(e) => setSettingsDraft({ ...settingsDraft, default_branch: e.target.value })} />
                </Field>
                <Field label="Description">
                  <input className="text" value={settingsDraft.description}
                    onChange={(e) => setSettingsDraft({ ...settingsDraft, description: e.target.value })} />
                </Field>
              </FieldGrid>
              {settingsMsg ? <div className="banner-ok">{settingsMsg}</div> : null}
              <div className="btn-row">
                <button className="btn btn-primary"
                  onClick={() => {
                    const body: ProjectPatchBody = {
                      name: settingsDraft.name,
                      git_url: settingsDraft.git_url,
                      default_branch: settingsDraft.default_branch,
                      description: settingsDraft.description,
                    };
                    // 0 unassigns; the API leaves it alone when absent.
                    body.git_credential_id =
                      settingsDraft.credId === "" ? 0 : settingsDraft.credId;
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
                  deleteProject(project.id)
                    .then(() => navigate("/projects"))
                    .catch((err) => setError(errorMessage(err)))
                }>
                Delete permanently
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </PageShell>
  );
}
