/** Edit one param set's VALUES — the WiFi credentials, the MQTT host, the
 *  creds salt, the default SIM PIN — wherever the operator happens to be.
 *
 *  Extracted from `ParamSetsPanel` so the deployment window can open the same
 *  editor (2026-09-17, user request: "deployment tab should allow user to fully
 *  configure the deployment"). Administering the SET — listing, renaming,
 *  deleting — stays on the files page; what a version needs is to change what
 *  it interpolates, and that is this box.
 *
 *  A param set is NOT versioned, and that is deliberate (design.md §14): the
 *  values are shared across every version and every project batch, encrypted at
 *  rest, and snapshotted masked onto each run. So saving here changes what the
 *  NEXT run of every version pointing at this set will use — the card says so,
 *  because the deployment page otherwise reads like a place where edits are
 *  versioned.
 */
import { useEffect, useState } from "react";
import { errorMessage, getParamSetValues, putParamSet } from "../../api";
import { ErrorBanner, Spinner } from "../Ui";
import { useModal } from "../modal";

/** Keys a new set starts with: what every V2 procedure interpolates. Typing
 *  six key names from memory is how a set ends up with `SSID1` in it. */
const SUGGESTED = ["SSId1", "Password1", "MqttHost", "MqttPort", "creds_salt", "sim_pin"];

/** Values never printed in the open. The API stores every value encrypted; this
 *  is about the screen, where a bench is often in a room with other people. */
const SECRET = /pass|pin|salt|secret|token|key$/i;

export interface ParamSetEditorProps {
  projectId: number;
  /** Existing set to edit. Omit (with `name`) to create one. */
  paramSetId?: number | null;
  /** Name for a NEW set. Ignored when `paramSetId` is given. */
  newName?: string;
  onClose: (saved: boolean) => void;
}

export default function ParamSetEditor(props: ParamSetEditorProps) {
  const { projectId, paramSetId, newName, onClose } = props;
  const [name, setName] = useState(newName ?? "");
  const [rows, setRows] = useState<{ key: string; value: string }[] | null>(
    paramSetId ? null : SUGGESTED.map((key) => ({ key, value: key === "MqttPort" ? "8883" : "" })),
  );
  const [shown, setShown] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
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

  const save = async () => {
    if (!name.trim()) {
      setError("the set needs a name");
      return;
    }
    const values: Record<string, string> = {};
    for (const r of rows ?? []) if (r.key.trim()) values[r.key.trim()] = r.value;
    setBusy(true);
    setError(null);
    try {
      await putParamSet(projectId, name.trim(), values);
      onClose(true);
    } catch (err) {
      setError(errorMessage(err));
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
              const secret = SECRET.test(r.key) && !shown.has(i);
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
                    type={secret ? "password" : "text"}
                    value={r.value}
                    onChange={(e) => set(i, { value: e.target.value })}
                  />
                  {SECRET.test(r.key) ? (
                    <button
                      type="button"
                      className="btn btn-sm"
                      title={secret ? "Show this value" : "Hide it again"}
                      onClick={() =>
                        setShown((cur) => {
                          const next = new Set(cur);
                          if (next.has(i)) next.delete(i);
                          else next.add(i);
                          return next;
                        })
                      }
                    >
                      {secret ? "show" : "hide"}
                    </button>
                  ) : (
                    <span />
                  )}
                  <button
                    type="button"
                    className="btn btn-sm row-del"
                    onClick={() => setRows((cur) => (cur ?? []).filter((_, j) => j !== i))}
                  >
                    ×
                  </button>
                </div>
              );
            })}
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
              <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
                {busy ? "Saving…" : "Save"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
