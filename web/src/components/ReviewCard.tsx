import { useEffect, useState } from "react";
import {
  errorMessage,
  getReviewDetail,
  isAbortError,
  recordReviewCheck,
  revokeReviewCheck,
  type ChecklistItemDef,
  type ReviewCheckAnswer,
  type ReviewDetail,
  type ReviewKind,
} from "../api";
import { useDialog } from "./Dialog";
import { ErrorBanner, ReviewPill, Spinner } from "./Ui";

/** Documentation verification for one component / symbol / footprint.
 *
 * The claim is different from a production sign-off: a check says "this data
 * matches the documentation", per checklist item, with per-item provenance
 * (machine / agent / human). Checks are cumulative — the card walks the
 * resolved checklist, pre-filled from everything already answered, and a save
 * writes a follow-up record on top. Nothing here blocks anything.
 */
export default function ReviewCard({
  kind,
  id,
  onChange,
}: {
  kind: ReviewKind;
  id: number;
  onChange?: (detail: ReviewDetail) => void;
}) {
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [answers, setAnswers] = useState<Record<string, ReviewCheckAnswer>>({});
  const [note, setNote] = useState("");
  const [showItems, setShowItems] = useState(false);
  const dialog = useDialog();

  useEffect(() => {
    const ctrl = new AbortController();
    setDetail(null);
    setLoadError(null);
    setActionError(null);
    setVerifying(false);
    setAnswers({});
    getReviewDetail(kind, id, ctrl.signal)
      .then(setDetail)
      .catch((err) => {
        if (!isAbortError(err)) setLoadError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [kind, id]);

  const apply = (next: ReviewDetail) => {
    setDetail(next);
    onChange?.(next);
  };

  const answer = async (item: ChecklistItemDef, result: "checked" | "na" | "skipped" | "flagged") => {
    let itemNote: string | undefined;
    if (result !== "checked") {
      const why = await dialog.prompt(
        result === "na"
          ? `Why does "${item.text}" not apply?`
          : result === "flagged"
            ? `What is wrong with "${item.text}"? (goes on the second-pass list)`
            : `Why can "${item.text}" not be verified?`,
        { title: result === "na" ? "Not applicable" : result === "flagged" ? "Flag an issue" : "Skipped" },
      );
      if (why === null) return;
      itemNote = why.trim() || undefined;
      if (result === "flagged" && !itemNote) {
        await dialog.alert("A flag needs a note — it IS the second-pass worklist entry.", {
          title: "Flag an issue",
        });
        return;
      }
    }
    setAnswers((prev) => ({ ...prev, [item.key]: { key: item.key, result, note: itemNote } }));
  };

  const save = async () => {
    const items = Object.values(answers);
    if (items.length === 0) {
      setActionError("Answer at least one item, or use Mark checked.");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      const next = await recordReviewCheck(kind, id, { items, note: note.trim() || undefined });
      apply(next);
      setVerifying(false);
      setAnswers({});
      setNote("");
      if (next.blocked_items && next.blocked_items.length > 0) {
        await dialog.alert(
          `Kept the existing higher-tier answers for: ${next.blocked_items.join(", ")}`,
          { title: "Some answers were kept" },
        );
      }
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const oneClick = async () => {
    if (
      !(await dialog.confirm(
        "Record that you checked this against its documentation, without walking the checklist?",
        { title: "Mark checked", confirmLabel: "Mark checked", tone: "ok" },
      ))
    )
      return;
    setBusy(true);
    setActionError(null);
    try {
      apply(await recordReviewCheck(kind, id, { one_click: true, note: note.trim() || undefined }));
      setNote("");
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    const reason = await dialog.prompt("Why is the verification being taken back?", {
      title: "Revoke verification",
    });
    if (reason === null || !reason.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      apply(await revokeReviewCheck(kind, id, reason.trim()));
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (loadError) {
    return (
      <section className="card pad meta-card">
        <h3 className="card-title">Verification</h3>
        <ErrorBanner message={`Verification state failed to load: ${loadError}`} />
      </section>
    );
  }
  if (!detail) {
    return (
      <section className="card pad meta-card">
        <h3 className="card-title">Verification</h3>
        <Spinner label="Loading verification state" />
      </section>
    );
  }

  const openCount = detail.items.filter((i) => !i.answered || i.answered.result === "skipped").length;

  return (
    <section className="card pad meta-card">
      <h3 className="card-title">
        Verification <ReviewPill state={detail.state} provenance={detail.provenance} />
      </h3>

      <p className="muted">{explain(detail, openCount)}</p>

      {actionError ? <ErrorBanner message={actionError} /> : null}

      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={() => setShowItems((v) => !v)}>
          {showItems ? "Hide checklist" : `Checklist (${detail.items.length})`}
        </button>
        {!verifying ? (
          <>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={busy || detail.version_id === null}
              onClick={() => {
                setVerifying(true);
                setShowItems(true);
              }}
            >
              Verify…
            </button>
            <button
              type="button"
              className="btn btn-ok btn-sm"
              disabled={busy || detail.version_id === null}
              onClick={() => void oneClick()}
              title="Record a human check without the item breakdown"
            >
              Mark checked
            </button>
            {detail.record ? (
              <button type="button" className="btn btn-danger btn-sm" disabled={busy} onClick={() => void revoke()}>
                Revoke
              </button>
            ) : null}
          </>
        ) : (
          <>
            <input
              className="text row-input"
              value={note}
              disabled={busy}
              placeholder="What documentation was used (optional)"
              onChange={(e) => setNote(e.target.value)}
            />
            <button type="button" className="btn btn-ok btn-sm" disabled={busy} onClick={() => void save()}>
              Save ({Object.keys(answers).length})
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={busy}
              onClick={() => {
                setVerifying(false);
                setAnswers({});
              }}
            >
              Cancel
            </button>
          </>
        )}
      </div>

      {showItems ? (
        <ul className="notes-list">
          {detail.items.map((item) => {
            const pending = answers[item.key];
            const a = item.answered;
            return (
              <li key={item.key} className="note">
                <div className="note-head">
                  <span title={item.hint ?? item.key}>{item.text}</span>{" "}
                  {pending ? (
                    <span className="pill ok" title="unsaved answer">
                      {pending.result} ✎
                    </span>
                  ) : a ? (
                    <span
                      className={`pill ${RESULT_TONE[a.result] ?? "neutral"}`}
                      title={`${a.actor_type} · ${a.actor}${a.note ? ` — ${a.note}` : ""}`}
                    >
                      {a.result}
                      {a.actor_type !== "human" ? ` (${a.actor_type})` : ""}
                    </span>
                  ) : (
                    <span className="pill neutral">open</span>
                  )}
                  {item.machine ? (
                    <span className="badge" title="answered automatically on publish">
                      auto
                    </span>
                  ) : null}
                </div>
                {a?.note && !pending ? <p className="muted">{a.note}</p> : null}
                {verifying && (!item.machine || a?.result === "failed") ? (
                  <div className="btn-row">
                    <button type="button" className="btn btn-sm" onClick={() => void answer(item, "checked")}>
                      Checked
                    </button>
                    <button type="button" className="btn btn-sm" onClick={() => void answer(item, "na")}>
                      N/A
                    </button>
                    <button type="button" className="btn btn-sm" onClick={() => void answer(item, "skipped")}>
                      Skip
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-danger"
                      onClick={() => void answer(item, "flagged")}
                      title="Verified and found wrong — record the defect without fixing it"
                    >
                      Flag
                    </button>
                  </div>
                ) : null}
              </li>
            );
          })}
          {detail.extra_items.map((item) => (
            <li key={item.key} className="note">
              <div className="note-head">
                <span className="mono">{item.key}</span> <span>{item.text}</span>{" "}
                <span className={`pill ${RESULT_TONE[item.result] ?? "neutral"}`}>{item.result}</span>
              </div>
              {item.note ? <p className="muted">{item.note}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

const RESULT_TONE: Record<string, string> = {
  checked: "ok",
  na: "neutral",
  skipped: "warn",
  failed: "err",
  flagged: "err",
};

function explain(d: ReviewDetail, openCount: number): string {
  switch (d.state) {
    case "checked":
      return d.provenance === "human"
        ? "Verified against the documentation, human-confirmed."
        : `Verified against the documentation (${d.provenance ?? "?"}-checked, no human confirmation yet).`;
    case "partial":
      return `Partially verified — ${d.skipped} skipped, ${openCount} item(s) still open.`;
    case "failed":
      return d.flagged
        ? `${d.flagged} item(s) flagged as wrong (second-pass list)${d.failed - d.flagged ? `, ${d.failed - d.flagged} machine check(s) failing` : ""}.`
        : `${d.failed} machine check(s) failing — fix the data and republish, or review the items.`;
    default:
      return "This version has not been verified against its documentation yet.";
  }
}
