import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  errorMessage,
  getReviewHealth,
  getReviewQueue,
  isAbortError,
  type ReviewHealth,
  type ReviewQueue,
  type ReviewQueueComponent,
  type ReviewQueueTemplate,
  type ReviewState,
} from "../api";
import { ErrorBanner, LifecyclePill, ReviewPill, SignoffPill, Spinner } from "../components/Ui";

/** The review queue: what still needs verification, what is failing its
 * machine checks, and the library-health numbers. Publishing no longer waits
 * for anybody — this page is where the review debt is worked down. */

const STATE_RANK: Record<string, number> = { failed: 0, unreviewed: 1, partial: 2, checked: 3 };

const TABS = ["components", "symbols", "footprints", "health"] as const;
type Tab = (typeof TABS)[number];

export default function Reviews() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get("tab") ?? "")
    ? (params.get("tab") as Tab)
    : "components";
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [health, setHealth] = useState<ReviewHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    getReviewQueue(signal)
      .then(setQueue)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getReviewHealth(signal)
      .then(setHealth)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const setTab = (t: Tab) => {
    const next = new URLSearchParams(params);
    next.set("tab", t);
    setParams(next, { replace: true });
  };

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <nav className="subnav">
            {TABS.map((t) => (
              <button
                key={t}
                type="button"
                className={"topbar-link" + (tab === t ? " active" : "")}
                onClick={() => setTab(t)}
              >
                {t === "health" ? "Library health" : t[0].toUpperCase() + t.slice(1)}
                {queue && t !== "health" ? (
                  <span className="badge">{needsAttention(queue, t)}</span>
                ) : null}
              </button>
            ))}
          </nav>
        </div>

        {error ? <ErrorBanner message={error} /> : null}
        {!queue ? (
          <Spinner label="Loading review states" />
        ) : tab === "components" ? (
          <ComponentsTab rows={queue.components} />
        ) : tab === "symbols" ? (
          <TemplatesTab rows={queue.symbols} kind="symbols" />
        ) : tab === "footprints" ? (
          <TemplatesTab rows={queue.footprints} kind="footprints" />
        ) : health ? (
          <HealthTab health={health} />
        ) : (
          <Spinner label="Loading health" />
        )}
      </div>
    </div>
  );
}

function needsAttention(queue: ReviewQueue, tab: Tab): number {
  if (tab === "components")
    return queue.components.filter((r) => r.review_state !== "checked").length;
  const rows = tab === "symbols" ? queue.symbols : queue.footprints;
  return rows.filter((r) => r.review_state !== "checked").length;
}

const STATE_FILTERS: (ReviewState | "all" | "attention")[] = [
  "attention",
  "all",
  "failed",
  "unreviewed",
  "partial",
  "checked",
];

function ComponentsTab({ rows }: { rows: ReviewQueueComponent[] }) {
  const [state, setState] = useState<(typeof STATE_FILTERS)[number]>("attention");
  const [usedOnly, setUsedOnly] = useState(false);
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows
      .filter((r) =>
        state === "all"
          ? true
          : state === "attention"
            ? r.review_state !== "checked" || r.signoff_state !== "signed"
            : r.review_state === state,
      )
      .filter((r) => (usedOnly ? r.used_in.length > 0 : true))
      .filter((r) => (needle ? r.name.toLowerCase().includes(needle) : true))
      .sort(
        (a, b) =>
          // used-in-a-project + unsigned first: those bite at production time
          Number(b.used_in.length > 0 && b.signoff_state !== "signed") -
            Number(a.used_in.length > 0 && a.signoff_state !== "signed") ||
          STATE_RANK[a.review_state] - STATE_RANK[b.review_state] ||
          a.name.localeCompare(b.name),
      );
  }, [rows, state, usedOnly, q]);

  return (
    <div className="card pad">
      <div className="toolbar">
        <select className="text" value={state} onChange={(e) => setState(e.target.value as never)}>
          {STATE_FILTERS.map((s) => (
            <option key={s} value={s}>
              {s === "attention" ? "needs attention" : s}
            </option>
          ))}
        </select>
        <label>
          <input type="checkbox" checked={usedOnly} onChange={(e) => setUsedOnly(e.target.checked)} /> used in
          projects only
        </label>
        <input className="search" placeholder="Filter by name…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="toolbar-total muted">{filtered.length} shown</span>
      </div>
      <div className="table-wrap">
        <table className="data data-fixed reviews-table">
          <thead>
            <tr>
              <th>Component</th>
              <th>Category</th>
              <th>Review</th>
              <th>Why</th>
              <th>Sign-off</th>
              <th>Lifecycle</th>
              <th>Used in</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.id}>
                <td title={r.name}>
                  <Link className="comp-link" to={`/library/components/${r.id}`}>
                    {r.name}
                  </Link>{" "}
                  {r.version_no ? <span className="muted mono">v{r.version_no}</span> : null}
                </td>
                <td className="cell-cat" title={r.category_path}>
                  {r.category_path}
                </td>
                <td>
                  <ReviewPill state={r.review_state} provenance={r.provenance} />
                </td>
                <td title={r.blockers.join("; ")}>{r.blockers.join("; ")}</td>
                <td>
                  <SignoffPill state={r.signoff_state} />
                </td>
                <td>
                  <LifecyclePill state={r.lifecycle} />
                </td>
                <td title={r.used_in.join(", ")}>{r.used_in.join(", ")}</td>
              </tr>
            ))}
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty">
                  Nothing matches — the library is in good shape here.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TemplatesTab({ rows, kind }: { rows: ReviewQueueTemplate[]; kind: "symbols" | "footprints" }) {
  const [state, setState] = useState<(typeof STATE_FILTERS)[number]>("attention");
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows
      .filter((r) =>
        state === "all" ? true : state === "attention" ? r.review_state !== "checked" : r.review_state === state,
      )
      .filter((r) => (needle ? r.name.toLowerCase().includes(needle) : true))
      .sort((a, b) => STATE_RANK[a.review_state] - STATE_RANK[b.review_state] || a.name.localeCompare(b.name));
  }, [rows, state, q]);

  return (
    <div className="card pad">
      <div className="toolbar">
        <select className="text" value={state} onChange={(e) => setState(e.target.value as never)}>
          {STATE_FILTERS.map((s) => (
            <option key={s} value={s}>
              {s === "attention" ? "needs attention" : s}
            </option>
          ))}
        </select>
        <input className="search" placeholder="Filter by name…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="toolbar-total muted">{filtered.length} shown</span>
      </div>
      <div className="table-wrap">
        <table className="data data-fixed reviews-template-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Review</th>
              <th>Failing</th>
              <th>Skipped</th>
              <th>Open items</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.id}>
                <td title={r.name}>
                  <Link className="comp-link" to={`/library/templates/${kind}/${r.id}`}>
                    {r.name}
                  </Link>
                </td>
                <td>
                  <ReviewPill state={r.review_state} provenance={r.provenance} />
                </td>
                <td className="num">{r.failed || ""}</td>
                <td className="num">{r.skipped || ""}</td>
                <td className="num">{r.unanswered || ""}</td>
              </tr>
            ))}
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="empty">
                  Nothing matches.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CountList({ title, counts }: { title: string; counts: Record<string, number> }) {
  return (
    <section className="card pad meta-card">
      <h3 className="card-title">{title}</h3>
      <dl className="kv">
        {Object.entries(counts)
          .sort((a, b) => b[1] - a[1])
          .map(([k, v]) => (
            <Item key={k} k={k} v={v} />
          ))}
      </dl>
    </section>
  );
}

function Item({ k, v }: { k: string; v: number }) {
  return (
    <>
      <dt>{k.replace(/_/g, " ")}</dt>
      <dd className="num">{v}</dd>
    </>
  );
}

function HealthTab({ health }: { health: ReviewHealth }) {
  return (
    <div className="edit-grid">
      <CountList title={`Review states (${health.components.total} components)`} counts={health.components.review} />
      <CountList title="Production sign-off" counts={health.components.signoff} />
      <CountList title="Lifecycle" counts={health.components.lifecycle} />
      <section className="card pad meta-card">
        <h3 className="card-title">Used in a project, not signed</h3>
        {health.used_not_signed.length === 0 ? (
          <p className="muted">None — every part on a board is signed off.</p>
        ) : (
          <ul className="val-list">
            {health.used_not_signed.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </section>
      <section className="card pad meta-card">
        <h3 className="card-title">Deprecated parts still on boards</h3>
        {health.used_deprecated.length === 0 ? (
          <p className="muted">None.</p>
        ) : (
          <ul className="val-list">
            {health.used_deprecated.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </section>
      <section className="card pad meta-card">
        <h3 className="card-title">Chronically skipped checklist items</h3>
        {health.top_skipped_items.length === 0 ? (
          <p className="muted">Nothing is being skipped.</p>
        ) : (
          <dl className="kv">
            {health.top_skipped_items.map((s) => (
              <Item key={s.key} k={s.key} v={s.count} />
            ))}
          </dl>
        )}
      </section>
    </div>
  );
}
