/** User administration for the Setup page.
 *
 * The only place accounts are made. There is no self-registration and no
 * password recovery anywhere in the platform (user decision 2026-07-31), so an
 * admin resetting a password here IS the recovery story.
 *
 * Expanding a row reveals that user's API token and the two links built from
 * it: the personal PCM repository URL and the personal `.kicad_httplib`. Those
 * are the whole client-setup flow — the user pastes one URL into KiCad and the
 * sync plugin arrives with their token already inside it.
 */
import { useCallback, useEffect, useState } from "react";

import {
  addUserToken,
  createUser,
  deleteUser,
  errorMessage,
  getUser,
  getUsers,
  isAbortError,
  revokeUserSessions,
  revokeUserToken,
  updateUser,
  type PlatformUser,
} from "../api";
import { useDialog } from "./Dialog";
import { ErrorBanner, Spinner } from "./Ui";
import DataTable, { type Column } from "./DataTable";

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  if (!value) return null;
  return (
    <div className="user-url-row">
      <span className="muted">{label}</span>
      <code className="user-url" title={value}>
        {value}
      </code>
      <button
        className="btn btn-sm"
        onClick={() => {
          void navigator.clipboard.writeText(value).then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          });
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function UserDetail({
  user,
  onChanged,
}: {
  user: PlatformUser;
  onChanged: (u: PlatformUser) => void;
}) {
  const dialog = useDialog();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<PlatformUser | { ok: boolean }>) {
    setBusy(true);
    setError("");
    try {
      const res = await action();
      if ("id" in res) onChanged(res);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="user-detail">
      <ErrorBanner message={error} />

      <p className="muted dim">
        Paste the repository URL into KiCad under Preferences &gt; Plugin and Content
        Manager &gt; Manage Repositories. The sync plugin it installs already carries
        this token, so nothing else needs to be entered.
      </p>
      <CopyRow label="PCM repository" value={user.repository_url} />
      <CopyRow label="KiCad HTTP library" value={user.httplib_url} />

      {user.tokens.map((t) => (
        <div className="user-url-row" key={t.id}>
          <span className="muted">{t.label || "token"}</span>
          <code className="user-url" title={t.token || t.prefix}>
            {t.token || `${t.prefix}…`}
          </code>
          <span className="muted dim">
            {t.last_used_at ? `used ${t.last_used_at.slice(0, 10)}` : "never used"}
          </span>
          <button
            className="btn btn-sm btn-danger"
            disabled={busy}
            onClick={async () => {
              const ok = await dialog.confirm(
                `Revoke token ${t.prefix}…? Every KiCad install and MCP client using it stops working until it is replaced.`,
                { title: "Revoke token", confirmLabel: "Revoke", tone: "danger" },
              );
              if (ok) await run(() => revokeUserToken(user.id, t.id));
            }}
          >
            Revoke
          </button>
        </div>
      ))}

      <div className="btn-row">
        <button
          className="btn btn-sm"
          disabled={busy}
          onClick={() => void run(() => addUserToken(user.id, "KiCad + MCP"))}
        >
          New token
        </button>
        <button
          className="btn btn-sm"
          disabled={busy}
          onClick={async () => {
            const pw = await dialog.prompt(`New password for ${user.username}:`, {
              title: "Reset password",
            });
            if (pw) await run(() => updateUser(user.id, { password: pw }));
          }}
        >
          Reset password
        </button>
        <button
          className="btn btn-sm"
          disabled={busy}
          onClick={async () => {
            const name = await dialog.prompt(
              `New username for ${user.username}. Their API tokens are unaffected, so KiCad keeps working.`,
              { title: "Rename user" },
            );
            if (name) await run(() => updateUser(user.id, { username: name }));
          }}
        >
          Rename
        </button>
        <button
          className="btn btn-sm"
          disabled={busy || user.session_count === 0}
          onClick={() => void run(() => revokeUserSessions(user.id))}
        >
          Sign out ({user.session_count})
        </button>
        <button
          className="btn btn-sm"
          disabled={busy}
          onClick={() =>
            void run(() =>
              updateUser(user.id, { role: user.role === "admin" ? "user" : "admin" }),
            )
          }
        >
          Make {user.role === "admin" ? "user" : "admin"}
        </button>
        <button
          className="btn btn-sm"
          disabled={busy}
          onClick={() => void run(() => updateUser(user.id, { active: !user.active }))}
        >
          {user.active ? "Deactivate" : "Activate"}
        </button>
      </div>
    </div>
  );
}

export default function UsersCard() {
  const dialog = useDialog();
  const [users, setUsers] = useState<PlatformUser[] | null>(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PlatformUser | null>(null);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("user");
  const [busy, setBusy] = useState(false);

  const load = useCallback((signal?: AbortSignal) => {
    getUsers(signal)
      .then(setUsers)
      .catch((err) => {
        if (isAbortError(err)) return;
        // 403 is not a failure to report loudly — a non-admin simply has no
        // business here, and the card hides itself below.
        setUsers([]);
        setError(errorMessage(err));
      });
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  // The list withholds token values on purpose, so opening a row fetches the
  // one user again — that read is the only one that reveals them.
  useEffect(() => {
    if (openId === null) {
      setDetail(null);
      return;
    }
    const ctrl = new AbortController();
    getUser(openId, ctrl.signal)
      .then(setDetail)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [openId]);

  async function add() {
    setBusy(true);
    setError("");
    try {
      const created = await createUser({
        username,
        password,
        display_name: displayName,
        role,
      });
      setUsername("");
      setDisplayName("");
      setPassword("");
      setRole("user");
      load();
      setOpenId(created.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (users === null) return <Spinner label="Loading users…" />;

  const cols: Column<(typeof users)[number]>[] = [
    {
      key: "username",
      label: "Username",
      width: 22,
      get: (u) => u.username,
      render: (u) => (
        <>
          <span className="ledger-caret">{openId === u.id ? "▾" : "▸"}</span> {u.username}
        </>
      ),
    },
    { key: "display_name", label: "Name", width: 24, get: (u) => u.display_name },
    { key: "role", label: "Role", width: 12, get: (u) => u.role },
    {
      key: "active",
      label: "Active",
      width: 10,
      className: "ctr",
      get: (u) => (u.active ? "yes" : "no"),
    },
    {
      key: "last_login",
      label: "Last sign-in",
      width: 20,
      className: "muted dim",
      get: (u) => u.last_login_at?.slice(0, 16) ?? "never",
    },
    {
      key: "delete",
      label: "Delete",
      width: 12,
      interactive: false,
      className: "ctr",
      get: () => "",
      render: (u) => (
        <button
          className="btn btn-sm btn-danger"
          onClick={async (e) => {
            e.stopPropagation();
            const ok = await dialog.confirm(
              `Delete ${u.username}? Their sessions and API tokens go with them, and any KiCad install using one stops working.`,
              { title: "Delete user", confirmLabel: "Delete", tone: "danger" },
            );
            if (!ok) return;
            try {
              await deleteUser(u.id);
              setOpenId(null);
              load();
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        >
          Delete
        </button>
      ),
    },
  ];

  return (
    <div className="card pad">
      <h2>Users</h2>
      <p className="muted">
        Accounts are created here and nowhere else. The platform has no sign-up page
        and no password recovery — reset a forgotten password below.
      </p>

      <ErrorBanner message={error} />

      <div className="table-wrap">
        <DataTable
          columns={cols}
          rows={users}
          rowKey={(u) => u.id}
          persistKey="users"
          openKey={openId}
          onOpenChange={(k) => setOpenId(k === null ? null : Number(k))}
          expand={() =>
            detail !== null ? (
              <UserDetail
                user={detail}
                onChanged={(next) => {
                  setDetail(next);
                  load();
                }}
              />
            ) : (
              <Spinner label="Loading user" />
            )
          }
          empty="No users."
        />
      </div>

      <h3 className="users-add-heading">Add a user</h3>
      <div className="user-form">
        <label className="login-field">
          <span className="login-label">Username</span>
          <input
            className="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="off"
          />
        </label>
        <label className="login-field">
          <span className="login-label">Display name</span>
          <input
            className="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            autoComplete="off"
          />
        </label>
        <label className="login-field">
          <span className="login-label">Password</span>
          <input
            className="text"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
        </label>
        <label className="login-field">
          <span className="login-label">Role</span>
          <select className="text" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <button
          className="btn btn-primary user-form-submit"
          disabled={busy || !username.trim() || password.length < 10}
          onClick={() => void add()}
        >
          Create
        </button>
      </div>
      <p className="muted dim">
        The password must be at least 10 characters. A new account gets an API token
        immediately — open its row to copy the KiCad links.
      </p>
    </div>
  );
}
