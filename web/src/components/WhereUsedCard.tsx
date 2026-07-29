/** Where a component is used — every project whose latest ready snapshot
 *  places it, with boards, refs and quantities. The endpoint existed with no
 *  caller anywhere; a part's blast radius was invisible while editing it.
 *  Also the jump-off to the part's stock ledger on Production → Stock. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getWhereUsed, isAbortError, type WhereUsedRow } from "../api";

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

  return (
    <section className="card pad">
      <h2 className="card-title">Where used</h2>
      {rows === null ? (
        <p className="muted">Checking projects…</p>
      ) : rows.length === 0 ? (
        <p className="muted">No tracked project uses this part in its latest snapshot.</p>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Project</th>
                <th>Board</th>
                <th>Refs</th>
                <th className="num">Qty / device</th>
              </tr>
            </thead>
            <tbody>
              {rows.flatMap((r) =>
                r.usages.map((u, i) => (
                  <tr key={`${r.project_id}-${i}`}>
                    <td>
                      {i === 0 ? (
                        <Link className="comp-link" to={`/projects/${r.project_id}`} title={r.ref}>
                          {r.project_name}
                        </Link>
                      ) : (
                        ""
                      )}
                    </td>
                    <td className="muted">
                      {u.board}
                      {u.variant ? ` (${u.variant})` : ""}
                      {u.dnp ? <span className="pill neutral">DNP</span> : null}
                    </td>
                    <td className="mono cell-fp" title={u.refs}>
                      {u.refs}
                    </td>
                    <td className="num">{u.qty}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
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
