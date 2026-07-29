/** Compose a new deployment version.
 *
 *  Starts from an existing version and inherits every section you do not
 *  touch, so "bump the firmware" or "update the berryware" is one action.
 *  Validation runs live against the same backend function the publish button
 *  uses, so the editor can never disagree with the gate.
 */
import { useEffect, useMemo, useState } from "react";
import {
  composeVersion,
  errorMessage,
  listBerryBundles,
  listFirmware,
  listParamSets,
  patchDeploymentVersion,
  publishDeploymentVersion,
  type BerryBundleRow,
  type DeploymentRow,
  type DeploymentVersionRow,
  type FirmwareAssetRow,
  type FlasherMeta,
  type ParamSetRow,
  type ValidationResult,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";
import StepEditor from "./StepEditor";

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
  const [bundles, setBundles] = useState<BerryBundleRow[]>([]);
  const [paramSets, setParamSets] = useState<ParamSetRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [comment, setComment] = useState("");
  const [images, setImages] = useState<ImageDraft[]>([]);
  const [fileIds, setFileIds] = useState<number[]>([]);
  const [filesLabel, setFilesLabel] = useState("");
  const [stepsText, setStepsText] = useState("");
  const [paramSetId, setParamSetId] = useState<number | "">("");
  const [transport, setTransport] = useState("uart_bridge");
  const [monitorBaud, setMonitorBaud] = useState(115200);

  // The draft, once created: everything after this point PATCHes it, so live
  // validation is the server's own answer.
  const [draft, setDraft] = useState<DeploymentVersionRow | null>(null);
  const [rawJson, setRawJson] = useState(false);
  const [bundleId, setBundleId] = useState<number | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    Promise.all([
      listFirmware(deployment.project_id, ac.signal),
      listParamSets(deployment.project_id, ac.signal),
      listBerryBundles(deployment.project_id, ac.signal),
    ])
      .then(([a, p, b]) => {
        setAssets(a);
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
    setBundleId(fromVersion.berry_bundle_id ?? null);
    setStepsText(JSON.stringify(fromVersion.steps ?? [], null, 2));
    setParamSetId(fromVersion.param_set_id ?? "");
    setTransport(fromVersion.transport_profile);
    setMonitorBaud(fromVersion.monitor_baud);
  }, [fromVersion]);

  const mark = (s: Section) => setTouched((t) => new Set(t).add(s));

  /** Names a step may interpolate: the chosen param set's keys. The server
   *  validates for real; this only fills the dropdowns. */
  const paramKeys = paramSets.find((p) => p.id === Number(paramSetId))?.keys ?? [];

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



  const sectionState = (s: Section) => (touched.has(s) ? "changed" : "unchanged");

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

        {/* ------- the procedure IS the editor: a flash step picks its images,
                   a download step picks its bundle, so firmware and berryware
                   need no sections of their own (user request 2026-07-30) ---- */}
        <div className="meta-card">
          <div className="toolbar">
            <strong>Procedure</strong>
            <span className={`pill ${touched.has("procedure") ? "warn" : "neutral"}`}>
              {sectionState("procedure")}
            </span>
            <span className="muted">{parsedSteps?.length ?? 0} steps</span>
            <select
              className="row-input"
              value={transport}
              title="uart_bridge = external USB-UART; usb_serial_jtag = native USB (never touches DTR/RTS in monitor mode)"
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
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setRawJson((x) => !x)}
              title="the same steps as JSON, for a bulk edit or a paste"
            >
              {rawJson ? "Visual editor" : "Edit as JSON"}
            </button>
          </div>

          {rawJson ? (
            <>
              <textarea
                className="note-textarea mono file-editor"
                spellCheck={false}
                value={stepsText}
                onChange={(e) => {
                  setStepsText(e.target.value);
                  mark("procedure");
                }}
              />
              {parsedSteps === null ? <p className="banner-error">Not valid JSON.</p> : null}
            </>
          ) : (
            <StepEditor
              steps={parsedSteps ?? []}
              onChange={(next) => {
                setStepsText(JSON.stringify(next, null, 2));
                mark("procedure");
              }}
              paramKeys={paramKeys}
              images={images
                .filter((i) => i.firmware_asset_id !== "")
                .map((i) => ({ firmware_asset_id: Number(i.firmware_asset_id), address: i.address }))}
              assets={assets}
              onImagesChange={(next) => {
                setImages(next.map((i) => ({ firmware_asset_id: i.firmware_asset_id, address: i.address })));
                mark("firmware");
              }}
              bundleId={bundleId}
              bundles={bundles}
              onBundleChange={(id) => {
                const b = bundles.find((x) => x.id === id);
                if (!b) return;
                setBundleId(id);
                setFileIds(b.files.map((f) => f.device_file_version_id));
                setFilesLabel(b.label);
                mark("files");
              }}
              defaultOffsets={meta?.default_offsets}
            />
          )}
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
