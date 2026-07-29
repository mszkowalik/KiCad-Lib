/** Compose a new deployment version.
 *
 *  Starts from an existing version and inherits every section you do not
 *  touch, so "bump the firmware" or "update the berryware" is one action.
 *  Validation runs live against the same backend function the publish button
 *  uses, so the editor can never disagree with the gate.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  composeVersion,
  errorMessage,
  importDeviceFiles,
  listBerryBundles,
  listDeviceFiles,
  listFirmware,
  listParamSets,
  patchDeploymentVersion,
  publishDeploymentVersion,
  uploadFirmware,
  type BerryBundleRow,
  type DeploymentRow,
  type DeploymentVersionRow,
  type DeviceFileRow,
  type FirmwareAssetRow,
  type FlasherMeta,
  type ImportedFile,
  type ParamSetRow,
  type ValidationResult,
} from "../../api";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { fmtBytes } from "./common";

interface ImageDraft {
  firmware_asset_id: number | "";
  address: string;
}

type Section = "firmware" | "files" | "procedure" | "params";

export default function Composer({
  deployment,
  fromVersion,
  meta,
  onClose,
}: {
  deployment: DeploymentRow;
  fromVersion: DeploymentVersionRow | null;
  meta: FlasherMeta | null;
  onClose: (published: boolean) => void;
}) {
  const [touched, setTouched] = useState<Set<Section>>(new Set());
  const [assets, setAssets] = useState<FirmwareAssetRow[]>([]);
  const [files, setFiles] = useState<DeviceFileRow[]>([]);
  const [bundles, setBundles] = useState<BerryBundleRow[]>([]);
  const [paramSets, setParamSets] = useState<ParamSetRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [comment, setComment] = useState("");
  const [images, setImages] = useState<ImageDraft[]>([]);
  const [fileIds, setFileIds] = useState<number[]>([]);
  const [filesLabel, setFilesLabel] = useState("");
  const [importedNote, setImportedNote] = useState<string | null>(null);
  const [stepsText, setStepsText] = useState("");
  const [paramSetId, setParamSetId] = useState<number | "">("");
  const [transport, setTransport] = useState("uart_bridge");
  const [monitorBaud, setMonitorBaud] = useState(115200);

  // The draft, once created: everything after this point PATCHes it, so live
  // validation is the server's own answer.
  const [draft, setDraft] = useState<DeploymentVersionRow | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const dirRef = useRef<HTMLInputElement>(null);
  const fwRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const ac = new AbortController();
    Promise.all([
      listFirmware(deployment.project_id, ac.signal),
      listDeviceFiles(deployment.project_id, ac.signal),
      listParamSets(deployment.project_id, ac.signal),
      listBerryBundles(deployment.project_id, ac.signal),
    ])
      .then(([a, f, p, b]) => {
        setAssets(a);
        setFiles(f);
        setParamSets(p);
        setBundles(b);
      })
      .catch((err) => setError(errorMessage(err)));
    return () => ac.abort();
  }, [deployment.project_id]);

  // Seed the editor from the starting version.
  useEffect(() => {
    if (!fromVersion) {
      setTransport("uart_bridge");
      setStepsText("[]");
      return;
    }
    setImages((fromVersion.images ?? []).map((i) => ({
      firmware_asset_id: i.firmware_asset_id, address: i.address,
    })));
    setFileIds((fromVersion.files ?? []).map((f) => f.device_file_version_id));
    setFilesLabel(fromVersion.files_label);
    setStepsText(JSON.stringify(fromVersion.steps ?? [], null, 2));
    setParamSetId(fromVersion.param_set_id ?? "");
    setTransport(fromVersion.transport_profile);
    setMonitorBaud(fromVersion.monitor_baud);
  }, [fromVersion]);

  const mark = (s: Section) => setTouched((t) => new Set(t).add(s));

  const parsedSteps = useMemo(() => {
    try {
      const v = JSON.parse(stepsText || "[]");
      return Array.isArray(v) ? (v as Record<string, unknown>[]) : null;
    } catch {
      return null;
    }
  }, [stepsText]);

  /** Create the draft (or PATCH it) and pick up the server's validation. */
  const sync = async (): Promise<DeploymentVersionRow | null> => {
    if (parsedSteps === null) {
      setError("The procedure is not valid JSON.");
      return null;
    }
    setBusy(true);
    setError(null);
    try {
      const payload = {
        comment,
        images: touched.has("firmware")
          ? images.filter((i) => i.firmware_asset_id !== "").map((i) => ({
              firmware_asset_id: Number(i.firmware_asset_id),
              address: i.address.trim() || "0x0",
            }))
          : undefined,
        file_version_ids: touched.has("files") ? fileIds : undefined,
        files_label: touched.has("files") ? filesLabel : undefined,
        steps: touched.has("procedure") ? parsedSteps : undefined,
        param_set_id: touched.has("params") ? (paramSetId === "" ? null : Number(paramSetId)) : undefined,
        transport_profile: touched.has("procedure") ? transport : undefined,
        monitor_baud: touched.has("procedure") ? monitorBaud : undefined,
      };
      const res = draft
        ? await patchDeploymentVersion(draft.id, payload)
        : await composeVersion(deployment.id, {
            ...payload,
            from_version_id: fromVersion?.id ?? null,
            created_by: "",
          });
      setDraft(res);
      setValidation(res.validation);
      return res;
    } catch (err) {
      setError(errorMessage(err));
      return null;
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    const v = draft ?? (await sync());
    if (!v) return;
    if (!comment.trim()) {
      setError("Say what changed and why — it is stored with the version.");
      return;
    }
    setBusy(true);
    try {
      // A PATCH first, so the comment and any last edit are in.
      const synced = await patchDeploymentVersion(v.id, { comment });
      if (!synced.validation.ok) {
        setValidation(synced.validation);
        setError("Validation failed — fix the errors below.");
        return;
      }
      await publishDeploymentVersion(v.id);
      onClose(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  /** Folder import: unchanged files are reused, only real changes mint a
   *  version. The resolved set becomes the pinned berryware. */
  const importFolder = async (picked: FileList | null) => {
    if (!picked?.length) return;
    const list = Array.from(picked).filter((f) => !f.name.startsWith("."));
    const label = list[0]?.webkitRelativePath?.split("/")[0] || "";
    setBusy(true);
    setError(null);
    try {
      const res = await importDeviceFiles(deployment.project_id, list, { label });
      setFileIds(res.files.map((f: ImportedFile) => f.device_file_version_id));
      setFilesLabel(res.bundle?.label ?? label);
      setImportedNote(
        `Bundle "${res.bundle?.label ?? label}" — ${res.changed} changed, ` +
          `${res.files.length - res.changed} unchanged`,
      );
      mark("files");
      setFiles(await listDeviceFiles(deployment.project_id));
      setBundles(await listBerryBundles(deployment.project_id));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      if (dirRef.current) dirRef.current.value = "";
    }
  };

  const uploadImage = async () => {
    const file = fwRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const res = await uploadFirmware(deployment.project_id, file, {
        kind: "factory", chip: deployment.chip,
      });
      setAssets(await listFirmware(deployment.project_id));
      setImages((xs) => [...xs, { firmware_asset_id: res.id, address: "0x0" }]);
      mark("firmware");
      if (fwRef.current) fwRef.current.value = "";
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const pinLatestFiles = () => {
    const latestOf = (fileId: number) => {
      const f = files.find((x) => x.id === fileId);
      const published = (f?.versions ?? []).filter((v) => v.status === "published");
      return published.length ? published[published.length - 1].id : null;
    };
    const next = fileIds
      .map((fvId) => {
        const owner = files.find((f) => f.versions.some((v) => v.id === fvId));
        return owner ? latestOf(owner.id) ?? fvId : fvId;
      })
      .filter((x): x is number => x !== null);
    setFileIds(next);
    mark("files");
  };

  const sectionState = (s: Section) => (touched.has(s) ? "changed" : "unchanged");
  const pinnedFileRows = fileIds
    .map((fvId) => {
      const owner = files.find((f) => f.versions.some((v) => v.id === fvId));
      const ver = owner?.versions.find((v) => v.id === fvId);
      return owner && ver ? { filename: owner.filename, ver } : null;
    })
    .filter((x): x is { filename: string; ver: DeviceFileRow["versions"][number] } => x !== null)
    .sort((a, b) =>
      Number(a.filename === "autoexec.be") - Number(b.filename === "autoexec.be")
      || a.filename.localeCompare(b.filename));

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose(false)}>
      <div className="card pad modal-card modal-card-wide" onMouseDown={(e) => e.stopPropagation()}>
        <h2 className="card-title">
          New version of {deployment.name}
          {fromVersion ? ` — starting from v${fromVersion.version_no}` : " — first version"}
        </h2>
        <p className="card-subtitle">
          Every section you do not touch is inherited. One version pins firmware, berryware, the
          procedure and the parameter wiring together.
        </p>
        {error ? <ErrorBanner message={error} /> : null}

        {/* ---------------- firmware ---------------- */}
        <div className="meta-card">
          <div className="toolbar">
            <strong>Firmware</strong>
            <span className={`pill ${touched.has("firmware") ? "warn" : "neutral"}`}>
              {sectionState("firmware")}
            </span>
          </div>
          {images.map((img, i) => (
            <div key={i} className="btn-row">
              <select
                className="row-input"
                value={img.firmware_asset_id}
                onChange={(e) => {
                  const val = e.target.value === "" ? "" : Number(e.target.value);
                  setImages((xs) => xs.map((x, j) => (j === i ? { ...x, firmware_asset_id: val } : x)));
                  mark("firmware");
                }}
              >
                <option value="">— pick an image —</option>
                {assets.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.filename} ({a.kind}, {fmtBytes(a.size_bytes)}){a.build_label ? ` — ${a.build_label}` : ""}
                  </option>
                ))}
              </select>
              <input
                className="row-input mono"
                value={img.address}
                placeholder="0x0"
                title="flash offset"
                onChange={(e) => {
                  setImages((xs) => xs.map((x, j) => (j === i ? { ...x, address: e.target.value } : x)));
                  mark("firmware");
                }}
              />
              <button
                type="button"
                className="btn btn-sm row-del"
                onClick={() => {
                  setImages((xs) => xs.filter((_, j) => j !== i));
                  mark("firmware");
                }}
              >
                ×
              </button>
            </div>
          ))}
          <div className="btn-row">
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                setImages((xs) => [...xs, { firmware_asset_id: "", address: "" }]);
                mark("firmware");
              }}
            >
              Add image
            </button>
            <input ref={fwRef} type="file" accept=".bin" />
            <button type="button" className="btn btn-sm" onClick={uploadImage} disabled={busy}>
              Upload + add
            </button>
          </div>
        </div>

        {/* ---------------- berryware ---------------- */}
        <div className="meta-card">
          <div className="toolbar">
            <strong>Berryware</strong>
            <span className={`pill ${touched.has("files") ? "warn" : "neutral"}`}>
              {sectionState("files")}
            </span>
            <span className="muted">{pinnedFileRows.length} files pinned</span>
          </div>
          <div className="btn-row">
            <input
              className="row-input"
              placeholder="set label (e.g. release-1.3.11)"
              value={filesLabel}
              onChange={(e) => {
                setFilesLabel(e.target.value);
                mark("files");
              }}
            />
            <select
              className="row-input"
              value=""
              title="pin an existing bundle — the whole set at once"
              onChange={(e) => {
                const b = bundles.find((x) => x.id === Number(e.target.value));
                if (!b) return;
                setFileIds(b.files.map((f) => f.device_file_version_id));
                setFilesLabel(b.label);
                setImportedNote(`Pinned bundle "${b.label}" (${b.file_count} files).`);
                mark("files");
              }}
            >
              <option value="">— pin a bundle —</option>
              {bundles.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.label} ({b.file_count} files{b.used_by ? `, used by ${b.used_by}` : ""})
                </option>
              ))}
            </select>
            <label className="btn btn-sm">
              Import folder…
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
            <button type="button" className="btn btn-sm" onClick={pinLatestFiles} disabled={!fileIds.length}>
              Pin latest published
            </button>
          </div>
          {importedNote ? <p className="banner-ok">{importedNote}</p> : null}
          {pinnedFileRows.length ? (
            <div className="table-wrap">
              <table className="data data-fixed composer-files-table">
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>File</th>
                    <th>Version</th>
                    <th className="num">Size</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {pinnedFileRows.map((row, i) => (
                    <tr key={row.ver.id}>
                      <td className="num">{i + 1}</td>
                      <td className="mono" title={row.filename}>{row.filename}</td>
                      <td>
                        v{row.ver.version_no} <StatusPill status={row.ver.status} />
                      </td>
                      <td className="num">{fmtBytes(row.ver.size_bytes)}</td>
                      <td className="ctr">
                        <button
                          type="button"
                          className="btn btn-sm row-del"
                          onClick={() => {
                            setFileIds((xs) => xs.filter((x) => x !== row.ver.id));
                            mark("files");
                          }}
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No berryware pinned — import a folder or inherit the previous set.</p>
          )}
        </div>

        {/* ---------------- procedure ---------------- */}
        <div className="meta-card">
          <div className="toolbar">
            <strong>Procedure</strong>
            <span className={`pill ${touched.has("procedure") ? "warn" : "neutral"}`}>
              {sectionState("procedure")}
            </span>
            <span className="muted">{parsedSteps?.length ?? "invalid JSON"} steps</span>
            <select
              className="row-input"
              value={transport}
              onChange={(e) => {
                setTransport(e.target.value);
                mark("procedure");
              }}
            >
              {(meta?.transport_profiles ?? ["uart_bridge", "usb_serial_jtag"]).map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <input
              className="row-input num"
              value={monitorBaud}
              title="monitor baud"
              onChange={(e) => {
                setMonitorBaud(Number(e.target.value) || 115200);
                mark("procedure");
              }}
            />
          </div>
          <textarea
            className="note-textarea mono file-editor"
            spellCheck={false}
            value={stepsText}
            onChange={(e) => {
              setStepsText(e.target.value);
              mark("procedure");
            }}
          />
          <p className="muted dim">Ops: {(meta?.ops ?? []).join(", ")}</p>
        </div>

        {/* ---------------- parameters ---------------- */}
        <div className="meta-card">
          <div className="toolbar">
            <strong>Parameters</strong>
            <span className={`pill ${touched.has("params") ? "warn" : "neutral"}`}>
              {sectionState("params")}
            </span>
            <select
              className="row-input"
              value={paramSetId}
              onChange={(e) => {
                setParamSetId(e.target.value === "" ? "" : Number(e.target.value));
                mark("params");
              }}
            >
              <option value="">— no param set —</option>
              {paramSets.map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.keys.length} keys)</option>
              ))}
            </select>
          </div>
        </div>

        {/* ---------------- validation ---------------- */}
        {validation ? (
          validation.ok && !validation.warnings.length ? (
            <p className="banner-ok">Validation passed — ready to publish.</p>
          ) : (
            <>
              {validation.errors.length ? (
                <div className="banner-error">
                  <strong>Must fix before publishing:</strong>
                  <ul className="val-list">
                    {validation.errors.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </div>
              ) : null}
              {validation.warnings.length ? (
                <div className="banner-warn">
                  <ul className="val-list">
                    {validation.warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              ) : null}
            </>
          )
        ) : null}

        <div className="btn-row modal-actions">
          <input
            className="row-input composer-comment"
            placeholder="what changed and why (stored with the version)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <button type="button" className="btn" onClick={() => onClose(false)} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-sm" onClick={() => sync()} disabled={busy}>
            {busy ? <Spinner /> : draft ? "Re-check" : "Save draft + check"}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={publish}
            disabled={busy || (validation !== null && !validation.ok)}
          >
            Publish
          </button>
        </div>
      </div>
    </div>
  );
}
