import { useState, type CSSProperties, type ReactNode } from "react";

/**
 * An ⓘ marker that shows its text the moment the pointer is over it.
 *
 * Use this instead of a `title` attribute wherever the text is worth reading.
 * A `title` waits about a second, gives no sign it exists, and renders as the
 * browser's own grey box with no line breaks — so a check's hint, which is
 * several sentences and the only explanation of what the check means, was
 * effectively invisible on the review card (user request 2026-09-14).
 *
 * The tip is `position: fixed` and placed from the marker's box by JS, for the
 * reason `SiInput` already documents: an absolutely positioned popup is clipped
 * by whatever is around it, and a 300 px tip anchored to a narrow column runs
 * off the edge of the window. **Nothing in its ancestry may carry a
 * `transform`** — a transformed ancestor makes `fixed` resolve against IT
 * rather than the viewport, which silently breaks every placement.
 *
 * `SiInput` keeps its own copy of this marker because that one is absolutely
 * positioned INSIDE the input box and shares itself with the rounding notice.
 * The tip styling (`.si-tip`) is the same in both.
 */
export default function InfoTip({
  children,
  label = "More about this",
  className,
}: {
  children: ReactNode;
  /** Read out by a screen reader, and the fallback `title`. */
  label?: string;
  className?: string;
}) {
  const [tip, setTip] = useState<CSSProperties | null>(null);
  const place = (el: HTMLElement | null) => {
    if (!el) return setTip(null);
    const r = el.getBoundingClientRect();
    const W = 300;
    const GAP = 6;
    const EDGE = 8;
    const left = Math.min(Math.max(EDGE, r.left - 8), window.innerWidth - W - EDGE);
    const below = window.innerHeight - r.bottom - GAP - EDGE;
    const above = r.top - GAP - EDGE;
    // Opens on the side with more room, and is never taller than that room.
    //
    // A hint long enough to be worth reading is long enough to run off the
    // window: `fp.shared_land_record` is 2,265 characters, about 45 lines in a
    // 300 px column. The old rule asked whether 160 px fitted below, which is
    // true for almost every marker on the page, so the tall ones opened
    // downwards and lost their last two thirds off the bottom edge with no
    // scrollbar to get them back (user report 2026-09-14). `max-height` plus
    // `overflow-y: auto` in `.si-tip` makes the overflow scrollable, and the
    // tip is a CHILD of the marker, so the pointer moving onto it to scroll
    // never leaves the element that keeps it open.
    const flip = above > below;
    setTip({
      left,
      maxHeight: Math.max(120, flip ? above : below),
      ...(flip ? { bottom: window.innerHeight - r.top + GAP } : { top: r.bottom + GAP }),
    });
  };
  return (
    <span
      className={`info-tip${className ? ` ${className}` : ""}`}
      tabIndex={0}
      role="note"
      aria-label={label}
      onMouseEnter={(e) => place(e.currentTarget)}
      onMouseLeave={() => setTip(null)}
      onFocus={(e) => place(e.currentTarget)}
      onBlur={() => setTip(null)}
    >
      ⓘ
      <span className={`si-tip${tip ? " on" : ""}`} style={tip ?? undefined}>
        {children}
      </span>
    </span>
  );
}
