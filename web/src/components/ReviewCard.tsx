import { useEffect, useState } from "react";
import {
  errorMessage,
  getReviewDetail,
  isAbortError,
  recordReviewCheck,
  revokeReviewCheck,
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
  label,
  onChange,
}: {
  kind: ReviewKind;
  id: number;
  /** Card heading. Defaults to "Verification" — pass a specific one when a
   *  page shows several cards (the component page verifies the part AND the
   *  two drawings it pins), or every heading reads the same. */
  label?: string;
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
  // A check this part needed that no checklist anticipated. It lives in this
  // subject's record only — the checklist document is untouched, which is what
  // makes it safe to add one without deciding it applies to every part.
  const [customText, setCustomText] = useState("");
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

  // Why a skip happened, as a CODE the health tab can count. 84 free-text
  // notes saying "datasheet is HTML" in different words were one problem
  // wearing 84 hats; a reason makes them one number with one fix.
  const SKIP_REASONS = [
    ["html_datasheet", "datasheet archived as HTML, not a PDF"],
    ["no_document", "no datasheet/documentation available"],
    ["no_land_pattern", "datasheet has no land-pattern drawing"],
    ["ambiguous_doc", "documentation is ambiguous or contradictory"],
    ["other", "other (say what in the note)"],
  ] as const;

  const answer = async (
    item: { key: string; text: string },
    result: "checked" | "na" | "skipped" | "flagged",
  ) => {
    let itemNote: string | undefined;
    let reason: string | undefined;
    if (result === "skipped") {
      const picked = await dialog.select(
        `Why can "${item.text}" not be verified?`,
        SKIP_REASONS.map(([value, label]) => ({ value, label })),
        { title: "Skipped" },
      );
      if (picked === null) return;
      reason = picked;
      const why = await dialog.prompt("Anything to add? (optional)", { title: "Skipped" });
      if (why === null) return;
      itemNote = why.trim() || undefined;
    } else if (result !== "checked") {
      const why = await dialog.prompt(
        result === "na"
          ? `Why does "${item.text}" not apply?`
          : `What is wrong with "${item.text}"? (goes on the second-pass list)`,
        { title: result === "na" ? "Not applicable" : "Flag an issue" },
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
    setAnswers((prev) => ({
      ...prev,
      [item.key]: { key: item.key, result, note: itemNote, text: item.text, reason },
    }));
  };

  /** `custom.<slug>`, unique against the checklist, the recorded extras and
   *  anything already pending — the key is the identity a later record merges
   *  onto, so a collision would silently overwrite a different question. */
  const customKey = (text: string): string => {
    const taken = new Set<string>([
      ...(detail?.items ?? []).map((i) => i.key),
      ...(detail?.extra_items ?? []).map((i) => i.key),
      ...Object.keys(answers),
    ]);
    const slug =
      text
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 40) || "check";
    let key = `custom.${slug}`;
    for (let n = 2; taken.has(key); n += 1) key = `custom.${slug}-${n}`;
    return key;
  };

  const addCustom = async (result: "checked" | "na" | "skipped" | "flagged") => {
    const text = customText.trim();
    if (!text) return;
    await answer({ key: customKey(text), text }, result);
    setCustomText("");
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
      setCustomText("");
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
        <h3 className="card-title">{label ?? "Verification"}</h3>
        <Spinner label="Loading verification state" />
      </section>
    );
  }

  const openCount = detail.items.filter((i) => !i.answered || i.answered.result === "skipped").length;
  // Answers to keys the checklist does not define and the record does not
  // carry yet — they have no row of their own to render in, so they get one.
  const known = new Set([...detail.items.map((i) => i.key), ...detail.extra_items.map((i) => i.key)]);
  const pendingCustom = Object.values(answers).filter((a) => !known.has(a.key));

  return (
    <section className="card pad meta-card">
      <h3 className="card-title">
        {label ?? "Verification"}{" "}
        <ReviewPill state={detail.state} provenance={detail.provenance} />
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
                setCustomText("");
              }}
            >
              Cancel
            </button>
          </>
        )}
      </div>

      {showItems ? (
        <ul className="notes-list">
          {detail.items_carried ? (
            <li className="note muted dim">
              These answers were recorded before the confirmation that set this state — the
              confirmation vouches for the subject as a whole and records no items of its own.
            </li>
          ) : null}
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
                {/* What this answer replaced. Accepting a flag keeps the flag
                    readable — otherwise clearing a defect means deleting the
                    only description of it. */}
                {a?.superseded && !pending ? (
                  <p className="muted dim superseded">
                    was{" "}
                    <span className={`pill ${RESULT_TONE[a.superseded.result] ?? "neutral"}`}>
                      {a.superseded.result}
                    </span>
                    {a.superseded.actor ? ` by ${a.superseded.actor}` : ""}
                    {a.superseded.note ? ` — ${a.superseded.note}` : ""}
                  </p>
                ) : null}
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
                <span>{item.text}</span>{" "}
                <span className={`pill ${RESULT_TONE[item.result] ?? "neutral"}`}>{item.result}</span>
                <span className="badge" title={`Added for this ${detail.kind} only — ${item.key}`}>
                  custom
                </span>
              </div>
              {item.note ? <p className="muted">{item.note}</p> : null}
            </li>
          ))}
          {pendingCustom.map((a) => (
            <li key={a.key} className="note">
              <div className="note-head">
                <span>{a.text}</span>{" "}
                <span className="pill ok" title="unsaved answer">
                  {a.result} ✎
                </span>
                <span className="badge">custom</span>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy}
                  onClick={() =>
                    setAnswers((prev) => {
                      const next = { ...prev };
                      delete next[a.key];
                      return next;
                    })
                  }
                >
                  Remove
                </button>
              </div>
              {a.note ? <p className="muted">{a.note}</p> : null}
            </li>
          ))}
          {verifying ? (
            <li className="note">
              <div className="note-head">
                <input
                  className="text row-input"
                  value={customText}
                  maxLength={200}
                  disabled={busy}
                  placeholder="Add a check of your own — what did you verify?"
                  aria-label="Custom check"
                  onChange={(e) => setCustomText(e.target.value)}
                />
              </div>
              <div className="btn-row">
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy || !customText.trim()}
                  onClick={() => void addCustom("checked")}
                >
                  Checked
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy || !customText.trim()}
                  onClick={() => void addCustom("na")}
                >
                  N/A
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy || !customText.trim()}
                  onClick={() => void addCustom("skipped")}
                >
                  Skip
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  disabled={busy || !customText.trim()}
                  onClick={() => void addCustom("flagged")}
                  title="Verified and found wrong — record the defect without fixing it"
                >
                  Flag
                </button>
                <span className="rail-hint">
                  Recorded on this {detail.kind} alone — it does not change the checklist
                  every other part is measured against.
                </span>
              </div>
            </li>
          ) : null}
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
