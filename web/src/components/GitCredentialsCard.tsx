/** Git account tokens, named once and assigned to projects by name.
 *
 *  Before this every project stored its own copy of a token, so three projects
 *  on one GitHub account held three copies of one secret and nothing compared
 *  them. Production carried a project whose copy had been revoked while its two
 *  siblings worked; the only symptom was a fetch failing with "could not read
 *  Username", which reads like a prompt bug rather than a dead credential.
 *
 *  Two rules this card exists to make visible:
 *  - **The token never comes back out.** The field says "replace", never
 *    "edit", like every other secret in the platform (`SettingsCard`).
 *  - **A credential nobody has checked is not claimed to be good.** Check runs
 *    the same `git ls-remote` a fetch uses, per project, and the verdict is
 *    shown with the date it was taken.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  checkGitCredential,
  createGitCredential,
  deleteGitCredential,
  errorMessage,
  getGitCredentials,
  isAbortError,
  updateGitCredential,
  type GitCredential,
  type GitCredentialCheck,
} from "../api";
import Field from "./Field";
import DataTable, { type Column } from "./DataTable";
import { useDialog } from "./Dialog";
import { ErrorBanner, Spinner } from "./Ui";

function CredentialDetail({
  cred,
  onChanged,
}: {
  cred: GitCredential;
  onChanged: () => void;
}) {
  const dialog = useDialog();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({
    name: cred.name,
    host: cred.host,
    username: cred.username,
    description: cred.description,
  });
  const [token, setToken] = useState("");
  const [checked, setChecked] = useState<GitCredentialCheck | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="field-stack">
      {error ? <ErrorBanner message={error} /> : null}

      <div className="field-row">
        <Field label="Name">
          <input
            className="text"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
        </Field>
        <Field label="Host">
          <input
            className="text"
            placeholder="github.com"
            value={draft.host}
            onChange={(e) => setDraft({ ...draft, host: e.target.value })}
          />
        </Field>
        <Field label="Account">
          <input
            className="text"
            placeholder="the login this token belongs to"
            value={draft.username}
            onChange={(e) => setDraft({ ...draft, username: e.target.value })}
          />
        </Field>
        <Field label="Note" wide>
          <input
            className="text"
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          />
        </Field>
        <Field label="Replace the token" wide>
          <input
            className="text"
            type="password"
            autoComplete="new-password"
            placeholder="leave blank to keep the stored one"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </Field>
      </div>

      <div className="btn-row">
        <button
          type="button"
          className="btn btn-sm btn-primary"
          disabled={busy || !draft.name.trim()}
          onClick={() =>
            void run(async () => {
              await updateGitCredential(cred.id, {
                ...draft,
                ...(token.trim() ? { token: token.trim() } : {}),
              });
              setToken("");
            })
          }
        >
          Save
        </button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              setChecked(await checkGitCredential(cred.id));
            })
          }
        >
          Check
        </button>
        <button
          type="button"
          className="btn btn-sm btn-danger"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              const ok = await dialog.confirm(
                `Delete the credential "${cred.name}"?`,
                { title: "Delete credential", confirmLabel: "Delete", tone: "danger" },
              );
              if (!ok) return;
              await deleteGitCredential(cred.id);
            })
          }
        >
          Delete
        </button>
        {busy ? <Spinner /> : null}
      </div>

      {checked ? (
        <div className="cred-results">
          {checked.results.length === 0 ? (
            <p className="muted">
              Not used by any project yet, so there is no repository to test it against.
              Assign it to a project first.
            </p>
          ) : (
            <ul>
              {checked.results.map((r) => (
                <li key={r.project_id}>
                  <span className={`pill ${r.ok ? "ok" : "err"}`}>{r.ok ? "ok" : "failed"}</span>{" "}
                  <Link className="comp-link" to={`/projects/${r.project_id}`}>
                    {r.project}
                  </Link>
                  {r.detail ? <span className="muted"> — {r.detail}</span> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      <p className="muted">
        {cred.projects.length === 0
          ? "No project uses this credential."
          : "Used by: "}
        {cred.projects.map((p, i) => (
          <span key={p.id}>
            {i > 0 ? ", " : ""}
            <Link className="comp-link" to={`/projects/${p.id}`}>
              {p.name}
            </Link>
          </span>
        ))}
      </p>
    </div>
  );
}

export default function GitCredentialsCard() {
  const [rows, setRows] = useState<GitCredential[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: "", host: "", username: "", token: "" });

  const load = useCallback(
    (signal?: AbortSignal) =>
      getGitCredentials(signal)
        .then(setRows)
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

  const add = async () => {
    setBusy(true);
    setError(null);
    try {
      const made = await createGitCredential({
        name: form.name.trim(),
        token: form.token.trim(),
        host: form.host.trim(),
        username: form.username.trim(),
      });
      setForm({ name: "", host: "", username: "", token: "" });
      await load();
      setOpenId(made.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const cols: Column<GitCredential>[] = [
    { key: "name", label: "Name", width: 26, get: (c) => c.name },
    { key: "host", label: "Host", width: 18, className: "mono", get: (c) => c.host || "—" },
    { key: "username", label: "Account", width: 18, get: (c) => c.username || "—" },
    {
      key: "projects",
      label: "Used by",
      width: 22,
      get: (c) => c.projects.map((p) => p.name).join(", ") || "nothing",
    },
    {
      key: "check",
      label: "Last check",
      width: 16,
      // A credential nobody tested must not read as working.
      get: (c) => (c.check_ok === null ? "not checked" : c.check_ok ? "ok" : "failed"),
      render: (c) => (
        <span
          className={`pill ${c.check_ok === null ? "neutral" : c.check_ok ? "ok" : "err"}`}
          title={c.check_detail || undefined}
        >
          {c.check_ok === null ? "not checked" : c.check_ok ? "ok" : "failed"}
        </span>
      ),
    },
  ];

  return (
    <div className="card pad">
      <h2 className="card-title">Git credentials</h2>
      <p className="muted">
        A token belongs to an ACCOUNT, not to each project that uses it. Name one here and
        pick it by name on any project — rotating it is then one edit in one place. A
        project can still carry its own token instead, for a one-off repository.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      <div className="table-wrap">
        {rows === null ? (
          <Spinner label="Loading credentials" />
        ) : (
          <DataTable
            columns={cols}
            rows={rows}
            rowKey={(c) => c.id}
            persistKey="git-credentials"
            openKey={openId}
            onOpenChange={(k) => setOpenId(k === null ? null : Number(k))}
            expand={(c) => <CredentialDetail cred={c} onChanged={() => void load()} />}
            empty="No credentials yet."
          />
        )}
      </div>

      <h3>Add a credential</h3>
      <div className="field-row">
        <Field label="Name">
          <input
            className="text"
            placeholder="GitHub — mszkowalik"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        <Field label="Host">
          <input
            className="text"
            placeholder="github.com"
            value={form.host}
            onChange={(e) => setForm({ ...form, host: e.target.value })}
          />
        </Field>
        <Field label="Account">
          <input
            className="text"
            placeholder="optional"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
          />
        </Field>
        <Field label="Token" wide>
          <input
            className="text"
            type="password"
            autoComplete="new-password"
            value={form.token}
            onChange={(e) => setForm({ ...form, token: e.target.value })}
          />
        </Field>
      </div>
      <div className="btn-row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !form.name.trim() || !form.token.trim()}
          onClick={() => void add()}
        >
          Create
        </button>
        {busy ? <Spinner /> : null}
      </div>
    </div>
  );
}
