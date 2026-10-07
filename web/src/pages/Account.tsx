/** The signed-in user's own settings, reached by clicking their name in the
 *  top bar.
 *
 *  It is deliberately NOT the Admin page. Admin is administration of the
 *  platform — other people's accounts, the deployment's knobs. This is the
 *  things that belong to whoever is signed in: who they are, how the platform
 *  looks to them, the git accounts they have taught it to authenticate as, and
 *  the clients — KiCad and agents — that act as them.
 *
 *  The page owns the account record (`me`) because two cards show its tokens:
 *  the password-and-tokens card and the MCP card.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage, getAccount, isAbortError, type PlatformUser } from "../api";
import { useAuth } from "../auth";
import AccountSecurityCard from "../components/AccountSecurityCard";
import AppearanceCard from "../components/AppearanceCard";
import GitCredentialsCard from "../components/GitCredentialsCard";
import KicadClientCards from "../components/KicadClientCards";
import McpSetupCard from "../components/McpSetupCard";
import { ErrorBanner } from "../components/Ui";

export default function Account() {
  const { user, isAdmin } = useAuth();
  const [me, setMe] = useState<PlatformUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getAccount(ctrl.signal)
      .then(setMe)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, []);

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Account</h1>
        </div>

        {user ? (
          <div className="card pad">
            <h2 className="card-title">Signed in as</h2>
            <dl className="kv">
              <dt>User</dt>
              <dd className="mono">{user.username}</dd>
              {user.display_name ? (
                <>
                  <dt>Name</dt>
                  <dd>{user.display_name}</dd>
                </>
              ) : null}
              <dt>Role</dt>
              <dd>{user.role}</dd>
            </dl>
            <p className="muted">
              Other people's accounts are administered on{" "}
              <Link className="comp-link" to="/admin">
                Admin
              </Link>
              {isAdmin ? " → Users." : "."}
            </p>
          </div>
        ) : null}

        <ErrorBanner message={error ?? ""} />
        <AppearanceCard />
        <AccountSecurityCard me={me} setMe={setMe} />
        <GitCredentialsCard />
        <KicadClientCards />
        <McpSetupCard me={me} />
      </div>
    </div>
  );
}
