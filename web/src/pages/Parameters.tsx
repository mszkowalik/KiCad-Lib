/** Production parameters — the values a procedure interpolates as
 *  {placeholders}, who depends on each, and the record of every time one moved.
 *
 *  WHY IT IS ITS OWN PAGE. It lived as a fourth tab under Files, beside
 *  berryware bundles and firmware images. It is not a file: it is the one thing
 *  on this bench that a deployment version DEPENDS on and does not contain, so
 *  it belongs one hop from the deployments, not filed with the artefacts (user
 *  request 2026-09-17).
 *
 *  WHAT THE PAGE HAS TO SAY, and could not before decision
 *  [0024](../../../docs/decisions/0024-a-version-declares-the-parameters-it-needs.md):
 *
 *  1. **Who depends on each key.** `Dongle_V2 config` v10 needs seven keys and
 *     v18 needs four, both pointing at the same set. Removing the three v18
 *     stopped using broke v10, and the platform said so at the bench with a
 *     device in the socket. The server now refuses that write by name.
 *  2. **That a VALUE changed.** A key whose name survives and whose meaning
 *     moves — a broker repointed, a salt rotated — passes every other check
 *     there is. Each save appends a revision, and a run stamps the one it used.
 *
 *  **Editing is IN PLACE, not in a dialog** (user request 2026-09-17): the page
 *  IS the editor, Save and Cancel appear when something differs from what is
 *  stored, and nothing is hidden behind a button that carries no decision. The
 *  modal `ParamSetEditor` still exists for the deployment page and the composer,
 *  where the set is not what the screen is about.
 *
 *  A set is still not versioned, deliberately: rotating a WiFi password must
 *  not mint a new version of every deployment that uses it. What the history
 *  gives instead is REVERT — which appends rather than rewinds, so the record
 *  still says that the changes happened and that somebody undid them.
 */
import { useCallback, useEffect, useState } from "react";
import {
  deleteParamSet,
  errorMessage,
  getParamSetValues,
  getProjects,
  isAbortError,
  listParamRevisions,
  listParamSets,
  putParamSet,
  revertParamSet,
  type ParamRevisionRow,
  type ParamSetRow,
  type ProjectInfo,
} from "../api";
import { useDialog } from "../components/Dialog";
import { ErrorBanner, Spinner } from "../components/Ui";
import { fmtWhen } from "../components/flasher/common";
import { useStickyState } from "../useStickyState";

/* Values are shown in the clear. Masking them was tried and removed the same
   day (user decision 2026-09-17): every value here is a bench setting somebody
   came to this page to read, the page is behind the sign-in gate, and a box of
   dots with a "show" beside it is one more click on every visit. Storage is
   unaffected — the set is Fernet-encrypted at rest whatever is on screen. */

type Row = { key: string; value: string };

/** Values keyed by set id. Fetched decrypted, which is what editing in place
 *  costs: the dialog fetched them only when it opened. They stay masked on
 *  screen — a bench is usually a room with other people in it. */
type Values = Record<number, Row[]>;

const sameRows = (a: Row[] | undefined, b: Row[] | undefined) =>
  JSON.stringify(a ?? []) === JSON.stringify(b ?? []);

export default function Parameters() {
  const dialog = useDialog();
  const [projects, setProjects] = useState<ProjectInfo[] | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("flasher.project", null);
  const [sets, setSets] = useState<ParamSetRow[] | null>(null);
  const [stored, setStored] = useState<Values>({});
  const [draft, setDraft] = useState<Values>({});
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refused, setRefused] = useState<Record<number, string>>({});
  const [historyFor, setHistoryFor] = useState<number | null>(null);
  const [history, setHistory] = useState<ParamRevisionRow[] | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getProjects(ac.signal)
      .then(setProjects)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  const valid = projects?.some((p) => p.id === projectId) ? projectId : projects?.[0]?.id ?? null;

  const reload = useCallback(() => {
    if (valid === null) return () => {};
    const ac = new AbortController();
    listParamSets(valid, ac.signal)
      .then(async (rows) => {
        setSets(rows);
        const loaded: Values = {};
        for (const ps of rows) {
          const detail = await getParamSetValues(ps.id, ac.signal);
          loaded[ps.id] = Object.entries(detail.values).map(([key, value]) => ({
            key, value: String(value),
          }));
        }
        setStored(loaded);
        setDraft(loaded);
        setNotes({});
        setRefused({});
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [valid]);

  useEffect(() => {
    setSets(null);
    return reload();
  }, [reload]);

  // Fetched only for the set whose fold is open — a set edited weekly
  // accumulates rows nobody asked for.
  useEffect(() => {
    if (historyFor === null) return;
    const ac = new AbortController();
    setHistory(null);
    listParamRevisions(historyFor, ac.signal)
      .then(setHistory)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [historyFor]);

  const edit = (id: number, i: number, patch: Partial<Row>) =>
    setDraft((cur) => ({
      ...cur,
      [id]: (cur[id] ?? []).map((r, j) => (j === i ? { ...r, ...patch } : r)),
    }));

  const save = async (ps: ParamSetRow, force = false) => {
    const values: Record<string, string> = {};
    for (const r of draft[ps.id] ?? []) if (r.key.trim()) values[r.key.trim()] = r.value;
    setSaving(ps.id);
    setError(null);
    try {
      await putParamSet(valid!, ps.name, values, "", { note: notes[ps.id] ?? "", force });
      setRefused((cur) => ({ ...cur, [ps.id]: "" }));
      reload();
      if (historyFor === ps.id) setHistory(await listParamRevisions(ps.id));
    } catch (err) {
      const msg = errorMessage(err);
      setError(msg);
      // A refusal names the versions it protects, so offering the override
      // right beside it is honest. Anything else is a plain failure.
      setRefused((cur) => ({
        ...cur, [ps.id]: msg.includes("would break a published version") ? msg : "",
      }));
    } finally {
      setSaving(null);
    }
  };

  const revert = async (ps: ParamSetRow, rev: ParamRevisionRow) => {
    if (!(await dialog.confirm(
      `Put the values back to what revision ${rev.revision_no} left?`
      + " Nothing is removed from the history — this is written on top of it as a new revision.",
      { title: `Revert to r${rev.revision_no}`, tone: "primary", confirmLabel: "Revert" },
    ))) return;
    try {
      await revertParamSet(ps.id, rev.revision_no);
      reload();
      setHistory(await listParamRevisions(ps.id));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const newSet = async () => {
    const name = await dialog.prompt('Parameter set name ("production", "bench"):', {
      title: "New parameter set",
    });
    if (!name || valid === null) return;
    try {
      await putParamSet(valid, name, {}, "", { note: "created" });
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const remove = async (ps: ParamSetRow) => {
    if (!(await dialog.confirm(`Delete parameter set “${ps.name}”?`, {
      title: "Delete parameter set", tone: "danger", confirmLabel: "Delete",
    }))) return;
    try {
      await deleteParamSet(ps.id);
      reload();
    } catch (err) {
      // The server refuses while any version points at the set, and names
      // them. Nothing to add here.
      setError(errorMessage(err));
    }
  };

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Parameters</h1>
          {projects ? (
            <select
              className="row-input"
              value={valid ?? ""}
              onChange={(e) => setProjectId(Number(e.target.value))}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          ) : null}
          <button type="button" className="btn btn-sm" onClick={() => void newSet()}>
            New set
          </button>
          <span className="toolbar-total">
            shared, encrypted, not versioned — the history is what a revert reads
          </span>
        </div>

        {error ? <ErrorBanner message={error} /> : null}

        {sets === null ? (
          <Spinner label="Loading parameters…" />
        ) : sets.length === 0 ? (
          <p className="muted">No parameter sets in this project yet.</p>
        ) : (
          sets.map((ps) => {
            const rows = draft[ps.id] ?? [];
            const dirty = !sameRows(rows, stored[ps.id]);
            return (
              <div key={ps.id} className="card pad param-set-card">
                <div className="toolbar">
                  <h2 className="card-title mono">{ps.name}</h2>
                  <span className="pill neutral">
                    {ps.revision_no ? `revision ${ps.revision_no}` : "no recorded edit"}
                  </span>
                  <span className="rail-spacer" />
                  <button
                    type="button"
                    className="btn btn-sm row-del"
                    onClick={() => void remove(ps)}
                  >
                    Delete
                  </button>
                </div>
                <p className="card-subtitle">
                  {ps.updated_by ? `${ps.updated_by} · ` : ""}{fmtWhen(ps.updated_at)} · a save
                  changes what the NEXT run of every version pointing here uses
                </p>

                <table className="data data-fixed param-keys-table">
                  <thead>
                    <tr>
                      <th>Key</th>
                      <th>Value</th>
                      <th className="ctr" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => {
                      // `used_by` still drives the × tooltip. The COLUMN is gone
                      // (user decision 2026-09-17): a parameter set is scoped to
                      // one project, so the list only ever named sibling
                      // deployments of the project already picked above, and it
                      // was taking 42% of the table to say so. The guard never
                      // depended on it — the server refuses the save and names
                      // the versions itself.
                      const uses = ps.used_by[r.key] ?? [];
                      const who = uses.map((u) => `${u.deployment} v${u.version_no}`).join(", ");
                      return (
                        <tr key={i}>
                          <td>
                            {/* The key and its "unused" marker share the cell,
                                in a DIV — `display: flex` on a <td> takes the
                                cell out of the table layout and it then sizes
                                to its own content (see components/CLAUDE.md). */}
                            <div className="param-key-cell">
                              <input
                                className="row-input mono"
                                value={r.key}
                                onChange={(e) => edit(ps.id, i, { key: e.target.value })}
                              />
                              {/* The full "needed by" list was a column and is
                                  gone. What stayed is the one fact that was
                                  useful (user, 2026-09-17): nothing published
                                  reads this key, so removing it is free. Who
                                  DOES need it is on the × and in the refusal. */}
                              {uses.length ? null : (
                                <span className="pill neutral" title="No published version reads this key">
                                  unused
                                </span>
                              )}
                            </div>
                          </td>
                          <td>
                            <input
                              className="row-input mono"
                              value={r.value}
                              onChange={(e) => edit(ps.id, i, { value: e.target.value })}
                            />
                          </td>
                          <td className="ctr">
                            <button
                              type="button"
                              className="btn btn-sm row-del"
                              title={uses.length
                                ? `Needed by ${who} — the server will refuse this`
                                : "Remove this row"}
                              onClick={() =>
                                setDraft((cur) => ({
                                  ...cur,
                                  [ps.id]: (cur[ps.id] ?? []).filter((_, j) => j !== i),
                                }))
                              }
                            >
                              ×
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                <div className="btn-row">
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() =>
                      setDraft((cur) => ({
                        ...cur, [ps.id]: [...(cur[ps.id] ?? []), { key: "", value: "" }],
                      }))
                    }
                  >
                    Add row
                  </button>
                </div>

                {dirty ? (
                  <div className="param-save">
                    <input
                      className="text"
                      placeholder="what changed and why — the only record that a VALUE moved"
                      value={notes[ps.id] ?? ""}
                      onChange={(e) => setNotes((c) => ({ ...c, [ps.id]: e.target.value }))}
                    />
                    <div className="btn-row">
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => void save(ps)}
                        disabled={saving === ps.id}
                      >
                        {saving === ps.id ? "Saving…" : "Save"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => {
                          setDraft((cur) => ({ ...cur, [ps.id]: stored[ps.id] ?? [] }));
                          setNotes((c) => ({ ...c, [ps.id]: "" }));
                          setRefused((c) => ({ ...c, [ps.id]: "" }));
                        }}
                        disabled={saving === ps.id}
                      >
                        Cancel
                      </button>
                      {refused[ps.id] ? (
                        <button
                          type="button"
                          className="btn btn-danger btn-sm"
                          onClick={() => void save(ps, true)}
                          disabled={saving === ps.id}
                          title="Those versions stop validating and cannot be run until the key comes back"
                        >
                          Save anyway
                        </button>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                <details
                  open={historyFor === ps.id}
                  onToggle={(e) =>
                    setHistoryFor((e.currentTarget as HTMLDetailsElement).open ? ps.id : null)
                  }
                >
                  <summary className="card-subtitle">
                    History — what changed, when, and by whom
                  </summary>
                  {historyFor !== ps.id ? null : history === null ? (
                    <Spinner label="Loading history…" />
                  ) : history.length === 0 ? (
                    <p className="muted">
                      Nothing recorded yet. The log starts at the first save after the platform
                      began keeping one — an older value simply has no entry, which is not the
                      same as never having changed.
                    </p>
                  ) : (
                    <div className="version-timeline param-history">
                      {history.map((r, i) => (
                        <div key={r.id} className="version-row">
                          <div className="version-head">
                            <strong>r{r.revision_no}</strong>
                            <span className="muted dim">{fmtWhen(r.created_at)}</span>
                            {r.updated_by ? <span className="muted dim">{r.updated_by}</span> : null}
                            {r.keys_added.length ? (
                              <span className="pill ok">+{r.keys_added.join(", ")}</span>
                            ) : null}
                            {r.keys_removed.length ? (
                              <span className="pill err">−{r.keys_removed.join(", ")}</span>
                            ) : null}
                            {r.changed.length ? (
                              <span className="pill warn">changed {r.changed.join(", ")}</span>
                            ) : null}
                            <span className="rail-spacer" />
                            {/* Not on the newest row: reverting to where you
                                already are writes a revision that says nothing. */}
                            {i > 0 && r.restorable ? (
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => void revert(ps, r)}
                                title="Write these values on top of the history as a new revision"
                              >
                                Revert to this
                              </button>
                            ) : null}
                            {i > 0 && !r.restorable ? (
                              <span className="muted dim" title="Recorded before the values were kept">
                                values not kept
                              </span>
                            ) : null}
                          </div>
                          {r.note ? <div className="version-changes muted">{r.note}</div> : null}
                        </div>
                      ))}
                    </div>
                  )}
                </details>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
