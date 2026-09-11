/** The three things every modal in the platform does, in one place.
 *
 *  1. **The page behind it does not scroll.** A wheel over a modal used to scroll the
 *     page under it, so closing the dialog left the reader somewhere else entirely.
 *  2. **A click outside closes it.**
 *  3. **Escape closes it.**
 *
 *  Escape is bound on `document`, NOT on the backdrop's `onKeyDown`. A key handler on
 *  an element only fires when focus is inside it, and focus sits on `document.body`
 *  until something in the dialog takes it — so a backdrop-bound Escape silently does
 *  nothing on any dialog that does not focus itself first. That was already a known
 *  trap here (see `RecheckDialog` in web/CLAUDE.md); binding it once on the document
 *  removes the trap rather than making every new dialog remember it.
 *
 *  Both effects are STACK-AWARE, because modals nest (a confirm over an editor):
 *  Escape only reaches the top one, and the scroll lock lifts when the last one goes,
 *  not the first.
 */
import { useEffect, type MouseEvent as ReactMouseEvent } from "react";

// ------------------------------------------------------------- scroll lock
let locks = 0;
let restore: { overflow: string; paddingRight: string } | null = null;

function lockScroll() {
  locks += 1;
  if (locks > 1) return;
  const body = document.body;
  restore = { overflow: body.style.overflow, paddingRight: body.style.paddingRight };
  // Hiding the scrollbar makes the page wider by its width; pad by the same amount or
  // everything behind the modal jumps sideways as it opens.
  const bar = window.innerWidth - document.documentElement.clientWidth;
  body.style.overflow = "hidden";
  if (bar > 0) body.style.paddingRight = `${bar}px`;
}

function unlockScroll() {
  locks = Math.max(0, locks - 1);
  if (locks || !restore) return;
  document.body.style.overflow = restore.overflow;
  document.body.style.paddingRight = restore.paddingRight;
  restore = null;
}

// ----------------------------------------------------------------- escape
const stack: (() => void)[] = [];
let bound = false;

function onKeyDown(e: KeyboardEvent) {
  if (e.key !== "Escape" || !stack.length) return;
  // A native <dialog>, a <select> being navigated, or an IME composition all take
  // Escape for themselves; only act when nobody else has.
  if (e.defaultPrevented) return;
  e.stopPropagation();
  stack[stack.length - 1]();
}

export interface ModalOptions {
  /** Escape and a click outside close it. Pass false for one the user must answer. */
  dismissable?: boolean;
  /** Whether the modal is on screen. Several modals here are rendered inside a `&&`,
   *  and a hook cannot be called inside one — so the hook is called unconditionally at
   *  the top of the component and told whether it is open. */
  active?: boolean;
}

export interface ModalProps {
  /** Spread onto the backdrop element. */
  backdropProps: { onMouseDown: (e: ReactMouseEvent) => void };
  /** Spread onto the card, so a click inside never reaches the backdrop. */
  cardProps: { onMouseDown: (e: ReactMouseEvent) => void };
}

/** Wire a modal up. `onClose` of null means it cannot be dismissed — it still locks
 *  the page behind it. */
export function useModal(onClose: (() => void) | null, opts: ModalOptions = {}): ModalProps {
  const active = opts.active !== false;
  const dismissable = active && opts.dismissable !== false && !!onClose;

  useEffect(() => {
    if (!active) return;
    lockScroll();
    return unlockScroll;
  }, [active]);

  useEffect(() => {
    if (!dismissable || !onClose) return;
    const entry = () => onClose();
    stack.push(entry);
    if (!bound) {
      document.addEventListener("keydown", onKeyDown, true);
      bound = true;
    }
    return () => {
      const i = stack.lastIndexOf(entry);
      if (i >= 0) stack.splice(i, 1);
      if (!stack.length && bound) {
        document.removeEventListener("keydown", onKeyDown, true);
        bound = false;
      }
    };
  }, [dismissable, onClose]);

  return {
    backdropProps: {
      // mousedown, not click: a click whose press started INSIDE the card and whose
      // release landed outside — the end of a text selection, a dragged slider — is
      // not "clicking outside", and closing on it loses work mid-gesture.
      onMouseDown: (e: ReactMouseEvent) => {
        if (dismissable && e.target === e.currentTarget) onClose!();
      },
    },
    cardProps: { onMouseDown: (e: ReactMouseEvent) => e.stopPropagation() },
  };
}
