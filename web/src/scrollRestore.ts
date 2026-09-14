import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * Put every scroll position back where it was, across a reload and across
 * back/forward.
 *
 * **The browser cannot do this here.** `history.scrollRestoration` restores the
 * WINDOW, and this app does not scroll the window: `.app` is `height: 100%` and
 * the scrollbar belongs to `.main` or `.main-solo` inside it. Even if it did,
 * the browser restores before React has fetched anything, so the page is still
 * one screen tall and the offset is clamped to 0.
 *
 * So positions are stored per URL and re-applied until they STICK — a frame
 * loop that keeps trying while the page is still growing, and gives up after
 * `SETTLE_MS` rather than fighting a page that will never be that tall again.
 *
 * **The scrollers are DISCOVERED, never listed.** Three pages, three different
 * ones: `.main` on browse, `.main-solo` on the review queue, `.detail-left` on
 * a component — and the component page scrolls two columns independently. A
 * hard-coded selector would silently stop working on the next page somebody
 * adds, so this walks the DOM for anything that actually has a scrollbar.
 */
const KEY = "scroll-positions";
const SETTLE_MS = 2500;

type Saved = Record<string, Record<string, number>>;

function read(): Saved {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || "{}") as Saved;
  } catch {
    return {};
  }
}

function write(all: Saved) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* a private window, or storage is full — losing a scroll offset is fine */
  }
}

/** Everything on the page that owns a scrollbar, in document order. */
function scrollers(): HTMLElement[] {
  const out: HTMLElement[] = [];
  document.querySelectorAll<HTMLElement>("div, main, section, aside, ul, ol").forEach((el) => {
    if (el.scrollHeight <= el.clientHeight + 4) return;
    const overflow = getComputedStyle(el).overflowY;
    if (overflow === "auto" || overflow === "scroll") out.push(el);
  });
  return out;
}

/** A stable name for one scroller. The class plus its position among the
 *  scrollers, because a two-column detail page has two that scroll and only
 *  their order tells them apart. A layout change makes the key miss, and a miss
 *  restores nothing — which is the safe way to be wrong. */
const nameOf = (el: HTMLElement, index: number) =>
  `${(el.className || el.tagName).toString().trim().split(/\s+/)[0]}#${index}`;

export default function useScrollRestore() {
  const { pathname, search } = useLocation();
  const key = pathname + search;

  useEffect(() => {
    // The window is not the scroller, so the browser's own restore only fights
    // ours on the rare page that does scroll it.
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";

    const wanted = read()[key] || {};

    let stop = false;
    const give_up = () => {
      stop = true;
    };
    // Any deliberate scroll ends the restore. Without this the loop fights the
    // user for up to SETTLE_MS, which feels like the page is stuck.
    window.addEventListener("wheel", give_up, { passive: true, once: true });
    window.addEventListener("touchstart", give_up, { passive: true, once: true });
    window.addEventListener("keydown", give_up, { once: true });

    const deadline = performance.now() + SETTLE_MS;
    const done = new Set<string>();
    const targets = Object.keys(wanted);
    const tick = () => {
      if (stop) return;
      scrollers().forEach((el, i) => {
        const name = nameOf(el, i);
        const want = wanted[name];
        if (!want || done.has(name)) return;
        el.scrollTop = want;
        if (Math.abs(el.scrollTop - want) <= 1) done.add(name);
      });
      const w = wanted.window;
      if (w && !done.has("window")) {
        window.scrollTo(0, w);
        if (Math.abs(window.scrollY - w) <= 1) done.add("window");
      }
      // KEEP TRYING WHILE ANY TARGET IS UNMET, not just while a scroller is
      // short of it. On mount the page is empty and `scrollers()` is EMPTY too,
      // so a loop that only looked at what exists decided it had nothing to do
      // and stopped on the first frame — the exact case this hook is for.
      const pending = targets.some((name) => !done.has(name));
      if (pending && performance.now() < deadline) requestAnimationFrame(tick);
      else stop = true;
    };
    requestAnimationFrame(tick);

    // Saved on the way out AND on a timer, because a reload fires no unmount.
    //
    // NEVER WHILE A RESTORE IS STILL RUNNING. `stop` is set when every target
    // has been met, when the deadline passes, or when the user scrolls — in
    // other words when the measurement means something. Before that the page is
    // half-built, every scroller reads 0, and the timer wrote that over the
    // position it was about to restore: the entry was saved correctly, then
    // deleted by its own first tick, and the reload landed at the top.
    const save = () => {
      if (!stop) return;
      const here: Record<string, number> = {};
      scrollers().forEach((el, i) => {
        if (el.scrollTop > 0) here[nameOf(el, i)] = el.scrollTop;
      });
      if (window.scrollY > 0) here.window = window.scrollY;
      const all = read();
      if (Object.keys(here).length) all[key] = here;
      else delete all[key];
      write(all);
    };
    const timer = window.setInterval(save, 400);
    window.addEventListener("beforeunload", save);
    window.addEventListener("pagehide", save);

    return () => {
      save();
      stop = true;
      window.clearInterval(timer);
      window.removeEventListener("beforeunload", save);
      window.removeEventListener("pagehide", save);
      window.removeEventListener("wheel", give_up);
      window.removeEventListener("touchstart", give_up);
      window.removeEventListener("keydown", give_up);
    };
  }, [key]);
}

/**
 * A fold's open state, remembered across a reload.
 *
 * Restoring the scroll offset alone puts a reader back at the same PIXEL, which
 * is the wrong place when the section they had expanded is closed again — the
 * content that was there is somewhere else entirely. Anything that opens on
 * click and changes the page height should remember it.
 */
export function readOpen(key: string): string | null {
  try {
    return sessionStorage.getItem(`open:${key}`);
  } catch {
    return null;
  }
}

export function writeOpen(key: string, value: string | null) {
  try {
    if (value === null) sessionStorage.removeItem(`open:${key}`);
    else sessionStorage.setItem(`open:${key}`, value);
  } catch {
    /* see `write` */
  }
}
