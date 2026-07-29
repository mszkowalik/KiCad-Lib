/** Side-by-side diff between two deployment versions. This is what you
 *  approve at publish time — a diff, never a form. */
import { useEffect, useState } from "react";
import {
  errorMessage,
  getDeploymentDiff,
  isAbortError,
  type DeploymentDiff,
  type DeploymentVersionRow,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";
import { fmtBytes, shortSha } from "./common";

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
  const earlier = versions.filter((v) => v.id !== versionId);
  const [against, setAgainst] = useState<number | "">("");
  const [diff, setDiff] = useState<DeploymentDiff | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setDiff(null);
    getDeploymentDiff(versionId, against === "" ? undefined : Number(against), ac.signal)
      .then(setDiff)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [versionId, against]);

  const changedOnly = (rows: { state: string }[]) => rows.filter((r) => r.state !== "unchanged");

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card pad modal-card modal-card-wide" onMouseDown={(e) => e.stopPropagation()}>
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
            <p className="card-subtitle">
              v{diff.from.version_no} → v{diff.to.version_no}: <strong>{diff.changes.summary}</strong>
            </p>

            <h3 className="card-title">Firmware</h3>
            {changedOnly(diff.images).length === 0 ? (
              <p className="muted">Unchanged.</p>
            ) : (
              <div className="table-wrap">
                <table className="data data-fixed diff-table">
                  <thead>
                    <tr>
                      <th>Offset</th>
                      <th>Before</th>
                      <th>After</th>
                      <th>State</th>
                    </tr>
                  </thead>
                  <tbody>
                    {changedOnly(diff.images).map((row) => {
                      const r = row as (typeof diff.images)[number];
                      return (
                        <tr key={r.address}>
                          <td className="mono">{r.address}</td>
                          <td className="mono dim" title={r.before?.filename}>
                            {r.before
                              ? `${r.before.filename} ${shortSha(r.before.sha256)} (${fmtBytes(r.before.size_bytes)})`
                              : "—"}
                          </td>
                          <td className="mono" title={r.after?.filename}>
                            {r.after
                              ? `${r.after.filename} ${shortSha(r.after.sha256)} (${fmtBytes(r.after.size_bytes)})`
                              : "—"}
                          </td>
                          <td><span className={`pill ${stateClass(r.state)}`}>{r.state}</span></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <h3 className="card-title">Berryware</h3>
            {changedOnly(diff.files).length === 0 ? (
              <p className="muted">Unchanged — same file set.</p>
            ) : (
              <div className="table-wrap">
                <table className="data data-fixed diff-table">
                  <thead>
                    <tr>
                      <th>File</th>
                      <th>Before</th>
                      <th>After</th>
                      <th>State</th>
                    </tr>
                  </thead>
                  <tbody>
                    {changedOnly(diff.files).map((row) => {
                      const r = row as (typeof diff.files)[number];
                      return (
                        <tr key={r.filename}>
                          <td className="mono" title={r.filename}>{r.filename}</td>
                          <td className="mono dim">
                            {r.before ? `v${r.before.version_no} ${shortSha(r.before.sha256)}` : "—"}
                          </td>
                          <td className="mono">
                            {r.after ? `v${r.after.version_no} ${shortSha(r.after.sha256)}` : "—"}
                          </td>
                          <td><span className={`pill ${stateClass(r.state)}`}>{r.state}</span></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
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
