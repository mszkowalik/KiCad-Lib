/** What a part is, in the terms it is specified in.
 *
 *  A component is not one string. A voltage source is a waveform and a few
 *  numbers; a diode is five model parameters; an op-amp is however many its
 *  model declares. Typing `PULSE(0 5 0 1u 1u 1m 2m)` into one box asks the
 *  user to remember an order, and a box that only takes one number cannot
 *  describe a part that has six.
 *
 *  So: a form per shape the part can take, a row per number, and a slider on
 *  the ones a slider suits. The value written is still the SPICE value — the
 *  form fills the template in, and the raw form is always there for anything
 *  the fields cannot express.
 *
 *  A row that a running transient can follow says so by acting at once. One
 *  that cannot is marked, because ngspice accepts `alter` on a waveform and
 *  silently keeps the old script, and a knob that does nothing is worse than
 *  no knob.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  buildValue, format, fromSlider, readParams, readValue, toSlider, writeParams,
  type ParamField, type ParamForm,
} from "./params";

/** A text field that survives a busy page.
 *
 *  It is UNCONTROLLED, and that is the whole point. A controlled input has its
 *  DOM value rewritten from the prop on every render; a live run re-renders
 *  this page thirty times a second, and one of those rewrites lands between
 *  the keystroke and the change event — so the character appears in the field
 *  and is then silently taken back. Measured: with a live run going, typing a
 *  new resistance did nothing while the slider beside it worked.
 *
 *  So the field owns its text, and the outside value only reclaims it when it
 *  changes while the field is not focused.
 */
function ParamInput({
  value, disabled, onCommit,
}: { value: string; disabled?: boolean; onCommit: (next: string) => void }) {
  const ref = useRef<HTMLInputElement | null>(null);
  const focused = useRef(false);
  useEffect(() => {
    const node = ref.current;
    if (node && !focused.current && node.value !== value) node.value = value;
  }, [value]);
  return (
    <input
      ref={ref}
      className="text"
      defaultValue={value}
      disabled={disabled}
      onFocus={() => { focused.current = true; }}
      onBlur={(e) => { focused.current = false; onCommit(e.target.value); }}
      onInput={(e) => onCommit((e.target as HTMLInputElement).value)}
    />
  );
}


interface Props {
  title: string;
  forms: ParamForm[];
  /** The part's Value field, for the forms that build one. */
  value: string;
  /** Its `Sim.Params`, for the forms that set keys. */
  params: string;
  onValue?: (next: string) => void;
  onParams?: (next: string) => void;
  /** Steer a field on the RUNNING transient. Absent when nothing is running. */
  onLive?: (field: ParamField, value: string) => void;
  /** Rows this part cannot change at all — a catalogue part on a sheet the
   *  editor may not rewrite. */
  readOnly?: boolean;
  children?: React.ReactNode;
}

export default function ComponentInspector({
  title, forms, value, params, onValue, onParams, onLive, readOnly, children,
}: Props) {
  const valueForms = forms.filter((f) => f.target === "value");
  const paramForms = forms.filter((f) => f.target === "params");
  const read = useMemo(() => readValue(valueForms, value), [valueForms, value]);
  const [formId, setFormId] = useState<string | null>(null);
  /** What the user typed for a part that has no document to write to — a
   *  catalogue part on a sheet the editor may not rewrite. The RUN follows it
   *  through `onLive`; the file does not, and says so. */
  const [local, setLocal] = useState<Record<string, string>>({});
  const form = valueForms.find((f) => f.id === formId) ?? read?.form ?? null;
  const paramValues = useMemo(() => readParams(params), [params]);

  /** Answers for the chosen form: what the value says when it is written in
   *  that form, else the form's own defaults. */
  const answers = useMemo(() => {
    if (!form) return {};
    if (read && read.form.id === form.id) return read.values;
    return Object.fromEntries(form.fields.map((f) => [f.key, f.default]));
  }, [form, read]);

  const setAnswer = (field: ParamField, next: string) => {
    if (!form) return;
    setLocal((v) => ({ ...v, [field.key]: next }));
    if (onValue) onValue(buildValue(form, { ...answers, ...local, [field.key]: next }));
    if (field.live) onLive?.(field, next);
  };

  const setParam = (field: ParamField, next: string) => {
    setLocal((v) => ({ ...v, [field.key]: next }));
    if (onParams) onParams(writeParams({ ...paramValues, [field.key]: next }));
    if (field.live) onLive?.(field, next);
  };

  const row = (field: ParamField, current: string, set: (f: ParamField, v: string) => void) => (
    <div className="sim-param" key={field.key}>
      <label>
        <span>{field.label}</span>
        <ParamInput value={current} disabled={readOnly} onCommit={(v) => set(field, v)} />
        {field.unit ? <span className="muted sim-param-unit">{field.unit}</span> : null}
      </label>
      {field.scale === "text" ? null : (
        <input
          type="range"
          min={0}
          max={1}
          step={0.001}
          value={toSlider(field, current)}
          disabled={readOnly}
          onChange={(e) => set(field, fromSlider(field, Number(e.target.value)))}
          aria-label={field.label}
        />
      )}
      {onLive && !field.live ? (
        <span className="muted sim-param-note" title="ngspice keeps the old value until the run restarts">
          needs a re-run
        </span>
      ) : null}
    </div>
  );

  return (
    <div className="sim-inspector">
      <div className="sim-inspector-head">
        <h3>{title}</h3>
        {valueForms.length > 1 ? (
          <div className="seg" role="group" aria-label="Waveform">
            {valueForms.map((f) => (
              <button
                key={f.id}
                type="button"
                className={form?.id === f.id ? "on" : ""}
                disabled={readOnly}
                onClick={() => {
                  setFormId(f.id);
                  // Switching shape rewrites the value from that shape's own
                  // defaults, so the part is never left half in one form.
                  if (onValue) {
                    onValue(buildValue(f, f.id === read?.form.id ? read.values
                      : Object.fromEntries(f.fields.map((x) => [x.key, x.default]))));
                  }
                }}
              >
                {f.label}
              </button>
            ))}
          </div>
        ) : null}
        {children}
      </div>
      {form ? form.fields.map((f) => row(f, local[f.key] ?? answers[f.key] ?? f.default, setAnswer)) : null}
      {paramForms.map((pf) => (
        <div key={pf.id} className="sim-param-group">
          {pf.fields.map((f) => row(f, local[f.key] ?? paramValues[f.key.toUpperCase()] ?? f.default, setParam))}
        </div>
      ))}
      {!form && !paramForms.length ? (
        <p className="muted">This part has no numbers to set.</p>
      ) : null}
    </div>
  );
}

export { format };
