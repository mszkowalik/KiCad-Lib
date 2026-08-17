/** Small shared UI atoms: spinner, error banner, status pill. */

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
