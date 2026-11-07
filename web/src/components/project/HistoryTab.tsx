/** Git history: commits + tags from the local mirror, snapshot status per
 *  commit, ingest-on-demand, and snapshot selection for the other tabs. A row
 *  opens to the files at that commit. */
import { useState } from "react";
import {
  ApiError,
  errorMessage,
  deleteSnapshot,
  getProjectFiles,
  getProjectHistory,
  ingestSnapshot,
  projectFilePath,
  type HistoryCommit,
  type ProjectFileRow,
  type ProjectInfo,
  type SnapshotInfo,
} from "../../api";
import DataTable, { type Column } from "../DataTable";
import { useDialog } from "../Dialog";
import { fmtBytes } from "../flasher/common";
import FoldSection, { StatChip } from "../FoldSection";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { useStickyState } from "../../useStickyState";
import { fileHref } from "../../viewkind";
import { localDate } from "../../format";
import Field from "../Field";
import { useLoad } from "../useLoad";

interface Props {
  project: ProjectInfo;
  snapshots: SnapshotInfo[];
  selectedSnapshotId: number | null;
  onSelectSnapshot: (id: number) => void;
  onIngested: () => void;
}

/** The files at one commit. It mounts when its row opens, so a closed row costs no
 *  request (the FoldSection rule, web/CLAUDE.md). The mirror can lose a commit, or
 *  the whole repository, after the page loaded: the server says which in a sentence,
 *  and that is a state of the project and not a fault. */
function CommitFiles({ projectId, sha }: { projectId: number; sha: string }) {
  const [gone, setGone] = useState<string | null>(null);
  const { data: files, error } = useLoad(
    (signal) =>
      getProjectFiles(projectId, sha, signal).catch((err) => {
        if (!(err instanceof ApiError && (err.status === 404 || err.status === 409))) throw err;
        setGone(err.message);
        return null;
      }),
    [projectId, sha],
    { keep: true },
  );
  if (error) return <ErrorBanner message={error} />;
  if (gone) return <p className="muted">The files of this commit cannot be read: {gone}</p>;
  if (!files) return <Spinner label="Reading the files of this commit" />;
  const columns: Column<ProjectFileRow>[] = [
    { key: "path", label: `File (${files.length.toLocaleString()} at ${sha.slice(0, 10)})`, width: 86, className: "mono", get: (f) => f.path,
      render: (f) => (f.size === null ? <>{f.path}</> : (
        <a href={fileHref(projectFilePath(projectId, sha, f.path), f.path.split("/").pop() ?? f.path)} target="_blank" rel="noreferrer">
          {f.path}
        </a>
      )) },
    { key: "size", label: "Size", width: 14, numeric: true, get: (f) => f.size ?? 0,
      render: (f) => <>{f.size === null ? "submodule" : fmtBytes(f.size)}</> },
  ];
  return <DataTable rows={files} rowKey={(f) => f.path} columns={columns} empty="This commit holds no file." />;
}

export default function HistoryTab({
  project,
  snapshots,
  selectedSnapshotId,
  onSelectSnapshot,
  onIngested,
}: Props) {
  const [ref, setRef] = useStickyState(`project:${project.id}:history:branch`, "");
  const { data: history, error, setError } = useLoad(
    (signal) => getProjectHistory(project.id, ref || undefined, signal),
    [project.id, ref, snapshots.length],
    { keep: true },
  );
  const [ingesting, setIngesting] = useState<string | null>(null);
  const dialog = useDialog();
  const removeSnapshot = async (id: number, sha: string) => {
    const ok = await dialog.confirm(
      `Delete what was read from commit ${sha.slice(0, 10)}, with its renders? The commit stays in git, and "Ingest" reads it again. `
        + "A batch that uses it refuses this.",
      { title: "Delete snapshot", confirmLabel: "Delete", tone: "danger" },
    );
    if (!ok) return;
    try {
      await deleteSnapshot(id);
      onIngested();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not delete the snapshot" });
    }
  };

  const snapBySha = new Map(snapshots.map((s) => [s.sha, s]));
  const snapshotCount = (status: string) =>
    (history?.commits ?? []).filter((c) => snapBySha.get(c.sha)?.status === status).length;

  const ingest = (refOrSha: string) => {
    setIngesting(refOrSha);
    ingestSnapshot(project.id, refOrSha)
      .then(() => {
        setIngesting(null);
        onIngested();
      })
      .catch((err) => {
        setError(errorMessage(err));
        setIngesting(null);
      });
  };

  const columns: Column<HistoryCommit>[] = [
    { key: "sha", label: "Commit", width: 10, className: "mono", get: (c) => c.sha.slice(0, 10) },
    { key: "message", label: "Message", width: 29, get: (c) => c.message },
    { key: "author", label: "Author", width: 11, className: "muted", get: (c) => c.author },
    { key: "date", label: "Date", width: 9, className: "muted", get: (c) => c.date,
      render: (c) => localDate(c.date) },
    { key: "refs", label: "Refs", width: 12, className: "mono", get: (c) => c.refs.join(", ") },
    { key: "snapshot", label: "Snapshot", width: 10, get: (c) => snapBySha.get(c.sha)?.status ?? "",
      render: (c) => {
        const snap = snapBySha.get(c.sha);
        return snap ? <StatusPill status={snap.status} /> : <span className="muted">—</span>;
      } },
    { key: "act", label: "", width: 19, interactive: false, get: () => "",
      render: (c) => {
        const snap = snapBySha.get(c.sha);
        const selected = !!snap && snap.id === selectedSnapshotId;
        if (snap && snap.status === "ready") {
          return (
            <>
              <button className="btn btn-sm" disabled={selected}
                onClick={(e) => { e.stopPropagation(); onSelectSnapshot(snap.id); }}>
                {selected ? "Viewing" : "View"}
              </button>{" "}
              <button className="btn btn-sm" disabled={selected}
                title="Delete what was read from this commit. The commit stays in git and can be read again."
                onClick={(e) => { e.stopPropagation(); void removeSnapshot(snap.id, c.sha); }}>
                Delete…
              </button>
            </>
          );
        }
        if (snap && (snap.status === "ingesting" || snap.status === "pending")) return <Spinner />;
        return (
          <button className="btn btn-sm" disabled={ingesting !== null}
            onClick={(e) => { e.stopPropagation(); ingest(c.sha); }}>
            {ingesting === c.sha ? "Starting…" : snap ? "Retry" : "Ingest"}
          </button>
        );
      } },
  ];

  if (!project.has_mirror) {
    return (
      <p className="muted">
        Repository not fetched yet — use the Fetch button in the header first.
      </p>
    );
  }

  return (
    <div>
      {error ? <ErrorBanner message={error} /> : null}
      {history === null && !error ? <Spinner label="Reading git history" /> : null}
      {history ? (
        <>
          <div className="toolbar">
            <Field inline label="Branch">
              <select className="text" value={ref} onChange={(e) => setRef(e.target.value)}>
                <option value="">{history.branch} (default)</option>
                {history.branches
                  .filter((b) => b.name !== history.branch)
                  .map((b) => (
                    <option key={b.name} value={b.name}>
                      {b.name}
                    </option>
                  ))}
              </select>
            </Field>
            {history.tags.length > 0 ? (
              <span className="muted">
                tags: {history.tags.map((t) => t.name).join(", ")}
              </span>
            ) : (
              <span className="muted">no tags yet</span>
            )}
          </div>
          <FoldSection
            title="Commits"
            count={history.commits.length}
            foldKey={`project:${project.id}:commits`}
            chips={
              <>
                {snapshotCount("failed") ? <StatChip n={snapshotCount("failed")} tone="err">failed</StatChip> : null}
                {snapshotCount("ingesting") + snapshotCount("pending") ? (
                  <StatChip n={snapshotCount("ingesting") + snapshotCount("pending")} tone="acc">reading</StatChip>
                ) : null}
                <StatChip n={snapshotCount("ready")} tone="ok">ready</StatChip>
                <StatChip n={history.commits.filter((c) => !snapBySha.has(c.sha)).length}>not read</StatChip>
              </>
            }
          >
          <p className="muted dim">Open a commit to list its files.</p>
          <div className="table-wrap">
            <DataTable
              rows={history.commits}
              rowKey={(c) => c.sha}
              columns={columns}
              rowClass={(c) => (snapBySha.get(c.sha)?.id === selectedSnapshotId ? "row-selected" : "")}
              expand={(c) => <CommitFiles projectId={project.id} sha={c.sha} />}
              empty="No commits on this branch."
            />
          </div>
          </FoldSection>
        </>
      ) : null}
    </div>
  );
}
