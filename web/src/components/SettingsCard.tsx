/** Editable runtime configuration — the Admin page's Configuration tab.
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
import { CheckField } from "./Field";
import { useDialog } from "./Dialog";
import InfoTip from "./InfoTip";
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

    // `.row-input` and not `.text`: these ARE table rows now, and the compact
    // size is what keeps a setting to one line. See `web/CLAUDE.md`, "there
    // are exactly TWO input sizes".
    if (it.kind === "bool") {
      const on = (pending ?? String(it.value)) === "true";
      return (
        <CheckField checked={on} disabled={busy === it.key} onChange={(v) => set(v ? "true" : "false")}>
          {on ? "on" : "off"}
        </CheckField>
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
        A value falls back to the environment. Saving one stores an override that wins over it,
        and Revert drops it.{" "}
        <InfoTip label="Why some settings are missing">
          Infrastructure settings are deliberately absent — the database URL, the object-storage
          credentials and SECRET_KEY cannot be changed under a running platform. The last one
          decrypts stored git tokens, so a new value would orphan them.
        </InfoTip>
      </p>
      <ErrorBanner message={error} />
      {restartKeys.length > 0 && (
        <div className="banner-warn">
          Saved, but only read at startup — restart the API for these to take effect:{" "}
          {restartKeys.join(", ")}.
        </div>
      )}

      {/* ONE LINE PER SETTING. The help text used to sit under the label and
          the buttons under the field, which made every one of the 24 settings
          about 100 px tall — the Render group was four screens below the
          Address group. The help is now an `InfoTip`, which shows more of it
          than the old two-line clamp did, and the buttons share the row.
          Save appears only when something differs from what is stored, the
          rule `.param-save` already follows — including on a SECRET, which
          used to carry a standing Save button because its field always reads
          empty. That button wrote the empty string, which is not how a stored
          secret is cleared (Revert is); typing is what makes the row dirty. */}
      {(groups ?? []).map((g) => (
        <div key={g.group}>
          <h3 className="card-subtitle">{g.group}</h3>
          <table className="kv settings-table">
            <tbody>
              {g.items.map((it) => {
                const dirty = edits[it.key] !== undefined && edits[it.key] !== asText(it);
                return (
                  <tr key={it.key}>
                    <td>
                      <div className="set-head">
                        <span className="set-name" title={it.label}>{it.label}</span>
                        {it.help ? <InfoTip label={`About ${it.label}`}>{it.help}</InfoTip> : null}
                        {it.source === "database" && <span className="pill neutral">stored</span>}
                        {it.restart && <span className="pill warn">restart</span>}
                      </div>
                    </td>
                    <td>{field(it)}</td>
                    <td>
                      <div className="btn-row">
                        {dirty ? (
                          <button
                            className="btn btn-sm btn-primary"
                            disabled={busy === it.key}
                            onClick={() => save(it)}
                          >
                            {busy === it.key ? "Saving…" : "Save"}
                          </button>
                        ) : null}
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
