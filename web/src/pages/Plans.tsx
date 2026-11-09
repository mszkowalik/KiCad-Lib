/** Sales → Plans (decision 0107): one row for each plan of a customer contract,
 *  with what blocks it. A plan owns draft orders, planned batches, draft
 *  purchases and dates; its page computes all of them on read. */
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createPlan, errorMessage, listCustomers, listPlans, type PlanIn, type PlanRow } from "../api";
import DataTable from "../components/DataTable";
import Field, { FieldGrid } from "../components/Field";
import { NarrowChip } from "../components/FoldSection";
import { useModal } from "../components/modal";
import NumberInput from "../components/NumberInput";
import PageShell from "../components/PageShell";
import SiInput from "../components/SiInput";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { useLoad } from "../components/useLoad";
import { fitColumns, useNarrow, WEEKDAY_NAMES, type PlanColumn } from "../components/plan/planUtil";
import { localDate, plural } from "../format";

function Count({ n, tone, word }: { n: number | undefined; tone: "err" | "warn" | "acc"; word: string }) {
  if (!n) return null;
  return <span className={`pill ${tone === "acc" ? "neutral" : tone}`} title={`${n} ${word}`}>{n}</span>;
}

function NewPlanDialog({ onClose }: { onClose: () => void }) {
  const modal = useModal(onClose);
  const navigate = useNavigate();
  const customers = useLoad(listCustomers, []).data ?? [];
  const [name, setName] = useState("");
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [currency, setCurrency] = useState("PLN");
  const [vat, setVat] = useState(23);
  const [advance, setAdvance] = useState(60);
  const [advanceDays, setAdvanceDays] = useState<number | null>(null);
  const [finalDays, setFinalDays] = useState(14);
  const [leadMonths, setLeadMonths] = useState(2);
  const [limit, setLimit] = useState<number | null>(null);
  const [weekday, setWeekday] = useState<number | null>(null);
  const [buildLead, setBuildLead] = useState(7);
  const [attrition, setAttrition] = useState(2);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const terms = customers.find((c) => c.id === customerId)?.payment_terms_days;
  const create = async () => {
    const body: PlanIn = {
      name: name.trim(), customer_id: customerId, currency: currency.trim().toUpperCase() || "PLN", vat_pct: vat,
      advance_pct: advance, final_days: finalDays, min_lead_months: leadMonths, advance_limit_net: limit,
      delivery_weekday: weekday, build_lead_days: buildLead, attrition_pct: attrition,
      ...(advanceDays != null ? { advance_days: advanceDays } : {}),
    };
    setBusy(true);
    setError(null);
    try {
      const full = await createPlan(body);
      navigate(`/sales/plans/${full.plan.id}?tab=setup`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">New plan</h2>
        <p className="muted dim">
          The terms of one customer contract. Its designs, orders and batches are added on the plan&apos;s
          Setup tab. History → Write batches undoes the creation.
        </p>
        <ErrorBanner message={error} />
        <FieldGrid>
          <Field label="Name" wide>
            <input className="text" value={name} maxLength={200} placeholder="e.g. CE 2027" onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Customer">
            <select className="text" value={customerId ?? ""} onChange={(e) => setCustomerId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Choose…</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Currency">
            <input className="text" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
          </Field>
          <Field label="VAT">
            <SiInput quantity="percent" value={vat} onChange={setVat} />
          </Field>
          <Field label="Advance share">
            <SiInput quantity="percent" value={advance} onChange={setAdvance} />
          </Field>
          <Field label="Advance due after (days)" hint={terms != null ? `Empty: the customer's terms, ${terms} days.` : "Empty: the customer's terms."}>
            <NumberInput className="text" value={advanceDays} min={0} onChange={(v) => setAdvanceDays(Math.round(v))}
              onEmpty={() => setAdvanceDays(null)} />
          </Field>
          <Field label="Final invoice due after (days)">
            <NumberInput className="text" value={finalDays} min={0} onChange={(v) => setFinalDays(Math.round(v))} />
          </Field>
          <Field label="Months from advance to first delivery">
            <NumberInput className="text" value={leadMonths} min={0} onChange={(v) => setLeadMonths(Math.round(v))} />
          </Field>
          <Field label={`Advance limit per due date (net ${currency || "PLN"})`} hint="Empty: no limit.">
            <NumberInput className="text" value={limit} min={0} onChange={setLimit} onEmpty={() => setLimit(null)} />
          </Field>
          <Field label="Delivery weekday">
            <select className="text" value={weekday ?? ""} onChange={(e) => setWeekday(e.target.value === "" ? null : Number(e.target.value))}>
              <option value="">any day</option>
              {WEEKDAY_NAMES.map((w, i) => <option key={w} value={i}>{w}</option>)}
            </select>
          </Field>
          <Field label="Build lead (days)" hint="A unit leaves the line this long before its delivery.">
            <NumberInput className="text" value={buildLead} min={0} onChange={(v) => setBuildLead(Math.round(v))} />
          </Field>
          <Field label="Attrition" hint="Added to every part a batch needs.">
            <SiInput quantity="percent" value={attrition} onChange={setAttrition} />
          </Field>
        </FieldGrid>
        <div className="btn-row modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !name.trim() || customerId == null}
            onClick={() => void create()}>
            Create the plan
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Plans() {
  const { data: plans, error } = useLoad(listPlans, []);
  const [creating, setCreating] = useState(false);
  const [narrow, setNarrow] = useState<"" | "blocked" | "draft">("");
  const navigate = useNavigate();
  const small = useNarrow();
  const rows = (plans ?? []).filter((p) =>
    narrow === "blocked" ? (p.attention?.counts.block ?? 0) > 0 : narrow === "draft" ? p.status === "draft" : true);
  const cols: PlanColumn<PlanRow>[] = [
    { key: "name", label: "Plan", width: 28, narrow: 62, get: (p) => p.name,
      render: (p) => <Link className="comp-link" to={`/sales/plans/${p.id}`} onClick={(e) => e.stopPropagation()}>{p.name}</Link> },
    { key: "customer", label: "Customer", width: 20, get: (p) => p.customer || "—" },
    { key: "status", label: "Status", width: 11, narrow: "86px", get: (p) => p.status, render: (p) => <StatusPill status={p.status} /> },
    { key: "orders", label: "Orders", width: 9, numeric: true, get: (p) => p.orders ?? 0 },
    { key: "block", label: "Blocking", width: 10, narrow: 38, numeric: true, get: (p) => p.attention?.counts.block ?? 0,
      render: (p) => <Count n={p.attention?.counts.block} tone="err" word="blocking" /> },
    { key: "risk", label: "At risk", width: 10, numeric: true, get: (p) => p.attention?.counts.risk ?? 0,
      render: (p) => <Count n={p.attention?.counts.risk} tone="warn" word="at risk" /> },
    { key: "decide", label: "Decide", width: 10, numeric: true, get: (p) => p.attention?.counts.decide ?? 0,
      render: (p) => <Count n={p.attention?.counts.decide} tone="acc" word="wait for a decision" /> },
    { key: "created", label: "Created", width: "104px", get: (p) => localDate(p.created_at), className: "mono" },
  ];
  const blocked = (plans ?? []).filter((p) => (p.attention?.counts.block ?? 0) > 0).length;
  const failed = (plans ?? []).filter((p) => p.attention?.error);
  return (
    <PageShell>
      <div className="toolbar">
        <h1>Plans</h1>
        <span className="toolbar-total">{plans ? plural(plans.length, "plan") : ""}</span>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>New plan…</button>
      </div>
      <ErrorBanner message={error} />
      {failed.map((p) => (
        <div key={p.id} className="banner-error">The plan {p.name} could not be computed: {p.attention?.error}</div>
      ))}
      <div className="card pad">
        <h2 className="card-title">Contract plans</h2>
        <p className="muted dim">
          A plan holds the draft orders, planned batches and purchases of one customer contract, with
          every date computed from the dates it follows. Click a plan for its blockers and timeline.
        </p>
        {plans === null ? (
          <Spinner label="Loading the plans…" />
        ) : (
          <>
            <div className="stat-row">
              <NarrowChip value="blocked" current={narrow} onNarrow={setNarrow} n={blocked} tone={blocked ? "err" : undefined}>with blockers</NarrowChip>
              <NarrowChip value="draft" current={narrow} onNarrow={setNarrow} n={plans.filter((p) => p.status === "draft").length} tone="warn">
                not sent
              </NarrowChip>
            </div>
            <DataTable columns={fitColumns(cols, small)} rows={rows} rowKey={(p) => p.id} onRowClick={(p) => navigate(`/sales/plans/${p.id}`)}
              empty="No plan yet. Create one for a customer contract." />
          </>
        )}
      </div>
      {creating ? <NewPlanDialog onClose={() => setCreating(false)} /> : null}
    </PageShell>
  );
}
