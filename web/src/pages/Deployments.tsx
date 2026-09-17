/** Deployments — one revision binds firmware + berryware + procedure + params.
 *
 *  Left: the deployments of a project with their channel badges.
 *  Middle: the version timeline, each row saying what changed.
 *  Right: the composed view of the selected version.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createDeployment,
  deleteDeployment,
  errorMessage,
  getFlasherMeta,
  getProjects,
  isAbortError,
  listDeployments,
  composeVersion,
  listParamSets,
  publishDeploymentVersion,
  rejectDeploymentVersion,
  updateDeployment,
  type DeploymentRow,
  type ParamSetRow,
  type DeploymentVersionRow,
  type FlasherMeta,
  type ProjectInfo,
} from "../api";
import AutoTextarea from "../components/AutoTextarea";
import { useDialog } from "../components/Dialog";
import Field, { CheckField, FieldRow } from "../components/Field";
import InfoTip from "../components/InfoTip";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import DiffView from "../components/flasher/DiffView";
import VersionView from "../components/flasher/VersionView";
import { fmtWhen } from "../components/flasher/common";
import { useStickyState } from "../useStickyState";

/** The three procedure kinds the API accepts (`DEPLOYMENT_KINDS` in
 *  routers/flasher.py). The bench reads `kind`, never the name. */
/** Bare words, no explanations (user request 2026-09-17). What each kind DOES
 *  is on the field's ⓘ; repeating it inside every option made the control the
 *  widest thing on the card for three values that are read once. */
const KIND_OPTIONS = [
  { value: "flash", label: "flash" },
  { value: "test", label: "test" },
  { value: "mark", label: "mark" },
];

export default function Deployments() {
  const dialog = useDialog();
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [meta, setMeta] = useState<FlasherMeta | null>(null);
  const [deployments, setDeployments] = useState<DeploymentRow[] | null>(null);
  /** The project's parameter sets, for the assignment field on the head card.
   *  A deployment names a set; each version pins one at creation. */
  const [paramSets, setParamSets] = useState<ParamSetRow[]>([]);
  /** Set when + created a deployment, so the name box takes the caret and the
   *  placeholder is selected — the first thing to do is rename it. */
  const [focusName, setFocusName] = useState(false);
  const nameRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("depl.project", null);
  const [selectedId, setSelectedId] = useStickyState<number | null>("depl.selected", null);
  const [versionId, setVersionId] = useState<number | null>(null);
  /** True while the POST that mints a draft is in flight. There is no modal
   *  any more: `New version` creates the draft, selects it, and the right-hand
   *  column IS the editor (user request 2026-09-17). */
  const [composing, setComposing] = useState(false);
  const [diffFor, setDiffFor] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  /** The draft this page just minted, which `VersionView` opens editing. */
  const [autoEditId, setAutoEditId] = useState<number | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    Promise.all([getProjects(ac.signal), getFlasherMeta(ac.signal)])
      .then(([p, m]) => {
        setProjects(p);
        setMeta(m);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  const validProject = projects.some((p) => p.id === projectId) ? projectId : projects[0]?.id ?? null;

  /** Re-read the project and RESOLVE when it has landed. `reload` below wraps
   *  it for the mount effect, which wants a cleanup rather than a promise — a
   *  caller that selects a row it just created needs to wait for the row to
   *  exist, or the "default to the live version" effect resets its selection. */
  const refetch = useCallback(async (signal?: AbortSignal) => {
    if (!validProject) return;
    try {
      const [d, ps] = await Promise.all([
        listDeployments(validProject, signal), listParamSets(validProject, signal),
      ]);
      setDeployments(d);
      setParamSets(ps);
    } catch (err) {
      if (!isAbortError(err)) setError(errorMessage(err));
    }
  }, [validProject]);

  const reload = useCallback(() => {
    if (!validProject) return;
    const ac = new AbortController();
    void refetch(ac.signal);
    return () => ac.abort();
  }, [validProject, refetch]);

  useEffect(() => {
    setDeployments(null);
    return reload();
  }, [reload]);

  const selected = useMemo(
    () => deployments?.find((d) => d.id === selectedId) ?? deployments?.[0] ?? null,
    [deployments, selectedId],
  );

  // Default the version pane to the live version of whatever is selected.
  useEffect(() => {
    if (!selected) return;
    const stillThere = selected.versions.some((v) => v.id === versionId);
    if (!stillThere) {
      setVersionId(selected.current_version_id ?? selected.versions[0]?.id ?? null);
    }
  }, [selected, versionId]);

  /** Create an empty deployment and select it — no prompts (user request
   *  2026-09-17). Two `dialog.prompt`s asked for the same two fields the head
   *  card holds, so the answers were typed twice over: once blind, once to
   *  correct them. The card IS the form; this only needs the row to exist.
   *
   *  The name still has to be unique per project, so a placeholder is found
   *  rather than sent empty — pressing + twice would otherwise hit the unique
   *  constraint and report a database error for an ordinary action. */
  const newDeployment = async () => {
    if (!validProject) return;
    const taken = new Set((deployments ?? []).map((d) => d.name));
    let name = "New deployment";
    for (let n = 2; taken.has(name); n += 1) name = `New deployment ${n}`;
    try {
      const res = await createDeployment(validProject, { name });
      setSelectedId(res.id);
      setVersionId(null);
      setFocusName(true);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  /** Mint a draft from the deployment's live version and select it. Nothing
   *  is asked for: every field the old modal prompted about is inherited, and
   *  the ones that are not — the note, the steps — are edited on the card that
   *  is about to appear. */
  const newVersion = async () => {
    if (!selected) return;
    setComposing(true);
    try {
      const from = selected.versions.find(
        (v) => v.id === (selected.current_version_id ?? selected.versions[0]?.id),
      );
      const made = await composeVersion(selected.id, {
        from_version_id: from?.id ?? null, comment: "", created_by: "",
      });
      // The row must EXIST before it is selected, or the effect that defaults
      // the pane to the live version sees an id that is not in the list yet
      // and resets it.
      await refetch();
      setAutoEditId(made.id);
      setVersionId(made.id);
      setReloadKey((k) => k + 1);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setComposing(false);
    }
  };

  /** Every field of the deployment itself — name, description, chip, kind,
   *  the test default — is edited through this, so a change to one can never
   *  reset another (the API takes the whole row). */
  const patchDeployment = async (patch: Partial<{
    name: string; description: string; chip: string; kind: string; active: boolean;
    param_set_id: number;
  }>) => {
    if (!selected) return;
    try {
      await updateDeployment(selected.id, {
        name: selected.name, description: selected.description, chip: selected.chip,
        kind: selected.kind, active: selected.active,
        // -1 clears it; the API leaves the field alone when it is absent.
        param_set_id: selected.param_set_id ?? -1,
        ...patch,
      });
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  /** The deployment's own fields, as typed. Boxes rather than prompts (user
   *  decision 2026-09-17): every field is visible at once, Save and Cancel
   *  appear only when something differs from what is stored, and one Save
   *  writes the whole row. */
  type Draft = {
    name: string; description: string; chip: string; kind: string; active: boolean;
    paramSetId: number;
  };
  const storedDraft = (d: DeploymentRow): Draft => ({
    name: d.name, description: d.description, chip: d.chip, kind: d.kind, active: d.active,
    // -1 is "none" throughout, so the draft holds a number and never a null
    // that `dirty` would have to special-case.
    paramSetId: d.param_set_id ?? -1,
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    // A new selection, or a reload after saving, is the stored row again.
    setDraft(selected ? storedDraft(selected) : null);
  }, [selected]);
  /** What the selected set supplies, for the hint under the field. */
  const paramKeys = paramSets.find((p) => p.id === draft?.paramSetId)?.keys ?? [];

  useEffect(() => {
    if (!focusName || !nameRef.current) return;
    nameRef.current.focus();
    nameRef.current.select();
    setFocusName(false);
  }, [focusName, draft]);

  const dirty = !!selected && !!draft
    && (Object.keys(draft) as (keyof Draft)[]).some((k) => draft[k] !== storedDraft(selected)[k]);
  const saveDraft = async () => {
    if (!selected || !draft || !draft.name.trim()) return;
    setSaving(true);
    try {
      await patchDeployment({
        name: draft.name.trim(), description: draft.description, chip: draft.chip.trim(),
        kind: draft.kind, active: draft.active, param_set_id: draft.paramSetId,
      });
    } finally {
      setSaving(false);
    }
  };

  /** The API is the authority: it refuses while any programming run records
   *  this deployment, so a cleanup can never orphan device history. */
  const removeDeployment = async (row?: DeploymentRow) => {
    const target = row ?? selected;
    if (!target) return;
    if (!(await dialog.confirm(
      `Delete "${target.name}" and its ${target.versions.length} version(s)? `
      + "Firmware and berryware stay in the project pool. Refused if any programming run "
      + "records this deployment.",
      { title: "Delete deployment", tone: "danger", confirmLabel: "Delete" },
    ))) return;
    try {
      await deleteDeployment(target.id);
      if (target.id === selected?.id) {
        setSelectedId(null);
        setVersionId(null);
      }
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  /** Publish a draft from the timeline. The composer can publish too, but a
   *  draft that was finished elsewhere — the API, another machine — had no
   *  button here, and "open the editor to press Publish" is not a status
   *  control. The server's gate is the same either way: it refuses without a
   *  comment or with validation errors, and says which. */
  const publishDraft = async (version: DeploymentVersionRow) => {
    if (!selected) return;
    if (!(await dialog.confirm(
      `Publish v${version.version_no} of "${selected.name}"? It becomes the current version and is immutable from then on.`,
      { title: "Publish version", tone: "ok", confirmLabel: "Publish" },
    ))) return;
    try {
      await publishDeploymentVersion(version.id);
      setReloadKey((k) => k + 1);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const discard = async (version: DeploymentVersionRow) => {
    if (!(await dialog.confirm(`Discard draft v${version.version_no}?`, {
      title: "Discard draft", tone: "danger", confirmLabel: "Discard",
    }))) return;
    try {
      await rejectDeploymentVersion(version.id);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Deployments</h1>
          <select
            className="row-input"
            value={validProject ?? ""}
            onChange={(e) => {
              setProjectId(Number(e.target.value));
              setSelectedId(null);
              setVersionId(null);
            }}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
        {error ? <ErrorBanner message={error} /> : null}

        {deployments === null ? (
          <Spinner label="Loading deployments…" />
        ) : deployments.length === 0 ? (
          <p className="muted">No deployments in this project yet.</p>
        ) : (
          <>
            {/* The deployments are TILES across the top, not a column down the
                left. There are a handful per project and each one is a word and
                two pills, so a full column of the page was spent on a picker —
                and every other column paid for it. A dropdown was the other
                option and was not taken: the pills say which version each
                channel runs and what kind the procedure is, and a dropdown
                shows one line of text (user request 2026-09-17). */}
            <div className="depl-tiles">
              {deployments.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  className={`depl-item${selected?.id === d.id ? " active" : ""}`}
                  onClick={() => {
                    setSelectedId(d.id);
                    setVersionId(d.current_version_id ?? d.versions[0]?.id ?? null);
                  }}
                >
                  <span className="depl-name">{d.name}</span>
                  <span className="muted dim">
                    {d.chip || "no chip"} · {d.versions.length} version{d.versions.length === 1 ? "" : "s"}
                  </span>
                  <span className="depl-chips">
                    {d.kind !== "flash" ? <span className="pill neutral">{d.kind}</span> : null}
                    {d.kind === "test" ? (
                      <span className={`pill ${d.active ? "ok" : "neutral"}`}>
                        {d.active ? "default on new batches" : "optional"}
                      </span>
                    ) : null}
                    {d.channels
                      .filter((c) => c.version_no !== null)
                      .map((c) => (
                        <span key={c.name} className="pill ok">
                          {c.name} v{c.version_no}
                        </span>
                      ))}
                  </span>
                  <span
                    className="depl-tile-x"
                    role="button"
                    tabIndex={0}
                    title={`Delete ${d.name}`}
                    onClick={(e) => { e.stopPropagation(); void removeDeployment(d); }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.stopPropagation();
                        void removeDeployment(d);
                      }
                    }}
                  >
                    ×
                  </span>
                </button>
              ))}
              {/* Adding and removing live WITH the tiles: the row is the list
                  of deployments, so the controls that change that list belong
                  on it rather than in the page toolbar (user request
                  2026-09-17). */}
              <button type="button" className="depl-item depl-item-new" onClick={newDeployment}>
                <span className="depl-plus">+</span>
                <span className="muted dim">new deployment</span>
              </button>
            </div>

            <div className="depl-layout">
              <div className="depl-timeline">
                {selected ? (
                  <>
                    {/* New version belongs to the timeline, not to the card of
                        editable fields: it acts on versions, and as a primary
                        button beside the name it outranked Save. */}
                    <div className="depl-versions-bar">
                      <span className="card-subtitle depl-versions-title">
                        {selected.versions.length} version{selected.versions.length === 1 ? "" : "s"}
                      </span>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => void newVersion()}
                        disabled={composing}
                      >
                        {composing ? "Creating…" : "New version"}
                      </button>
                    </div>
                    <div className="version-timeline">
                      {selected.versions.map((v) => {
                        const chans = selected.channels.filter((c) => c.deployment_version_id === v.id);
                        return (
                          <div
                            key={v.id}
                            className={`version-row${versionId === v.id ? " active" : ""}`}
                            onClick={() => setVersionId(v.id)}
                            title={v.comment || undefined}
                          >
                            <div className="version-head">
                              <strong>v{v.version_no}</strong>
                              <StatusPill status={v.status} />
                              {chans.map((c) => (
                                <span key={c.name} className="pill ok">{c.name}</span>
                              ))}
                              <span className="muted dim">{fmtWhen(v.created_at)}</span>
                            </div>
                            <div className="version-changes muted">
                              {v.changes?.summary ?? ""}
                              {v.file_set ? ` · berryware ${v.file_set.label}` : ""}
                              {v.artwork_set ? ` · artwork ${v.artwork_set.label}` : ""}
                            </div>
                            {/* The note is NOT repeated here. Seven versions of
                                one deployment share an opening sentence, so a
                                clipped copy per row distinguished nothing and
                                cost a line each — the changed summary above is
                                what tells them apart. It is on the row's title,
                                and in full on the version card. */}
                            {/* Only a DRAFT has actions now. The published rows
                                carried → production and → bench, which pointed
                                a channel a BATCH could follow — and no batch in
                                the database follows one, so the pair moved a
                                label and cost 40 px on every row (user decision
                                2026-09-17). `promote` and `setDeploymentChannel`
                                went with them; the channels themselves are
                                untouched and still drawn as pills. An empty
                                action row is rendered for nobody, so it is
                                conditional. */}
                            {v.status === "draft" ? (
                              <div className="btn-row version-actions">
                                  <button
                                    type="button"
                                    className="btn btn-sm btn-primary"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      void publishDraft(v);
                                    }}
                                  >
                                    Publish
                                  </button>
                                  <button
                                    type="button"
                                    className="btn btn-sm row-del"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      void discard(v);
                                    }}
                                  >
                                    Discard
                                  </button>
                              </div>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  </>
                ) : null}
              </div>

              <div className="depl-detail">
                {/* The deployment's own fields live with the version they
                    describe now, in the wide column: three of them fit on one
                    line here, and the procedure below gets the rest. */}
                {selected ? (
                  <div className="depl-head">
                    {draft ? (
                      <>
                        {/* Name, chip and kind on one line. They are three short
                            values and a row each made this card taller than the
                            timeline beside it. The hints that used to sit under
                            every box are ⓘ markers on the labels — a permanent
                            instruction under a field called "Chip" is read once
                            and then costs a line forever. */}
                        <FieldRow>
                          <Field label="Name" className="depl-field-wide">
                            <input
                              ref={nameRef}
                              className="text"
                              value={draft.name}
                              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                            />
                          </Field>
                          {/* A dropdown, not a box. The platform already knows
                              which parts it supports (`CHIPS` in
                              routers/flasher.py, served by /meta) and the
                              validator refuses a version whose transport does
                              not match its chip — so a free-text field could
                              only ever produce a typo that fails at publish
                              (user request 2026-09-17). The blank option stays:
                              a marking or test deployment legitimately has no
                              chip, and `Dongle_V2 test` is one. */}
                          <Field
                            label={<>Chip <InfoTip>The chip family esptool is told to expect. Only the parts the platform supports are listed; a mark or test procedure may have none.</InfoTip></>}
                            className="depl-field-chip"
                          >
                            <select
                              className="text mono"
                              value={draft.chip}
                              onChange={(e) => setDraft({ ...draft, chip: e.target.value })}
                            >
                              <option value="">— none —</option>
                              {(meta?.chips ?? []).map((c) => (
                                <option key={c} value={c}>{c}</option>
                              ))}
                              {/* A chip stored before it left the list still
                                  shows, rather than silently reading as none. */}
                              {draft.chip && !(meta?.chips ?? []).includes(draft.chip) ? (
                                <option value={draft.chip}>{draft.chip} (unknown)</option>
                              ) : null}
                            </select>
                          </Field>
                          <Field
                            label={<>Kind <InfoTip>Decides which bench offers this procedure, and the bench reads the kind rather than the name. flash programs the device; test judges it; mark engraves and labels it.</InfoTip></>}
                            className="depl-field-kind"
                          >
                            <select
                              className="text"
                              value={draft.kind}
                              onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
                            >
                              {KIND_OPTIONS.map((k) => (
                                <option key={k.value} value={k.value}>{k.label}</option>
                              ))}
                            </select>
                          </Field>
                          {draft.kind === "test" ? (
                            <CheckField
                              checked={draft.active}
                              onChange={(v) => setDraft({ ...draft, active: v })}
                              title="New batches of this project are created with “units must pass the test” ticked. Each batch can still be changed, and devices already made keep the rule they were made under."
                            >
                              New batches must pass this test
                            </CheckField>
                          ) : null}
                        </FieldRow>
                        <Field
                          label={<>Description <InfoTip>What this procedure is for, in a sentence. Shown on the bench beside the version you are about to run.</InfoTip></>}
                        >
                          <AutoTextarea
                            className="depl-desc-box"
                            rows={2}
                            value={draft.description}
                            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                          />
                        </Field>
                        {/* Under the description, because it answers "what is
                            this deployment wired to" — which used to have no
                            answer at the deployment level at all: the link
                            lived only on each version, chosen three screens
                            into the composer (user question 2026-09-17). */}
                        <Field
                          label={
                            <>
                              Parameters{" "}
                              <InfoTip>
                                The set this deployment works against. A NEW version starts from
                                it; a version already published keeps the set it was made with, so
                                changing this never rewrites what a device was given. Edit the
                                values on the Parameters page.
                              </InfoTip>
                            </>
                          }
                          hint={
                            paramKeys.length ? (
                              <>
                                supplies <span className="mono">
                                  {paramKeys.map((k) => `{${k}}`).join(" ")}
                                </span>
                              </>
                            ) : draft.paramSetId === -1 ? (
                              "none — a procedure that interpolates {SSId1} or {MqttHost} cannot be published"
                            ) : undefined
                          }
                        >
                          <select
                            className="text"
                            value={draft.paramSetId}
                            onChange={(e) =>
                              setDraft({ ...draft, paramSetId: Number(e.target.value) })
                            }
                          >
                            <option value={-1}>— no parameter set —</option>
                            {paramSets.map((ps) => (
                              <option key={ps.id} value={ps.id}>
                                {ps.name} ({ps.keys.length} keys)
                              </option>
                            ))}
                          </select>
                        </Field>
                        <div className="depl-settings">
                          {dirty ? (
                            <>
                              <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                onClick={() => void saveDraft()}
                                disabled={saving || !draft.name.trim()}
                              >
                                {saving ? "Saving…" : "Save"}
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => setDraft(storedDraft(selected))}
                                disabled={saving}
                              >
                                Cancel
                              </button>
                            </>
                          ) : null}
                          <span className="rail-spacer" />
                          <button
                            type="button"
                            className="btn btn-sm row-del"
                            onClick={() => void removeDeployment()}
                            title="Delete this deployment — refused while any programming run records it"
                          >
                            Delete
                          </button>
                        </div>
                      </>
                    ) : null}
                  </div>
                ) : null}
                {versionId ? (
                  <VersionView
                    versionId={versionId}
                    onDiff={setDiffFor}
                    reloadKey={reloadKey}
                    autoEdit={versionId === autoEditId}
                    onEditAsNew={() => void newVersion()}
                    meta={meta}
                    onChanged={() => void refetch()}
                    onGone={() => {
                      setVersionId(selected?.current_version_id ?? null);
                      void refetch();
                    }}
                  />
                ) : (
                  <p className="muted">Pick a version.</p>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {diffFor && selected ? (
        <DiffView versionId={diffFor} versions={selected.versions} onClose={() => setDiffFor(null)} />
      ) : null}
    </div>
  );
}
