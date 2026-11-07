/** The words a barcode scanner's CSV export puts around the payloads.
 *  Dropping them is safe because none of them can be a device serial; every
 *  other token is offered to the server, which is the only thing that knows
 *  what a serial is. */
const SCAN_NOISE = new Set([
  "timestamp", "type", "content", "favorite", "true", "false",
  "code128", "code39", "code93", "codabar", "ean13", "ean8", "upc_a", "upc_e",
  "qr_code", "qrcode", "data_matrix", "pdf417", "itf", "aztec",
]);

/** Serial-looking tokens in a paste, in the order they were scanned.
 *
 *  Takes a plain list, one per line, AND the CSV a scanner exports — nobody
 *  should have to strip quotes and timestamps by hand to use their own scan
 *  sheet. It deliberately does NOT try to decide what a serial looks like:
 *  a payload that is not a device comes back named by the server, which is
 *  the honest place for that answer. The two EAN barcodes in the 2026-09-17
 *  sheet arrived exactly that way. */
export function parseScanSheet(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of text.split(/[\s,;"']+/)) {
    const tok = raw.trim();
    if (!tok) continue;
    if (SCAN_NOISE.has(tok.toLowerCase())) continue;
    if (tok.includes(":") || tok.includes("-")) continue; // ISO timestamps, MACs with separators
    if (seen.has(tok)) continue;
    seen.add(tok);
    out.push(tok);
  }
  return out;
}
