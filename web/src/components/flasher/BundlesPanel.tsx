/** Berryware bundles — the SETS the user actually receives ("release-1.3.11"),
 *  one row per distinct file set. Files keep versioning individually in the
 *  panel below; this is the view that matches how berryware ships. */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  errorMessage,
  importDeviceFiles,
  isAbortError,
  listBerryBundles,
  type BerryBundleRow,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";
import { fmtBytes, fmtWhen, shortSha } from "./common";

export default function BundlesPanel({ projectId }: { projectId: number }) {
  const [bundles, setBundles] = useState<BerryBundleRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dirRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(() => {
    const ac = new AbortController();
    listBerryBundles(projectId, ac.signal)
      .then(setBundles)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [projectId]);

  useEffect(() => {
    setBundles(null);
    setNote(null);
    return reload();
  }, [reload]);

  const importFolder = async (picked: FileList | null) => {
    if (!picked?.length) return;
    const list = Array.from(picked).filter((f) => !f.name.startsWith("."));
    const label = list[0]?.webkitRelativePath?.split("/")[0] || "";
    setBusy(true);
    setError(null);
    try {
      const res = await importDeviceFiles(projectId, list, { label });
      setNote(
        `Imported as bundle "${res.bundle?.label ?? label}" — ${res.changed} file(s) changed, ` +
          `${res.files.length - res.changed} reused.`,
      );
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      if (dirRef.current) dirRef.current.value = "";
    }
  };

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Berryware bundles</h2>
        <label className="btn btn-sm">
          {busy ? "Importing…" : "Import folder as bundle…"}
          <input
            ref={dirRef}
            type="file"
            multiple
            // @ts-expect-error — non-standard but supported in Chromium
            webkitdirectory=""
            className="hidden-input"
            onChange={(e) => importFolder(e.target.files)}
          />
        </label>
      </div>
      <p className="card-subtitle">
        One row per distinct file set — the folder name becomes the bundle label. Re-importing an
        unchanged folder reuses the bundle; only real content changes mint file versions.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      {note ? <p className="banner-ok">{note}</p> : null}
      {bundles === null ? (
        <Spinner label="Loading bundles…" />
      ) : bundles.length === 0 ? (
        <p className="muted">No bundles yet — import a berryware folder.</p>
      ) : (
        <div className="table-wrap">
          <table className="data data-fixed bundles-table">
            <thead>
              <tr>
                <th>Bundle</th>
                <th className="num">Files</th>
                <th>Used by</th>
                <th>Fingerprint</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {bundles.map((b) => (
                <tr key={b.id} className="ledger-row" onClick={() => setOpen(open === b.id ? null : b.id)}>
                  <td className="mono" title={b.comment}>
                    <span className="ledger-caret">{open === b.id ? "▾" : "▸"}</span>
                    {b.label}
                  </td>
                  <td className="num">{b.file_count}</td>
                  <td>{b.used_by ? `${b.used_by} version${b.used_by === 1 ? "" : "s"}` : "—"}</td>
                  <td className="mono dim" title={b.files_fingerprint}>{shortSha(b.files_fingerprint)}</td>
                  <td className="muted">{fmtWhen(b.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open !== null && bundles ? (
        <div className="meta-card">
          {bundles
            .filter((b) => b.id === open)
            .map((b) => (
              <div key={b.id} className="table-wrap">
                <table className="data data-fixed bundle-files-table">
                  <thead>
                    <tr>
                      <th className="num">#</th>
                      <th>File</th>
                      <th>Version</th>
                      <th className="num">Size</th>
                      <th>sha256</th>
                    </tr>
                  </thead>
                  <tbody>
                    {b.files.map((f, i) => (
                      <tr key={f.device_file_version_id}>
                        <td className="num">{i + 1}</td>
                        <td className="mono" title={f.filename}>{f.filename}</td>
                        <td>v{f.version_no}</td>
                        <td className="num">{fmtBytes(f.size_bytes)}</td>
                        <td className="mono dim" title={f.sha256}>{shortSha(f.sha256)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
        </div>
      ) : null}
    </div>
  );
}
