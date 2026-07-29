/** Editable runtime configuration — the first card on the Setup page.
 *
 * Values come from `Settings` on the API, which reads the environment; saving
 * one writes a database override that wins over it, and Revert drops the
 * override. Two things the UI has to be honest about, because the backend
 * cannot hide them:
 *
 *   - A secret is never sent back. The API reports only whether one is set, so
 *     the field offers "replace", never "edit".
 *   - Some values are only read when the app starts (the nightly datasheet
 *     re-check, the autofetch threads). Those say so, and saving one reports
 *     that a restart is needed rather than implying it already applies.
 */
import { useEffect, useState } from "react";
import {
  errorMessage,
  getSettings,
  isAbortError,
  revertSetting,
  setSetting,
  type SettingGroup,
  type SettingItem,
} from "../api";
import { useDialog } from "./Dialog";
import { ErrorBanner, Spinner } from "./Ui";

/** The value as it should appear in a text input. */
function asText(it: SettingItem): string {
  if (it.secret) return "";
  if (it.value === null || it.value === undefined) return "";
  return String(it.value);
}

export default function SettingsCard() {
  const dialog = useDialog();
  const [groups, setGroups] = useState<SettingGroup[] | null>(null);
  const [error, setError] = useState("");
  /** Per-key pending edit. Absent = not touched. */
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [restartKeys, setRestartKeys] = useState<string[]>([]);

  const load = (signal?: AbortSignal) =>
    getSettings(signal)
      .then((d) => {
        setGroups(d.groups);
        setEdits({});
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, []);

  async function save(it: SettingItem) {
    const value = edits[it.key] ?? asText(it);
    setBusy(it.key);
    setError("");
    try {
      const res = await setSetting(it.key, value);
      if (res.restart_required) {
        setRestartKeys((prev) => (prev.includes(it.label) ? prev : [...prev, it.label]));
      }
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function revert(it: SettingItem) {
    const ok = await dialog.confirm(
      `Drop the stored value for "${it.label}" and use the environment value again?`,
      { title: "Revert setting", confirmLabel: "Revert", tone: "danger" },
    );
    if (!ok) return;
    setBusy(it.key);
    setError("");
    try {
      const res = await revertSetting(it.key);
      if (res.restart_required) {
        setRestartKeys((prev) => (prev.includes(it.label) ? prev : [...prev, it.label]));
      }
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  function field(it: SettingItem) {
    const pending = edits[it.key];
    const current = pending ?? asText(it);
    const set = (v: string) => setEdits((prev) => ({ ...prev, [it.key]: v }));

    if (it.kind === "bool") {
      const on = (pending ?? String(it.value)) === "true";
      return (
        <label className="muted">
          <input
            type="checkbox"
            checked={on}
            disabled={busy === it.key}
            onChange={(e) => set(e.target.checked ? "true" : "false")}
          />{" "}
          {on ? "on" : "off"}
        </label>
      );
    }
    if (it.choices.length > 0) {
      return (
        <select className="row-input" value={current} disabled={busy === it.key} onChange={(e) => set(e.target.value)}>
          {it.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        className="row-input mono"
        type={it.secret ? "password" : it.kind === "int" ? "number" : "text"}
        value={current}
        disabled={busy === it.key}
        placeholder={it.secret ? (it.is_set ? "set — type a new value to replace" : "not set") : ""}
        onChange={(e) => set(e.target.value)}
      />
    );
  }

  if (groups === null && !error) {
    return (
      <div className="card pad">
        <h2>Configuration</h2>
        <Spinner label="Loading settings" />
      </div>
    );
  }

  return (
    <div className="card pad">
      <h2>Configuration</h2>
      <p className="muted">
        Values fall back to the environment; saving one stores an override that wins over it, and
        Revert drops it. Infrastructure settings are deliberately absent — the database URL, the
        object-storage credentials and <code>SECRET_KEY</code> cannot be changed under a running
        platform (the last one decrypts stored git tokens, so a new value would orphan them).
      </p>
      <ErrorBanner message={error} />
      {restartKeys.length > 0 && (
        <div className="banner-warn">
          Saved, but only read at startup — restart the API for these to take effect:{" "}
          {restartKeys.join(", ")}.
        </div>
      )}

      {(groups ?? []).map((g) => (
        <div key={g.group}>
          <h3>{g.group}</h3>
          <table className="kv">
            <tbody>
              {g.items.map((it) => {
                const dirty = edits[it.key] !== undefined && edits[it.key] !== asText(it);
                return (
                  <tr key={it.key}>
                    <td>
                      <div>
                        {it.label}{" "}
                        {it.source === "database" && <span className="pill neutral">stored</span>}{" "}
                        {it.restart && <span className="pill warn">restart</span>}
                      </div>
                      {it.help && <div className="muted">{it.help}</div>}
                    </td>
                    <td>
                      {field(it)}
                      <div className="btn-row">
                        <button
                          className="btn btn-sm btn-primary"
                          disabled={busy === it.key || (!dirty && !it.secret)}
                          onClick={() => save(it)}
                        >
                          {busy === it.key ? "Saving…" : "Save"}
                        </button>
                        {it.source === "database" && (
                          <button
                            className="btn btn-sm"
                            disabled={busy === it.key}
                            onClick={() => revert(it)}
                          >
                            Revert
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
