/** The Setup tab of a plan (decision 0107): the contract parameters, the
 *  designs the plan builds from, and the records it owns — orders, batches,
 *  lots, milestones and the parts the customer supplies. Deleting the plan is
 *  at the bottom, behind a list of what goes and what stays. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  deletePlan,
  errorMessage,
  getSnapshots,
  listCustomers,
  markPlanReviewed,
  setPlanProjects,
  updatePlan,
  type PlanFull,
  type PlanIn,
  type PlanProjectRow,
  type PlanRow,
  type ProjectInfo as ApiProject,
} from "../../api";
import { plural } from "../../format";
import AutoTextarea from "../AutoTextarea";
import { useDialog } from "../Dialog";
import Field, { FieldGrid } from "../Field";
import { StatChip } from "../FoldSection";
import NumberInput from "../NumberInput";
import SiInput from "../SiInput";
import { useLoad } from "../useLoad";
import { OrdersCard } from "./PlanOrders";
import { BatchesCard, CustomerPartsCard, LotsCard, MilestonesCard } from "./PlanWork";
import { WEEKDAY_NAMES, type Apply } from "./planUtil";

// ------------------------------------------------------------------ parameters

type Params = Required<Pick<PlanRow, "name" | "customer_id" | "status" | "sent_on" | "agreed_on" | "currency" | "vat_pct"
  | "advance_pct" | "advance_days" | "final_days" | "min_lead_months" | "advance_limit_net" | "delivery_weekday"
  | "build_lead_days" | "attrition_pct" | "notes">>;

const PARAM_KEYS: (keyof Params)[] = ["name", "customer_id", "status", "sent_on", "agreed_on", "currency", "vat_pct",
  "advance_pct", "advance_days", "final_days", "min_lead_months", "advance_limit_net", "delivery_weekday",
  "build_lead_days", "attrition_pct", "notes"];

const paramsOf = (p: PlanRow): Params =>
  Object.fromEntries(PARAM_KEYS.map((k) => [k, p[k]])) as Params;

function ParamsCard({ full, apply }: { full: PlanFull; apply: Apply }) {
  const customers = useLoad(listCustomers, []).data ?? [];
  const [v, setV] = useState<Params>(() => paramsOf(full.plan));
  useEffect(() => setV(paramsOf(full.plan)), [full.plan]);
  const set = <K extends keyof Params>(k: K, x: Params[K]) => setV((o) => ({ ...o, [k]: x }));
  const changed = PARAM_KEYS.filter((k) => v[k] !== full.plan[k]);
  const save = () => {
    const body: PlanIn = {};
    for (const k of changed) (body as Record<string, unknown>)[k] = typeof v[k] === "string" ? (v[k] as string).trim() : v[k];
    if (body.currency) body.currency = body.currency.toUpperCase();
    return apply("the plan's parameters", () => updatePlan(full.plan.id, body));
  };
  return (
    <div className="card pad edit-card">
      <h2 className="card-title">Contract</h2>
      <p className="muted dim">
        The terms every order of the plan follows. A change moves the computed dates and amounts at
        once. Nothing is copied.
      </p>
      <FieldGrid>
        <Field label="Name">
          <input className="text" value={v.name} maxLength={200} onChange={(e) => set("name", e.target.value)} />
        </Field>
        <Field label="Customer">
          <select className="text" value={v.customer_id ?? ""}
            onChange={(e) => set("customer_id", e.target.value ? Number(e.target.value) : null)}>
            <option value="">—</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Status" hint="Draft until it goes to the customer.">
          <select className="text" value={v.status} onChange={(e) => set("status", e.target.value as Params["status"])}>
            <option value="draft">draft</option>
            <option value="sent">sent to the customer</option>
            <option value="agreed">agreed</option>
          </select>
        </Field>
        {v.status !== "draft" ? (
          <Field label="Sent on" hint="Empty: today, on save.">
            <input className="text" type="date" value={v.sent_on} onChange={(e) => set("sent_on", e.target.value)} />
          </Field>
        ) : null}
        {v.status === "agreed" ? (
          <Field label="Agreed on" hint="Empty: today, on save.">
            <input className="text" type="date" value={v.agreed_on} onChange={(e) => set("agreed_on", e.target.value)} />
          </Field>
        ) : null}
        <Field label="Currency">
          <input className="text" value={v.currency} maxLength={3} onChange={(e) => set("currency", e.target.value.toUpperCase())} />
        </Field>
        <Field label="VAT">
          <SiInput quantity="percent" value={v.vat_pct} onChange={(x) => set("vat_pct", x)} />
        </Field>
        <Field label="Advance share">
          <SiInput quantity="percent" value={v.advance_pct} onChange={(x) => set("advance_pct", x)} />
        </Field>
        <Field label="Advance due after (days)" hint="From the order date.">
          <NumberInput className="text" value={v.advance_days} min={0} onChange={(x) => set("advance_days", Math.round(x))} />
        </Field>
        <Field label="Final invoice due after (days)" hint="From the last delivery.">
          <NumberInput className="text" value={v.final_days} min={0} onChange={(x) => set("final_days", Math.round(x))} />
        </Field>
        <Field label="Months from advance to first delivery" hint="At least this many.">
          <NumberInput className="text" value={v.min_lead_months} min={0} onChange={(x) => set("min_lead_months", Math.round(x))} />
        </Field>
        <Field label={`Advance limit per due date (net ${v.currency})`} hint="Empty: no limit.">
          <NumberInput className="text" value={v.advance_limit_net} min={0}
            onChange={(x) => set("advance_limit_net", x)} onEmpty={() => set("advance_limit_net", null)} />
        </Field>
        <Field label="Delivery weekday" hint="A delivery after the advance moves to the next one.">
          <select className="text" value={v.delivery_weekday ?? ""}
            onChange={(e) => set("delivery_weekday", e.target.value === "" ? null : Number(e.target.value))}>
            <option value="">any day</option>
            {WEEKDAY_NAMES.map((w, i) => <option key={w} value={i}>{w}</option>)}
          </select>
        </Field>
        <Field label="Build lead (days)" hint="A unit leaves the line this long before its delivery.">
          <NumberInput className="text" value={v.build_lead_days} min={0} onChange={(x) => set("build_lead_days", Math.round(x))} />
        </Field>
        <Field label="Attrition" hint="Added to every part a batch needs.">
          <SiInput quantity="percent" value={v.attrition_pct} onChange={(x) => set("attrition_pct", x)} />
        </Field>
        <Field label="Notes" wide>
          <AutoTextarea className="text" value={v.notes} onChange={(e) => set("notes", e.target.value)} />
        </Field>
      </FieldGrid>
      <div className="btn-row">
        <button type="button" className="btn btn-primary btn-sm" disabled={!changed.length || !v.name.trim()} onClick={() => void save()}>
          Save
        </button>
        <button type="button" className="btn btn-sm" disabled={!changed.length} onClick={() => setV(paramsOf(full.plan))}>
          Cancel
        </button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ designs

type DesignIn = Omit<PlanProjectRow, "id" | "project">;

const designOf = (p: PlanProjectRow): DesignIn => ({
  project_id: p.project_id,
  snapshot_mode: p.snapshot_mode,
  snapshot_id: p.snapshot_id,
  branch: p.branch,
  board: p.board,
  variant: p.variant,
  line_rate_week: p.line_rate_week,
});

function DesignRow({ row, projects, onChange, onRemove }: {
  row: DesignIn;
  projects: ApiProject[];
  onChange: (r: DesignIn) => void;
  onRemove: () => void;
}) {
  const { data: snaps } = useLoad((signal) => getSnapshots(row.project_id, signal), [row.project_id],
    { enabled: row.project_id > 0 });
  const ready = (snaps ?? []).filter((s) => s.status === "ready");
  const branches = [...new Set(ready.filter((s) => !s.is_tag).map((s) => s.ref_name))];
  const snap = row.snapshot_mode === "fixed"
    ? ready.find((s) => s.id === row.snapshot_id)
    : ready.find((s) => !s.is_tag && s.ref_name === (row.branch || "main"));
  const boards = (snap?.boards ?? []).filter((b) => (b.kind ?? "board") === "board").map((b) => b.name);
  const set = (p: Partial<DesignIn>) => onChange({ ...row, ...p });
  return (
    <div className="plan-design-row">
      <Field label="Project">
        <select className="text" value={row.project_id || ""}
          onChange={(e) => set({ project_id: Number(e.target.value), snapshot_id: null, board: "" })}>
          <option value="">Choose…</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </Field>
      <Field label="Design">
        <select className="text" value={row.snapshot_mode}
          onChange={(e) => set({ snapshot_mode: e.target.value as DesignIn["snapshot_mode"] })}>
          <option value="fixed">one snapshot</option>
          <option value="branch">follow a branch</option>
        </select>
      </Field>
      {row.snapshot_mode === "fixed" ? (
        <Field label="Snapshot">
          <select className="text" value={row.snapshot_id ?? ""}
            onChange={(e) => set({ snapshot_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">Choose…</option>
            {ready.map((s) => (
              <option key={s.id} value={s.id}>{s.ref_name} · {s.sha.slice(0, 8)}{s.is_tag ? " (tag)" : ""}</option>
            ))}
          </select>
        </Field>
      ) : (
        <Field label="Branch" hint="The newest ready snapshot of it.">
          <input className="text" list={`plan-branches-${row.project_id}`} value={row.branch}
            placeholder="main" onChange={(e) => set({ branch: e.target.value })} />
          <datalist id={`plan-branches-${row.project_id}`}>
            {branches.map((b) => <option key={b} value={b} />)}
          </datalist>
        </Field>
      )}
      <Field label="Board">
        <select className="text" value={row.board} onChange={(e) => set({ board: e.target.value })}>
          <option value="">{boards[0] ? `${boards[0]} (the first)` : "the first board"}</option>
          {boards.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
      </Field>
      <Field label="Variant">
        <input className="text" value={row.variant} onChange={(e) => set({ variant: e.target.value })} />
      </Field>
      <Field label="Line rate a week">
        <NumberInput className="text" value={row.line_rate_week} min={0}
          onChange={(x) => set({ line_rate_week: Math.round(x) })} onEmpty={() => set({ line_rate_week: null })} />
      </Field>
      <button type="button" className="row-del" title="Remove this design" aria-label="Remove this design" onClick={onRemove}>
        &#x2715;
      </button>
    </div>
  );
}

function DesignsCard({ full, projects, apply }: { full: PlanFull; projects: ApiProject[]; apply: Apply }) {
  const [rows, setRows] = useState<DesignIn[]>(() => full.plan.projects.map(designOf));
  useEffect(() => setRows(full.plan.projects.map(designOf)), [full.plan.projects]);
  const dirty = JSON.stringify(rows) !== JSON.stringify(full.plan.projects.map(designOf));
  const problem = rows.some((r) => !r.project_id)
    ? "Choose a project on each row."
    : rows.some((r) => r.snapshot_mode === "fixed" && !r.snapshot_id)
      ? "Choose a snapshot on each fixed design."
      : new Set(rows.map((r) => r.project_id)).size !== rows.length
        ? "A project can be in the plan once."
        : "";
  const unreviewed = full.schedule.changes.filter((c) => c.first);
  const changed = full.schedule.changes.filter((c) => !c.first);
  return (
    <div className="card pad edit-card">
      <h2 className="card-title">Designs</h2>
      <p className="muted dim">
        The design of each project the plan builds: one snapshot, or the newest of a branch. A planned
        batch takes it, with the project&apos;s current process. An ordered batch keeps the design it
        was ordered with. The line rate is the units the line makes in a week. Leave it empty for no check.
      </p>
      {rows.map((r, i) => (
        <DesignRow key={i} row={r} projects={projects}
          onChange={(x) => setRows(rows.map((y, j) => (j === i ? x : y)))}
          onRemove={() => setRows(rows.filter((_, j) => j !== i))} />
      ))}
      <div className="btn-row">
        <button type="button" className="btn btn-sm"
          onClick={() => setRows([...rows, { project_id: 0, snapshot_mode: "fixed", snapshot_id: null, branch: "", board: "", variant: "", line_rate_week: null }])}>
          Add a project
        </button>
        <button type="button" className="btn btn-sm btn-primary" disabled={!dirty || !!problem}
          onClick={() => void apply("the plan's designs", () => setPlanProjects(full.plan.id, rows))}>
          Save the designs
        </button>
        {dirty ? <button type="button" className="btn btn-sm" onClick={() => setRows(full.plan.projects.map(designOf))}>Cancel</button> : null}
        {dirty && problem ? <StatChip tone="warn">{problem}</StatChip> : null}
      </div>
      {full.schedule.designs.length ? (
        <>
          <h3 className="plan-sub">What the plan builds now</h3>
          {full.schedule.designs.map((d) => (
            <div key={d.project_id} className="plan-design-sum">
              <b>{d.project}</b>
              <span className="mono">{d.snapshot_ref || "no snapshot"}{d.snapshot_sha ? ` · ${d.snapshot_sha}` : ""}</span>
              <span>board {d.board || "—"}{d.variant ? `, variant ${d.variant}` : ""}</span>
              <span>{d.process_version_no != null ? `process v${d.process_version_no}` : "no published process"}</span>
              <span>{d.bom_lines} BOM lines, {d.step_inputs} step inputs</span>
              {d.recipes.length ? (
                <span>recipes: {d.recipes.map((r) => `${r.label}${r.rate_per_day ? ` (${r.rate_per_day} a day)` : ""}`).join(", ")}</span>
              ) : null}
              {d.warnings.map((w) => <span key={w} className="pill warn">{w}</span>)}
            </div>
          ))}
        </>
      ) : null}
      {unreviewed.length || changed.length ? (
        <div className="btn-row">
          <span className="muted">
            {changed.length
              ? "A design input changed since the last review. The Overview shows the difference."
              : "Nobody has marked these inputs reviewed. Do it once, and a later change of snapshot or process shows on the Overview."}
          </span>
          <button type="button" className="btn btn-sm"
            onClick={() => void apply("the design review", () => markPlanReviewed(full.plan.id))}>
            Mark reviewed
          </button>
        </div>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ delete

function DangerCard({ full }: { full: PlanFull }) {
  const dialog = useDialog();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const dry = await deletePlan(full.plan.id, true);
      const d = dry.delete;
      const k = dry.keep;
      const list = (xs: string[]) => (xs.length > 8 ? `${xs.slice(0, 8).join(", ")} and ${xs.length - 8} more` : xs.join(", "));
      const goes = [
        d.draft_orders.length ? `${plural(d.draft_orders.length, "draft order")} (${list(d.draft_orders.map((o) => o.key || `#${o.id}`))})` : "",
        d.planned_batches.length ? `${plural(d.planned_batches.length, "planned batch", "planned batches")} (${list(d.planned_batches.map((b) => b.label))})` : "",
        d.draft_purchase_orders.length ? plural(d.draft_purchase_orders.length, "draft purchase order") : "",
        d.reservations ? plural(d.reservations, "reservation") : "",
        d.lots ? plural(d.lots, "machining lot") : "",
        d.customer_parts ? plural(d.customer_parts, "customer part") : "",
        d.nodes ? plural(d.nodes, "date") : "",
      ].filter(Boolean);
      const stays = [
        k.orders.length ? `${plural(k.orders.length, "confirmed order")} (${list(k.orders.map((o) => o.key || `#${o.id}`))})` : "",
        k.batches.length ? `${plural(k.batches.length, "ordered batch", "ordered batches")} (${list(k.batches.map((b) => b.label))})` : "",
        k.purchase_orders.length ? plural(k.purchase_orders.length, "placed purchase order") : "",
      ].filter(Boolean);
      // The dialog prints one paragraph, so this is sentences, not a list.
      const msg = `Delete the plan "${full.plan.name}"? It deletes ${goes.length ? goes.join(", ") : "the plan only"}.`
        + (stays.length ? ` These stay, without their link to the plan: ${stays.join(", ")}.` : "")
        + " Stock stays where it is. History → Write batches can undo the delete.";
      setBusy(false);
      const ok = await dialog.confirm(msg, { title: "Delete plan", confirmLabel: "Delete the plan", tone: "danger" });
      if (!ok) return;
      setBusy(true);
      await deletePlan(full.plan.id, false);
      navigate("/sales/plans");
    } catch (err) {
      setBusy(false);
      await dialog.alert(errorMessage(err), { title: "The plan was not deleted" });
    }
  };
  return (
    <div className="card pad danger-card">
      <h2 className="card-title">Delete the plan</h2>
      <p className="muted dim">
        Deletes the plan and what it owns: draft orders, planned batches, draft purchase orders,
        reservations and dates. Confirmed orders, ordered batches and placed purchases stay. You see the
        list before anything goes.
      </p>
      <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={() => void run()}>
        Delete plan…
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ the tab

export default function PlanSetup({ full, projects, apply, onOrder }: {
  full: PlanFull;
  projects: ApiProject[];
  apply: Apply;
  onOrder: (orderId: number) => void;
}) {
  return (
    <>
      <ParamsCard full={full} apply={apply} />
      <DesignsCard full={full} projects={projects} apply={apply} />
      <OrdersCard full={full} projects={projects} apply={apply} onOpen={onOrder} />
      <BatchesCard full={full} apply={apply} />
      <LotsCard full={full} apply={apply} />
      <MilestonesCard full={full} apply={apply} />
      <CustomerPartsCard full={full} apply={apply} />
      <DangerCard full={full} />
    </>
  );
}
