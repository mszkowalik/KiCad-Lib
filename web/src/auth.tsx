/** Sign-in state for the whole SPA.
 *
 * `AuthGate` wraps the router in `App.tsx`, so nothing renders until the server
 * has answered "who are you?". That ordering matters: a screen that mounts
 * first and fetches second would fire a dozen requests as an anonymous user and
 * paint a dozen error banners before the login form appeared.
 *
 * There is no sign-up and no password reset here, by design — an admin creates
 * accounts on the Setup page. Do not add a link for either.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  getAuthState,
  login as apiLogin,
  logout as apiLogout,
  setUnauthorizedHandler,
  type AuthUser,
} from "./api";
import Login from "./pages/Login";
import { Spinner } from "./components/Ui";

interface AuthContextValue {
  user: AuthUser | null;
  /** False when the API runs with AUTH_ENABLED=0 (local development). */
  authEnabled: boolean;
  isAdmin: boolean;
  signOut: () => Promise<void>;
  /** Re-read `/api/auth/me` — call after anything that can change the role. */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  authEnabled: false,
  isAdmin: true,
  signOut: async () => {},
  refresh: async () => {},
});

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authEnabled, setAuthEnabled] = useState(true);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const state = await getAuthState();
      setAuthEnabled(state.auth_enabled);
      setUser(state.user);
    } catch {
      // `/api/auth/me` is one of the few endpoints the gate lets through, so a
      // failure here means the API is unreachable, not that we are signed out.
      // Showing the login form is the honest answer either way.
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Any 401 from any endpoint drops us back to the login form. Registered once
  // for the whole app — see `setUnauthorizedHandler` in api.ts.
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    return () => setUnauthorizedHandler(null);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      authEnabled,
      // With auth off there is no user to ask, and every control stays usable —
      // the API takes the same posture in that mode.
      isAdmin: !authEnabled || user?.is_admin === true,
      signOut,
      refresh,
    }),
    [user, authEnabled, signOut, refresh],
  );

  if (loading) return <Spinner label="Loading…" />;

  if (authEnabled && user === null) {
    return (
      <Login
        onSignedIn={(signedIn) => {
          setUser(signedIn);
        }}
        signIn={apiLogin}
      />
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
