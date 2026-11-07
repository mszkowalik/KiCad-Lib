/** What was changed on one record, by whom, newest first (decision 0089).
 *
 *  The rows are what the database trigger recorded, so they cover every route,
 *  the cascades Postgres runs itself and the work of agents. It starts folded and
 *  asks the server only when it opens: most readers of a record never want this,
 *  and each page that holds it already makes enough requests.
 *
 *  A change is undone on History, per request, because one request may have
 *  changed many rows. This card only reads.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, getRowHistory, isAbortError, type RowHistoryEntry } from "../api";
import { useAuth } from "../auth";
import DataTable, { type Column } from "./DataTable";
import { localWhen } from "../format";
import FoldSection from "./FoldSection";
import { ErrorBanner, Spinner } from "./Ui";

const OP_WORD: Record<RowHistoryEntry["op"], string> = { I: "added", U: "changed", D: "deleted" };

/** The server's page size (`row_changes.row_history`). */
const SERVER_LIMIT = 50;

/** A stored value in words. A long new value is kept only as its hash, so the
 *  platform can compare it and cannot print it. */
function valueText(v: unknown): string {
  if (v === null || v === undefined || v === "") return "empty";
  if (typeof v === "object" && "$md5" in (v as object)) return "a long value (not kept)";
  return typeof v === "string" ? v : JSON.stringify(v);
}

interface FieldChange { field: string; before: string; after: string }

/** One line per column the change names. An update holds only those; an insert
 *  and a delete hold the whole row. */
function fieldsOf(r: RowHistoryEntry): FieldChange[] {
  const keys = new Set([...Object.keys(r.old ?? {}), ...Object.keys(r.new ?? {})]);
  return [...keys].sort().map((field) => ({
    field,
    before: r.old && field in r.old ? valueText(r.old[field]) : "",
    after: r.new && field in r.new ? valueText(r.new[field]) : "",
  }));
}

/** What the row says on its one line: the columns an update changed. An insert
 *  or a delete would name every column, which says nothing. */
function summary(r: RowHistoryEntry): string {
  if (r.op === "U") return Object.keys(r.new ?? {}).sort().join(", ");
  return r.op === "I" ? "The record was added." : "The record was deleted.";
}

const FIELD_COLUMNS: Column<FieldChange>[] = [
  { key: "field", label: "Field", width: 24, className: "mono", get: (f) => f.field },
  { key: "before", label: "Before", width: 38, get: (f) => f.before, title: (f) => f.before },
  { key: "after", label: "After", width: 38, get: (f) => f.after, title: (f) => f.after },
];

/** The card sits in a narrow column on a component, so the date and the word take
 *  a length, and the two free texts share what is left. */
const COLUMNS: Column<RowHistoryEntry>[] = [
  { key: "at", label: "When", width: "162px", className: "mono", get: (r) => r.at, render: (r) => localWhen(r.at) },
  { key: "actor", label: "Who", width: 45, get: (r) => `${r.actor || "nobody named"} (${r.client})`,
    title: (r) => `${r.actor || "nobody named"}, through ${r.client}` },
  { key: "op", label: "What", width: "92px", get: (r) => OP_WORD[r.op] },
  { key: "fields", label: "Fields", width: 55, get: summary, title: summary },
];

function ChangeRows({ table, id, onCount }: {
  table: string; id: number; onCount: (n: number) => void;
}) {
  const { isAdmin } = useAuth();
  const [rows, setRows] = useState<RowHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    setRows(null);
    setError(null);
    getRowHistory(table, id, ac.signal)
      .then((r) => { setRows(r); onCount(r.length); })
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    return () => ac.abort();
  }, [table, id, onCount]);
  if (error) return <ErrorBanner message={error} />;
  if (!rows) return <Spinner label="Loading changes" />;
  return (
    <>
      <DataTable
        rows={rows}
        rowKey={(r) => r.id}
        columns={COLUMNS}
        defaultSort={{ key: "at", dir: "desc" }}
        empty="No change of this record is recorded."
        expand={(r) => (
          <DataTable rows={fieldsOf(r)} rowKey={(f) => f.field} columns={FIELD_COLUMNS} empty="No field recorded." />
        )}
      />
      <p className="muted dim">
        {rows.length >= SERVER_LIMIT ? `This is the newest ${SERVER_LIMIT}. ` : ""}
        {isAdmin ? "" : "You see only the changes you made. "}
        To undo a change, open <Link to="/history">History</Link>.
      </p>
    </>
  );
}

export default function RowChangesCard({ table, id, bare }: {
  /** the real table name, as `row_changes.table_name` holds it */
  table: string;
  id: number;
  /** no card of its own: inside another card */
  bare?: boolean;
}) {
  const [count, setCount] = useState<number | null>(null);
  // The same card can show another record: a link from one component to the next.
  useEffect(() => setCount(null), [table, id]);
  // `limit={-1}` keeps the toggle after the count arrives, so a short list can
  // still be closed again.
  return (
    <FoldSection title="Changes" count={count} limit={-1} bare={bare}>
      <ChangeRows table={table} id={id} onCount={setCount} />
    </FoldSection>
  );
}
