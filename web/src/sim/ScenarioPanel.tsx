/** What this schematic offers to run, and what the last run said.
 *
 *  A harness carries its scenario as SPICE text beside the circuit. Left as
 *  text it is a wall the user is asked to take on faith before pressing Run;
 *  listed, it is a menu — these runs, this analysis, this stimulus behind
 *  them.
 *
 *  And a harness ends by printing a verdict table. Showing that first, green
 *  and red, is the difference between a simulator and a test runner.
 */
import { useMemo, useState } from "react";
import type { SimScenarios, SimTextItem } from "../api";
import { buildValue, readValue, type ParamForm } from "./edit/params";
import { readVerdicts } from "./scenario";

interface Props {
  scenarios: SimScenarios | null;
  /** The `.control` block to run, empty for the sheet's own. */
  control: string;
  onControl: (next: string) => void;
  /** The analysis directive, empty to leave the sheet's alone. */
  analysis: string;
  onAnalysis: (next: string) => void;
  /** The last run's log, for the verdicts. */
  log: string;
  busy: boolean;
  onRun: () => void;
}

export default function ScenarioPanel({
  scenarios, control, onControl, analysis, onAnalysis, log, busy, onRun,
}: Props) {
  const [open, setOpen] = useState(false);
  const verdicts = useMemo(() => readVerdicts(log), [log]);
  const forms = (scenarios?.analysis_forms ?? []) as ParamForm[];
  const [formId, setFormId] = useState<string | null>(null);
  const read = useMemo(
    () => (analysis ? readValue(forms, analysis) : null),
    [forms, analysis],
  );
  const form = forms.find((f) => f.id === formId) ?? read?.form ?? null;
  const answers = useMemo(() => {
    if (!form) return {} as Record<string, string>;
    if (read && read.form.id === form.id) return read.values;
    return Object.fromEntries(form.fields.map((f) => [f.key, f.default]));
  }, [form, read]);

  const setAnswer = (key: string, next: string) => {
    if (!form) return;
    onAnalysis(buildValue(form, { ...answers, [key]: next }));
  };

  const list = scenarios?.scenarios ?? [];
  const chosen = list.find((s) => s.text === control) ?? null;

  return (
    <div className="card pad sim-scenarios">
      <div className="card-title">What to run</div>

      {list.length ? (
        <div className="sim-runs">
          <button
            type="button"
            className={`sim-run${!control ? " on" : ""}`}
            onClick={() => onControl("")}
          >
            <strong>The sheet&apos;s own</strong>
            <span className="muted">whatever the harness does by default</span>
          </button>
          {list.map((s: SimTextItem) => (
            <button
              key={s.id}
              type="button"
              className={`sim-run${chosen?.id === s.id ? " on" : ""}`}
              onClick={() => onControl(s.text)}
            >
              <strong>{s.title}</strong>
              <span className="muted">
                {s.checks ? `${s.checks} checks` : "no verdict table"}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="muted">
          This schematic carries no <span className="mono">.control</span> block.
          Choose an analysis below and it runs that.
        </p>
      )}

      <div className="sim-knobs sim-analysis">
        <span className="muted">Analysis</span>
        <div className="seg" role="group" aria-label="Analysis">
          <button
            type="button"
            className={!analysis ? "on" : ""}
            onClick={() => { setFormId(null); onAnalysis(""); }}
            title="Use the directive the schematic itself carries"
          >
            From the sheet
          </button>
          {forms.map((f) => (
            <button
              key={f.id}
              type="button"
              className={analysis && form?.id === f.id ? "on" : ""}
              onClick={() => {
                setFormId(f.id);
                onAnalysis(buildValue(f, Object.fromEntries(f.fields.map((x) => [x.key, x.default]))));
              }}
            >
              {f.label}
            </button>
          ))}
        </div>
        {analysis && form ? form.fields.map((f) => (
          <label key={f.key} className="sim-knob">
            <span>{f.label}</span>
            {f.scale === "choice" ? (
              <select
                className="text"
                value={answers[f.key] ?? f.default}
                onChange={(e) => setAnswer(f.key, e.target.value)}
              >
                {(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input
                className="text"
                defaultValue={answers[f.key] ?? f.default}
                key={`${form.id}:${f.key}:${answers[f.key] ?? f.default}`}
                onBlur={(e) => setAnswer(f.key, e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") setAnswer(f.key, (e.target as HTMLInputElement).value);
                }}
              />
            )}
            {f.unit ? <span className="muted">{f.unit}</span> : null}
          </label>
        )) : null}
        <button type="button" className="primary" onClick={onRun} disabled={busy}>
          {busy ? "Running…" : "Run"}
        </button>
        {analysis ? <span className="mono muted">{analysis}</span> : null}
      </div>

      {verdicts.checks.length ? (
        <>
          <div className="sim-verdict-head">
            <span className={`pill ${verdicts.failed ? "bad" : "good"}`}>
              {verdicts.failed ? `${verdicts.failed} failed` : "all passed"}
            </span>
            <span className="muted">{verdicts.passed} of {verdicts.checks.length} checks</span>
          </div>
          <div className="sim-verdicts">
            {verdicts.checks.map((c, i) => {
              const heading = i === 0 || c.section !== verdicts.checks[i - 1].section;
              return (
                <div key={i}>
                  {heading && c.section ? <div className="sim-verdict-section">{c.section}</div> : null}
                  <div className={`sim-verdict${c.ok ? "" : " bad"}`}>
                    <span className="sim-verdict-mark">{c.ok ? "PASS" : "FAIL"}</span>
                    {c.id ? <span className="mono sim-verdict-id">{c.id}</span> : null}
                    <span>{c.text}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      ) : null}

      {(chosen || control) ? (
        <>
          <button type="button" className="ghost" onClick={() => setOpen((v) => !v)}>
            {open ? "Hide" : "Show"} the control block
          </button>
          {open ? (
            <textarea
              className="text sim-control"
              rows={14}
              value={control}
              onChange={(e) => onControl(e.target.value)}
              spellCheck={false}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}
