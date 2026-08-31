/** Stackup and production-rule editors.
 *
 *  Both save to the platform, not to the browser: a stackup someone builds here is
 *  a shared fact about how boards get made, so it belongs in Postgres next to the
 *  rest of the library. The built-in fab presets are read-only.
 */
import { useEffect, useState } from "react";
import {
  fsDeleteRules,
  fsDeleteStackup,
  fsSaveRules,
  fsSaveStackup,
  type FsFinish,
  type FsLayer,
  type FsMaterial,
  type FsRuleSet,
  type FsStackup,
} from "../../api";
import { errorMessage } from "../../api";
import NumberInput from "../../components/NumberInput";

export interface StackupEditorProps {
  stackup: FsStackup;
  materials: FsMaterial[];
  finishes: FsFinish[];
  rules: FsRuleSet | undefined;
  onClose: () => void;
  onSaved: (s: FsStackup) => void;
  onDeleted: (id: string) => void;
}

interface Draft {
  id: string | null;
  name: string;
  layers: FsLayer[];
  soldermask: FsStackup["soldermask"];
  finish: FsStackup["finish"];
  mask_geom: Record<string, number>;
}

const toDraft = (s: FsStackup): Draft => ({
  id: s.builtin ? null : s.id,
  name: s.builtin ? `${s.name} (copy)` : s.name,
  layers: s.layers.map((l) => ({ ...l })),
  soldermask: s.soldermask ? { ...s.soldermask } : null,
  finish: s.finish ? { ...s.finish } : null,
  mask_geom: { ...s.mask_geom },
});

export function StackupEditor({ stackup, materials, finishes, rules, onClose, onSaved, onDeleted }: StackupEditorProps) {
  const [d, setD] = useState<Draft>(() => toDraft(stackup));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => setD(toDraft(stackup)), [stackup]);

  const set = (patch: Partial<Draft>) => setD((old) => ({ ...old, ...patch }));
  const setLayer = (i: number, patch: Partial<FsLayer>) =>
    setD((old) => ({ ...old, layers: old.layers.map((l, k) => (k === i ? { ...l, ...patch } : l)) }));

  const addLayer = (kind: "copper" | "dielectric") =>
    setD((old) => ({
      ...old,
      layers: [
        ...old.layers,
        kind === "copper"
          ? { type: "copper", name: `L${old.layers.filter((l) => l.type === "copper").length + 1}`, thickness_mm: 0.035 }
          : { type: "dielectric", label: "prepreg", material: materials[0]?.id ?? null, thickness_mm: 0.2 },
      ],
    }));

  const save = async (asNew: boolean) => {
    setBusy(true);
    setErr("");
    try {
      const body = {
        id: asNew ? null : d.id,
        name: d.name,
        layers: d.layers,
        soldermask: d.soldermask,
        finish: d.finish,
        mask_geom: d.mask_geom,
      };
      onSaved(await fsSaveStackup(body));
      onClose();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!d.id) return;
    setBusy(true);
    try {
      await fsDeleteStackup(d.id);
      onDeleted(d.id);
      onClose();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fs-modal" role="dialog" aria-label="Stackup editor">
      <div className="fs-modal-box card pad">
        <div className="fs-modal-head">
          <b>Stackup</b>
          <label className="fs-field">
            <span>Name</span>
            <input className="text" value={d.name} onChange={(e) => set({ name: e.target.value })} />
          </label>
        </div>

        <table className="data fs-stack-edit">
          <thead>
            <tr>
              <th>Layer</th>
              <th>Material</th>
              <th>Type</th>
              <th>Thickness mm</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr className="fs-coat">
              <td>
                <label className="fs-check">
                  <input
                    type="checkbox"
                    checked={!!d.soldermask}
                    onChange={(e) =>
                      set({
                        soldermask: e.target.checked
                          ? {
                              material: "jlc_soldermask",
                              above_substrate_mm: Number(rules?.mask_c1 ?? 0.0305),
                              above_trace_mm: Number(rules?.mask_c2 ?? 0.0152),
                            }
                          : null,
                      })
                    }
                  />
                  Solder mask
                </label>
              </td>
              <td className="muted">overlay</td>
              <td className="muted">both sides</td>
              <td>
                {d.soldermask ? (
                  <>
                    <NumberInput
                      className="text fs-num"
                      step={0.005}
                      value={d.soldermask.above_substrate_mm}
                      onChange={(v) => set({ soldermask: { ...d.soldermask!, above_substrate_mm: v } })}
                    />
                    {" / "}
                    <NumberInput
                      className="text fs-num"
                      step={0.005}
                      value={d.soldermask.above_trace_mm}
                      onChange={(v) => set({ soldermask: { ...d.soldermask!, above_trace_mm: v } })}
                    />
                  </>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className="muted">substrate / trace</td>
            </tr>
            <tr className="fs-coat">
              <td>
                <label className="fs-check">
                  <input
                    type="checkbox"
                    checked={!!d.finish}
                    onChange={(e) =>
                      set({
                        finish: e.target.checked
                          ? { type: finishes[0]?.type ?? "none / OSP", thickness_um: finishes[0]?.thickness_um ?? 0 }
                          : null,
                      })
                    }
                  />
                  Surface finish
                </label>
              </td>
              <td colSpan={2}>
                {d.finish ? (
                  <select
                    className="text"
                    value={d.finish.type}
                    onChange={(e) => {
                      const f = finishes.find((x) => x.type === e.target.value);
                      set({ finish: { type: e.target.value, thickness_um: f?.thickness_um ?? d.finish!.thickness_um } });
                    }}
                  >
                    {finishes.map((f) => (
                      <option key={f.type} value={f.type}>
                        {f.type}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td>
                {d.finish ? (
                  <NumberInput
                    className="text fs-num"
                    step={0.5}
                    value={d.finish.thickness_um}
                    onChange={(v) => set({ finish: { ...d.finish!, thickness_um: v } })}
                  />
                ) : null}
              </td>
              <td className="muted">µm, on exposed copper</td>
            </tr>
            {d.layers.map((l, i) => (
              <tr key={`${l.type}${i}`}>
                <td>
                  {l.type === "copper" ? (
                    <input className="text fs-num" value={l.name ?? ""} onChange={(e) => setLayer(i, { name: e.target.value })} />
                  ) : (
                    <input className="text" value={l.label ?? ""} onChange={(e) => setLayer(i, { label: e.target.value })} />
                  )}
                </td>
                <td>
                  {l.type === "dielectric" ? (
                    <select
                      className="text"
                      value={l.material ?? ""}
                      onChange={(e) => setLayer(i, { material: e.target.value || null })}
                    >
                      <option value="">custom Dk</option>
                      {materials
                        .filter((m) => m.kind !== "conductor")
                        .map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                          </option>
                        ))}
                    </select>
                  ) : (
                    <span className="muted">copper</span>
                  )}
                </td>
                <td className="muted">{l.type}</td>
                <td>
                  <NumberInput
                    className="text fs-num"
                    step={0.001}
                    value={l.thickness_mm}
                    onChange={(v) => setLayer(i, { thickness_mm: v })}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setD((old) => ({ ...old, layers: old.layers.filter((_, k) => k !== i) }))}
                  >
                    remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="fs-row">
          <button type="button" className="btn btn-sm" onClick={() => addLayer("copper")}>
            + copper layer
          </button>
          <button type="button" className="btn btn-sm" onClick={() => addLayer("dielectric")}>
            + dielectric
          </button>
          <span className="muted">Top to bottom. Copper layers are named L1…Ln.</span>
        </div>

        {err ? <p className="fs-error">{err}</p> : null}
        <div className="fs-modal-foot">
          {d.id ? (
            <button type="button" className="btn btn-sm btn-danger" onClick={remove} disabled={busy}>
              Delete
            </button>
          ) : null}
          <span className="fs-spacer" />
          <button type="button" className="btn btn-sm" onClick={() => save(true)} disabled={busy}>
            Save as new
          </button>
          <button type="button" className="btn btn-sm btn-accent" onClick={() => save(false)} disabled={busy}>
            Save
          </button>
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- rules

const RULE_FIELDS: { key: string; label: string; step: number; group: string }[] = [
  { key: "min_width_2l", label: "2-layer trace width", step: 0.01, group: "Trace / space minimum (mm)" },
  { key: "min_space_2l", label: "2-layer space", step: 0.01, group: "Trace / space minimum (mm)" },
  { key: "min_width_ml", label: "multilayer trace width", step: 0.01, group: "Trace / space minimum (mm)" },
  { key: "min_space_ml", label: "multilayer space", step: 0.01, group: "Trace / space minimum (mm)" },
  { key: "via_min_hole", label: "via hole", step: 0.05, group: "Via minimum (mm)" },
  { key: "via_min_diameter", label: "via pad ⌀", step: 0.05, group: "Via minimum (mm)" },
  { key: "drill_to_copper", label: "drill to copper", step: 0.05, group: "Via minimum (mm)" },
  { key: "via_plating_um", label: "plating (µm)", step: 1, group: "Via process" },
  { key: "via_drill_oversize", label: "drill oversize (mm)", step: 0.01, group: "Via process" },
  { key: "etch_outer_um", label: "outer, 1 oz (µm)", step: 0.5, group: "Etch undercut per side" },
  { key: "etch_inner_um", label: "inner, 0.5 oz (µm)", step: 0.5, group: "Etch undercut per side" },
  { key: "mask_dk", label: "solder mask Dk", step: 0.1, group: "Coating defaults" },
  { key: "mask_tand", label: "solder mask tanδ", step: 0.001, group: "Coating defaults" },
  { key: "mask_c1", label: "mask over substrate (mm)", step: 0.005, group: "Coating defaults" },
  { key: "mask_c2", label: "mask over trace (mm)", step: 0.005, group: "Coating defaults" },
  { key: "mask_expansion", label: "mask opening expansion (mm)", step: 0.01, group: "Coating defaults" },
  { key: "finish_um", label: "finish thickness (µm)", step: 0.5, group: "Coating defaults" },
  { key: "impedance_tolerance_pct", label: "impedance tolerance (%)", step: 1, group: "Other" },
];

export interface RulesEditorProps {
  ruleset: FsRuleSet;
  finishes: FsFinish[];
  onClose: () => void;
  onSaved: (r: FsRuleSet) => void;
  onDeleted: (id: string) => void;
}

export function RulesEditor({ ruleset, finishes, onClose, onSaved, onDeleted }: RulesEditorProps) {
  const [d, setD] = useState<Record<string, unknown>>(() => ({
    ...ruleset,
    id: ruleset.builtin ? null : ruleset.id,
    name: ruleset.builtin ? `${ruleset.name} (copy)` : ruleset.name,
    via_sizes: (ruleset.via_sizes ?? []).map((v) => ({ ...v })),
  }));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const groups = [...new Set(RULE_FIELDS.map((f) => f.group))];
  const sizes = (d.via_sizes as { name: string; hole: number; pad: number }[]) ?? [];

  const save = async (asNew: boolean) => {
    setBusy(true);
    setErr("");
    try {
      onSaved(await fsSaveRules({ ...d, id: asNew ? null : d.id }));
      onClose();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!d.id) return;
    setBusy(true);
    try {
      await fsDeleteRules(String(d.id));
      onDeleted(String(d.id));
      onClose();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fs-modal" role="dialog" aria-label="Production rules editor">
      <div className="fs-modal-box card pad">
        <div className="fs-modal-head">
          <b>Production rules</b>
          <label className="fs-field">
            <span>Name</span>
            <input className="text" value={String(d.name ?? "")} onChange={(e) => setD({ ...d, name: e.target.value })} />
          </label>
        </div>

        <div className="fs-rules-grid">
          {groups.map((g) => (
            <fieldset key={g} className="fs-fieldset">
              <legend>{g}</legend>
              {RULE_FIELDS.filter((f) => f.group === g).map((f) => (
                <label key={f.key} className="fs-field-row">
                  <span>{f.label}</span>
                  <NumberInput
                    className="text fs-num"
                    step={f.step}
                    value={(d[f.key] as number | null) ?? null}
                    onChange={(v) => setD({ ...d, [f.key]: v })}
                    onEmpty={() => setD({ ...d, [f.key]: null })}
                  />
                </label>
              ))}
              {g === "Coating defaults" ? (
                <label className="fs-field-row">
                  <span>finish type</span>
                  <select
                    className="text"
                    value={String(d.finish_type ?? "")}
                    onChange={(e) => setD({ ...d, finish_type: e.target.value })}
                  >
                    {finishes.map((f) => (
                      <option key={f.type} value={f.type}>
                        {f.type}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
            </fieldset>
          ))}
          <fieldset className="fs-fieldset fs-span">
            <legend>Via sizes — the first is the default for every structure</legend>
            <table className="data">
              <thead>
                <tr>
                  <th>name</th>
                  <th>hole mm</th>
                  <th>pad ⌀ mm</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sizes.map((v, i) => (
                  <tr key={i}>
                    <td>
                      <input
                        className="text"
                        value={v.name}
                        onChange={(e) =>
                          setD({ ...d, via_sizes: sizes.map((x, k) => (k === i ? { ...x, name: e.target.value } : x)) })
                        }
                      />
                    </td>
                    <td>
                      <NumberInput
                        className="text fs-num"
                        step={0.05}
                        value={v.hole}
                        onChange={(n) =>
                          setD({ ...d, via_sizes: sizes.map((x, k) => (k === i ? { ...x, hole: n } : x)) })
                        }
                      />
                    </td>
                    <td>
                      <NumberInput
                        className="text fs-num"
                        step={0.05}
                        value={v.pad}
                        onChange={(n) =>
                          setD({ ...d, via_sizes: sizes.map((x, k) => (k === i ? { ...x, pad: n } : x)) })
                        }
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => setD({ ...d, via_sizes: sizes.filter((_, k) => k !== i) })}
                      >
                        remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setD({ ...d, via_sizes: [...sizes, { name: "0.3 / 0.6", hole: 0.3, pad: 0.6 }] })}
            >
              + size
            </button>
          </fieldset>
        </div>

        {err ? <p className="fs-error">{err}</p> : null}
        <div className="fs-modal-foot">
          {d.id ? (
            <button type="button" className="btn btn-sm btn-danger" onClick={remove} disabled={busy}>
              Delete
            </button>
          ) : null}
          <span className="fs-spacer" />
          <button type="button" className="btn btn-sm" onClick={() => save(true)} disabled={busy}>
            Save as new
          </button>
          <button type="button" className="btn btn-sm btn-accent" onClick={() => save(false)} disabled={busy}>
            Save
          </button>
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
