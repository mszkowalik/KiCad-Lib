import { useEffect, useState } from "react";

/** The value, once it has stayed the same for `ms`. A keystroke is not a query.
 *
 *  It compares CONTENT, because a table hands its filters over as a new object on
 *  every change. Typing a letter and deleting it again ends on the value already
 *  applied, so nothing changes and the caller does not fetch again. */
export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  const next = JSON.stringify(value);
  const current = JSON.stringify(settled);
  useEffect(() => {
    if (next === current) return;
    const t = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(t);
    // `next` stands for `value`: a new object with the same content changes nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [next, current, ms]);
  return settled;
}
