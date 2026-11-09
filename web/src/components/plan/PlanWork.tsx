/** The work of a plan (decision 0107 items 7 to 13): planned batches, machining
 *  lots, milestones and closures, and the parts the customer supplies. Each is
 *  a list with an Add dialog, and a click on a row opens what it can change.
 *  Every date goes through `StepFields` or `NodeEditor`. */
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  addPlanBatch,
  addPlanCustomerPart,
  addPlanLot,
  addPlanNode,
  deletePlanBatch,
  deletePlanCustomerPart,
  deletePlanLot,
  deletePlanNode,
  markPlanBatchOrdered,
  reviewWarningOf,
  updatePlanCustomerPart,
  updatePlanLot,
  type PlanBatch,
  type PlanCustomerPartRow,
  type PlanFull,
  type PlanLagUnit,
  type PlanLotRow,
  type PlanMilestone,
  type PlanParty,
  type PlanSource,
  type PlanStepIn,
} from "../../api";
import { today } from "../../format";
import DataTable from "../DataTable";
import { useDialog } from "../Dialog";
import Field, { CheckField, FieldGrid } from "../Field";
import FoldSection, { StatChip } from "../FoldSection";
import { useModal } from "../modal";
import NumberInput from "../NumberInput";
import { StatusPill } from "../Ui";
import NodeEditor, { LAG_UNITS, PARTIES, RefsPicker, SOURCES, StepFields, stepProblem, type StepValue } from "./NodeEditor";
import { Declined, fitColumns, refOptions, units, useNarrow, type Apply, type PlanColumn } from "./planUtil";

const FIXED_TODAY = (): StepValue => ({ mode: "fixed", day: today(), after: [], lag: 0, lag_unit: "days", snap_weekday: null });

function stepBody(v: StepValue): PlanStepIn {
  return v.mode === "fixed"
    ? { mode: "fixed", day: v.day, ...(v.after.length ? { after: v.after, lag: v.lag, lag_unit: v.lag_unit } : {}) }
    : { mode: "after", after: v.after, lag: v.lag, lag_unit: v.lag_unit };
}

/** A design-review warning in sentences, with counts and the first names. The
 *  dialog prints one paragraph, so it is sentences, not a list. */
function reviewText(w: NonNullable<ReturnType<typeof reviewWarningOf>>): string {
  const some = (xs: string[]) => `${xs.length} parts (${xs.slice(0, 5).join(", ")}${xs.length > 5 ? ", …" : ""})`;
  const parts: string[] = ["The design this batch is built from is not review-clean."];
  if (!w.review_completed) parts.push("Its design review was never completed.");
  if (w.changed_since_review.length) parts.push(`${some(w.changed_since_review)} changed since the review.`);
  if (w.unsigned.length) parts.push(`${some(w.unsigned)} are not signed off.`);
  if (w.not_verified.length) parts.push(`${some(w.not_verified)} are not verified.`);
  if (w.deprecated.length) parts.push(`${some(w.deprecated)} are deprecated.`);
  parts.push("Plan the batch anyway? The confirmation is recorded.");
  return parts.join(" ");
}

// ------------------------------------------------------------------ batches

function AddBatchDialog({ full, onClose, apply }: { full: PlanFull; onClose: () => void; apply: Apply }) {
  const modal = useModal(onClose);
  const dialog = useDialog();
  const designs = full.plan.projects;
  const [projectId, setProjectId] = useState<number | null>(designs[0]?.project_id ?? null);
  const [label, setLabel] = useState("");
  const [qty, setQty] = useState(500);
  const [order, setOrder] = useState<StepValue>(FIXED_TODAY);
  const [lag, setLag] = useState(20);
  const [lagUnit, setLagUnit] = useState<PlanLagUnit>("days");
  const [waits, setWaits] = useState<string[]>([]);
  const [cost, setCost] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const problem = projectId == null ? "Choose the project." : !(qty >= 1) ? "Enter the quantity." : stepProblem(order);
  const save = async () => {
    if (projectId == null) return;
    const body = {
      project_id: projectId,
      label: label.trim(),
      qty,
      order: { ...stepBody(order), ...(cost != null ? { amount: cost, currency: "PLN" } : {}) },
      arrival: { lag, lag_unit: lagUnit, ...(waits.length ? { after: waits } : {}), source: "estimate" as PlanSource },
    };
    setBusy(true);
    const ok = await apply(`the batch ${label || `of ${qty}`}`, async () => {
      try {
        return await addPlanBatch(full.plan.id, body);
      } catch (err) {
        const w = reviewWarningOf(err);
        if (!w) throw err;
        const go = await dialog.confirm(reviewText(w), {
          title: "Design review incomplete", confirmLabel: "Plan it anyway", tone: "danger", cancelLabel: "Not yet",
        });
        if (!go) throw new Declined();
        return addPlanBatch(full.plan.id, { ...body, ack_review: true });
      }
    });
    setBusy(false);
    if (ok) onClose();
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">Plan a batch</h2>
        <p className="muted dim">
          A planned batch is a batch with the status planned. It takes the plan&apos;s design of its
          project, and its BOM counts in the parts balance from the order date.
        </p>
        {designs.length ? null : (
          <div className="banner-warn">Add the project to the plan&apos;s designs first.</div>
        )}
        <FieldGrid>
          <Field label="Project">
            <select className="text" value={projectId ?? ""} onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)}>
              {designs.map((d) => <option key={d.project_id} value={d.project_id}>{d.project}</option>)}
            </select>
          </Field>
          <Field label="Name" hint="Empty: Planned batch with its quantity.">
            <input className="text" value={label} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label="Boards">
            <NumberInput className="text" value={qty} min={1} onChange={(v) => setQty(Math.round(v))} />
          </Field>
          <Field label="PCBA cost estimate (PLN)" hint="Counts as a purchase in the cash check.">
            <NumberInput className="text" value={cost} onChange={setCost} onEmpty={() => setCost(null)} />
          </Field>
        </FieldGrid>
        <h3 className="plan-sub">Order</h3>
        <StepFields value={order} onChange={setOrder} options={refOptions(full)} fixedLabel="Order day" />
        <h3 className="plan-sub">Arrival</h3>
        <FieldGrid>
          <Field label="After the order, plus">
            <NumberInput className="text" value={lag} onChange={(v) => setLag(Math.round(v))} onEmpty={() => setLag(0)} />
          </Field>
          <Field label="Unit">
            <select className="text" value={lagUnit} onChange={(e) => setLagUnit(e.target.value as PlanLagUnit)}>
              {LAG_UNITS.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
            </select>
          </Field>
        </FieldGrid>
        <Field group label="It also waits for (optional): a purchase that must arrive, a milestone">
          <RefsPicker value={waits} onChange={setWaits} options={refOptions(full)} />
        </Field>
        <div className="btn-row modal-actions">
          {problem ? <StatChip tone="warn">{problem}</StatChip> : null}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !!problem} onClick={() => void save()}>
            Plan the batch
          </button>
        </div>
      </div>
    </div>
  );
}

function BatchDialog({ full, batch, onClose, apply }: {
  full: PlanFull;
  batch: PlanBatch;
  onClose: () => void;
  apply: Apply;
}) {
  const modal = useModal(onClose);
  const dialog = useDialog();
  const [node, setNode] = useState<"order" | "arrival" | null>(null);
  const editing = node === "order" ? batch.order_node_id : node === "arrival" ? batch.arrival_node_id : null;
  const n = editing ? full.nodes.find((x) => x.id === editing) : undefined;
  const ordered = async () => {
    const day = await dialog.prompt(`The day ${batch.label} was ordered (YYYY-MM-DD):`, {
      title: "Mark the batch ordered", initial: today(), confirmLabel: "Mark ordered",
    });
    if (day == null) return;
    if (await apply(`${batch.label} ordered on ${day}`, () => markPlanBatchOrdered(full.plan.id, batch.id, day.trim())))
      onClose();
  };
  const remove = async () => {
    const ok = await dialog.confirm(
      `Delete the planned batch ${batch.label} (${units(batch.qty)} boards)? Its order and arrival dates go with it. `
      + "History → Write batches can undo it.",
      { title: "Delete planned batch", confirmLabel: "Delete", tone: "danger" },
    );
    if (!ok) return;
    if (await apply(`the deletion of ${batch.label}`, () => deletePlanBatch(full.plan.id, batch.id))) onClose();
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">{batch.label} <StatusPill status={batch.status} /></h2>
        <dl className="kv">
          <dt>Project</dt>
          <dd>{batch.project}</dd>
          <dt>Boards</dt>
          <dd>{units(batch.qty)}</dd>
          <dt>Order</dt>
          <dd>{batch.order_day || "—"}{batch.order_late_days ? ` (${batch.order_late_days} days late, planned ${batch.order_planned})` : ""}</dd>
          <dt>Arrival</dt>
          <dd>{batch.arrival_day || "—"}</dd>
          <dt>Cost estimate</dt>
          <dd>{batch.cost != null ? `${batch.cost.toLocaleString()} ${batch.cost_currency}` : "—"}</dd>
        </dl>
        {batch.conflict || batch.closures.length ? (
          <div className="banner-warn">
            {batch.conflict}{batch.closures.length ? ` In production over ${batch.closures.join(", ")}.` : ""}
          </div>
        ) : null}
        <p className="muted dim">
          {batch.planned
            ? "Mark it ordered when the order goes to the factory: its design and process are then pinned."
            : "The batch is ordered. Its page holds everything else about it."}
        </p>
        <div className="btn-row modal-actions">
          <Link className="comp-link" to={`/production/batches/${batch.id}`}>Open the batch page</Link>
          {batch.order_node_id ? <button type="button" className="btn btn-sm" onClick={() => setNode("order")}>Order date…</button> : null}
          {batch.arrival_node_id ? <button type="button" className="btn btn-sm" onClick={() => setNode("arrival")}>Arrival…</button> : null}
          {batch.planned ? <button type="button" className="btn btn-sm" onClick={() => void ordered()}>Mark ordered…</button> : null}
          {batch.planned ? <button type="button" className="btn btn-sm btn-danger" onClick={() => void remove()}>Delete…</button> : null}
          <button type="button" className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
      {n ? (
        <NodeEditor full={full} node={n} apply={apply} onClose={() => setNode(null)}
          title={node === "order" ? `When ${batch.label} is ordered` : `When ${batch.label} arrives`} />
      ) : null}
    </div>
  );
}

export function BatchesCard({ full, apply }: { full: PlanFull; apply: Apply }) {
  const narrow = useNarrow();
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const rows = full.schedule.batches;
  const open = rows.find((b) => b.id === openId);
  const bad = rows.filter((b) => b.conflict || b.closures.length || b.order_late_days).length;
  const cols: PlanColumn<PlanBatch>[] = [
    { key: "label", label: "Batch", width: 24, narrow: 50, get: (b) => b.label },
    { key: "project", label: "Project", width: 20, get: (b) => b.project },
    { key: "qty", label: "Boards", width: 10, numeric: true, get: (b) => b.qty, render: (b) => units(b.qty) },
    { key: "order", label: "Order", width: "104px", narrow: "104px", get: (b) => b.order_day, className: "mono" },
    { key: "arrival", label: "Arrival", width: "104px", get: (b) => b.arrival_day, className: "mono" },
    { key: "cost", label: "Cost", width: 14, numeric: true, get: (b) => b.cost ?? "",
      render: (b) => (b.cost != null ? `${Math.round(b.cost).toLocaleString()} ${b.cost_currency}` : "—") },
    { key: "state", label: "State", width: 16, narrow: 50,
      get: (b) => (b.conflict || b.closures.length ? "problem" : b.order_late_days ? "late" : b.status),
      render: (b) => b.conflict || b.closures.length
        ? <span className="pill err" title={[b.conflict, ...b.closures].join(" ")}>problem</span>
        : b.order_late_days ? <StatusPill status="late" title={`${b.order_late_days} days late`} />
          : <StatusPill status={b.status} /> },
    { key: "go", label: "", width: 16, interactive: false, get: () => "",
      render: (b) => <Link className="comp-link" to={`/production/batches/${b.id}`} onClick={(e) => e.stopPropagation()}>batch page</Link> },
  ];
  return (
    <FoldSection title="Planned batches" count={rows.length} foldKey={`plan-${full.plan.id}-batches`}
      chips={bad ? <StatChip n={bad} tone="err">with problems</StatChip> : null}
      actions={<button type="button" className="btn btn-sm btn-primary" onClick={() => setAdding(true)}>Plan a batch…</button>}>
      <DataTable columns={fitColumns(cols, narrow)} rows={rows} rowKey={(b) => b.id} onRowClick={(b) => setOpenId(b.id)} empty="No batches planned yet." />
      {adding ? <AddBatchDialog full={full} onClose={() => setAdding(false)} apply={apply} /> : null}
      {open ? <BatchDialog full={full} batch={open} onClose={() => setOpenId(null)} apply={apply} /> : null}
    </FoldSection>
  );
}

// ------------------------------------------------------------------ machining lots

function AddLotDialog({ full, onClose, apply }: { full: PlanFull; onClose: () => void; apply: Apply }) {
  const modal = useModal(onClose);
  const withRecipes = full.schedule.designs.filter((d) => d.recipes.length);
  const [projectId, setProjectId] = useState<number | null>(withRecipes[0]?.project_id ?? null);
  const recipes = full.schedule.designs.find((d) => d.project_id === projectId)?.recipes ?? [];
  const [recipe, setRecipe] = useState(recipes[0]?.key ?? "");
  const [label, setLabel] = useState("");
  const [qty, setQty] = useState(1000);
  const [rate, setRate] = useState<number | null>(recipes[0]?.rate_per_day ?? null);
  const [days, setDays] = useState<number | null>(null);
  const [start, setStart] = useState<StepValue>(FIXED_TODAY);
  const [busy, setBusy] = useState(false);
  const problem = projectId == null || !recipe ? "Choose a recipe." : !(qty > 0) ? "Enter the quantity." : stepProblem(start);
  const save = async () => {
    if (projectId == null) return;
    setBusy(true);
    const ok = await apply(`the machining lot ${label || recipe}`, () =>
      addPlanLot(full.plan.id, {
        project_id: projectId, recipe_key: recipe, label: label.trim(), qty,
        rate_per_day: days ? null : rate, duration_days: days, start: { ...stepBody(start), lag_unit: start.lag_unit },
      }));
    setBusy(false);
    if (ok) onClose();
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">Plan a machining lot</h2>
        <p className="muted dim">
          A lot makes a prepared part from its recipe: it needs the recipe&apos;s inputs on the start day
          and adds the output day by day at the rate, on working days.
        </p>
        {withRecipes.length ? null : (
          <div className="banner-warn">No design of the plan has a prepared-part recipe in its current process.</div>
        )}
        <FieldGrid>
          <Field label="Project">
            <select className="text" value={projectId ?? ""} onChange={(e) => {
              const pid = e.target.value ? Number(e.target.value) : null;
              setProjectId(pid);
              const r = full.schedule.designs.find((d) => d.project_id === pid)?.recipes[0];
              setRecipe(r?.key ?? "");
              setRate(r?.rate_per_day ?? null);
            }}>
              {withRecipes.map((d) => <option key={d.project_id} value={d.project_id}>{d.project}</option>)}
            </select>
          </Field>
          <Field label="Recipe">
            <select className="text" value={recipe} onChange={(e) => {
              setRecipe(e.target.value);
              setRate(recipes.find((r) => r.key === e.target.value)?.rate_per_day ?? null);
            }}>
              {recipes.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
            </select>
          </Field>
          <Field label="Name" hint="Empty: the recipe's name.">
            <input className="text" value={label} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label="Quantity">
            <NumberInput className="text" value={qty} onChange={setQty} />
          </Field>
          <Field label="Rate a working day" hint="Empty: the recipe's rate.">
            <NumberInput className="text" value={rate} onChange={setRate} onEmpty={() => setRate(null)} />
          </Field>
          <Field label="Or fixed working days">
            <NumberInput className="text" value={days} onChange={(v) => setDays(Math.round(v))} onEmpty={() => setDays(null)} />
          </Field>
        </FieldGrid>
        <h3 className="plan-sub">Start</h3>
        <StepFields value={start} onChange={setStart} options={refOptions(full)} fixedLabel="Start day" />
        <div className="btn-row modal-actions">
          {problem ? <StatChip tone="warn">{problem}</StatChip> : null}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !!problem} onClick={() => void save()}>
            Plan the lot
          </button>
        </div>
      </div>
    </div>
  );
}

function LotDialog({ full, lot, onClose, apply }: { full: PlanFull; lot: PlanLotRow; onClose: () => void; apply: Apply }) {
  const modal = useModal(onClose);
  const dialog = useDialog();
  const stored = full.lots.find((l) => l.id === lot.id);
  const [label, setLabel] = useState(stored?.label ?? lot.label);
  const [qty, setQty] = useState(lot.qty);
  const [rate, setRate] = useState<number | null>(stored?.rate_per_day ?? null);
  const [days, setDays] = useState<number | null>(stored?.duration_days ?? null);
  const [startOpen, setStartOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const startNode = lot.start_node_id ? full.nodes.find((n) => n.id === lot.start_node_id) : undefined;
  const save = async () => {
    setBusy(true);
    const ok = await apply(`the machining lot ${label}`, () =>
      updatePlanLot(lot.id, { label: label.trim(), qty, rate_per_day: rate, duration_days: days }));
    setBusy(false);
    if (ok) onClose();
  };
  const remove = async () => {
    const ok = await dialog.confirm(
      `Delete the machining lot ${lot.label} (${units(lot.qty)})? Its start date goes with it. History → Write batches can undo it.`,
      { title: "Delete machining lot", confirmLabel: "Delete", tone: "danger" },
    );
    if (!ok) return;
    if (await apply(`the deletion of ${lot.label}`, () => deletePlanLot(lot.id))) onClose();
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">Machining lot: {lot.label}</h2>
        {lot.unknown_recipe ? (
          <div className="banner-warn">The recipe {lot.recipe_key} is not in the project&apos;s current process.</div>
        ) : null}
        <p className="muted dim">
          {lot.start_day ? `Runs ${lot.start_day} to ${lot.end_day || "—"}` : "No start date"}
          {lot.workdays ? `, ${lot.workdays} working days.` : "."}
        </p>
        <FieldGrid>
          <Field label="Name">
            <input className="text" value={label} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label="Quantity">
            <NumberInput className="text" value={qty} onChange={setQty} />
          </Field>
          <Field label="Rate a working day" hint="Empty: the recipe's rate.">
            <NumberInput className="text" value={rate} onChange={setRate} onEmpty={() => setRate(null)} />
          </Field>
          <Field label="Or fixed working days">
            <NumberInput className="text" value={days} onChange={(v) => setDays(Math.round(v))} onEmpty={() => setDays(null)} />
          </Field>
        </FieldGrid>
        <div className="btn-row modal-actions">
          {startNode ? <button type="button" className="btn btn-sm" onClick={() => setStartOpen(true)}>Start date…</button> : null}
          <button type="button" className="btn btn-sm btn-danger" onClick={() => void remove()}>Delete…</button>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !(qty > 0)} onClick={() => void save()}>Save</button>
        </div>
      </div>
      {startOpen && startNode ? (
        <NodeEditor full={full} node={startNode} apply={apply} onClose={() => setStartOpen(false)} title={`When ${lot.label} starts`} />
      ) : null}
    </div>
  );
}

export function LotsCard({ full, apply }: { full: PlanFull; apply: Apply }) {
  const narrow = useNarrow();
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const rows = full.schedule.lots;
  const open = rows.find((l) => l.id === openId);
  const hasRecipes = full.schedule.designs.some((d) => d.recipes.length);
  if (!rows.length && !hasRecipes) return null;
  const cols: PlanColumn<PlanLotRow>[] = [
    { key: "label", label: "Lot", width: 24, narrow: 50, get: (l) => l.label },
    { key: "recipe", label: "Recipe", width: 18, get: (l) => l.recipe_key, className: "mono" },
    { key: "qty", label: "Quantity", width: 12, numeric: true, get: (l) => l.qty, render: (l) => units(l.qty) },
    { key: "rate", label: "A day", width: 10, numeric: true, get: (l) => l.rate_per_day ?? "" },
    { key: "days", label: "Working days", width: 14, numeric: true, get: (l) => l.workdays ?? "" },
    { key: "start", label: "Start", width: "104px", narrow: "104px", get: (l) => l.start_day, className: "mono" },
    { key: "end", label: "End", width: "104px", get: (l) => l.end_day, className: "mono" },
    { key: "state", label: "State", width: 22, narrow: 50, get: (l) => (l.unknown_recipe ? "no recipe" : l.late_days ? "late" : "planned"),
      render: (l) => l.unknown_recipe ? <span className="pill err">no recipe</span>
        : <StatusPill status={l.late_days ? "late" : "planned"} /> },
  ];
  return (
    <FoldSection title="Machining lots" count={rows.length} foldKey={`plan-${full.plan.id}-lots`}
      actions={hasRecipes ? <button type="button" className="btn btn-sm btn-primary" onClick={() => setAdding(true)}>Plan a lot…</button> : null}>
      <DataTable columns={fitColumns(cols, narrow)} rows={rows} rowKey={(l) => l.id} onRowClick={(l) => setOpenId(l.id)} empty="No machining lots yet." />
      {adding ? <AddLotDialog full={full} onClose={() => setAdding(false)} apply={apply} /> : null}
      {open ? <LotDialog full={full} lot={open} onClose={() => setOpenId(null)} apply={apply} /> : null}
    </FoldSection>
  );
}

// ------------------------------------------------------------------ milestones and closures

function AddNodeDialog({ full, kind, onClose, apply }: {
  full: PlanFull;
  kind: "milestone" | "closure";
  onClose: () => void;
  apply: Apply;
}) {
  const modal = useModal(onClose);
  const [label, setLabel] = useState("");
  const [step, setStep] = useState<StepValue>(FIXED_TODAY);
  const [endDay, setEndDay] = useState("");
  const [duration, setDuration] = useState<number | null>(null);
  const [party, setParty] = useState<PlanParty>(kind === "closure" ? "supplier" : "ours");
  const [source, setSource] = useState<PlanSource>("");
  const [sourceText, setSourceText] = useState("");
  const [busy, setBusy] = useState(false);
  const problem = !label.trim() ? "Name it." : stepProblem(step) || (kind === "closure" && !endDay ? "Choose the last day." : "");
  const save = async () => {
    setBusy(true);
    const ok = await apply(`the ${kind} ${label}`, () =>
      addPlanNode(full.plan.id, {
        kind, label: label.trim(), mode: step.mode, day: step.day, after: step.after, lag: step.lag,
        lag_unit: step.lag_unit, snap_weekday: step.snap_weekday, party, source, source_text: sourceText,
        ...(kind === "closure" ? { end_day: endDay } : { duration_days: duration }),
      }));
    setBusy(false);
    if (ok) onClose();
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">{kind === "closure" ? "Add a closure" : "Add a milestone"}</h2>
        <p className="muted dim">
          {kind === "closure"
            ? "A closure is a time a supplier does not work, such as Chinese New Year. A batch in production over it is a blocker."
            : "A milestone is a dated step with no record of its own: a layout, a prototype, a test. A late one of ours counts from today."}
        </p>
        <FieldGrid>
          <Field label="Name" wide>
            <input className="text" value={label} onChange={(e) => setLabel(e.target.value)} />
          </Field>
        </FieldGrid>
        <StepFields value={step} onChange={setStep} options={refOptions(full)} snap={kind === "milestone"}
          fixedLabel={kind === "closure" ? "First day" : "Day"} />
        <FieldGrid>
          {kind === "closure" ? (
            <Field label="Last day">
              <input className="text" type="date" value={endDay} onChange={(e) => setEndDay(e.target.value)} />
            </Field>
          ) : (
            <Field label="Takes (days)" hint="Leave empty for a single day.">
              <NumberInput className="text" value={duration} onChange={(v) => setDuration(Math.round(v))} onEmpty={() => setDuration(null)} />
            </Field>
          )}
          <Field label="Whose date">
            <select className="text" value={party} onChange={(e) => setParty(e.target.value as PlanParty)}>
              {PARTIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </Field>
          <Field label="Source">
            <select className="text" value={source} onChange={(e) => setSource(e.target.value as PlanSource)}>
              {SOURCES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="Source text">
            <input className="text" value={sourceText} maxLength={300} onChange={(e) => setSourceText(e.target.value)} />
          </Field>
        </FieldGrid>
        <div className="btn-row modal-actions">
          {problem ? <StatChip tone="warn">{problem}</StatChip> : null}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !!problem} onClick={() => void save()}>Add</button>
        </div>
      </div>
    </div>
  );
}

export function MilestonesCard({ full, apply }: { full: PlanFull; apply: Apply }) {
  const dialog = useDialog();
  const narrow = useNarrow();
  const [adding, setAdding] = useState<"milestone" | "closure" | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const rows = full.schedule.milestones;
  const node = openId != null ? full.nodes.find((n) => n.id === openId) : undefined;
  const late = rows.filter((m) => m.late_days || m.conflict).length;
  const remove = async (m: PlanMilestone) => {
    const ok = await dialog.confirm(`Delete the ${m.kind} "${m.label}"? History → Write batches can undo it.`,
      { title: `Delete ${m.kind}`, confirmLabel: "Delete", tone: "danger" });
    if (ok) await apply(`the deletion of ${m.label}`, () => deletePlanNode(m.id));
  };
  const cols: PlanColumn<PlanMilestone>[] = [
    { key: "label", label: "Name", width: 32, narrow: 40, get: (m) => m.label },
    { key: "kind", label: "Kind", width: 13, get: (m) => m.kind },
    { key: "day", label: "Day", width: "104px", narrow: "104px", get: (m) => m.day, className: "mono" },
    { key: "end", label: "Until", width: "104px", get: (m) => m.end_day, className: "mono" },
    { key: "party", label: "Whose", width: 13, get: (m) => m.party },
    { key: "source", label: "Source", width: 14, get: (m) => m.source || "—",
      title: (m) => m.source_text || m.source || undefined },
    { key: "state", label: "State", width: 22, narrow: 46,
      get: (m) => (m.conflict ? "conflict" : m.done ? "done" : m.late_days ? "late" : m.kind === "closure" ? "fixed" : "planned"),
      render: (m) => m.conflict ? <span className="pill err" title={m.conflict}>conflict</span>
        : <StatusPill status={m.done ? "done" : m.late_days ? "late" : m.kind === "closure" ? "fixed" : "planned"}
            title={m.late_days ? `${m.late_days} days late, planned ${m.planned}` : undefined} /> },
    { key: "del", label: "", width: 6, narrow: 14, interactive: false, className: "ctr", get: () => "",
      render: (m) => (
        <button type="button" className="row-del" title={`Delete ${m.label}`} aria-label={`Delete ${m.label}`}
          onClick={(e) => { e.stopPropagation(); void remove(m); }}>&#x2715;</button>
      ) },
  ];
  return (
    <FoldSection title="Milestones and closures" count={rows.length} foldKey={`plan-${full.plan.id}-milestones`}
      chips={late ? <StatChip n={late} tone="err">late or in conflict</StatChip> : null}
      actions={
        <span className="btn-row plan-actions">
          <button type="button" className="btn btn-sm btn-primary" onClick={() => setAdding("milestone")}>Add milestone…</button>
          <button type="button" className="btn btn-sm" onClick={() => setAdding("closure")}>Add closure…</button>
        </span>
      }>
      <DataTable columns={fitColumns(cols, narrow)} rows={rows} rowKey={(m) => m.id} onRowClick={(m) => setOpenId(m.id)}
        empty="No milestones or closures yet." />
      {adding ? <AddNodeDialog full={full} kind={adding} onClose={() => setAdding(null)} apply={apply} /> : null}
      {node ? <NodeEditor full={full} node={node} apply={apply} onClose={() => setOpenId(null)} /> : null}
    </FoldSection>
  );
}

// ------------------------------------------------------------------ customer-supplied parts

function CustomerPartDialog({ full, part, onClose, apply }: {
  full: PlanFull;
  part: PlanCustomerPartRow | null;
  onClose: () => void;
  apply: Apply;
}) {
  const modal = useModal(onClose);
  const dialog = useDialog();
  const [name, setName] = useState(part?.name ?? "");
  const [projectId, setProjectId] = useState<number | null>(part?.project_id ?? null);
  const [perUnit, setPerUnit] = useState<number>(part?.per_unit ?? 1);
  const [received, setReceived] = useState<number>(part?.received ?? 0);
  const [confirmed, setConfirmed] = useState(part?.confirmed ?? false);
  const [note, setNote] = useState(part?.note ?? "");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const body = { name: name.trim(), per_unit: perUnit, received, confirmed, note };
    const ok = await apply(`the customer part ${name}`, () =>
      part ? updatePlanCustomerPart(part.id, body) : addPlanCustomerPart(full.plan.id, { ...body, project_id: projectId }));
    setBusy(false);
    if (ok) onClose();
  };
  const remove = async () => {
    if (!part) return;
    const ok = await dialog.confirm(`Delete the customer part ${part.name}? History → Write batches can undo it.`,
      { title: "Delete customer part", confirmLabel: "Delete", tone: "danger" });
    if (!ok) return;
    if (await apply(`the deletion of ${part.name}`, () => deletePlanCustomerPart(part.id))) onClose();
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">{part ? `Customer part: ${part.name}` : "Add a part the customer supplies"}</h2>
        <p className="muted dim">
          A part the customer supplies, such as SIM cards, must arrive before the units that need it are built.
        </p>
        <FieldGrid>
          <Field label="Name">
            <input className="text" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Project" hint={part ? "Fixed once added." : "Empty: every project of the plan."}>
            <select className="text" value={projectId ?? ""} disabled={!!part}
              onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">every project</option>
              {full.plan.projects.map((d) => <option key={d.project_id} value={d.project_id}>{d.project}</option>)}
            </select>
          </Field>
          <Field label="Per unit">
            <NumberInput className="text" value={perUnit} onChange={setPerUnit} />
          </Field>
          <Field label="Received so far">
            <NumberInput className="text" value={received} onChange={setReceived} />
          </Field>
          <Field label="Note" wide>
            <input className="text" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
        <CheckField checked={confirmed} onChange={setConfirmed}>The customer confirmed the dates</CheckField>
        <div className="btn-row modal-actions">
          {part ? <button type="button" className="btn btn-sm btn-danger" onClick={() => void remove()}>Delete…</button> : null}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !name.trim()} onClick={() => void save()}>
            {part ? "Save" : "Add"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function CustomerPartsCard({ full, apply }: { full: PlanFull; apply: Apply }) {
  const [open, setOpen] = useState<PlanCustomerPartRow | "new" | null>(null);
  const narrow = useNarrow();
  const rows = full.schedule.customer_parts;
  const project = new Map(full.plan.projects.map((p) => [p.project_id, p.project]));
  const unconfirmed = rows.filter((r) => !r.confirmed).length;
  const cols: PlanColumn<PlanCustomerPartRow>[] = [
    { key: "name", label: "Part", width: 20, narrow: 45, get: (r) => r.name },
    { key: "project", label: "Project", width: 14, get: (r) => (r.project_id ? project.get(r.project_id) ?? `#${r.project_id}` : "every project") },
    { key: "per", label: "Per unit", width: 9, numeric: true, get: (r) => r.per_unit },
    { key: "received", label: "Received", width: 10, numeric: true, get: (r) => r.received, render: (r) => units(r.received) },
    { key: "next", label: "Next need", width: 21, narrow: 55,
      get: (r) => (r.next_need ? `${units(r.next_need.cumulative)} by ${r.next_need.need_day}` : "covered") },
    { key: "confirmed", label: "Dates", width: 16, get: (r) => (r.confirmed ? "confirmed" : "not confirmed"),
      render: (r) => (r.confirmed ? <span className="pill ok">confirmed</span> : <span className="pill warn">not confirmed</span>) },
    { key: "note", label: "Note", width: 10, get: (r) => r.note, className: "muted" },
  ];
  return (
    <FoldSection title="Parts the customer supplies" count={rows.length} foldKey={`plan-${full.plan.id}-cparts`}
      chips={unconfirmed ? <StatChip n={unconfirmed} tone="warn">dates not confirmed</StatChip> : null}
      actions={<button type="button" className="btn btn-sm" onClick={() => setOpen("new")}>Add…</button>}>
      <DataTable columns={fitColumns(cols, narrow)} rows={rows} rowKey={(r) => r.id} onRowClick={(r) => setOpen(r)}
        empty="None. Add a part the customer sends, such as SIM cards." />
      {open ? (
        <CustomerPartDialog full={full} part={open === "new" ? null : open} onClose={() => setOpen(null)} apply={apply} />
      ) : null}
    </FoldSection>
  );
}
