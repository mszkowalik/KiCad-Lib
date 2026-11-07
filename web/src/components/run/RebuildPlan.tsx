/** The answer of a rebuild's dry run, in words and tables. The dry run IS the
 *  review (decision 0075 §11): the per-device plan, the parts against the units,
 *  what is unsettled, the money check and every refusal.
 *
 *  The answer is big, about 650 KB for a batch of 1000 devices. So each list is in
 *  a `FoldSection`, whose rows render only when open, and the first thing a reader
 *  sees is what stops the write.
 */
import type { RebuildDevicePlan, RebuildPartRow, RebuildPlan, RebuildUndoPlan, RebuildUndoRow } from "../../api";
import { pln } from "../../format";
import DataTable, { type Column } from "../DataTable";
import FoldSection, { StatChip } from "../FoldSection";
import { StatusPill } from "../Ui";

/** A USD figure of the plan, in PLN at the batch's date. */
type Money = (v: number | null | undefined) => string;

/** One price, or the lowest and the highest. An append with no new twin has none. */
function deviceCost(v: number | number[], money: Money): string {
  if (!Array.isArray(v)) return money(v);
  if (!v.length) return "—";
  return v.length === 1 ? money(v[0]) : `${money(v[0])} to ${money(v[1])}`;
}

/** What a dry run states on one line. */
export function rebuildSummary(p: RebuildPlan): string {
  const had = Array.isArray(p.devices_with_a_twin_already)
    ? p.devices_with_a_twin_already.length : p.devices_with_a_twin_already;
  return [
    `Process v${p.process_version}: ${p.twins} twin(s), ${p.named} on named devices, ${p.spares} spare(s).`,
    `${p.finished} finished, ${p.active} active, ${p.scrapped} scrapped.`,
    had ? `${had} device(s) already have a twin and stay as they are.` : "",
    p.twins ? "" : "Nothing would be written.",
  ].filter(Boolean).join(" ");
}

function warnings(p: RebuildPlan, label: (k: string) => string): string[] {
  const out: string[] = [];
  if (p.no_assembly_invoice) out.push("No invoice of this batch has a board or an assembly position.");
  if (p.more_units_than_boards) {
    out.push(`${p.more_units_than_boards} more unit(s) than the ${p.boards_from_orders} board(s) on its orders.`);
  }
  if (p.found_naming_this_batch.unnamed_active) {
    out.push(`${p.found_naming_this_batch.unnamed_active} found unit(s) name this batch as their origin and have no device yet.`);
  }
  if (p.finish_lacks.length) {
    out.push(`Some twins lack a required step, so they are finished without it: ${p.finish_lacks.map(label).join(", ")}.`);
  }
  for (const [step, v] of Object.entries(p.bench_says_not_done)) {
    out.push(`A bench record says ${label(step)} was not done on ${v.devices} device(s), so a statement cannot add it. First: ${v.first.join("; ")}.`);
  }
  return out;
}

function MoneyCheck({ p, money }: { p: RebuildPlan; money: Money }) {
  const c = p.check;
  return (
    <>
      <div className="btn-row">
        <h3 className="card-subtitle">Money check</h3>
        <StatusPill status={c.ok ? "ok" : "failed"} />
      </div>
      <dl className="kv">
        <dt>Batch cost before</dt>
        <dd>{money(c.total_before_usd)}</dd>
        <dt>Batch cost after</dt>
        <dd>{money(c.total_usd)}{c.moved_usd ? ` (moves ${money(c.moved_usd)})` : ""}</dd>
        <dt>Draws written</dt>
        <dd>{money(c.drawn_usd)}{p.draws_added.length ? ` in ${p.draws_added.length} draw(s)` : ""}</dd>
        <dt>Surplus returned</dt>
        <dd>{money(c.returned_usd)}{p.draws_returned.length ? ` from ${p.draws_returned.length} draw(s)` : ""}</dd>
        <dt>The twins carry</dt>
        <dd>
          {money(c.carried_usd)} over {c.twins} twin(s)
          {c.from_other_batches_usd ? `, ${money(c.from_other_batches_usd)} from other batches` : ""}
        </dd>
        <dt>One device, before</dt>
        <dd>{money(p.device_cost_before_usd)}</dd>
        <dt>One device, after</dt>
        <dd>{deviceCost(p.device_cost_after_usd, money)}</dd>
      </dl>
    </>
  );
}

interface StepRow { key: string; label: string; units: number | null; recorded: string; note: string }

const STEP_COLUMNS: Column<StepRow>[] = [
  { key: "label", label: "Step", width: 24, get: (r) => r.label },
  { key: "units", label: "Units", width: 8, numeric: true, get: (r) => r.units ?? 0,
    render: (r) => (r.units === null ? "—" : r.units.toLocaleString()) },
  { key: "recorded", label: "Recorded", width: 11, get: (r) => r.recorded },
  { key: "note", label: "Evidence, or why not", width: 57, get: (r) => r.note, title: (r) => r.note },
];

function stepRows(p: RebuildPlan): StepRow[] {
  return [
    ...p.recorded.map((r) => ({
      // The plan names the assembly and the receipt by their keys alone.
      key: `r${r.step}`, label: r.label ?? r.step[0].toUpperCase() + r.step.slice(1), units: r.units, recorded: "yes",
      note: [r.evidence, r.clicks ? `${r.clicks} click(s) on ${r.days} day(s)` : ""].filter(Boolean).join(", "),
    })),
    ...p.not_recorded.map((r) => ({ key: `n${r.step}`, label: r.label, units: null, recorded: "no", note: r.why })),
  ];
}

const PART_COLUMNS: Column<RebuildPartRow>[] = [
  { key: "step", label: "Step", width: 12, className: "mono", get: (r) => r.step },
  { key: "part", label: "Part key", width: 13, className: "mono", get: (r) => r.part },
  { key: "name", label: "Name", width: 17, get: (r) => r.name, title: (r) => r.name },
  { key: "need", label: "Needed", width: 8, numeric: true, get: (r) => r.need },
  { key: "drawn", label: "Drawn", width: 8, numeric: true, get: (r) => r.drawn },
  { key: "surplus", label: "Surplus", width: 8, numeric: true, get: (r) => r.surplus },
  { key: "deficit", label: "Deficit", width: 8, numeric: true, get: (r) => r.deficit },
  { key: "say", label: "Statement", width: 26, get: (r) => r.why ?? r.settled ?? "", title: (r) => r.why ?? r.settled ?? "",
    render: (r) => (r.why ? <span className="err-text">{r.why}</span> : r.settled ?? <span className="muted">none needed</span>) },
];

function deviceColumns(label: (k: string) => string, money: Money): Column<RebuildDevicePlan>[] {
  const stepsText = (d: RebuildDevicePlan) => Object.entries(d.steps)
    .map(([k, s]) => `${label(k)} ${s.on ?? ""}`.trim()).join(", ");
  // A date, a pill and a price have a hard maximum, so they take a length. The
  // percent columns share what is left.
  return [
    { key: "device", label: "Device", width: 18, className: "mono", get: (d) => d.serial || d.mac },
    { key: "status", label: "Status", width: "100px", get: (d) => d.status, render: (d) => <StatusPill status={d.status} /> },
    { key: "produced", label: "Programmed", width: "112px", className: "mono", get: (d) => d.produced ?? "" },
    { key: "steps", label: "Steps", width: 44, get: stepsText, title: stepsText },
    { key: "lacks", label: "Lacks", width: 22, get: (d) => d.lacks.map(label).join(", "), title: (d) => d.lacks.map(label).join(", ") },
    { key: "origin", label: "Origin", width: 16, get: (d) => d.origin ?? "", title: (d) => d.origin ?? "" },
    { key: "price", label: "Price", width: "96px", numeric: true, get: (d) => d.price_usd ?? 0, render: (d) => money(d.price_usd) },
  ];
}

interface OriginRow { key: string; kind: string; what: string }

function originRows(p: RebuildPlan, money: Money): OriginRow[] {
  return [
    ...p.left_in_origin.lines.map((l) => ({ key: `l${l.line_id}`, kind: "position", what: l.label })),
    ...p.lines_whose_steps_were_not_recorded.map((l) => ({
      key: `u${l.line_id}`, kind: "position, its steps are not recorded", what: `${l.label} (${l.steps.join(", ")})`,
    })),
    ...p.left_in_origin.draws.map((d) => ({ key: `d${d.consumption_id}`, kind: "draw", what: d.mpn })),
    ...p.left_in_origin.loss.map((d, i) => ({
      key: `x${i}`, kind: "surplus kept as a loss", what: `${d.step} ${d.part}: ${d.qty} (${money(d.usd)})`,
    })),
  ];
}

const ORIGIN_COLUMNS: Column<OriginRow>[] = [
  { key: "kind", label: "Kind", width: 30, get: (r) => r.kind },
  { key: "what", label: "What", width: 70, get: (r) => r.what, title: (r) => r.what },
];

/** The sentence to copy into the advanced box. The first unsettled row is the
 *  example, so the step and the part key are already the right ones. */
function settleExample(rows: RebuildPartRow[]): string {
  const first = rows[0];
  const how = first.surplus > 0 ? "return" : "draw";
  return JSON.stringify({ settle: [{ step: first.step, part: first.part, how }] });
}

export function RebuildPlanView({ plan: p, rate }: { plan: RebuildPlan; rate: number | null | undefined }) {
  const money: Money = (v) => pln(v, rate, 4);
  const labels = new Map<string, string>();
  for (const r of p.recorded) if (r.label) labels.set(r.step, r.label);
  for (const r of p.not_recorded) labels.set(r.step, r.label);
  const label = (k: string) => labels.get(k) ?? k;
  const warn = warnings(p, label);
  const steps = stepRows(p);
  const origin = originRows(p, money);
  return (
    <>
      {p.refusals.length ? (
        <div className="banner-error">
          {p.refusals.map((r) => <div key={r.message}>{r.message}</div>)}
        </div>
      ) : null}
      {warn.length ? <div className="banner-warn">{warn.map((w) => <div key={w}>{w}</div>)}</div> : null}
      <MoneyCheck p={p} money={money} />
      <FoldSection bare title="Steps" count={steps.length}
        chips={<>
          <StatChip n={p.recorded.length} tone="ok">recorded</StatChip>
          {p.not_recorded.length ? <StatChip n={p.not_recorded.length} tone="warn">not recorded</StatChip> : null}
        </>}>
        <DataTable rows={steps} rowKey={(r) => r.key} columns={STEP_COLUMNS} empty="No step." />
      </FoldSection>
      <FoldSection bare title="Parts against units" count={p.parts.length} forceOpen={p.unsettled.length > 0}
        chips={p.unsettled.length ? <StatChip n={p.unsettled.length} tone="err">need a statement</StatChip> : null}>
        {p.unsettled.length ? (
          <p className="muted dim">
            Each red row needs one statement in the advanced box: <code>draw</code> or <code>short</code> for a
            deficit, <code>return</code> or <code>loss</code> for a surplus. Example: <code>{settleExample(p.unsettled)}</code>
          </p>
        ) : null}
        <DataTable rows={p.parts} rowKey={(r) => `${r.step}|${r.part}`} columns={PART_COLUMNS} empty="No step draws parts." />
      </FoldSection>
      <FoldSection bare title="Stays in the origin batch cost" count={origin.length}>
        <DataTable rows={origin} rowKey={(r) => r.key} columns={ORIGIN_COLUMNS} empty="Nothing stays there." />
      </FoldSection>
      {p.spare_units.length ? (
        <p className="muted">
          Spares: {p.spare_units.map((s) => `${s.qty} × ${s.done.map(label).join(" + ")}`).join("; ")}.
        </p>
      ) : null}
      <FoldSection bare title="Devices" count={p.devices.length}
        chips={<>
          <StatChip n={p.finished} tone="ok">finished</StatChip>
          {p.active ? <StatChip n={p.active}>active</StatChip> : null}
          {p.scrapped ? <StatChip n={p.scrapped}>scrapped</StatChip> : null}
        </>}>
        <DataTable rows={p.devices} rowKey={(d) => d.device_id} columns={deviceColumns(label, money)} empty="No device gets a twin." />
      </FoldSection>
    </>
  );
}

function undoRowText(r: RebuildUndoRow): string {
  switch (r.kind) {
    case "journal":
      return `Write batch ${r.batch_id} (${r.write}): `
        + (r.clicks.map((c) => `${c.label || c.step} on ${c.made_at}, ${c.units} unit(s)`).join("; ") || "no click")
        + (r.twins_outside_the_rebuild ? `. It also touches ${r.twins_outside_the_rebuild} twin(s) outside the rebuild.` : "");
    case "bench":
      return `${r.label || r.step} on ${r.made_at}: ${r.devices.length} device(s), ${r.draws} draw(s)`;
    case "link":
      return `Invoice position ${r.line_id} leaves click ${r.click_id}`;
    case "key":
      return `Invoice position ${r.line_id} leaves the step ${r.step}`;
  }
}

const UNDO_KIND: Record<RebuildUndoRow["kind"], string> = {
  journal: "crafting write", bench: "bench click", link: "cost link", key: "whole-step link",
};

const UNDO_COLUMNS: Column<RebuildUndoRow>[] = [
  { key: "kind", label: "Kind", width: 18, get: (r) => UNDO_KIND[r.kind] },
  { key: "what", label: "What", width: 82, get: undoRowText, title: undoRowText },
];

export function RebuildUndoView({ plan: p }: { plan: RebuildUndoPlan }) {
  return (
    <>
      {p.refused.length ? (
        <div className="banner-error">{p.refused.map((r) => <div key={r}>{r}</div>)}</div>
      ) : null}
      {p.takes_back.length ? (
        <FoldSection bare title="It takes back" count={p.takes_back.length}>
          <DataTable rows={p.takes_back} rowKey={(r) => JSON.stringify(r)} columns={UNDO_COLUMNS} />
        </FoldSection>
      ) : null}
    </>
  );
}
