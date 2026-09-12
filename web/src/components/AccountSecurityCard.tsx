/** The signed-in user's own password and API tokens.
 *
 *  `UsersCard` does the same two things for OTHER people and is admin-only.
 *  The difference that matters is the password: an admin RESETS one for
 *  somebody who lost it, a user CHANGES their own and must type the current one
 *  first — otherwise a borrowed session is enough to lock the owner out.
 *
 *  **A token is shown in full, on purpose.** It is baked into a personal PCM
 *  repository URL, so show-once would mean a rotation and a KiCad re-install
 *  every time somebody loses the link (the decision `routers/users.py` records).
 *  Revoking is not deleting: the row is the record that the credential existed
 *  and when it was last used.
 */
import { useCallback, useEffect, useState } from "react";

import {
  addOwnToken,
  changeOwnPassword,
  errorMessage,
  getAccount,
  isAbortError,
  revokeOwnToken,
  type PlatformUser,
} from "../api";
import Field from "./Field";
import { useDialog } from "./Dialog";
import { ErrorBanner, Spinner } from "./Ui";

export default function AccountSecurityCard() {
  const dialog = useDialog();
  const [me, setMe] = useState<PlatformUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pw, setPw] = useState({ current: "", next: "", again: "" });
  const [label, setLabel] = useState("");

  const load = useCallback(
    (signal?: AbortSignal) =>
      getAccount(signal)
        .then(setMe)
        .catch((err) => {
          if (!isAbortError(err)) setError(errorMessage(err));
        }),
    [],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const mismatch = pw.next !== "" && pw.again !== "" && pw.next !== pw.again;

  return (
    <div className="card pad">
      <h2 className="card-title">Password and API tokens</h2>
      {error ? <ErrorBanner message={error} /> : null}

      <h3>Change your password</h3>
      <div className="field-row">
        <Field label="Current password">
          <input
            className="row-input"
            type="password"
            autoComplete="current-password"
            value={pw.current}
            onChange={(e) => setPw({ ...pw, current: e.target.value })}
          />
        </Field>
        <Field label="New password">
          <input
            className="row-input"
            type="password"
            autoComplete="new-password"
            value={pw.next}
            onChange={(e) => setPw({ ...pw, next: e.target.value })}
          />
        </Field>
        <Field label="Repeat it">
          <input
            className="row-input"
            type="password"
            autoComplete="new-password"
            value={pw.again}
            onChange={(e) => setPw({ ...pw, again: e.target.value })}
          />
        </Field>
      </div>
      {mismatch ? <p className="err-text">The two new passwords do not match.</p> : null}
      <p className="muted">
        Changing it ends every OTHER session — a change that left them alive would not have
        changed anything — and re-issues this one, so you stay signed in here.
      </p>
      <div className="btn-row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !pw.current || !pw.next || mismatch}
          onClick={() =>
            void run(async () => {
              await changeOwnPassword(pw.current, pw.next);
              setPw({ current: "", next: "", again: "" });
              await dialog.alert(
                "Password changed. Every other session was signed out.",
                { title: "Password changed" },
              );
            })
          }
        >
          Change password
        </button>
        {busy ? <Spinner /> : null}
      </div>

      <h3>API tokens</h3>
      <p className="muted">
        One token authenticates KiCad, the sync plugin and the MCP server as you. The links
        below carry it, so treat them as the credential they are.
      </p>
      {me === null ? (
        <Spinner label="Loading account" />
      ) : me.tokens.length === 0 ? (
        <p className="muted">No token yet — create one to get your personal KiCad links.</p>
      ) : (
        <table className="data data-fixed account-tokens">
          <colgroup>
            <col style={{ width: "24%" }} />
            <col style={{ width: "44%" }} />
            <col style={{ width: "20%" }} />
            <col style={{ width: "12%" }} />
          </colgroup>
          <thead>
            <tr>
              <th>Label</th>
              <th>Token</th>
              <th>Last used</th>
              <th className="ctr">Revoke</th>
            </tr>
          </thead>
          <tbody>
            {me.tokens.map((t) => (
              <tr key={t.id}>
                <td>{t.label || <span className="muted">—</span>}</td>
                <td className="mono" title={t.token || t.prefix}>
                  {t.token || `${t.prefix}…`}
                </td>
                <td className="muted">
                  {t.last_used_at ? t.last_used_at.slice(0, 10) : "never"}
                </td>
                <td className="ctr">
                  <button
                    type="button"
                    className="row-del"
                    title="Revoke this token"
                    onClick={() =>
                      void run(async () => {
                        const ok = await dialog.confirm(
                          "Revoke this token? Anything using it — KiCad, the sync plugin, " +
                            "the MCP server — stops working until you paste a new one.",
                          { title: "Revoke token", confirmLabel: "Revoke", tone: "danger" },
                        );
                        if (!ok) return;
                        setMe(await revokeOwnToken(t.id));
                      })
                    }
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="field-row">
        <Field label="New token label">
          <input
            className="row-input"
            placeholder="laptop, bench PC…"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
        </Field>
      </div>
      <div className="btn-row">
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              setMe(await addOwnToken(label.trim()));
              setLabel("");
            })
          }
        >
          Create a token
        </button>
        {busy ? <Spinner /> : null}
      </div>
    </div>
  );
}
