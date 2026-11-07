/** Where a component is used — every project whose latest ready snapshot
 *  places it, with boards, refs and quantities. The endpoint existed with no
 *  caller anywhere; a part's blast radius was invisible while editing it.
 *  Also the jump-off to the part's stock ledger on Stock → Parts. */
import { Link } from "react-router-dom";
import { getWhereUsed, type WhereUsedRow } from "../api";
import DataTable, { type Column } from "./DataTable";
import FoldSection, { StatChip } from "./FoldSection";
import { useLoad } from "./useLoad";

export default function WhereUsedCard({ compId, name }: { compId: number; name: string }) {
  const { data: rows } = useLoad<WhereUsedRow[]>(
    (signal) => getWhereUsed(compId, signal).catch(() => []),
    [compId],
    { keep: true },
  );

  // One row per (project, usage): the nested shape reads well but cannot be
  // sorted or filtered, and this is a list like any other.
  const flat = (rows ?? []).flatMap((r) =>
    r.usages.map((u, i) => ({
      key: `${r.project_id}-${i}`,
      project_id: r.project_id,
      project_name: r.project_name,
      ref: r.ref,
      ...u,
    })),
  );

  const cols: Column<(typeof flat)[number]>[] = [
    {
      key: "project",
      label: "Project",
      width: 30,
      get: (u) => u.project_name,
      render: (u) => (
        <Link className="comp-link" to={`/projects/${u.project_id}`} title={u.ref}>
          {u.project_name}
        </Link>
      ),
    },
    {
      key: "board",
      label: "Board",
      width: 26,
      className: "muted",
      get: (u) => `${u.board}${u.variant ? ` (${u.variant})` : ""}${u.dnp ? " DNP" : ""}`,
      render: (u) => (
        <>
          {u.board}
          {u.variant ? ` (${u.variant})` : ""}
          {u.dnp ? <span className="pill neutral">DNP</span> : null}
        </>
      ),
    },
    { key: "refs", label: "Refs", width: 30, className: "mono", get: (u) => u.refs },
    { key: "qty", label: "Qty / device", width: 14, numeric: true, get: (u) => u.qty },
  ];

  const dnp = flat.filter((u) => u.dnp).length;

  return (
    <FoldSection
      title="Where used"
      count={flat.length}
      foldKey={`component:${compId}:where-used`}
      chips={
        <>
          {rows?.length ? <StatChip n={rows.length}>{rows.length === 1 ? "project" : "projects"}</StatChip> : null}
          {dnp ? <StatChip n={dnp}>DNP</StatChip> : null}
        </>
      }
      actions={
        <Link className="btn btn-sm" to={`/stock?q=${encodeURIComponent(name)}`} title="Stock and draws for this part">
          Stock ledger
        </Link>
      }
    >
      {rows === null ? (
        <p className="muted">Checking projects…</p>
      ) : rows.length === 0 ? (
        <p className="muted">No tracked project uses this part in its latest snapshot.</p>
      ) : (
        <div className="table-wrap">
          <DataTable
            columns={cols}
            rows={flat}
            rowKey={(u) => u.key}
            persistKey={`where-used:${compId}`}
            empty="No usages."
          />
        </div>
      )}
    </FoldSection>
  );
}
