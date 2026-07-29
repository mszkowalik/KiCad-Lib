/** Berryware bundles — the SETS a device downloads, named as the berry
 *  project releases them ("release-1.3.11").
 *
 *  Left: how a bundle gets in (drop a folder, or name a set of existing
 *  files). Right: the bundles as cards — one line of identity, the file list
 *  on demand. Files still version individually; the bundle is the unit you
 *  pin, so it is the unit shown.
 */
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
  const [files, setFiles] = useState<DeviceFileRow[]>([]);
  const [picked, setPicked] = useState<number[]>([]);
  const [newLabel, setNewLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const dirRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(() => {
    const ac = new AbortController();
    Promise.all([listBerryBundles(projectId, ac.signal), listDeviceFiles(projectId, ac.signal)])
      .then(([b, f]) => {
        setBundles(b);
        setFiles(f);
      })
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

  const importFolder = async (chosen: FileList | null) => {
    if (!chosen?.length) return;
    const list = Array.from(chosen).filter((f) => !f.name.startsWith("."));
    const label = list[0]?.webkitRelativePath?.split("/")[0] || "";
    setBusy(true);
    setError(null);
    try {
      const res = await importDeviceFiles(projectId, list, { label });
      setNote(
        `"${res.bundle?.label ?? label}": ${res.files.length} files — ` +
          `${res.changed} new version(s), ${res.files.length - res.changed} reused.` +
          (res.changed === 0 ? " Identical to what was already stored, so no version churn." : ""),
      );
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      if (dirRef.current) dirRef.current.value = "";
    }
  };

  const createFromPicked = async () => {
    if (!picked.length || !newLabel.trim()) return;
    setBusy(true);
    try {
      const b = await createBerryBundle(projectId, {
        label: newLabel.trim(), file_version_ids: picked,
      });
      setNote(`"${b.label}" now holds ${b.file_count} files.`);
      setPicked([]);
      setNewLabel("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const rename = async (b: BerryBundleRow) => {
    const label = await dialog.prompt("Bundle name:", { title: b.label, initial: b.label });
    if (!label || label === b.label) return;
    try {
      await patchBerryBundle(b.id, { label });
      setNote(`Renamed to "${label}" — every version using it shows the new name.`);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const remove = async (b: BerryBundleRow) => {
    if (!(await dialog.confirm(
      b.used_by
        ? `"${b.label}" is used by ${b.used_by} deployment version(s) — the platform will refuse. Try anyway?`
        : `Delete bundle "${b.label}"? The files themselves stay in the pool.`,
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

  /** Newest published version of each file — what "name a set" picks from. */
  const livePerFile = files
    .map((f) => {
      const published = f.versions.filter((v) => v.status === "published");
      return published.length ? { file: f, live: published[published.length - 1] } : null;
    })
    .filter((x): x is { file: DeviceFileRow; live: DeviceFileRow["versions"][number] } => x !== null);

  return (
    <div className="fw-layout">
      {/* ---------------- add a bundle ---------------- */}
      <div className="card pad">
        <h2 className="card-title">Add a bundle</h2>
        <p className="card-subtitle">
          A bundle is one exact file set. The same set is always the same bundle, whatever the
          folder was called — so re-importing cannot create a twin.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        {note ? <p className="banner-ok">{note}</p> : null}

        <label className="btn btn-primary bundle-drop">
          {busy ? "Working…" : "Import a berryware folder…"}
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
        <p className="muted dim">
          The folder name becomes the bundle label (e.g. <span className="mono">release-1.3.11</span>).
          Only files whose content actually changed get a new version.
        </p>

        <h3 className="card-title bundle-or">or name a set of stored files</h3>
        <div className="btn-row">
          <input
            className="row-input"
            placeholder="bundle name"
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
          />
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setPicked(livePerFile.map((x) => x.live.id))}
            disabled={!livePerFile.length}
          >
            Select all
          </button>
          <button type="button" className="btn btn-sm" onClick={() => setPicked([])}>
            Clear
          </button>
        </div>
        <div className="bundle-pick-list">
          {livePerFile.length === 0 ? (
            <p className="muted">No published files in this project yet.</p>
          ) : (
            livePerFile.map(({ file, live }) => (
              <label key={file.id} className="bundle-pick">
                <input
                  type="checkbox"
                  checked={picked.includes(live.id)}
                  onChange={(e) =>
                    setPicked((xs) =>
                      e.target.checked ? [...xs, live.id] : xs.filter((x) => x !== live.id),
                    )
                  }
                />
                <span className="mono bundle-pick-name">{file.filename}</span>
                <span className="muted dim">v{live.version_no} · {fmtBytes(live.size_bytes)}</span>
              </label>
            ))
          )}
        </div>
        <div className="btn-row">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={createFromPicked}
            disabled={busy || !picked.length || !newLabel.trim()}
          >
            Create bundle
          </button>
          <span className="muted">{picked.length} of {livePerFile.length} selected</span>
        </div>
      </div>

      {/* ---------------- the bundles ---------------- */}
      <div className="card pad">
        <div className="toolbar">
          <h2 className="card-title">Bundles</h2>
          <span className="muted">{bundles ? `${bundles.length} sets` : ""}</span>
        </div>
        {bundles === null ? (
          <Spinner label="Loading bundles…" />
        ) : bundles.length === 0 ? (
          <p className="muted">No bundles yet — import a berryware folder on the left.</p>
        ) : (
          <div className="bundle-cards">
            {bundles.map((b) => (
              <div key={b.id} className={`bundle-card${open === b.id ? " open" : ""}`}>
                <div className="bundle-head">
                  <strong className="mono bundle-label">{b.label}</strong>
                  <span className="pill neutral">{b.file_count} files</span>
                  <span className={`pill ${b.used_by ? "ok" : "warn"}`}
                        title={b.used_by
                          ? "pinned by that many deployment versions"
                          : "no deployment version pins this set"}>
                    {b.used_by ? `used by ${b.used_by}` : "unused"}
                  </span>
                  <span className="muted dim mono" title={b.files_fingerprint}>
                    {shortSha(b.files_fingerprint)}
                  </span>
                  <span className="bundle-actions btn-row">
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setOpen(open === b.id ? null : b.id)}
                    >
                      {open === b.id ? "Hide files" : "Show files"}
                    </button>
                    <button type="button" className="btn btn-sm" onClick={() => rename(b)}>
                      Rename
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm row-del"
                      title={b.used_by ? "in use — will be refused" : "delete"}
                      onClick={() => remove(b)}
                    >
                      ×
                    </button>
                  </span>
                </div>
                <div className="bundle-meta muted dim">
                  {b.comment || "no note"} · created {fmtWhen(b.created_at)}
                  {b.created_by ? ` by ${b.created_by}` : ""}
                </div>
                {open === b.id ? (
                  <div className="table-wrap">
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
                ) : null}
              </div>
            ))}
          </div>
        )}
        <p className="muted dim">
          Download order is fixed when a version pins a bundle: autoexec.be goes last, so a partial
          download never leaves a device booting an incomplete application.
        </p>
      </div>
    </div>
  );
}
