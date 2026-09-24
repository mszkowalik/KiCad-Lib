/** Admin → Activity: who changed what, across every user (decision 0050).
 *
 *  ONE log — `audit_log` — carrying three kinds of row: a `request` for every
 *  write call, the `event` an endpoint wrote itself, and a `row.*` for every
 *  database row a request changed. The list defaults to requests and events;
 *  the row changes are what unfolding a request shows, because one invoice
 *  save writes a dozen of them.
 *
 *  Server-paged, newest first, keyset on the row id — the same shape as the
 *  Changes feed (`ChangesFeed.tsx`), for the same reasons: the log grows while
 *  it is read, and a local filter would only search the loaded page.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  errorMessage,
  getActivityRequest,
  isAbortError,
  listActivity,
  type ActivityKind,
  type ActivityRow,
  type ActivityWriteBatch,
} from "../api";
import { KeyValueDiff } from "./ChangeDetail";
import { when } from "./ChangesFeed";
import DataTable, { type Column } from "./DataTable";
import { ErrorBanner, Spinner } from "./Ui";
import { useInfiniteScroll } from "./useInfiniteScroll";

const PAGE = 100;
const DEBOUNCE_MS = 300;

const KINDS: { key: ActivityKind; label: string }[] = [
  { key: "request", label: "Requests" },
  { key: "event", label: "Events" },
  { key: "row", label: "Row changes" },
];

type Details = Record<string, unknown>;

/** No chip on means every kind, not an empty log. */
const effective = (kinds: ActivityKind[]): ActivityKind[] => (kinds.length ? kinds : KINDS.map((k) => k.key));

function asDetails(d: unknown): Details {
  return d !== null && typeof d === "object" && !Array.isArray(d) ? (d as Details) : {};
}

/** One stored value as text. A long value was stored as its length and
 *  digest (`services/tracking.py`), and says so rather than printing JSON. */
function fmt(v: unknown): string | undefined {
  if (v === null || v === undefined) return undefined;
  if (typeof v === "object" && !Array.isArray(v)) {
    const o = v as Details;
    if (typeof o.len === "number" && typeof o.sha256 === "string" && Object.keys(o).length === 2) {
      return `${o.len} chars · sha256 ${o.sha256.slice(0, 12)}…`;
    }
  }
  return typeof v === "string" ? v : JSON.stringify(v);
}

function who(r: ActivityRow): string {
  // A robot actor ("jaravis", "review") keeps its label; the person who set it
  // going is shown beside it.
  if (!r.user_display) return r.actor;
  return r.actor === r.user_display ? r.actor : `${r.actor} · ${r.user_display}`;
}

function what(r: ActivityRow): string {
  const d = asDetails(r.details);
  if (r.kind === "request") return `${String(d.method ?? "")} ${String(d.path ?? r.entity_id ?? "")}`;
  if (r.kind === "row") return `${r.action.slice(4)} ${r.entity_type} #${r.entity_id ?? ""}`;
  return `${r.action} · ${r.entity_type} ${r.entity_id ?? ""}`.trim();
}

function statusPill(status: unknown) {
  if (typeof status !== "number") return <span className="pill neutral">no answer</span>;
  const tone = status < 400 ? "ok" : status < 500 ? "warn" : "err";
  return <span className={`pill ${tone}`}>{status}</span>;
}

function result(r: ActivityRow) {
  if (r.kind !== "request") return null;
  const d = asDetails(r.details);
  const c = r.counts ?? { rows: 0, events: 0 };
  const parts = [
    c.rows ? `${c.rows} row${c.rows === 1 ? "" : "s"}` : "",
    c.events ? `${c.events} event${c.events === 1 ? "" : "s"}` : "",
  ].filter(Boolean);
  return (
    <>
      {statusPill(d.status)} <span className="muted">{parts.length ? parts.join(" · ") : "no change"}</span>
    </>
  );
}

/** A row's details as Key / Before / After. */
function DetailsTable({ row }: { row: ActivityRow }) {
  const d = asDetails(row.details);
  const keys = Object.keys(d).sort();
  if (keys.length === 0) return <p className="dim">No details recorded.</p>;
  const rows = keys.map((k) => {
    const v = d[k];
    if (row.action === "row.update" && Array.isArray(v) && v.length === 2) {
      return { key: k, before: fmt(v[0]), after: fmt(v[1]) };
    }
    if (row.action === "row.delete") return { key: k, before: fmt(v) };
    return { key: k, after: fmt(v) };
  });
  return <KeyValueDiff rows={rows} />;
}

/** Everything the row's request wrote, fetched only while the row is open. */
function RequestDetail({ row }: { row: ActivityRow }) {
  const [entries, setEntries] = useState<ActivityRow[] | null>(null);
  const [batches, setBatches] = useState<ActivityWriteBatch[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!row.request_id) return;
    const ctrl = new AbortController();
    getActivityRequest(row.request_id, ctrl.signal)
      .then((d) => {
        setEntries(d.rows);
        setBatches(d.write_batches);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [row.request_id]);

  // Written outside a request (a background job): only its own details exist.
  if (!row.request_id) {
    return (
      <div className="change-detail">
        <DetailsTable row={row} />
      </div>
    );
  }
  if (error !== null) return <ErrorBanner message={error} />;
  if (entries === null) return <Spinner label="loading the request" />;

  return (
    <div className="change-detail">
      {batches.map((b) => (
        // The undoable half of the same request lives in the Write log.
        <p key={b.id} className="muted">
          Write batch <span className="mono">#{b.id}</span> ({b.kind}
          {b.source_ref ? ` ${b.source_ref}` : ""})
          {b.reversed_at ? `, reversed by #${b.reversed_by_batch_id}` : ""} —{" "}
          <Link className="comp-link" to="/production/writes">
            undo it in Production → Write log
          </Link>
        </p>
      ))}
      {entries.map((e) => (
        <div key={e.id}>
          <div className="change-section-title">
            {e.kind === "request" ? "Request" : what(e)} · {who(e)} ·{" "}
            <span title={new Date(e.ts).toLocaleString()}>{new Date(e.ts).toLocaleTimeString()}</span>
          </div>
          <DetailsTable row={e} />
        </div>
      ))}
    </div>
  );
}

export default function ActivityCard() {
  // `?request=<id>` narrows the list to one request — the Write log links here.
  const [searchParams, setSearchParams] = useSearchParams();
  const requestId = searchParams.get("request") ?? "";
  const [rows, setRows] = useState<ActivityRow[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [kinds, setKinds] = useState<ActivityKind[]>(["request", "event"]);
  const [typed, setTyped] = useState({ who: "", q: "" });
  const [applied, setApplied] = useState({ who: "", q: "" });

  useEffect(() => {
    if (typed.who === applied.who && typed.q === applied.q) return;
    const t = window.setTimeout(() => setApplied(typed), DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [typed, applied]);

  // A filter change is a different list: drop what is loaded and start again.
  const reqId = useRef(0);
  useEffect(() => {
    const ctrl = new AbortController();
    const mine = ++reqId.current;
    setBusy(true);
    setError(null);
    listActivity(
      // One request shows every kind it wrote, whatever chips are on.
      { kinds: requestId ? KINDS.map((k) => k.key) : effective(kinds), who: applied.who, q: applied.q,
        requestId, limit: PAGE },
      ctrl.signal,
    )
      .then((page) => {
        if (mine !== reqId.current) return;
        setRows(page.rows);
        setNext(page.next_before_id);
        setBusy(false);
      })
      .catch((err) => {
        if (isAbortError(err) || mine !== reqId.current) return;
        setError(errorMessage(err));
        setBusy(false);
      });
    return () => ctrl.abort();
  }, [kinds, applied, requestId]);

  const loadMore = useCallback(() => {
    if (busy || next === null) return;
    const mine = reqId.current;
    setBusy(true);
    listActivity({
      kinds: requestId ? KINDS.map((k) => k.key) : effective(kinds),
      who: applied.who,
      q: applied.q,
      requestId,
      beforeId: next,
      limit: PAGE,
    })
      .then((page) => {
        if (mine !== reqId.current) return; // the filters moved under us
        setRows((prev) => [...prev, ...page.rows]);
        setNext(page.next_before_id);
        setBusy(false);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(errorMessage(err));
        setBusy(false);
      });
  }, [busy, next, kinds, applied, requestId]);

  const sentinel = useInfiniteScroll(loadMore, next !== null, busy);

  const toggleKind = (k: ActivityKind) =>
    setKinds((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]));

  const columns: Column<ActivityRow>[] = [
    {
      key: "ts",
      label: "When",
      width: 12,
      interactive: false,
      get: (r) => r.ts,
      title: (r) => new Date(r.ts).toLocaleString(),
      render: (r) => when(r.ts),
    },
    {
      key: "who",
      label: "Who",
      width: 18,
      serverFilter: true,
      get: (r) => who(r),
    },
    {
      key: "kind",
      label: "Kind",
      width: 9,
      interactive: false,
      get: (r) => r.kind,
      render: (r) => <span className="pill neutral">{r.kind}</span>,
    },
    {
      key: "q",
      label: "What",
      width: 41,
      serverFilter: true,
      className: "mono",
      get: (r) => what(r),
    },
    {
      key: "result",
      label: "Result",
      width: 20,
      interactive: false,
      get: (r) => (r.kind === "request" ? String(asDetails(r.details).status ?? "") : ""),
      render: (r) => result(r),
    },
  ];

  return (
    <div className="card pad">
      {requestId ? (
        <div className="toolbar">
          <span className="muted">
            One request: <span className="mono">{requestId}</span>
          </span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setSearchParams({ tab: "activity" }, { replace: true })}
          >
            Show all activity
          </button>
        </div>
      ) : null}
      {requestId ? null : (
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
        </div>
      )}

      {error !== null ? <ErrorBanner message={error} /> : null}

      <div className="table-wrap">
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.id}
          // Newest first from the server, paged on that order.
          serverSort
          onServerFilters={(f) => setTyped({ who: f.who ?? "", q: f.q ?? "" })}
          pageSize={10000}
          expand={(r) => <RequestDetail row={r} />}
          empty={busy ? "Loading…" : "Nothing recorded."}
          footer={
            next !== null ? (
              <div ref={sentinel} className="scroll-sentinel">
                <Spinner label={`${rows.length} loaded`} />
              </div>
            ) : null
          }
        />
      </div>
    </div>
  );
}
