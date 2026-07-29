import { useCallback, useContext, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  approveGeometryProposal,
  approveProposal,
  approveSkillProposal,
  errorMessage,
  geometryProposalPreviewUrl,
  getProposalHistory,
  getProposals,
  isAbortError,
  rejectGeometryProposal,
  rejectProposal,
  rejectSkillProposal,
  type GeometryProposal,
  type Proposal,
  type ProposalHistoryRow,
} from "../api";
import { ProposalsBadge } from "../App";
import { useDialog } from "../components/Dialog";
import { ErrorBanner, Spinner } from "../components/Ui";

const isGeometry = (p: Proposal): p is GeometryProposal =>
  p.kind === "symbol" || p.kind === "footprint";

/** proposal_id is only unique per kind — key selections by both. */
const keyOf = (p: Proposal) => `${p.kind}-${p.proposal_id}`;

const labelOf = (p: Proposal) =>
  p.kind === "skill" ? `skill ${p.skill_name}` : `${p.kind} ${p.component_name}`;

export default function Proposals() {
  const [rows, setRows] = useState<Proposal[] | null>(null);
  const [history, setHistory] = useState<ProposalHistoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  /** Progress of a bulk approve; non-null means the whole table is busy. */
  const [bulk, setBulk] = useState<{ done: number; total: number } | null>(null);
  const { refresh: refreshBadge } = useContext(ProposalsBadge);
  const dialog = useDialog();

  const load = useCallback((signal?: AbortSignal) => {
    getProposals(signal)
      .then((list) => {
        setRows(list);
        setError(null);
        // Drop selections for proposals that are no longer pending.
        const live = new Set(list.map(keyOf));
        setSelected((prev) => new Set([...prev].filter((k) => live.has(k))));
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  }, []);

  const loadHistory = useCallback((signal?: AbortSignal) => {
    getProposalHistory(200, signal)
      .then(setHistory)
      .catch((err) => {
        // History is secondary — never let it mask the pending queue.
        if (!isAbortError(err)) setHistory([]);
      });
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    loadHistory(ctrl.signal);
    return () => ctrl.abort();
  }, [load, loadHistory]);

  /** Approves one proposal and returns its mirror warnings. Throws on failure. */
  const approveOne = async (p: Proposal): Promise<string[]> => {
    if (p.kind === "skill") {
      await approveSkillProposal(p.proposal_id);
      return [];
    }
    if (isGeometry(p)) {
      const res = await approveGeometryProposal(p.kind, p.proposal_id);
      return res.mirror_warnings ?? [];
    }
    const res = await approveProposal(p.proposal_id);
    return res.mirror_warnings ?? [];
  };

  // Approving is deliberately unconfirmed — the click IS the decision, and a
  // wrong approval is recoverable (versions are immutable; restore the previous
  // one). Rejecting still confirms: it is the one action that discards work.
  const act = async (p: Proposal, action: "approve" | "reject") => {
    if (action === "reject") {
      const confirmed = await dialog.confirm(`Reject ${labelOf(p)} v${p.version_no}?`, {
        title: "Reject proposal",
        confirmLabel: "Reject",
        tone: "danger",
      });
      if (!confirmed) return;
    }
    setBusyId(keyOf(p));
    setError(null);
    setNotice(null);
    try {
      if (action === "approve") {
        const warnings = await approveOne(p);
        if (warnings.length > 0) {
          setNotice(`Approved with mirror warnings: ${warnings.join("; ")}`);
        }
      } else if (p.kind === "skill") {
        await rejectSkillProposal(p.proposal_id);
      } else if (isGeometry(p)) {
        await rejectGeometryProposal(p.kind, p.proposal_id);
      } else {
        await rejectProposal(p.proposal_id);
      }
      load();
      loadHistory();
      refreshBadge();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  /**
   * Bulk approve, one at a time on purpose: every approval regenerates the
   * affected KiCad library + file mirror server-side, so firing them in
   * parallel would have concurrent writers on the same mirror files. A single
   * failure doesn't abort the run — it is collected and reported at the end.
   */
  const approveSelected = async () => {
    const picked = (rows ?? []).filter((p) => selected.has(keyOf(p)));
    if (picked.length === 0 || bulk !== null || busyId !== null) return;
    setError(null);
    setNotice(null);
    setBulk({ done: 0, total: picked.length });
    const warnings: string[] = [];
    const failures: string[] = [];
    for (const [i, p] of picked.entries()) {
      try {
        warnings.push(...(await approveOne(p)));
      } catch (err) {
        failures.push(`${labelOf(p)}: ${errorMessage(err)}`);
      }
      setBulk({ done: i + 1, total: picked.length });
    }
    setBulk(null);
    if (failures.length > 0) {
      setError(`${failures.length} of ${picked.length} could not be approved — ${failures.join("; ")}`);
    }
    if (warnings.length > 0) {
      setNotice(
        `Approved ${picked.length - failures.length} with mirror warnings: ${warnings.join("; ")}`,
      );
    }
    load();
    loadHistory();
    refreshBadge();
  };

  const toggleOne = (p: Proposal) =>
    setSelected((prev) => {
      const next = new Set(prev);
      const k = keyOf(p);
      if (!next.delete(k)) next.add(k);
      return next;
    });

  const allSelected = rows !== null && rows.length > 0 && selected.size === rows.length;
  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set((rows ?? []).map(keyOf)));
  const rowsBusy = bulk !== null || busyId !== null;

  return (
    <div className="main-solo">
      <div className="page">
        <h1>Proposals</h1>
        <p className="muted">
          Draft versions created by Jaravis. Nothing becomes part of the published library until
          approved here.
        </p>

        {error ? <ErrorBanner message={error} /> : null}
        {notice ? (
          <div className="banner-warn" role="status">
            {notice}
          </div>
        ) : null}

        {rows === null ? (
          <div className="block-loading">
            <Spinner label="Loading proposals" />
          </div>
        ) : rows.length === 0 ? (
          <div className="card pad">
            <p className="muted no-warnings">No pending proposals.</p>
          </div>
        ) : (
          <>
          <div className="proposals-bulk">
            <button
              type="button"
              className="btn btn-sm btn-ok"
              disabled={selected.size === 0 || rowsBusy}
              onClick={() => void approveSelected()}
            >
              {bulk !== null
                ? `Approving ${bulk.done}/${bulk.total}…`
                : `Approve selected (${selected.size})`}
            </button>
            {selected.size > 0 && bulk === null ? (
              <button type="button" className="btn btn-sm" onClick={() => setSelected(new Set())}>
                Clear selection
              </button>
            ) : null}
            <span className="muted rail-hint">
              {rows.length} pending — approving regenerates the affected library on each one.
            </span>
          </div>
          <div className="card table-wrap">
            <table className="data data-fixed proposals-table">
              <thead>
                <tr>
                  <th className="ctr">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      disabled={rowsBusy}
                      onChange={toggleAll}
                      aria-label="Select all pending proposals"
                    />
                  </th>
                  <th>Name</th>
                  <th>Kind</th>
                  <th>Version</th>
                  <th>Category</th>
                  <th>By</th>
                  <th>Comment</th>
                  <th>Created</th>
                  <th className="ctr" aria-label="Actions"></th>
                </tr>
              </thead>
              <tbody>
                {rows.flatMap((p) => {
                  const key = `${p.kind}-${p.proposal_id}`;
                  const rendered = [
                    <tr key={key}>
                      <td className="ctr">
                        <input
                          type="checkbox"
                          checked={selected.has(key)}
                          disabled={rowsBusy}
                          onChange={() => toggleOne(p)}
                          aria-label={`Select ${labelOf(p)} v${p.version_no}`}
                        />
                      </td>
                      <td>
                        <Link
                          to={
                            isGeometry(p)
                              ? `/library/templates/${p.kind}s/${p.template_id}`
                              : p.kind === "skill"
                                ? `/library/skills/${p.skill_id}`
                                : `/library/components/${p.component_id}`
                          }
                          state={{ backTo: "/proposals", showVersion: p.version_no }}
                          className="mono comp-link"
                        >
                          {p.component_name}
                        </Link>
                      </td>
                      <td>
                        {p.kind === "skill" ? (
                          <span className="pill info">skill</span>
                        ) : isGeometry(p) ? (
                          <span className={`pill ${p.is_new_component ? "warn" : "neutral"}`}>
                            {p.kind} {p.is_new_component ? "new" : "edit"}
                          </span>
                        ) : (
                          <span className={`pill ${p.is_new_component ? "warn" : "neutral"}`}>
                            {p.is_new_component ? "new" : "edit"}
                          </span>
                        )}
                      </td>
                      <td className="mono">v{p.version_no}</td>
                      <td
                        className="cell-cat"
                        title={p.kind === "component" ? p.category_path : undefined}
                      >
                        {p.kind === "component" ? p.category_path : "—"}
                      </td>
                      <td className="mono">{p.created_by ?? ""}</td>
                      <td className="cell-desc" title={p.comment ?? undefined}>
                        {p.comment ?? ""}
                      </td>
                      <td className="mono nowrap">{new Date(p.created_at).toLocaleString()}</td>
                      <td className="ctr nowrap">
                        {isGeometry(p) ? (
                          <>
                            <button
                              type="button"
                              className="btn btn-sm"
                              onClick={() => setPreviewKey(previewKey === key ? null : key)}
                            >
                              {previewKey === key ? "Hide" : "Preview"}
                            </button>{" "}
                          </>
                        ) : null}
                        <button
                          type="button"
                          className="btn btn-sm btn-ok"
                          disabled={rowsBusy}
                          onClick={() => void act(p, "approve")}
                        >
                          {busyId === keyOf(p) ? "…" : "Approve"}
                        </button>{" "}
                        <button
                          type="button"
                          className="btn btn-sm btn-danger"
                          disabled={rowsBusy}
                          onClick={() => void act(p, "reject")}
                        >
                          Reject
                        </button>
                      </td>
                    </tr>,
                  ];
                  if (isGeometry(p) && previewKey === key) {
                    rendered.push(
                      <tr key={`${key}-preview`}>
                        <td colSpan={9} className="preview-cell">
                          <div className="proposal-preview">
                            {!p.is_new_component ? (
                              <div>
                                <p className="muted panel-cap">Current (live)</p>
                                <div className="preview-fill">
                                  <img
                                    src={geometryProposalPreviewUrl(p.kind, p.proposal_id, "current")}
                                    alt={`Current ${p.component_name}`}
                                  />
                                </div>
                              </div>
                            ) : null}
                            <div>
                              <p className="muted panel-cap">Draft v{p.version_no}</p>
                              <div className="preview-fill">
                                <img
                                  src={geometryProposalPreviewUrl(p.kind, p.proposal_id, "draft")}
                                  alt={`Draft ${p.component_name}`}
                                />
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>,
                    );
                  }
                  return rendered;
                })}
              </tbody>
            </table>
          </div>
          </>
        )}

        {history && history.length > 0 ? (
          <section className="history-section">
            <h2 className="history-title">History</h2>
            <p className="muted">Approved and rejected proposals, most recent decision first.</p>
            <div className="card table-wrap">
              <table className="data data-fixed proposals-history-table">
                <thead>
                  <tr>
                    <th>Outcome</th>
                    <th>Name</th>
                    <th>Kind</th>
                    <th>Version</th>
                    <th>By</th>
                    <th>Comment</th>
                    <th>Decided</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h, i) => (
                    <tr key={`${h.kind}-${h.proposal_id ?? "x"}-${i}`}>
                      <td>
                        <span className={`pill ${h.outcome === "approved" ? "ok" : "err"}`}>
                          {h.outcome}
                        </span>
                      </td>
                      <td title={h.component_name}>
                        {h.kind === "component" && h.component_id !== null ? (
                          <Link
                            to={`/library/components/${h.component_id}`}
                            state={{ backTo: "/proposals", showVersion: h.version_no }}
                            className="mono comp-link"
                          >
                            {h.component_name}
                          </Link>
                        ) : h.kind === "skill" ? (
                          <Link to="/library/skills" className="mono comp-link">
                            {h.component_name}
                          </Link>
                        ) : (
                          <span className="mono">{h.component_name}</span>
                        )}
                      </td>
                      <td>
                        <span className={`pill ${h.kind === "skill" ? "info" : "neutral"}`}>
                          {h.kind}
                        </span>
                      </td>
                      <td className="mono">{h.version_no !== null ? `v${h.version_no}` : "—"}</td>
                      <td className="mono">{h.created_by ?? ""}</td>
                      <td title={h.comment ?? undefined}>{h.comment ?? ""}</td>
                      <td className="mono nowrap" title={`Decided by ${h.decided_by}`}>
                        {new Date(h.decided_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}
