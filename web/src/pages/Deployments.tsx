/** Deployments — one revision binds firmware + berryware + procedure + params.
 *
 *  Left: the deployments of a project with their channel badges.
 *  Middle: the version timeline, each row saying what changed.
 *  Right: the composed view of the selected version.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createDeployment,
  deleteDeployment,
  errorMessage,
  getFlasherMeta,
  getProjects,
  isAbortError,
  listDeployments,
  publishDeploymentVersion,
  rejectDeploymentVersion,
  setDeploymentChannel,
  updateDeployment,
  type DeploymentRow,
  type DeploymentVersionRow,
  type FlasherMeta,
  type ProjectInfo,
} from "../api";
import { useDialog } from "../components/Dialog";
import Field, { CheckField, FieldRow } from "../components/Field";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import Composer from "../components/flasher/Composer";
import DiffView from "../components/flasher/DiffView";
import VersionView from "../components/flasher/VersionView";
import { fmtWhen } from "../components/flasher/common";
import { useStickyState } from "../useStickyState";

const CHANNELS = ["production", "bench"];
/** The three procedure kinds the API accepts (`DEPLOYMENT_KINDS` in
 *  routers/flasher.py). The bench reads `kind`, never the name. */
const KIND_OPTIONS = [
  { value: "flash", label: "flash — programs the device" },
  { value: "test", label: "test — judges the device" },
  { value: "mark", label: "mark — engraves and labels it" },
];

export default function Deployments() {
  const dialog = useDialog();
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [meta, setMeta] = useState<FlasherMeta | null>(null);
  const [deployments, setDeployments] = useState<DeploymentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("depl.project", null);
  const [selectedId, setSelectedId] = useStickyState<number | null>("depl.selected", null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [composing, setComposing] = useState<{ from: DeploymentVersionRow | null } | null>(null);
  const [diffFor, setDiffFor] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

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

  const reload = useCallback(() => {
    if (!validProject) return;
    const ac = new AbortController();
    listDeployments(validProject, ac.signal)
      .then(setDeployments)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [validProject]);

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

  const newDeployment = async () => {
    if (!validProject) return;
    const name = await dialog.prompt("Deployment name (e.g. Dongle_V3 production):", {
      title: "New deployment",
    });
    if (!name) return;
    const chip = (await dialog.prompt("Chip (esp32 / esp32c6):", { title: "New deployment" })) ?? "";
    try {
      const res = await createDeployment(validProject, { name, chip });
      setSelectedId(res.id);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  /** Every field of the deployment itself — name, description, chip, kind,
   *  the test default — is edited through this, so a change to one can never
   *  reset another (the API takes the whole row). */
  const patchDeployment = async (patch: Partial<{
    name: string; description: string; chip: string; kind: string; active: boolean;
  }>) => {
    if (!selected) return;
    try {
      await updateDeployment(selected.id, {
        name: selected.name, description: selected.description, chip: selected.chip,
        kind: selected.kind, active: selected.active, ...patch,
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
  type Draft = { name: string; description: string; chip: string; kind: string; active: boolean };
  const storedDraft = (d: DeploymentRow): Draft => ({
    name: d.name, description: d.description, chip: d.chip, kind: d.kind, active: d.active,
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    // A new selection, or a reload after saving, is the stored row again.
    setDraft(selected ? storedDraft(selected) : null);
  }, [selected]);
  const dirty = !!selected && !!draft
    && (Object.keys(draft) as (keyof Draft)[]).some((k) => draft[k] !== storedDraft(selected)[k]);
  const saveDraft = async () => {
    if (!selected || !draft || !draft.name.trim()) return;
    setSaving(true);
    try {
      await patchDeployment({ ...draft, name: draft.name.trim(), chip: draft.chip.trim() });
    } finally {
      setSaving(false);
    }
  };

  /** The API is the authority: it refuses while any programming run records
   *  this deployment, so a cleanup can never orphan device history. */
  const removeDeployment = async () => {
    if (!selected) return;
    if (!(await dialog.confirm(
      `Delete "${selected.name}" and its ${selected.versions.length} version(s)? `
      + "Firmware and berryware stay in the project pool. Refused if any programming run "
      + "records this deployment.",
      { title: "Delete deployment", tone: "danger", confirmLabel: "Delete" },
    ))) return;
    try {
      await deleteDeployment(selected.id);
      setSelectedId(null);
      setVersionId(null);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const promote = async (channel: string, version: DeploymentVersionRow) => {
    if (!selected) return;
    const live = selected.channels.find((c) => c.name === channel);
    const msg = live?.version_no
      ? `Point "${channel}" at v${version.version_no}? It currently runs v${live.version_no}.`
      : `Point "${channel}" at v${version.version_no}?`;
    if (!(await dialog.confirm(msg, {
      title: `Channel ${channel}`, tone: "ok", confirmLabel: "Point it",
    }))) return;
    try {
      await setDeploymentChannel(selected.id, channel, version.id);
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
          <button type="button" className="btn btn-sm" onClick={newDeployment}>New deployment</button>
          <span className="toolbar-total">
            one version = firmware + berryware + procedure + parameters
          </span>
        </div>
        {error ? <ErrorBanner message={error} /> : null}

        {deployments === null ? (
          <Spinner label="Loading deployments…" />
        ) : deployments.length === 0 ? (
          <p className="muted">No deployments in this project yet.</p>
        ) : (
          <div className="depl-layout">
            <div className="depl-list">
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
                </button>
              ))}
            </div>

            <div className="depl-timeline">
              {selected ? (
                <>
                  <div className="depl-head">
                    {draft ? (
                      <>
                        <div className="depl-head-row">
                          <Field label="Name" className="depl-field-wide">
                            <input
                              className="text"
                              value={draft.name}
                              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                            />
                          </Field>
                          <button
                            type="button"
                            className="btn btn-primary btn-sm depl-new-version"
                            onClick={() =>
                              setComposing({
                                from: selected.versions.find(
                                  (v) => v.id === (selected.current_version_id ?? selected.versions[0]?.id),
                                ) ?? null,
                              })
                            }
                          >
                            New version
                          </button>
                        </div>
                        <Field label="Description" hint="What this procedure is for, in a sentence.">
                          <textarea
                            className="text depl-desc-box"
                            rows={2}
                            value={draft.description}
                            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                          />
                        </Field>
                        <FieldRow>
                          <Field
                            label="Kind"
                            hint="Decides which bench offers this procedure."
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
                          <Field label="Chip" hint="esp32, esp32c6, …">
                            <input
                              className="text mono"
                              value={draft.chip}
                              onChange={(e) => setDraft({ ...draft, chip: e.target.value })}
                            />
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
                            onClick={removeDeployment}
                            title="Delete this deployment — refused while any programming run records it"
                          >
                            Delete
                          </button>
                        </div>
                      </>
                    ) : null}
                  </div>
                  <div className="version-timeline">
                    {selected.versions.map((v) => {
                      const chans = selected.channels.filter((c) => c.deployment_version_id === v.id);
                      return (
                        <div
                          key={v.id}
                          className={`version-row${versionId === v.id ? " active" : ""}`}
                          onClick={() => setVersionId(v.id)}
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
                            {v.files_label ? ` · berryware ${v.files_label}` : ""}
                          </div>
                          <div className="version-comment dim">{v.comment}</div>
                          <div className="btn-row version-actions">
                            {v.status === "published"
                              ? CHANNELS.map((c) => (
                                  <button
                                    key={c}
                                    type="button"
                                    className="btn btn-sm"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      void promote(c, v);
                                    }}
                                  >
                                    → {c}
                                  </button>
                                ))
                              : null}
                            {v.status === "draft" ? (
                              <>
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
                                  className="btn btn-sm"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setComposing({ from: v });
                                  }}
                                >
                                  Continue editing
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
                              </>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              ) : null}
            </div>

            <div className="depl-detail">
              {versionId ? (
                <VersionView versionId={versionId} onDiff={setDiffFor} reloadKey={reloadKey} />
              ) : (
                <p className="muted">Pick a version.</p>
              )}
            </div>
          </div>
        )}
      </div>

      {composing && selected ? (
        <Composer
          deployment={selected}
          fromVersion={composing.from}
          meta={meta}
          onClose={(published) => {
            setComposing(null);
            if (published) {
              setReloadKey((k) => k + 1);
              reload();
            }
          }}
        />
      ) : null}
      {diffFor && selected ? (
        <DiffView versionId={diffFor} versions={selected.versions} onClose={() => setDiffFor(null)} />
      ) : null}
    </div>
  );
}
