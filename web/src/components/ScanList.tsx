/** Scanning codes into a list: one way for the whole platform (decision 0103).
 *
 *  A barcode scanner is a keyboard: it types the code and presses Enter. So this
 *  is a plain text box, and it must keep working with nobody at the computer:
 *
 *  - **A wrong code never opens a dialog.** A dialog takes the focus, so the next
 *    scan only closes it, and that code is lost. It is a row and a sound.
 *  - **The box keeps the focus**, and a mark says whether the next scan lands.
 *  - **The server checks each code in the background.** The page's list is as old
 *    as the page, and scans do not wait for each other.
 *  - **One scan is taken as typed; only a PASTED list goes through
 *    `parseScanSheet`.** That parser drops every token with `:` or `-`, so a
 *    scanned `PROTO-0045` would vanish.
 *  - **The list survives a reload.** A half-scanned carton must, so it is in
 *    `localStorage`, not `useStickyState`, whose storage forbids drafts. Check
 *    results are never stored; they are asked again on load.
 */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";

import { errorMessage } from "../api";
import { playVerdict } from "../flasher/sound";
import { parseScanSheet } from "../scanSheet";
import AutoTextarea from "./AutoTextarea";
import Field from "./Field";

export type ScanState = "pending" | "checking" | "done" | "error";
export type ScanHow = "scanned" | "list";

export interface Scan<C> {
  code: string;
  state: ScanState;
  check?: C;
  error?: string;
  how: ScanHow;
}

export interface ScanNotice {
  tone: "" | "ok" | "warn" | "err";
  text: string;
}

export interface ScanListOptions<C> {
  /** where the list lives in `localStorage` */
  storageKey: string;
  check: (codes: string[]) => Promise<C[]>;
  /** the code a result answers */
  codeOf: (c: C) => string;
  /** a result that is not usable makes the error sound */
  isOk: (c: C) => boolean;
  /** the words for the line under the box */
  describe: (c: C) => ScanNotice;
  /** a code that is on another list of this page, and must not be added */
  taken?: (code: string) => boolean;
}

function readList<C>(key: string): Scan<C>[] {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const rows = JSON.parse(raw) as unknown;
    if (!Array.isArray(rows)) return [];
    return rows.flatMap((r): Scan<C>[] => {
      if (typeof r === "string") return [{ code: r, state: "pending", how: "scanned" }];
      if (r && typeof (r as { code?: unknown }).code === "string") {
        const x = r as { code: string; how?: ScanHow };
        return [{ code: x.code, state: "pending", how: x.how === "list" ? "list" : "scanned" }];
      }
      return [];
    });
  } catch {
    return [];
  }
}

export function useScanList<C>({ storageKey, check, codeOf, isOk, describe, taken }: ScanListOptions<C>) {
  const [scans, setScans] = useState<Scan<C>[]>(() => readList<C>(storageKey));
  const [notice, setNotice] = useState<ScanNotice | null>(null);
  const inflight = useRef(false);
  const current = useRef(scans);
  current.current = scans;
  // The latest options, for an effect that must not restart on each render.
  const opts = useRef({ check, codeOf, isOk, describe });
  opts.current = { check, codeOf, isOk, describe };
  /** The last code scanned by hand: its answer is what the line under the box says. */
  const lastScan = useRef<string | null>(null);

  useEffect(() => {
    try {
      if (scans.length) {
        window.localStorage.setItem(storageKey, JSON.stringify(scans.map((s) => ({ code: s.code, how: s.how }))));
      } else {
        window.localStorage.removeItem(storageKey);
      }
    } catch {
      /* a full or blocked store: the list still works until a reload */
    }
  }, [scans, storageKey]);

  // One request at a time, with every code that waits: a scanner is faster than
  // the server, and the codes that arrive meanwhile wait for the next round.
  useEffect(() => {
    if (inflight.current) return;
    const pending = scans.filter((s) => s.state === "pending").map((s) => s.code);
    if (!pending.length) return;
    inflight.current = true;
    const want = new Set(pending);
    setScans((ss) => ss.map((s) => (want.has(s.code) && s.state === "pending" ? { ...s, state: "checking" } : s)));
    opts.current.check(pending)
      .then((res) => {
        const { codeOf: code, isOk: ok, describe: say } = opts.current;
        const by = new Map(res.map((r) => [code(r), r]));
        setScans((ss) => ss.map((s) => (s.state === "checking" && by.has(s.code)
          ? { ...s, state: "done", check: by.get(s.code) } : s)));
        if (res.some((r) => !ok(r) && lastScan.current === code(r))) playVerdict("fail");
        const last = lastScan.current ? by.get(lastScan.current) : undefined;
        if (last) setNotice(say(last));
      })
      .catch((err) => {
        const msg = errorMessage(err);
        setScans((ss) => ss.map((s) => (s.state === "checking" && want.has(s.code)
          ? { ...s, state: "error", error: msg } : s)));
        setNotice({ tone: "err", text: msg });
      })
      .finally(() => {
        inflight.current = false;
        // Wake the effect for anything scanned meanwhile.
        setScans((ss) => [...ss]);
      });
  }, [scans]);

  /** Add codes. The updater checks against the list as it is NOW: two scans can
   *  land before this render's `scans` is replaced. */
  const add = useCallback((codes: string[], how: ScanHow) => {
    if (!codes.length) return;
    const shut = codes.filter((c) => taken?.(c));
    setScans((ss) => {
      const have = new Set(ss.map((s) => s.code));
      const fresh = codes.filter((c) => !have.has(c) && !taken?.(c));
      return fresh.length ? [...fresh.map((c) => ({ code: c, state: "pending" as ScanState, how })), ...ss] : ss;
    });
    if (shut.length) {
      setNotice({ tone: "warn", text: `${shut.length === 1 ? `${shut[0]} is` : `${shut.length} codes are`} already on a list. Not added again.` });
    }
  }, [taken]);

  /** One code from the scanner, taken as typed. */
  const scan = useCallback((raw: string) => {
    const code = raw.trim();
    if (!code) return;
    const have = current.current.find((s) => s.code === code);
    if (have) {
      lastScan.current = null;
      if (have.how === "list") {
        // Ticked before, seen now: a scan is an observation, a tick a statement.
        setScans((ss) => ss.map((s) => (s.code === code ? { ...s, how: "scanned" } : s)));
        setNotice({ tone: "ok", text: `${code} was ticked, and is now scanned.` });
      } else {
        setNotice({ tone: "warn", text: `${code} is already in the list. Not added again.` });
      }
      return;
    }
    if (!taken?.(code)) {
      lastScan.current = code;
      setNotice(null);
    }
    add([code], "scanned");
  }, [add, taken]);

  /** A pasted list: a scanner's CSV export. */
  const paste = useCallback((text: string) => add(parseScanSheet(text), "scanned"), [add]);

  const remove = useCallback((code: string) => setScans((ss) => ss.filter((s) => s.code !== code)), []);
  const removeWhere = useCallback((test: (s: Scan<C>) => boolean) => setScans((ss) => ss.filter((s) => !test(s))), []);
  const clear = useCallback(() => { setScans([]); setNotice(null); lastScan.current = null; }, []);
  /** Ask again: a step changed what each device can take. */
  const recheck = useCallback(() => setScans((ss) => ss.map((s) => ({ code: s.code, state: "pending", how: s.how }))), []);

  return { scans, notice, setNotice, add, scan, paste, remove, removeWhere, clear, recheck };
}

export interface ScanBoxHandle {
  focus: () => void;
}

/** The text box. It takes the focus when it opens, and the caller gives it back
 *  after anything that took it, with `ref.current.focus()`. */
export const ScanBox = forwardRef<ScanBoxHandle, {
  label: string;
  placeholder?: string;
  onScan: (code: string) => void;
  onPaste: (text: string) => void;
  notice?: ScanNotice | null;
  hint?: string;
  autoFocus?: boolean;
  children?: React.ReactNode;
}>(function ScanBox({ label, placeholder, onScan, onPaste, notice, hint, autoFocus = true, children }, ref) {
  const input = useRef<HTMLInputElement>(null);
  const [code, setCode] = useState("");
  const [focused, setFocused] = useState(false);
  useImperativeHandle(ref, () => ({ focus: () => input.current?.focus({ preventScroll: true }) }), []);
  useEffect(() => {
    if (autoFocus) input.current?.focus({ preventScroll: true });
  }, [autoFocus]);
  return (
    <>
      <div className="scan-row">
        <Field label={label} hint={hint}>
          <input
            ref={input}
            className="text mono"
            value={code}
            autoComplete="off"
            spellCheck={false}
            placeholder={placeholder ?? "scan, then Enter"}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onScan(code);
                setCode("");
              }
            }}
            onPaste={(e) => {
              const text = e.clipboardData.getData("text");
              if (/\s/.test(text.trim())) {
                e.preventDefault();
                onPaste(text);
              }
            }}
          />
        </Field>
        <span className={`scan-mark ${focused ? "on" : "off"}`}>{focused ? "● ready to scan" : "○ click the box to scan"}</span>
        {children}
      </div>
      {notice ? <div className={`scan-last ${notice.tone}`} role="status">{notice.text}</div> : null}
    </>
  );
});

/** Many codes in one box, for a job that takes them all at once: one per line, or
 *  a scanner's CSV pasted in. The caller reads the box with `parseScanSheet`, and
 *  the server names any code that is not a device. */
export function SerialsField({ value, onChange }: { value: string; onChange: (text: string) => void }) {
  return (
    <Field label="Serials" wide
      hint={`${parseScanSheet(value).length} serial(s) read. One per line, or paste a scanner's CSV. A word with a dash or a colon is dropped.`}>
      <AutoTextarea className="text mono" rows={4} value={value} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}
