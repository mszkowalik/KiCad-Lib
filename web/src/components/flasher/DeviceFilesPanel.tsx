/** Device files: the .be/.json payload the device downloads during
 *  deployment. Versioned separately from firmware — a script change never
 *  needs a firmware rebuild (user decision 2026-07-29). */
import { useCallback, useEffect, useState } from "react";
import {
  createDeviceFileVersion,
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

export default function DeviceFilesPanel({ projectId }: { projectId: number }) {
  const dialog = useDialog();
  const [files, setFiles] = useState<DeviceFileRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null); // expanded file id
  const [editor, setEditor] = useState<{ filename: string; content: string; comment: string } | null>(null);
  const [busy, setBusy] = useState(false);

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

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Device files</h2>
        <button type="button" className="btn btn-sm" onClick={() => openEditor(null)}>
          New file
        </button>
      </div>
      <p className="card-subtitle">
        Berry scripts and driver JSONs the device downloads over HTTP during deployment. Each file
        versions independently; a deployment script pins exact versions.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      {files === null ? (
        <Spinner label="Loading files…" />
      ) : files.length === 0 ? (
        <p className="muted">No device files yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="data data-fixed device-files-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Live</th>
                <th>Versions</th>
                <th>Description</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {files.map((f) => {
                const live = f.versions.find((v) => v.id === f.current_version_id);
                return (
                  <tr key={f.id} className="ledger-row" onClick={() => setOpen(open === f.id ? null : f.id)}>
                    <td className="mono" title={f.filename}>
                      <span className="ledger-caret">{open === f.id ? "▾" : "▸"}</span>
                      {f.filename}
                    </td>
                    <td>{live ? `v${live.version_no} (${fmtBytes(live.size_bytes)})` : "—"}</td>
                    <td className="num">{f.versions.length}</td>
                    <td title={f.description}>{f.description || "—"}</td>
                    <td className="ctr">
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
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {open !== null && files ? (
        <FileVersions
          file={files.find((f) => f.id === open) ?? null}
          onPublish={publish}
          onReject={reject}
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
  file, onPublish, onReject,
}: {
  file: DeviceFileRow | null;
  onPublish: (id: number, label: string) => void;
  onReject: (id: number, label: string) => void;
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
                  {v.status === "draft" ? (
                    <span className="btn-row">
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
                    </span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
