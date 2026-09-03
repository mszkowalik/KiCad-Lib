/** The PASS/FAIL table a harness printed, under the waveform it belongs to.
 *
 *  Read out of the run's own log (`scenario.ts`), grouped by the `-- A. … ----`
 *  headings the harnesses already print. Nothing new is asked of anyone.
 */
import type { Verdicts as Read } from "./scenario";

export default function Verdicts({ verdicts }: { verdicts: Read }) {
  if (!verdicts.checks.length) return null;
  return (
    <div className="card pad sim-verdict-card">
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
    </div>
  );
}
