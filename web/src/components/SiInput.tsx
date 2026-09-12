/** A number that carries a unit: type "35um", "0.035" or "1.4mil" into the same box.
 *
 *  Built on the same reasoning as `NumberInput` — a text field rather than
 *  `<input type="number">`, because the browser draws that one in the browser's
 *  locale and floats a spinner over the last characters of a narrow field. This one
 *  adds the unit: the value is held in one base unit (mm, Hz) and typed in whatever
 *  prefix the figure arrived in.
 *
 *  Typing never rewrites the text under the caret. The field re-prints itself from
 *  the value when the OWNER changes it and when focus leaves, which is what turns
 *  "35um" into "35 um" and a pasted "0.000035m" into something readable.
 */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { formatSiParts, parseSi, unitsOf, type Quantity } from "./si";

export interface SiInputProps {
  value: number | null;
  onChange: (v: number) => void;
  /** Called when the box is cleared, if the owner accepts "no value". */
  onEmpty?: () => void;
  quantity?: Quantity;
  /** Unit a bare number is taken to be. Defaults to the base unit (mm, Hz). */
  assume?: string;
  /** Always print in this unit instead of the one that suits the magnitude. */
  fixedUnit?: string;
  min?: number;
  max?: number;
  /** Return a message to mark the box bad, or "" when the value is acceptable. */
  validate?: (v: number) => string;
  /** Text behind a ⓘ marker to the right of the box. */
  help?: ReactNode;
  className?: string;
  disabled?: boolean;
  placeholder?: string;
  title?: string;
  "aria-label"?: string;
}

export default function SiInput({
  value,
  onChange,
  onEmpty,
  quantity = "length",
  assume,
  fixedUnit,
  min,
  max,
  validate,
  help,
  className,
  disabled,
  placeholder,
  title,
  "aria-label": ariaLabel,
}: SiInputProps) {
  /* No memory of the unit the user typed, on purpose. The ladder already
     answers "10m" with "10 mΩ", because mΩ IS the prefix that puts 10 before
     the decimal point — so remembering the spelling buys nothing and costs a
     great deal: a box pinned to mΩ printed 1 000 000 Ω as "1000000000 mΩ", ten
     digits wide, which is the very thing the three-digit rule exists to stop.
     `fixedUnit` still pins a field whose caller says it has one unit. */
  const parts = (v: number | null) => formatSiParts(v, quantity, fixedUnit);
  const print = (v: number | null) => parts(v).text;
  const [text, setText] = useState(() => print(value));
  const [bad, setBad] = useState("");
  const typing = useRef(false);
  const shown = parts(value);

  /* The tip is `position: fixed` and placed from the marker's own box, for the
     reason `TemplateThumb` already documents: an absolutely positioned popup is
     clipped by whatever is around it, and this one sits in a 320 px panel where
     a 300 px tip anchored `right: 0` ran off the LEFT edge of the window —
     measured at x = -132 on every field in the solver. Clamped to the viewport
     on both axes, and flipped above the marker when there is no room below. */
  const [tip, setTip] = useState<CSSProperties | null>(null);
  const place = (el: HTMLElement | null) => {
    if (!el) return setTip(null);
    const r = el.getBoundingClientRect();
    const W = 300;
    const left = Math.min(Math.max(8, r.right - W), window.innerWidth - W - 8);
    const below = r.bottom + 6;
    const flip = below + 160 > window.innerHeight && r.top > 170;
    setTip({
      left,
      ...(flip ? { bottom: window.innerHeight - r.top + 6 } : { top: below }),
    });
  };

  // Follow the owner's value, but never while the user is mid-word: rewriting the
  // box under the caret is how "0.0" becomes impossible to type past.
  useEffect(() => {
    if (typing.current) return;
    setText(print(value));
    setBad("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, quantity, fixedUnit]);

  const check = (v: number): string => {
    if (min !== undefined && v < min) return `Must be at least ${print(min)}.`;
    if (max !== undefined && v > max) return `Must be at most ${print(max)}.`;
    return validate?.(v) ?? "";
  };

  const commit = (raw: string) => {
    const v = parseSi(raw, quantity, assume);
    if (v === null) {
      if (!raw.trim() && onEmpty) {
        onEmpty();
        setBad("");
        return;
      }
      setBad(
        raw.trim()
          ? `Not a number this field can read. Units: ${unitsOf(quantity)}. ` +
            "A prefix may stand in for the decimal point (4k7 = 4.7k)."
          : "",
      );
      return;
    }
    setBad(check(v));
    onChange(v);
  };

  return (
    /* The caller's class goes on the WRAP as well as the input. The marker is
       positioned against the wrap, so a width cap applied only to the input
       (`.fs-num` is max-width: 110px) left the wrap at its full 166 px and the
       ⓘ floating in the gap beside the box instead of inside it. */
    <span className={`si-wrap${bad ? " si-bad" : ""} ${className ?? ""}`.trimEnd()}>
      <input
        className={`text ${className ?? ""}`}
        type="text"
        inputMode="decimal"
        disabled={disabled}
        placeholder={placeholder}
        title={title}
        aria-label={ariaLabel}
        aria-invalid={bad ? true : undefined}
        value={text}
        onFocus={() => {
          typing.current = true;
        }}
        onChange={(e) => {
          setText(e.target.value);
          commit(e.target.value);
        }}
        onBlur={() => {
          typing.current = false;
          const v = parseSi(text, quantity, assume);
          if (v !== null) setText(print(v));
          else if (!text.trim() && !onEmpty) setText(print(value));
        }}
      />
      {/* ONE marker per field. Rounding shares the help marker rather than
          adding a second ⓘ beside it — two info markers on one box is a
          puzzle, not a hint (user decision 2026-09-12). */}
      {help || bad || shown.rounded ? (
        <span
          className={`si-help${shown.rounded && !bad ? " si-rounded" : ""}`}
          tabIndex={0}
          role="note"
          aria-label={bad || (shown.rounded ? `Rounded — exact value ${shown.exact}` : undefined)}
          onMouseEnter={(e) => place(e.currentTarget)}
          onMouseLeave={() => setTip(null)}
          onFocus={(e) => place(e.currentTarget)}
          onBlur={() => setTip(null)}
        >
          {bad ? "!" : "ⓘ"}
          <span className={`si-tip${tip ? " on" : ""}`} style={tip ?? undefined}>
            {bad ? <b className="si-tip-bad">{bad}</b> : null}
            {shown.rounded && !bad ? (
              <b className="si-tip-round">Rounded for display. Exact value: {shown.exact}</b>
            ) : null}
            {help}
          </span>
        </span>
      ) : null}
    </span>
  );
}
