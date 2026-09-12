/** A board's stackup and its impedance profiles, at one commit.
 *
 *  Both are commit-versioned like the manual cost data: what you assign here applies
 *  from this commit forward and travels with later commits until somebody changes
 *  it. Changing the stackup keeps every profile and its numbers — results computed
 *  against the previous stackup are marked outdated rather than thrown away.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  fsAssignStackup,
  fsBoardState,
  fsDeleteProfile,
  fsColors,
  fsSetAppearance,
  fsStackups,
  isAbortError,
  type FsBoardState,
  type FsColors,
  type FsComparison,
  type FsStackup,
} from "../../api";
import { useAuth } from "../../auth";
import StackupTable, { StackupLegend } from "../StackupTable";
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
  const [palette, setPalette] = useState<FsColors | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    (signal?: AbortSignal) => {
      Promise.all([
        fsBoardState(projectId, board, snapshot?.id ?? null, signal),
        fsStackups(signal),
        fsColors(signal),
      ])
        .then(([s, list, cols]) => {
          setState(s);
          setStackups(list);
          setPalette(cols);
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

  /** The board's ink. A colour is written to the PROJECT, never to the stackup: the
   *  library would otherwise need a copy of every stackup per colour, and the solver
   *  cannot tell two of them apart. */
  const setColor = async (patch: { mask_color?: string; silk_color?: string }) => {
    if (!palette) return;
    const mask = patch.mask_color ?? state?.revision?.mask_color ?? "";
    // JLCPCB does not sell the legend as a free choice — white on every mask but a
    // white one. Follow that when the mask changes, unless the user has already said
    // otherwise for this board.
    const silk =
      patch.silk_color ??
      (patch.mask_color !== undefined
        ? palette.silkscreen_rule.by_mask[patch.mask_color] ?? palette.silkscreen_rule.default
        : state?.revision?.silk_color ?? "");
    setBusy(true);
    setError("");
    try {
      setState(await fsSetAppearance(projectId, { mask_color: mask, silk_color: silk, board, snapshot_id: snapshot?.id ?? null }));
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

  const maskColor = state?.revision?.mask_color ?? "";
  const silkColor = state?.revision?.silk_color ?? "";
  const inkOf = (list: FsColors["soldermask"] | undefined, id: string) =>
    list?.find((c) => c.id === id)?.hex;
  const boardInk = {
    mask: inkOf(palette?.soldermask, maskColor),
    silk: inkOf(palette?.silkscreen, silkColor),
  };

  if (!state) return <Spinner label="Loading the board's impedance work" />;

  const outdated = state.profiles.filter((p) => p.outdated).length;

  return (
    <div className="fs-page">
      {error ? <ErrorBanner message={error} /> : null}

      <section className="card pad">
        <h2 className="card-title">Stackup</h2>
        <div className="field-row">
          <label className="field">
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
        {palette ? (
          <div className="field-row stk-colors">
            <label className="field">
              <span>Solder mask colour</span>
              <span className="swatches">
                {palette.soldermask.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className={`swatch${maskColor === c.id ? " on" : ""}`}
                    style={{ background: c.hex }}
                    title={`${c.name} solder mask`}
                    aria-label={`${c.name} solder mask`}
                    aria-pressed={maskColor === c.id}
                    disabled={busy}
                    onClick={() => setColor({ mask_color: c.id })}
                  />
                ))}
              </span>
            </label>
            <label className="field">
              <span>Silkscreen</span>
              <span className="swatches">
                {palette.silkscreen.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className={`swatch${silkColor === c.id ? " on" : ""}`}
                    style={{ background: c.hex }}
                    title={`${c.name} legend`}
                    aria-label={`${c.name} legend`}
                    aria-pressed={silkColor === c.id}
                    disabled={busy}
                    onClick={() => setColor({ silk_color: c.id })}
                  />
                ))}
              </span>
            </label>
          </div>
        ) : null}
        <p className="muted fs-note">
          The colour belongs to this board, not to the stackup — the same stackup in another colour is the same board
          electrically, so choosing one here changes nothing in the library. The legend follows the mask the way the fab
          sells it (white on everything but a white mask), and you can override it.
        </p>

        <p className="muted fs-note">
          {snapshot
            ? `Applies from ${snapshot.ref_name || snapshot.sha.slice(0, 8)} forward; earlier commits keep what they had.`
            : "No commit selected — this edits the current assignment."}
          {isAdmin
            ? " New stackups are created in Simulator → Field solver (administrators only)."
            : " Only an administrator can create or edit a stackup."}
        </p>

      </section>

      <BoardFileCheck state={state} ink={boardInk} />

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
        <p className="muted fs-note">
          A profile is built in the field solver — it needs a geometry and a solve — so this is the way across. The
          solver opens on this board's stackup and saves back to this commit.
        </p>
        <div className="field-row">
          <Link
            className="btn btn-sm btn-accent"
            to={`/sim?tab=field${state.revision?.stackup_key ? `&stackup=${encodeURIComponent(state.revision.stackup_key)}` : ""}&project=${projectId}${
              board ? `&board=${encodeURIComponent(board)}` : ""
            }${snapshot ? `&snapshot=${snapshot.id}` : ""}`}
          >
            {state.profiles.length ? "Add or edit profiles in the field solver" : "Build a profile in the field solver"}
          </Link>
        </div>

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
          <p className="muted fs-note">No profiles on this board yet.</p>
        )}
      </section>
    </div>
  );
}


/** Does the `.kicad_pcb` describe the same board as the assigned stackup?
 *
 *  The two are compared in a normal form — the copper layers, and the dielectric GAP
 *  between each neighbouring pair — because KiCad allows only `copper - 1` dielectric
 *  layers and writes a multi-sheet gap as sub-layers of one layer. The backend does
 *  the work (`services/field_state.py`); this panel only says where the two differ.
 *
 *  Informational by design (user decision 2026-08-31): a board may disagree with the
 *  stackup it is solved and costed against, and nothing here refuses anything.
 */
function BoardFileCheck({ state, ink }: { state: FsBoardState; ink?: { mask?: string; silk?: string } }) {
  const cmp: FsComparison | undefined = state.comparison;
  const file = state.board_file;

  if (!state.stackup) {
    return (
      <section className="card pad">
        <h2 className="card-title">Board file against the stackup</h2>
        <p className="muted fs-note">
          No stackup is assigned to this board, so there is nothing to compare it against.
        </p>
      </section>
    );
  }
  if (!file) {
    return (
      <section className="card pad">
        <h2 className="card-title">
          Board file against the stackup <span className="pill neutral">not compared</span>
        </h2>
        <p className="muted fs-note">
          {state.board_file_note || "The board file was not read, and the platform gave no reason."}
        </p>
      </section>
    );
  }

  const same = cmp.verdict === "match";
  const compared = cmp.rows.filter((r) => r.ok !== null).length;
  const fmt = (v: string | number | null, unit: string) => {
    if (v === null || v === undefined) return "—";
    if (typeof v === "number") return `${unit === "mm" ? v.toFixed(4) : String(v)}${unit ? ` ${unit}` : ""}`;
    return v;
  };

  return (
    <section className="card pad">
      <h2 className="card-title">
        Board file against the stackup{" "}
        <span className={`pill ${same ? "ok" : "warn"}`}>{same ? "same" : "differs"}</span>
      </h2>

      {same ? (
        <p className="fs-note">
          <b>The board file describes the same build as the assigned stackup.</b> All {compared} compared values agree:{" "}
          {file.copper_layers} copper layers, {file.total_mm.toFixed(4)} mm of copper and dielectric, and every copper
          thickness, dielectric thickness, Dk and loss tangent inside tolerance.
        </p>
      ) : (
        <div className="fs-notice warn">
          <b>The board file and the assigned stackup describe different boards.</b>
          <ul className="fs-notes">
            {cmp.differences.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
          <span className="muted fs-note">
            Nothing is blocked — the impedance numbers are computed against the assigned stackup, which is what the fab
            will build. Fix the board file in KiCad (Board Setup → Physical Stackup) or assign the stackup the board
            really uses.
          </span>
        </div>
      )}

      <StackupTable rows={cmp.stack} mode="compare" boardLabel="Board file" stackupLabel="Assigned stackup" colors={ink} />
      <StackupLegend
        note={
          <>
            Inside tolerance counts as the same: copper ±{cmp.tolerance.copper_mm} mm, dielectric ±
            {cmp.tolerance.dielectric_mm} mm, Dk ±{cmp.tolerance.eps_r}, loss tangent ±{cmp.tolerance.tand}.
          </>
        }
      />

      <details className="fs-details">
        <summary>The same check as a list of values ({compared} compared)</summary>
        <table className="data fs-kv">
          <thead>
            <tr>
              <th>Checked</th>
              <th>Board file</th>
              <th>Assigned stackup</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {cmp.rows.map((r, i) => (
              <tr key={`${r.what}-${i}`} className={r.ok === false ? "fs-bad" : undefined}>
                <td style={r.what.startsWith("  ") ? { paddingLeft: 26, color: "var(--muted)" } : undefined}>
                  {r.what.trim()}
                </td>
                <td>{fmt(r.board, r.unit)}</td>
                <td>{fmt(r.stackup, r.unit)}</td>
                <td>
                  {r.ok === true ? (
                    <span className="pill ok">same</span>
                  ) : r.ok === false ? (
                    <span className="pill err">differs</span>
                  ) : (
                    <span className="pill neutral">not stated</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <p className="muted fs-note">
        A dielectric is compared as the gap between two copper layers, because KiCad carries a multi-sheet gap as
        sub-layers of one layer and a fab lists each sheet. The surface finish is shown and does not decide the verdict:
        it is a separate order option at the fab.
      </p>
      {cmp.notes.length ? (
        <details className="fs-details">
          <summary>What is not compared</summary>
          <ul className="fs-notes">
            {cmp.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
