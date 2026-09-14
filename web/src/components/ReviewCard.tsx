import { useEffect, useState } from "react";
import {
  errorMessage,
  getReviewDetail,
  isAbortError,
  recordReviewCheck,
  grantReviewException,
  revokeReviewCheck,
  revokeReviewException,
  type ChecklistItemDef,
  type ReviewCheckAnswer,
  type ReviewDetail,
  type ReviewException,
  type ReviewKind,
} from "../api";
import { useDialog } from "./Dialog";
import InfoTip from "./InfoTip";
/** Mirror of `review.TEXT_LIMITS` and `exceptions.TEXT_LIMITS` in the backend,
 *  in characters. The server REFUSES an over-long explanation, so these stop
 *  the typing rather than the save — change one and change the other, because a
 *  UI cap above the server's lets somebody write a note that is then thrown
 *  away.
 *
 *  The numbers came from measuring what is already stored: a person writes 31
 *  characters here, an agent's median is 367 and its longest is 3,316. Nobody
 *  reads 3,316 characters on one checklist item, so the finding inside it is
 *  lost exactly as surely as if it had never been written. */
const LIMITS = { note: 400, passNote: 300, revokeReason: 300 } as const;


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
  const [answers, setAnswers] = useState<Record<string, ReviewCheckAnswer>>({});
  const [note, setNote] = useState("");
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
    setAnswers({});
    getReviewDetail(kind, id, ctrl.signal)
      .then((d) => setDetail(d))
      .catch((err) => {
        if (!isAbortError(err)) setLoadError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [kind, id]);

  const apply = (next: ReviewDetail) => {
    setDetail(next);
    onChange?.(next);
  };

  // WHICH WAY an item does not apply, as a CODE the health tab can count. The
  // same argument the retired skip reasons were built on: free-text notes
  // saying the same thing in 84 different words are one problem wearing 84
  // hats, and a code makes them one number with one fix.
  //
  // `skipped` was retired on 2026-09-13 (decision 0011). It meant "applies,
  // but I could not verify it" and read to everybody as "does not apply",
  // which is `na`'s job — so agents reached for it to mean "I did not re-open
  // the PDF on this pass" and 38 subjects sat at partial for no real reason.
  // An item nobody can verify is now simply LEFT UNANSWERED.
  //
  // `na` stopped being an ANSWER on 2026-09-14. It is a standing exception, and
  // "Does not apply…" grants one. The two said the same thing and only one of
  // them lasted: the library held 314 live `na` answers, 312 of them written by
  // agents, none with a reason, every one due to expire at the next version
  // bump — while the table built to hold such decisions held ZERO rows. These
  // codes live on as the exception's `reason`.
  const NA_REASONS = [
    ["feature_absent", "the part does not have the thing this checks"],
    ["kind_exempt", "the convention exempts this class of part"],
    ["waived", "applies, but accepted as-is by the owner"],
    ["other", "other (say what in the note)"],
  ] as const;

  const answer = async (
    item: { key: string; text: string },
    result: "checked" | "flagged",
  ) => {
    let itemNote: string | undefined;
    if (result === "flagged") {
      const why = await dialog.prompt(
        `What is wrong with "${item.text}"? (goes on the second-pass list)`,
        { title: "Flag an issue" },
      );
      if (why === null) return;
      itemNote = why.trim() || undefined;
      if (!itemNote) {
        await dialog.alert("A flag needs a note — it IS the second-pass worklist entry.", {
          title: "Flag an issue",
        });
        return;
      }
    }
    setAnswers((prev) => ({
      ...prev,
      [item.key]: { key: item.key, result, note: itemNote, text: item.text },
    }));
  };

  /** The scopes an exception may be pinned to, for THIS kind of subject.
   *
   *  A component's `$material_sha` is its symbol's and its footprint's joined
   *  together, so "while the drawing is unchanged" says nothing at all about
   *  the component's own fields — `$property_sha` is what covers those. Offer
   *  the wrong one and a waiver on a Value or a datasheet silently outlives
   *  the edit that changed it, which is the exact failure the scope question
   *  exists to prevent.
   */
  const SCOPES: { value: string; label: string; pin?: string[] }[] =
    kind === "component"
      ? [
          { value: "property", label: "While this component's own data is unchanged", pin: ["$property_sha"] },
          { value: "drawing", label: "While the symbol and footprint are unchanged" },
          { value: "always", label: "Always — this is about the part, whatever it is drawn as" },
        ]
      : [
          { value: "drawing", label: "While the drawing is unchanged — dies if the copper moves" },
          { value: "always", label: "Always — this is about the part, not this drawing" },
        ];

  /** Grant a standing exception straight from the finding it excuses.
   *
   *  The only way in used to be Verify… → N/A → "keep this decision?" — three
   *  dialogs deep, gated on entering verify mode, and never once using the
   *  word "exception". A user looking at a red check reported there was no way
   *  to excuse it (2026-09-14), which is what a hidden control looks like from
   *  the outside.
   *
   *  It needs no verify mode and stages nothing: conformance is computed on
   *  read and an exception is an OVERLAY on it (decision 0017), so the finding
   *  changes the moment this returns. There is no Save to forget.
   */
  const excuse = async (item: { key: string; text: string; variant?: string }) => {
    const picked = await dialog.select(
      `Why is "${item.text}" excused on this ${kind}?`,
      NA_REASONS.map(([value, label]) => ({ value, label })),
      { title: "Does not apply" },
    );
    if (picked === null) return;
    const why = await dialog.prompt("Why? The next reviewer has nothing else to go on.", {
      title: "Does not apply",
      maxLength: LIMITS.note,
    });
    if (why === null) return;
    if (!why.trim()) {
      await dialog.alert(
        "A standing exception needs a note — it is the only place the reason will ever live.",
        { title: "Does not apply" },
      );
      return;
    }
    const scope = await dialog.select(
      `How long does this decision hold for "${detail?.name ?? "this subject"}"?`,
      SCOPES.map(({ value, label }) => ({ value, label })),
      { title: "Does not apply" },
    );
    if (scope === null) return;
    const chosen = SCOPES.find((s) => s.value === scope);
    setBusy(true);
    setActionError(null);
    try {
      apply(
        await grantReviewException(kind, id, {
          key: item.key,
          variant: item.variant,
          reason: picked,
          note: why.trim(),
          ...(chosen?.pin ? { pin: chosen.pin } : { scope: scope as "drawing" | "always" }),
        }),
      );
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
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

  /** A check this part needed that no checklist anticipated. There is no "does
   *  not apply" here on purpose: inventing a check and excusing it in the same
   *  gesture records nothing anybody can use. */
  const addCustom = async (result: "checked" | "flagged") => {
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

  /* "Re-run auto checks" was removed on 2026-09-14 (decision 0017).
     Conformance is computed on read and its cache is keyed on a digest of the
     checklist, the subject's facts and the live exceptions — so there is
     nothing to re-run. The button existed because machine answers used to be
     stored and could go stale. */


  /** Withdraw a standing decision. The check comes straight back — an answer
   *  written by an exception dies with it (`review.record_check`), so this is
   *  not a button that half works. */
  const revokeException = async (excId: number, key: string) => {
    const why = await dialog.prompt(`Why is the exception on "${key}" being withdrawn?`, {
      title: "Revoke exception",
      maxLength: LIMITS.revokeReason,
    });
    if (why === null) return;
    setBusy(true);
    setActionError(null);
    try {
      apply(await revokeReviewException(kind, id, excId, why.trim()));
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    const reason = await dialog.prompt("Why is the verification being taken back?", {
      title: "Revoke verification",
      maxLength: LIMITS.revokeReason,
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

  // A pre-2026-09-13 `skipped` answer reads as "nobody has answered this yet".
  const openCount = detail.items.filter((i) => !i.answered || i.answered.result === "skipped").length;
  // Answers to keys the checklist does not define and the record does not
  // carry yet — they have no row of their own to render in, so they get one.
  const known = new Set([...detail.items.map((i) => i.key), ...detail.extra_items.map((i) => i.key)]);
  const pendingCustom = Object.values(answers).filter((a) => !known.has(a.key));
  const dirty = Object.keys(answers).length > 0;

  // Work first, settled last. The card is read top-down by somebody looking for
  // what to do next, and a checked machine item is never that (user request
  // 2026-09-14).
  //
  // The rank comes from the SAVED answer, never from a staged one, so answering
  // a row does not make it jump out from under the cursor. It re-sorts on the
  // next load, once the answer is real.
  const sorted = detail.items
    .map((item, index) => ({ item, index, rank: attentionRank(item) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map((row) => row.item);

  // A standing decision is drawn ON the row of the check it excuses (user
  // request 2026-09-14). It used to sit in a block of its own above the
  // checklist, which put the reason a check is quiet — and the only button that
  // undoes it — several rows away from the check itself, under a bare key
  // nobody reads as the question it answers.
  //
  // `answered.exception_id` is the exact link and is preferred. The key match
  // is the fallback for a STALE exception: it has stopped closing its item, so
  // the item is open again and carries no id, and it still has to be visible.
  const exceptions = detail.exceptions ?? [];
  const excFor = (item: ChecklistItemDef): ReviewException | undefined => {
    const id = item.answered?.exception_id;
    if (id != null) {
      const exact = exceptions.find((e) => e.id === id);
      if (exact) return exact;
    }
    return exceptions.find(
      (e) => e.key === item.key && (!e.variant || !item.variant || e.variant === item.variant),
    );
  };
  const attached = new Set(
    sorted.map((item) => excFor(item)?.id).filter((x): x is number => x != null),
  );
  // Whatever has no row keeps a block of its own: a check can be scoped out,
  // switched off, or dropped from the checklist since the decision was made,
  // and an exception with no Revoke button is an exception nobody can withdraw.
  const looseExceptions = exceptions.filter((e) => !attached.has(e.id));

  return (
    <section className="card pad meta-card">
      <h3 className="card-title">
        {label ?? "Verification"}{" "}
        {/* The aggregate AND the two facts under it. One word could not say
            "the code is happy" and "a person has looked at 3 of 9" at once,
            and the card is where both matter most. */}
        <ReviewPill state={detail.state} provenance={detail.provenance} detail={detail} />
      </h3>

      {actionError ? <ErrorBanner message={actionError} /> : null}

      {/* The sentence and the buttons that act on it share ONE line (user
          request 2026-09-14). They are the same statement — what state this
          subject is in, and what you can do about it — and stacking them put
          two lines of chrome above every checklist. The line wraps at narrow
          widths rather than squeezing the note input. */}
      <div className="review-actions">
        <p className="muted">{explain(detail, openCount)}</p>

      {/* SAVE AND CANCEL ONLY WHEN THERE IS SOMETHING TO SAVE. There used to be
          a "Verify…" button that switched the card into an edit mode before any
          row would answer, which is a click that carries no decision — the card
          is the edit mode now, and this row appears the moment an answer is
          staged (user request 2026-09-14). */}
      <div className="btn-row">
        {dirty ? (
          <>
            <input
              className="text row-input"
              value={note}
              disabled={busy}
              maxLength={LIMITS.passNote}
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
                setAnswers({});
                setCustomText("");
              }}
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className="btn btn-ok btn-sm"
              disabled={busy || detail.version_id === null}
              onClick={() => void oneClick()}
              title="Record a human check without the item breakdown"
            >
              Mark checked
            </button>
            {/* Named in full because the exception rows below carry their own
                Revoke, and two identical red buttons a few pixels apart is a
                mis-click waiting to happen — this one withdraws the whole
                verification, that one withdraws one standing decision. */}
            {detail.record ? (
              <button
                type="button"
                className="btn btn-danger btn-sm"
                disabled={busy}
                onClick={() => void revoke()}
                title="Withdraw the whole verification record for this version"
              >
                Revoke verification
              </button>
            ) : null}
          </>
        )}
        </div>
      </div>

      {/* Only the decisions with no check to sit on. Every other one is drawn
          on its own row below — see `excFor`. */}
      {looseExceptions.length ? (
        <ul className="notes-list">
          {looseExceptions.map((exc) => (
          <li key={`exc-${exc.id}`} className="note">
            <div className="note-head">
              <span>{exc.key}</span>{" "}
              <span
                className={`pill ${exc.stale_reason ? "warn" : "neutral"}`}
                title={exc.stale_reason ?? `Granted by ${exc.created_by}`}
              >
                {exc.stale_reason ? "exception stale" : `exception · ${exc.scope}`}
              </span>
              <button
                type="button"
                className="btn btn-sm btn-danger"
                disabled={busy}
                onClick={() => void revokeException(exc.id, exc.key)}
                title="Withdraw this decision — the check it excuses answers again on the next read"
              >
                Revoke exception
              </button>
            </div>
            <p className="muted">
              {exc.note}
              {exc.stale_reason ? ` — no longer applies: ${exc.stale_reason}` : ""}
            </p>
          </li>
        ))}
        </ul>
      ) : null}

      {/* The checklist is ALWAYS open. It used to be behind a fold that opened
          itself on a failing card; the fold only ever hid the thing somebody
          opened the card to read, and a collapsed finding is how "there is no
          way to excuse this check" happens (user reports 2026-09-14). */}
      <ul className="notes-list">
        {detail.items_carried ? (
          <li className="note muted dim">
            These answers were recorded before the confirmation that set this state — the
            confirmation vouches for the subject as a whole and records no items of its own.
          </li>
        ) : null}
        {sorted.map((item) => {
          const pending = answers[item.key];
          const a = item.answered;
          const finding = a?.result === "failed" || a?.result === "flagged";
          const excused = a?.exception_id != null;
          const exc = excFor(item);
          // A machine item is normally the validator's to answer, so a
          // passing one offers no buttons. A FINDING is different: it is a
          // worklist entry addressed to a person.
          const canAnswer = !excused && (!item.machine || finding);
          // "Does not apply" is available on ANY judgment item, answered or
          // not, and on a machine FINDING. Saying a check is not about this
          // part does not require running it first — it is the only honest
          // way to close such an item, and refusing it on an open item was
          // what left `na` in place as a second, weaker way to say the same
          // thing. It needs no verify mode: an exception stages nothing and
          // saves nothing (decision 0017).
          const canExcuse = !excused && !pending && (!item.machine || finding);
          return (
            <li key={item.key} className="note">
              <div className="note-head">
                <span title={item.key}>{item.text}</span>{" "}
                {item.hint ? (
                  <InfoTip label={`What "${item.text}" asks`}>{item.hint}</InfoTip>
                ) : null}{" "}
                {pending ? (
                  <span className="pill ok" title="unsaved answer">
                    {pending.result} ✎
                  </span>
                ) : a ? (
                  <span
                    className={`pill ${resultTone(a)}`}
                    title={`${a.actor_type} · ${a.actor}${
                      isWarning(a) ? ` — recorded as ${a.result}, at warning severity` : ""
                    }${a.note ? ` — ${a.note}` : ""}`}
                  >
                    {isWarning(a) ? "warning" : a.result}
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
                {exc ? (
                  <span
                    className={`pill ${exc.stale_reason ? "warn" : "neutral"}`}
                    title={exc.stale_reason ?? `Granted by ${exc.created_by}`}
                  >
                    {exc.stale_reason ? "exception stale" : `exception · ${exc.scope}`}
                  </span>
                ) : null}
              </div>
              {a?.note && !pending ? <p className="muted">{a.note}</p> : null}
              {/* The decision's own words, printed only when the answer did not
                  already carry them — an excused item's note IS the reason. */}
              {exc && (!a?.note || pending) ? <p className="muted">{exc.note}</p> : null}
              {exc?.stale_reason ? (
                <p className="muted">No longer applies: {exc.stale_reason}</p>
              ) : null}
              {exc ? (
                <div className="btn-row">
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    disabled={busy}
                    onClick={() => void revokeException(exc.id, exc.key)}
                    title="Withdraw this decision — the check it excuses answers again on the next read"
                  >
                    Revoke exception
                  </button>
                </div>
              ) : null}
              {/* What this answer replaced. Accepting a flag keeps the flag
                  readable — otherwise clearing a defect means deleting the
                  only description of it.

                  FOLDED, and open on request (user request 2026-09-14). The
                  old finding is longer than the answer that replaced it — a
                  flag says what is wrong and why, a "checked" says it is
                  settled — so printing it open buried the current answer under
                  the history of the item. The summary still names WHAT it was
                  and who wrote it, which is the part worth seeing at a glance;
                  only the note is behind the fold. */}
              {a?.superseded && !pending ? (
                <SupersededRow was={a.superseded} />
              ) : null}
              {/* Until 2026-09-13 only `failed` could be closed here. An
                  agent's `flagged` on a machine item — `cmp.datasheet_text`
                  is the one that reaches this state in practice — rendered
                  read-only with no way to accept, waive or re-check it (user
                  report 2026-09-13). The backend never forbade it:
                  `record_check` lets a human answer over an agent on any key,
                  and keeps the old answer as `superseded`. */}
              {canAnswer || canExcuse ? (
                <div className="btn-row">
                  {canAnswer ? (
                    <>
                      <button type="button" className="btn btn-sm" onClick={() => void answer(item, "checked")}>
                        Checked
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        onClick={() => void answer(item, "flagged")}
                        title="Verified and found wrong — record the defect without fixing it"
                      >
                        Flag
                      </button>
                    </>
                  ) : null}
                  {canExcuse ? (
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={busy}
                      onClick={() => void excuse(item)}
                      title="This check is not about this part — records a standing decision that survives the next version, and shows on the card until somebody revokes it"
                    >
                      Does not apply…
                    </button>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
        {/* FOLDED. These are checks that are NOT ABOUT parts like this one, and
            printing them open put five questions a MOSFET can never answer —
            "IQ is per CHANNEL", "the exposed pad is documented" — in the middle
            of its checklist, where they read as work (user report 2026-09-14).
            Kept, because "this check exists and does not apply here" is how
            somebody finds out a scope is wrong; a count in the summary is
            enough to say so. */}
        {detail.inapplicable?.length ? (
          <li className="note muted">
            <details className="not-here">
              <summary>
                {detail.inapplicable.length} check
                {detail.inapplicable.length === 1 ? "" : "s"} not about parts like this one
              </summary>
              <ul className="notes-list">
                {detail.inapplicable.map((item) => (
                  <li key={item.key} className="note muted">
                    <div className="note-head">
                      <span>{item.text}</span>{" "}
                      <span
                        className="pill neutral"
                        title={`Not about parts like this one: ${Object.entries(item.when)
                          .map(([f, p]) => `${f} matches ${p}`)
                          .join(" and ")}`}
                      >
                        n/a here
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          </li>
        ) : null}
        {detail.switched_off?.length ? (
          <li className="note muted">
            <details className="not-here">
              <summary>
                {detail.switched_off.length} check
                {detail.switched_off.length === 1 ? "" : "s"} switched off for this subject
              </summary>
              <ul className="notes-list">
                {detail.switched_off.map((item) => (
                  <li key={item.key} className="note muted">
                    <div className="note-head">
                      <span>{item.text}</span>{" "}
                      <span className="pill neutral" title="Switched off in the checklist for this subject">
                        off
                      </span>
                      {item.machine ? <span className="badge">auto</span> : null}
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          </li>
        ) : null}
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
        {(
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
        )}
      </ul>
    </section>
  );
}

/** The answer a current one replaced — folded, with what it WAS in the summary.
 *
 *  A disclosure arrow that opens onto nothing is a lie, so an answer with no
 *  note stays a plain line. */
function SupersededRow({ was }: { was: NonNullable<NonNullable<ChecklistItemDef["answered"]>["superseded"]> }) {
  const head = (
    <>
      was <span className={`pill ${RESULT_TONE[was.result] ?? "neutral"}`}>{was.result}</span>
      {was.actor ? ` by ${was.actor}` : ""}
    </>
  );
  if (!was.note) return <p className="muted dim superseded">{head}</p>;
  return (
    <details className="muted dim superseded">
      <summary>{head}</summary>
      <p>{was.note}</p>
    </details>
  );
}

/** How much attention a checklist row needs, lowest first.
 *
 *  Read off the SAVED answer only. Ranking a staged answer would re-sort the
 *  list while somebody is working down it. */
function attentionRank(item: ChecklistItemDef): number {
  const a = item.answered;
  if (!a) return 2; // nobody has answered it
  if (a.exception_id != null) return 3; // a standing decision closed it
  if (a.result === "failed" || a.result === "flagged") {
    return a.severity === "warning" ? 1 : 0;
  }
  return 4; // checked, or na
}

/** A warning-level failure says `warning`, not `failed`.
 *
 *  `result` and `severity` are two axes (decision 0016): the rule IS broken, and
 *  the breakage does not fail the part — `state_from_record` gives such a
 *  subject `checked` with `warnings: 1`. Printing both axes raw put `failed
 *  (machine)` and `warning only` side by side on one row, which reads as a
 *  contradiction and got reported as a broken check (2026-09-14).
 *
 *  The word shown changes; the stored `result` does not. The row's `title`
 *  still names it, so nothing is hidden from somebody who looks. */
const isWarning = (a: { result: string; severity?: string }) =>
  a.severity === "warning" && (a.result === "failed" || a.result === "flagged");

const resultTone = (a: { result: string; severity?: string }) =>
  isWarning(a) ? "warn" : (RESULT_TONE[a.result] ?? "neutral");

const RESULT_TONE: Record<string, string> = {
  checked: "ok",
  na: "neutral",
  skipped: "warn", // retired 2026-09-13, still rendered on old records
  failed: "err",
  flagged: "err",
};

/** Warnings are counted SEPARATELY and never change the state — that is the
 *  whole point of the severity. Printing them on the end of every line keeps
 *  them visible without letting them read as failures. */
function warningSuffix(d: ReviewDetail): string {
  return d.warnings ? ` ${d.warnings} warning(s).` : "";
}

/** "and 2 excused" — never folded into the verified count. An exception says
 *  the question is not about this part; it does not say anybody looked. */
function excusedSuffix(d: ReviewDetail): string {
  return d.excused ? ` ${d.excused} item(s) excused by a standing decision.` : "";
}

function explain(d: ReviewDetail, openCount: number): string {
  switch (d.state) {
    case "checked":
      return (
        (d.provenance === "human"
          ? "Verified against the documentation, human-confirmed."
          : `Verified against the documentation (${d.provenance ?? "?"}-checked, no human confirmation yet).`) +
        warningSuffix(d) + excusedSuffix(d)
      );
    case "partial":
      return `Partially verified — ${openCount} item(s) still open.` + warningSuffix(d) + excusedSuffix(d);
    case "failed":
      return (
        (d.flagged
          ? `${d.flagged} item(s) flagged as wrong (second-pass list)${d.failed - d.flagged ? `, ${d.failed - d.flagged} machine check(s) failing` : ""}.`
          : `${d.failed} machine check(s) failing.`) +
        " Fix the data and republish, or mark the check as not applying to this part below." +
        warningSuffix(d) + excusedSuffix(d)
      );
    default:
      return "This version has not been verified against its documentation yet." +
        warningSuffix(d) + excusedSuffix(d);
  }
}
