/** History: what changed, and the way back (decisions 0050, 0089).
 *
 *  "My changes" is open to everybody: each request you made that changed rows,
 *  with Undo. Undo always runs dry first, and names what would be written and
 *  anything that refuses it. "Everyone" is the administrator's activity log.
 */
import { useCallback, useEffect, useState } from "react";
import {
  errorMessage,
  getChangeGroup,
  isAbortError,
  listChangeGroups,
  undoChangeGroup,
  type ChangeGroup,
  type JournalChange,
} from "../api";
import { useAuth } from "../auth";
import ActivityCard from "../components/ActivityCard";
import DataTable from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import { StatChip } from "../components/FoldSection";
import { ErrorBanner, Spinner } from "../components/Ui";
import { localWhen } from "../format";
import { useLoad } from "../components/useLoad";
import PageShell from "../components/PageShell";

const PAGE = 100;

const OP_WORD: Record<JournalChange["op"], string> = { I: "added", U: "changed", D: "deleted" };

function requestText(g: ChangeGroup): string {
  const r = g.request;
  if (!r) return "—";
  return typeof r === "string" ? r : [r.method, r.path].filter(Boolean).join(" ");
}

function tablesText(g: ChangeGroup): string {
  return Object.entries(g.tables)
    .map(([t, c]) => `${t}: ${[c.inserted && `+${c.inserted}`, c.updated && `~${c.updated}`, c.deleted && `−${c.deleted}`]
      .filter(Boolean).join(" ")}`)
    .join(", ");
}

function GroupDetail({ groupKey }: { groupKey: string }) {
  const { data: rows, error } = useLoad(
    (signal) => getChangeGroup(groupKey, signal).then((d) => d.changes),
    [groupKey],
    { keep: true },
  );
  if (error) return <ErrorBanner message={error} />;
  if (!rows) return <Spinner />;
  return (
    <DataTable
      rows={rows}
      rowKey={(r) => r.id}
      columns={[
        { key: "table", label: "Table", width: 24, className: "mono", get: (r) => r.table },
        { key: "op", label: "What", width: 10, get: (r) => OP_WORD[r.op] },
        { key: "pk", label: "Row", width: 12, className: "mono", get: (r) => JSON.stringify(r.pk) },
        { key: "new", label: "Values", width: 54, className: "mono",
          get: (r) => JSON.stringify(r.op === "D" ? r.old : r.new) },
      ]}
    />
  );
}

export default function History() {
  const dialog = useDialog();
  const [rows, setRows] = useState<ChangeGroup[] | null>(null);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const ac = new AbortController();
    listChangeGroups({ limit: PAGE }, ac.signal)
      .then((r) => { setRows(r); setMore(r.length === PAGE); setError(null); })
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    return () => ac.abort();
  }, [tick]);

  const loadMore = async () => {
    const last = rows?.[rows.length - 1];
    if (!last) return;
    try {
      const page = await listChangeGroups({ before: last.last_id, limit: PAGE });
      setRows([...(rows ?? []), ...page]);
      setMore(page.length === PAGE);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const undo = async (g: ChangeGroup) => {
    let plan;
    try {
      plan = await undoChangeGroup(g.key, true);
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Undo refused" });
      return;
    }
    if (plan.refused.length) {
      await dialog.alert(plan.refused.map((r) => r.why).join("\n"), { title: "Undo refused" });
      return;
    }
    const ok = await dialog.confirm(
      `Undo “${requestText(g)}”? It writes ${plan.rows} row(s) back to what they were. The undo is a new change, so it appears in this list.`,
      { title: "Undo this change", confirmLabel: "Undo", tone: "danger" },
    );
    if (!ok) return;
    try {
      await undoChangeGroup(g.key, false);
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Undo refused" });
      return;
    }
    reload();
  };

  const undone = (rows ?? []).filter((g) => g.undone_by).length;
  return (
    <PageShell>
      <div className="toolbar">
        <h1>My changes</h1>
        <span className="toolbar-total">Each request of yours that changed rows, newest first.</span>
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      <div className="card pad">
        {!rows ? <Spinner /> : (
          <>
            <div className="stat-row">
              <StatChip n={rows.length}>{more ? "shown" : "changes"}</StatChip>
              {undone ? <StatChip n={undone}>undone</StatChip> : null}
            </div>
            <DataTable
              rows={rows}
              rowKey={(g) => g.key}
              empty="You have changed nothing yet."
              expand={(g) => <GroupDetail groupKey={g.key} />}
              columns={[
                { key: "at", label: "When", width: 15, className: "mono", get: (g) => g.at ?? "", render: (g) => localWhen(g.at) },
                { key: "req", label: "Request", width: 33, className: "mono", get: requestText },
                { key: "rows", label: "Rows", width: 6, numeric: true, get: (g) => g.rows },
                { key: "tables", label: "Tables", width: 32, className: "mono", get: tablesText },
                { key: "undo", label: "", width: 14, interactive: false, get: () => "",
                  render: (g) => (g.undone_by ? <span className="pill neutral">undone</span>
                    : g.undoes ? <span className="pill neutral">an undo</span>
                    : <button type="button" className="btn btn-sm"
                        onClick={(e) => { e.stopPropagation(); void undo(g); }}>Undo…</button>) },
              ]}
            />
            {more ? <button type="button" className="btn btn-sm" onClick={() => void loadMore()}>Load more</button> : null}
          </>
        )}
      </div>
    </PageShell>
  );
}

/** History → Everyone: the administrator's activity log. A non-admin who opens
 *  the address gets the API's refusal from inside the card. */
export function Everyone() {
  const { isAdmin } = useAuth();
  return (
    <PageShell>
      <div className="toolbar">
        <h1>Everyone</h1>
        <span className="toolbar-total">Who changed what: every write call, and every row it changed.</span>
      </div>
      {isAdmin ? <ActivityCard /> : <ErrorBanner message="This list is for administrators." />}
    </PageShell>
  );
}
