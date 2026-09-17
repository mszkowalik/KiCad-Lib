/** Edit one param set's VALUES — the WiFi credentials, the MQTT host, the
 *  creds salt, the default SIM PIN — wherever the operator happens to be.
 *
 *  ONE editor, opened from three places: the Parameters page, a version's
 *  Parameters card and the composer (2026-09-17, user request: "deployment tab
 *  should allow user to fully configure the deployment"). Administering the
 *  SET — listing it, its history, deleting it — is the Parameters page; this
 *  box only changes what a procedure interpolates.
 *
 *  A param set is NOT versioned, and that is deliberate (design.md §14): the
 *  values are shared across every version and every project batch, encrypted at
 *  rest, and snapshotted masked onto each run. So saving here changes what the
 *  NEXT run of every version pointing at this set will use — the card says so,
 *  because the deployment page otherwise reads like a place where edits are
 *  versioned.
 *
 *  Since decision 0024 the box also shows WHO depends on each key, and the
 *  server refuses a save that would remove one a published version declares.
 *  Before that, removing a key nobody appeared to use broke a version from
 *  months earlier and the platform said so at the bench, mid-run. `note` is
 *  asked for because a VALUE change — the same key repointed at a different
 *  broker, a rotated salt — passes every other check there is, so the revision
 *  log is the only place it is recorded.
 */
import { useEffect, useState } from "react";
import { errorMessage, getParamSetValues, putParamSet, type ParamUse } from "../../api";
import { ErrorBanner, Spinner } from "../Ui";
import { useModal } from "../modal";

/** Keys a new set starts with: what every V2 procedure interpolates. Typing
 *  six key names from memory is how a set ends up with `SSID1` in it. */
const SUGGESTED = ["SSId1", "Password1", "MqttHost", "MqttPort", "creds_salt", "sim_pin"];

/* No masking. Every value here is a bench setting somebody opened this box to
   read, and the page is already behind the sign-in gate; a box of dots with a
   "show" beside it is one more click on every visit (user decision
   2026-09-17). Storage is unaffected — the set is Fernet-encrypted at rest. */

export interface ParamSetEditorProps {
  projectId: number;
  /** Existing set to edit. Omit (with `name`) to create one. */
  paramSetId?: number | null;
  /** Name for a NEW set. Ignored when `paramSetId` is given. */
  newName?: string;
  /** key -> published versions that need it, from `listParamSets`. Optional:
   *  a caller without it simply shows no usage, and the SERVER still refuses a
   *  breaking save. This is the warning, never the guard. */
  usedBy?: Record<string, ParamUse[]>;
  onClose: (saved: boolean) => void;
}

export default function ParamSetEditor(props: ParamSetEditorProps) {
  const { projectId, paramSetId, newName, usedBy = {}, onClose } = props;
  const [name, setName] = useState(newName ?? "");
  const [rows, setRows] = useState<{ key: string; value: string }[] | null>(
    paramSetId ? null : SUGGESTED.map((key) => ({ key, value: key === "MqttPort" ? "8883" : "" })),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  /** Set when the server refused a breaking save. Holding it is what turns
   *  Save into "Save anyway" — the force flag is never on by default. */
  const [refused, setRefused] = useState<string | null>(null);
  const modal = useModal(() => onClose(false), { active: true });

  useEffect(() => {
    if (!paramSetId) return;
    let alive = true;
    getParamSetValues(paramSetId)
      .then((detail) => {
        if (!alive) return;
        setName(detail.name);
        setRows(
          Object.entries(detail.values).map(([key, value]) => ({ key, value: String(value) })),
        );
      })
      .catch((err) => alive && setError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [paramSetId]);

  const set = (i: number, patch: Partial<{ key: string; value: string }>) =>
    setRows((cur) => (cur ?? []).map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const save = async (force = false) => {
    if (!name.trim()) {
      setError("the set needs a name");
      return;
    }
    const values: Record<string, string> = {};
    for (const r of rows ?? []) if (r.key.trim()) values[r.key.trim()] = r.value;
    setBusy(true);
    setError(null);
    try {
      await putParamSet(projectId, name.trim(), values, "", { note, force });
      onClose(true);
    } catch (err) {
      const msg = errorMessage(err);
      setError(msg);
      // A refusal names the versions it protects, so offering the override
      // right there is honest. Anything else is a plain failure.
      setRefused(msg.includes("would break a published version") ? msg : null);
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">
          {paramSetId ? `Param set “${name}”` : "New param set"}
        </h2>
        <p className="card-subtitle">
          What a procedure interpolates as {"{placeholders}"} — WiFi, MQTT, the creds salt.
          Shared and NOT versioned: saving changes what every version pointing at this set uses
          on its next run. Each run keeps a masked snapshot of what it was given.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        {rows === null ? (
          <Spinner label="Loading values…" />
        ) : (
          <>
            {!paramSetId ? (
              <input
                className="text modal-input mono"
                placeholder="set name, e.g. production"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            ) : null}
            {rows.map((r, i) => {
              const uses = usedBy[r.key] ?? [];
              return (
                <div key={i} className="param-row">
                  <input
                    className="row-input mono"
                    placeholder="key"
                    value={r.key}
                    onChange={(e) => set(i, { key: e.target.value })}
                  />
                  <input
                    className="row-input mono"
                    placeholder="value"
                    value={r.value}
                    onChange={(e) => set(i, { value: e.target.value })}
                  />
                  <button
                    type="button"
                    className="btn btn-sm row-del"
                    title={uses.length
                      ? `Needed by ${uses.map((u) => `${u.deployment} v${u.version_no}`).join(", ")} — the server will refuse this`
                      : "Remove this row"}
                    onClick={() => setRows((cur) => (cur ?? []).filter((_, j) => j !== i))}
                  >
                    ×
                  </button>
                  {uses.length ? (
                    <span className="param-uses muted dim" title={uses.map((u) => `${u.deployment} v${u.version_no}`).join(", ")}>
                      needed by {uses.length} published version{uses.length === 1 ? "" : "s"}
                    </span>
                  ) : (
                    <span className="param-uses" />
                  )}
                </div>
              );
            })}
            <input
              className="text modal-input"
              placeholder="what changed and why — kept on the revision, and it is the only record of a value change"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <div className="btn-row modal-actions">
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setRows((cur) => [...(cur ?? []), { key: "", value: "" }])}
              >
                Add row
              </button>
              <button type="button" className="btn" onClick={() => onClose(false)} disabled={busy}>
                Cancel
              </button>
              {refused ? (
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => void save(true)}
                  disabled={busy}
                  title="Those versions will stop validating and cannot be run until the key comes back"
                >
                  Save anyway
                </button>
              ) : null}
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void save(false)}
                disabled={busy}
              >
                {busy ? "Saving…" : "Save"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
