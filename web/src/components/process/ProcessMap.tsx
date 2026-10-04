/** The process as a map (decisions 0058 §8, 0059 §4).
 *
 *  The main route runs left to right; each step card says where it is done,
 *  whether it is required, what it needs and what parts it adds. Steps off the
 *  route (an optional leaflet, the other option of a choice) sit beside it, so
 *  the map shows everything a unit can go through, not only the usual order.
 *  Prepared parts — made before they meet a device — follow, with their stock
 *  and the actions that make or correct it. A bench step shows the deployment
 *  that says how it is done (decision 0060), linked to its page.
 */
import { Link } from "react-router-dom";
import {
  STEP_STATION,
  type PreparedRecipe,
  type ProcessDeployment,
  type PreparedStock,
  type ProcessStep,
  type ProcessVersionDetail,
} from "../../api";
import { usd } from "../../format";

export function inputsText(inputs: { component_id?: number | null; mpn?: string; qty: number }[] | undefined,
  parts: ProcessVersionDetail["parts"]): string {
  return (inputs ?? [])
    .map((i) => `${i.qty} × ${i.component_id ? parts[String(i.component_id)]?.name ?? `part ${i.component_id}` : i.mpn}`)
    .join(" + ");
}

function StepCard({ step, version, n, deployments }: {
  step: ProcessStep; version: ProcessVersionDetail; n?: number; deployments: ProcessDeployment[];
}) {
  const label = (k: string) => version.graph.steps.find((s) => s.key === k)?.label || k;
  const dep = step.deployment_id ? deployments.find((d) => d.id === step.deployment_id) : null;
  return (
    <div className={`process-stage${step.kind === "program" ? " programmable" : ""}`}>
      <div className="process-stage-head">
        <b>{n !== undefined ? `${n}. ` : ""}{step.label || step.key}</b>
        <span className={`pill ${step.kind === "finish" || step.required ? "neutral" : "warn"}`}>
          {step.kind === "finish" ? "last" : step.required ? (step.group ? `choice: ${step.group}` : "required") : "optional"}
        </span>
      </div>
      <div className="muted dim">at the {STEP_STATION[step.kind]}</div>
      {step.kind === "finish" ? (
        <div className="muted dim">needs every required step</div>
      ) : step.needs?.length ? (
        <div className="muted dim">needs {step.needs.map(label).join(", ")}</div>
      ) : null}
      {step.needs_not?.length ? (
        <div className="muted dim">before {step.needs_not.map(label).join(", ")}</div>
      ) : null}
      {step.inputs?.length ? <div className="process-recipe">{inputsText(step.inputs, version.parts)}</div> : null}
      {dep ? (
        <div className="process-recipe">
          procedure{" "}
          <Link to={`/production/deployments?project=${version.project_id}&deployment=${dep.id}`}>{dep.name}</Link>
          {dep.current_version_no ? ` v${dep.current_version_no}` : " (nothing published)"}
        </div>
      ) : step.deployment_id ? (
        <div className="process-recipe muted">procedure {step.deployment_id} (not in this project)</div>
      ) : null}
    </div>
  );
}

export default function ProcessMap({ version, prepared, deployments, canMake, onMake, onBank, onStocktake }: {
  version: ProcessVersionDetail;
  /** the project's deployments, to name the procedure of each bench step */
  deployments: ProcessDeployment[];
  prepared: PreparedStock[] | null;
  /** only the CURRENT published version takes new work */
  canMake: boolean;
  onMake: (r: PreparedRecipe) => void;
  onBank: (p: PreparedStock) => void;
  onStocktake: (p: PreparedStock) => void;
}) {
  const g = version.graph;
  const steps = g.steps ?? [];
  if (!steps.length) return <p className="muted">This version has no steps.</p>;
  const route = (g.route ?? []).map((k) => steps.find((s) => s.key === k)).filter(Boolean) as ProcessStep[];
  const off = steps.filter((s) => !(g.route ?? []).includes(s.key));
  const byPart = new Map((prepared ?? []).map((p) => [p.component_id, p]));
  return (
    <>
      <div className="card-subtitle">Main route</div>
      <div className="process-map">
        {route.map((s, i) => (
          <div key={s.key} className="process-col"><StepCard step={s} version={version} n={i + 1} deployments={deployments} /></div>
        ))}
      </div>
      {off.length ? (
        <>
          <div className="card-subtitle">Off the route — any time their needs are met</div>
          <div className="process-map">
            {off.map((s) => <div key={s.key} className="process-col"><StepCard step={s} version={version} deployments={deployments} /></div>)}
          </div>
        </>
      ) : null}
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
                    <div className="muted">{st ? <>{st.on_hand} on hand · {usd(st.value_usd)}</> : "—"}</div>
                    <div className="process-recipe">
                      {r.label || r.key}
                      <div className="muted dim">{inputsText(r.inputs, version.parts)}</div>
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
