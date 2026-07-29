/** Berryware bundles — the SETS the user actually receives ("release-1.3.11"),
 *  one row per distinct file set. Files keep versioning individually in the
 *  panel below; this is the view that matches how berryware ships. */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  createBerryBundle,
  deleteBerryBundle,
  errorMessage,
  importDeviceFiles,
  isAbortError,
  listBerryBundles,
  listDeviceFiles,
  patchBerryBundle,
  type BerryBundleRow,
  type DeviceFileRow,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";
import { fmtBytes, fmtWhen, shortSha } from "./common";

export default function BundlesPanel({ projectId }: { projectId: number }) {
  const dialog = useDialog();
  const [bundles, setBundles] = useState<BerryBundleRow[] | null>(null);
  const [picking, setPicking] = useState(false);
  const [files, setFiles] = useState<DeviceFileRow[]>([]);
  const [picked, setPicked] = useState<number[]>([]);
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

  const rename = async (b: BerryBundleRow) => {
    const label = await dialog.prompt("Bundle name:", { title: b.label, initial: b.label });
    if (!label || label === b.label) return;
    try {
      await patchBerryBundle(b.id, { label });
      setNote(`Renamed to "${label}" — every version using it now shows the new name.`);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const remove = async (b: BerryBundleRow) => {
    if (!(await dialog.confirm(
      b.used_by
        ? `"${b.label}" is used by ${b.used_by} deployment version(s). The platform will refuse — delete anyway?`
        : `Delete bundle "${b.label}"? The files themselves stay.`,
      { title: "Delete bundle", tone: "danger", confirmLabel: "Delete" },
    ))) return;
    try {
      await deleteBerryBundle(b.id);
      setNote(`Deleted "${b.label}".`);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  /** Name a set by hand: pick the newest published version of each file. */
  const openPicker = async () => {
    try {
      const list = await listDeviceFiles(projectId);
      setFiles(list);
      setPicked([]);
      setPicking(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const createFromPicked = async () => {
    if (!picked.length) return;
    const label = await dialog.prompt("Name this bundle:", { title: "New bundle" });
    if (!label) return;
    try {
      const b = await createBerryBundle(projectId, { label, file_version_ids: picked });
      setNote(`Created "${b.label}" with ${b.file_count} files.`);
      setPicking(false);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

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
        <button type="button" className="btn btn-sm" onClick={openPicker}>
          New from files…
        </button>
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
                <th />
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
                  <td className="ctr">
                    <span className="btn-row">
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          void rename(b);
                        }}
                      >
                        Rename
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm row-del"
                        title={b.used_by ? "in use — the platform will refuse" : "delete"}
                        onClick={(e) => {
                          e.stopPropagation();
                          void remove(b);
                        }}
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

      {picking ? (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setPicking(false)}>
          <div className="card pad modal-card" onMouseDown={(e) => e.stopPropagation()}>
            <h2 className="card-title">New bundle from existing files</h2>
            <p className="card-subtitle">
              Pick the published version of each file. The same set as an existing bundle resolves
              to that bundle instead of creating a twin.
            </p>
            <div className="pin-file-list">
              {files.map((f) => {
                const published = f.versions.filter((v) => v.status === "published");
                const live = published[published.length - 1];
                if (!live) return null;
                return (
                  <label key={f.id} className="muted">
                    <input
                      type="checkbox"
                      checked={picked.includes(live.id)}
                      onChange={(e) =>
                        setPicked((xs) =>
                          e.target.checked ? [...xs, live.id] : xs.filter((x) => x !== live.id),
                        )
                      }
                    />{" "}
                    <span className="mono">{f.filename}</span> v{live.version_no}
                  </label>
                );
              })}
            </div>
            <div className="btn-row modal-actions">
              <span className="muted">{picked.length} selected</span>
              <button type="button" className="btn" onClick={() => setPicking(false)}>Cancel</button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={createFromPicked}
                disabled={!picked.length}
              >
                Create bundle
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
