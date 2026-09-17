/** Device files: the pool a deployment version pins one file at a time. NOT
 *  berryware only — the .be/.json payload the device downloads shares the pool
 *  with the .lbrn2 artwork a `mark` version engraves, because both are
 *  project-scoped versioned content a version pins through `deployment_files`
 *  (decision 0026). Versioned separately from firmware — a script change never
 *  needs a firmware rebuild (user decision 2026-07-29).
 *
 *  **Nothing here is typed in. A file is UPLOADED** (user decision 2026-09-17):
 *  the paste editor is gone, because the source of every one of these files is
 *  a file on disk, and an upload publishes. Berryware is updated by importing
 *  the folder on the Bundles tab, so its rows carry no upload control at all;
 *  artwork gets one per row, and the toolbar's Upload takes anything, with the
 *  kind decided by the extension.
 *
 *  **Delete takes the NEWEST version**, and the server refuses while a
 *  deployment version or a bundle pins it — the "Used" column says so before
 *  the click. More versions mean more clicks, on purpose: a file a device was
 *  given is history, and history goes one row at a time.
 */
import { useCallback, useEffect, useState } from "react";
import {
  deleteDeviceFileVersion,
  deviceFilePath,
  errorMessage,
  getDeviceFileVersion,
  importDeviceFiles,
  isAbortError,
  listDeviceFiles,
  publishDeviceFileVersion,
  rejectDeviceFileVersion,
  type DeviceFileRow,
  type DeviceFileVersionRow,
} from "../../api";
import { useDialog } from "../Dialog";
import FilePick from "../FilePick";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { fmtBytes, fmtWhen, lbrnThumbnail, shortSha } from "./common";
import DataTable, { type Column } from "../DataTable";
import { useModal } from "../modal";

const KIND_TONE: Record<string, string> = { artwork: "info", berryware: "neutral" };

/** The eye on every row: a small rectangular button, never the content itself
 *  squeezed into a cell — the preview is a popup with room for the file. */
function EyeButton({ onClick, title }: { onClick: () => void; title: string }) {
  return (
    <button
      type="button"
      className="btn btn-sm btn-eye"
      title={title}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
           strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    </button>
  );
}

function usedText(v: DeviceFileVersionRow): string {
  const u = v.used_by;
  if (!u || (!u.versions && !u.bundles)) return "not used";
  const bits = [];
  if (u.versions) bits.push(`${u.versions} version${u.versions === 1 ? "" : "s"}`);
  if (u.bundles) bits.push(`${u.bundles} bundle${u.bundles === 1 ? "" : "s"}`);
  return bits.join(" · ");
}

export default function DeviceFilesPanel({ projectId }: { projectId: number }) {
  const dialog = useDialog();
  const [files, setFiles] = useState<DeviceFileRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null); // expanded file id
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ file: DeviceFileRow; version: DeviceFileVersionRow } | null>(null);
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

  /** One upload path for both buttons: a new file under its own name, or a
   *  new version of an existing row under the row's name. Publishes. */
  const upload = async (picked: File[], replace?: DeviceFileRow) => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const res = await importDeviceFiles(projectId, picked, {
        make_bundle: false, replace_file_id: replace?.id,
      });
      const lines = res.files.map((f) =>
        f.state === "unchanged"
          ? `${f.filename}: identical to v${f.version_no} — reused, nothing added`
          : `${f.filename}: v${f.version_no} published (${f.kind}, ${fmtBytes(f.size_bytes)})`);
      setNote(lines.join(" · "));
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const publish = async (versionId: number, label: string) => {
    if (!(await dialog.confirm(`Publish ${label}? Deployment versions can then pin it.`, {
      title: "Publish file version", tone: "ok", confirmLabel: "Publish",
    }))) return;
    try {
      await publishDeviceFileVersion(versionId);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const remove = async (v: DeviceFileVersionRow, file: DeviceFileRow) => {
    const label = `${file.filename} v${v.version_no}`;
    const others = file.versions.length - 1;
    const used = usedText(v);
    if (!(await dialog.confirm(
      `Delete ${label}?`
      + (used !== "not used" ? ` It is pinned by ${used} — the platform will refuse.` : "")
      + (others > 0
         ? ` ${others} older version${others === 1 ? "" : "s"} of the file stay${others === 1 ? "s" : ""}.`
         : " It is the last version, so the file leaves the pool."),
      { title: "Delete file version", tone: "danger", confirmLabel: "Delete" },
    ))) return;
    try {
      await deleteDeviceFileVersion(v.id);
      setNote(`Deleted ${label}.`);
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
  const newestOf = (f: DeviceFileRow) => f.versions[f.versions.length - 1];

  const cols: Column<DeviceFileRow>[] = [
    {
      key: "filename",
      label: "File",
      width: 25,
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
      key: "kind",
      label: "Kind",
      // A pill cannot truncate: "BERRYWARE" needs the room, measured at 1500 px.
      width: 12,
      get: (f) => f.kind,
      render: (f) => <span className={`pill ${KIND_TONE[f.kind] ?? "neutral"}`}>{f.kind}</span>,
    },
    {
      key: "live",
      label: "Live",
      width: 13,
      get: (f) => {
        const live = liveOf(f);
        return live ? `v${live.version_no} (${fmtBytes(live.size_bytes)})` : "—";
      },
    },
    { key: "versions", label: "Versions", width: 7, numeric: true, get: (f) => f.versions.length },
    {
      key: "used",
      label: "Used",
      width: 11,
      get: (f) => (f.used ? "in use" : "not used"),
      render: (f) => (
        <span
          className={`pill ${f.used ? "ok" : "neutral"}`}
          title={f.used
            ? "A deployment version or a bundle pins a version of this file"
            : "Nothing pins any version of this file — it can be deleted"}
        >
          {f.used ? "in use" : "not used"}
        </span>
      ),
    },
    { key: "description", label: "Description", width: 17, get: (f) => f.description || "—" },
    {
      key: "actions",
      label: "",
      width: 15,
      interactive: false,
      className: "ctr",
      get: () => "",
      render: (f) => {
        const newest = newestOf(f);
        return (
          <span className="btn-row">
            {newest ? (
              <EyeButton
                title={`Preview ${f.filename} v${newest.version_no}`}
                onClick={() => setPreview({ file: f, version: newest })}
              />
            ) : null}
            {/* Berryware is updated by importing the folder on the Bundles
                tab, so its rows offer no upload. Artwork is one file. */}
            {f.kind === "artwork" ? (
              <FilePick
                accept=".lbrn2,.lbrn"
                disabled={busy}
                title={`Upload a new version of ${f.filename}. The uploaded file's own name is ignored.`}
                onPick={(picked) => void upload(picked, f)}
              >
                Upload
              </FilePick>
            ) : null}
            {newest ? (
              <button
                type="button"
                className="btn btn-sm row-del"
                title={`Delete v${newest.version_no}, the newest version. Refused while pinned.`}
                onClick={(e) => { e.stopPropagation(); void remove(newest, f); }}
              >
                ×
              </button>
            ) : null}
          </span>
        );
      },
    },
  ];

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Device files — the raw pool</h2>
        <span className="muted">{files ? `${files.length} files` : ""}</span>
        <button type="button" className="btn btn-sm" onClick={() => setExpanded((x) => !x)}>
          {expanded ? "Hide" : "Show"}
        </button>
        {expanded ? (
          <FilePick
            multiple
            disabled={busy}
            className="btn btn-primary btn-sm"
            title="Upload one or more files into the pool. A .lbrn2 becomes artwork, anything else berryware. An upload publishes."
            onPick={(picked) => void upload(picked)}
          >
            {busy ? "Uploading…" : "Upload a file…"}
          </FilePick>
        ) : null}
      </div>
      <p className="card-subtitle">
        Every file, every version — the berryware a device downloads and the laser artwork a
        mark version pins. Day-to-day berryware work happens in bundles above. Open this to
        preview, upload or delete one file.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      {note ? <p className="banner-ok">{note}</p> : null}
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
          onPreview={(file, version) => setPreview({ file, version })}
          onPublish={publish}
          onReject={reject}
          onDelete={remove}
        />
      ) : null}

      {preview ? (
        <FilePreview file={preview.file} version={preview.version} onClose={() => setPreview(null)} />
      ) : null}
    </div>
  );
}

function FileVersions({
  file, onPreview, onPublish, onReject, onDelete,
}: {
  file: DeviceFileRow | null;
  onPreview: (file: DeviceFileRow, version: DeviceFileVersionRow) => void;
  onPublish: (id: number, label: string) => void;
  onReject: (id: number, label: string) => void;
  onDelete: (version: DeviceFileVersionRow, file: DeviceFileRow) => void;
}) {
  if (!file) return null;
  return (
    <div className="meta-card">
      <strong className="mono">{file.filename}</strong>{" "}
      <span className={`pill ${KIND_TONE[file.kind] ?? "neutral"}`}>{file.kind}</span>
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
              <th>Used by</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {[...file.versions].reverse().map((v) => {
              const used = usedText(v);
              const label = `${file.filename} v${v.version_no}`;
              return (
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
                  <td className={used === "not used" ? "muted" : ""} title={used}>{used}</td>
                  <td className="ctr">
                    <span className="btn-row">
                      <EyeButton title={`Preview ${label}`} onClick={() => onPreview(file, v)} />
                      {v.status === "published" ? (
                        <a
                          className="btn btn-sm"
                          href={deviceFilePath(v.id, file.filename)}
                          download={file.filename}
                          title="Download this version's bytes"
                        >
                          ↓
                        </a>
                      ) : null}
                      {v.status === "draft" ? (
                        <>
                          <button
                            type="button"
                            className="btn btn-ok btn-sm"
                            onClick={() => onPublish(v.id, label)}
                          >
                            Publish
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => onReject(v.id, label)}
                          >
                            Reject
                          </button>
                        </>
                      ) : null}
                      <button
                        type="button"
                        className="btn btn-sm row-del"
                        title={used === "not used" ? "Delete this version" : `Pinned by ${used} — the platform will refuse`}
                        onClick={() => onDelete(v, file)}
                      >
                        ×
                      </button>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** The preview popup: the LightBurn thumbnail when the file carries one, then
 *  the text — or, for a binary, its size and a download. Fetched when opened;
 *  a 150 kB artwork is not something to hold for every row. */
function FilePreview({
  file, version, onClose,
}: {
  file: DeviceFileRow;
  version: DeviceFileVersionRow;
  onClose: () => void;
}) {
  const modal = useModal(onClose, { active: true });
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setContent(null);
    setError(null);
    getDeviceFileVersion(version.id, ac.signal)
      .then((v) => setContent(v.content))
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [version.id]);

  const thumb = content ? lbrnThumbnail(content) : null;
  const label = `${file.filename} v${version.version_no}`;

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <div className="toolbar">
          <h2 className="card-title">{label}</h2>
          <span className={`pill ${KIND_TONE[file.kind] ?? "neutral"}`}>{file.kind}</span>
          <StatusPill status={version.status} />
          <span className="muted dim mono">
            {fmtBytes(version.size_bytes)} · {shortSha(version.sha256)}
          </span>
          {version.status === "published" ? (
            <a
              className="btn btn-sm"
              href={deviceFilePath(version.id, file.filename)}
              download={file.filename}
            >
              Download
            </a>
          ) : null}
          <button type="button" className="btn btn-sm" onClick={onClose}>Close</button>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {content === null && !error ? <Spinner label="Loading the file…" /> : null}
        {content !== null && version.binary ? (
          <p className="muted">
            A binary file of {fmtBytes(version.size_bytes)} — there is no text to show. Download
            it to open it in its own program.
          </p>
        ) : null}
        {thumb ? <img className="file-preview-thumb" src={thumb} alt={`${label} — LightBurn preview`} /> : null}
        {content !== null && !version.binary ? (
          <pre className="code-block file-preview">{content}</pre>
        ) : null}
      </div>
    </div>
  );
}
