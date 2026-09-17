/** A textarea that is exactly as tall as what is in it.
 *
 *  A fixed `rows` is a guess about content nobody has written yet, and it is
 *  wrong in both directions: two rows hid the second half of a deployment's
 *  description behind an inner scrollbar with no sign it was there (bench,
 *  2026-09-17), and the same two rows are one too many for a field holding a
 *  single word. A scrollbar inside a form control is the worst of the options,
 *  because the page around it already scrolls and nothing tells the reader
 *  which one holds the rest of the sentence.
 *
 *  `rows` still sets the FLOOR, so an empty box keeps a sensible shape, and
 *  `maxRows` sets the ceiling past which the inner scrollbar is the lesser
 *  evil. Height is measured, not calculated from a line count: the box may be
 *  any width and the text wraps.
 */
import { useCallback, useLayoutEffect, useRef, type TextareaHTMLAttributes } from "react";

export interface AutoTextareaProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "rows"> {
  /** Smallest height, in rows. Default 2. */
  rows?: number;
  /** Largest height before the box scrolls. Default 14. */
  maxRows?: number;
}

export default function AutoTextarea({
  rows = 2,
  maxRows = 14,
  value,
  className = "",
  ...rest
}: AutoTextareaProps) {
  const ref = useRef<HTMLTextAreaElement | null>(null);

  const fit = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    // Collapse first: scrollHeight never shrinks below the height already set,
    // so measuring without this makes the box grow and never come back.
    el.style.height = "auto";
    const cs = getComputedStyle(el);
    const line = parseFloat(cs.lineHeight) || 18;
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    // scrollHeight counts padding but NOT the border, while `height` on a
    // border-box control does — so without this the box lands exactly two
    // pixels short and scrolls one last time.
    const border = cs.boxSizing === "border-box"
      ? parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth)
      : 0;
    const min = rows * line + pad + border;
    const max = maxRows * line + pad + border;
    const content = el.scrollHeight + border;
    const want = Math.min(Math.max(content, min), max);
    el.style.height = `${Math.ceil(want)}px`;
    el.style.overflowY = content > max ? "auto" : "hidden";
  }, [rows, maxRows]);

  // Layout effect, not effect: the box must be the right height in the frame
  // it first paints, or the card visibly jumps on every open.
  useLayoutEffect(fit, [fit, value]);

  // The width can change without the value changing — a wrapped line then
  // needs a different height — and ResizeObserver is the only thing that says
  // so for a flex child that nothing re-rendered.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  return (
    <textarea
      ref={ref}
      className={`text auto-grow ${className}`.trim()}
      value={value}
      {...rest}
    />
  );
}
