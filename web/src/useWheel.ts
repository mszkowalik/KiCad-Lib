/** Wheel zoom that does not also scroll the page.
 *
 *  React registers ONE `wheel` listener on the root container, and it is
 *  passive, so `preventDefault()` inside an `onWheel` prop is ignored: the
 *  drawing zooms and the window scrolls behind it, and a touchpad pinch zooms
 *  the whole browser. The only fix is a listener on the element itself, added
 *  with `{ passive: false }`.
 *
 *  Use the returned callback as the element's `ref`. It keeps the ref object
 *  you already have filled, so a component that measures its own box does not
 *  need a second ref. The handler decides whether to consume the event — call
 *  `preventDefault()` in it when you zoom, and return without calling it when
 *  the view is locked, so the page scrolls as usual.
 */
import { useCallback, useRef } from "react";

export function useWheel<T extends HTMLElement>(
  ref: React.MutableRefObject<T | null>,
  onWheel: (e: WheelEvent) => void,
): (node: T | null) => void {
  const latest = useRef(onWheel);
  latest.current = onWheel;
  const bound = useRef<T | null>(null);
  const handler = useRef((e: WheelEvent) => latest.current(e));

  return useCallback((node: T | null) => {
    if (bound.current) bound.current.removeEventListener("wheel", handler.current);
    bound.current = node;
    ref.current = node;
    if (node) node.addEventListener("wheel", handler.current, { passive: false });
  }, [ref]);
}
