/** Edit a DRAFT process version in place (decisions 0058 §2, 0059 §4).
 *
 *  The deployment-version rule, carried over: no composer screen — the draft
 *  is edited where it is read, every edit is sent to the server, and the answer
 *  carries the machine check, so the editor shows exactly what Publish would
 *  refuse. Text boxes save shortly after typing stops; a pick saves at once.
 *
 *  Three parts:
 *  - the STEP LIBRARY: each step's kind (which fixes where it is done), whether
 *    it is required, its choice group (a sticker OR a UV print), what a unit
 *    must have done before it, and the parts it adds;
 *  - the MAIN ROUTE: the usual order. Any step whose needs are met may still
 *    run in any order;
 *  - PREPARED PARTS: recipes for internal parts made before they meet a device
 *    (an enclosure drilled and printed), held as stock lots.
 */
import { useEffect, useRef, useState } from "react";
import {
  createInternalPart,
  DEPLOYMENT_KIND_FOR,
  errorMessage,
  FIXED_KINDS,
  inputKey,
  STEP_STATION,
  updateProcessDraft,
  type PreparedRecipe,
  type ProcessGraph,
  type ProcessDeployment,
  type ProcessInput,
  type ProcessStep,
  type ProcessVersionDetail,
  type StepKind,
} from "../../api";
import ComponentPickDialog from "../ComponentPickDialog";
import DataTable from "../DataTable";
import { useDialog } from "../Dialog";
import Field, { CheckField, FieldRow, FieldSet } from "../Field";
import NumberInput from "../NumberInput";
import { ErrorBanner } from "../Ui";

const KIND_LABEL: Record<StepKind, string> = {
  assembly: "assembly at the supplier", receive: "receive the boards", step: "a step", program: "programming",
  test: "test",
  mark_laser: "laser marking", label: "barcode label", finish: "finished",
};

function nextKey(prefix: string, keys: string[]): string {
  let n = 1;
  while (keys.includes(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

/** The four steps every process has: the supplier assembles the board, the
 *  batch receives it, the bench programs it, a person marks it finished. */
export function templateGraph(): ProcessGraph {
  return {
    steps: [
      { key: "assembly", label: "Board from the assembler", kind: "assembly", required: true },
      { key: "receive", label: "Receive PCBA", kind: "receive", required: true },
      { key: "program", label: "Program", kind: "program", required: true, needs: ["receive"] },
      { key: "finish", label: "Finished", kind: "finish" },
    ],
    route: ["assembly", "receive", "program", "finish"],
    prepared: [],
  };
}

/** Chips for a list of step / choice references, with an "add…" select. */
function RefList({ value, options, onChange, placeholder }: {
  value: string[];
  options: { value: string; label: string }[];
  onChange: (v: string[]) => void;
  placeholder: string;
}) {
  const label = (v: string) => options.find((o) => o.value === v)?.label ?? v;
  return (
    <div className="btn-row">
      {value.map((v) => (
        <button key={v} type="button" className="btn btn-sm" title="Remove"
          onClick={() => onChange(value.filter((x) => x !== v))}>
          {label(v)} ×
        </button>
      ))}
      <select className="row-input" value="" onChange={(e) => {
        if (e.target.value && !value.includes(e.target.value)) onChange([...value, e.target.value]);
      }}>
        <option value="">{placeholder}</option>
        {options.filter((o) => !value.includes(o.value)).map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

/** The parts table of a step or a recipe: bought parts by picker, prepared
 *  parts from the process's own recipes. */
function InputsTable({ inputs, names, prepared, onChange, onPick }: {
  inputs: ProcessInput[];
  names: Record<string, string>;
  prepared: { id: number; name: string }[];
  onChange: (v: ProcessInput[], delay?: number) => void;
  onPick: () => void;
}) {
  return (
    <>
      <DataTable
        rows={inputs}
        rowKey={inputKey}
        empty="Adds no parts."
        columns={[
          { key: "part", label: "Part, per unit", width: 60,
            get: (i) => (i.component_id ? names[String(i.component_id)] ?? `part ${i.component_id}` : `${i.mpn} (by MPN)`) },
          { key: "qty", label: "Qty", width: 25, interactive: false, get: (i) => i.qty,
            render: (i) => (
              <NumberInput className="row-input" value={i.qty} min={0}
                onChange={(v) => onChange(inputs.map((x) => (inputKey(x) === inputKey(i) ? { ...x, qty: v } : x)), 600)} />
            ) },
          { key: "rm", label: "", width: 15, interactive: false, get: () => "",
            render: (i) => (
              <button type="button" className="btn btn-sm"
                onClick={() => onChange(inputs.filter((x) => inputKey(x) !== inputKey(i)))}>Remove</button>
            ) },
        ]}
      />
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={onPick}>Add a bought part…</button>
        {prepared.length ? (
          <select className="row-input" value="" onChange={(e) => {
            const cid = Number(e.target.value);
            if (cid && !inputs.some((x) => x.component_id === cid)) onChange([...inputs, { component_id: cid, qty: 1 }]);
          }}>
            <option value="">add a prepared part…</option>
            {prepared.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        ) : null}
      </div>
    </>
  );
}

export default function ProcessEditor({ draft, internalParts, deployments, onSaved, onPartCreated }: {
  draft: ProcessVersionDetail;
  internalParts: { id: number; name: string }[];
  /** the project's deployments: a bench step names the one that says how it is done */
  deployments: ProcessDeployment[];
  onSaved: (v: ProcessVersionDetail) => void;
  onPartCreated: () => void;
}) {
  const dialog = useDialog();
  const [graph, setGraph] = useState<ProcessGraph>({
    steps: draft.graph.steps ?? [], route: draft.graph.route ?? [], prepared: draft.graph.prepared ?? [],
  });
  const [names, setNames] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(draft.parts).map(([k, p]) => [k, p.name])));
  // what the bought-part picker is adding to: a step key or a recipe key
  const [picking, setPicking] = useState<{ kind: "step" | "recipe"; key: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    for (const p of internalParts) setNames((n) => (n[String(p.id)] ? n : { ...n, [String(p.id)]: p.name }));
  }, [internalParts]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const save = (g: ProcessGraph, delay = 0) => {
    setGraph(g);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      updateProcessDraft(draft.id, { graph: g })
        .then((v) => { setError(null); onSaved(v); })
        .catch((err) => setError(errorMessage(err)));
    }, delay);
  };

  const stepLabel = (k: string) => graph.steps.find((s) => s.key === k)?.label || k;
  const groups = Array.from(new Set(graph.steps.map((s) => s.group).filter(Boolean))) as string[];
  const refOptions = (self: string) => [
    ...graph.steps.filter((s) => s.key !== self && s.kind !== "finish")
      .map((s) => ({ value: s.key, label: s.label || s.key })),
    ...groups.map((g) => ({ value: g, label: `one of: ${g}` })),
  ];
  const preparedParts = graph.prepared.map((r) => ({
    id: r.output_component_id, name: names[String(r.output_component_id)] ?? `part ${r.output_component_id}`,
  })).filter((p, i, a) => a.findIndex((x) => x.id === p.id) === i);

  const patchStep = (key: string, patch: Partial<ProcessStep>, delay = 0) =>
    save({ ...graph, steps: graph.steps.map((s) => (s.key === key ? { ...s, ...patch } : s)) }, delay);
  const patchRecipe = (key: string, patch: Partial<PreparedRecipe>, delay = 0) =>
    save({ ...graph, prepared: graph.prepared.map((r) => (r.key === key ? { ...r, ...patch } : r)) }, delay);

  /** A draft made before decision 0060 has no assembly step; it goes first,
   *  with no needs and no parts. */
  const addAssembly = () => {
    const key = nextKey("assembly", graph.steps.map((s) => s.key));
    save({ ...graph, steps: [{ key, label: "Board from the assembler", kind: "assembly", required: true },
                             ...graph.steps],
           route: [key, ...graph.route] });
  };

  const addStep = (kind: StepKind) => {
    const key = nextKey(kind === "step" ? "s" : kind, graph.steps.map((s) => s.key));
    const label = kind === "step" ? "" : KIND_LABEL[kind];
    const finishAt = graph.route.indexOf(graph.steps.find((s) => s.kind === "finish")?.key ?? "");
    const route = finishAt >= 0
      ? [...graph.route.slice(0, finishAt), key, ...graph.route.slice(finishAt)]
      : [...graph.route, key];
    save({ ...graph, steps: [...graph.steps, { key, label, kind, required: true, needs: [] }], route });
  };

  const removeStep = async (s: ProcessStep) => {
    if (!(await dialog.confirm(`Remove step “${s.label || s.key}”? Steps that need it lose that need.`,
      { title: "Remove step", confirmLabel: "Remove", tone: "danger" }))) return;
    save({
      ...graph,
      steps: graph.steps.filter((x) => x.key !== s.key).map((x) => ({
        ...x,
        needs: (x.needs ?? []).filter((r) => r !== s.key),
        needs_not: (x.needs_not ?? []).filter((r) => r !== s.key),
      })),
      route: graph.route.filter((k) => k !== s.key),
    });
  };

  const moveRoute = (i: number, d: -1 | 1) => {
    const r = [...graph.route];
    const j = i + d;
    if (j < 0 || j >= r.length) return;
    [r[i], r[j]] = [r[j], r[i]];
    save({ ...graph, route: r });
  };

  const addRecipe = async (value: string) => {
    let cid: number;
    if (value === "new") {
      const name = await dialog.prompt("Name the prepared part — what it IS once made, e.g. “V3 enclosure, drilled and printed”:",
        { title: "New prepared part" });
      if (!name?.trim()) return;
      try {
        const part = await createInternalPart(name.trim());
        cid = part.id;
        setNames((n) => ({ ...n, [String(part.id)]: part.name }));
        onPartCreated();
      } catch (err) {
        setError(errorMessage(err));
        return;
      }
    } else {
      cid = Number(value);
    }
    const key = nextKey("r", graph.prepared.map((r) => r.key));
    save({ ...graph, prepared: [...graph.prepared, { key, label: "", output_component_id: cid, inputs: [], preferred: true }] });
  };

  const removeRecipe = async (r: PreparedRecipe) => {
    if (!(await dialog.confirm(`Remove recipe “${r.label || r.key}”? Its stock lots are not touched.`,
      { title: "Remove recipe", confirmLabel: "Remove", tone: "danger" }))) return;
    save({ ...graph, prepared: graph.prepared.filter((x) => x.key !== r.key) });
  };

  if (!graph.steps.length) {
    return (
      <>
        {error ? <ErrorBanner message={error} /> : null}
        <p className="muted dim">
          Every process starts with four fixed steps: the supplier assembles the board, the batch
          receives it, the programming bench programs it, and a person marks it finished. Add
          those, then the steps in between.
        </p>
        <button type="button" className="btn btn-primary" onClick={() => save(templateGraph())}>
          Add the four fixed steps
        </button>
      </>
    );
  }

  return (
    <>
      {error ? <ErrorBanner message={error} /> : null}

      <FieldSet legend="Steps">
        <p className="muted dim">
          What can be done to a unit. A step says what the unit must have done before it; any
          step whose needs are met can run, in any order. Steps that share a choice name are
          options of one choice — one of them is done (a sticker or a UV print).
        </p>
        {graph.steps.map((s) => (
          <div key={s.key} className="card pad edit-card">
            <FieldRow>
              <Field label="Step">
                <input className="text" value={s.label ?? ""} placeholder="e.g. Put into enclosure"
                  onChange={(e) => patchStep(s.key, { label: e.target.value }, 600)} />
              </Field>
              <Field label="Kind" hint={`done at the ${STEP_STATION[s.kind]}`}>
                <select className="text" value={s.kind}
                  disabled={FIXED_KINDS.includes(s.kind)}
                  onChange={(e) => {
                    // A procedure belongs to a bench step of its kind; another kind drops it,
                    // or the draft could not be published and the field to clear it is hidden.
                    const kind = e.target.value as StepKind;
                    const keep = s.deployment_id && DEPLOYMENT_KIND_FOR[kind] === DEPLOYMENT_KIND_FOR[s.kind];
                    patchStep(s.key, { kind, deployment_id: keep ? s.deployment_id : null });
                  }}>
                  {(Object.keys(KIND_LABEL) as StepKind[])
                    .filter((k) => k === s.kind || !FIXED_KINDS.includes(k))
                    .map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
                </select>
              </Field>
              {s.kind !== "finish" ? (
                <Field label="Required">
                  <CheckField checked={!!s.required}
                    disabled={s.kind === "assembly" || s.kind === "receive" || s.kind === "program"}
                    onChange={(v) => patchStep(s.key, { required: v })}>
                    {s.required ? "required to finish" : "optional"}
                  </CheckField>
                </Field>
              ) : null}
              {DEPLOYMENT_KIND_FOR[s.kind] ? (
                <Field label="Procedure" hint={`the ${DEPLOYMENT_KIND_FOR[s.kind]} deployment the bench runs for this step`}>
                  <select className="text" value={s.deployment_id ?? ""}
                    onChange={(e) => patchStep(s.key, { deployment_id: Number(e.target.value) || null })}>
                    <option value="">none — the operator picks</option>
                    {deployments.filter((d) => d.kind === DEPLOYMENT_KIND_FOR[s.kind] || d.id === s.deployment_id)
                      .map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name}{d.current_version_no ? ` (v${d.current_version_no})` : " (nothing published)"}
                        </option>
                      ))}
                  </select>
                </Field>
              ) : null}
              {!FIXED_KINDS.includes(s.kind) ? (
                <Field label="Choice" hint="same name = options of one choice">
                  <input className="text" value={s.group ?? ""} placeholder="e.g. branding"
                    onChange={(e) => patchStep(s.key, { group: e.target.value.trim() }, 600)} />
                </Field>
              ) : null}
            </FieldRow>
            {s.kind === "finish" ? (
              <p className="muted dim">Needs every required step, by itself.</p>
            ) : s.kind === "receive" ? (
              <p className="muted dim">The first step: one unit per board the batch's assembly order delivered.</p>
            ) : s.kind === "assembly" ? (
              <p className="muted dim">
                Recorded from the batch's assembly order when the boards are received: the parts the
                supplier drew from our stock, and every board and assembly charge of the batch.
              </p>
            ) : (
              <>
                <Field label="Needs done before" wide>
                  <RefList value={s.needs ?? []} options={refOptions(s.key)} placeholder="add a step it needs…"
                    onChange={(v) => patchStep(s.key, { needs: v })} />
                </Field>
                <Field label="Must come before" wide hint="refused once one of these is done">
                  <RefList value={s.needs_not ?? []} options={refOptions(s.key)} placeholder="add…"
                    onChange={(v) => patchStep(s.key, { needs_not: v })} />
                </Field>
                <InputsTable inputs={s.inputs ?? []} names={names} prepared={preparedParts}
                  onChange={(v, d) => patchStep(s.key, { inputs: v }, d)}
                  onPick={() => setPicking({ kind: "step", key: s.key })} />
              </>
            )}
            {!FIXED_KINDS.includes(s.kind) ? (
              <div className="btn-row">
                <button type="button" className="btn btn-sm btn-danger" onClick={() => removeStep(s)}>Remove step</button>
              </div>
            ) : null}
          </div>
        ))}
        <div className="btn-row">
          <button type="button" className="btn btn-sm" onClick={() => addStep("step")}>Add a step</button>
          {!graph.steps.some((s) => s.kind === "assembly") ? (
            <button type="button" className="btn btn-sm" onClick={addAssembly}>Add the assembly step</button>
          ) : null}
          {!graph.steps.some((s) => s.kind === "test") ? (
            <button type="button" className="btn btn-sm" onClick={() => addStep("test")}>Add a test</button>
          ) : null}
          {!graph.steps.some((s) => s.kind === "mark_laser") ? (
            <button type="button" className="btn btn-sm" onClick={() => addStep("mark_laser")}>Add laser marking</button>
          ) : null}
          {!graph.steps.some((s) => s.kind === "label") ? (
            <button type="button" className="btn btn-sm" onClick={() => addStep("label")}>Add the barcode label</button>
          ) : null}
        </div>
      </FieldSet>

      <FieldSet legend="Main route">
        <p className="muted dim">The usual order. The map draws it and the batch page offers it first.</p>
        <DataTable
          rows={graph.route.map((k, i) => ({ k, i }))}
          rowKey={(r) => r.k}
          empty="The route is empty."
          columns={[
            { key: "n", label: "#", width: 8, numeric: true, get: (r) => r.i + 1 },
            { key: "step", label: "Step", width: 62, get: (r) => stepLabel(r.k) },
            { key: "act", label: "", width: 30, interactive: false, get: () => "",
              render: (r) => (
                <div className="btn-row">
                  <button type="button" className="btn btn-sm" disabled={r.i === 0} onClick={() => moveRoute(r.i, -1)}>Up</button>
                  <button type="button" className="btn btn-sm" disabled={r.i === graph.route.length - 1} onClick={() => moveRoute(r.i, 1)}>Down</button>
                  <button type="button" className="btn btn-sm" onClick={() => save({ ...graph, route: graph.route.filter((k) => k !== r.k) })}>Remove</button>
                </div>
              ) },
          ]}
        />
        <select className="row-input" value="" onChange={(e) => {
          if (e.target.value) save({ ...graph, route: [...graph.route, e.target.value] });
        }}>
          <option value="">add a step to the route…</option>
          {graph.steps.filter((s) => !graph.route.includes(s.key)).map((s) => (
            <option key={s.key} value={s.key}>{s.label || s.key}</option>
          ))}
        </select>
      </FieldSet>

      <FieldSet legend="Prepared parts">
        <p className="muted dim">
          Parts made before they meet a device — an enclosure drilled and printed, an antenna
          glued into an enclosure. Each is held as stock lots, and a step adds it to units.
        </p>
        {graph.prepared.map((r) => (
          <div key={r.key} className="card pad edit-card">
            <FieldRow>
              <Field label="Recipe">
                <input className="text" value={r.label ?? ""} placeholder="e.g. Drill and UV print"
                  onChange={(e) => patchRecipe(r.key, { label: e.target.value }, 600)} />
              </Field>
              <Field label="Makes">
                <span className="mono">{names[String(r.output_component_id)] ?? r.output_component_id}</span>
              </Field>
              <Field label="Expected scrap %">
                <NumberInput className="text num-input" value={r.expected_scrap_pct ?? 0} min={0} max={99}
                  onChange={(v) => patchRecipe(r.key, { expected_scrap_pct: v }, 600)} />
              </Field>
            </FieldRow>
            <InputsTable inputs={r.inputs} names={names}
              prepared={preparedParts.filter((p) => p.id !== r.output_component_id)}
              onChange={(v, d) => patchRecipe(r.key, { inputs: v }, d)}
              onPick={() => setPicking({ kind: "recipe", key: r.key })} />
            <div className="btn-row">
              <button type="button" className="btn btn-sm btn-danger" onClick={() => removeRecipe(r)}>Remove recipe</button>
            </div>
          </div>
        ))}
        <select className="row-input" value="" onChange={(e) => { if (e.target.value) addRecipe(e.target.value); }}>
          <option value="">add a prepared-part recipe…</option>
          <option value="new">New prepared part…</option>
          {internalParts.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </FieldSet>

      {picking ? (
        <ComponentPickDialog
          line={{ label: "" }}
          title="Pick the bought part"
          confirmLabel="Add"
          allowFreeText
          onClose={() => setPicking(null)}
          onPick={(cid, mpn) => {
            // A part the library does not hold (a shipping carton) is named by
            // the MPN its purchases carry, which is how the pool keys it.
            const target = picking;
            setPicking(null);
            const inp: ProcessInput = cid ? { component_id: cid, qty: 1 } : { mpn: mpn.trim(), qty: 1 };
            if (!cid && !inp.mpn) return;
            if (cid) setNames((n) => ({ ...n, [String(cid)]: n[String(cid)] ?? mpn }));
            if (target.kind === "step") {
              const s = graph.steps.find((x) => x.key === target.key);
              if (s && !(s.inputs ?? []).some((x) => inputKey(x) === inputKey(inp))) {
                patchStep(s.key, { inputs: [...(s.inputs ?? []), inp] });
              }
            } else {
              const r = graph.prepared.find((x) => x.key === target.key);
              if (r && !r.inputs.some((x) => inputKey(x) === inputKey(inp))) {
                patchRecipe(r.key, { inputs: [...r.inputs, inp] });
              }
            }
          }}
        />
      ) : null}
    </>
  );
}
