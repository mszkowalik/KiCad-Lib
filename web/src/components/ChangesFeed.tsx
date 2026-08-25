import { useCallback, useEffect, useRef, useState } from "react";

import {
  errorMessage,
  isAbortError,
  listChanges,
  type ChangeKind,
  type ChangeRow,
} from "../api";
import ChangeDetail from "./ChangeDetail";
import DataTable, { type Column } from "./DataTable";
import { ErrorBanner, Spinner } from "./Ui";
import { useInfiniteScroll } from "./useInfiniteScroll";

/** Recent edits, newest first, across everything the library versions.
 *
 *  Two decisions shape it. **Rows are cheap and diffs are not**, so a row
 *  carries only what its line prints and `ChangeDetail` fetches the diff when
 *  the row is opened — there are ~18k events here and rendering a symbol costs
 *  a kicad-cli invocation. And **filtering runs on the server**, because the
 *  browser holds one page: a local filter would search a slice and then report
 *  "no rows match" about history it never loaded. */

const PAGE = 50;
const DEBOUNCE_MS = 300;

const KINDS: { key: ChangeKind; label: string }[] = [
  { key: "component", label: "Components" },
  { key: "symbol", label: "Symbols" },
  { key: "footprint", label: "Footprints" },
  { key: "skill", label: "Skills" },
  { key: "model3d", label: "3D models" },
  { key: "event", label: "Review & lifecycle" },
];

/** Absolute date plus a relative hint — "when" is usually the first question
 *  and "3 hours ago" answers it faster than a timestamp. */
function when(iso: string): string {
  const then = new Date(iso);
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days < 30 ? `${days} d ago` : then.toLocaleDateString();
}

export default function ChangesFeed() {
  const [rows, setRows] = useState<ChangeRow[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Server-side filters. `kinds` is a chip row; the other two ride in the
  // table's own filter boxes so the feed looks and works like every other list.
  const [kinds, setKinds] = useState<ChangeKind[]>([]);
  const [typed, setTyped] = useState({ name: "", actor: "" });
  const [applied, setApplied] = useState({ name: "", actor: "" });

  useEffect(() => {
    if (typed.name === applied.name && typed.actor === applied.actor) return;
    const t = window.setTimeout(() => setApplied(typed), DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [typed, applied]);

  // A filter change is a different feed: drop what is loaded and start again,
  // or the new first page would be appended under stale rows.
  const reqId = useRef(0);
  useEffect(() => {
    const ctrl = new AbortController();
    const mine = ++reqId.current;
    setBusy(true);
    setError(null);
    listChanges({ limit: PAGE, kinds, actor: applied.actor, q: applied.name }, ctrl.signal)
      .then((page) => {
        if (mine !== reqId.current) return;
        setRows(page.items);
        setCursor(page.next_cursor);
        setHasMore(page.has_more);
        setBusy(false);
      })
      .catch((err) => {
        if (isAbortError(err) || mine !== reqId.current) return;
        setError(errorMessage(err));
        setBusy(false);
      });
    return () => ctrl.abort();
  }, [kinds, applied]);

  const loadMore = useCallback(() => {
    if (busy || !hasMore || cursor === null) return;
    const mine = reqId.current;
    setBusy(true);
    listChanges({ limit: PAGE, cursor, kinds, actor: applied.actor, q: applied.name })
      .then((page) => {
        if (mine !== reqId.current) return; // the filters moved under us
        setRows((prev) => [...prev, ...page.items]);
        setCursor(page.next_cursor);
        setHasMore(page.has_more);
        setBusy(false);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(errorMessage(err));
        setBusy(false);
      });
  }, [busy, hasMore, cursor, kinds, applied]);

  const sentinel = useInfiniteScroll(loadMore, hasMore, busy);

  const toggleKind = (k: ChangeKind) =>
    setKinds((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]));

  const columns: Column<ChangeRow>[] = [
    {
      // No filter box and no sort on this column: the kind chips above ARE its
      // server-side filter, and a local box would search the loaded page only.
      // Same reasoning for Change and When below.
      key: "kind",
      label: "What",
      width: 12,
      interactive: false,
      get: (r) => r.kind,
      render: (r) => <span className={`change-kind ${r.kind}`}>{r.kind}</span>,
    },
    {
      key: "name",
      label: "Name",
      width: 34,
      serverFilter: true,
      get: (r) => r.name,
      className: "mono",
    },
    {
      key: "action",
      label: "Change",
      width: 16,
      interactive: false,
      get: (r) => r.action_label ?? r.action,
      render: (r) => (
        <>
          {r.action_label ?? r.action}
          {r.version_no !== null ? <span className="pill neutral">v{r.version_no}</span> : null}
        </>
      ),
    },
    { key: "actor", label: "By", width: 16, serverFilter: true, get: (r) => r.actor },
    {
      key: "ts",
      label: "When",
      width: 22,
      interactive: false,
      get: (r) => r.ts,
      render: (r) => <span title={new Date(r.ts).toLocaleString()}>{when(r.ts)}</span>,
    },
  ];

  return (
    <div className="page">
      <div className="toolbar">
        <nav className="subnav">
          {KINDS.map((k) => (
            <button
              key={k.key}
              type="button"
              className={"topbar-link" + (kinds.includes(k.key) ? " active" : "")}
              onClick={() => toggleKind(k.key)}
            >
              {k.label}
            </button>
          ))}
        </nav>
        {kinds.length > 0 ? (
          <button type="button" className="btn btn-sm" onClick={() => setKinds([])}>
            All kinds
          </button>
        ) : null}
      </div>

      {error !== null ? <ErrorBanner message={error} /> : null}

      <div className="table-wrap">
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.key}
          // The whole feed is already newest-first from the server, and its
          // pages are keyed on that order — re-sorting in the browser would
          // only reorder what happens to be loaded.
          serverSort
          onServerFilters={(f) => setTyped({ name: f.name ?? "", actor: f.actor ?? "" })}
          // Every loaded row is laid out: the server page IS the chunk.
          pageSize={10000}
          expand={(r) => <ChangeDetail kind={r.kind} id={r.id} />}
          empty={busy ? "Loading…" : "Nothing has changed yet."}
          footer={
            hasMore ? (
              <div ref={sentinel} className="scroll-sentinel">
                <Spinner label={`${rows.length} loaded`} />
              </div>
            ) : rows.length > 0 ? (
              <div className="scroll-sentinel">That is the whole history — {rows.length} changes.</div>
            ) : null
          }
        />
      </div>
    </div>
  );
}
