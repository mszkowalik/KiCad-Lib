import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  errorMessage,
  getChangeDetail,
  isAbortError,
  type ChangeDetailPayload,
  type ChangeKind,
  type ChangeRowDiff,
} from "../api";
import GeometryDiff from "./GeometryDiff";
import { ErrorBanner, Spinner } from "./Ui";

/** The unfolded half of one change-feed row.
 *
 *  It fetches ON MOUNT, and it is only mounted while its row is open — that is
 *  the whole reason the feed can carry ~18k events cheaply. Nothing here is
 *  prefetched, and collapsing a row unmounts this and drops the diff.
 *
 *  Each kind answers "what changed" in the terms that kind is edited in:
 *  components as a property table, drawings as before/after renders plus the
 *  pin or pad rows behind them, skills as a text diff. */

function KeyValueDiff({ rows }: { rows: { key: string; before?: string; after?: string }[] }) {
  return (
    <table className="data data-fixed">
      <colgroup>
        <col style={{ width: "26%" }} />
        <col style={{ width: "37%" }} />
        <col style={{ width: "37%" }} />
      </colgroup>
      <thead>
        <tr>
          <th>Key</th>
          <th>Before</th>
          <th>After</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key}>
            <td className="mono" title={r.key}>
              {r.key}
            </td>
            <td title={r.before}>{r.before ?? <span className="dim">—</span>}</td>
            <td title={r.after}>{r.after ?? <span className="dim">—</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Pins or pads, keyed by the number that identifies them. */
function RowDiffTable({ diff }: { diff: ChangeRowDiff }) {
  const cells = (v: Record<string, string> | undefined) =>
    v === undefined ? (
      <span className="dim">—</span>
    ) : (
      Object.entries(v)
        .filter(([, val]) => val !== "")
        .map(([k, val]) => `${k} ${val}`)
        .join(", ")
    );
  const rows = [
    ...diff.changed.map((r) => ({ id: r.id, before: r.before, after: r.after, what: "changed" })),
    ...diff.added.map((r) => ({ id: r.id, before: undefined, after: r.after, what: "added" })),
    ...diff.removed.map((r) => ({ id: r.id, before: r.before, after: undefined, what: "removed" })),
  ];
  if (rows.length === 0) {
    return (
      <div className="muted">
        {diff.label}: none added, removed or changed ({diff.unchanged} unchanged).
      </div>
    );
  }
  return (
    <>
      <div className="change-section-title">
        {diff.label} — {rows.length} changed, {diff.unchanged} unchanged
      </div>
      <table className="data data-fixed">
        <colgroup>
          <col style={{ width: "14%" }} />
          <col style={{ width: "12%" }} />
          <col style={{ width: "37%" }} />
          <col style={{ width: "37%" }} />
        </colgroup>
        <thead>
          <tr>
            <th>#</th>
            <th />
            <th>Before</th>
            <th>After</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.what}-${r.id}`}>
              <td className="mono">{r.id}</td>
              <td className="muted">{r.what}</td>
              <td>{cells(r.before)}</td>
              <td>{cells(r.after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function TextDiff({ lines, truncated }: { lines: string[]; truncated: boolean }) {
  return (
    <>
      <pre className="text-diff">
        {lines.map((line, i) => {
          const cls = line.startsWith("+++") || line.startsWith("---")
            ? "muted"
            : line.startsWith("@@")
              ? "hunk"
              : line.startsWith("+")
                ? "add"
                : line.startsWith("-")
                  ? "del"
                  : undefined;
          return (
            <span key={i} className={cls}>
              {line || " "}
              {"\n"}
            </span>
          );
        })}
      </pre>
      {truncated ? <div className="diff-note">Diff trimmed — open the skill for the full text.</div> : null}
    </>
  );
}

/** Where this change lives, so a reader can go and act on it. */
function subjectLink(d: ChangeDetailPayload) {
  if (d.kind === "component") return <Link to={`/library/components/${d.id}`}>Open component</Link>;
  if (d.kind === "symbol") return <Link to={`/library/templates/symbol/${d.id}`}>Open symbol</Link>;
  if (d.kind === "footprint")
    return <Link to={`/library/templates/footprint/${d.id}`}>Open footprint</Link>;
  if (d.kind === "skill") return <Link to={`/library/skills/${d.id}`}>Open skill</Link>;
  return null;
}

export default function ChangeDetail({ kind, id }: { kind: ChangeKind; id: number }) {
  const [data, setData] = useState<ChangeDetailPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setData(null);
    setError(null);
    getChangeDetail(kind, id, ctrl.signal)
      .then(setData)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [kind, id]);

  if (error !== null) return <ErrorBanner message={error} />;
  if (data === null) return <Spinner label="loading the diff" />;

  const props = data.properties;
  const propRows = props
    ? [
        ...props.changed,
        ...props.added,
        ...props.removed,
      ]
    : [];

  return (
    <div className="change-detail">
      {data.comment ? <div className="change-comment">{data.comment}</div> : null}

      {data.first_version && data.kind !== "model3d" && data.kind !== "event" ? (
        <div className="muted">First version — there is nothing before it to compare against.</div>
      ) : null}

      {data.kind === "component" ? (
        <>
          {(data.fields ?? []).length > 0 ? (
            <>
              <div className="change-section-title">Pins and placement</div>
              <KeyValueDiff
                rows={(data.fields ?? []).map((f) => ({
                  key: f.label,
                  before: f.before,
                  after: f.after,
                }))}
              />
            </>
          ) : null}
          {propRows.length > 0 ? (
            <>
              <div className="change-section-title">
                Properties — {props?.changed.length} changed, {props?.added.length} added,{" "}
                {props?.removed.length} removed, {props?.unchanged} untouched
              </div>
              <KeyValueDiff rows={propRows} />
            </>
          ) : (
            <div className="muted">
              No property changed ({props?.unchanged ?? 0} untouched).
              {(data.fields ?? []).length > 0 ? " Only the pins above moved." : ""}
            </div>
          )}
        </>
      ) : null}

      {data.kind === "symbol" || data.kind === "footprint" ? (
        <>
          <GeometryDiff
            beforePath={data.before_svg ?? null}
            afterPath={data.after_svg ?? ""}
            beforeLabel={
              data.prev_version_no !== null && data.prev_version_no !== undefined
                ? `Before — v${data.prev_version_no}`
                : "Before"
            }
            afterLabel={`After — v${data.version_no}`}
          />
          {data.rows ? <RowDiffTable diff={data.rows} /> : null}
          <div className="diff-note">
            {data.material_changed
              ? "The material fingerprint MOVED — pads, drills, layers or the courtyard changed, so verifications did not carry."
              : "The material fingerprint is unchanged — this edit did not touch what reaches the board."}
            {data.recheck_required === false ? " Published as a minor change." : ""}
          </div>
        </>
      ) : null}

      {data.kind === "skill" ? (
        <>
          <div className="change-section-title">
            +{data.added_lines} / −{data.removed_lines} lines
          </div>
          <TextDiff lines={data.diff ?? []} truncated={data.diff_truncated ?? false} />
        </>
      ) : null}

      {data.kind === "model3d" ? (
        <KeyValueDiff
          rows={[
            { key: "Path", after: data.name },
            { key: "Size", after: `${((data.size_bytes ?? 0) / 1024).toFixed(1)} kB` },
            { key: "SHA-256", after: data.sha256 },
          ]}
        />
      ) : null}

      {data.kind === "event" ? (
        <KeyValueDiff
          rows={[
            { key: "Action", after: data.action },
            { key: "Subject", after: `${data.entity_type} ${data.entity_id ?? ""}`.trim() },
            ...(data.details ?? []).map((d) => ({
              key: d.key,
              after: d.value === null || d.value === undefined ? "—" : String(d.value),
            })),
          ]}
        />
      ) : null}

      <div>{subjectLink(data)}</div>
    </div>
  );
}
