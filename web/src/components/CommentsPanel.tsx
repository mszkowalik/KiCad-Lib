import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import {
  addComment,
  deleteComment,
  errorMessage,
  getComments,
  type Comment,
  type CommentTargetKind,
} from "../api";
import { useDialog } from "./Dialog";
import FoldSection, { FOLD_LIMIT, StatChip } from "./FoldSection";
import { Spinner } from "./Ui";
import { localDate, localWhen } from "../format";
import { useLoad } from "./useLoad";

/** Free-form notes (Facebook-style, not versioned) on any entity — the user's
 *  future-reference notebook. Shared by components, symbols and footprints.
 *  Fetched once per target.
 *
 *  It opens when notes exist, unless they exceed `FOLD_LIMIT`. With no note it is
 *  closed too, so that an empty form does not take room on every page. */
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
  const { data: comments, setData: setComments, error: loadError } = useLoad((signal) => {
    setActionError(null);
    setDraft("");
    setAdding(false);
    return getComments(kind, id, signal);
  }, [kind, id]);
  /** "Add note" on a folded list: the form stays open until the person says done. */
  const [adding, setAdding] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const dialog = useDialog();

  const count = comments?.length ?? 0;
  const foldable = count === 0 || count > FOLD_LIMIT;
  const newest = comments?.length ? comments[comments.length - 1].created_at : null;

  useEffect(() => {
    if (adding) box.current?.focus();
  }, [adding]);

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
    <FoldSection
      title="Notes"
      count={count}
      limit={count === 0 ? -1 : FOLD_LIMIT}
      foldKey={`notes:${kind}:${id}`}
      forceOpen={adding}
      chips={
        <>
          {comments === null && loadError === null ? <Spinner /> : null}
          {loadError ? <StatChip tone="err">failed to load</StatChip> : null}
          {newest ? <StatChip n={localDate(newest)}>newest</StatChip> : null}
        </>
      }
      actions={
        foldable && comments !== null ? (
          <button type="button" className="btn btn-sm" onClick={() => setAdding((v) => !v)}>
            {adding ? "Done" : "Add note"}
          </button>
        ) : null
      }
    >
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
                <span className="note-date">{localWhen(c.created_at)}</span>
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
          ref={box}
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
    </FoldSection>
  );
}
