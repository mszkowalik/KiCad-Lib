/** The process as a plan (decisions 0058 §8, 0059 §4, 0103): the board in plan
 *  mode, on the project's Process tab.
 *
 *  Each field says where the step is done, whether it is required, what it needs,
 *  and how many devices the stock of its parts covers, coloured against a number
 *  the reader types. Steps off the route (the other option of a choice) sit under
 *  the path, so the map shows everything a unit can go through. Prepared parts —
 *  made before they meet a device — follow, with their stock and the actions that
 *  make or correct it. A bench step shows the deployment that says how it is done
 *  (decision 0060), linked to its page.
 */
import { Link } from "react-router-dom";
import {
  inputKey,
  type PreparedRecipe,
  type ProcessDeployment,
  type PreparedStock,
  type ProcessStep,
  type ProcessVersionDetail,
} from "../../api";
import { pln } from "../../format";
import { useTodayRate } from "../../useTodayRate";
import { useStickyState } from "../../useStickyState";
import Field, { FieldRow } from "../Field";
import NumberInput from "../NumberInput";
import ProcessBoard, { OffRouteFields, stockTone, type BoardField } from "./ProcessBoard";

export function inputsText(inputs: { component_id?: number | null; mpn?: string; qty: number }[] | undefined,
  parts: ProcessVersionDetail["parts"]): string {
  return (inputs ?? [])
    .map((i) => `${i.qty} × ${i.component_id ? parts[String(i.component_id)]?.name ?? `part ${i.component_id}` : i.mpn}`)
    .join(" + ");
}

function planFields(version: ProcessVersionDetail, steps: ProcessStep[], deployments: ProcessDeployment[],
  stock: Record<string, number>, planFor: number): BoardField[] {
  const label = (k: string) => version.graph.steps.find((s) => s.key === k)?.label || k;
  return steps.map((step) => {
    const inputs = (step.inputs ?? []).map((i) => {
      const onHand = stock[inputKey(i)] ?? 0;
      const covers = i.qty > 0 ? Math.floor(onHand / i.qty) : null;
      return {
        name: i.component_id ? version.parts[String(i.component_id)]?.name ?? `part ${i.component_id}` : i.mpn ?? "",
        qty: i.qty,
        covers,
      };
    });
    const dep = step.deployment_id ? deployments.find((d) => d.id === step.deployment_id) : null;
    const required = !!step.required || step.kind === "finish";
    const short = required && inputs.some((i) => i.covers !== null && i.covers < planFor);
    return {
      key: step.key,
      label: step.label || step.key,
      kind: step.kind,
      required,
      note: step.group ? `choice: ${step.group}` : undefined,
      state: short ? "short" : "idle",
      needsText: step.kind === "finish" ? "every required step" : step.needs?.map(label).join(", "),
      beforeText: step.needs_not?.map(label).join(", "),
      stock: inputs.map((i) => ({
        name: i.name,
        line: <b title="devices the stock covers">{i.covers === null ? "—" : i.covers.toLocaleString()}</b>,
        tone: stockTone(i.covers, planFor),
      })),
      procedure: dep ? (
        <>
          <Link to={`/production/procedures?project=${version.project_id}&deployment=${dep.id}`}>{dep.name}</Link>
          {dep.current_version_no ? ` v${dep.current_version_no}` : " (nothing published)"}
        </>
      ) : step.deployment_id ? <span className="muted">{step.deployment_id} (not in this project)</span> : undefined,
    };
  });
}

export default function ProcessMap({ version, prepared, deployments, stock, canMake, onMake, onBank, onStocktake }: {
  version: ProcessVersionDetail;
  /** the project's deployments, to name the procedure of each bench step */
  deployments: ProcessDeployment[];
  prepared: PreparedStock[] | null;
  /** on hand of each step input, by `inputKey` */
  stock: Record<string, number>;
  /** only the CURRENT published version takes new work */
  canMake: boolean;
  onMake: (r: PreparedRecipe) => void;
  onBank: (p: PreparedStock) => void;
  onStocktake: (p: PreparedStock) => void;
}) {
  const rate = useTodayRate();
  const [planFor, setPlanFor] = useStickyState<number>(`process:${version.project_id}:plan-for`, 100);
  const g = version.graph;
  const steps = g.steps ?? [];
  if (!steps.length) return <p className="muted">This version has no steps.</p>;
  const route = (g.route ?? []).map((k) => steps.find((s) => s.key === k)).filter(Boolean) as ProcessStep[];
  const off = steps.filter((s) => !(g.route ?? []).includes(s.key));
  const byPart = new Map((prepared ?? []).map((p) => [p.component_id, p]));
  const fedSteps = (componentId: number) => steps.filter((s) => (s.inputs ?? []).some((i) => i.component_id === componentId));
  return (
    <>
      <FieldRow>
        <Field label="Plan for" hint="devices. The number on a part is how many devices its stock covers.">
          <NumberInput className="text num-input" value={planFor} min={1} step={1} onChange={(v) => setPlanFor(v ?? 1)} />
        </Field>
      </FieldRow>
      <ProcessBoard fields={planFields(version, route, deployments, stock, planFor)} />
      <OffRouteFields fields={planFields(version, off, deployments, stock, planFor)} />
      {(g.prepared ?? []).length ? (
        <>
          <div className="card-subtitle">Prepared parts</div>
          <div className="process-map">
            {(g.prepared ?? []).map((r) => {
              const st = byPart.get(r.output_component_id);
              return (
                <div key={r.key} className="process-col">
                  <div className="process-stage">
                    <div className="process-stage-head">
                      <b>{version.parts[String(r.output_component_id)]?.name ?? r.output_component_id}</b>
                    </div>
                    <div className="muted">{st ? <>{st.on_hand} on hand · {pln(st.value_usd, rate)}</> : "—"}</div>
                    <div className="process-recipe">
                      {r.label || r.key}
                      <div className="muted dim">{inputsText(r.inputs, version.parts)}</div>
                      {fedSteps(r.output_component_id).length ? (
                        <div className="muted dim">↑ goes into {fedSteps(r.output_component_id).map((f) => f.label || f.key).join(", ")}</div>
                      ) : null}
                    </div>
                    {canMake ? (
                      <div className="btn-row">
                        <button type="button" className="btn btn-sm" onClick={() => onMake(r)}>Make…</button>
                        {st ? <button type="button" className="btn btn-sm" onClick={() => onBank(st)}>Bank found…</button> : null}
                        {st ? <button type="button" className="btn btn-sm" onClick={() => onStocktake(st)}>Take stock…</button> : null}
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      ) : null}
    </>
  );
}
