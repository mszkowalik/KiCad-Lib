/** Device files: the .be/.json payload the device downloads during
 *  deployment. Versioned separately from firmware — a script change never
 *  needs a firmware rebuild (user decision 2026-07-29). */
import { useCallback, useEffect, useState } from "react";
import {
  createDeviceFileVersion,
  deleteDeviceFileVersion,
  errorMessage,
  getDeviceFileVersion,
  isAbortError,
  listDeviceFiles,
  publishDeviceFileVersion,
  rejectDeviceFileVersion,
  type DeviceFileRow,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { fmtBytes, fmtWhen, shortSha } from "./common";
import DataTable, { type Column } from "../DataTable";

export default function DeviceFilesPanel({ projectId }: { projectId: number }) {
  const dialog = useDialog();
  const [files, setFiles] = useState<DeviceFileRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null); // expanded file id
  const [editor, setEditor] = useState<{ filename: string; content: string; comment: string } | null>(null);
  const [busy, setBusy] = useState(false);
  // This panel has its own tab now, so it opens expanded; the toggle stays
  // for a quick collapse when a project has many files.
  const [expanded, setExpanded] = useState(true);

  const reload = useCallback(() => {
    const ac = new AbortController();
    listDeviceFiles(projectId, ac.signal)
      .then(setFiles)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [projectId]);

  useEffect(() => {
    setFiles(null);
    return reload();
  }, [reload]);

  const openEditor = async (file: DeviceFileRow | null) => {
    if (!file) {
      const filename = await dialog.prompt("Filename on the device (e.g. autoexec.be):", {
        title: "New device file",
      });
      if (!filename) return;
      setEditor({ filename, content: "", comment: "" });
      return;
    }
    // Prefill from the newest version (draft or published).
    const latest = file.versions[file.versions.length - 1];
    let content = "";
    if (latest) {
      try {
        content = (await getDeviceFileVersion(latest.id)).content;
      } catch (err) {
        setError(errorMessage(err));
        return;
      }
    }
    setEditor({ filename: file.filename, content, comment: "" });
  };

  const saveDraft = async () => {
    if (!editor) return;
    setBusy(true);
    setError(null);
    try {
      await createDeviceFileVersion(projectId, {
        filename: editor.filename,
        content: editor.content,
        comment: editor.comment,
      });
      setEditor(null);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const publish = async (versionId: number, label: string) => {
    if (!(await dialog.confirm(`Publish ${label}? Deployment scripts can then pin it.`, {
      title: "Publish file version", tone: "ok", confirmLabel: "Publish",
    }))) return;
    try {
      await publishDeviceFileVersion(versionId);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const remove = async (versionId: number, label: string) => {
    if (!(await dialog.confirm(
      `Delete ${label}? Refused while a bundle or deployment version pins it.`,
      { title: "Delete file version", tone: "danger", confirmLabel: "Delete" },
    ))) return;
    try {
      await deleteDeviceFileVersion(versionId);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const reject = async (versionId: number, label: string) => {
    if (!(await dialog.confirm(`Reject ${label}?`, {
      title: "Reject draft", tone: "danger", confirmLabel: "Reject",
    }))) return;
    try {
      await rejectDeviceFileVersion(versionId);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const liveOf = (f: DeviceFileRow) => f.versions.find((v) => v.id === f.current_version_id);

  const cols: Column<DeviceFileRow>[] = [
    {
      key: "filename",
      label: "File",
      width: 30,
      className: "mono",
      get: (f) => f.filename,
      render: (f) => (
        <>
          <span className="ledger-caret">{open === f.id ? "▾" : "▸"}</span>
          {f.filename}
        </>
      ),
    },
    {
      key: "live",
      label: "Live",
      width: 18,
      get: (f) => {
        const live = liveOf(f);
        return live ? `v${live.version_no} (${fmtBytes(live.size_bytes)})` : "—";
      },
    },
    { key: "versions", label: "Versions", width: 10, numeric: true, get: (f) => f.versions.length },
    { key: "description", label: "Description", width: 28, get: (f) => f.description || "—" },
    {
      key: "actions",
      label: "",
      width: 14,
      interactive: false,
      className: "ctr",
      get: () => "",
      render: (f) => (
        <button
          type="button"
          className="btn btn-sm"
          onClick={(e) => {
            e.stopPropagation();
            void openEditor(f);
          }}
        >
          New version
        </button>
      ),
    },
  ];

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Berryware files — the raw pool</h2>
        <span className="muted">{files ? `${files.length} files` : ""}</span>
        <button type="button" className="btn btn-sm" onClick={() => setExpanded((x) => !x)}>
          {expanded ? "Hide" : "Show"}
        </button>
        {expanded ? (
          <button type="button" className="btn btn-sm" onClick={() => openEditor(null)}>
            New file
          </button>
        ) : null}
      </div>
      <p className="card-subtitle">
        Every file, every version. Day-to-day work happens in bundles above; open this for a
        surgical edit to one file.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      {!expanded ? null : files === null ? (
        <Spinner label="Loading files…" />
      ) : files.length === 0 ? (
        <p className="muted">No device files yet.</p>
      ) : (
        <div className="table-wrap">
          <DataTable
            columns={cols}
            rows={files}
            rowKey={(f) => f.id}
            persistKey="device-files"
            rowClass={() => "ledger-row"}
            openKey={open}
            onOpenChange={(k) => setOpen(k === null ? null : Number(k))}
            empty="No device files yet."
          />
        </div>
      )}
      {expanded && open !== null && files ? (
        <FileVersions
          file={files.find((f) => f.id === open) ?? null}
          onPublish={publish}
          onReject={reject}
          onDelete={remove}
        />
      ) : null}

      {editor ? (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setEditor(null)}>
          <div className="card pad modal-card modal-card-wide" onMouseDown={(e) => e.stopPropagation()}>
            <h2 className="card-title">
              {editor.filename} — new draft version
            </h2>
            <textarea
              className="note-textarea mono file-editor"
              value={editor.content}
              spellCheck={false}
              onChange={(e) => setEditor({ ...editor, content: e.target.value })}
            />
            <div className="btn-row modal-actions">
              <input
                className="row-input"
                placeholder="comment (what changed)"
                value={editor.comment}
                onChange={(e) => setEditor({ ...editor, comment: e.target.value })}
              />
              <button type="button" className="btn" onClick={() => setEditor(null)} disabled={busy}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={saveDraft} disabled={busy}>
                {busy ? "Saving…" : "Save draft"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function FileVersions({
  file, onPublish, onReject, onDelete,
}: {
  file: DeviceFileRow | null;
  onPublish: (id: number, label: string) => void;
  onReject: (id: number, label: string) => void;
  onDelete: (id: number, label: string) => void;
}) {
  if (!file) return null;
  return (
    <div className="meta-card">
      <strong className="mono">{file.filename}</strong>
      <div className="table-wrap">
        <table className="data data-fixed file-versions-table">
          <thead>
            <tr>
              <th>v</th>
              <th>Status</th>
              <th className="num">Size</th>
              <th>sha256</th>
              <th>Comment</th>
              <th>Created</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {[...file.versions].reverse().map((v) => (
              <tr key={v.id}>
                <td className="mono">
                  v{v.version_no}
                  {file.current_version_id === v.id ? " ●" : ""}
                </td>
                <td><StatusPill status={v.status} /></td>
                <td className="num">{fmtBytes(v.size_bytes)}</td>
                <td className="mono dim" title={v.sha256}>{shortSha(v.sha256)}</td>
                <td title={v.comment}>{v.comment || "—"}</td>
                <td className="muted">{fmtWhen(v.created_at)}</td>
                <td className="ctr">
                  <span className="btn-row">
                    {v.status === "draft" ? (
                      <>
                        <button
                          type="button"
                          className="btn btn-ok btn-sm"
                          onClick={() => onPublish(v.id, `${file.filename} v${v.version_no}`)}
                        >
                          Publish
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => onReject(v.id, `${file.filename} v${v.version_no}`)}
                        >
                          Reject
                        </button>
                      </>
                    ) : null}
                    <button
                      type="button"
                      className="btn btn-sm row-del"
                      title="delete — refused while pinned"
                      onClick={() => onDelete(v.id, `${file.filename} v${v.version_no}`)}
                    >
                      ×
                    </button>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
