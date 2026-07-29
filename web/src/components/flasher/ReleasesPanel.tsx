/** Releases — only the FLASH: named per project, immutable versions mapping
 *  firmware images to offsets. Steps live in deployment scripts, not here. */
import { useCallback, useEffect, useState } from "react";
import {
  createRelease,
  createReleaseVersion,
  errorMessage,
  isAbortError,
  listFirmware,
  listReleases,
  publishReleaseVersion,
  rejectReleaseVersion,
  type FirmwareAssetRow,
  type ReleaseRow,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { fmtBytes, fmtWhen } from "./common";

interface ImageDraft {
  firmware_asset_id: number | "";
  address: string;
}

export default function ReleasesPanel({ projectId }: { projectId: number }) {
  const dialog = useDialog();
  const [releases, setReleases] = useState<ReleaseRow[] | null>(null);
  const [assets, setAssets] = useState<FirmwareAssetRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // new-version composer, keyed by release id (null = closed)
  const [composerFor, setComposerFor] = useState<number | null>(null);
  const [images, setImages] = useState<ImageDraft[]>([{ firmware_asset_id: "", address: "0x0" }]);
  const [comment, setComment] = useState("");

  const reload = useCallback(() => {
    const ac = new AbortController();
    Promise.all([listReleases(projectId, ac.signal), listFirmware(projectId, ac.signal)])
      .then(([r, a]) => {
        setReleases(r);
        setAssets(a);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [projectId]);

  useEffect(() => {
    setReleases(null);
    return reload();
  }, [reload]);

  const addRelease = async () => {
    const name = await dialog.prompt("Release name (e.g. CE_Dongle_V3 production):", {
      title: "New release",
    });
    if (!name) return;
    const chip = (await dialog.prompt("Chip (esp32 / esp32c6):", { title: "New release" })) ?? "";
    try {
      await createRelease(projectId, { name, chip });
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const saveVersion = async (releaseId: number) => {
    const picked = images.filter((i) => i.firmware_asset_id !== "");
    if (!picked.length) {
      setError("Pick at least one firmware image.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createReleaseVersion(releaseId, {
        comment,
        images: picked.map((i) => ({
          firmware_asset_id: Number(i.firmware_asset_id),
          address: i.address.trim() || "0x0",
        })),
      });
      setComposerFor(null);
      setComment("");
      setImages([{ firmware_asset_id: "", address: "0x0" }]);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const publish = async (versionId: number, label: string) => {
    if (!(await dialog.confirm(`Publish ${label}? Programming runs can then use it.`, {
      title: "Publish release version", tone: "ok", confirmLabel: "Publish",
    }))) return;
    try {
      await publishReleaseVersion(versionId);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const reject = async (versionId: number, label: string) => {
    if (!(await dialog.confirm(`Reject ${label}? The draft stays as a tombstone.`, {
      title: "Reject draft", tone: "danger", confirmLabel: "Reject",
    }))) return;
    try {
      await rejectReleaseVersion(versionId);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Releases — the flash</h2>
        <button type="button" className="btn btn-sm" onClick={addRelease}>New release</button>
      </div>
      <p className="card-subtitle">
        A release version is an immutable set of firmware images at flash offsets. The programming
        steps live in a deployment script, which pins one of these.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      {releases === null ? (
        <Spinner label="Loading releases…" />
      ) : releases.length === 0 ? (
        <p className="muted">No releases yet.</p>
      ) : (
        releases.map((r) => (
          <div key={r.id} className="meta-card">
            <div className="toolbar">
              <strong>{r.name}</strong>
              <span className="mono dim">{r.chip || "chip?"}</span>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  setComposerFor(composerFor === r.id ? null : r.id);
                  setImages([{ firmware_asset_id: "", address: "0x0" }]);
                }}
              >
                {composerFor === r.id ? "Cancel" : "New version"}
              </button>
            </div>
            {composerFor === r.id ? (
              <div className="edit-card pad">
                {images.map((img, i) => (
                  <div key={i} className="btn-row">
                    <select
                      className="row-input"
                      value={img.firmware_asset_id}
                      onChange={(e) =>
                        setImages((xs) =>
                          xs.map((x, j) =>
                            j === i
                              ? { ...x, firmware_asset_id: e.target.value === "" ? "" : Number(e.target.value) }
                              : x,
                          ),
                        )
                      }
                    >
                      <option value="">— pick a firmware image —</option>
                      {assets.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.filename} ({a.kind}, {fmtBytes(a.size_bytes)})
                        </option>
                      ))}
                    </select>
                    <input
                      className="row-input mono"
                      value={img.address}
                      placeholder="0x0"
                      title="flash offset"
                      onChange={(e) =>
                        setImages((xs) => xs.map((x, j) => (j === i ? { ...x, address: e.target.value } : x)))
                      }
                    />
                    <button
                      type="button"
                      className="btn btn-sm row-del"
                      onClick={() => setImages((xs) => xs.filter((_, j) => j !== i))}
                    >
                      ×
                    </button>
                  </div>
                ))}
                <div className="btn-row">
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setImages((xs) => [...xs, { firmware_asset_id: "", address: "" }])}
                  >
                    Add image
                  </button>
                  <input
                    className="row-input"
                    placeholder="comment (what changed)"
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={busy}
                    onClick={() => saveVersion(r.id)}
                  >
                    Save draft version
                  </button>
                </div>
                <p className="muted dim">
                  Flash mode/freq/size stay "keep" — PlatformIO bakes them into the image header.
                </p>
              </div>
            ) : null}
            {r.versions.length === 0 ? (
              <p className="muted">No versions.</p>
            ) : (
              <div className="table-wrap">
                <table className="data data-fixed release-versions-table">
                  <thead>
                    <tr>
                      <th>v</th>
                      <th>Status</th>
                      <th>Images</th>
                      <th>Comment</th>
                      <th>Created</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {r.versions.map((v) => (
                      <tr key={v.id}>
                        <td className="mono">
                          v{v.version_no}
                          {r.current_version_id === v.id ? " ●" : ""}
                        </td>
                        <td><StatusPill status={v.status} /></td>
                        <td
                          className="mono dim"
                          title={v.images.map((i) => `${i.filename} @ ${i.address}`).join("\n")}
                        >
                          {v.images.map((i) => `${i.kind}@${i.address}`).join(" + ") || "—"}
                        </td>
                        <td title={v.comment}>{v.comment || "—"}</td>
                        <td className="muted">{fmtWhen(v.created_at)}</td>
                        <td className="ctr">
                          {v.status === "draft" ? (
                            <span className="btn-row">
                              <button
                                type="button"
                                className="btn btn-ok btn-sm"
                                onClick={() => publish(v.id, `${r.name} v${v.version_no}`)}
                              >
                                Publish
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => reject(v.id, `${r.name} v${v.version_no}`)}
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
            )}
          </div>
        ))
      )}
    </div>
  );
}
