/** A numeric field that always prints a dot, and no spinner over the value.
 *
 *  `<input type="number">` is drawn by the BROWSER in the browser's locale, so
 *  on a Polish profile a dimension reads "0,2" while the value the API stores
 *  is 0.2 — one number in two spellings on one screen. The same control also
 *  floats a spinner over the last characters of a field as narrow as the field
 *  solver's, which hides the digit being typed.
 *
 *  A text field with `inputMode="decimal"` has neither problem. It still takes
 *  a comma, because a Polish keyboard types one, and Up/Down still step by
 *  `step`, because that is the part of the spinner worth keeping.
 */
import { useEffect, useRef, useState } from "react";

export interface Props {
  /** `null` shows an empty field, for a setting that may be left unset. */
  value: number | null;
  onChange: (v: number) => void;
  /** Called when the field is cleared, if the owner accepts "no value". Without
   *  it, an empty field simply waits for the next digit. */
  onEmpty?: () => void;
  step?: number;
  min?: number;
  max?: number;
  className?: string;
  disabled?: boolean;
  id?: string;
  title?: string;
  placeholder?: string;
}

/** Decimals to keep after a step, so 0.15 + 0.05 is 0.2 and not 0.2000000004. */
function places(step: number): number {
  const s = String(step);
  const dot = s.indexOf(".");
  return dot < 0 ? 0 : s.length - dot - 1;
}

export default function NumberInput({
  value,
  onChange,
  onEmpty,
  step = 1,
  min,
  max,
  className,
  disabled,
  id,
  title,
  placeholder,
}: Props) {
  const [text, setText] = useState(() => (value == null ? "" : String(value)));
  const shown = useRef(text);
  shown.current = text;

  // Follow the value when the OWNER changes it — a preset, a solved geometry,
  // a switch to another profile. Typing does not run this, so a half-typed
  // "0." is never rewritten under the caret.
  useEffect(() => {
    if (value == null) {
      if (shown.current !== "") setText("");
    } else if (Number(shown.current.replace(",", ".")) !== value) {
      setText(String(value));
    }
  }, [value]);

  const clamp = (v: number): number => {
    let out = v;
    if (min != null && out < min) out = min;
    if (max != null && out > max) out = max;
    return out;
  };

  const commit = (raw: string) => {
    setText(raw);
    if (raw.trim() === "") {
      onEmpty?.();
      return;
    }
    const v = Number(raw.replace(",", "."));
    if (Number.isFinite(v)) onChange(clamp(v));
  };

  const bump = (dir: number) => {
    const from = Number(text.replace(",", ".")) || 0;
    const next = clamp(Number((from + dir * step).toFixed(places(step))));
    setText(String(next));
    onChange(next);
  };

  return (
    <input
      className={className}
      type="text"
      inputMode="decimal"
      id={id}
      title={title}
      placeholder={placeholder}
      disabled={disabled}
      value={text}
      onChange={(e) => commit(e.target.value)}
      onBlur={() => {
        if (text.trim() === "" && onEmpty) return;
        const v = Number(text.replace(",", "."));
        const ok = text.trim() !== "" && Number.isFinite(v);
        setText(ok ? String(clamp(v)) : value == null ? "" : String(value));
      }}
      onKeyDown={(e) => {
        if (e.key === "ArrowUp" || e.key === "ArrowDown") {
          e.preventDefault();
          bump(e.key === "ArrowUp" ? 1 : -1);
        }
      }}
    />
  );
}
