/** A part's parameters, as a person thinks of them.
 *
 *  SPICE wants a string: `PULSE(0 5 0 1u 1u 1m 2m)` is seven numbers in an
 *  order nobody remembers, and `Sim.Params` is `KEY=value` pairs. The server
 *  declares what each part is ASKED for (`sch_lib.PARAM_FORMS`); this builds
 *  the string from the answers and reads the answers back out of it.
 *
 *  Nothing is translated behind the user's back — the Value field stays the
 *  SPICE value, and the raw form is always there for anything the fields
 *  cannot express.
 */
import { spiceValue } from "../live";

export interface ParamField {
  key: string;
  label: string;
  unit: string;
  default: string;
  /** `log` gets a logarithmic slider, `linear` a plain one, `text` none,
   *  `choice` a menu of `options`. */
  scale: "log" | "linear" | "text" | "choice";
  options?: string[];
  min: number;
  max: number;
  /** Can be steered by `alter` on a RUNNING transient. A waveform cannot, and
   *  neither can a `.model` parameter. */
  live: boolean;
}

export interface ParamForm {
  id: string;
  label: string;
  /** `value` builds the Value field; `params` sets `Sim.Params` keys. */
  target: "value" | "params";
  template: string;
  fields: ParamField[];
}

const PLACEHOLDER = /\{(\w+)\}/g;

/** Fill a template from the answers. */
export function buildValue(form: ParamForm, values: Record<string, string>): string {
  return form.template.replace(PLACEHOLDER, (_, key: string) => {
    const field = form.fields.find((f) => f.key === key);
    const got = values[key];
    return (got === undefined || got === "" ? field?.default ?? "" : got).trim();
  });
}

/** Read the answers back out of a value. Returns null when the template does
 *  not describe this string, which is how the right form is chosen. */
export function matchValue(form: ParamForm, value: string): Record<string, string> | null {
  const keys: string[] = [];
  let pattern = "";
  let last = 0;
  for (const m of form.template.matchAll(PLACEHOLDER)) {
    pattern += form.template.slice(last, m.index).replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
    // A field runs to the next literal — a bracket, a comma or whitespace.
    pattern += "(\\S+?)";
    keys.push(m[1]);
    last = (m.index ?? 0) + m[0].length;
  }
  pattern += form.template.slice(last).replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
  const re = new RegExp(`^\\s*${pattern}\\s*$`, "i");
  const hit = re.exec(value.trim());
  if (!hit) return null;
  const out: Record<string, string> = {};
  keys.forEach((k, i) => { out[k] = hit[i + 1] ?? ""; });
  return out;
}

/** The form a value is written in, and the answers in it. Falls back to the
 *  LAST form, which is the raw one — a value the fields cannot express is
 *  still a value, and hiding it would be worse than showing it plainly. */
export function readValue(forms: ParamForm[], value: string): { form: ParamForm; values: Record<string, string> } | null {
  const usable = forms.filter((f) => f.target === "value");
  if (!usable.length) return null;
  for (const form of usable) {
    const values = matchValue(form, value);
    if (values) return { form, values };
  }
  const raw = usable[usable.length - 1];
  return { form: raw, values: { [raw.fields[0]?.key ?? "raw"]: value } };
}

/** `Sim.Params` as a map. `KEY=value KEY=value`, the way KiCad writes it. */
export function readParams(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of (text || "").matchAll(/([A-Za-z_]\w*)\s*=\s*(\S+)/g)) out[m[1].toUpperCase()] = m[2];
  return out;
}

export function writeParams(values: Record<string, string>): string {
  return Object.entries(values)
    .filter(([, v]) => v !== "" && v !== undefined)
    .map(([k, v]) => `${k}=${v}`)
    .join(" ");
}

// ------------------------------------------------------------------ slider

/** A slider position (0..1) for a value, and back. Logarithmic where the
 *  quantity is: a resistance slider that is linear spends nine tenths of its
 *  travel above a megohm and is useless below one. */
export function toSlider(field: ParamField, value: string): number {
  const v = spiceValue(value);
  if (v === null) return 0.5;
  if (field.scale === "log") {
    const lo = Math.log10(Math.max(field.min, 1e-18));
    const hi = Math.log10(Math.max(field.max, field.min * 10));
    return clamp((Math.log10(Math.max(Math.abs(v), 1e-18)) - lo) / (hi - lo));
  }
  return clamp((v - field.min) / (field.max - field.min || 1));
}

export function fromSlider(field: ParamField, at: number): string {
  if (field.scale === "log") {
    const lo = Math.log10(Math.max(field.min, 1e-18));
    const hi = Math.log10(Math.max(field.max, field.min * 10));
    return format(10 ** (lo + clamp(at) * (hi - lo)));
  }
  return format(field.min + clamp(at) * (field.max - field.min));
}

function clamp(v: number): number {
  return Math.min(1, Math.max(0, Number.isFinite(v) ? v : 0));
}

const SUFFIX: [number, string][] = [
  [1e12, "T"], [1e9, "G"], [1e6, "meg"], [1e3, "k"], [1, ""],
  [1e-3, "m"], [1e-6, "u"], [1e-9, "n"], [1e-12, "p"], [1e-15, "f"],
];

/** A number the way an engineer types it — `4k7` is not SPICE, but `4.7k`
 *  is, and that is what goes in the field. */
export function format(v: number): string {
  if (!Number.isFinite(v) || v === 0) return "0";
  const sign = v < 0 ? "-" : "";
  const abs = Math.abs(v);
  for (const [scale, suffix] of SUFFIX) {
    if (abs >= scale) {
      const n = abs / scale;
      const digits = n >= 100 ? 0 : n >= 10 ? 1 : 2;
      return sign + Number(n.toFixed(digits)).toString() + suffix;
    }
  }
  return sign + abs.toExponential(2);
}
