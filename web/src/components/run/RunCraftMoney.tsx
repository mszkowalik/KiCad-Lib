/** Batch → Money, the part a crafted batch adds: what its process steps cost
 *  (decision 0060), and the invoice positions linked to them or to none.
 */
import {
  craftCosts,
  type RunInfo,
} from "../../api";
import { pln } from "../../format";
import DataTable from "../DataTable";
import { useDialog } from "../Dialog";
import FoldSection, { StatChip } from "../FoldSection";
import { refusalText, type CraftModal } from "./craftDialogs";
import type { Craft } from "./useCraft";

export default function RunCraftMoney({ run, craft, onModal }: {
  run: RunInfo;
  craft: Craft;
  onModal: (m: CraftModal) => void;
}) {
  const dialog = useDialog();
  const { view, costs, reload } = craft;
  if (!view) return null;
  const money = (v: number | null | undefined) => pln(v, view.pln_per_usd);

  // Take a position off the steps it paid for: its money goes back into the
  // origin batch cost (decisions 0061, 0074). A split one goes with its header.
  const unlink = async (l: (typeof view.linked)[number]) => {
    try {
      const plan = await craftCosts(run.id, { line_ids: [l.line_id], step_run_ids: [], step_keys: [], unlink: true,
                                              dry_run: true });
      if (plan.refused.length) {
        await dialog.alert(plan.refused.map((r) => `${r.label}: ${r.why}`).join("\n"), { title: "Unlink refused" });
        return;
      }
    } catch (err) {
      await dialog.alert(refusalText(err), { title: "Unlink refused" });
      return;
    }
    const ok = await dialog.confirm(
      `Unlink “${l.label}” (${money(l.usd)}) from ${l.steps.join(", ")}? Its money goes back into the batch's `
        + "origin cost, shared by all its units. Undo it on History → Write batches.",
      { title: "Unlink position", confirmLabel: "Unlink", tone: "danger" },
    );
    if (!ok) return;
    try {
      await craftCosts(run.id, { line_ids: [l.line_id], step_run_ids: [], step_keys: [], unlink: true, dry_run: false });
    } catch (err) {
      await dialog.alert(refusalText(err), { title: "Unlink refused" });
      return;
    }
    reload();
  };

  const stepCounts = new Map<string, number>();
  for (const l of view.linked) for (const s of l.steps) stepCounts.set(s, (stepCounts.get(s) ?? 0) + 1);

  return (
    <>
      <div className="card pad">
        <h2 className="card-title">Origin batch cost</h2>
        <p className="muted dim">
          {money(view.origin.origin_cost_usd)}{view.origin.scrap_carried_usd ? ` + ${money(view.origin.scrap_carried_usd)} of scrapped units` : ""}
          {view.origin.share_usd != null ? <>, {money(view.origin.share_usd)} per unit{view.origin.frozen ? " (frozen at close)" : ""}</> : null}.
          {view.origin.step_costs_usd ? <> Invoices linked to steps: {money(view.origin.step_costs_usd)}, carried by the units of those steps.</> : null}
        </p>
      </div>

      {view.unlinked.lines.length || view.unlinked.draws.length ? (
        <FoldSection title="Charged to the batch, not linked to a step" count={view.unlinked.lines.length}
          foldKey={`run:${run.id}:unlinked`} chips={<StatChip n={money(view.unlinked.usd)} tone="warn" />}>
          <p className="muted dim">
            {money(view.unlinked.usd)} stays in the origin batch cost and is split over every unit. Link a
            position to the step it paid for, and only the units of that step carry it.
          </p>
          <DataTable
            rows={view.unlinked.lines}
            rowKey={(l) => l.line_id}
            empty="Every invoice position of this batch is linked to a step."
            columns={[
              { key: "label", label: "Invoice position", width: 46, get: (l) => l.label },
              { key: "key", label: "What it is", width: 20, className: "mono", get: (l) => l.plan_key || "—" },
              { key: "usd", label: "Amount", width: 16, numeric: true, get: (l) => l.usd, render: (l) => money(l.usd) },
              { key: "act", label: "", width: 18, interactive: false, get: () => "",
                render: (l) => (
                  <button type="button" className="btn btn-sm"
                    onClick={() => onModal({ kind: "link", lineIds: [l.line_id], label: l.label })}>Link to steps…</button>
                ) },
            ]}
          />
          {view.unlinked.draws.length ? (
            <p className="muted">
              {view.unlinked.draws.length} part draw(s) of this batch belong to no step
              ({money(view.unlinked.draws.reduce((a, d) => a + d.usd, 0))}).
            </p>
          ) : null}
        </FoldSection>
      ) : null}

      {costs ? (
        <FoldSection title="Cost by process step" count={costs.steps.length + 1} foldKey={`run:${run.id}:cost-steps`}
          chips={<StatChip n={money(costs.total_usd)}>total</StatChip>}>
          <p className="muted dim">
            What {run.label} cost, read off its process steps: the parts each step
            drew and the invoices linked to it. The board and its assembly are the assembly step
            {costs.board_and_assembly_per_unit_usd != null ? `, ${money(costs.board_and_assembly_per_unit_usd)} per unit` : ""}.
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
              { key: "parts", label: "Parts", width: 15, numeric: true, get: (r) => r.parts_usd,
                render: (r) => (r.parts_usd ? money(r.parts_usd) : "—") },
              { key: "inv", label: "Invoices", width: 15, numeric: true, get: (r) => r.invoices_usd,
                render: (r) => (r.invoices_usd ? money(r.invoices_usd) : "—"),
                title: (r) => r.invoices.map((i) => `${i.name}: ${money(i.usd)}`).join("\n") },
              { key: "total", label: "Total", width: 15, numeric: true, get: (r) => r.total_usd,
                render: (r) => money(r.total_usd) },
              { key: "per", label: "Per unit", width: 15, numeric: true, get: (r) => r.per_unit_usd ?? 0,
                render: (r) => (r.per_unit_usd != null ? money(r.per_unit_usd) : "—") },
            ]}
          />
        </FoldSection>
      ) : null}

      {view.linked.length ? (
        <FoldSection title="Invoice positions linked to steps" count={view.linked.length} limit={-1} foldKey={`run:${run.id}:linked`}
          chips={<>
            <StatChip n={money(view.linked.reduce((a, l) => a + l.usd, 0))} />
            {[...stepCounts.entries()].slice(0, 3).map(([s, n]) => <StatChip key={s} n={n}>{`→ ${s}`}</StatChip>)}
          </>}>
          <DataTable
            rows={view.linked}
            rowKey={(l) => l.line_id}
            columns={[
              { key: "label", label: "Position", width: 40, get: (l) => l.label },
              { key: "steps", label: "Pays for", width: 30, get: (l) => l.steps.join(", "),
                title: (l) => (l.whole_steps.length ? `whole steps: ${l.whole_steps.join(", ")} — also the clicks recorded later` : "single clicks") },
              { key: "usd", label: "Amount", width: 18, numeric: true, get: (l) => l.usd, render: (l) => money(l.usd) },
              { key: "act", label: "", width: 12, interactive: false, get: () => "",
                render: (l) => <button type="button" className="btn btn-sm" onClick={() => void unlink(l)}>Unlink…</button> },
            ]}
          />
        </FoldSection>
      ) : null}
    </>
  );
}
