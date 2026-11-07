/** The address that opens the bench set up for one step of a batch (decision
 *  0103). The bench reads these once and the operator can change all of them.
 *  Firmware and parameters are not here: the procedure version pins both.
 *
 *  A bench does what one layout can do, so the link ticks the step and its
 *  partners that still have work: Program with its Test, and Laser mark with its
 *  Label (decision 0076).
 */
import type { CraftView, RunInfo } from "../../api";

const LAYOUTS: string[][] = [["program", "test"], ["mark_laser", "label"]];

export function benchHref(run: RunInfo, view: CraftView, key: string): string {
  const step = view.board.find((s) => s.key === key);
  const layout = LAYOUTS.find((l) => step && l.includes(step.kind)) ?? [];
  const partners = view.board.filter((s) => s.key !== key && layout.includes(s.kind) && s.still_to_do > 0);
  const ticked = [key, ...partners.map((s) => s.key)];
  const qs = new URLSearchParams({ project: String(run.project_id), batch: String(run.id), steps: ticked.join(",") });
  if (ticked.some((k) => view.board.find((s) => s.key === k)?.kind === "program")) {
    const stack = view.bench_stack || view.bench_stacks[0]?.stack;
    if (stack) qs.set("stack", stack);
  }
  return `/production/bench?${qs.toString()}`;
}
