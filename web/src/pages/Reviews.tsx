import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  confirmAgentChecks,
  createReviewRequests,
  errorMessage,
  getReviewHealth,
  getReviewQueue,
  isAbortError,
  type ReviewHealth,
  type ReviewKind,
  type ReviewQueue,
  type ReviewQueueComponent,
  type ReviewQueueTemplate,
  type ReviewState,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import ChangesFeed from "../components/ChangesFeed";
import { ComponentWorkbench, TemplateWorkbench } from "../components/ReviewWorkbench";
import { ErrorBanner, LifecyclePill, ReviewPill, SignoffPill, Spinner } from "../components/Ui";

/** The review queue: what still needs verification, ranked by LEVERAGE — a
 * failed symbol pinning 30 components outranks a failed one pinning none —
 * with an inline workbench so a check never needs a page change, and an agent
 * worklist so the debt can be burned down without touching every part by
 * hand. Publishing waits for nobody; this page is where the debt is paid. */

const STATE_RANK: Record<string, number> = { failed: 0, unreviewed: 1, partial: 2, checked: 3 };

const TABS = ["changes", "components", "symbols", "footprints", "flagged", "health"] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = {
  changes: "Recent changes",
  components: "Components",
  symbols: "Symbols",
  footprints: "Footprints",
  flagged: "Flagged",
  health: "Library health",
};

export default function Reviews() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get("tab") ?? "")
    ? (params.get("tab") as Tab)
    : "components";
  const snapshotId = Number(params.get("snapshot")) || undefined;
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [health, setHealth] = useState<ReviewHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dialog = useDialog();

  const load = useCallback(
    (signal?: AbortSignal) => {
      getReviewQueue(signal, snapshotId)
        .then(setQueue)
        .catch((err) => {
          if (!isAbortError(err)) setError(errorMessage(err));
        });
      getReviewHealth(signal)
        .then(setHealth)
        .catch((err) => {
          if (!isAbortError(err)) setError(errorMessage(err));
        });
    },
    [snapshotId],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  // Pushing from KiCad changes this page's data behind its back, and coming
  // back to the browser is exactly when it is read. Refetch on focus so the
  // queue is never quietly a few minutes stale — with a manual button for the
  // times the answer still looks wrong.
  useEffect(() => {
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);

  const setTab = (t: Tab) => {
    const next = new URLSearchParams(params);
    next.set("tab", t);
    setParams(next, { replace: true });
  };

  const confirmAgent = async () => {
    const ok = await dialog.confirm(
      "Write a human confirmation on every subject the agent verified in full? " +
        "Partial, failed and already-confirmed subjects are untouched.",
      { title: "Confirm agent checks", confirmLabel: "Confirm all", tone: "ok" },
    );
    if (!ok) return;
    setBusy(true);
    try {
      const res = await confirmAgentChecks();
      setNotice(
        res.total === 0
          ? "Nothing to confirm — no subject is agent-checked in full."
          : `Confirmed ${res.total}: ` +
            (["component", "symbol", "footprint"] as ReviewKind[])
              .filter((k) => res.confirmed[k].length)
              .map((k) => `${res.confirmed[k].length} ${k}(s)`)
              .join(", "),
      );
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="main-solo">
      <div className="page">
        {queue?.scope ? (
          <div className="banner-warn" role="status">
            Scoped to <strong>{queue.scope.project}</strong> @{" "}
            <span className="mono">{queue.scope.sha}</span> — {queue.scope.components}{" "}
            component(s) on this BOM, and only the drawings they pin.{" "}
            <Link to="/reviews">Show the whole library</Link>
          </div>
        ) : null}
        <div className="toolbar">
          <nav className="subnav">
            {TABS.map((t) => (
              <button
                key={t}
                type="button"
                className={"topbar-link" + (tab === t ? " active" : "")}
                onClick={() => setTab(t)}
              >
                {TAB_LABEL[t]}
                {queue && (t === "components" || t === "symbols" || t === "footprints") ? (
                  <span className="badge">{needsAttention(queue, t)}</span>
                ) : health && t === "flagged" ? (
                  <span className="badge">{health.flagged.length}</span>
                ) : null}
              </button>
            ))}
          </nav>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              setNotice(null);
              load();
            }}
            title="Refetch the queue — the page also refreshes whenever you come back to this window"
          >
            Refresh
          </button>
          <button
            type="button"
            className="btn btn-sm"
            disabled={busy}
            onClick={() => void confirmAgent()}
            title="One human confirmation over every fully agent-checked subject"
          >
            Confirm agent checks
          </button>
        </div>

        {error ? <ErrorBanner message={error} /> : null}
        {notice ? (
          <div className="banner-ok" role="status">
            {notice}
          </div>
        ) : null}
        {tab === "changes" ? (
          // Its own data, its own paging — it must not wait on the queue.
          <ChangesFeed />
        ) : !queue ? (
          <Spinner label="Loading review states" />
        ) : tab === "components" ? (
          <ComponentsTab rows={queue.components} onChanged={() => load()} />
        ) : tab === "symbols" ? (
          <TemplatesTab rows={queue.symbols} kind="symbols" onChanged={() => load()} />
        ) : tab === "footprints" ? (
          <TemplatesTab rows={queue.footprints} kind="footprints" onChanged={() => load()} />
        ) : tab === "flagged" && health ? (
          <FlaggedTab health={health} />
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

/** Queue rows for the agent: a small "→ agent" per row plus "queue shown". */
function useAgentQueue(onChanged: () => void) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const queueItems = async (items: { kind: ReviewKind; id: number }[]) => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await createReviewRequests(items);
      setMessage(
        `Queued ${res.added} for the agent (${res.open_total} open` +
          (res.already_queued_or_unpublished ? `, ${res.already_queued_or_unpublished} already queued` : "") +
          "). Ask the agent to run its review worklist.",
      );
      onChanged();
    } catch (err) {
      setMessage(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return { busy, message, queueItems };
}

function ComponentsTab({
  rows,
  onChanged,
}: {
  rows: ReviewQueueComponent[];
  onChanged: () => void;
}) {
  const [state, setState] = useState<(typeof STATE_FILTERS)[number]>("attention");
  const [usedOnly, setUsedOnly] = useState(false);
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const agent = useAgentQueue(onChanged);

  // The state select, the used-only toggle and the name box stay in the
  // toolbar — they are the queue's own vocabulary. Column sorting, per-column
  // filtering and chunked rendering come from DataTable, so this table behaves
  // like every other list in the platform.
  const [visible, setVisible] = useState<ReviewQueueComponent[]>([]);
  const preFiltered = useMemo(
    () =>
      rows
        .filter((r) =>
          state === "all"
            ? true
            : state === "attention"
              ? r.review_state !== "checked" || r.signoff_state !== "signed"
              : r.review_state === state,
        )
        .filter((r) => (usedOnly ? r.used_in.length > 0 : true))
        .filter((r) => (q.trim() ? r.name.toLowerCase().includes(q.trim().toLowerCase()) : true)),
    [rows, state, usedOnly, q],
  );

  const openIndex = visible.findIndex((r) => r.id === openId);
  const step = (by: number) => {
    const next = visible[openIndex + by];
    if (next) setOpenId(next.id);
  };

  const cols: Column<ReviewQueueComponent>[] = [
    {
      key: "name",
      label: "Component",
      width: 26,
      get: (r) => r.name,
      render: (r) => (
        <>
          <Link
            className="comp-link"
            to={`/library/components/${r.id}`}
            onClick={(e) => e.stopPropagation()}
          >
            {r.name}
          </Link>{" "}
          {r.version_no ? <span className="muted mono">v{r.version_no}</span> : null}
          {r.agent_requested ? (
            <span className="badge" title="queued for agent verification">
              → agent
            </span>
          ) : null}
        </>
      ),
    },
    { key: "category", label: "Category", width: 18, className: "cell-cat", get: (r) => r.category_path },
    {
      key: "review",
      label: "Review",
      width: 10,
      // Worst first — sorting this column means "what still needs looking at".
      get: (r) => r.review_state,
      sortValue: (r) => STATE_RANK[r.review_state] ?? 9,
      render: (r) => <ReviewPill state={r.review_state} provenance={r.provenance} />,
    },
    { key: "why", label: "Why", width: 20, get: (r) => r.blockers.join("; ") },
    {
      key: "signoff",
      label: "Sign-off",
      width: 9,
      get: (r) => r.signoff_state,
      render: (r) => <SignoffPill state={r.signoff_state} />,
    },
    {
      key: "lifecycle",
      label: "Lifecycle",
      width: 8,
      get: (r) => r.lifecycle,
      render: (r) => <LifecyclePill state={r.lifecycle} />,
    },
    { key: "used_in", label: "Used in", width: 9, get: (r) => r.used_in.join(", ") },
  ];

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
        <span className="toolbar-total muted">{visible.length} shown</span>
        <button
          type="button"
          className="btn btn-sm"
          disabled={agent.busy || visible.length === 0}
          title="Queue every shown, not-yet-checked row for the agent to verify"
          onClick={() =>
            void agent.queueItems(
              visible
                .filter((r) => r.review_state !== "checked" && !r.agent_requested)
                .map((r) => ({ kind: "component" as const, id: r.id })),
            )
          }
        >
          Queue shown → agent
        </button>
      </div>
      {agent.message ? <p className="muted">{agent.message}</p> : null}
      <div className="table-wrap">
        <DataTable
          columns={cols}
          rows={preFiltered}
          rowKey={(r) => r.id}
          persistKey="review-components"
          defaultSort={{ key: "review", dir: "asc" }}
          // Used in a project AND unsigned sorts above everything: those are
          // the ones that bite at production time.
          group={(r) => (r.used_in.length > 0 && r.signoff_state !== "signed" ? 0 : 1)}
          onVisibleChange={setVisible}
          openKey={openId}
          onOpenChange={(k) => setOpenId(k === null ? null : Number(k))}
          expand={(r) => (
            <BenchFrame
              onPrev={openIndex > 0 ? () => step(-1) : undefined}
              onNext={openIndex >= 0 && openIndex < visible.length - 1 ? () => step(1) : undefined}
              onClose={() => setOpenId(null)}
            >
              <ComponentWorkbench compId={r.id} onChanged={onChanged} />
            </BenchFrame>
          )}
          empty="Nothing matches — the library is in good shape here."
        />
      </div>
    </div>
  );
}

function TemplatesTab({
  rows,
  kind,
  onChanged,
}: {
  rows: ReviewQueueTemplate[];
  kind: "symbols" | "footprints";
  onChanged: () => void;
}) {
  const [state, setState] = useState<(typeof STATE_FILTERS)[number]>("attention");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const agent = useAgentQueue(onChanged);
  const oneKind: ReviewKind = kind === "symbols" ? "symbol" : "footprint";

  const [visible, setVisible] = useState<ReviewQueueTemplate[]>([]);
  const preFiltered = useMemo(
    () =>
      rows
        .filter((r) =>
          state === "all"
            ? true
            : state === "attention"
              ? r.review_state !== "checked"
              : r.review_state === state,
        )
        .filter((r) => (q.trim() ? r.name.toLowerCase().includes(q.trim().toLowerCase()) : true)),
    [rows, state, q],
  );

  const unblocked = visible
    .filter((r) => r.review_state !== "checked")
    .reduce((n, r) => n + r.used_by, 0);
  const openIndex = visible.findIndex((r) => r.id === openId);
  const step = (by: number) => {
    const next = visible[openIndex + by];
    if (next) setOpenId(next.id);
  };

  const cols: Column<ReviewQueueTemplate>[] = [
    {
      key: "name",
      label: "Name",
      width: 46,
      get: (r) => r.name,
      render: (r) => (
        <>
          <Link
            className="comp-link"
            to={`/library/templates/${kind}/${r.id}`}
            onClick={(e) => e.stopPropagation()}
          >
            {r.name}
          </Link>
          {r.agent_requested ? (
            <span className="badge" title="queued for agent verification">
              → agent
            </span>
          ) : null}
        </>
      ),
    },
    {
      key: "review",
      label: "Review",
      width: 14,
      get: (r) => r.review_state,
      sortValue: (r) => STATE_RANK[r.review_state] ?? 9,
      render: (r) => <ReviewPill state={r.review_state} provenance={r.provenance} />,
    },
    {
      key: "used_by",
      label: "Unblocks",
      width: 10,
      numeric: true,
      get: (r) => r.used_by || "",
      title: () => "Live components pinning this drawing — what checking it unblocks",
    },
    { key: "failed", label: "Failing", width: 10, numeric: true, get: (r) => r.failed || "" },
    { key: "skipped", label: "Skipped", width: 10, numeric: true, get: (r) => r.skipped || "" },
    { key: "unanswered", label: "Open items", width: 10, numeric: true, get: (r) => r.unanswered || "" },
  ];

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
        <span className="toolbar-total muted">
          {visible.length} shown{unblocked ? ` — checking them unblocks ${unblocked} component pin(s)` : ""}
        </span>
        <button
          type="button"
          className="btn btn-sm"
          disabled={agent.busy || visible.length === 0}
          title="Queue every shown, not-yet-checked row for the agent to verify"
          onClick={() =>
            void agent.queueItems(
              visible
                .filter((r) => r.review_state !== "checked" && !r.agent_requested)
                .map((r) => ({ kind: oneKind, id: r.id })),
            )
          }
        >
          Queue shown → agent
        </button>
      </div>
      {agent.message ? <p className="muted">{agent.message}</p> : null}
      <div className="table-wrap">
        <DataTable
          columns={cols}
          rows={preFiltered}
          rowKey={(r) => r.id}
          persistKey={`review-${kind}`}
          // Leverage first: a failed drawing pinning 30 parts IS the job.
          defaultSort={{ key: "used_by", dir: "desc" }}
          group={(r) => STATE_RANK[r.review_state] ?? 9}
          onVisibleChange={setVisible}
          openKey={openId}
          onOpenChange={(k) => setOpenId(k === null ? null : Number(k))}
          expand={(r) => (
            <BenchFrame
              onPrev={openIndex > 0 ? () => step(-1) : undefined}
              onNext={openIndex >= 0 && openIndex < visible.length - 1 ? () => step(1) : undefined}
              onClose={() => setOpenId(null)}
            >
              <TemplateWorkbench
                kind={oneKind}
                id={r.id}
                name={r.name}
                versionId={r.version_id}
                onChanged={onChanged}
              />
            </BenchFrame>
          )}
          empty="Nothing matches."
        />
      </div>
    </div>
  );
}

function BenchFrame({
  children,
  onPrev,
  onNext,
  onClose,
}: {
  children: React.ReactNode;
  onPrev?: () => void;
  onNext?: () => void;
  onClose: () => void;
}) {
  return (
    <div>
      <div className="btn-row bench-nav">
        <button type="button" className="btn btn-sm" disabled={!onPrev} onClick={onPrev}>
          ← Prev
        </button>
        <button type="button" className="btn btn-sm" disabled={!onNext} onClick={onNext}>
          Next →
        </button>
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Close
        </button>
      </div>
      {children}
    </div>
  );
}

/** The known-defects worklist: every flagged item on a current version,
 *  groupable by checklist key so systemic problems read as one job. A flag
 *  disappears from here the moment a later record clears or fixes it. */
function FlaggedTab({ health }: { health: ReviewHealth }) {
  const [groupByKey, setGroupByKey] = useState(true);
  const [q, setQ] = useState("");
  const flagged = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return health.flagged.filter(
      (f) =>
        !needle ||
        f.name.toLowerCase().includes(needle) ||
        f.key.toLowerCase().includes(needle) ||
        (f.note ?? "").toLowerCase().includes(needle),
    );
  }, [health.flagged, q]);

  const groups = useMemo(() => {
    const by: Record<string, typeof flagged> = {};
    for (const f of flagged) (by[groupByKey ? f.key : f.kind] ??= []).push(f);
    return Object.entries(by).sort((a, b) => b[1].length - a[1].length);
  }, [flagged, groupByKey]);

  return (
    <div className="card pad">
      <div className="toolbar">
        <label>
          <input type="checkbox" checked={groupByKey} onChange={(e) => setGroupByKey(e.target.checked)} /> group
          by checklist item
        </label>
        <input className="search" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="toolbar-total muted">{flagged.length} known defect(s)</span>
      </div>
      {flagged.length === 0 ? (
        <p className="muted">Nothing is flagged — no known defects awaiting a fix.</p>
      ) : (
        groups.map(([label, items]) => (
          <section key={label}>
            <h3 className="card-title">
              <span className="mono">{label}</span> <span className="muted">({items.length})</span>
            </h3>
            <ul className="notes-list">
              {items.map((f, i) => (
                <li key={`${f.kind}-${f.id}-${f.key}-${i}`} className="note">
                  <div className="note-head">
                    <Link
                      className="comp-link"
                      to={
                        f.kind === "component"
                          ? `/library/components/${f.id}`
                          : `/library/templates/${f.kind}s/${f.id}`
                      }
                    >
                      {f.name}
                    </Link>{" "}
                    {groupByKey ? (
                      <span className="pill neutral">{f.kind}</span>
                    ) : (
                      <span className="mono muted">{f.key}</span>
                    )}
                  </div>
                  <p className="muted">
                    {f.note ?? ""}{" "}
                    <span className="dim">
                      — {f.actor_type} · {f.actor}
                    </span>
                  </p>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
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
      {(["footprint", "symbol", "component"] as ReviewKind[]).map((kind) =>
        health.failing_keys[kind]?.length ? (
          <section key={kind} className="card pad meta-card">
            <h3 className="card-title">Failing {kind} checks, by item</h3>
            <p className="muted">One systemic fix clears a whole row.</p>
            <dl className="kv">
              {health.failing_keys[kind].map((f) => (
                <Item key={f.key} k={f.key} v={f.count} />
              ))}
            </dl>
          </section>
        ) : null,
      )}
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
      {health.skip_reasons.length ? (
        <section className="card pad meta-card">
          <h3 className="card-title">Why items are skipped</h3>
          <p className="muted">
            A reason names the fix — "html datasheet" means: archive the real PDF, re-verify.
          </p>
          <dl className="kv">
            {health.skip_reasons.map((s) => (
              <Item key={s.reason} k={s.reason} v={s.count} />
            ))}
          </dl>
        </section>
      ) : null}
    </div>
  );
}
