/** One line that says what will run, and one word about what it said.
 *
 *  What this replaced was a card of its own under the drawing: a row of large
 *  buttons for the scenarios, a second row of large buttons for the analysis,
 *  a form, a Run button, a verdict table and a textarea — six blocks deep,
 *  between the circuit and its waveform. Nothing there needs that much room.
 *  A scenario is a choice among a handful of named things, and a choice among
 *  named things is a menu.
 *
 *  So: Run, what to run, which analysis, the directive it builds, and the
 *  score. The analysis form appears only when a form is chosen, and the
 *  control block moved to the details at the foot of the page — it is
 *  reference material, not a control.
 */
import { useMemo, useState } from "react";
import type { SimScenarios } from "../api";
import { eng } from "./payload";
import { buildValue, readValue, type ParamForm } from "./edit/params";
import type { Verdicts } from "./scenario";
import type { LiveState } from "./live";

interface Props {
  live: boolean;
  /** Render the live controls inline (no bar of their own) — they sit in the
   *  page's topbar, beside the volt scale and the current-speed slider. */
  bare?: boolean;
  /** ---------------------------------------------------------- scenario */
  scenarios: SimScenarios | null;
  /** The `.control` block to run, empty for the sheet's own. */
  control: string;
  onControl: (next: string) => void;
  /** The analysis directive, empty to leave the sheet's alone. */
  analysis: string;
  onAnalysis: (next: string) => void;
  busy: boolean;
  onRun: () => void;
  verdicts: Verdicts | null;
  ran: boolean;
  /** -------------------------------------------------------------- live */
  state: LiveState | null;
  speed: number;
  onSpeed: (next: number) => void;
  onHold: () => void;
}

const SPEEDS = [1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1];

export default function RunBar({
  live, bare, scenarios, control, onControl, analysis, onAnalysis, busy, onRun, verdicts, ran,
  state, speed, onSpeed, onHold,
}: Props) {
  const forms = (scenarios?.analysis_forms ?? []) as ParamForm[];
  const [formId, setFormId] = useState<string | null>(null);
  const read = useMemo(() => (analysis ? readValue(forms, analysis) : null), [forms, analysis]);
  const form = forms.find((f) => f.id === formId) ?? read?.form ?? null;
  const answers = useMemo(() => {
    if (!form) return {} as Record<string, string>;
    if (read && read.form.id === form.id) return read.values;
    return Object.fromEntries(form.fields.map((f) => [f.key, f.default]));
  }, [form, read]);
  const setAnswer = (key: string, next: string) => {
    if (form) onAnalysis(buildValue(form, { ...answers, [key]: next }));
  };

  const list = scenarios?.scenarios ?? [];
  const chosen = list.find((s) => s.text === control) ?? null;

  if (live) {
    const status = state?.status ?? "connecting";
    const inner = (
      <>
        <button
          type="button"
          className="primary"
          onClick={onHold}
          disabled={!state || status === "connecting"}
        >
          {status === "halted" ? "Resume" : "Hold"}
        </button>
        <span className={`pill ${status === "running" ? "good" : "neutral"}`}>{status}</span>
        <label className="sim-runbar-pick">
          <span>Speed</span>
          <select className="text" value={String(speed)} onChange={(e) => onSpeed(Number(e.target.value))}>
            {SPEEDS.map((v) => (
              <option key={v} value={String(v)}>{eng(v, "s")} per second</option>
            ))}
          </select>
        </label>
        {bare ? null : <span className="sim-runbar-spacer" />}
        {state ? (
          <span className="muted">
            t = {eng(state.simTime, "s")} · {state.pointsPerSecond} points/s
          </span>
        ) : null}
        {state?.message ? <span className="muted">{state.message}</span> : null}
      </>
    );
    return bare ? inner : <div className="sim-runbar">{inner}</div>;
  }

  return (
    <>
      <div className="sim-runbar">
        <button type="button" className="primary" onClick={onRun} disabled={busy}>
          {busy ? "Running…" : "Run"}
        </button>

        {list.length ? (
          <label className="sim-runbar-pick">
            <span>Scenario</span>
            <select
              className="text"
              value={chosen?.id ?? ""}
              onChange={(e) => {
                const hit = list.find((s) => s.id === e.target.value);
                onControl(hit ? hit.text : "");
              }}
            >
              <option value="">The sheet&apos;s own</option>
              {list.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title}{s.checks ? ` · ${s.checks} checks` : ""}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <label className="sim-runbar-pick">
          <span>Analysis</span>
          <select
            className="text"
            value={analysis ? form?.id ?? "" : ""}
            onChange={(e) => {
              const hit = forms.find((f) => f.id === e.target.value);
              if (!hit) { setFormId(null); onAnalysis(""); return; }
              setFormId(hit.id);
              onAnalysis(buildValue(hit, Object.fromEntries(hit.fields.map((x) => [x.key, x.default]))));
            }}
          >
            <option value="">From the sheet</option>
            {forms.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </label>

        {analysis ? <code className="sim-runbar-directive">{analysis}</code> : null}

        <span className="sim-runbar-spacer" />

        {verdicts && verdicts.checks.length ? (
          <span className={`pill ${verdicts.failed ? "bad" : "good"}`}>
            {verdicts.failed
              ? `${verdicts.failed} of ${verdicts.checks.length} failed`
              : `${verdicts.checks.length} checks passed`}
          </span>
        ) : ran ? (
          <span className="muted">no checks in this run</span>
        ) : null}
      </div>

      {/* Only for an analysis the user chose. "From the sheet" has no numbers
          to ask for, and an empty form row under every run is furniture. */}
      {analysis && form ? (
        <div className="sim-runbar sim-runbar-form">
          {form.fields.map((f) => (
            <label key={f.key} className="sim-runbar-pick">
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
          ))}
        </div>
      ) : null}
    </>
  );
}
