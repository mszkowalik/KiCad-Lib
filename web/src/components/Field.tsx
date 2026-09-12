/** The ONE way a control is labelled in this app.
 *
 *  Before it, every page invented its own label-and-group wrapper — `edit-grid`,
 *  `user-form`, `cred-form`, `fs-field` — so the same kind of form rendered at a
 *  different label size, gap and margin depending on which page you opened it
 *  from. The field solver's was the one that had been thought about, so its
 *  shape is what these promote: a 12px muted label stacked over the control, a
 *  3px gap, groups under a legend.
 *
 *  **It wraps the control, it does not replace it.** `<Field>` takes any child —
 *  `<input className="text">`, `<select className="text">`, `SiInput`,
 *  `NumberInput`, a checkbox — so a special control keeps its own behaviour and
 *  only its FRAME is shared. That is deliberate: putting a unit parser behind a
 *  project-name field to make the boxes match would be a worse kind of
 *  uniformity.
 *
 *  **The two input sizes stay.** `.text` is the standard field; `.row-input` is
 *  the compact one for table rows, filter bars and toolbars, where a full-height
 *  input would break the one-line-per-row rule every table in the platform
 *  follows. Pass `compact` to size a Field's own control the second way.
 */
import type { ReactNode } from "react";

export interface FieldProps {
  /** The label. Omit for a control that is already labelled by its context. */
  label?: ReactNode;
  /** Shown under the control, muted. Say what a good value looks like. */
  hint?: ReactNode;
  /** Shown under the control in the error colour, and outlines the control.
   *  An empty string is "no error", so a validator can return one freely. */
  error?: string;
  /** Take the whole width of a `<FieldRow>` — for a note, a URL, a token. */
  wide?: boolean;
  className?: string;
  children: ReactNode;
}

export default function Field({
  label,
  hint,
  error,
  wide = false,
  className = "",
  children,
}: FieldProps) {
  const cls = ["field", wide ? "field-wide" : "", error ? "bad" : "", className]
    .filter(Boolean)
    .join(" ");
  return (
    <label className={cls}>
      {label !== undefined ? <span>{label}</span> : null}
      {children}
      {error ? <span className="field-error">{error}</span> : null}
      {hint !== undefined && !error ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

/** Several fields side by side, wrapping when the card is narrow. */
export function FieldRow({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`field-row ${className}`.trim()}>{children}</div>;
}

/** A named group of fields. `legend` is the group's name, printed like a
 *  column header so it reads as structure rather than as another label. */
export function FieldSet({
  legend,
  children,
  className = "",
}: {
  legend: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <fieldset className={`fieldset ${className}`.trim()}>
      <legend>{legend}</legend>
      {children}
    </fieldset>
  );
}

/** A checkbox with its label beside it rather than above it — the one control
 *  where the label reads as part of the thing being ticked. */
export function CheckField({
  checked,
  onChange,
  disabled = false,
  children,
  title,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  children: ReactNode;
  title?: string;
}) {
  return (
    <label className="field-check" title={title}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>{children}</span>
    </label>
  );
}
