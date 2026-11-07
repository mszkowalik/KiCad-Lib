/** The clicks of a batch, past the newest page the craft view holds.
 *
 *  The craft view carries the newest 200 clicks and how many the batch has
 *  (`clicks_total`). Batch 8 has thousands, because programming and marking are
 *  one click per device. The list used to stop at 200 and print that as the
 *  count. Here the reader asks for older clicks, and `want` is how many. They are
 *  fetched again each time the view is, from the oldest click of the newest
 *  page, so a click recorded or undone since leaves no gap and no stale row.
 */
import { useEffect, useMemo, useState } from "react";
import { getCraftClicks, type CraftClick, type CraftView, type CraftWrites } from "../../api";
import { useLoad } from "../useLoad";

const NO_CLICKS: CraftClick[] = [];
/** The most one request asks for: the route's own limit. */
const MAX_PAGE = 10000;

export interface ClickList {
  /** newest first: the view's page, then the older clicks loaded */
  clicks: CraftClick[];
  writes: CraftWrites;
  /** how many clicks the batch has */
  total: number;
  loading: boolean;
  error: string | null;
  /** load `n` more older clicks */
  more: (n: number) => void;
  /** load every click */
  all: () => void;
}

export function useClicks(runId: number, view: CraftView | null): ClickList {
  const newest = view?.clicks ?? NO_CLICKS;
  const total = view?.clicks_total ?? newest.length;
  const oldest = newest.length ? newest[newest.length - 1].id : null;
  const room = Math.max(total - newest.length, 0);
  const [want, setWant] = useState(0);
  useEffect(() => setWant(0), [runId]);
  const n = Math.min(want, room, MAX_PAGE);
  const older = useLoad((signal) => getCraftClicks(runId, oldest ?? 0, n, signal), [runId, view, oldest, n],
    { enabled: n > 0 && oldest !== null, keep: true });
  const clicks = useMemo(() => {
    // Kept while a new answer loads: only what is older than the newest page.
    const rest = (older.data?.clicks ?? NO_CLICKS).filter((c) => oldest === null || c.id < oldest);
    return n > 0 && rest.length ? [...newest, ...rest] : newest;
  }, [newest, older.data, oldest, n]);
  const writes = useMemo(() => ({ ...(older.data?.writes ?? {}), ...(view?.writes ?? {}) }), [older.data, view]);
  return {
    clicks, writes, total,
    loading: n > 0 && older.loading,
    error: n > 0 ? older.error : null,
    more: (k) => setWant((w) => Math.min(w + k, room)),
    all: () => setWant(room),
  };
}
