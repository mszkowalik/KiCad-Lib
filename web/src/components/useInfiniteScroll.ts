import { useCallback, useEffect, useRef, useState } from "react";

/** "Load more when the reader gets near the end" — the one implementation.
 *
 *  Three lists want this and they want it for different reasons: the change
 *  feed pages from the server on a cursor, the device list pages on an offset,
 *  and every DataTable renders a slice of rows it already holds. What they
 *  share is the trigger, so only the trigger lives here.
 *
 *  It fires from a SENTINEL element placed after the last row, watched by an
 *  IntersectionObserver with a generous `rootMargin` — the point is to load
 *  before the reader arrives, not once they are staring at the bottom. A scroll
 *  handler would do the same job by asking the layout engine for offsets on
 *  every frame; the observer costs nothing until it fires.
 *
 *  `busy` matters as much as `hasMore`: without it the observer re-fires on
 *  every intersection change while a request is in flight and asks for the same
 *  page three or four times. */
export function useInfiniteScroll(
  onLoadMore: () => void,
  hasMore: boolean,
  busy: boolean,
  rootMargin = "400px",
) {
  const sentinel = useRef<HTMLDivElement | null>(null);
  // The callback is usually an inline arrow, so a new identity every render
  // would tear the observer down and rebuild it every render.
  const fire = useRef(onLoadMore);
  fire.current = onLoadMore;

  useEffect(() => {
    const node = sentinel.current;
    if (node === null || !hasMore || busy) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) fire.current();
      },
      { rootMargin },
    );
    obs.observe(node);
    return () => obs.disconnect();
  }, [hasMore, busy, rootMargin]);

  return sentinel;
}

/** The client-side half: how many of `total` rows to render right now.
 *
 *  Grows by `step` each time the sentinel is reached, and resets whenever
 *  `resetKey` changes — a new filter or a new sort is a new list, and keeping
 *  the old count would leave the reader scrolled into rows that no longer mean
 *  anything. The reset happens during render, not in an effect, because an
 *  effect would paint one frame of the old count against the new list. */
export function useVisibleCount(total: number, step: number, resetKey: unknown) {
  const [count, setCount] = useState(step);
  const seen = useRef(resetKey);
  if (seen.current !== resetKey) {
    seen.current = resetKey;
    if (count !== step) setCount(step);
  }
  const more = useCallback(() => setCount((n) => n + step), [step]);
  return { count: Math.min(count, total), hasMore: count < total, more };
}
