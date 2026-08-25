import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

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


/** One subject's changes, merged.
 *
 *  A burst of agent work writes a check, a carry and a publish against the
 *  same part within seconds, and an ungrouped feed then reads as a wall of
 *  near-identical lines with the one interesting row buried in it (user
 *  report, 2026-08-25 — `LQW15AN2N2C10D` appeared three times in fifteen
 *  rows). So the feed lists SUBJECTS, newest activity first, and a subject's
 *  individual changes live behind its unfold.
 *
 *  Grouping is by name across everything loaded, not just adjacent rows: the
 *  three copies in that report were seven rows apart. A group therefore sits
 *  at its NEWEST change and grows as older pages arrive, which is what an
 *  activity list should do. */
interface FeedGroup {
  key: string;
  name: string;
  rows: ChangeRow[];
  kind: ChangeKind;
  actors: string[];
  ts: string;
  /** Where the name links. Taken from whichever member resolved one — an
   *  event knows its parent even when the group's lead row does not. */
  href: string | null;
}

/** A version publish outranks an event: it is the change that has a diff, and
 *  it is what the row should advertise. */
const KIND_RANK: Record<ChangeKind, number> = {
  component: 0, symbol: 0, footprint: 0, skill: 0, model3d: 1, event: 2,
};

function groupRows(rows: ChangeRow[]): FeedGroup[] {
  const byName = new Map<string, ChangeRow[]>();
  const order: string[] = [];
  for (const r of rows) {
    // A nameless event has no subject to group on — keep it as its own row
    // rather than lumping every one of them together.
    const key = r.name ? `n:${r.name}` : `r:${r.key}`;
    const bucket = byName.get(key);
    if (bucket) bucket.push(r);
    else {
      byName.set(key, [r]);
      order.push(key);
    }
  }
  // `order` is first-seen order, and the feed arrives newest-first, so it is
  // already "newest activity first" without a re-sort.
  return order.map((key) => {
    const members = byName.get(key) as ChangeRow[];
    const lead = [...members].sort((a, b) => KIND_RANK[a.kind] - KIND_RANK[b.kind])[0];
    return {
      key,
      name: members[0].name,
      rows: members,
      kind: lead.kind,
      actors: [...new Set(members.map((m) => m.actor))],
      ts: members[0].ts,
      href: subjectHref(members.find((m) => m.subject_kind !== null) ?? null),
    };
  });
}

/** The page a change is about. Every kind but a 3D upload has one. */
export function subjectHref(r: ChangeRow | null): string | null {
  if (r === null || r.subject_kind === null || r.subject_id === null) return null;
  if (r.subject_kind === "component") return `/library/components/${r.subject_id}`;
  if (r.subject_kind === "skill") return `/library/skills/${r.subject_id}`;
  return `/library/templates/${r.subject_kind}s/${r.subject_id}`;
}

/** The member a group opens on: the change that carries a diff, else newest. */
function leadRow(g: FeedGroup): ChangeRow {
  return [...g.rows].sort((a, b) => KIND_RANK[a.kind] - KIND_RANK[b.kind])[0];
}

function GroupDetail({ group }: { group: FeedGroup }) {
  const [sel, setSel] = useState<string>(leadRow(group).key);
  const row = group.rows.find((r) => r.key === sel) ?? group.rows[0];
  return (
    <div className="change-detail">
      {group.rows.length > 1 ? (
        <div className="change-members">
          {group.rows.map((r) => (
            <button
              key={r.key}
              type="button"
              className={"btn btn-sm" + (r.key === sel ? " btn-primary" : "")}
              onClick={(e) => {
                e.stopPropagation();
                setSel(r.key);
              }}
              title={new Date(r.ts).toLocaleString()}
            >
              <span className={`change-kind ${r.kind}`}>{r.kind}</span>{" "}
              {r.action_label ?? r.action}
              {r.version_no !== null ? ` v${r.version_no}` : ""} · {r.actor} · {when(r.ts)}
            </button>
          ))}
        </div>
      ) : null}
      {/* One detail request at a time — the selected change, not all of them. */}
      <ChangeDetail key={row.key} kind={row.kind} id={row.id} />
    </div>
  );
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

  const groups = useMemo(() => groupRows(rows), [rows]);

  const columns: Column<FeedGroup>[] = [
    {
      // No filter box and no sort on this column: the kind chips above ARE its
      // server-side filter, and a local box would search the loaded page only.
      // Same reasoning for Change and When below.
      key: "kind",
      label: "What",
      width: 12,
      interactive: false,
      get: (g) => g.kind,
      render: (g) => <span className={`change-kind ${g.kind}`}>{g.kind}</span>,
    },
    {
      key: "name",
      label: "Name",
      width: 34,
      serverFilter: true,
      get: (g) => g.name,
      className: "mono",
      render: (g) =>
        g.href === null ? (
          <>{g.name}</>
        ) : (
          // stopPropagation: the row itself is the unfold toggle.
          <Link className="comp-link" to={g.href} onClick={(e) => e.stopPropagation()}>
            {g.name}
          </Link>
        ),
    },
    {
      key: "action",
      label: "Change",
      width: 16,
      interactive: false,
      get: (g) => (g.rows.length > 1 ? `${g.rows.length} changes` : g.rows[0].action_label ?? g.rows[0].action),
      render: (g) => {
        const lead = leadRow(g);
        return (
          <>
            {lead.action_label ?? lead.action}
            {lead.version_no !== null ? <span className="pill neutral">v{lead.version_no}</span> : null}
            {g.rows.length > 1 ? (
              <span className="badge" title="changes to this subject, newest first">
                +{g.rows.length - 1}
              </span>
            ) : null}
          </>
        );
      },
    },
    {
      key: "actor",
      label: "By",
      width: 16,
      serverFilter: true,
      get: (g) => g.actors.join(", "),
      render: (g) => (
        <span title={g.actors.join(", ")}>
          {g.actors.length <= 2 ? g.actors.join(", ") : `${g.actors[0]} +${g.actors.length - 1}`}
        </span>
      ),
    },
    {
      key: "ts",
      label: "When",
      width: 22,
      interactive: false,
      get: (g) => g.ts,
      render: (g) => <span title={new Date(g.ts).toLocaleString()}>{when(g.ts)}</span>,
    },
  ];

  return (
    <div className="page">
      <div className="toolbar">
        <nav className="chip-row" aria-label="Filter by kind">
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
          rows={groups}
          rowKey={(g) => g.key}
          // The whole feed is already newest-first from the server, and its
          // pages are keyed on that order — re-sorting in the browser would
          // only reorder what happens to be loaded.
          serverSort
          onServerFilters={(f) => setTyped({ name: f.name ?? "", actor: f.actor ?? "" })}
          // Every loaded row is laid out: the server page IS the chunk.
          pageSize={10000}
          expand={(g) => <GroupDetail group={g} />}
          empty={busy ? "Loading…" : "Nothing has changed yet."}
          footer={
            hasMore ? (
              <div ref={sentinel} className="scroll-sentinel">
                <Spinner label={`${groups.length} subjects · ${rows.length} changes loaded`} />
              </div>
            ) : rows.length > 0 ? (
              <div className="scroll-sentinel">
                That is the whole history — {rows.length} changes to {groups.length} subjects.
              </div>
            ) : null
          }
        />
      </div>
    </div>
  );
}
