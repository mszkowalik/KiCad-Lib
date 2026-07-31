/** The sign-in screen.
 *
 * Deliberately the whole page rather than a route: `AuthGate` renders this
 * INSTEAD of the router, so there is no app chrome to click through and no
 * half-loaded screen behind it.
 *
 * No "create account" and no "forgot password" link. Accounts are made by an
 * admin on the Setup page and passwords are reset there — see
 * `api/app/routers/auth.py`, which has no endpoint for either.
 */
import { useState, type FormEvent } from "react";

import { errorMessage, type AuthUser } from "../api";
import { ErrorBanner } from "../components/Ui";

interface Props {
  signIn: (username: string, password: string) => Promise<AuthUser>;
  onSignedIn: (user: AuthUser) => void;
}

export default function Login({ signIn, onSignedIn }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      onSignedIn(await signIn(username, password));
    } catch (err) {
      setError(errorMessage(err));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="card login-card" onSubmit={submit}>
        <h1 className="login-brand">Project Management Platform</h1>
        <p className="login-sub muted">7Sigma component library</p>

        <ErrorBanner message={error} />

        <label className="login-field">
          <span className="login-label">Username</span>
          <input
            className="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>

        <label className="login-field">
          <span className="login-label">Password</span>
          <input
            className="text"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        <button className="btn btn-primary login-submit" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p className="login-note muted dim">
          Accounts are created by an administrator.
        </p>
      </form>
    </div>
  );
}
