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
import { useEffect, useRef, useState, type ReactNode } from "react";
import { formatSi, parseSi, unitsOf, type Quantity } from "./si";

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
  const print = (v: number | null) => formatSi(v, quantity, fixedUnit);
  const [text, setText] = useState(() => print(value));
  const [bad, setBad] = useState("");
  const typing = useRef(false);

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
      setBad(raw.trim() ? `Not a number this field can read. Units: ${unitsOf(quantity)}.` : "");
      return;
    }
    setBad(check(v));
    onChange(v);
  };

  return (
    <span className={`si-wrap${bad ? " si-bad" : ""}`}>
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
      {help || bad ? (
        <span className="si-help" tabIndex={0} role="note" aria-label={bad || undefined}>
          {bad ? "!" : "ⓘ"}
          <span className="si-tip">
            {bad ? <b className="si-tip-bad">{bad}</b> : null}
            {help}
          </span>
        </span>
      ) : null}
    </span>
  );
}
