/** The files a bench fetches for every unit, kept in the browser.
 *
 *  Run 8994 (2026-10-24) spent 2.5 s of every unit fetching the same 2.46 MB
 *  factory image from the platform. A firmware image never changes under its
 *  asset id and a file set is an immutable manifest (decision 0029), so both
 *  are safe to keep: the firmware by its SHA-256, which the run spec carries
 *  and which is checked again on every fetch, and an artwork file by its set
 *  and name.
 *
 *  Two layers. A Map for this tab, because four stations ask for the same
 *  image within seconds of each other; and Cache Storage, which outlives a
 *  reload and a deploy. Cache Storage needs a secure context (the deployed
 *  https page, or localhost) and is skipped quietly where it is missing or
 *  refused — the fetch still works, it is only slower.
 *
 *  The bench agent keeps its own copy of each image as well (decision 0099),
 *  so with a current agent the bytes cross loopback once per machine. This
 *  cache is what the page sends it from, and what an older agent gets every
 *  time.
 */
import { API_URL } from "../api";

const CACHE_NAME = "7sigma-bench-files-v1";
/** Bytes kept in this tab. Two or three images and a few drawings. */
const MEMORY_LIMIT = 16 * 1024 * 1024;

const memory = new Map<string, Uint8Array>();
/** One fetch per key at a time: four stations starting together share it. */
const inFlight = new Map<string, Promise<Uint8Array>>();

function remember(key: string, bytes: Uint8Array) {
  memory.delete(key);
  memory.set(key, bytes);
  let total = 0;
  for (const v of memory.values()) total += v.length;
  for (const k of memory.keys()) {
    if (total <= MEMORY_LIMIT) break;
    total -= memory.get(k)?.length ?? 0;
    memory.delete(k);
  }
}

async function openCache(): Promise<Cache | null> {
  try {
    return typeof caches === "undefined" ? null : await caches.open(CACHE_NAME);
  } catch {
    return null; // private window, blocked storage, plain http
  }
}

/** The cache key is a URL Cache Storage accepts, not the address fetched. */
const keyUrl = (key: string) => `https://bench-cache.invalid/${encodeURIComponent(key)}`;

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as Uint8Array<ArrayBuffer>);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function cached(
  key: string,
  url: string,
  check: (bytes: Uint8Array) => Promise<void>,
): Promise<Uint8Array> {
  const hit = memory.get(key);
  if (hit) return hit;
  const running = inFlight.get(key);
  if (running) return running;
  const work = (async () => {
    const store = await openCache();
    const stored = await store?.match(keyUrl(key)).catch(() => undefined);
    if (stored) {
      const bytes = new Uint8Array(await stored.arrayBuffer());
      try {
        await check(bytes);
        remember(key, bytes);
        return bytes;
      } catch {
        await store?.delete(keyUrl(key)).catch(() => false); // damaged: fetch again
      }
    }
    // The same credentials the station always fetched with (same-origin).
    const res = await fetch(url);
    if (!res.ok) throw new Error(`could not fetch ${url}: HTTP ${res.status}`);
    const bytes = new Uint8Array(await res.arrayBuffer());
    await check(bytes);
    remember(key, bytes);
    await store?.put(keyUrl(key), new Response(bytes)).catch(() => undefined);
    return bytes;
  })();
  inFlight.set(key, work);
  try {
    return await work;
  } finally {
    inFlight.delete(key);
  }
}

/** A firmware image's bytes, checked against the size and SHA-256 the
 *  platform stored. */
export async function firmwareBytes(img: {
  url: string;
  filename: string;
  sha256: string;
  size: number;
}): Promise<Uint8Array> {
  const key = img.sha256 ? `fw:${img.sha256.toLowerCase()}` : `url:${img.url}`;
  return cached(key, `${API_URL}${img.url}`, async (bytes) => {
    if (bytes.length !== img.size)
      throw new Error(`${img.filename}: got ${bytes.length} B, platform stored ${img.size} B`);
    if (img.sha256 && (await sha256Hex(bytes)) !== img.sha256.toLowerCase())
      throw new Error(`${img.filename}: the bytes do not match the platform's SHA-256`);
  });
}

/** One file of a file set — a drawing the marking bench patches. */
export async function setFileText(setId: number, filename: string, base = API_URL): Promise<string> {
  const bytes = await cached(
    `set:${setId}/${filename}`,
    `${base}/api/flasher/files/${setId}/${encodeURIComponent(filename)}`,
    async () => {},
  );
  return new TextDecoder().decode(bytes);
}
