/** Attach the work on screen to a board, from inside the field solver.
 *
 *  The common way in is sideways: somebody opens the solver, works out a geometry,
 *  and only then needs somewhere to keep it. This panel is that somewhere — pick the
 *  project, the commit and the board, and the current profile (with its result, when
 *  it has been solved) is saved exactly as the project's own Stackup tab would save
 *  it. Assignments are commit-versioned: they apply from the chosen commit forward.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  errorMessage,
  fsAssignStackup,
  fsBoardState,
  fsSaveProfiles,
  getProjects,
  getSnapshots,
  isAbortError,
  type FsBoardProfile,
  type FsBoardState,
  type ProjectInfo,
  type SnapshotInfo,
} from "../../api";
import { zKey, type Profile } from "./model";
import { fmtHz } from "./model";

export interface ProjectPanelProps {
  /** The stackup the page is working on, for the "assign it" action and the gate. */
  stackupKey: string;
  /** Every profile on the page. The user picks which ones to keep. */
  profiles: Profile[];
  /** The full payload for the profile currently on screen, when it has been solved.
   *  Strictly more than a cell carries — sweep, notes and the geometry outline. */
  liveResult?: { profileId: number; payload: Record<string, unknown> } | null;
  /** Where the page came from, when the project page deep-linked into the solver. */
  initial?: { projectId?: number | null; snapshotId?: number | null; board?: string };
  onLoadProfile: (p: FsBoardProfile) => void;
}

/** A profile's result in the shape the board stores — `{summary, design, …}` — never
 *  the solved mesh.
 *
 *  A CELL keeps a flat summary plus the C/L matrices (`{Z0, …, Cm, Lm, C0m}`), which
 *  is not the shape the project page reads (`result.summary.Z0`). Reshaping here is
 *  what lets a profile solved earlier in the session be saved with its numbers
 *  instead of as an empty row. The profile currently on screen has more than a cell
 *  holds — the sweep, the notes, the geometry outline — so its live payload wins. */
const resultOf = (
  p: Profile,
  live?: { profileId: number; payload: Record<string, unknown> } | null,
): Record<string, unknown> | null => {
  if (live && live.profileId === p.id) return live.payload;
  const solved = Object.values(p.cells ?? {}).find((c) => c?.result);
  if (!solved?.result) return null;
  const { Cm, Lm, C0m, ...summary } = solved.result as Record<string, unknown>;
  return { summary, design: { C: Cm, L: Lm }, C0: C0m };
};

const zOf = (p: Profile): number | null => {
  const solved = Object.values(p.cells ?? {}).find((c) => c?.result);
  const v = (solved?.result as Record<string, number> | undefined)?.[zKey(p)];
  return typeof v === "number" ? v : null;
};

export default function ProjectPanel({ stackupKey, profiles, liveResult, initial, onLoadProfile }: ProjectPanelProps) {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotInfo[]>([]);
  const [projectId, setProjectId] = useState<number | null>(initial?.projectId ?? null);
  const [snapshotId, setSnapshotId] = useState<number | null>(initial?.snapshotId ?? null);
  const [board, setBoard] = useState(initial?.board ?? "");
  const [state, setState] = useState<FsBoardState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  // Which profiles to keep. Solved ones are ticked by default: an unsolved profile is
  // a target with no answer, and saving one writes a row with nothing in it.
  const [picked, setPicked] = useState<Record<number, boolean>>({});

  useEffect(() => {
    setPicked((old) => {
      const next: Record<number, boolean> = {};
      for (const p of profiles) next[p.id] = old[p.id] ?? zOf(p) !== null;
      return next;
    });
  }, [profiles]);

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
        setSnapshotId((cur) => (cur && ready.some((x) => x.id === cur) ? cur : ready[0]?.id ?? null));
        setBoard((cur) => {
          const snap = ready.find((x) => x.boards?.some((b) => b.name === cur));
          return snap ? cur : ready[0]?.boards?.[0]?.name ?? "";
        });
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
  const chosen = useMemo(() => profiles.filter((p) => picked[p.id]), [profiles, picked]);

  // The gate. A geometry only means anything against the stackup it was solved on, so
  // a board assigned something else cannot take these profiles at all. The server
  // enforces this too — the agent tools write through the same endpoint — and refuses
  // without writing anything.
  const conflict = !!stackupKey && !!assigned && assigned !== stackupKey;
  const unassigned = !!stackupKey && !assigned;
  const blocked = conflict || !chosen.length;
  const existing = new Set((state?.profiles ?? []).map((p) => p.name));
  const replacing = chosen.filter((p) => existing.has(p.name)).length;

  const save = () =>
    act(async () => {
      setNote("");
      const res = await fsSaveProfiles(projectId!, {
        profiles: chosen.map((p) => ({
          name: p.name,
          config: p as unknown as Record<string, unknown>,
          result: resultOf(p, liveResult),
        })),
        board,
        snapshot_id: snapshotId,
        stackup_key: stackupKey,
        assign_stackup: unassigned,
      });
      const { added, replaced } = res.saved;
      setNote(
        `Saved ${added + replaced} profile${added + replaced === 1 ? "" : "s"}` +
          (replaced ? ` — ${added} new, ${replaced} replaced by name.` : ".") +
          (unassigned ? ` The board was also assigned ${stackupKey}.` : ""),
      );
      return res;
    });

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
          {conflict ? (
            <div className="fs-notice warn">
              <b>Nothing can be saved to this board.</b> It is assigned <b>{assigned}</b> and this page is working on{" "}
              <b>{stackupKey}</b>. A geometry only means anything against the stackup it was solved on, so these
              profiles describe a board that is not this one.
              <div className="fs-row">
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy}
                  onClick={() =>
                    act(() => fsAssignStackup(projectId, { stackup_key: stackupKey, board, snapshot_id: snapshotId }))
                  }
                >
                  Assign {stackupKey} to this board
                </button>
                <span className="muted fs-note">
                  …or pick {assigned} at the top of the page and build the profiles against it.
                </span>
              </div>
            </div>
          ) : null}

          <table className="data">
            <thead>
              <tr>
                <th className="ctr">
                  <input
                    type="checkbox"
                    aria-label="Select every profile"
                    checked={chosen.length === profiles.length && profiles.length > 0}
                    onChange={(e) =>
                      setPicked(Object.fromEntries(profiles.map((p) => [p.id, e.target.checked])))
                    }
                  />
                </th>
                <th>Profile on this page</th>
                <th>Target</th>
                <th>Result</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {profiles.map((p) => {
                const z = zOf(p);
                return (
                  <tr key={p.id}>
                    <td className="ctr">
                      <input
                        type="checkbox"
                        aria-label={`Save ${p.name}`}
                        checked={!!picked[p.id]}
                        onChange={(e) => setPicked((old) => ({ ...old, [p.id]: e.target.checked }))}
                      />
                    </td>
                    <td>{p.name}</td>
                    <td>
                      {p.target} Ω ±{p.tolerance}% · {fmtHz(p.f)}
                    </td>
                    <td>
                      {z != null ? `${z.toFixed(2)} Ω` : <span className="muted">not solved</span>}
                    </td>
                    <td className="muted">{existing.has(p.name) ? "replaces one on the board" : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div className="fs-row">
            <button
              type="button"
              className="btn btn-sm"
              disabled={busy || !stackupKey || assigned === stackupKey}
              onClick={() => act(() => fsAssignStackup(projectId, { stackup_key: stackupKey, board, snapshot_id: snapshotId }))}
            >
              {assigned === stackupKey ? "Stackup already assigned" : "Assign this stackup to the board"}
            </button>
            <button type="button" className="btn btn-sm btn-accent" disabled={busy || blocked} onClick={save}>
              {chosen.length
                ? `Save ${chosen.length} profile${chosen.length === 1 ? "" : "s"} to ${board || "this board"}`
                : "Pick at least one profile"}
            </button>
          </div>
          {unassigned && chosen.length ? (
            <p className="muted fs-note">
              This board carries no stackup, so saving also assigns <b>{stackupKey}</b> to it, effective at the chosen
              commit and forward.
            </p>
          ) : null}
          {replacing ? (
            <p className="muted fs-note">
              {replacing} of these {replacing === 1 ? "matches a profile" : "match profiles"} already on the board by
              name and will replace {replacing === 1 ? "it" : "them"}.
            </p>
          ) : null}
          {note ? <p className="fs-note">{note}</p> : null}
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
