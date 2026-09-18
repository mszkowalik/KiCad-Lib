/** Small shared UI atoms: spinner, error banner, status pill, back link,
 *  fold-away list. */
import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

/** "← Back" that means BACK, not UP.
 *
 * Every one of these used to be a plain `<Link to={somewhere}>` naming a place
 * in the site hierarchy — so opening a footprint from a component and pressing
 * Back landed you in the footprint LIST, not on the component you came from,
 * and the trail to finish verifying that part was gone. React Router keeps its
 * position in the history stack on `history.state.idx`, so `idx > 0` means
 * there IS an in-app entry behind this one and `navigate(-1)` returns to it.
 *
 * `to` stays required and stays the anchor's real href: it is the answer for a
 * page opened directly (a pasted link, a new tab, `idx === 0`), and keeping a
 * real href is what preserves middle-click and "open in new tab".
 */
export function BackLink({
  to,
  children,
  className = "backlink",
}: {
  /** Where to go when there is no history to go back to. */
  to: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const navigate = useNavigate();
  const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
  return (
    <Link
      to={to}
      className={className}
      onClick={(e) => {
        // Let the browser handle the modified clicks it already handles well.
        if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0)
          return;
        if (idx > 0) {
          e.preventDefault();
          navigate(-1);
        }
      }}
    >
      {children ?? <>&larr; Back</>}
    </Link>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="spinner-wrap" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label ? <span className="spinner-label">{label}</span> : null}
    </span>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  // Nothing to report renders nothing. This used to draw the bordered box
  // regardless, so every caller had to guard it with `{error && <ErrorBanner/>}`
  // and any that forgot got an empty red rectangle on the page. Guarding here
  // fixes it for every caller at once, and an empty `role="alert"` was announcing
  // nothing to a screen reader anyway.
  if (!message || !message.trim()) return null;
  return (
    <div className="banner-error" role="alert">
      {message}
    </div>
  );
}

const STATUS_TONES: Record<string, string> = {
  published: "ok",
  approved: "ok",
  active: "ok",
  current: "ok",
  ok: "ok",
  // A programming run's own words. They used to fall through to "neutral",
  // which drew PASS and FAIL in the same grey — the one column an operator
  // scans down a device list said nothing at a glance (user report
  // 2026-09-16). `aborted` is warn, not err: somebody stopped it, the device
  // did not fail.
  pass: "ok",
  fail: "err",
  aborted: "warn",
  draft: "warn",
  pending: "warn",
  proposed: "warn",
  running: "warn",
  rejected: "err",
  failed: "err",
  error: "err",
  deprecated: "err",
  archived: "err",
};

export function StatusPill({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="pill neutral">unknown</span>;
  const tone = STATUS_TONES[status.toLowerCase()] ?? "neutral";
  return <span className={`pill ${tone}`}>{status}</span>;
}

/** Production sign-off state — deliberately its OWN pill, not a StatusPill.
 *
 * `published` and `signed` are different claims and must never share a word or
 * a colour: a published component may never have been checked by anybody. The
 * labels spell the state out for the same reason — "stale" alone reads like a
 * cache problem rather than "this needs looking at again". */
const SIGNOFF_TONES: Record<string, [string, string]> = {
  signed: ["ok", "signed"],
  stale: ["warn", "re-check"],
  revoked: ["err", "revoked"],
  unsigned: ["neutral", "not signed"],
};

export function SignoffPill({
  state,
  title,
}: {
  state: string | null | undefined;
  title?: string;
}) {
  const [tone, label] = SIGNOFF_TONES[(state ?? "").toLowerCase()] ?? [
    "neutral",
    "not signed",
  ];
  return (
    <span className={`pill ${tone}`} title={title}>
      {label}
    </span>
  );
}

/** Review (verification) state — its own pill for the same reason as
 * SignoffPill: "published" says nothing about whether anybody compared the
 * part against its documentation. `partial` = items skipped or unanswered;
 * `failed` = a machine check found a violation. */
const REVIEW_TONES: Record<string, [string, string]> = {
  checked: ["ok", "checked"],
  partial: ["warn", "partial"],
  failed: ["err", "issues"],
  unreviewed: ["neutral", "unreviewed"],
};

/** Who answered, as one glyph: ⚙ the validator on publish, 🤖 an agent run.
 *
 *  A human answer carries no mark — it is the default and the strongest claim.
 *  The pills used to spell the word (`checked (agent)`, uppercased by the pill
 *  style into `CHECKED (AGENT)`), which was the widest thing a review column
 *  printed and got clipped in every narrow cell (user report 2026-09-18). The
 *  full word still reaches the reader through the pill's `title`. */
export const ACTOR_MARK: Record<string, string> = { machine: "⚙", agent: "🤖" };

export function actorMark(actor: string | null | undefined): string | null {
  return actor ? (ACTOR_MARK[actor] ?? null) : null;
}

/** The review state, and — when the caller has them — the two facts underneath.
 *
 *  One word was doing three jobs. `partial` meant "nobody has looked", "a
 *  question was added last week" and "one item is still open"; `unreviewed`
 *  showed on a subject whose every check had just been decided, because
 *  completeness is measured over JUDGMENT items and a part can have none left.
 *  132 of 212 footprints read `unreviewed` — a queue signal wearing a quality
 *  signal's clothes.
 *
 *  KiCad reports "0 errors, 12 warnings, 3 excluded" and has no aggregate state
 *  at all. This keeps the aggregate, because sorting and filtering need one
 *  value, and prints the facts beside it: **conforms** is what the code can
 *  see, **judged n of m** is what a person has confirmed. Pass `detail` and
 *  they show; leave it off and the pill is what it always was.
 */
export function ReviewPill({
  state,
  provenance,
  title,
  detail,
}: {
  state: string | null | undefined;
  provenance?: string | null;
  title?: string;
  /** The state object from the API. `conforms: null` means "not evaluated" and
   *  must never print as "conforms". */
  detail?: {
    conforms?: boolean | null;
    answered?: number;
    total?: number;
    excused?: number;
    warnings?: number;
  } | null;
}) {
  const [tone, label] = REVIEW_TONES[(state ?? "").toLowerCase()] ?? ["neutral", "unreviewed"];
  const mark = state === "checked" ? actorMark(provenance) : null;
  const pill = (
    <span className={`pill ${tone}`} title={title ?? (mark ? `checked by ${provenance}` : undefined)}>
      {label}
      {mark ? ` ${mark}` : ""}
    </span>
  );
  if (!detail) return pill;
  const { conforms, answered = 0, total = 0, excused = 0, warnings = 0 } = detail;
  return (
    <span className="state-facts">
      {pill}
      <span
        className={`pill ${conforms === null || conforms === undefined ? "neutral" : conforms ? "ok" : "err"}`}
        title={
          conforms === null || conforms === undefined
            ? "The automatic checks have not been worked out for this version yet"
            : conforms
              ? "Every automatic check passes"
              : "An automatic check is failing"
        }
      >
        {conforms === null || conforms === undefined ? "not evaluated" : conforms ? "conforms" : "fails"}
      </span>
      <span
        className="pill neutral"
        title="Items a person or an agent has answered, out of the ones this subject is asked"
      >
        judged {answered}/{total}
      </span>
      {excused ? (
        <span className="pill neutral" title="Closed by a standing decision, not by a verification">
          {excused} excused
        </span>
      ) : null}
      {warnings ? (
        <span className="pill warn" title="Warning-level failures. They do not fail the subject.">
          {warnings} warning{warnings === 1 ? "" : "s"}
        </span>
      ) : null}
    </span>
  );
}

/** The three facts as one line of text, for a place that cannot hold pills.
 *
 *  The queue is a DataTable, and every row there is exactly one line tall with
 *  no wrapping (`web/src/components/CLAUDE.md`), so three pills in a cell would
 *  break the table rather than inform anybody. The tooltip carries them
 *  instead, which keeps the one-word state sortable and still lets somebody
 *  find out what it means. */
export function stateFacts(detail: {
  conforms?: boolean | null;
  judged?: number;
  judged_of?: number;
  excused?: number;
  warnings?: number;
}): string {
  const parts = [
    detail.conforms === null || detail.conforms === undefined
      ? "automatic checks not worked out yet"
      : detail.conforms
        ? "conforms"
        : "an automatic check fails",
    `judged ${detail.judged ?? 0} of ${detail.judged_of ?? 0}`,
  ];
  if (detail.excused) parts.push(`${detail.excused} excused by a standing decision`);
  if (detail.warnings) parts.push(`${detail.warnings} warning(s)`);
  return parts.join(" · ");
}

/** Usage-fitness lifecycle — what the part may be used for, not whether it was
 * checked. Deprecated/obsolete parts are hidden from KiCad. */
const LIFECYCLE_TONES: Record<string, [string, string]> = {
  in_design: ["neutral", "in design"],
  released: ["ok", "released"],
  deprecated: ["warn", "deprecated"],
  obsolete: ["err", "obsolete"],
};

export function LifecyclePill({ state, title }: { state: string | null | undefined; title?: string }) {
  const [tone, label] = LIFECYCLE_TONES[(state ?? "").toLowerCase()] ?? ["neutral", state ?? "?"];
  return (
    <span className={`pill ${tone}`} title={title}>
      {label}
    </span>
  );
}

/** A long list that shows its first few rows and unfolds the rest in place.
 *
 *  The library-health cards hold lists that are legitimately long — every part
 *  used on a board and not signed off, every chronically skipped checklist item
 *  — and a card whose list runs to forty rows pushes everything under it off
 *  the screen, so the OTHER cards stop being readable at a glance. This shows
 *  `min` rows and puts the rest behind one button.
 *
 *  **It slices the array; it does not clamp a height.** A CSS `max-height`
 *  would have to guess a row height, and the row would then shrink or the last
 *  visible row would be cut in half. Rows keep exactly the height they have,
 *  folded or not — which is the point, since these are read by scanning.
 */
export function FoldList<T>({
  items,
  min = 2,
  noun = "more",
  children,
}: {
  items: T[];
  /** Rows shown while folded. */
  min?: number;
  /** What the unfold button counts, e.g. "part" -> "Show 12 more parts". */
  noun?: string;
  children: (shown: T[]) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const hidden = items.length - min;
  const shown = open || hidden <= 0 ? items : items.slice(0, min);
  return (
    <>
      {children(shown)}
      {hidden > 0 ? (
        <button type="button" className="btn btn-sm fold-more" onClick={() => setOpen(!open)}>
          {open ? "Show fewer" : `Show ${hidden} more ${noun}${hidden === 1 ? "" : "s"}`}
        </button>
      ) : null}
    </>
  );
}
