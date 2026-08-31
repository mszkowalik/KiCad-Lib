/** A board's stackup and its impedance profiles, at one commit.
 *
 *  Both are commit-versioned like the manual cost data: what you assign here applies
 *  from this commit forward and travels with later commits until somebody changes
 *  it. Changing the stackup keeps every profile and its numbers — results computed
 *  against the previous stackup are marked outdated rather than thrown away.
 */
import { useCallback, useEffect, useState } from "react";
import {
  errorMessage,
  fsAssignStackup,
  fsBoardState,
  fsDeleteProfile,
  fsStackups,
  isAbortError,
  type FsBoardState,
  type FsStackup,
} from "../../api";
import { useAuth } from "../../auth";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";

export interface SnapshotInfo {
  id: number;
  sha: string;
  ref_name?: string | null;
}

export default function StackupTab({
  projectId,
  snapshot,
  board,
}: {
  projectId: number;
  snapshot: SnapshotInfo | null;
  board: string;
}) {
  const { isAdmin } = useAuth();
  const dialog = useDialog();
  const [state, setState] = useState<FsBoardState | null>(null);
  const [stackups, setStackups] = useState<FsStackup[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    (signal?: AbortSignal) => {
      Promise.all([fsBoardState(projectId, board, snapshot?.id ?? null, signal), fsStackups(signal)])
        .then(([s, list]) => {
          setState(s);
          setStackups(list);
        })
        .catch((e) => {
          if (!isAbortError(e)) setError(errorMessage(e));
        });
    },
    [projectId, board, snapshot?.id],
  );

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  const assign = async (key: string) => {
    setBusy(true);
    setError("");
    try {
      setState(await fsAssignStackup(projectId, { stackup_key: key, board, snapshot_id: snapshot?.id ?? null }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number, name: string) => {
    if (!(await dialog.confirm(`Remove “${name}” from this board?`, { title: "Remove profile" }))) return;
    setBusy(true);
    try {
      setState(await fsDeleteProfile(projectId, id, board, snapshot?.id ?? null));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!state) return <Spinner label="Loading the board's impedance work" />;

  const outdated = state.profiles.filter((p) => p.outdated).length;

  return (
    <div className="fs-page">
      {error ? <ErrorBanner message={error} /> : null}

      <section className="card pad">
        <h2 className="card-title">Stackup</h2>
        <div className="fs-row">
          <label className="fs-field">
            <span>Assigned to this board</span>
            <select
              className="text"
              value={state.revision?.stackup_key ?? ""}
              disabled={busy}
              onChange={(e) => assign(e.target.value)}
            >
              <option value="">— none —</option>
              {stackups.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.builtin ? "" : "★ "}
                  {s.manufacturer} {s.name}
                </option>
              ))}
            </select>
          </label>
          {state.stackup ? (
            <span className="muted fs-note">
              {state.stackup.layers.filter((l) => l.type === "copper").length} copper layers ·{" "}
              {state.stackup.total_mm.toFixed(3)} mm ·{" "}
              {state.stackup.soldermask ? "solder mask" : "no mask"} ·{" "}
              {state.stackup.finish ? state.stackup.finish.type : "no finish"}
            </span>
          ) : null}
        </div>
        <p className="muted fs-note">
          {snapshot
            ? `Applies from ${snapshot.ref_name || snapshot.sha.slice(0, 8)} forward; earlier commits keep what they had.`
            : "No commit selected — this edits the current assignment."}
          {isAdmin
            ? " New stackups are created in Simulator → Field solver (administrators only)."
            : " Only an administrator can create or edit a stackup."}
        </p>

        {state.mismatch.length ? (
          <div className="fs-notice warn">
            <b>The board file and the assigned stackup disagree.</b>
            <ul className="fs-notes">
              {state.mismatch.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
            <span className="muted fs-note">
              Nothing is blocked — the impedance numbers are computed against the assigned stackup, which is what the
              fab will build.
            </span>
          </div>
        ) : state.board_file ? (
          <p className="muted fs-note">
            The board file declares {state.board_file.copper_layers} copper layers and{" "}
            {state.board_file.total_mm.toFixed(3)} mm, which agrees with the assigned stackup.
          </p>
        ) : (
          <p className="muted fs-note">The board file declares no stackup of its own, so there is nothing to compare.</p>
        )}
      </section>

      <section className="card pad">
        <h2 className="card-title">Impedance profiles</h2>
        {outdated ? (
          <div className="fs-notice warn">
            <b>
              {outdated} of these {outdated === 1 ? "results was" : "results were"} solved against a different stackup.
            </b>{" "}
            The geometry and the numbers are kept for reference, but they no longer describe this board — open the
            profile in the field solver and calculate it again.
          </div>
        ) : null}
        {state.profiles.length ? (
          <table className="data">
            <thead>
              <tr>
                <th>Profile</th>
                <th>Type</th>
                <th>Target</th>
                <th>Design f</th>
                <th>Result</th>
                <th>Solved</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {state.profiles.map((p) => {
                const cfg = p.config as { type?: string; target?: number; tolerance?: number; f?: number };
                const res = p.result as { summary?: Record<string, number> } | null;
                const z = res?.summary?.Z0 ?? res?.summary?.Zdiff;
                return (
                  <tr key={p.id} className={p.outdated ? "fs-bad" : ""}>
                    <td>{p.name}</td>
                    <td className="muted">{cfg.type ?? "—"}</td>
                    <td>
                      {cfg.target ?? "—"} Ω ±{cfg.tolerance ?? "—"} %
                    </td>
                    <td>{cfg.f ? `${(cfg.f / 1e9).toPrecision(3)} GHz` : "—"}</td>
                    <td>
                      {z != null ? `${z.toFixed(2)} Ω` : <span className="muted">not solved</span>}
                      {p.outdated ? <span className="pill warn"> outdated</span> : null}
                    </td>
                    <td className="muted">{p.solved_at ? p.solved_at.slice(0, 10) : "—"}</td>
                    <td>
                      <button type="button" className="btn btn-sm" disabled={busy} onClick={() => remove(p.id, p.name)}>
                        remove
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p className="muted fs-note">
            No profiles on this board yet. Build one in Simulator → Field solver and save it to this project.
          </p>
        )}
      </section>
    </div>
  );
}
