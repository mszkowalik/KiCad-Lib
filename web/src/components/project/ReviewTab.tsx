import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  bulkSignoff,
  completeProjectReview,
  errorMessage,
  getProjectReview,
  isAbortError,
  type ProjectInfo,
  type ProjectReview,
  type SnapshotInfo,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, LifecyclePill, ReviewPill, SignoffPill, Spinner } from "../Ui";

/** The end-of-design review: every BOM-matched component of the snapshot with
 * its verification, sign-off and lifecycle state, per-selection bulk sign-off,
 * and the "review complete" record a production run warns against. */
export default function ReviewTab({
  project,
  snapshot,
}: {
  project: ProjectInfo;
  snapshot: SnapshotInfo | null;
}) {
  const [data, setData] = useState<ProjectReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const dialog = useDialog();

  const load = useCallback(
    (signal?: AbortSignal) => {
      getProjectReview(project.id, snapshot?.sha, signal)
        .then((d) => {
          setData(d);
          setError(null);
        })
        .catch((err) => {
          if (!isAbortError(err)) setError(errorMessage(err));
        });
    },
    [project.id, snapshot?.sha],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    setData(null);
    setSelected(new Set());
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Spinner label="Loading design review" />;

  const unsignedIds = [
    ...new Set(
      data.rows
        .filter((r) => r.matched && r.signoff_state !== "signed" && r.component_id !== null)
        .map((r) => r.component_id as number),
    ),
  ];

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const signSelected = async () => {
    const ids = [...selected];
    if (ids.length === 0) return;
    if (
      !(await dialog.confirm(
        `Sign off ${ids.length} component(s) as checked for production?`,
        { title: "Bulk sign-off", confirmLabel: "Sign off", tone: "ok" },
      ))
    )
      return;
    setBusy(true);
    try {
      await bulkSignoff(ids, `Design review of ${project.name} @ ${data.sha.slice(0, 8)}`);
      setSelected(new Set());
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const complete = async () => {
    const note = await dialog.prompt(
      data.clean
        ? "Optional note for the review record:"
        : "The snapshot is NOT clean — the record will store what is still open. Note:",
      { title: "Complete design review" },
    );
    if (note === null) return;
    setBusy(true);
    try {
      setData(await completeProjectReview(project.id, data.sha, note.trim() || undefined));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      {data.clean ? (
        <div className="banner-ok">
          Every matched component is verified and signed off
          {data.reviewed ? " — review completed" : ""}.
        </div>
      ) : (
        <div className="banner-warn">
          {data.unsigned.length} not signed off · {data.unreviewed.length} not verified ·{" "}
          {data.deprecated.length} deprecated
          {data.unmatched_lines ? ` · ${data.unmatched_lines} BOM line(s) match no library part` : ""}
          {data.changed_since_review.length
            ? ` · changed since the last review: ${data.changed_since_review.join(", ")}`
            : ""}
        </div>
      )}

      <div className="toolbar">
        <span className="toolbar-total">
          Snapshot <span className="mono">{data.sha.slice(0, 8)}</span>
          {data.ref_name ? ` (${data.ref_name})` : ""}
          {data.last_review
            ? ` — last review by ${data.last_review.reviewed_by} on ${new Date(
                data.last_review.reviewed_at,
              ).toLocaleDateString()}`
            : " — never reviewed"}
        </span>
        <button
          className="btn btn-sm"
          disabled={busy || unsignedIds.length === 0}
          onClick={() => setSelected(new Set(unsignedIds))}
        >
          Select unsigned ({unsignedIds.length})
        </button>
        <button className="btn btn-ok btn-sm" disabled={busy || selected.size === 0} onClick={() => void signSelected()}>
          Sign off selected ({selected.size})
        </button>
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void complete()}>
          Complete review
        </button>
      </div>

      <div className="table-wrap">
        <table className="data data-fixed project-review-table">
          <thead>
            <tr>
              <th className="ctr" aria-label="Select" />
              <th>Component</th>
              <th>Refs</th>
              <th>Value</th>
              <th>Drawn with</th>
              <th>Review</th>
              <th>Sign-off</th>
              <th>Lifecycle</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r, i) => (
              <tr key={i}>
                <td className="ctr">
                  {r.matched && r.signoff_state !== "signed" && r.component_id !== null ? (
                    <input
                      type="checkbox"
                      checked={selected.has(r.component_id)}
                      disabled={busy}
                      onChange={() => toggle(r.component_id as number)}
                      aria-label={`Select ${r.component_name ?? r.value}`}
                    />
                  ) : null}
                </td>
                <td title={r.component_name ?? `${r.value} (unmatched)`}>
                  {r.matched && r.component_id !== null ? (
                    <Link className="comp-link" to={`/library/components/${r.component_id}`}>
                      {r.component_name}
                    </Link>
                  ) : (
                    <span className="muted">{r.mpn || r.value || "?"} (no library match)</span>
                  )}
                </td>
                <td className="mono" title={r.refs}>
                  {r.refs}
                </td>
                <td className="mono" title={r.value}>
                  {r.value}
                </td>
                <td
                  className="mono"
                  title={
                    r.lib_version
                      ? `Library versions in the committed schematic vs current v${r.current_version_no ?? "?"}`
                      : "The committed schematic predates the version field"
                  }
                >
                  {r.lib_version || "—"}
                  {r.current_version_no !== null ? ` / v${r.current_version_no}` : ""}
                </td>
                <td title={r.review_blockers.join("; ")}>
                  {r.matched ? <ReviewPill state={r.review_state} /> : null}
                </td>
                <td>{r.matched ? <SignoffPill state={r.signoff_state} /> : null}</td>
                <td>{r.matched ? <LifecyclePill state={r.lifecycle} /> : null}</td>
              </tr>
            ))}
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="empty">
                  No BOM lines in this snapshot.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {data.past_reviews.length > 0 ? (
        <details className="card pad">
          <summary>Past reviews ({data.past_reviews.length})</summary>
          <ul className="notes-list">
            {data.past_reviews.map((r) => (
              <li key={r.id} className="note">
                <div className="note-head mono">
                  <span className="note-author">{r.reviewed_by}</span>
                  <span className="note-date">{new Date(r.reviewed_at).toLocaleString()}</span>
                  <span className="mono">{r.sha.slice(0, 8)}</span>
                </div>
                <p className="muted">
                  {r.summary_counts
                    ? `${r.summary_counts.components ?? "?"} components — ${r.summary_counts.unsigned ?? 0} unsigned, ${
                        r.summary_counts.unreviewed ?? 0
                      } unreviewed`
                    : ""}
                  {r.note ? ` — ${r.note}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
