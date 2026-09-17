/** Shared bits for the flasher admin panels. */

export function fmtBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(2)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} kB`;
  return `${n} B`;
}

export function shortSha(sha: string): string {
  return sha ? sha.slice(0, 10) : "—";
}

export function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 16).replace("T", " ");
}

export function fmtDuration(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  // A whole run is minutes long. "204.3 s" spends four characters on a
  // precision nobody reads and still has to be squeezed into a table column.
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/** The PNG a LightBurn project embeds as its own preview, as a data URL — or
 *  null when the text is not an .lbrn2 or carries none. The file is XML and
 *  the thumbnail sits in one attribute near the top, so a regex is enough and
 *  a parser would be a second thing to keep in step with LightBurn. */
export function lbrnThumbnail(text: string): string | null {
  const m = /<Thumbnail\s+Source="([A-Za-z0-9+/=\s]+)"/.exec(text);
  return m ? `data:image/png;base64,${m[1].replace(/\s+/g, "")}` : null;
}
