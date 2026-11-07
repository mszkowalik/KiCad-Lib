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
import DataTable, { type Column } from "../DataTable";
import { useDialog } from "../Dialog";
import FoldSection, { StatChip } from "../FoldSection";
import { ErrorBanner, LifecyclePill, ReviewPill, SignoffPill, Spinner } from "../Ui";
import { localDate, localWhen } from "../../format";

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

  type Row = ProjectReview["rows"][number];
  const columns: Column<Row>[] = [
    { key: "sel", label: "", width: 3, interactive: false, className: "ctr", get: () => "",
      render: (r) => (r.matched && r.signoff_state !== "signed" && r.component_id !== null ? (
        <input
          type="checkbox"
          checked={selected.has(r.component_id)}
          disabled={busy}
          onChange={() => toggle(r.component_id as number)}
          aria-label={`Select ${r.component_name ?? r.value}`}
        />
      ) : null) },
    { key: "component", label: "Component", width: 18,
      get: (r) => r.component_name ?? `${r.mpn || r.value || "?"} (no library match)`,
      render: (r) => (r.matched && r.component_id !== null ? (
        <Link className="comp-link" to={`/library/components/${r.component_id}`}>{r.component_name}</Link>
      ) : (
        <span className="muted">{r.mpn || r.value || "?"} (no library match)</span>
      )) },
    { key: "refs", label: "Refs", width: 13, className: "mono", get: (r) => r.refs },
    { key: "value", label: "Value", width: 12, className: "mono", get: (r) => r.value },
    { key: "drawn", label: "Drawn with", width: 14, className: "mono",
      get: (r) => `${r.lib_version || "—"}${r.current_version_no !== null ? ` / v${r.current_version_no}` : ""}`,
      title: (r) => (r.lib_version
        ? `Library versions in the committed schematic vs current v${r.current_version_no ?? "?"}`
        : "The committed schematic predates the version field") },
    { key: "review", label: "Review", width: 13, get: (r) => (r.matched ? r.review_state ?? "" : ""),
      title: (r) => r.review_blockers.join("; "),
      render: (r) => (r.matched ? <ReviewPill state={r.review_state} /> : null) },
    { key: "signoff", label: "Sign-off", width: 13, get: (r) => (r.matched ? r.signoff_state ?? "" : ""),
      render: (r) => (r.matched ? <SignoffPill state={r.signoff_state} /> : null) },
    { key: "lifecycle", label: "Lifecycle", width: 14, get: (r) => (r.matched ? r.lifecycle ?? "" : ""),
      render: (r) => (r.matched ? <LifecyclePill state={r.lifecycle} /> : null) },
  ];

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
            ? ` — last review by ${data.last_review.reviewed_by} on ${localDate(
                data.last_review.reviewed_at,
              )}`
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

      <FoldSection
        title="Parts"
        count={data.rows.length}
        foldKey={`project:${project.id}:review-parts`}
        forceOpen={selected.size > 0}
        chips={
          <>
            {data.unmatched_lines ? <StatChip n={data.unmatched_lines} tone="err">no library match</StatChip> : null}
            {data.unsigned.length ? <StatChip n={data.unsigned.length} tone="warn">not signed</StatChip> : null}
            {data.unreviewed.length ? <StatChip n={data.unreviewed.length} tone="warn">not verified</StatChip> : null}
            {data.deprecated.length ? <StatChip n={data.deprecated.length} tone="warn">deprecated</StatChip> : null}
          </>
        }
      >
      <div className="table-wrap">
        <DataTable
          rows={data.rows}
          rowKey={(r) => `${r.refs}|${r.value}|${r.component_id}`}
          columns={columns}
          empty="No BOM lines in this snapshot."
        />
      </div>
      </FoldSection>

      {data.past_reviews.length > 0 ? (
        <FoldSection
          title="Past reviews"
          count={data.past_reviews.length}
          foldKey={`project:${project.id}:past-reviews`}
          chips={data.last_review ? <StatChip n={localDate(data.last_review.reviewed_at)}>last</StatChip> : undefined}
        >
          <ul className="notes-list">
            {data.past_reviews.map((r) => (
              <li key={r.id} className="note">
                <div className="note-head mono">
                  <span className="note-author">{r.reviewed_by}</span>
                  <span className="note-date">{localWhen(r.reviewed_at)}</span>
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
        </FoldSection>
      ) : null}
    </div>
  );
}
