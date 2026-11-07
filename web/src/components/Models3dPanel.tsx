/** Library → Templates → 3D models: the file store that a footprint's
 *  `(model "${SEVENSIGMA_DIR}/3DModels/<rel_path>")` entries name.
 *
 *  The list is a WINDOW: the store holds thousands of files, and the route caps a
 *  list at 300 with no offset. So the path filter goes to the server, and the other
 *  columns offer no filter and no sort, because they could only act on the window.
 *
 *  A file carries no version and no review (routers/models3d.py). An upload is live
 *  at once, and an upload to a path that exists replaces its content for every
 *  footprint that names it. That is why that one case asks first.
 */
import { useEffect, useRef, useState } from "react";
import {
  errorMessage,
  isAbortError,
  listModels3d,
  model3dPath,
  uploadModel3d,
  type Model3DRow,
} from "../api";
import { fileHref } from "../viewkind";
import DataTable, { type Column } from "./DataTable";
import { useDialog } from "./Dialog";
import Field from "./Field";
import FilePick from "./FilePick";
import FoldSection from "./FoldSection";
import { fmtBytes } from "./flasher/common";
import { ErrorBanner, Spinner } from "./Ui";

/** The route's own cap on one list. */
const LIMIT = 300;

const COLUMNS: Column<Model3DRow>[] = [
  {
    key: "path",
    label: "Path",
    width: 64,
    serverFilter: true,
    className: "mono",
    get: (m) => m.rel_path,
    render: (m) => (
      <a
        className="comp-link"
        href={fileHref(model3dPath(m.rel_path), m.rel_path)}
        target="_blank"
        rel="noreferrer"
      >
        {m.rel_path}
      </a>
    ),
  },
  {
    key: "size",
    label: "Size",
    width: 12,
    numeric: true,
    interactive: false,
    get: (m) => m.size_bytes,
    render: (m) => fmtBytes(m.size_bytes),
  },
  {
    key: "sha",
    label: "SHA-256",
    width: 24,
    interactive: false,
    className: "mono dim",
    get: (m) => m.sha256,
  },
];

export default function Models3dPanel({ onChanged }: { onChanged?: () => void }) {
  const dialog = useDialog();
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<Model3DRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [seq, setSeq] = useState(0);
  const typing = useRef<number | undefined>(undefined);

  const [relPath, setRelPath] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const ac = new AbortController();
    listModels3d(query, LIMIT, ac.signal)
      .then((r) => {
        setRows(r.models);
        setTotal(r.total_matching);
        setError("");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [query, seq]);

  useEffect(() => () => window.clearTimeout(typing.current), []);

  const upload = async () => {
    if (!file) return;
    const path = relPath.trim().replace(/^\/+/, "");
    setBusy(true);
    setUploadError("");
    setNotice("");
    try {
      const same = await listModels3d(path, LIMIT);
      const existing = same.models.find((m) => m.rel_path === path);
      if (
        existing &&
        !(await dialog.confirm(
          `${path} exists (${fmtBytes(existing.size_bytes)}). The upload replaces its content for every ` +
            "footprint that names this path. The old file is not kept.",
          { title: "Replace this 3D model", confirmLabel: "Replace", tone: "danger" },
        ))
      ) {
        return;
      }
      const res = await uploadModel3d(path, file);
      setNotice(`${existing ? "Replaced" : "Added"} ${res.rel_path} (${fmtBytes(res.size_bytes)}). It is live now.`);
      setFile(null);
      setRelPath("");
      setSeq((n) => n + 1);
      onChanged?.();
    } catch (err) {
      setUploadError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <ErrorBanner message={error} />
      {rows === null && !error ? <Spinner label="Loading 3D models" /> : null}
      {rows !== null ? (
        <>
          <p className="muted dim">
            {total > rows.length
              ? `Shows the first ${rows.length.toLocaleString()} of ${total.toLocaleString()} files. Search the path to narrow the list.`
              : `${total.toLocaleString()} file(s).`}{" "}
            Open a path to see the file in the viewer.
          </p>
          <div className="card table-wrap">
            <DataTable<Model3DRow>
              rows={rows}
              rowKey={(m) => m.rel_path}
              empty="No 3D model matches."
              columns={COLUMNS}
              onServerFilters={(f) => {
                window.clearTimeout(typing.current);
                typing.current = window.setTimeout(() => setQuery((f.path ?? "").trim()), 250);
              }}
            />
          </div>
        </>
      ) : null}
      <FoldSection title="Upload a 3D model" count={null}>
        <p className="muted">
          An upload is live at once. There is no review step. A footprint names the file by its path under{" "}
          <span className="mono">3DModels/</span>, so type the path that the footprint names. If the path exists,
          the upload replaces its content for every footprint that names it. A path that does not exist makes a new
          file.
        </p>
        <ErrorBanner message={uploadError} />
        {notice ? <div className="banner-ok">{notice}</div> : null}
        <Field label="Path" hint="It must end in .step, .stp or .wrl.">
          <input
            className="text mono"
            value={relPath}
            placeholder="1551RFL.stp"
            spellCheck={false}
            onChange={(e) => setRelPath(e.target.value)}
          />
        </Field>
        <div className="btn-row">
          <FilePick
            accept=".step,.stp,.wrl"
            disabled={busy}
            onPick={(files) => {
              const f = files[0] ?? null;
              setFile(f);
              // The usual case: the file already has the name the footprint uses.
              if (f && !relPath.trim()) setRelPath(f.name);
            }}
          >
            Choose file…
          </FilePick>
          {file ? <span className="mono">{file.name} · {fmtBytes(file.size)}</span> : null}
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy || !file || !relPath.trim()}
            onClick={() => void upload()}
          >
            {busy ? "Uploading…" : "Upload…"}
          </button>
        </div>
      </FoldSection>
    </>
  );
}
