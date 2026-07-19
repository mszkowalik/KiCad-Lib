import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

/**
 * A `useState` whose value is remembered across navigation and refresh for the
 * browser session (backed by `sessionStorage`). Use it so returning to a page
 * restores the user's last selections — filters, active tab, sort order,
 * segmented/toggle buttons, a selected library/snapshot, etc.
 *
 * Use ONLY for ephemeral UI selection state. Never store server data, secrets,
 * or in-progress form/edit drafts here.
 *
 * Keys are namespaced + versioned below. Give each call a stable, unique key.
 * Scope per-entity state by embedding an id in the key, e.g.
 * `useStickyState(`project:${projectId}:tab`, "BOM")` — when the id changes the
 * hook re-loads that entity's own remembered value.
 *
 * Session-scoped by design (cleared when the tab closes). Swap `sessionStorage`
 * for `localStorage` below if cross-session persistence is ever wanted.
 */
const store: Storage | null = typeof window !== "undefined" ? window.sessionStorage : null;
const NS = "kicadlib:v2:"; // bump the version if a stored value's shape changes

function read<T>(key: string, fallback: T): T {
  if (!store) return fallback;
  try {
    const raw = store.getItem(NS + key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function useStickyState<T>(
  key: string,
  initial: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => read(key, initial));

  // One effect: when the key changes (e.g. navigating between projects) re-load
  // that key's stored value; otherwise persist the current value. Guarding the
  // write behind a committed-key check avoids briefly writing the previous
  // entity's value under the new key.
  const committedKey = useRef(key);
  useEffect(() => {
    if (committedKey.current !== key) {
      committedKey.current = key;
      setValue(read(key, initial));
      return;
    }
    if (!store) return;
    try {
      store.setItem(NS + key, JSON.stringify(value));
    } catch {
      // storage full/unavailable — the value still works in memory this session
    }
    // `initial` intentionally omitted: it's only a fallback for a missing key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, value]);

  return [value, setValue];
}
