/** Batch → Floor (decision 0103): where the work on a batch is done.
 *
 *  The board on top says how far each step is and how far stock goes. A click on
 *  a field opens its work panel: who waits there, what they need, and the buttons
 *  of that step. The scan group under the board chooses named devices, which the
 *  board cannot. "Needs attention" holds only problems, so it is empty on a
 *  healthy batch.
 *
 *  Before programming, units are taken as "N from this stack", because nothing on
 *  an unprogrammed board says which one it is. After programming they are devices.
 *  Programming and marking are done at their benches, which read the device: their
 *  fields link to the bench, set up for that step (`benchHref`).
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  setBenchStack,
  errorMessage,
  STEP_STATION,
  type BoardStep,
  type CraftClick,
  type CraftStack,
  type RunInfo,
} from "../../api";
import { pln } from "../../format";
import DataTable, { type Column } from "../DataTable";
import { useDialog } from "../Dialog";
import Field from "../Field";
import FoldSection, { StatChip } from "../FoldSection";
import ProcessBoard, { BoardLegend, isBench, liveFields, OffRouteFields } from "../process/ProcessBoard";
import { ErrorBanner, Spinner } from "../Ui";
import { benchHref } from "./benchLink";
import { AssemblyCard, stackText, stepLabelOf, undoWrite, type CraftModal } from "./craftDialogs";
import ScanGroup, { type ScanGroupState } from "./ScanGroup";
import type { Craft } from "./useCraft";

export default function RunFloor({ run, craft, group, onModal, onMoney }: {
  run: RunInfo;
  craft: Craft;
  group: ScanGroupState;
  onModal: (m: CraftModal) => void;
  /** go to the Money tab */
  onMoney: () => void;
}) {
  const dialog = useDialog();
  const { view, error, draft, draftError, reload } = craft;
  const [selected, setSelected] = useState<string | null>(null);

  // Start on the first field where something can go.
  const board = view?.board;
  useEffect(() => {
    if (!board || selected !== null) return;
    setSelected((board.find((s) => s.can_go > 0) ?? board.find((s) => s.state !== "done") ?? board[0])?.key ?? null);
  }, [board, selected]);

  if (error) return <ErrorBanner message={error} />;
  if (!view) return <Spinner />;

  const label = stepLabelOf(view);
  const onRoute = view.board.filter((s) => s.on_route);
  const offRoute = view.board.filter((s) => !s.on_route);
  const hasDevices = view.devices.length > 0 || view.gaps.length > 0;
  const step = view.board.find((s) => s.key === selected) ?? null;

  const scanFor = (key: string) => { group.tick(key, true); group.focus(); };
  const stacksFor = (key: string) => view.stacks.filter((s) => (s.can ?? []).includes(key));

  const action = (key: string) => {
    const s = view.board.find((x) => x.key === key)!;
    if (s.state === "done" && !isBench(s.kind)) return null;
    if (isBench(s.kind)) {
      return <Link className="btn btn-sm" to={benchHref(run, view, key)} target="_blank" rel="noopener">Open bench ↗</Link>;
    }
    if (s.kind === "assembly") {
      return draft && !view.assembly.recorded
        ? <button type="button" className="btn btn-sm btn-primary" onClick={() => onModal({ kind: "assembly" })}>Record assembly…</button>
        : null;
    }
    if (s.kind === "receive") {
      return s.waiting
        ? <button type="button" className="btn btn-sm btn-primary" onClick={() => onModal({ kind: "receive" })}>Receive boards…</button>
        : null;
    }
    const stacks = stacksFor(key);
    return (
      <>
        {stacks.length === 1 && s.waiting_unnamed ? (
          <button type="button" className="btn btn-sm btn-primary"
            onClick={() => onModal({ kind: "step", target: { kind: "stack", stack: stacks[0] }, stepKey: key })}>Run step…</button>
        ) : null}
        {s.waiting_named ? <button type="button" className="btn btn-sm" onClick={() => scanFor(key)}>Scan devices</button> : null}
      </>
    );
  };
  const extra = (key: string) => {
    const n = group.ready.length ? group.countFor(key) : 0;
    return n ? <StatChip n={n} tone="acc">group can go</StatChip> : null;
  };

  // One write can hold several clicks (a group run, found units, a caught-up
  // bench step): the undo takes them all, so the question names them all.
  const undoClick = async (c: CraftClick) => {
    if (!c.batch_id) return;
    const together = view.clicks.filter((x) => x.batch_id === c.batch_id);
    const named = together.map((x) => `“${x.label}” on ${x.qty} unit(s)`).join(", ");
    const undone = await undoWrite(dialog, c.batch_id, "Undo step", (would) =>
      `Undo ${named}, recorded ${c.made_at} by ${c.actor || "nobody named"}? `
        + `It deletes ${would.delete}, restores ${would.restore} and re-inserts `
        + `${would.reinsert} row(s): the click${together.length > 1 ? "s" : ""}, the twin links, `
        + "the draws and their lot bindings.");
    if (!undone) return;
    reload();
    group.recheck();
  };

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
            onClick={() => onModal({ kind: "step", target: { kind: "stack", stack: s } })}>Run a step…</button>
          <button type="button" className="btn btn-sm" onClick={() => onModal({ kind: "scrap", target: { kind: "stack", stack: s } })}>Scrap…</button>
        </div>
      ) },
  ];

  const short = view.board.flatMap((s) => s.inputs
    .filter((i) => i.covers !== null && i.covers < s.still_to_do && s.required)
    .map((i) => ({ step: s, input: i })));
  const unlinkedLines = view.unlinked.lines;
  const attention = view.gaps.length + short.length + unlinkedLines.length + (view.origin.uncarried_usd ? 1 : 0);

  return (
    <>
      <div className="card pad">
        <div className="fold-bar">
          <div className="fold-toggle"><h2 className="card-title">Board</h2></div>
          <button type="button" className="btn btn-sm" onClick={() => onModal({ kind: "receive" })}>Receive boards…</button>
          <button type="button" className="btn btn-sm" onClick={() => onModal({ kind: "found" })}>Enter found units…</button>
        </div>
        <div className="fold-body">
          <ProcessBoard fields={liveFields(onRoute)} selected={selected} onSelect={setSelected} action={action} extra={extra} />
          <OffRouteFields fields={liveFields(offRoute)} selected={selected} onSelect={setSelected} action={action} extra={extra} />
          <BoardLegend />
        </div>
      </div>

      {hasDevices ? <ScanGroup run={run} view={view} group={group} onChanged={reload} /> : null}

      {attention ? (
        <div className="card pad">
          <h2 className="card-title">Needs attention · {attention}</h2>
          {view.origin.uncarried_usd ? (
            <div className="banner-warn">
              {pln(view.origin.uncarried_usd, view.pln_per_usd)} of this batch's cost is carried by no device: no board received in
              it is alive. The batch cannot be closed until that money goes to the batch whose units it paid for.
            </div>
          ) : null}
          <div className="attention-rows">
            {view.gaps.length ? (
              <div className="attention-row">
                <span><StatChip n={view.gaps.length} tone="warn">gaps</StatChip> devices programmed with no unit behind them</span>
                <button type="button" className="btn btn-sm"
                  onClick={() => onModal({ kind: "merge", ids: view.gaps.map((g) => g.device_id) })}>Merge all {view.gaps.length}…</button>
              </div>
            ) : null}
            {unlinkedLines.length ? (
              <div className="attention-row">
                <span><StatChip n={pln(view.unlinked.usd, view.pln_per_usd)} tone="warn" /> {unlinkedLines.length === 1 ? `“${unlinkedLines[0].label}” is` : `${unlinkedLines.length} invoice positions are`} charged to the batch and linked to no step</span>
                {unlinkedLines.length === 1 ? (
                  <button type="button" className="btn btn-sm"
                    onClick={() => onModal({ kind: "link", lineIds: [unlinkedLines[0].line_id], label: unlinkedLines[0].label })}>Link to steps…</button>
                ) : <button type="button" className="btn btn-sm" onClick={onMoney}>Open Money</button>}
              </div>
            ) : null}
            {short.map(({ step: s, input: i }) => (
              <div key={`${s.key}:${i.key}`} className="attention-row">
                <span><StatChip n={Math.ceil(s.still_to_do - (i.covers ?? 0))} tone="warn">short</StatChip> {s.label}: {i.name} has {Math.floor(i.on_hand).toLocaleString()} in stock, the batch needs {Math.ceil(s.still_to_do * i.per_unit).toLocaleString()} more</span>
                <Link className="btn btn-sm" to={`/stock?q=${encodeURIComponent(i.name)}`}>Open stock ↗</Link>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {step ? <WorkPanel run={run} craft={craft} step={step} stacks={stacksFor(step.key)} stackColumns={stackColumns}
        draftError={draftError} onModal={onModal} scanFor={scanFor} /> : null}

      {view.gaps.length ? (
        <FoldSection title="Gaps: programmed with no unit behind them" count={view.gaps.length} foldKey={`run:${run.id}:gaps`}
          chips={<StatChip n={view.gaps.length} tone="warn">need a unit</StatChip>}
          actions={<button type="button" className="btn btn-sm"
            onClick={() => onModal({ kind: "merge", ids: view.gaps.map((g) => g.device_id) })}>Merge all {view.gaps.length}…</button>}>
          <DataTable
            rows={view.gaps}
            rowKey={(g) => g.device_id}
            columns={[
              { key: "dev", label: "Device", width: 70, className: "mono", get: (g) => g.serial || g.mac || "",
                render: (g) => <Link to={`/production/devices/${g.device_id}`}>{g.serial || g.mac}</Link> },
              { key: "act", label: "", width: 30, interactive: false, get: () => "",
                render: (g) => <button type="button" className="btn btn-sm" onClick={() => onModal({ kind: "merge", ids: [g.device_id] })}>Merge…</button> },
            ]}
          />
        </FoldSection>
      ) : null}

      {view.stacks.length ? (
        <FoldSection title="Units before programming" count={view.stacks.length} foldKey={`run:${run.id}:stacks`}
          chips={<StatChip n={view.stacks.reduce((a, s) => a + s.count, 0).toLocaleString()}>units</StatChip>}>
          <p className="muted dim">Units are taken as “N from this stack”: nothing on an unprogrammed board says which one it is.</p>
          <DataTable rows={view.stacks} columns={stackColumns} rowKey={(s) => s.stack} />
        </FoldSection>
      ) : null}

      <FoldSection title="Steps done in this batch" count={view.clicks.length} foldKey={`run:${run.id}:clicks`}
        chips={view.clicks.length ? <StatChip n={view.clicks[0].made_at}>last</StatChip> : undefined}>
        <DataTable
          rows={view.clicks}
          rowKey={(c) => c.id}
          empty="Nothing done yet."
          columns={[
            { key: "date", label: "Date", width: 10, className: "mono", get: (c) => c.made_at },
            { key: "step", label: "Step", width: 18, get: (c) => c.label },
            { key: "qty", label: "Units", width: 7, numeric: true, get: (c) => c.qty },
            { key: "parts", label: "Parts", width: 13, numeric: true, get: (c) => c.parts_usd,
              render: (c) => (c.parts_usd ? pln(c.parts_usd, view.pln_per_usd) : "—") },
            { key: "costs", label: "Invoices", width: 13, numeric: true, get: (c) => c.costs_usd,
              render: (c) => (c.costs_usd ? pln(c.costs_usd, view.pln_per_usd) : "—") },
            { key: "how", label: "Chosen", width: 9, get: (c) => c.chosen },
            { key: "by", label: "By", width: 11, get: (c) => c.actor },
            { key: "note", label: "Note", width: 12, get: (c) => c.note },
            { key: "undo", label: "", width: 7, interactive: false, get: () => "",
              render: (c) => (c.batch_id
                ? <button type="button" className="btn btn-sm" onClick={() => void undoClick(c)}
                    title="Reverse this click and everything it wrote">Undo…</button>
                : null) },
          ]}
        />
      </FoldSection>
    </>
  );
}

/** What the selected field holds: who waits there, what they need, and its buttons. */
function WorkPanel({ run, craft, step, stacks, stackColumns, draftError, onModal, scanFor }: {
  run: RunInfo;
  craft: Craft;
  step: BoardStep;
  stacks: CraftStack[];
  stackColumns: Column<CraftStack>[];
  draftError: string | null;
  onModal: (m: CraftModal) => void;
  scanFor: (key: string) => void;
}) {
  const dialog = useDialog();
  const { view, draft, reload } = craft;
  if (!view) return null;
  const label = stepLabelOf(view);
  if (step.kind === "assembly") {
    return <AssemblyCard run={run} draft={draft} error={draftError}
      onOpen={() => onModal({ kind: "assembly" })} onChanged={reload} />;
  }
  const parts = step.inputs.map((i) =>
    `${i.per_unit} × ${i.name}: ${Math.floor(i.on_hand).toLocaleString()} in stock`).join(" · ");
  const waits = step.needs.length && !step.waiting && step.state !== "done"
    ? `No unit can take this step yet: units need ${step.needs.map(label).join(" and ")}.` : "";
  return (
    <div className="card pad">
      <h2 className="card-title">{step.label} · {STEP_STATION[step.kind]}</h2>
      <p>
        {step.done.toLocaleString()} of {step.total.toLocaleString()} done.
        {step.waiting_unnamed ? ` ${step.waiting_unnamed.toLocaleString()} unit(s) wait here, unnamed.` : ""}
        {step.waiting_named ? ` ${step.waiting_named.toLocaleString()} device(s) wait here.` : ""}
        {step.can_go < step.waiting ? ` Stock lets ${step.can_go.toLocaleString()} go now.` : ""}
        {waits ? ` ${waits}` : ""}
      </p>
      {parts ? <p className="muted">Each unit takes {parts}.</p> : null}
      {step.procedure ? (
        <p className="muted">
          Procedure <Link to={`/production/procedures?project=${run.project_id}&deployment=${step.procedure.id}`}>{step.procedure.name}</Link>
          {step.procedure.version_no ? ` v${step.procedure.version_no}` : " (nothing published)"}.
        </p>
      ) : null}

      {step.kind === "program" ? (
        <>
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
        </>
      ) : null}

      <div className="btn-row">
        {isBench(step.kind)
          ? <Link className="btn btn-primary" to={benchHref(run, view, step.key)} target="_blank" rel="noopener">Open bench ↗</Link>
          : null}
        {step.kind === "receive" ? (
          <>
            <button type="button" className="btn btn-primary" onClick={() => onModal({ kind: "receive" })}>Receive boards…</button>
            <button type="button" className="btn" onClick={() => onModal({ kind: "found" })}>Enter found units…</button>
          </>
        ) : null}
        {step.waiting_named && !isBench(step.kind)
          ? <button type="button" className="btn" onClick={() => scanFor(step.key)}>Scan devices</button> : null}
        {view.gaps.length && step.kind === "program" ? (
          <button type="button" className="btn"
            onClick={() => onModal({ kind: "merge", ids: view.gaps.map((g) => g.device_id) })}>Merge {view.gaps.length} gaps…</button>
        ) : null}
      </div>

      {step.kind === "step" && stacks.length ? (
        <DataTable rows={stacks} columns={stackColumns.map((c) => (c.key === "act" ? {
          ...c,
          render: (s: CraftStack) => (
            <div className="btn-row">
              <button type="button" className="btn btn-sm btn-primary"
                onClick={() => onModal({ kind: "step", target: { kind: "stack", stack: s }, stepKey: step.key })}>Run on the stack…</button>
              <button type="button" className="btn btn-sm" onClick={() => onModal({ kind: "scrap", target: { kind: "stack", stack: s } })}>Scrap…</button>
            </div>
          ),
        } : c))} rowKey={(s) => s.stack} />
      ) : null}
    </div>
  );
}
