/** Small shared UI atoms: spinner, error banner, status pill, back link. */
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

export function ReviewPill({
  state,
  provenance,
  title,
}: {
  state: string | null | undefined;
  provenance?: string | null;
  title?: string;
}) {
  const [tone, label] = REVIEW_TONES[(state ?? "").toLowerCase()] ?? ["neutral", "unreviewed"];
  const suffix = state === "checked" && provenance && provenance !== "human" ? ` (${provenance})` : "";
  return (
    <span className={`pill ${tone}`} title={title}>
      {label}
      {suffix}
    </span>
  );
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
