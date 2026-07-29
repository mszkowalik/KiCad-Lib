/** The composed view of ONE deployment version: everything a device gets,
 *  in the order it gets it, plus where the version is used. */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  firmwareBinPath,
  getDeploymentVersion,
  isAbortError,
  type DeploymentVersionDetail,
} from "../../api";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { fmtBytes, fmtWhen, shortSha } from "./common";

export default function VersionView({
  versionId,
  onDiff,
  reloadKey = 0,
}: {
  versionId: number;
  onDiff?: (versionId: number) => void;
  reloadKey?: number;
}) {
  const [v, setV] = useState<DeploymentVersionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSteps, setShowSteps] = useState(true);
  // The BUNDLE is what you see; the file list is detail behind a toggle
  // (user feedback 2026-07-30: "I still see the files listed instead of the bundle").
  const [showFiles, setShowFiles] = useState(false);

  const load = useCallback(() => {
    const ac = new AbortController();
    setV(null);
    getDeploymentVersion(versionId, ac.signal)
      .then(setV)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [versionId, reloadKey]);

  useEffect(() => load(), [load]);

  if (error) return <ErrorBanner message={error} />;
  if (!v) return <Spinner label="Loading version…" />;

  const val = v.validation;

  return (
    <>
      <div className="card pad">
        <div className="toolbar">
          <h2 className="card-title">
            {v.deployment.name} v{v.version_no}
          </h2>
          <StatusPill status={v.status} />
          {v.where_used.channels.map((c) => (
            <span key={c} className="pill ok">{c}</span>
          ))}
          {onDiff ? (
            <button type="button" className="btn btn-sm" onClick={() => onDiff(v.id)}>
              Compare
            </button>
          ) : null}
        </div>
        <p className="card-subtitle">
          {v.comment || "no comment"} · {v.created_by || "unknown author"} · {fmtWhen(v.created_at)}
          {v.approved_by ? ` · published by ${v.approved_by}` : ""}
        </p>
        <p className="muted">
          Changed vs the previous version: <strong>{v.changes.summary}</strong>
        </p>
        {val.errors.length ? (
          <div className="banner-error">
            <strong>Would not publish:</strong>
            <ul className="val-list">
              {val.errors.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          </div>
        ) : null}
        {val.warnings.length ? (
          <div className="banner-warn">
            <ul className="val-list">
              {val.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          </div>
        ) : null}
      </div>

      <div className="card pad">
        <h3 className="card-title">
          Firmware{" "}
          <span className="muted dim mono">
            {v.firmware_fingerprint ? shortSha(v.firmware_fingerprint) : "none"}
          </span>
        </h3>
        {v.images?.length ? (
          <div className="table-wrap">
            <table className="data data-fixed dv-images-table">
              <thead>
                <tr>
                  <th>Offset</th>
                  <th>Image</th>
                  <th>Kind</th>
                  <th>Chip</th>
                  <th className="num">Size</th>
                  <th>Build</th>
                  <th>sha256</th>
                </tr>
              </thead>
              <tbody>
                {v.images.map((img) => (
                  <tr key={img.address}>
                    <td className="mono">{img.address}</td>
                    <td className="mono" title={img.filename}>
                      <a className="comp-link" href={firmwareBinPath(img.firmware_asset_id)}>
                        {img.filename}
                      </a>
                    </td>
                    <td>{img.kind}</td>
                    <td className="mono dim">{img.chip || "—"}</td>
                    <td className="num">{fmtBytes(img.size_bytes)}</td>
                    <td title={img.build_label}>{img.build_label || "—"}</td>
                    <td className="mono dim" title={img.sha256}>{shortSha(img.sha256)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No firmware — this version flashes nothing.</p>
        )}
      </div>

      <div className="card pad">
        <div className="toolbar">
          <h3 className="card-title">Berryware</h3>
          {v.files?.length ? (
            <span className={`pill ${v.berry_bundle_id ? "ok" : "warn"}`}
                  title={v.berry_bundle_id
                    ? "a named bundle — the same set everywhere it appears"
                    : "an ad-hoc file set nobody has named"}>
              {v.files_label || "unnamed set"} · {v.files.length} files
            </span>
          ) : null}
          <span className="muted dim mono">
            {v.files_fingerprint ? shortSha(v.files_fingerprint) : ""}
          </span>
          {v.files?.length ? (
            <button type="button" className="btn btn-sm" onClick={() => setShowFiles((x) => !x)}>
              {showFiles ? "Hide files" : "Show files"}
            </button>
          ) : null}
        </div>
        {!v.files?.length ? (
          <p className="muted">No berryware pinned.</p>
        ) : !showFiles ? null : (
          <div className="table-wrap">
            <table className="data data-fixed dv-files-table">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>File</th>
                  <th>Version</th>
                  <th className="num">Size</th>
                  <th>sha256</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {v.files.map((f, i) => (
                  <tr key={f.device_file_version_id}>
                    <td className="num">{i + 1}</td>
                    <td className="mono" title={f.filename}>{f.filename}</td>
                    <td>
                      v{f.version_no} <StatusPill status={f.status} />
                    </td>
                    <td className="num">{fmtBytes(f.size_bytes)}</td>
                    <td className="mono dim" title={f.sha256}>{shortSha(f.sha256)}</td>
                    <td className="muted" title={f.comment}>{f.comment || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card pad">
        <div className="toolbar">
          <h3 className="card-title">Procedure — {v.steps?.length ?? 0} steps</h3>
          <span className="muted dim mono">
            {v.transport_profile} @ {v.monitor_baud}
          </span>
          <button type="button" className="btn btn-sm" onClick={() => setShowSteps((s) => !s)}>
            {showSteps ? "Hide" : "Show"}
          </button>
        </div>
        {showSteps ? (
          <ol className="step-list">
            {(v.steps ?? []).map((s, i) => {
              const step = s as Record<string, unknown>;
              return (
                <li key={i}>
                  <span className="mono dim step-op">{String(step.op)}</span>
                  <span>{String(step.label ?? step.op)}</span>
                  {step.note ? <span className="muted dim"> — {String(step.note)}</span> : null}
                </li>
              );
            })}
          </ol>
        ) : null}
      </div>

      <div className="card pad">
        <h3 className="card-title">Parameters</h3>
        <p className="card-subtitle">
          Values resolve at run time and are snapshotted (masked) on every run — rotating a password
          never mints a version.
        </p>
        <p className="muted">
          Param set: <strong>{v.param_set_name ?? "none"}</strong>
          {v.param_defaults && Object.keys(v.param_defaults).length
            ? ` · defaults: ${Object.keys(v.param_defaults).join(", ")}`
            : ""}
        </p>
      </div>

      <div className="card pad">
        <h3 className="card-title">Where used</h3>
        <p className="muted">
          {v.where_used.runs} programming runs · {v.where_used.devices} devices
          {v.where_used.channels.length ? ` · channels: ${v.where_used.channels.join(", ")}` : ""}
        </p>
        {v.where_used.batches.length ? (
          <p className="muted">
            Batches:{" "}
            {v.where_used.batches.map((b, i) => (
              <span key={b.id}>
                {i ? ", " : ""}
                <Link className="val-link" to={`/runs/${b.id}`}>{b.label}</Link>
              </span>
            ))}
          </p>
        ) : null}
        {v.where_used.runs > 0 ? (
          <Link className="val-link" to={`/production/devices?deployment_version=${v.id}`}>
            See the devices programmed with this version
          </Link>
        ) : null}
      </div>
    </>
  );
}
