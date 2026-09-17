/** Light, dark, or the operating system's answer — for the whole app.
 *
 *  **`data-theme` on `<html>` is always `light` or `dark`, never `system`.**
 *  The OS preference is resolved here rather than by a `prefers-color-scheme`
 *  media query in `styles.css`, because a person can now override it: keeping
 *  the query as well would mean writing the same 60 palette tokens twice, once
 *  per way of arriving at dark. So there is one dark rule,
 *  `:root[data-theme="dark"]`, and this module decides when it applies.
 *
 *  **Two stores, and each has a job.** The account row is the truth and follows
 *  the person to the next browser (`POST /api/account/theme`). `localStorage`
 *  is a CACHE of it, because the theme has to be on `<html>` before anything
 *  paints and `/api/auth/me` has not answered yet at that point — the snippet
 *  in `index.html` reads exactly this key, so do not rename it there alone.
 */
import { setOwnTheme } from "./api";

export type ThemePref = "system" | "light" | "dark";

export const THEME_PREFS: ThemePref[] = ["system", "light", "dark"];

/** Also read by the pre-paint snippet in `index.html`. */
const STORAGE_KEY = "ui-theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function isPref(value: unknown): value is ThemePref {
  return value === "system" || value === "light" || value === "dark";
}

/** The cached choice. Private browsing can make `localStorage` throw, and the
 *  OS answer is a fine thing to fall back to, so a failure is not an error. */
export function storedTheme(): ThemePref {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (isPref(raw)) return raw;
  } catch {
    /* no storage — follow the OS */
  }
  return "system";
}

function osPrefersDark(): boolean {
  return window.matchMedia(DARK_QUERY).matches;
}

/** Put the choice on `<html>`, resolving `system` against the OS. */
export function applyTheme(pref: ThemePref): void {
  const dark = pref === "dark" || (pref === "system" && osPrefersDark());
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

/** Apply a choice AND remember it for the next load's first paint.
 *  NOT named `use…`: it is called inside effects, and the hook lint rules
 *  would read that prefix as a conditional hook call. */
export function rememberTheme(pref: ThemePref): void {
  try {
    localStorage.setItem(STORAGE_KEY, pref);
  } catch {
    /* the choice still applies to this tab; only the next load flashes */
  }
  applyTheme(pref);
}

/** Save to the account, then apply. Call this from the UI control.
 *
 *  It applies FIRST and saves second: the click must feel instant, and a
 *  failed save leaves the tab showing a theme the account does not have —
 *  which is exactly what the error the caller re-throws is for.
 */
export async function saveTheme(pref: ThemePref, persist: boolean): Promise<void> {
  rememberTheme(pref);
  if (persist) await setOwnTheme(pref);
}

/** Called once at boot, before React renders.
 *
 *  Installs the OS listener too, so a laptop that flips to dark at sunset
 *  flips the app with it — but only while the choice is `system`.
 */
export function initTheme(): () => void {
  applyTheme(storedTheme());
  const mq = window.matchMedia(DARK_QUERY);
  const onChange = () => {
    if (storedTheme() === "system") applyTheme("system");
  };
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}
