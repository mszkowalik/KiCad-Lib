/** The path prefix this app is served under, e.g. "" at the root or "/lib".
 *
 * Injected at CONTAINER START, not build time: nginx substitutes __APP_BASE__
 * in index.html (see web/40-app-base.sh), so one image serves at any prefix.
 * Baking it in with Vite's `base` would tie the image to a single mount point,
 * the same trap that VITE_API_URL sets — see the API_URL note in api.ts.
 *
 * Never ends with a slash, so `${APP_BASE}/api/x` is always well formed.
 * The dev server resolves the placeholder to "" (vite.config.ts).
 */
declare global {
  interface Window {
    __APP_BASE__?: string;
  }
}

function read(): string {
  if (typeof window === "undefined") return "";
  const raw = window.__APP_BASE__ ?? "";
  // An unsubstituted placeholder means the page is served raw, outside the
  // container — treat it as the root rather than a literal path segment.
  if (raw === "" || raw.includes("__APP_BASE__")) return "";
  return raw.endsWith("/") ? raw.slice(0, -1) : raw;
}

export const APP_BASE: string = read();

/** Prefix an app-internal absolute path with the base.
 *
 * Needed for plain <a href> targets. React Router's <Link> applies the
 * router basename itself, and `<base href>` only governs RELATIVE urls, so a
 * hand-built "/view?..." would escape the prefix and 404 under /lib.
 */
export function appHref(path: string): string {
  return `${APP_BASE}${path}`;
}
