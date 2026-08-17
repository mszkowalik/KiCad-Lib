import { useEffect, useState } from "react";
import {
  addSignoff,
  errorMessage,
  getSignoff,
  isAbortError,
  revokeSignoff,
  type SignoffDetail,
  type SignoffRow,
} from "../api";
import { useDialog } from "./Dialog";
import { ErrorBanner, SignoffPill, Spinner } from "./Ui";

/** Production sign-off for one component.
 *
 * The claim it makes is narrow and must stay narrow: a human opened the symbol
 * and the land pattern, compared them against the datasheet, and is willing to
 * build boards with this part. It is NOT the same as the version being
 * published — the meta card's "Approved by" answers a different question, and
 * the two are deliberately shown apart so they can never be read as one.
 *
 * The card never blocks anything. It reports (user decision, 2026-08-17).
 */
export default function SignoffCard({
  componentId,
  onChange,
}: {
  componentId: number;
  /** Fired after a successful sign or revoke, so the page can refresh its badge. */
  onChange?: (state: SignoffDetail) => void;
}) {
  const [detail, setDetail] = useState<SignoffDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [note, setNote] = useState("");
  const dialog = useDialog();

  useEffect(() => {
    const ctrl = new AbortController();
    setDetail(null);
    setLoadError(null);
    setActionError(null);
    setShowHistory(false);
    getSignoff(componentId, ctrl.signal)
      .then(setDetail)
      .catch((err) => {
        if (!isAbortError(err)) setLoadError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [componentId]);

  const apply = (next: SignoffDetail) => {
    setDetail(next);
    onChange?.(next);
  };

  // The note is an inline field, NOT a dialog.prompt: the prompt dialog
  // refuses to resolve on empty input, so an OPTIONAL note asked that way
  // would leave the user with no way to say "nothing to add".
  const sign = async () => {
    setBusy(true);
    setActionError(null);
    try {
      apply(await addSignoff(componentId, note.trim() || undefined));
      setNote("");
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    const reason = await dialog.prompt("Why is the sign-off being taken back?", {
      title: "Revoke sign-off",
    });
    if (reason === null) return;
    if (!reason.trim()) {
      await dialog.alert("A revoke needs a reason — the next person has to know what to look for.", {
        title: "Revoke sign-off",
      });
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      apply(await revokeSignoff(componentId, reason.trim()));
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (loadError) {
    return (
      <section className="card pad meta-card">
        <h3 className="card-title">Production sign-off</h3>
        <ErrorBanner message={`Sign-off state failed to load: ${loadError}`} />
      </section>
    );
  }
  if (!detail) {
    return (
      <section className="card pad meta-card">
        <h3 className="card-title">Production sign-off</h3>
        <Spinner label="Loading sign-off state" />
      </section>
    );
  }

  const live = detail.signoff;
  const canSign = detail.state !== "signed";

  return (
    <section className="card pad meta-card">
      <h3 className="card-title">
        Production sign-off <SignoffPill state={detail.state} />
      </h3>

      <p className="muted">{explain(detail)}</p>

      {detail.state === "stale" && detail.blockers.length > 0 ? (
        <ul className="val-list">
          {detail.blockers.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      ) : null}

      {live ? (
        // `dl.kv` is a two-column GRID whose dt/dd must be direct children —
        // a wrapper element would collapse into one grid cell.
        <dl className="kv">
          <dt>Signed by</dt>
          <dd>
            {live.signed_by}
            {live.signed_at ? (
              <span className="muted"> on {new Date(live.signed_at).toLocaleString()}</span>
            ) : null}
          </dd>
          <dt>How</dt>
          <dd>{HOW[live.kind] ?? live.kind}</dd>
          {live.revoked_at ? (
            // The reason is the useful half of a revoke: it tells the next
            // person what to look for. Showing "checked by X" on a revoked
            // card without it reads as though the part is still fine.
            <>
              <dt>Taken back</dt>
              <dd>
                {live.revoked_by ?? "?"}
                <span className="muted">
                  {" on "}
                  {live.revoked_at ? new Date(live.revoked_at).toLocaleString() : ""}
                </span>
                {live.revoke_reason ? <> — {live.revoke_reason}</> : null}
              </dd>
            </>
          ) : null}
          <dt>Version checked</dt>
          <dd className="mono">
            v{detail.signed_version_no ?? "?"}
            {detail.signed.symbol ? (
              <>
                {" · "}
                {detail.signed.symbol.name}{" "}
                <span className="pin-ver">v{detail.signed.symbol.version_no}</span>
              </>
            ) : null}
            {detail.signed.footprint ? (
              <>
                {" · "}
                {detail.signed.footprint.name}{" "}
                <span className="pin-ver">v{detail.signed.footprint.version_no}</span>
              </>
            ) : null}
          </dd>
          {live.note ? (
            <>
              <dt>Note</dt>
              <dd>{live.note}</dd>
            </>
          ) : null}
        </dl>
      ) : null}

      {actionError ? <ErrorBanner message={actionError} /> : null}

      <div className="btn-row">
        {canSign ? (
          <>
            <input
              className="text row-input"
              value={note}
              disabled={busy}
              placeholder="What you checked (optional)"
              onChange={(e) => setNote(e.target.value)}
            />
            <button type="button" className="btn btn-ok" disabled={busy} onClick={() => void sign()}>
              {detail.state === "stale" ? "Re-check and sign off" : "Sign off"}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn btn-danger"
            disabled={busy}
            onClick={() => void revoke()}
          >
            Revoke
          </button>
        )}
        {detail.history.length > 0 ? (
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setShowHistory((v) => !v)}
            aria-expanded={showHistory}
          >
            {showHistory ? "Hide history" : `History (${detail.history.length})`}
          </button>
        ) : null}
      </div>

      {showHistory ? (
        <ul className="notes-list">
          {detail.history.map((r) => (
            <li key={r.id} className="note">
              <div className="note-head mono">
                <span className="note-author">{r.signed_by}</span>
                <span className="note-date">
                  {r.signed_at ? new Date(r.signed_at).toLocaleString() : ""}
                </span>
                <SignoffPill state={r.revoked_at ? "revoked" : "signed"} />
              </div>
              <p className="muted">{describeRow(r)}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

const HOW: Record<string, string> = {
  checked: "a human opened the drawings and checked them",
  "auto-carried": "carried forward — the drawing's pads and pins did not change",
  carried: "carried forward — the approver waived the re-check on a changed drawing",
};

function explain(d: SignoffDetail): string {
  switch (d.state) {
    case "signed":
      return `Version v${d.current_version_no ?? "?"} has been checked for production.`;
    case "stale":
      return `v${d.signed_version_no ?? "?"} was checked. The component is now on v${
        d.current_version_no ?? "?"
      } and something material changed:`;
    case "revoked":
      return "The sign-off on this version was taken back. Check the part again before building.";
    default:
      return "Nobody has checked this part for production yet.";
  }
}

function describeRow(r: SignoffRow): string {
  const head = HOW[r.kind] ?? r.kind;
  if (r.revoked_at) {
    return `${head}. Revoked by ${r.revoked_by ?? "?"}: ${r.revoke_reason ?? "no reason given"}`;
  }
  return r.note ? `${head}. ${r.note}` : head;
}
