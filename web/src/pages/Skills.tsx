import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createSkill,
  deleteSkill,
  errorMessage,
  getSkill,
  getSkills,
  getSkillVersion,
  isAbortError,
  saveSkill,
  saveSkillDescription,
  type SkillDetail,
  type SkillListItem,
  type SkillVersionDetail,
} from "../api";
import { useDialog } from "../components/Dialog";
import { ErrorBanner, Spinner } from "../components/Ui";
import { useStickyState } from "../useStickyState";

function fmtSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} kB`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** Draft state for a not-yet-created skill (via "New skill"). */
interface NewSkillDraft {
  name: string;
}

export default function Skills() {
  const [list, setList] = useState<SkillListItem[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  // Selection lives in the URL so a skill is linkable — an agent's answer, a
  // chat message or a bookmark lands on the right document; the sticky copy
  // only restores the last skill on a bare /library/skills visit.
  const params = useParams();
  const navigate = useNavigate();
  const urlId = params.id != null ? Number(params.id) : null;
  const [stickyId, setStickyId] = useStickyState<number | null>("skills:selectedId", null);
  const selectedId = urlId ?? stickyId;
  const setSelectedId = useCallback(
    (next: number | null | ((prev: number | null) => number | null)) => {
      const value = typeof next === "function" ? next(selectedId) : next;
      setStickyId(value);
      navigate(value == null ? "/library/skills" : `/library/skills/${value}`, {
        replace: true,
      });
    },
    [navigate, selectedId, setStickyId],
  );

  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  /** null = current version (editable); a number = viewing an old version. */
  const [viewNo, setViewNo] = useState<number | null>(null);
  const [viewVersion, setViewVersion] = useState<SkillVersionDetail | null>(null);
  const [viewLoading, setViewLoading] = useState(false);

  const [editorText, setEditorText] = useState("");
  /** Unversioned when-to-use line — saved separately from the editor text. */
  const [descText, setDescText] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedBanner, setSavedBanner] = useState<string | null>(null);

  const [newDraft, setNewDraft] = useState<NewSkillDraft | null>(null);
  const dialog = useDialog();

  // Content and description are saved through different endpoints (the
  // description is not versioned), so track their dirtiness separately.
  const contentDirty =
    newDraft !== null ? editorText.trim() !== "" : detail !== null && editorText !== detail.content;
  const descDirty =
    newDraft !== null ? descText.trim() !== "" : detail !== null && descText !== detail.description;
  const dirty = contentDirty || descDirty;

  const loadList = (signal?: AbortSignal, selectFirst = false) => {
    getSkills(signal)
      .then((rows) => {
        setList(rows);
        setListError(null);
        if (selectFirst) {
          setSelectedId((prev) => prev ?? (rows.length > 0 ? rows[0].id : null));
        }
      })
      .catch((err) => {
        if (!isAbortError(err)) setListError(errorMessage(err));
      });
  };

  useEffect(() => {
    const ctrl = new AbortController();
    loadList(ctrl.signal, true);
    return () => ctrl.abort();
  }, []);

  // Load skill detail when the selection changes (not in new-draft mode).
  useEffect(() => {
    if (selectedId === null || newDraft !== null) return;
    const ctrl = new AbortController();
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    setViewNo(null);
    setViewVersion(null);
    setSaveError(null);
    setSavedBanner(null);
    getSkill(selectedId, ctrl.signal)
      .then((d) => {
        setDetail(d);
        setEditorText(d.content);
        setDescText(d.description);
        setDetailLoading(false);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setDetailError(errorMessage(err));
        setDetailLoading(false);
      });
    return () => ctrl.abort();
  }, [selectedId, newDraft]);

  // Load an old version's content when viewing it.
  useEffect(() => {
    if (selectedId === null || viewNo === null) {
      setViewVersion(null);
      return;
    }
    const ctrl = new AbortController();
    setViewVersion(null);
    setViewLoading(true);
    getSkillVersion(selectedId, viewNo, ctrl.signal)
      .then((v) => {
        setViewVersion(v);
        setViewLoading(false);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setSaveError(errorMessage(err));
        setViewLoading(false);
      });
    return () => ctrl.abort();
  }, [selectedId, viewNo]);

  const confirmDiscard = async (): Promise<boolean> =>
    !dirty ||
    dialog.confirm("Discard unsaved changes?", {
      title: "Unsaved changes",
      confirmLabel: "Discard",
      tone: "danger",
    });

  const selectSkill = async (id: number) => {
    if (id === selectedId && newDraft === null) return;
    if (!(await confirmDiscard())) return;
    setNewDraft(null);
    setSelectedId(id);
  };

  const selectVersion = async (no: number | null) => {
    if (no === viewNo) return;
    // Only leaving the editable current view can lose edits.
    if (viewNo === null && !(await confirmDiscard())) return;
    if (viewNo === null && detail !== null) {
      setEditorText(detail.content);
      setDescText(detail.description);
    }
    setViewNo(no);
    setSavedBanner(null);
    setSaveError(null);
  };

  const startNewSkill = async () => {
    if (!(await confirmDiscard())) return;
    const name = await dialog.prompt("New skill name:", {
      title: "New skill",
      confirmLabel: "Create",
    });
    if (name === null) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    if (list?.some((s) => s.name === trimmed)) {
      setSaveError(`Skill ${trimmed} already exists.`);
      return;
    }
    setNewDraft({ name: trimmed });
    setDetail(null);
    setDetailError(null);
    setViewNo(null);
    setViewVersion(null);
    setEditorText("");
    setDescText("");
    setSaveError(null);
    setSavedBanner(null);
  };

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setSaveError(null);
    setSavedBanner(null);
    try {
      if (newDraft !== null) {
        const res = await createSkill(newDraft.name, editorText, descText);
        setNewDraft(null);
        setSelectedId(res.id);
        setSavedBanner(`Created ${res.name} as v${res.current_version_no}`);
        loadList();
      } else if (selectedId !== null) {
        // Only the changed half is written — editing just the description must
        // not mint a content version identical to the current one.
        const versioned = contentDirty ? await saveSkill(selectedId, editorText) : null;
        if (descDirty) await saveSkillDescription(selectedId, descText);
        const d = await getSkill(selectedId);
        setDetail(d);
        setEditorText(d.content);
        setDescText(d.description);
        setViewNo(null);
        setSavedBanner(
          versioned ? `Saved as v${versioned.current_version_no}` : "Description saved",
        );
        loadList();
      }
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const restore = async () => {
    if (selectedId === null || viewVersion === null || saving) return;
    const confirmed = await dialog.confirm(
      `Restore v${viewVersion.version_no} as the new current version of ${viewVersion.name}?`,
      { title: "Restore version", confirmLabel: "Restore" },
    );
    if (!confirmed) return;
    setSaving(true);
    setSaveError(null);
    try {
      const res = await saveSkill(selectedId, viewVersion.content);
      const d = await getSkill(selectedId);
      setDetail(d);
      setEditorText(d.content);
      setDescText(d.description);
      setViewNo(null);
      setSavedBanner(`Restored v${viewVersion.version_no} as v${res.current_version_no}`);
      loadList();
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const removeSkill = async () => {
    if (selectedId === null || detail === null || saving) return;
    const confirmed = await dialog.confirm(
      `Delete ${detail.name} and all ${detail.versions.length} of its versions? This cannot be undone.`,
      { title: "Delete skill", confirmLabel: "Delete", tone: "danger" },
    );
    if (!confirmed) return;
    setSaving(true);
    setSaveError(null);
    try {
      await deleteSkill(selectedId);
      setDetail(null);
      setSelectedId(null);
      setEditorText("");
      setDescText("");
      setViewNo(null);
      setSavedBanner(`Deleted ${detail.name}`);
      loadList();
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  // ------------------------------------------------------------- rendering

  const viewingOld = viewNo !== null && detail !== null;

  const descriptionField = (readOnly: boolean) => (
    <div className="skill-desc">
      <label className="card-title" htmlFor="skill-description">
        When to use — description
      </label>
      <input
        id="skill-description"
        className="text"
        value={descText}
        readOnly={readOnly}
        maxLength={500}
        placeholder="One line telling an agent when this document is relevant…"
        onChange={(e) => setDescText(e.target.value)}
        spellCheck={false}
      />
      <span className="rail-hint">
        Goes into Jaravis's system prompt and becomes the Claude Code skill's{" "}
        <span className="mono">description</span> — all an agent sees before deciding to open
        the document. Not versioned; saved on its own. {descText.length}/500
      </span>
    </div>
  );
  const editorValue = viewingOld ? (viewVersion?.content ?? "") : editorText;
  const versions = detail ? [...detail.versions].sort((a, b) => a.version_no - b.version_no) : [];

  return (
    <div className="skills-layout">
      <aside className="skills-list">
        {listError ? <ErrorBanner message={`Skills failed to load: ${listError}`} /> : null}
        {list === null && listError === null ? (
          <div className="sidebar-loading">
            <Spinner label="Loading skills" />
          </div>
        ) : null}
        {list?.map((s) => (
          <button
            key={s.id}
            type="button"
            className={
              "skill-item" + (s.id === selectedId && newDraft === null ? " selected" : "")
            }
            title={s.description || undefined}
            onClick={() => selectSkill(s.id)}
          >
            <span className="mono skill-name">{s.name}</span>
            <span className="skill-meta">
              v{s.current_version_no ?? "?"} · {fmtSize(s.size)} ·{" "}
              {s.updated_at ? new Date(s.updated_at).toLocaleDateString() : "—"}
            </span>
          </button>
        ))}
        {newDraft !== null ? (
          <div className="skill-item selected">
            <span className="mono skill-name">{newDraft.name}</span>
            <span className="skill-meta">new — not saved yet</span>
          </div>
        ) : null}
        <div className="skills-list-footer">
          <button type="button" className="btn btn-sm" onClick={startNewSkill}>
            New skill
          </button>
        </div>
      </aside>

      <main className="skill-editor">
        {detailError ? <ErrorBanner message={`Skill failed to load: ${detailError}`} /> : null}
        {saveError ? <ErrorBanner message={saveError} /> : null}
        {savedBanner ? (
          <div className="banner-ok" role="status">
            {savedBanner}
          </div>
        ) : null}

        {detailLoading ? (
          <div className="block-loading">
            <Spinner label="Loading skill" />
          </div>
        ) : null}

        {newDraft !== null ? (
          <>
            <div className="skill-head">
              <h1 className="mono skill-title">{newDraft.name}</h1>
              <span className="rail-hint">new skill — not saved yet</span>
            </div>
            {descriptionField(false)}
            <textarea
              className="text skill-textarea"
              value={editorText}
              onChange={(e) => setEditorText(e.target.value)}
              placeholder="Write the skill content (markdown)…"
              aria-label={`Content of new skill ${newDraft.name}`}
              spellCheck={false}
            />
            <div className="skill-actions">
              <button
                type="button"
                className="btn btn-accent"
                disabled={saving || editorText.trim() === ""}
                onClick={() => void save()}
              >
                {saving ? "Creating…" : "Create skill"}
              </button>
              <button
                type="button"
                className="btn"
                disabled={saving}
                onClick={async () => {
                  if (await confirmDiscard()) setNewDraft(null);
                }}
              >
                Cancel
              </button>
              <span className="muted skill-caption">
                Jaravis reads the current version of every skill on each chat — edits apply
                immediately.
              </span>
            </div>
          </>
        ) : detail !== null ? (
          <>
            <div className="skill-head">
              <h1 className="mono skill-title">{detail.name}</h1>
            </div>
            {descriptionField(viewingOld)}
            <div className="version-rail" role="tablist" aria-label="Skill versions">
              {versions.map((v) => {
                const isCurrent = v.version_no === detail.current_version_no;
                const isSelected = viewNo === null ? isCurrent : v.version_no === viewNo;
                const isDraft = v.status === "draft";
                const isRejected = v.status === "rejected";
                // Drafts and rejections are HISTORY: nothing has filed one since
                // skills started publishing directly (2026-08-24). They stay
                // readable, and restoring one publishes its text like any other.
                const statusNote = isDraft
                  ? " — draft, never published"
                  : isRejected
                    ? " — rejected"
                    : "";
                const commentNote = v.comment ? ` — ${v.comment}` : "";
                return (
                  <button
                    key={v.version_no}
                    type="button"
                    role="tab"
                    aria-selected={isSelected}
                    className={
                      "vchip" +
                      (isSelected ? " selected" : "") +
                      (isCurrent ? " current" : "") +
                      (isDraft ? " draft" : "") +
                      (isRejected ? " rejected" : "")
                    }
                    title={`v${v.version_no} — ${fmtDate(v.created_at)} by ${v.created_by ?? "?"} (${fmtSize(v.size)})${isCurrent ? " (current)" : ""}${statusNote}${commentNote}`}
                    onClick={() => selectVersion(isCurrent ? null : v.version_no)}
                  >
                    v{v.version_no}
                  </button>
                );
              })}
            </div>

            {viewingOld ? (
              <div className="banner-warn skill-view-banner" role="status">
                viewing v{viewNo} — current is v{detail.current_version_no}
                <button
                  type="button"
                  className="btn btn-sm restore-btn"
                  disabled={saving || viewVersion === null}
                  onClick={() => void restore()}
                >
                  {saving ? "Restoring…" : "Restore this version"}
                </button>
              </div>
            ) : null}

            {viewingOld && viewLoading ? (
              <div className="block-loading">
                <Spinner label={`Loading v${viewNo}`} />
              </div>
            ) : (
              <textarea
                className="text skill-textarea"
                value={editorValue}
                readOnly={viewingOld}
                onChange={(e) => {
                  if (!viewingOld) setEditorText(e.target.value);
                }}
                aria-label={`Content of ${detail.name}`}
                spellCheck={false}
              />
            )}

            {!viewingOld ? (
              <div className="skill-actions">
                <button
                  type="button"
                  className="btn btn-accent"
                  disabled={saving || !dirty || editorText.trim() === ""}
                  onClick={() => void save()}
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={saving || !dirty}
                  onClick={() => {
                    setEditorText(detail.content);
                    setDescText(detail.description);
                  }}
                >
                  Discard changes
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={saving}
                  onClick={() => void removeSkill()}
                >
                  Delete skill
                </button>
                <span className="muted skill-caption">
                  Jaravis reads the current version of every skill on each chat — edits apply
                  immediately.
                </span>
              </div>
            ) : null}
          </>
        ) : !detailLoading && list !== null && list.length === 0 ? (
          <p className="muted">No skills yet — create one.</p>
        ) : null}

        <p className="muted dim">
          Using these skills in Claude Code is set up once — see{" "}
          <Link to="/setup">Setup</Link>.
        </p>
      </main>
    </div>
  );
}
