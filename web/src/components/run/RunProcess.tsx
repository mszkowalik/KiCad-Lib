/** Batch → Process: crafting a batch step by step (decision 0059).
 *
 *  A crafted batch starts empty. "Receive boards" makes one unit (a twin) per
 *  board; every later step is a click on N units, with a dry run first.
 *
 *  - Before programming, units are taken from a STACK — "N from this pile",
 *    never one unit by its id, because nothing on an unprogrammed board says
 *    which one it is.
 *  - After programming, units are DEVICES, chosen by scanning their label or
 *    MAC, or by ticking them in the list. Each step records which of the two:
 *    a scan is an observation, a tick is a person's statement.
 *  - Programming and marking are done at their benches, which read the device.
 *    A device programmed with no stack selected is a GAP; a merge gives it a
 *    unit from a stack.
 *  - "Finished" is the last step, done here, and it refuses a device that
 *    misses a required step.
 *  - The board's assembly at the supplier is a step too (decision 0060),
 *    recorded from the batch's assembly order when the boards are received.
 *    Any other invoice position of the batch can be linked to the step click
 *    it paid for; what no step claims stays in the origin batch cost.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  craftAssembly,
  craftCosts,
  craftFinish,
  craftFound,
  craftMerge,
  craftReceive,
  craftScrap,
  craftStep,
  errorMessage,
  getCostByStep,
  getCraft,
  getRuns,
  isAbortError,
  setBenchStack,
  STEP_STATION,
  type CraftClick,
  type CraftDevice,
  type CraftStack,
  type CostByStep,
  type CraftView,
  type RunInfo,
  type StepPlan,
} from "../../api";
import { usd } from "../../format";
import AutoTextarea from "../AutoTextarea";
import DataTable, { type Column } from "../DataTable";
import { useDialog } from "../Dialog";
import Field, { CheckField, FieldGrid } from "../Field";
import NumberInput from "../NumberInput";
import { today } from "../process/MakeDialog";
import { DryRunDialog } from "../process/StageDialogs";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";

type Target = { kind: "stack"; stack: CraftStack } | { kind: "devices"; ids: number[]; chosen: "scanned" | "list" };

/** A stack in words: the steps its units have done, and the lots they used. */
function stackText(s: CraftStack, label: (k: string) => string): string {
  const done = s.done.map(label).join(" + ");
  return s.lots.length ? `${done} (lots ${s.lots.join(", ")})` : done;
}

function StepDialog({ run, view, target, onClose }: {
  run: RunInfo; view: CraftView; target: Target; onClose: (changed: boolean) => void;
}) {
  const steps = view.graph.steps.filter((s) => s.kind === "step");
  const allowed = target.kind === "stack" ? new Set(target.stack.can ?? []) : null;
  const choices = steps.filter((s) => !allowed || allowed.has(s.key));
  const [stepKey, setStepKey] = useState(choices[0]?.key ?? "");
  const [qty, setQty] = useState<number | null>(target.kind === "stack" ? target.stack.count : null);
  const [madeAt, setMadeAt] = useState(today());
  const [note, setNote] = useState("");
  const [lots, setLots] = useState<Record<string, number>>({});
  const step = steps.find((s) => s.key === stepKey);
  const preparedInputs = (step?.inputs ?? []).filter((i) => view.parts[String(i.component_id)]?.internal);
  const body = (dry: boolean) => ({
    step_key: stepKey, made_at: madeAt, note, dry_run: dry,
    lots: Object.keys(lots).length ? lots : null,
    ...(target.kind === "stack"
      ? { stack: target.stack.stack, qty: qty ?? 0 }
      : { device_ids: target.ids, chosen: target.chosen }),
  });
  return (
    <DryRunDialog<StepPlan>
      title="Run a step"
      intro={target.kind === "stack"
        ? `On units from the stack “${stackText(target.stack, (k) => view.graph.steps.find((s) => s.key === k)?.label || k)}”.`
        : `On ${target.ids.length} device(s), ${target.chosen === "scanned" ? "scanned" : "picked from the list"}.`}
      onClose={onClose}
      run={(dry) => craftStep(run.id, body(dry))}
      describe={(p) => (
        <>
          {p.refused.length ? (
            <span className="banner-error">
              Refused: {p.refused.map((r) => `${r.unit} — ${r.why.join(", ")}`).join("; ")}
            </span>
          ) : null}
          {p.shortages.length ? (
            <span className="banner-error">Not in stock: {p.shortages.map((s) => `${s.label} (${s.short} short)`).join(", ")}</span>
          ) : null}
          {p.problems.length ? (
            <span className="banner-error">{p.problems.map((x) => `${x.name}: ${x.problem}`).join("; ")}</span>
          ) : null}
          {p.units} unit(s) take {p.draws.length ? p.draws.map((d) => `${d.qty} × ${d.name}${d.lot_adjustment_id ? ` (lot A${d.lot_adjustment_id})` : ""}`).join(", ") : "no parts"}
          {p.draws.length ? <> — {usd(p.value_usd)}, {usd(p.per_unit_usd, 4)} per unit, charged to {run.label}.</> : "."}
        </>
      )}
      fields={
        <FieldGrid>
          <Field label="Step">
            <select className="text" value={stepKey} onChange={(e) => { setStepKey(e.target.value); setLots({}); }}>
              {choices.map((s) => <option key={s.key} value={s.key}>{s.label || s.key}{s.required ? "" : " (optional)"}</option>)}
            </select>
          </Field>
          {target.kind === "stack" ? (
            <Field label="Units" hint={`of ${target.stack.count} in the stack`}>
              <NumberInput className="text" value={qty} min={1} max={target.stack.count} onChange={setQty} />
            </Field>
          ) : null}
          <Field label="Done on">
            <input className="text" type="date" value={madeAt} onChange={(e) => setMadeAt(e.target.value)} />
          </Field>
          {preparedInputs.map((i) => (
            <Field key={i.component_id} label={`Lot of ${view.parts[String(i.component_id)]?.name}`}
              hint="one lot per click, so the units stay one pile">
              <NumberInput className="text" value={lots[String(i.component_id)] ?? null} min={1}
                placeholder="oldest lot that holds enough"
                onChange={(v) => setLots({ ...lots, [String(i.component_id)]: v })} />
            </Field>
          ))}
          <Field label="Note" wide>
            <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

export default function RunProcess({ run }: { run: RunInfo }) {
  const dialog = useDialog();
  const [view, setView] = useState<CraftView | null>(null);
  const [costs, setCosts] = useState<CostByStep | null>(null);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  // selected devices, and how each one was chosen
  const [picked, setPicked] = useState<Record<number, "scanned" | "list">>({});
  const [scan, setScan] = useState("");
  const [modal, setModal] = useState<
    | { kind: "step"; target: Target }
    | { kind: "receive" } | { kind: "found" } | { kind: "finish" }
    | { kind: "scrap"; target: Target } | { kind: "merge"; ids: number[] }
    | { kind: "assembly" } | { kind: "link"; lineIds: number[]; label: string }
    | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getCraft(run.id, ac.signal)
      .then((v) => { setView(v); setError(null); })
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    getRuns(run.project_id, ac.signal).then(setRuns).catch(() => undefined);
    getCostByStep(run.id, ac.signal).then(setCosts).catch(() => setCosts(null));
    return () => ac.abort();
  }, [run.id, run.project_id, tick]);

  const label = useCallback((k: string) => view?.graph.steps.find((s) => s.key === k)?.label || k, [view]);
  const pickedIds = Object.keys(picked).map(Number);
  const chosenOf = (ids: number[]): "scanned" | "list" =>
    ids.every((id) => picked[id] === "scanned") ? "scanned" : "list";

  const devColumns: Column<CraftDevice>[] = useMemo(() => [
    { key: "sel", label: "", width: 4, interactive: false, className: "ctr", get: (d) => (picked[d.device_id] ? 1 : 0),
      render: (d) => (
        <input type="checkbox" checked={!!picked[d.device_id]} onChange={(e) => {
          const next = { ...picked };
          if (e.target.checked) next[d.device_id] = next[d.device_id] ?? "list"; else delete next[d.device_id];
          setPicked(next);
        }} />
      ) },
    { key: "dev", label: "Device", width: 18, className: "mono", get: (d) => d.serial || d.mac || "",
      render: (d) => <Link to={`/production/devices/${d.device_id}`}>{d.serial || d.mac}</Link> },
    { key: "status", label: "State", width: 10, get: (d) => d.status, render: (d) => <StatusPill status={d.status} /> },
    { key: "done", label: "Done", width: 34, get: (d) => d.done.map(label).join(", ") },
    { key: "missing", label: "Still needs", width: 24, get: (d) => d.missing.join("; "),
      render: (d) => (d.status === "finished" ? <span className="muted">—</span> : d.missing.join("; ") || "ready to finish") },
    { key: "price", label: "Price", width: 10, numeric: true, get: (d) => d.price_usd ?? 0, render: (d) => usd(d.price_usd) },
  ], [picked, label]);

  if (error) return <ErrorBanner message={error} />;
  if (!view) return <Spinner />;

  const addScan = () => {
    const code = scan.trim().toLowerCase();
    if (!code) return;
    const d = view.devices.find((x) => [x.serial, x.mac].some((v) => (v || "").toLowerCase() === code
      || (v || "").toLowerCase().replace(/[:-]/g, "") === code.replace(/[:-]/g, "")));
    setScan("");
    if (!d) {
      void dialog.alert(`${scan.trim()} is not a device of ${run.label}.`, { title: "Not in this batch" });
      return;
    }
    setPicked({ ...picked, [d.device_id]: "scanned" });
  };

  const close = (changed: boolean) => { setModal(null); if (changed) { setPicked({}); reload(); } };
  const stackColumns: Column<CraftStack>[] = [
    { key: "done", label: "Units that have done", width: 48, get: (s) => stackText(s, label) },
    { key: "n", label: "Units", width: 8, numeric: true, get: (s) => s.count },
    { key: "next", label: "Next on the route", width: 24,
      get: (s) => (s.next ?? []).map((k) => {
        const st = view.graph.steps.find((x) => x.key === k);
        return st && st.kind !== "step" ? `${label(k)} (${STEP_STATION[st.kind]})` : label(k);
      }).join(", ") || "—" },
    { key: "act", label: "", width: 20, interactive: false, get: () => "",
      render: (s) => (
        <div className="btn-row">
          <button type="button" className="btn btn-sm" disabled={!(s.can ?? []).length}
            onClick={() => setModal({ kind: "step", target: { kind: "stack", stack: s } })}>Run a step…</button>
          <button type="button" className="btn btn-sm" onClick={() => setModal({ kind: "scrap", target: { kind: "stack", stack: s } })}>Scrap…</button>
        </div>
      ) },
  ];

  return (
    <>
      <div className="card pad">
        <h2 className="card-title">Crafting {run.label}</h2>
        <p className="muted dim">
          Process v{view.version_no}. {view.origin.received} board(s) received, {view.origin.finished} finished
          {view.origin.scrapped ? `, ${view.origin.scrapped} scrapped` : ""}. Origin batch cost{" "}
          {usd(view.origin.origin_cost_usd)}{view.origin.scrap_carried_usd ? ` + ${usd(view.origin.scrap_carried_usd)} of scrapped units` : ""}
          {view.origin.share_usd != null ? <>, {usd(view.origin.share_usd)} per unit{view.origin.frozen ? " (frozen at close)" : ""}</> : null}.
          {view.origin.step_costs_usd ? <> Invoices linked to steps: {usd(view.origin.step_costs_usd)}, carried by the units of those steps.</> : null}
        </p>
        <div className="btn-row">
          <button type="button" className="btn btn-primary" onClick={() => setModal({ kind: "receive" })}>Receive boards…</button>
          <button type="button" className="btn" onClick={() => setModal({ kind: "found" })}>Enter found units…</button>
        </div>
      </div>

      <div className="card pad">
        <h2 className="card-title">Board assembly</h2>
        {view.assembly.recorded ? (
          <p className="muted dim">
            {view.assembly.chosen === "rebuilt" ? "Rebuilt from the batch's records" : "Recorded from the assembly order"}
            {view.assembly.orders.length ? ` (${view.assembly.orders.join(", ")})` : ""}, dated {view.assembly.made_at}:{" "}
            {view.assembly.units} unit(s), {view.assembly.lines} invoice position(s), {view.assembly.draws} part
            draw(s) from our stock at the supplier.
          </p>
        ) : (
          <p className="muted dim">
            Not recorded yet. Receiving the boards records it from the batch's assembly order
            {view.assembly.orders.length ? ` (${view.assembly.orders.join(", ")})` : " — none is linked yet (JLC import queue)"}.
          </p>
        )}
        <div className="btn-row">
          <button type="button" className="btn btn-sm" disabled={!view.origin.received}
            onClick={() => setModal({ kind: "assembly" })}>Pick up new board and assembly positions…</button>
        </div>
      </div>

      {view.unlinked.lines.length || view.unlinked.draws.length ? (
        <div className="card pad">
          <h2 className="card-title">Charged to the batch, not linked to a step</h2>
          <p className="muted dim">
            {usd(view.unlinked.usd)} stays in the origin batch cost and is split over every unit. Link a
            position to the step it paid for, and only the units of that step carry it.
          </p>
          <DataTable
            rows={view.unlinked.lines}
            rowKey={(l) => l.line_id}
            empty="Every invoice position of this batch is linked to a step."
            columns={[
              { key: "label", label: "Invoice position", width: 50, get: (l) => l.label },
              { key: "key", label: "What it is", width: 20, className: "mono", get: (l) => l.plan_key || "—" },
              { key: "usd", label: "USD", width: 12, numeric: true, get: (l) => l.usd, render: (l) => usd(l.usd) },
              { key: "act", label: "", width: 18, interactive: false, get: () => "",
                render: (l) => (
                  <button type="button" className="btn btn-sm"
                    onClick={() => setModal({ kind: "link", lineIds: [l.line_id], label: l.label })}>Link to steps…</button>
                ) },
            ]}
          />
          {view.unlinked.draws.length ? (
            <p className="muted">
              {view.unlinked.draws.length} part draw(s) of this batch belong to no step
              ({usd(view.unlinked.draws.reduce((a, d) => a + d.usd, 0))}).
            </p>
          ) : null}
        </div>
      ) : null}

      {costs ? (
        <div className="card pad">
          <h2 className="card-title">Cost by step</h2>
          <p className="muted dim">
            What {run.label} cost ({usd(costs.total_usd)}), read off its process steps: the parts each step
            drew and the invoices linked to it. The board and its assembly are the assembly step
            {costs.board_and_assembly_per_unit_usd != null ? ` — ${usd(costs.board_and_assembly_per_unit_usd)} per unit` : ""}.
          </p>
          <DataTable
            rows={[...costs.steps.map((r) => ({ ...r, key: r.step })),
                   { key: "_origin", step: "", label: "Origin batch cost (no step claims it)", kind: "origin",
                     units: costs.origin.twins ?? 0, parts_usd: 0, invoices_usd: costs.origin.usd,
                     total_usd: costs.origin.usd, per_unit_usd: costs.origin.share_usd, invoices: [] }]}
            rowKey={(r) => r.key}
            columns={[
              { key: "label", label: "Step", width: 32, get: (r) => r.label },
              { key: "units", label: "Units", width: 8, numeric: true, get: (r) => r.units },
              { key: "parts", label: "Parts", width: 12, numeric: true, get: (r) => r.parts_usd,
                render: (r) => (r.parts_usd ? usd(r.parts_usd) : "—") },
              { key: "inv", label: "Invoices", width: 12, numeric: true, get: (r) => r.invoices_usd,
                render: (r) => (r.invoices_usd ? usd(r.invoices_usd) : "—"),
                title: (r) => r.invoices.map((i) => `${i.name}: ${usd(i.usd)}`).join("\n") },
              { key: "total", label: "Total", width: 12, numeric: true, get: (r) => r.total_usd,
                render: (r) => usd(r.total_usd) },
              { key: "per", label: "Per unit", width: 12, numeric: true, get: (r) => r.per_unit_usd ?? 0,
                render: (r) => (r.per_unit_usd != null ? usd(r.per_unit_usd) : "—") },
            ]}
          />
        </div>
      ) : null}

      <div className="card pad">
        <h2 className="card-title">Before programming</h2>
        <p className="muted dim">Units are taken as “N from this stack”: nothing on an unprogrammed board says which one it is.</p>
        <DataTable rows={view.stacks} columns={stackColumns} rowKey={(s) => s.stack} empty="No units waiting — receive the boards first." />
      </div>

      <div className="card pad">
        <h2 className="card-title">Programming bench</h2>
        <p className="muted dim">
          The bench names one unit of this stack for every board it programs. When the stack is
          used up it asks for the next; a board programmed with none becomes a gap.
        </p>
        <Field label="Stack the bench programs from">
          <select className="text" value={view.bench_stack ?? ""} onChange={async (e) => {
            try { await setBenchStack(run.id, e.target.value || null); reload(); }
            catch (err) { await dialog.alert(errorMessage(err), { title: "Could not set the stack" }); }
          }}>
            <option value="">no stack — programmed boards become gaps</option>
            {view.bench_stack && !view.bench_stacks.some((s) => s.stack === view.bench_stack) ? (
              <option value={view.bench_stack} disabled>used up — choose the next stack</option>
            ) : null}
            {view.bench_stacks.map((s) => (
              <option key={s.stack} value={s.stack}>
                {s.run_label}: {stackText(s, label)} — {s.count} unit(s)
              </option>
            ))}
          </select>
        </Field>
        {view.bench_stack ? <p className="muted">{view.bench_left} unit(s) left in it.</p> : null}
      </div>

      {view.gaps.length ? (
        <div className="card pad">
          <h2 className="card-title">Gaps — programmed with no unit behind them</h2>
          <DataTable
            rows={view.gaps}
            rowKey={(g) => g.device_id}
            columns={[
              { key: "dev", label: "Device", width: 70, className: "mono", get: (g) => g.serial || g.mac || "" },
              { key: "act", label: "", width: 30, interactive: false, get: () => "",
                render: (g) => <button type="button" className="btn btn-sm" onClick={() => setModal({ kind: "merge", ids: [g.device_id] })}>Merge…</button> },
            ]}
          />
          <button type="button" className="btn btn-sm" onClick={() => setModal({ kind: "merge", ids: view.gaps.map((g) => g.device_id) })}>
            Merge all {view.gaps.length}…
          </button>
        </div>
      ) : null}

      <div className="card pad">
        <h2 className="card-title">Devices</h2>
        <div className="toolbar">
          <Field label="Scan a label or MAC">
            <input className="text mono" value={scan} placeholder="scan, then Enter"
              onChange={(e) => setScan(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addScan(); } }} />
          </Field>
          <span className="muted">{pickedIds.length} selected
            {pickedIds.length ? ` (${chosenOf(pickedIds) === "scanned" ? "all scanned" : "some picked from the list"})` : ""}</span>
          <button type="button" className="btn btn-sm" disabled={!pickedIds.length}
            onClick={() => setModal({ kind: "step", target: { kind: "devices", ids: pickedIds, chosen: chosenOf(pickedIds) } })}>Run a step…</button>
          <button type="button" className="btn btn-sm btn-primary" disabled={!pickedIds.length}
            onClick={() => setModal({ kind: "finish" })}>Mark finished…</button>
          <button type="button" className="btn btn-sm" disabled={!pickedIds.length}
            onClick={() => setModal({ kind: "scrap", target: { kind: "devices", ids: pickedIds, chosen: chosenOf(pickedIds) } })}>Scrap…</button>
          {pickedIds.length ? <button type="button" className="btn btn-sm" onClick={() => setPicked({})}>Clear</button> : null}
        </div>
        <DataTable rows={view.devices} columns={devColumns} rowKey={(d) => d.device_id}
          empty="No device yet — the programming bench names units as it programs them." />
      </div>

      <div className="card pad">
        <h2 className="card-title">Steps done in this batch</h2>
        <DataTable
          rows={view.clicks}
          rowKey={(c) => c.id}
          empty="Nothing done yet."
          columns={[
            { key: "date", label: "Date", width: 12, className: "mono", get: (c) => c.made_at },
            { key: "step", label: "Step", width: 28, get: (c) => c.label },
            { key: "qty", label: "Units", width: 8, numeric: true, get: (c) => c.qty },
            { key: "parts", label: "Parts", width: 10, numeric: true, get: (c) => c.parts_usd,
              render: (c) => (c.parts_usd ? usd(c.parts_usd) : "—") },
            { key: "costs", label: "Invoices", width: 10, numeric: true, get: (c) => c.costs_usd,
              render: (c) => (c.costs_usd ? usd(c.costs_usd) : "—") },
            { key: "how", label: "Chosen", width: 10, get: (c) => c.chosen },
            { key: "by", label: "By", width: 12, get: (c) => c.actor },
            { key: "note", label: "Note", width: 18, get: (c) => c.note },
          ]}
        />
      </div>

      {modal?.kind === "step" ? <StepDialog run={run} view={view} target={modal.target} onClose={close} /> : null}
      {modal?.kind === "receive" ? <ReceiveDialog run={run} onClose={close} /> : null}
      {modal?.kind === "found" ? <FoundDialog run={run} view={view} runs={runs} onClose={close} /> : null}
      {modal?.kind === "finish" ? (
        <DryRunDialog<{ units: number; refused: { unit: string; why: string[] }[] }>
          title="Mark finished"
          intro={`${pickedIds.length} device(s), ${chosenOf(pickedIds) === "scanned" ? "scanned" : "picked from the list"}. A device that misses a required step is refused.`}
          onClose={close}
          run={(dry) => craftFinish(run.id, { device_ids: pickedIds, chosen: chosenOf(pickedIds), dry_run: dry })}
          describe={(p) => (p.refused.length
            ? <span className="banner-error">Refused: {p.refused.map((r) => `${r.unit} — ${r.why.join(", ")}`).join("; ")}</span>
            : <>{p.units} device(s) can be marked finished.</>)}
          fields={null}
        />
      ) : null}
      {modal?.kind === "scrap" ? <ScrapDialog run={run} target={modal.target} onClose={close} /> : null}
      {modal?.kind === "merge" ? <MergeDialog run={run} view={view} ids={modal.ids} label={label} onClose={close} /> : null}
      {modal?.kind === "assembly" ? (
        <DryRunDialog<{ status: string; lines_linked?: number; draws_linked?: number; twins_added?: number }>
          title="Board assembly"
          intro="Links every board and assembly position charged to this batch, and the parts the supplier drew from our stock, to the assembly step."
          onClose={close}
          run={(dry) => craftAssembly(run.id, dry)}
          describe={(p) => (p.status === "no_twins"
            ? <span className="banner-error">No boards received yet.</span>
            : <>{p.lines_linked ?? 0} position(s) and {p.draws_linked ?? 0} draw(s) join the assembly step
                {p.twins_added ? `, and ${p.twins_added} unit(s)` : ""}.</>)}
          fields={null}
        />
      ) : null}
      {modal?.kind === "link" ? <LinkDialog run={run} clicks={view.clicks} lineIds={modal.lineIds}
        what={modal.label} onClose={close} /> : null}
    </>
  );
}

/** Link invoice positions to the step clicks they paid for (decisions 0060,
 *  0061). One invoice can pay for several steps — the final assembler's covers
 *  programming, the enclosure, the laser mark and the label — and the units of
 *  all the clicks ticked share it. A scrap is no step a cost can pay for. */
function LinkDialog({ run, clicks, lineIds, what, onClose }: {
  run: RunInfo; clicks: CraftClick[]; lineIds: number[]; what: string; onClose: (c: boolean) => void;
}) {
  const options = clicks.filter((c) => c.qty > 0 && c.kind !== "scrap");
  const [ticked, setTicked] = useState<number[]>([]);
  const [wholeSteps, setWholeSteps] = useState<string[]>([]);
  const toggle = (id: number, on: boolean) =>
    setTicked((t) => (on ? [...t, id] : t.filter((x) => x !== id)));
  // A whole step goes to the server by its key, which resolves EVERY click of
  // it — the list here holds only the newest 200, and programming is one
  // click per device.
  const steps = [...new Map(options.map((c) => [c.step, c.label])).entries()];
  const tickStep = (step: string, on: boolean) =>
    setWholeSteps((w) => (on ? [...new Set([...w, step])] : w.filter((x) => x !== step)));
  return (
    <DryRunDialog<{ lines: { line_id: number; label: string }[]; refused: { label: string; why: string }[] }>
      title="Link to steps"
      intro={`“${what}” paid for these step clicks. Their units share it equally; the money stays charged to ${run.label}.`}
      onClose={onClose}
      run={(dry) => craftCosts(run.id, { step_run_ids: ticked, step_keys: wholeSteps, line_ids: lineIds,
                                         dry_run: dry })}
      describe={(p) => (p.refused.length
        ? <span className="banner-error">Refused: {p.refused.map((r) => `${r.label} — ${r.why}`).join("; ")}</span>
        : <>{p.lines.length} position(s) will be linked to {wholeSteps.length} whole step(s)
            {ticked.length ? ` and ${ticked.length} single click(s)` : ""}.</>)}
      fields={
        <>
          <Field label="Whole steps" wide>
            <div className="btn-row">
              {steps.map(([step, label]) => (
                <CheckField key={step} checked={wholeSteps.includes(step)}
                  onChange={(v) => tickStep(step, v)}>{label}</CheckField>
              ))}
            </div>
          </Field>
          <Field label="Or single clicks" wide>
            <div>
              {options.map((c) => (
                <CheckField key={c.id} checked={ticked.includes(c.id)} onChange={(v) => toggle(c.id, v)}>
                  {c.made_at} · {c.label} · {c.qty} unit(s)
                </CheckField>
              ))}
            </div>
          </Field>
        </>
      }
    />
  );
}

function ReceiveDialog({ run, onClose }: { run: RunInfo; onClose: (c: boolean) => void }) {
  const [qty, setQty] = useState<number | null>(run.qty || null);
  const [madeAt, setMadeAt] = useState(today());
  return (
    <DryRunDialog<{ qty: number; received_before: number; ordered: number; over_order: boolean }>
      title="Receive boards"
      intro="One unit per board the batch's assembly order delivered."
      onClose={onClose}
      run={(dry) => craftReceive(run.id, { qty: qty ?? 0, made_at: madeAt, dry_run: dry })}
      describe={(p) => (
        <>
          {p.qty} unit(s); {p.received_before} received before, {p.ordered} ordered.
          {p.over_order ? <span className="banner-warn"> That is more than the order.</span> : null}
        </>
      )}
      fields={
        <FieldGrid>
          <Field label="Boards"><NumberInput className="text" value={qty} min={1} onChange={setQty} /></Field>
          <Field label="Received on">
            <input className="text" type="date" value={madeAt} onChange={(e) => setMadeAt(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

function FoundDialog({ run, view, runs, onClose }: {
  run: RunInfo; view: CraftView; runs: RunInfo[]; onClose: (c: boolean) => void;
}) {
  const [qty, setQty] = useState<number | null>(null);
  const [done, setDone] = useState<string[]>([]);
  const [origin, setOrigin] = useState<number>(run.id);
  const [note, setNote] = useState("");
  const steps = view.graph.steps.filter((s) => s.kind === "step" || s.kind === "mark_laser" || s.kind === "label");
  return (
    <DryRunDialog<{ units: number; done: string[] }>
      title="Enter found units"
      intro="Units that exist but have no record — found at a stock count. They enter at zero value: their cost already sits in the books of the batch they came from."
      onClose={onClose}
      run={(dry) => craftFound(run.id, { qty: qty ?? 0, done, origin_run_id: origin, note, dry_run: dry })}
      describe={(p) => <>{p.units} unit(s) enter with: {p.done.join(", ")}.</>}
      fields={
        <FieldGrid>
          <Field label="Units"><NumberInput className="text" value={qty} min={1} onChange={setQty} /></Field>
          <Field label="Came from batch" hint="whose books hold their cost">
            <select className="text" value={origin} onChange={(e) => setOrigin(Number(e.target.value))}>
              {runs.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </Field>
          <Field label="Already done" wide>
            <div className="btn-row">
              {steps.map((s) => (
                <CheckField key={s.key} checked={done.includes(s.key)}
                  onChange={(v) => setDone(v ? [...done, s.key] : done.filter((k) => k !== s.key))}>
                  {s.label || s.key}
                </CheckField>
              ))}
            </div>
          </Field>
          <Field label="Where they were found" wide hint="required">
            <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

function ScrapDialog({ run, target, onClose }: { run: RunInfo; target: Target; onClose: (c: boolean) => void }) {
  const [qty, setQty] = useState<number | null>(1);
  const [reason, setReason] = useState("");
  return (
    <DryRunDialog<{ units: number }>
      title="Scrap units"
      intro="Their price is carried by the other units of the batch they came from, until that batch is closed."
      onClose={onClose}
      run={(dry) => craftScrap(run.id, {
        reason, dry_run: dry,
        ...(target.kind === "stack" ? { stack: target.stack.stack, qty: qty ?? 0 } : { device_ids: target.ids, chosen: target.chosen }),
      })}
      describe={(p) => <>{p.units} unit(s) will be scrapped.</>}
      fields={
        <FieldGrid>
          {target.kind === "stack" ? (
            <Field label="Units" hint={`of ${target.stack.count}`}>
              <NumberInput className="text" value={qty} min={1} max={target.stack.count} onChange={setQty} />
            </Field>
          ) : null}
          <Field label="Why" wide hint="required">
            <AutoTextarea className="text" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

function MergeDialog({ run, view, ids, label, onClose }: {
  run: RunInfo; view: CraftView; ids: number[]; label: (k: string) => string; onClose: (c: boolean) => void;
}) {
  // The bench's stack only while it still holds units: a used-up one is in no
  // option, and sending it would merge from nothing.
  const ready = view.bench_stacks.some((s) => s.stack === view.bench_stack);
  const [stack, setStack] = useState((ready ? view.bench_stack : null) ?? view.bench_stacks[0]?.stack ?? "");
  return (
    <DryRunDialog<{ units: number; stack: string }>
      title="Merge gaps"
      intro={`${ids.length} programmed device(s) take a unit from the stack they came from.`}
      onClose={onClose}
      run={(dry) => craftMerge(run.id, { stack, device_ids: ids, chosen: "list", dry_run: dry })}
      describe={(p) => <>{p.units} device(s) take units from the stack.</>}
      fields={
        <Field label="Stack they came from">
          <select className="text" value={stack} onChange={(e) => setStack(e.target.value)}>
            {view.bench_stacks.map((s) => (
              <option key={s.stack} value={s.stack}>{s.run_label}: {stackText(s, label)} — {s.count}</option>
            ))}
          </select>
        </Field>
      }
    />
  );
}
