import { useEffect, useState, type KeyboardEvent } from "react";
import {
  addComment,
  deleteComment,
  errorMessage,
  getComments,
  isAbortError,
  type Comment,
  type CommentTargetKind,
} from "../api";
import { useDialog } from "./Dialog";
import { Spinner } from "./Ui";

/** Free-form notes (Facebook-style, not versioned) on any entity — the user's
 *  future-reference notebook. Shared by components, symbols and footprints.
 *  Fetched once per target. */
export default function CommentsPanel({
  kind,
  id,
  noun = "item",
}: {
  kind: CommentTargetKind;
  id: number;
  /** Word used in the "Add a note about this …" placeholder. */
  noun?: string;
}) {
  const [comments, setComments] = useState<Comment[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  /** "auto" follows the content (open when any note exists); an explicit
   *  user toggle ("open"/"closed") wins for the rest of the visit. */
  const [openState, setOpenState] = useState<"auto" | "open" | "closed">("auto");
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const dialog = useDialog();

  const open = openState === "open" || (openState === "auto" && (comments?.length ?? 0) > 0);

  useEffect(() => {
    const ctrl = new AbortController();
    setComments(null);
    setLoadError(null);
    setActionError(null);
    setDraft("");
    setOpenState("auto");
    getComments(kind, id, ctrl.signal)
      .then((list) => {
        setComments(list);
      })
      .catch((err) => {
        if (!isAbortError(err)) setLoadError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [kind, id]);

  const submit = async () => {
    const text = draft.trim();
    if (!text || posting) return;
    setPosting(true);
    setActionError(null);
    try {
      const c = await addComment(kind, id, text);
      setComments((prev) => [...(prev ?? []), c]);
      setDraft("");
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setPosting(false);
    }
  };

  const del = async (c: Comment) => {
    const confirmed = await dialog.confirm("Delete this note?", {
      title: "Delete note",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!confirmed) return;
    setBusyId(c.id);
    setActionError(null);
    try {
      await deleteComment(c.id);
      setComments((prev) => (prev ?? []).filter((x) => x.id !== c.id));
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <section className="card notes-panel">
      <button
        type="button"
        className="notes-head"
        aria-expanded={open}
        onClick={() => setOpenState(open ? "closed" : "open")}
      >
        <svg
          className={"chev" + (open ? " open" : "")}
          width="10"
          height="10"
          viewBox="0 0 10 10"
          aria-hidden="true"
        >
          <path d="M3 1.5 L7 5 L3 8.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
        <span>Notes{comments !== null ? ` (${comments.length})` : ""}</span>
        {comments === null && loadError === null ? <Spinner /> : null}
      </button>
      {open ? (
        <>
          {loadError ? (
            <p className="pad-note err-text">Notes failed to load: {loadError}</p>
          ) : comments !== null && comments.length === 0 ? (
            <p className="muted pad-note">No notes yet.</p>
          ) : (
            <ul className="notes-list">
              {(comments ?? []).map((c) => (
                <li key={c.id} className="note">
                  <div className="note-head mono">
                    <span className="note-author">{c.author}</span>
                    <span className="note-date">{new Date(c.created_at).toLocaleString()}</span>
                    <button
                      type="button"
                      className="row-del note-del"
                      disabled={busyId !== null}
                      onClick={() => void del(c)}
                      aria-label="Delete note"
                      title="Delete note"
                    >
                      &#x2715;
                    </button>
                  </div>
                  <div className="note-body">{c.body}</div>
                </li>
              ))}
            </ul>
          )}
          {actionError ? <p className="pad-note err-text">{actionError}</p> : null}
          <div className="note-form">
            <textarea
              className="text note-textarea"
              rows={2}
              placeholder={`Add a note about this ${noun}…`}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              aria-label="Add a note"
            />
            <button
              type="button"
              className="btn btn-sm"
              disabled={posting || draft.trim() === ""}
              onClick={() => void submit()}
            >
              {posting ? "Adding…" : "Add note"}
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}
