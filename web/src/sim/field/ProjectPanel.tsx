/** Attach the work on screen to a board, from inside the field solver.
 *
 *  The common way in is sideways: somebody opens the solver, works out a geometry,
 *  and only then needs somewhere to keep it. This panel is that somewhere — pick the
 *  project, the commit and the board, and the current profile (with its result, when
 *  it has been solved) is saved exactly as the project's own Stackup tab would save
 *  it. Assignments are commit-versioned: they apply from the chosen commit forward.
 */
import { useCallback, useEffect, useState } from "react";
import {
  errorMessage,
  fsAssignStackup,
  fsBoardState,
  fsSaveProfile,
  getProjects,
  getSnapshots,
  isAbortError,
  type FsBoardProfile,
  type FsBoardState,
  type ProjectInfo,
  type SnapshotInfo,
} from "../../api";
import { fmtHz } from "./model";

export interface ProjectPanelProps {
  /** The stackup the page is working on, for the "assign it" action. */
  stackupKey: string;
  /** The profile as the page holds it, ready to store. */
  profileName: string;
  profileConfig: Record<string, unknown>;
  /** Numbers only — the solved mesh is far too large to keep. */
  profileResult: Record<string, unknown> | null;
  onLoadProfile: (p: FsBoardProfile) => void;
}

export default function ProjectPanel({
  stackupKey,
  profileName,
  profileConfig,
  profileResult,
  onLoadProfile,
}: ProjectPanelProps) {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotInfo[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [snapshotId, setSnapshotId] = useState<number | null>(null);
  const [board, setBoard] = useState("");
  const [state, setState] = useState<FsBoardState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const ac = new AbortController();
    getProjects(ac.signal)
      .then(setProjects)
      .catch((e) => {
        if (!isAbortError(e)) setError(errorMessage(e));
      });
    return () => ac.abort();
  }, []);

  useEffect(() => {
    if (projectId == null) return;
    const ac = new AbortController();
    getSnapshots(projectId, ac.signal)
      .then((s) => {
        const ready = s.filter((x) => x.status === "ready");
        setSnapshots(ready);
        setSnapshotId(ready[0]?.id ?? null);
        setBoard(ready[0]?.boards?.[0]?.name ?? "");
      })
      .catch((e) => {
        if (!isAbortError(e)) setError(errorMessage(e));
      });
    return () => ac.abort();
  }, [projectId]);

  const reload = useCallback(
    (signal?: AbortSignal) => {
      if (projectId == null) return;
      fsBoardState(projectId, board, snapshotId, signal)
        .then(setState)
        .catch((e) => {
          if (!isAbortError(e)) setError(errorMessage(e));
        });
    },
    [projectId, board, snapshotId],
  );

  useEffect(() => {
    const ac = new AbortController();
    reload(ac.signal);
    return () => ac.abort();
  }, [reload]);

  const act = async (fn: () => Promise<FsBoardState>) => {
    setBusy(true);
    setError("");
    try {
      setState(await fn());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const snap = snapshots.find((s) => s.id === snapshotId);
  const boards = snap?.boards ?? [];
  const assigned = state?.revision?.stackup_key ?? "";

  return (
    <section className="card pad">
      <h2 className="card-title">Save to a project</h2>
      <div className="fs-row">
        <label className="fs-field">
          <span>Project</span>
          <select
            className="text"
            value={projectId ?? ""}
            onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">— none —</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="fs-field">
          <span>Commit</span>
          <select
            className="text"
            value={snapshotId ?? ""}
            disabled={!snapshots.length}
            onChange={(e) => setSnapshotId(e.target.value ? Number(e.target.value) : null)}
          >
            {snapshots.map((s) => (
              <option key={s.id} value={s.id}>
                {s.ref_name || s.sha.slice(0, 8)} · {s.committed_at?.slice(0, 10) ?? ""}
              </option>
            ))}
          </select>
        </label>
        <label className="fs-field">
          <span>Board</span>
          <select className="text" value={board} disabled={!boards.length} onChange={(e) => setBoard(e.target.value)}>
            {boards.map((b) => (
              <option key={b.name} value={b.name}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {projectId == null ? (
        <p className="muted fs-note">
          Pick a project to keep this work. Anything saved here applies from the chosen commit forward and shows up on
          the project's Stackup tab.
        </p>
      ) : (
        <>
          <div className="fs-row">
            <button
              type="button"
              className="btn btn-sm"
              disabled={busy || !stackupKey || assigned === stackupKey}
              onClick={() => act(() => fsAssignStackup(projectId, { stackup_key: stackupKey, board, snapshot_id: snapshotId }))}
            >
              {assigned === stackupKey ? "Stackup already assigned" : "Assign this stackup to the board"}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-accent"
              disabled={busy || !profileName}
              onClick={() =>
                act(() =>
                  fsSaveProfile(projectId, {
                    name: profileName,
                    config: profileConfig,
                    result: profileResult,
                    board,
                    snapshot_id: snapshotId,
                  }),
                )
              }
            >
              Save “{profileName}” to this board
            </button>
          </div>
          {assigned && assigned !== stackupKey ? (
            <p className="fs-note fs-warn">
              This board is assigned <b>{assigned}</b>, and the page is working on <b>{stackupKey}</b>. Saving the
              profile keeps its numbers, and they will be marked outdated against the board's stackup until you assign
              this one or recalculate.
            </p>
          ) : null}
          {error ? <p className="fs-error">{error}</p> : null}

          {state?.profiles.length ? (
            <table className="data">
              <thead>
                <tr>
                  <th>On this board</th>
                  <th>Target</th>
                  <th>Result</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {state.profiles.map((p) => {
                  const cfg = p.config as { target?: number; f?: number };
                  const res = p.result as { summary?: Record<string, number> } | null;
                  const z = res?.summary?.Z0 ?? res?.summary?.Zdiff;
                  return (
                    <tr key={p.id} className={p.outdated ? "fs-bad" : ""}>
                      <td>{p.name}</td>
                      <td>
                        {cfg.target ?? "—"} Ω{cfg.f ? ` · ${fmtHz(cfg.f)}` : ""}
                      </td>
                      <td>
                        {z != null ? `${z.toFixed(2)} Ω` : <span className="muted">not solved</span>}
                        {p.outdated ? <span className="pill warn"> outdated</span> : null}
                      </td>
                      <td>
                        <button type="button" className="btn btn-sm" onClick={() => onLoadProfile(p)}>
                          open
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <p className="muted fs-note">This board carries no impedance profiles yet.</p>
          )}
        </>
      )}
    </section>
  );
}
