/** The path prefix this app is served under, e.g. "" at the root or "/lib".
 *
 * Read back from the <base href> in index.html, which is stamped at CONTAINER
 * START (see web/40-app-base.sh) rather than build time — Vite inlines its
 * `base`, so baking the prefix in would tie one image to one mount point, the
 * same trap as VITE_API_URL (see api.ts).
 *
 * The <base> tag is the single source of truth on purpose. An earlier version
 * also emitted a `window.__APP_BASE__` global, and because the substitution is
 * a plain string replace, the placeholder inside that property name got
 * rewritten too — the inline script became `window./lib = "/lib"`, a syntax
 * error. The prefix then silently fell back to "", which stripped the router
 * basename and the API prefix at once. Read the tag; do not add a second copy.
 *
 * Never ends with a slash, so `${APP_BASE}/api/x` is always well formed.
 */
function read(): string {
  if (typeof document === "undefined") return "";
  // getAttribute, not .href: the property resolves to an absolute URL, and we
  // want the path as written ("/lib/").
  const href = document.querySelector("base")?.getAttribute("href") ?? "/";
  // An unsubstituted placeholder means the page is served outside the
  // container — treat it as the root rather than a literal path segment.
  if (href.includes("__APP_BASE__")) return "";
  const trimmed = href.endsWith("/") ? href.slice(0, -1) : href;
  return trimmed === "/" ? "" : trimmed;
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
