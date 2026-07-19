/** Free-form project notes — same pattern as component comments. */
import { useEffect, useState } from "react";
import {
  addProjectNote,
  deleteProjectNote,
  errorMessage,
  getProjectNotes,
  isAbortError,
  type ProjectNoteRow,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";

interface Props {
  projectId: number;
  /** Currently selected snapshot — recorded as the note's commit context.
   *  The list itself ALWAYS shows every note regardless of selection. */
  snapshotId: number | null;
}

export default function NotesTab({ projectId, snapshotId }: Props) {
  const [notes, setNotes] = useState<ProjectNoteRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const load = (signal?: AbortSignal) => {
    getProjectNotes(projectId, signal)
      .then((rows) => {
        setNotes(rows);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  };

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const submit = () => {
    if (!draft.trim()) return;
    setSaving(true);
    addProjectNote(projectId, draft.trim(), snapshotId)
      .then(() => {
        setDraft("");
        setSaving(false);
        load();
      })
      .catch((err) => {
        setError(errorMessage(err));
        setSaving(false);
      });
  };

  return (
    <div className="notes-panel">
      {error ? <ErrorBanner message={error} /> : null}
      {notes === null && !error ? <Spinner label="Loading notes" /> : null}
      <div className="note-form">
        <textarea
          className="note-textarea"
          value={draft}
          placeholder="Anything worth keeping about this project — supplier quotes, decisions, links…"
          onChange={(e) => setDraft(e.target.value)}
        />
        <div className="btn-row">
          <button className="btn btn-primary btn-sm" disabled={saving || !draft.trim()} onClick={submit}>
            {saving ? "Saving…" : "Add note"}
          </button>
        </div>
      </div>
      <div className="notes-list">
        {notes?.map((n) => (
          <div key={n.id} className="note">
            <div className="note-head">
              <span className="note-author">{n.author}</span>
              <span className="note-date">{new Date(n.created_at).toLocaleString()}</span>
              {n.ref_name || n.sha ? (
                <span className="pill neutral" title={n.sha}>
                  @ {n.ref_name || n.sha.slice(0, 8)}
                </span>
              ) : null}
              <button
                className="note-del"
                title="Delete note"
                onClick={() => deleteProjectNote(n.id).then(() => load())}
              >
                ×
              </button>
            </div>
            <div className="note-body">{n.body}</div>
          </div>
        ))}
        {notes !== null && notes.length === 0 ? <p className="muted">No notes yet.</p> : null}
      </div>
    </div>
  );
}
