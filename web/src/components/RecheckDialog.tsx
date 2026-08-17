import { useEffect, useRef, useState } from "react";
import {
  errorMessage,
  getMaterialDiff,
  isAbortError,
  type MaterialDiff,
} from "../api";
import { ErrorBanner, Spinner } from "./Ui";

/** "Does this change need a new verification?", asked when a symbol or
 *  footprint proposal is approved.
 *
 * This is the one moment where the platform can cheaply save the user from
 * re-checking forty parts by hand — or cheaply let a moved pad through forty
 * signed-off components. So the question is asked here rather than inferred,
 * and it is pre-answered from a PROVABLE comparison: `same_material` means the
 * pads, drills, layers and courtyard (or the pins) are byte-identical, and only
 * silkscreen, fab, metadata or 3D changed.
 *
 * It is a three-way control on purpose. `dialog.confirm` cannot express it —
 * its cancel and its "no" are the same boolean — and the difference between
 * "carry the sign-offs" and "abandon the approval" matters here.
 */
export default function RecheckDialog({
  kind,
  proposalId,
  name,
  onDecide,
  onCancel,
}: {
  kind: "symbol" | "footprint";
  proposalId: number;
  name: string;
  /** `true` = every affected component drops to "re-check".
   *  `false` = the sign-offs carry forward, with the user's name on the waiver. */
  onDecide: (recheckRequired: boolean) => void;
  onCancel: () => void;
}) {
  const [diff, setDiff] = useState<MaterialDiff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const suggestedRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getMaterialDiff(kind, proposalId, ctrl.signal)
      .then(setDiff)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [kind, proposalId]);

  // Move focus INTO the dialog once its buttons exist. Without this the
  // keydown handler below never fires — key events go to document.body, which
  // is outside this subtree — so Escape did nothing and the backdrop stayed up.
  // It is also what makes the suggested answer reachable by keyboard.
  useEffect(() => {
    if (diff) suggestedRef.current?.focus();
  }, [diff]);

  const affected = diff?.affected_signed ?? 0;
  const noun = `component${affected === 1 ? "" : "s"}`;

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onCancel();
        }
      }}
    >
      <div
        className="card pad modal-card modal-card-mid"
        role="dialog"
        aria-modal="true"
        aria-label="Production verification"
      >
        <div className="card-title">Approve {name} — production verification</div>

        {error ? <ErrorBanner message={`Comparison failed: ${error}`} /> : null}
        {!diff && !error ? <Spinner label="Comparing the drawings" /> : null}

        {diff ? (
          <>
            <p className="modal-msg">
              {diff.is_new ? (
                <>This is a new {kind}. Nothing has been checked against it yet.</>
              ) : diff.same_material ? (
                <>
                  Nothing that reaches the board changed between v{diff.from_version} and v
                  {diff.to_version}. Only silkscreen, fab, metadata or 3D differ.
                </>
              ) : (
                <>
                  Something that reaches the board changed between v{diff.from_version} and v
                  {diff.to_version}:
                </>
              )}
            </p>

            {!diff.same_material && diff.changed.length > 0 ? (
              <ul className="val-list">
                {diff.changed.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            ) : null}

            <p className="muted">
              {affected === 0
                ? `No signed-off ${kind === "symbol" ? "component" : "component"}s use this drawing, so nothing carries either way.`
                : `${affected} signed-off ${noun} use${affected === 1 ? "s" : ""} this drawing.`}
            </p>

            <div className="btn-row modal-actions">
              <button type="button" className="btn" onClick={onCancel}>
                Cancel
              </button>
              <button
                ref={diff.suggest_recheck ? suggestedRef : undefined}
                type="button"
                className={"btn" + (diff.suggest_recheck ? " btn-primary" : "")}
                onClick={() => onDecide(true)}
              >
                Check them again
              </button>
              <button
                ref={diff.suggest_recheck ? undefined : suggestedRef}
                type="button"
                className={"btn" + (diff.suggest_recheck ? "" : " btn-ok")}
                onClick={() => onDecide(false)}
              >
                {affected === 0
                  ? "Good enough"
                  : `Keep the ${affected} sign-off${affected === 1 ? "" : "s"}`}
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
