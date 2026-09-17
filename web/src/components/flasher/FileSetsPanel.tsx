/** Releases — the file SETS a deployment version pins (decision 0029).
 *
 *  One panel for both kinds: `berryware` is what the device downloads, named
 *  as the berry project releases it ("release-1.3.11"); `artwork` is what
 *  the laser engraves, one drawing per set. A set is an immutable manifest
 *  of (filename, content), platform wide — the same folder imported twice,
 *  by any project, is the same row — and there is no per-file version number
 *  anywhere on this page: a file's history is which releases carried which
 *  content, and the "vs previous" column reads it off the older sets.
 *
 *  Two ways in, one path on the server: import a folder (or upload files)
 *  makes a release; DERIVE copies an existing manifest, lets you replace or
 *  add files by upload, borrow files from any other release, or leave some
 *  out, and mints a new labelled release — the base is untouched. Delete is
 *  refused while any deployment version pins the set; the "Used by" column
 *  prints the same join before the click.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  deleteFileSet,
  deriveFileSet,
  errorMessage,
  fileSetFilePath,
  getFileSet,
  getFileSetEntry,
  importFileSet,
  isAbortError,
  listFileSets,
  patchFileSet,
  type FileSetRow,
  type VersionFileRow,
} from "../../api";
import { useDialog } from "../Dialog";
import Field, { FieldGrid } from "../Field";
import FilePick from "../FilePick";
import DataTable, { type Column } from "../DataTable";
import { ErrorBanner, Spinner } from "../Ui";
import { useModal } from "../modal";
import { fmtBytes, fmtWhen, lbrnThumbnail, shortSha } from "./common";

const KIND_TITLE: Record<string, string> = { berryware: "release", artwork: "drawing" };

/** The eye on a file row: a small rectangular button, never the content
 *  itself squeezed into a cell — the preview is a popup with room for it. */
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

export default function FileSetsPanel({
  kind, openId,
}: {
  kind: "berryware" | "artwork";
  /** a set to open on arrival — the version card links here with it */
  openId?: number | null;
}) {
  const dialog = useDialog();
  const [sets, setSets] = useState<FileSetRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<number | null>(openId ?? null);
  const [label, setLabel] = useState("");
  const [comment, setComment] = useState("");
  const [preview, setPreview] = useState<{ set: FileSetRow; file: VersionFileRow } | null>(null);
  const [deriving, setDeriving] = useState<FileSetRow | null>(null);
  const noun = KIND_TITLE[kind];

  const reload = useCallback(() => {
    const ac = new AbortController();
    listFileSets(kind, ac.signal)
      .then(setSets)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [kind]);

  useEffect(() => {
    setSets(null);
    setNote(null);
    return reload();
  }, [reload]);

  useEffect(() => {
    if (openId) setOpen(openId);
  }, [openId]);

  /** Folder or files, the same call: the server reuses unchanged bytes and
   *  finds the set if the exact manifest already exists. */
  const upload = async (picked: File[]) => {
    const list = picked.filter((f) => !f.name.startsWith("."));
    if (!list.length) return;
    const folder = list[0]?.webkitRelativePath?.split("/")[0] || "";
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const res = await importFileSet(list, { label: label.trim() || folder, comment, kind });
      const fresh = res.files.filter((f) => f.state === "new").length;
      setNote(res.created
        ? `"${res.set.label}": ${res.set.file_count} files, ${fresh} with new content.`
        : `"${res.set.label}" already existed with exactly these files — reused, nothing added.`);
      setLabel("");
      setComment("");
      setOpen(res.set.id);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const rename = async (s: FileSetRow) => {
    const next = await dialog.prompt(`Name of this ${noun}:`, { title: s.label, initial: s.label });
    if (!next || next === s.label) return;
    try {
      await patchFileSet(s.id, { label: next });
      setNote(`Renamed to "${next}" — every version pinning it shows the new name.`);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const remove = async (s: FileSetRow) => {
    if (!(await dialog.confirm(
      s.used_by
        ? `"${s.label}" is pinned by ${s.used_by} deployment version(s) — the platform will refuse. Try anyway?`
        : `Delete "${s.label}"? Content no other ${noun} shares goes with it.`,
      { title: `Delete ${noun}`, tone: "danger", confirmLabel: "Delete" },
    ))) return;
    try {
      const res = await deleteFileSet(s.id);
      setNote(`Deleted "${s.label}"${res.blobs_pruned ? ` and ${res.blobs_pruned} file(s) nothing else carried` : ""}.`);
      if (open === s.id) setOpen(null);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const cols: Column<FileSetRow>[] = [
    {
      key: "label",
      label: kind === "artwork" ? "Drawing" : "Release",
      width: kind === "artwork" ? 32 : 26,
      className: "mono",
      get: (s) => s.label,
      render: (s) => (
        <>
          <span className="ledger-caret">{open === s.id ? "▾" : "▸"}</span>
          {s.label}
        </>
      ),
    },
    { key: "files", label: "Files", width: 6, numeric: true, get: (s) => s.file_count },
    {
      key: "size", label: "Size", width: 9, numeric: true,
      get: (s) => s.size_bytes, render: (s) => <>{fmtBytes(s.size_bytes)}</>,
    },
    {
      key: "used",
      label: "Used by",
      width: 13,
      get: (s) => (s.used_by ? `${s.used_by} version${s.used_by === 1 ? "" : "s"}` : "unused"),
      render: (s) => (
        <span
          className={`pill ${s.used_by ? "ok" : "neutral"}`}
          title={s.used_by
            ? "deployment versions pinning this set — open the row to see which"
            : "no deployment version pins this set — it can be deleted"}
        >
          {s.used_by ? `${s.used_by} version${s.used_by === 1 ? "" : "s"}` : "unused"}
        </span>
      ),
    },
    {
      key: "created", label: "Created", width: kind === "artwork" ? 12 : 18, className: "muted",
      get: (s) => s.created_at ?? "",
      render: (s) => <>{fmtWhen(s.created_at)}{s.created_by ? ` · ${s.created_by}` : ""}</>,
    },
    {
      key: "actions",
      label: "",
      width: 28,
      interactive: false,
      className: "ctr",
      get: () => "",
      render: (s) => (
        <span className="btn-row">
          <button
            type="button"
            className="btn btn-sm"
            title={`A new ${noun} from this one: replace or add files, borrow from another, leave some out. This one is not touched.`}
            onClick={(e) => { e.stopPropagation(); setDeriving(s); }}
          >
            Derive…
          </button>
          <button type="button" className="btn btn-sm" onClick={(e) => { e.stopPropagation(); void rename(s); }}>
            Rename
          </button>
          <button
            type="button"
            className="btn btn-sm row-del"
            title={s.used_by ? "pinned by a version — will be refused" : "delete"}
            onClick={(e) => { e.stopPropagation(); void remove(s); }}
          >
            ×
          </button>
        </span>
      ),
    },
  ];

  return (
    <div className="fw-layout">
      {/* ---------------- add ---------------- */}
      <div className="card pad">
        <h2 className="card-title">{kind === "artwork" ? "Add a drawing" : "Add a release"}</h2>
        <p className="card-subtitle">
          {kind === "artwork"
            ? "One LightBurn file is one drawing. The same file uploaded twice is one row."
            : "A release is one exact set of files. The same set is always the same release, whatever the folder was called — so re-importing cannot create a twin."}
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        {note ? <p className="banner-ok">{note}</p> : null}
        <FieldGrid>
          <Field label="Name" hint={kind === "artwork" ? "empty = the file's own name" : "empty = the folder's name"}>
            <input
              className="text"
              value={label}
              placeholder={kind === "artwork" ? "Side_Info rev 4" : "release-1.3.12"}
              onChange={(e) => setLabel(e.target.value)}
            />
          </Field>
          <Field label="Note">
            <input
              className="text"
              value={comment}
              placeholder="where it came from, what changed"
              onChange={(e) => setComment(e.target.value)}
            />
          </Field>
        </FieldGrid>
        <div className="btn-row">
          {kind === "berryware" ? (
            <FilePick
              directory
              disabled={busy}
              className="btn btn-primary"
              title="Pick the release folder. Every file in it becomes the set; unchanged content is reused."
              onPick={(files) => void upload(files)}
            >
              {busy ? "Working…" : "Import a folder…"}
            </FilePick>
          ) : null}
          <FilePick
            multiple={kind === "berryware"}
            accept={kind === "artwork" ? ".lbrn2,.lbrn" : undefined}
            disabled={busy}
            className={kind === "artwork" ? "btn btn-primary" : "btn"}
            title={kind === "artwork"
              ? "Upload a LightBurn project."
              : "Pick the files of the release one by one."}
            onPick={(files) => void upload(files)}
          >
            {busy ? "Working…" : kind === "artwork" ? "Upload a .lbrn2…" : "Upload files…"}
          </FilePick>
        </div>
        {kind === "berryware" ? (
          <p className="muted dim">
            To change one file of an existing release, use <strong>Derive…</strong> on its row:
            the new release keeps everything else and names what moved.
          </p>
        ) : null}
      </div>

      {/* ---------------- the sets ---------------- */}
      <div className="card pad">
        <div className="toolbar">
          <h2 className="card-title">{kind === "artwork" ? "Drawings" : "Releases"}</h2>
          <span className="muted">{sets ? `${sets.length} ${noun}${sets.length === 1 ? "" : "s"}` : ""}</span>
        </div>
        {sets === null ? (
          <Spinner label="Loading…" />
        ) : sets.length === 0 ? (
          <p className="muted">Nothing yet — add one on the left.</p>
        ) : (
          <div className="table-wrap">
            <DataTable
              columns={cols}
              rows={sets}
              rowKey={(s) => s.id}
              persistKey={`file-sets-${kind}`}
              rowClass={() => "ledger-row"}
              openKey={open}
              onOpenChange={(k) => setOpen(k === null ? null : Number(k))}
              empty="Nothing yet."
            />
          </div>
        )}
        {open !== null && sets ? (
          <SetDetail
            key={open}
            setId={open}
            onPreview={(set, file) => setPreview({ set, file })}
          />
        ) : null}
        {kind === "berryware" ? (
          <p className="muted dim">
            Download order is fixed when a release is made: autoexec.be goes last, so a partial
            download never leaves a device booting an incomplete application.
          </p>
        ) : null}
      </div>

      {preview ? (
        <FilePreview set={preview.set} file={preview.file} onClose={() => setPreview(null)} />
      ) : null}
      {deriving ? (
        <DeriveDialog
          base={deriving}
          others={(sets ?? []).filter((s) => s.id !== deriving.id)}
          onClose={() => setDeriving(null)}
          onMade={(made, created) => {
            setDeriving(null);
            setNote(created
              ? `"${made.label}" made from "${deriving.label}".`
              : `"${made.label}" already existed with exactly these files — reused.`);
            setOpen(made.id);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}

/** The manifest and its users, fetched when the row opens. */
function SetDetail({
  setId, onPreview,
}: {
  setId: number;
  onPreview: (set: FileSetRow, file: VersionFileRow) => void;
}) {
  const [set, setSet] = useState<FileSetRow | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    setSet(null);
    getFileSet(setId, ac.signal)
      .then(setSet)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [setId]);
  if (error) return <ErrorBanner message={error} />;
  if (!set) return <Spinner label="Loading the files…" />;
  const users = set.users ?? [];
  return (
    <div className="meta-card">
      <div className="toolbar">
        <strong className="mono">{set.label}</strong>
        <span className="muted dim mono" title={set.fingerprint}>{shortSha(set.fingerprint)}</span>
        {set.comment ? <span className="muted">{set.comment}</span> : null}
      </div>
      <p className="muted">
        {users.length === 0 ? "Pinned by no deployment version." : (
          <>
            Pinned by{" "}
            {users.map((u, i) => (
              <span key={u.version_id}>
                {i ? ", " : ""}
                <Link className="val-link" to={`/production/deployments?version=${u.version_id}`}>
                  {u.deployment} v{u.version_no}
                </Link>
                {u.status !== "published" ? ` (${u.status})` : ""}
              </span>
            ))}
          </>
        )}
      </p>
      <div className="table-wrap">
        <table className="data data-fixed set-files-table">
          <thead>
            <tr>
              <th className="num">#</th>
              <th>File</th>
              <th className="num">Size</th>
              <th>sha256</th>
              <th>vs previous</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(set.files ?? []).map((f, i) => (
              <tr key={f.filename}>
                <td className="num">{i + 1}</td>
                <td className="mono" title={f.filename}>{f.filename}</td>
                <td className="num">{fmtBytes(f.size_bytes)}</td>
                <td className="mono dim" title={f.sha256}>{shortSha(f.sha256)}</td>
                <td>
                  {f.previous === null || f.previous === undefined ? (
                    <span className="pill info">new</span>
                  ) : f.previous.same ? (
                    <span className="muted dim">same as {f.previous.label}</span>
                  ) : (
                    <span className="pill warn" title={`differs from the copy in ${f.previous.label}`}>
                      changed since {f.previous.label}
                    </span>
                  )}
                </td>
                <td className="ctr">
                  <span className="btn-row">
                    <EyeButton title={`Preview ${f.filename}`} onClick={() => onPreview(set, f)} />
                    <a
                      className="btn btn-sm"
                      href={fileSetFilePath(set.id, f.filename)}
                      download={f.filename}
                      title="Download this file's bytes"
                    >
                      ↓
                    </a>
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

/** The preview popup: the LightBurn thumbnail when the file carries one, then
 *  the text — or, for a binary, its size and a download. Fetched when opened;
 *  a 150 kB artwork is not something to hold for every row. */
function FilePreview({
  set, file, onClose,
}: {
  set: FileSetRow;
  file: VersionFileRow;
  onClose: () => void;
}) {
  const modal = useModal(onClose, { active: true });
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setContent(null);
    setError(null);
    getFileSetEntry(set.id, file.filename, ac.signal)
      .then((e) => setContent(e.content))
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [set.id, file.filename]);

  const thumb = content ? lbrnThumbnail(content) : null;
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <div className="toolbar">
          <h2 className="card-title">{file.filename}</h2>
          <span className="pill neutral">{set.label}</span>
          <span className="muted dim mono">
            {fmtBytes(file.size_bytes)} · {shortSha(file.sha256)}
          </span>
          <a className="btn btn-sm" href={fileSetFilePath(set.id, file.filename)} download={file.filename}>
            Download
          </a>
          <button type="button" className="btn btn-sm" onClick={onClose}>Close</button>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {content === null && !error ? <Spinner label="Loading the file…" /> : null}
        {content !== null && file.binary ? (
          <p className="muted">
            A binary file of {fmtBytes(file.size_bytes)} — there is no text to show. Download it to
            open it in its own program.
          </p>
        ) : null}
        {thumb ? <img className="file-preview-thumb" src={thumb} alt={`${file.filename} — LightBurn preview`} /> : null}
        {content !== null && !file.binary ? (
          <pre className="code-block file-preview">{content}</pre>
        ) : null}
      </div>
    </div>
  );
}

type Planned =
  | { filename: string; state: "kept"; size_bytes: number }
  | { filename: string; state: "removed"; size_bytes: number }
  | { filename: string; state: "upload"; file: File; replaces: boolean }
  | { filename: string; state: "borrowed"; from: FileSetRow; replaces: boolean; size_bytes: number };

/** A new set from an existing one. Every row starts as "kept"; Replace…
 *  swaps it for an upload, Remove leaves it out, and the two controls at the
 *  bottom add files by upload or borrow them from any other release. The
 *  server does the work in one call; this only says what to do. */
function DeriveDialog({
  base, others, onClose, onMade,
}: {
  base: FileSetRow;
  others: FileSetRow[];
  onClose: () => void;
  onMade: (made: FileSetRow, created: boolean) => void;
}) {
  const modal = useModal(onClose, { active: true });
  const [rows, setRows] = useState<Planned[] | null>(null);
  const [label, setLabel] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [borrowFrom, setBorrowFrom] = useState<FileSetRow | null>(null);
  const [borrowFiles, setBorrowFiles] = useState<VersionFileRow[] | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getFileSet(base.id, ac.signal)
      .then((s) => setRows((s.files ?? []).map((f) => ({
        filename: f.filename, state: "kept", size_bytes: f.size_bytes,
      }))))
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [base.id]);

  useEffect(() => {
    if (!borrowFrom) { setBorrowFiles(null); return; }
    const ac = new AbortController();
    setBorrowFiles(null);
    getFileSet(borrowFrom.id, ac.signal)
      .then((s) => setBorrowFiles(s.files ?? []))
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [borrowFrom]);

  const put = (next: Planned) =>
    setRows((xs) => {
      const list = xs ?? [];
      const i = list.findIndex((r) => r.filename === next.filename);
      return i < 0 ? [...list, next] : list.map((r, j) => (j === i ? next : r));
    });
  const inBase = (name: string) => (rows ?? []).some((r) => r.filename === name && (r.state === "kept" || r.state === "removed"))
    || base.filenames.includes(name);

  const replaceWith = (name: string, file: File) =>
    put({ filename: name, state: "upload", file, replaces: base.filenames.includes(name) });
  const addUploads = (files: File[]) => {
    for (const f of files) put({ filename: f.name, state: "upload", file: f, replaces: base.filenames.includes(f.name) });
  };
  const restore = (name: string) => {
    if (base.filenames.includes(name)) {
      const size = (rows ?? []).find((r) => r.filename === name);
      put({ filename: name, state: "kept", size_bytes: size && "size_bytes" in size ? size.size_bytes : 0 });
    } else {
      setRows((xs) => (xs ?? []).filter((r) => r.filename !== name));
    }
  };
  const borrow = (f: VersionFileRow) => {
    if (!borrowFrom) return;
    put({ filename: f.filename, state: "borrowed", from: borrowFrom, replaces: inBase(f.filename), size_bytes: f.size_bytes });
  };

  const changed = (rows ?? []).filter((r) => r.state !== "kept");
  const submit = async () => {
    if (!label.trim()) {
      setError("Give the new release a name.");
      return;
    }
    if (!changed.length) {
      setError("Nothing changed — the result would be this same release.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await deriveFileSet(base.id, {
        files: (rows ?? []).flatMap((r) => (r.state === "upload" ? [r.file] : [])),
        remove: (rows ?? []).flatMap((r) => (r.state === "removed" ? [r.filename] : [])),
        take: (rows ?? []).flatMap((r) => (r.state === "borrowed" ? [{ set_id: r.from.id, filename: r.filename }] : [])),
        label: label.trim(),
        comment,
      });
      onMade(res.set, res.created);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <div className="toolbar">
          <h2 className="card-title">New release from {base.label}</h2>
          <span className="muted">{base.label} itself is not changed</span>
          <button type="button" className="btn btn-sm" onClick={onClose}>Cancel</button>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        <FieldGrid>
          <Field label="Name of the new release">
            <input
              className="text"
              value={label}
              placeholder={`${base.label}-fix1`}
              onChange={(e) => setLabel(e.target.value)}
              autoFocus
            />
          </Field>
          <Field label="Note">
            <input
              className="text"
              value={comment}
              placeholder="what moved and why"
              onChange={(e) => setComment(e.target.value)}
            />
          </Field>
        </FieldGrid>
        {rows === null ? <Spinner label="Loading the files…" /> : (
          <div className="table-wrap">
            <table className="data data-fixed derive-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th className="num">Size</th>
                  <th>Will be</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.filename} className={r.state === "removed" ? "dim" : ""}>
                    <td className="mono" title={r.filename}>{r.filename}</td>
                    <td className="num">
                      {r.state === "upload" ? fmtBytes(r.file.size) : fmtBytes(r.size_bytes)}
                    </td>
                    <td>
                      {r.state === "kept" ? <span className="muted dim">kept</span>
                        : r.state === "removed" ? <span className="pill err">left out</span>
                        : r.state === "upload" ? <span className="pill ok">{r.replaces ? "replaced by upload" : "added by upload"}</span>
                        : <span className="pill info">{r.replaces ? "replaced" : "added"} from {r.from.label}</span>}
                    </td>
                    <td className="ctr">
                      <span className="btn-row">
                        {r.state === "kept" || r.state === "removed" ? (
                          <FilePick
                            disabled={busy}
                            title={`Upload a new ${r.filename}. The uploaded file's own name is ignored.`}
                            onPick={(files) => { if (files[0]) replaceWith(r.filename, files[0]); }}
                          >
                            Replace…
                          </FilePick>
                        ) : null}
                        {r.state === "kept" ? (
                          <button type="button" className="btn btn-sm row-del"
                                  onClick={() => put({ filename: r.filename, state: "removed", size_bytes: r.size_bytes })}>
                            Leave out
                          </button>
                        ) : (
                          <button type="button" className="btn btn-sm" onClick={() => restore(r.filename)}>
                            Undo
                          </button>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="btn-row">
          <FilePick multiple disabled={busy} onPick={addUploads}
                    title="Add files by upload. A file with a name already in the list replaces it.">
            Add files…
          </FilePick>
          <select
            className="text"
            value={borrowFrom?.id ?? ""}
            onChange={(e) => setBorrowFrom(others.find((s) => s.id === Number(e.target.value)) ?? null)}
            title="Borrow files from any other release on the platform"
          >
            <option value="">— borrow from another release —</option>
            {others.map((s) => (
              <option key={s.id} value={s.id}>{s.label} · {s.file_count} files</option>
            ))}
          </select>
        </div>
        {borrowFrom ? (
          borrowFiles === null ? <Spinner label="Loading…" /> : (
            <div className="bundle-pick-list">
              {borrowFiles.map((f) => {
                const taken = (rows ?? []).some((r) => r.filename === f.filename && r.state === "borrowed" && r.from.id === borrowFrom.id);
                return (
                  <label key={f.filename} className="bundle-pick">
                    <input
                      type="checkbox"
                      checked={taken}
                      onChange={(e) => (e.target.checked ? borrow(f) : restore(f.filename))}
                    />
                    <span className="mono bundle-pick-name">{f.filename}</span>
                    <span className="muted dim">{fmtBytes(f.size_bytes)} · {shortSha(f.sha256)}</span>
                  </label>
                );
              })}
            </div>
          )
        ) : null}
        <div className="btn-row">
          <button type="button" className="btn btn-primary" disabled={busy || !changed.length} onClick={() => void submit()}>
            {busy ? "Working…" : "Make the release"}
          </button>
          <span className="muted">
            {changed.length ? `${changed.length} change${changed.length === 1 ? "" : "s"}` : "no changes yet"}
          </span>
        </div>
      </div>
    </div>
  );
}
