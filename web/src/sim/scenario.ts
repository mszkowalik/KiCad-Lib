/** What a harness said, read out of what it printed.
 *
 *  A simulation harness ends its `.control` block with a verdict table —
 *  `PASS <id> <words>` and `FAIL <id> <words>`, under `-- A. section ----`
 *  headings. That convention is already in every harness in `EVSE_20_CTRL`;
 *  nothing new is asked of anyone. Reading it turns a run from a wall of log
 *  into a list of answers, which is the thing a reviewer actually wants.
 */

export interface Verdict {
  ok: boolean;
  /** The check's own id, where the harness gives one — `S9`, `S5`. */
  id: string;
  text: string;
  section: string;
}

export interface Verdicts {
  checks: Verdict[];
  passed: number;
  failed: number;
}

const VERDICT = /^\s*(PASS|FAIL)\b[ \t]*(.*)$/;
const SECTION = /^\s*--+\s*(.*?)\s*--+\s*$/;

export function readVerdicts(log: string): Verdicts {
  const checks: Verdict[] = [];
  let section = "";
  for (const line of (log || "").split("\n")) {
    const head = SECTION.exec(line);
    if (head && head[1]) {
      section = head[1];
      continue;
    }
    const hit = VERDICT.exec(line);
    if (!hit) continue;
    const rest = hit[2].trim();
    // `PASS  S9  power-up   SO1 released` — the first token is the check's own
    // id where the harness gives one, and a heading otherwise.
    const parts = rest.split(/\s+(.*)/s);
    const id = parts.length > 1 && parts[0].length <= 8 ? parts[0] : "";
    checks.push({
      ok: hit[1] === "PASS",
      id,
      text: (id ? parts[1] ?? "" : rest).trim(),
      section,
    });
  }
  const passed = checks.filter((c) => c.ok).length;
  return { checks, passed, failed: checks.length - passed };
}
