/** The signed-in user's light/dark choice, on the Account page.
 *
 *  It writes the ACCOUNT, not the browser: the same person gets the same
 *  platform on the bench machine and on their laptop. `theme.ts` explains the
 *  browser cache that sits in front of that, and why it is a cache rather than
 *  a second setting.
 *
 *  The click applies instantly and the save follows, so a slow network never
 *  makes the buttons feel stuck. If the save fails, the tab is already showing
 *  a theme the account does not have — which is what the banner has to say.
 */
import { useState } from "react";

import { errorMessage } from "../api";
import { useAuth } from "../auth";
import { THEME_PREFS, type ThemePref } from "../theme";
import { ErrorBanner } from "./Ui";

const LABELS: Record<ThemePref, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

export default function AppearanceCard() {
  const { theme, setTheme, authEnabled } = useAuth();
  const [error, setError] = useState<string | null>(null);

  const choose = async (pref: ThemePref) => {
    setError(null);
    try {
      await setTheme(pref);
    } catch (err) {
      setError(
        `${errorMessage(err)} — this tab is showing ${LABELS[pref].toLowerCase()}, ` +
          "but the account was not changed.",
      );
    }
  };

  return (
    <div className="card pad">
      <h2 className="card-title">Appearance</h2>
      {error ? <ErrorBanner message={error} /> : null}
      {/* `.seg` is a block-level flex box, so on its own in a card it stretches
          to the full width. `.btn-row` makes it a flex ITEM instead, which is
          how every toolbar already holds one — no new class for this. */}
      <div className="btn-row">
        <div className="seg" role="group" aria-label="Theme">
          {THEME_PREFS.map((pref) => (
            <button
              key={pref}
              type="button"
              className={theme === pref ? "on" : ""}
              aria-pressed={theme === pref}
              onClick={() => void choose(pref)}
            >
              {LABELS[pref]}
            </button>
          ))}
        </div>
      </div>
      <p className="muted">
        {authEnabled
          ? "System follows the operating system, and changes with it. The choice is stored on your account, so it follows you to another browser."
          : "Authentication is off on this deployment, so there is no account to store this on — the choice applies to this browser only."}
      </p>
    </div>
  );
}
