/** Side-by-side diff between two deployment versions. This is what you
 *  approve at publish time — a diff, never a form. */
import { useState } from "react";
import {
  getDeploymentDiff,
  type DeploymentVersionRow,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";
import { fmtBytes, shortSha } from "./common";
import { useModal } from "../modal";
import DataTable from "../DataTable";
import { useLoad } from "../useLoad";

function stateClass(state: string): string {
  return state === "unchanged" ? "neutral" : state === "removed" ? "err" : state === "added" ? "ok" : "warn";
}

export default function DiffView({
  versionId,
  versions,
  onClose,
}: {
  versionId: number;
  versions: DeploymentVersionRow[];
  onClose: () => void;
}) {
  const modal = useModal(() => onClose());
  const earlier = versions.filter((v) => v.id !== versionId);
  const [against, setAgainst] = useState<number | "">("");
  const { data: diff, error } = useLoad(
    (signal) => getDeploymentDiff(versionId, against === "" ? undefined : Number(against), signal),
    [versionId, against],
  );

  const changedOnly = (rows: { state: string }[]) => rows.filter((r) => r.state !== "unchanged");

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <div className="toolbar">
          <h2 className="card-title">Compare versions</h2>
          <select
            className="row-input"
            value={against}
            onChange={(e) => setAgainst(e.target.value === "" ? "" : Number(e.target.value))}
          >
            <option value="">against the previous version</option>
            {earlier.map((v) => (
              <option key={v.id} value={v.id}>
                against v{v.version_no} ({v.status})
              </option>
            ))}
          </select>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {!diff ? (
          <Spinner label="Computing the diff…" />
        ) : !diff.from ? (
          <p className="muted">This is the first version — nothing to compare against.</p>
        ) : (
          <>
            <p className="muted">
              v{diff.from.version_no} → v{diff.to.version_no}: <strong>{diff.changes.summary}</strong>
            </p>

            <h3 className="card-title">Firmware</h3>
            {changedOnly(diff.images).length === 0 ? (
              <p className="muted">Unchanged.</p>
            ) : (
              <div className="table-wrap">
                <DataTable
                  rows={diff.images.filter((r) => r.state !== "unchanged")}
                  rowKey={(r) => r.address}
                  columns={[
                    { key: "offset", label: "Offset", width: 22, className: "mono", get: (r) => r.address },
                    { key: "before", label: "Before", width: 32, className: "mono dim", title: (r) => r.before?.filename,
                      get: (r) => (r.before ? `${r.before.filename} ${shortSha(r.before.sha256)} (${fmtBytes(r.before.size_bytes)})` : "—") },
                    { key: "after", label: "After", width: 32, className: "mono", title: (r) => r.after?.filename,
                      get: (r) => (r.after ? `${r.after.filename} ${shortSha(r.after.sha256)} (${fmtBytes(r.after.size_bytes)})` : "—") },
                    { key: "state", label: "State", width: 14, get: (r) => r.state,
                      render: (r) => <span className={`pill ${stateClass(r.state)}`}>{r.state}</span> },
                  ]}
                />
              </div>
            )}

            <h3 className="card-title">{filesTitle(diff.files)}</h3>
            {changedOnly(diff.files).length === 0 ? (
              <p className="muted">Unchanged — same file set.</p>
            ) : (
              <div className="table-wrap">
                <DataTable
                  rows={diff.files.filter((r) => r.state !== "unchanged")}
                  rowKey={(r) => r.filename}
                  columns={[
                    { key: "file", label: "File", width: 22, className: "mono", get: (r) => r.filename },
                    { key: "before", label: "Before", width: 32, className: "mono dim",
                      get: (r) => (r.before ? `${shortSha(r.before.sha256)} (${fmtBytes(r.before.size_bytes)})` : "—") },
                    { key: "after", label: "After", width: 32, className: "mono",
                      get: (r) => (r.after ? `${shortSha(r.after.sha256)} (${fmtBytes(r.after.size_bytes)})` : "—") },
                    { key: "state", label: "State", width: 14, get: (r) => r.state,
                      render: (r) => <span className={`pill ${stateClass(r.state)}`}>{r.state}</span> },
                  ]}
                />
              </div>
            )}

            <h3 className="card-title">Procedure</h3>
            {!diff.steps_changed ? (
              <p className="muted">Unchanged — {diff.steps_after?.length ?? 0} steps.</p>
            ) : (
              <p className="muted">
                Changed: {diff.steps_before?.length ?? 0} → {diff.steps_after?.length ?? 0} steps.
              </p>
            )}
            {diff.steps_changed ? (
              <StepDiff before={diff.steps_before ?? []} after={diff.steps_after ?? []} />
            ) : null}

            {diff.changes.params !== "unchanged" ? (
              <p className="banner-warn">Parameter wiring changed.</p>
            ) : null}
            {diff.transport_before && diff.transport_after
              && (diff.transport_before.profile !== diff.transport_after.profile
                  || diff.transport_before.baud !== diff.transport_after.baud) ? (
              <p className="banner-warn">
                Transport changed: {diff.transport_before.profile}@{diff.transport_before.baud} →{" "}
                {diff.transport_after.profile}@{diff.transport_after.baud}
              </p>
            ) : null}
          </>
        )}
        <div className="btn-row modal-actions">
          <button type="button" className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

function StepDiff({
  before, after,
}: {
  before: Record<string, unknown>[];
  after: Record<string, unknown>[];
}) {
  const key = (s: Record<string, unknown>) => `${String(s.op)}|${String(s.label ?? "")}`;
  const beforeKeys = new Set(before.map(key));
  const afterKeys = new Set(after.map(key));
  const added = after.filter((s) => !beforeKeys.has(key(s)));
  const removed = before.filter((s) => !afterKeys.has(key(s)));
  return (
    <div className="step-diff">
      {added.map((s, i) => (
        <div key={`a${i}`} className="fl-tx mono">+ {String(s.op)} — {String(s.label ?? "")}</div>
      ))}
      {removed.map((s, i) => (
        <div key={`r${i}`} className="fl-err mono">− {String(s.op)} — {String(s.label ?? "")}</div>
      ))}
      {!added.length && !removed.length ? (
        <p className="muted">Same steps, reordered or re-parameterised.</p>
      ) : null}
    </div>
  );
}

/** "Berryware", "Artwork" or "Files" — from the kinds on both sides, so a
 *  mark version's diff does not call its drawing berryware. */
function filesTitle(rows: { before: { kind: string } | null; after: { kind: string } | null }[]): string {
  const kinds = new Set(rows.flatMap((r) => [r.before?.kind, r.after?.kind]).filter(Boolean));
  if (kinds.size === 1) return kinds.has("artwork") ? "Artwork" : "Berryware";
  return "Files";
}
