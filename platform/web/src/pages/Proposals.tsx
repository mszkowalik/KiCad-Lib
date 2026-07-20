import { useCallback, useContext, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  approveGeometryProposal,
  approveProposal,
  approveSkillProposal,
  errorMessage,
  geometryProposalPreviewUrl,
  getProposals,
  isAbortError,
  rejectGeometryProposal,
  rejectProposal,
  rejectSkillProposal,
  type GeometryProposal,
  type Proposal,
} from "../api";
import { ProposalsBadge } from "../App";
import { ErrorBanner, Spinner } from "../components/Ui";

const isGeometry = (p: Proposal): p is GeometryProposal =>
  p.kind === "symbol" || p.kind === "footprint";

export default function Proposals() {
  const [rows, setRows] = useState<Proposal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const { refresh: refreshBadge } = useContext(ProposalsBadge);

  const load = useCallback((signal?: AbortSignal) => {
    getProposals(signal)
      .then((list) => {
        setRows(list);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const act = async (p: Proposal, action: "approve" | "reject") => {
    const verb = action === "approve" ? "Approve" : "Reject";
    const what = p.kind === "skill" ? `skill ${p.skill_name}` : `${p.kind} ${p.component_name}`;
    if (!window.confirm(`${verb} ${what} v${p.version_no}?`)) return;
    setBusyId(p.proposal_id);
    setError(null);
    setNotice(null);
    try {
      if (p.kind === "skill") {
        if (action === "approve") await approveSkillProposal(p.proposal_id);
        else await rejectSkillProposal(p.proposal_id);
      } else if (isGeometry(p)) {
        if (action === "approve") {
          const res = await approveGeometryProposal(p.kind, p.proposal_id);
          if (res.mirror_warnings && res.mirror_warnings.length > 0) {
            setNotice(`Approved with mirror warnings: ${res.mirror_warnings.join("; ")}`);
          }
        } else {
          await rejectGeometryProposal(p.kind, p.proposal_id);
        }
      } else if (action === "approve") {
        const res = await approveProposal(p.proposal_id);
        if (res.mirror_warnings && res.mirror_warnings.length > 0) {
          setNotice(`Approved with mirror warnings: ${res.mirror_warnings.join("; ")}`);
        }
      } else {
        await rejectProposal(p.proposal_id);
      }
      load();
      refreshBadge();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

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
          <div className="card table-wrap">
            <table className="data">
              <thead>
                <tr>
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
                      <td>
                        {isGeometry(p) ? (
                          <span className="mono">{p.component_name}</span>
                        ) : (
                          <Link
                            to={p.kind === "skill" ? "/skills" : `/components/${p.component_id}`}
                            className="mono comp-link"
                          >
                            {p.component_name}
                          </Link>
                        )}
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
                          disabled={busyId !== null}
                          onClick={() => void act(p, "approve")}
                        >
                          {busyId === p.proposal_id ? "…" : "Approve"}
                        </button>{" "}
                        <button
                          type="button"
                          className="btn btn-sm btn-danger"
                          disabled={busyId !== null}
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
                        <td colSpan={8}>
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
        )}
      </div>
    </div>
  );
}
