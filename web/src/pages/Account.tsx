/** The signed-in user's own settings, reached by clicking their name in the
 *  top bar.
 *
 *  It is deliberately NOT the Admin page. Admin is administration of the
 *  platform — other people's accounts, the deployment's knobs. This is the
 *  things that belong to whoever is signed in: who they are, and the git
 *  accounts they have taught the platform to authenticate as.
 */
import { Link } from "react-router-dom";

import { useAuth } from "../auth";
import AccountSecurityCard from "../components/AccountSecurityCard";
import GitCredentialsCard from "../components/GitCredentialsCard";
import KicadClientCards from "../components/KicadClientCards";

export default function Account() {
  const { user, isAdmin } = useAuth();

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

        <AccountSecurityCard />
        <GitCredentialsCard />
        <KicadClientCards />
      </div>
    </div>
  );
}
