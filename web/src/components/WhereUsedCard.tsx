/** Where a component is used — every project whose latest ready snapshot
 *  places it, with boards, refs and quantities. The endpoint existed with no
 *  caller anywhere; a part's blast radius was invisible while editing it.
 *  Also the jump-off to the part's stock ledger on Production → Stock. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getWhereUsed, isAbortError, type WhereUsedRow } from "../api";
import DataTable, { type Column } from "./DataTable";

export default function WhereUsedCard({ compId, name }: { compId: number; name: string }) {
  const [rows, setRows] = useState<WhereUsedRow[] | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getWhereUsed(compId, ac.signal)
      .then(setRows)
      .catch((err) => {
        if (!isAbortError(err)) setRows([]);
      });
    return () => ac.abort();
  }, [compId]);

  // One row per (project, usage): the nested shape reads well but cannot be
  // sorted or filtered, and this is a list like any other.
  const flat = (rows ?? []).flatMap((r) =>
    r.usages.map((u, i) => ({
      key: `${r.project_id}-${i}`,
      project_id: r.project_id,
      project_name: r.project_name,
      ref: r.ref,
      first: i === 0,
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

  return (
    <section className="card pad">
      <h2 className="card-title">Where used</h2>
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
      <p className="muted dim">
        Stock and draws for this part:{" "}
        <Link to={`/production/stock?q=${encodeURIComponent(name)}`}>
          ledger on Production → Stock
        </Link>
      </p>
    </section>
  );
}
