/** Stackup and production-rule editors.
 *
 *  Both save to the platform, not to the browser: a stackup someone builds here is
 *  a shared fact about how boards get made, so it belongs in Postgres next to the
 *  rest of the library. The built-in fab presets are read-only.
 */
import { useEffect, useMemo, useState } from "react";
import {
  fsDeleteRules,
  fsDeleteStackup,
  fsSaveRules,
  fsSaveStackup,
  type FsFinish,
  type FsLayer,
  type FsMaterial,
  type FsRuleSet,
  type FsStackFace,
  type FsStackRow,
  type FsStackup,
} from "../../api";
import { errorMessage } from "../../api";
import NumberInput from "../../components/NumberInput";
import SiInput from "../../components/SiInput";
import { COPPER_CHOICES, copperWeight, formatSi, maskOverTrace } from "../../components/si";
import StackupTable, { StackupLegend } from "../../components/StackupTable";
import { useModal } from "../../components/modal";
import { useDialog } from "../../components/Dialog";

export interface StackupEditorProps {
  stackup: FsStackup;
  materials: FsMaterial[];
  finishes: FsFinish[];
  rules: FsRuleSet | undefined;
  onClose: () => void;
  onSaved: (s: FsStackup) => void;
  onDeleted: (id: string) => void;
}

/** The outer layers of ONE face. Each is present or absent, which is what makes them
 *  addable and removable rather than a checkbox: a board really is built with legend
 *  on one side only, or a different finish per face. */
export interface FaceDraft {
  silkscreen: { present: true } | null;
  soldermask: string | null;
  finish: FsStackup["finish"];
}

interface Draft {
  id: string | null;
  name: string;
  layers: FsLayer[];
  faces: { top: FaceDraft; bottom: FaceDraft };
  mask_geom: Record<string, number>;
}

/** Which outer layers a face may carry, outermost first. The order is the physical
 *  one and is not a choice, so these rows cannot be moved — only added and removed. */
const OUTER: { key: keyof FaceDraft; kind: "overlay" | "mask" | "finish"; label: string }[] = [
  { key: "silkscreen", kind: "overlay", label: "Overlay" },
  { key: "soldermask", kind: "mask", label: "Solder mask" },
  { key: "finish", kind: "finish", label: "Surface finish" },
];

const dielectricDefault = (materials: FsMaterial[]): string | null =>
  materials.find((m) => m.use === "laminate" && /prepreg/i.test(m.name))?.id ??
  materials.find((m) => m.use === "laminate")?.id ??
  null;

const faceDraft = (f: Record<string, unknown> | undefined): FaceDraft => ({
  silkscreen: f?.silkscreen ? { present: true } : null,
  soldermask: (f?.soldermask as string) ?? null,
  finish: (f?.finish as FsStackup["finish"]) ?? null,
});

const toDraft = (s: FsStackup): Draft => ({
  id: s.builtin ? null : s.id,
  name: s.builtin ? `${s.name} (copy)` : s.name,
  layers: s.layers.map((l) => ({ ...l })),
  faces: {
    top: faceDraft(s.faces?.top),
    bottom: faceDraft(s.faces?.bottom),
  },
  mask_geom: { ...s.mask_geom },
});

/** The draft as drawable rows, plus a map back to what each row edits.
 *
 *  Shaping only — no alignment and no tolerances. The comparison logic stays in one
 *  place on the server (`field_state.stack_rows`); this exists because a draft being
 *  typed into cannot round-trip to the server for every keystroke.
 *
 *  Names are NOT carried: copper is L1..Ln by position and a dielectric is described
 *  by its material and where it sits, both generated here and again on the server
 *  (`StackupLibrary.normalise`) so the file and the page can never disagree. */
function draftRows(d: Draft, materials: FsMaterial[]): { rows: FsStackRow[]; meta: RowMeta[] } {
  const rows: FsStackRow[] = [];
  const meta: RowMeta[] = [];
  const face = (o: Partial<FsStackFace>): FsStackFace => ({
    name: "", material: "", thickness_mm: null, dk: null, tand: null, weight: "", type: "", ...o,
  });
  const row = (kind: FsStackRow["kind"], stackup: FsStackFace, index: number | null = null): FsStackRow => ({
    kind, index, board: null, stackup, ok: {}, advisory: {}, row_ok: null, severity: "none", note: "",
  });

  const outerRows = (side: "top" | "bottom") => {
    const f = d.faces[side];
    const order = side === "top" ? OUTER : [...OUTER].reverse();
    const word = side === "top" ? "Top" : "Bottom";
    for (const o of order) {
      const v = f[o.key];
      if (!v) continue;
      if (o.kind === "overlay") {
        rows.push(row("overlay", face({ name: `${word} Overlay`, material: "legend ink" })));
      } else if (o.kind === "mask") {
        const mat = materials.find((m) => m.id === v);
        rows.push(row("mask", face({ name: `${word} Solder`, material: mat?.name ?? String(v) })));
      } else {
        const fin = v as NonNullable<FsStackup["finish"]>;
        rows.push(row("finish", face({ name: fin.type, thickness_mm: fin.thickness_um / 1000 })));
      }
      meta.push({ kind: o.kind, layer: null, side, key: o.key });
    }
  };

  outerRows("top");
  let cu = 0;
  d.layers.forEach((l, i) => {
    const copper = l.type === "copper";
    if (copper) cu += 1;
    const mat = l.material ? materials.find((m) => m.id === l.material) : undefined;
    const kind: FsStackRow["kind"] = copper
      ? "copper"
      : /core/i.test(mat?.name ?? l.label ?? "")
        ? "core"
        : /prepreg/i.test(mat?.name ?? l.label ?? "")
          ? "prepreg"
          : "dielectric";
    // Copper is named by where it is; a dielectric by what it is. Neither is typed —
    // the file still gets a full generated name from the server
    // (`StackupLibrary.normalise`), which is the only place it matters.
    const name = copper ? `L${cu}` : kind === "core" ? "Core" : kind === "prepreg" ? "Prepreg" : "Dielectric";
    rows.push(
      row(
        kind,
        face({
          name,
          material: copper ? "" : mat?.name ?? l.material ?? "",
          thickness_mm: l.thickness_mm,
          dk: mat?.points?.[0]?.dk ?? l.eps_r ?? null,
        }),
        copper ? cu : null,
      ),
    );
    meta.push({ kind: copper ? "copper" : "dielectric", layer: i });
  });
  outerRows("bottom");
  return { rows, meta };
}

/** Would this move leave the stack unbuildable? Returns the reason, or "".
 *
 *  Refusing the move is the point: a warning after the fact lets the file be saved in
 *  a state no fab can build, and the solver would model it without complaint. Two
 *  dielectrics in a row are fine; two copper layers are not. */
function moveBlocked(layers: FsLayer[], i: number, dir: -1 | 1): string {
  const j = i + dir;
  if (j < 0 || j >= layers.length) return "Already at the end of the stack.";
  const next = [...layers];
  [next[i], next[j]] = [next[j], next[i]];
  if (next[0].type !== "copper") return "The stack has to start with a copper layer.";
  if (next[next.length - 1].type !== "copper") return "The stack has to end with a copper layer.";
  for (let k = 1; k < next.length; k += 1) {
    if (next[k].type === "copper" && next[k - 1].type === "copper")
      return "That would put two copper layers against each other, with nothing between them.";
  }
  return "";
}

function removeBlocked(layers: FsLayer[], i: number): string {
  const next = layers.filter((_, k) => k !== i);
  if (next.filter((l) => l.type === "copper").length < 2) return "A stackup needs at least two copper layers.";
  if (!next.length || next[0].type !== "copper") return "The stack has to start with a copper layer.";
  if (next[next.length - 1].type !== "copper") return "The stack has to end with a copper layer.";
  for (let k = 1; k < next.length; k += 1) {
    if (next[k].type === "copper" && next[k - 1].type === "copper")
      return "That would leave two copper layers against each other. Remove one of them instead.";
  }
  return "";
}

interface RowMeta {
  kind: string;
  /** Index into `Draft.layers`, or null for an outer layer. */
  layer: number | null;
  /** Which face an outer layer belongs to. */
  side?: "top" | "bottom";
  key?: keyof FaceDraft;
}

export function StackupEditor({ stackup, materials, finishes, onClose, onSaved, onDeleted }: StackupEditorProps) {
  const [d, setD] = useState<Draft>(() => toDraft(stackup));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => setD(toDraft(stackup)), [stackup]);

  const { rows, meta } = useMemo(() => draftRows(d, materials), [d, materials]);
  const modal = useModal(onClose);
  const dialog = useDialog();

  /** Things a reorder or a delete can leave behind that no fab would build.
   *
   *  Adjacent DIELECTRICS are fine and common — JLC06121H-3313A lists three 7628
   *  sheets in one gap. Adjacent COPPER is not: there is no insulation between them,
   *  and the solver would not complain, it would quietly model a different board. */
  const faults = useMemo(() => {
    const out: string[] = [];
    const cu = d.layers.filter((l) => l.type === "copper").length;
    for (let i = 1; i < d.layers.length; i += 1) {
      if (d.layers[i].type === "copper" && d.layers[i - 1].type === "copper") {
        const a = d.layers[i - 1].name || `layer ${i}`;
        const b = d.layers[i].name || `layer ${i + 1}`;
        out.push(`${a} and ${b} sit against each other with no dielectric between them.`);
      }
    }
    if (d.layers.length && d.layers[0].type !== "copper") out.push("The stack does not start with a copper layer.");
    if (d.layers.length && d.layers[d.layers.length - 1].type !== "copper")
      out.push("The stack does not end with a copper layer.");
    if (cu < 2) out.push("A stackup needs at least two copper layers.");
    return out;
  }, [d.layers]);

  const set = (patch: Partial<Draft>) => setD((old) => ({ ...old, ...patch }));
  const setLayer = (i: number, patch: Partial<FsLayer>) =>
    setD((old) => ({ ...old, layers: old.layers.map((l, k) => (k === i ? { ...l, ...patch } : l)) }));

  /** Move a layer one place up or down the stack.
   *
   *  Indexes into `Draft.layers`, NOT into the table's rows: the table also carries
   *  the mask and finish rows, so a row-index swap would move a sheet into the solder
   *  mask. Mostly used to order the prepreg sheets inside one gap, where the fab lists
   *  several and the order decides which one sits against which copper layer. */
  const moveLayer = (i: number, dir: -1 | 1) =>
    setD((old) => {
      const j = i + dir;
      if (j < 0 || j >= old.layers.length) return old;
      const layers = [...old.layers];
      [layers[i], layers[j]] = [layers[j], layers[i]];
      return { ...old, layers };
    });

  const setFace = (side: "top" | "bottom", patch: Partial<FaceDraft>) =>
    setD((old) => ({ ...old, faces: { ...old.faces, [side]: { ...old.faces[side], ...patch } } }));

  /** Default contents for an outer layer the user just added. */
  const newOuter = (key: keyof FaceDraft): FaceDraft[keyof FaceDraft] => {
    if (key === "silkscreen") return { present: true };
    if (key === "soldermask") return materials.find((m) => m.use === "soldermask")?.id ?? "jlc_soldermask";
    return { type: finishes[0]?.type ?? "none / OSP", thickness_um: finishes[0]?.thickness_um ?? 0 };
  };

  /** Adding to one face mirrors onto the other when that face has nothing there yet.
   *  A board is nearly always finished the same way on both sides, and the user can
   *  still remove or change either one afterwards. */
  const addOuter = (side: "top" | "bottom", key: keyof FaceDraft) =>
    setD((old) => {
      const other = side === "top" ? "bottom" : "top";
      const value = newOuter(key) as never;
      const faces = { ...old.faces, [side]: { ...old.faces[side], [key]: value } };
      if (!old.faces[other][key]) faces[other] = { ...old.faces[other], [key]: value };
      return { ...old, faces };
    });

  const addLayer = (kind: "copper" | "dielectric") =>
    setD((old) => ({
      ...old,
      // A copper layer added on its own would sit against the copper already at the
      // bottom, which is not buildable — so it arrives with the dielectric it needs.
      // That is the rule the user cannot break rather than a warning after the fact.
      layers: [
        ...old.layers,
        ...(kind === "copper"
          ? [
              { type: "dielectric" as const, material: dielectricDefault(materials), thickness_mm: 0.1 },
              { type: "copper" as const, thickness_mm: 0.0152 },
            ]
          : [{ type: "dielectric" as const, material: dielectricDefault(materials), thickness_mm: 0.1 }]),
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
        // Per face. The server keeps reading a bare value as "both faces", so a
        // stackup written before faces existed still loads; what it writes back is
        // always the explicit shape.
        silkscreen: { top: d.faces.top.silkscreen, bottom: d.faces.bottom.silkscreen },
        soldermask: { top: d.faces.top.soldermask, bottom: d.faces.bottom.soldermask },
        finish: { top: d.faces.top.finish, bottom: d.faces.bottom.finish },
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
    // A stackup is shared by every project on the platform, and a board assigned to
    // this one is left pointing at something that no longer exists. One click was not
    // proportionate to that.
    if (
      !(await dialog.confirm(
        `Delete the stackup “${d.name}”? It is shared by every project here, not just this page. ` +
          `Any board assigned to it keeps the assignment and will resolve to nothing, and its solved ` +
          `impedance profiles lose the stackup they were computed against.`,
        { title: "Delete stackup", confirmLabel: "Delete", tone: "danger" },
      ))
    )
      return;
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
    <div className="fs-modal" role="dialog" aria-label="Stackup editor" {...modal.backdropProps}>
      <div className="fs-modal-box card pad" {...modal.cardProps}>
        <div className="fs-modal-head">
          <b>Stackup</b>
          <label className="field">
            <span>Name</span>
            <input className="text" value={d.name} onChange={(e) => set({ name: e.target.value })} />
          </label>
        </div>

        {/* The SAME table every other view of a stackup uses
            (components/StackupTable.tsx), with controls dropped into the cells. The
            editor used to be its own markup with its own greys, so the thing you edit
            looked nothing like the thing you then read on a project. */}
        <StackupTable
          rows={rows}
          mode="single"
          side="stackup"
          renderCell={(_row, col, i) => {
            const m = meta[i];

            // ---- an outer layer: it belongs to ONE face and has ONE legal position,
            //      so the only things it offers are its own settings.
            if (m.layer == null && m.side && m.key) {
              const f = d.faces[m.side];
              if (m.key === "silkscreen") {
                if (col === "material") return <span className="muted">legend ink</span>;
                if (col === "thickness")
                  return <span className="muted">not published</span>;
                return undefined;
              }
              if (m.key === "soldermask") {
                if (col === "material")
                  return (
                    <select
                      className="text"
                      value={f.soldermask ?? ""}
                      onChange={(e) => setFace(m.side!, { soldermask: e.target.value })}
                    >
                      {materials
                        .filter((mm) => mm.use === "soldermask")
                        .map((mm) => (
                          <option key={mm.id} value={mm.id}>
                            {mm.name}
                          </option>
                        ))}
                    </select>
                  );
                // The box in Thickness, the sentence it drives in the Dk cell beside
                // it — which a mask row has no use for. Crammed into one cell the
                // sentence was the half that got the ellipsis.
                if (col === "dk")
                  return (
                    <span className="muted stk-derived">
                      above substrate / {formatSi(d.mask_geom.above_trace_mm, "length")} above trace
                    </span>
                  );
                if (col === "thickness")
                  return (
                    <span className="field-inline">
                      <SiInput
                        className="fs-num"
                        aria-label="Coating above the substrate"
                        value={d.mask_geom.above_substrate_mm}
                        min={0}
                        // One number, and the other follows it. They are one coating,
                        // and a pair that can be typed independently is a pair that
                        // ends up describing no real ink.
                        onChange={(v) =>
                          set({
                            mask_geom: {
                              ...d.mask_geom,
                              above_substrate_mm: v,
                              above_trace_mm: maskOverTrace(v),
                            },
                          })
                        }
                        help={
                          <>
                            Coating above the bare substrate. JLCPCB publishes 1.2 mil (30.5 um) over the substrate and
                            0.6 mil (15.2 um) over a trace — exactly half — so the figure over a trace follows this one
                            and is not typed.
                          </>
                        }
                      />
                    </span>
                  );
                return undefined;
              }
              // finish
              const fin = f.finish!;
              if (col === "name") return <span>{m.side === "top" ? "Top Finish" : "Bottom Finish"}</span>;
              if (col === "material")
                return (
                  <select
                    className="text"
                    value={fin.type}
                    onChange={(e) => {
                      const preset = finishes.find((x) => x.type === e.target.value);
                      setFace(m.side!, {
                        finish: { type: e.target.value, thickness_um: preset?.thickness_um ?? fin.thickness_um },
                      });
                    }}
                  >
                    {finishes.map((x) => (
                      <option key={x.type} value={x.type}>
                        {x.type}
                      </option>
                    ))}
                  </select>
                );
              if (col === "thickness")
                return (
                  <SiInput
                    className="fs-num"
                    aria-label="Surface finish thickness"
                    assume="um"
                    fixedUnit="um"
                    min={0}
                    value={fin.thickness_um / 1000}
                    onChange={(v) => setFace(m.side!, { finish: { ...fin, thickness_um: v * 1000 } })}
                    help={<>Thickness on exposed copper. A bare number means um here; 0.0045mm works too.</>}
                  />
                );
              return undefined;
            }

            // ---- a copper or dielectric layer
            const li = m.layer;
            if (li == null) return undefined;
            const l = d.layers[li];
            if (col === "material")
              return l.type === "dielectric" ? (
                <select
                  className="text"
                  value={l.material ?? ""}
                  onChange={(e) => setLayer(li, { material: e.target.value || null })}
                >
                  <option value="">custom Dk</option>
                  {materials
                    .filter((mm) => mm.use === "laminate")
                    .map((mm) => (
                      <option key={mm.id} value={mm.id}>
                        {mm.name}
                      </option>
                    ))}
                </select>
              ) : (
                <span className="muted">copper</span>
              );
            if (col === "thickness") {
              const copper = l.type === "copper";
              return (
                <SiInput
                  className="fs-num"
                  quantity="length"
                  value={l.thickness_mm}
                  onChange={(v) => setLayer(li, { thickness_mm: v })}
                  min={0}
                  validate={
                    copper
                      ? (v) => {
                          if (copperWeight(v)) return "";
                          // A bare number is read as mm, so "35" means 35 mm. Rather than
                          // guess that a big number must have meant micrometres — which
                          // would quietly change what was typed — say what was read and
                          // what it probably meant.
                          const asUm = copperWeight(v / 1000);
                          return asUm
                            ? `Read as ${formatSi(v, "length")}, which is not a copper foil. Did you mean ${formatSi(
                                v / 1000,
                                "length",
                              )} (${asUm.label})? Type the unit — "um" — to be sure.`
                            : `${formatSi(v, "length")} is not a standard copper foil.`;
                        }
                      : undefined
                  }
                  help={
                    copper ? (
                      <>
                        Copper comes in foil weights, so only a few thicknesses exist:{" "}
                        <b>{COPPER_CHOICES}</b>. Both the nominal weight and the figure a fab publishes as built are
                        accepted — JLCPCB states its half-ounce inner layers as 15.2 um, which is the etched thickness,
                        not the 17.5 um nominal.
                      </>
                    ) : (
                      <>Type any unit: 0.2104, 210.4um, 8.3mil. A bare number means mm.</>
                    )
                  }
                />
              );
            }
            return undefined;
          }}
          rowActions={(_r, i) => {
            const m = meta[i];
            if (m.layer == null) {
              // An outer layer has ONE legal position, so it cannot be moved — only
              // taken off. Saying so is better than two dead arrows.
              return (
                <span className="stk-rowbtns">
                  <button
                    type="button"
                    className="btn btn-sm"
                    title="Remove this layer from this face"
                    onClick={() => setFace(m.side!, { [m.key!]: null } as Partial<FaceDraft>)}
                  >
                    remove
                  </button>
                </span>
              );
            }
            const li = m.layer;
            return (
              <span className="stk-rowbtns">
                <button
                  type="button"
                  className="btn btn-sm"
                  title={moveBlocked(d.layers, li, -1) || "Move this layer up"}
                  aria-label="Move up"
                  disabled={!!moveBlocked(d.layers, li, -1)}
                  onClick={() => moveLayer(li, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  title={moveBlocked(d.layers, li, 1) || "Move this layer down"}
                  aria-label="Move down"
                  disabled={!!moveBlocked(d.layers, li, 1)}
                  onClick={() => moveLayer(li, 1)}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  title={removeBlocked(d.layers, li) || "Remove this layer"}
                  disabled={!!removeBlocked(d.layers, li)}
                  onClick={() => setD((old) => ({ ...old, layers: old.layers.filter((_, k) => k !== li) }))}
                >
                  remove
                </button>
              </span>
            );
          }}
        />
        <StackupLegend />

        <div className="field-row">
          <button type="button" className="btn btn-sm" onClick={() => addLayer("copper")}>
            + copper layer
          </button>
          <button type="button" className="btn btn-sm" onClick={() => addLayer("dielectric")}>
            + dielectric
          </button>
          {/* An outer layer is added the same way a copper layer is, and only where it
              is missing — each face can carry one of each. Adding to one face mirrors
              onto the other when that face has none, because a board is nearly always
              finished the same way on both sides. */}
          {(["top", "bottom"] as const).flatMap((side) =>
            OUTER.filter((o) => !d.faces[side][o.key]).map((o) => (
              <button
                key={`${side}-${o.key}`}
                type="button"
                className="btn btn-sm"
                onClick={() => addOuter(side, o.key)}
              >
                + {side} {o.label.toLowerCase()}
              </button>
            )),
          )}
          <span className="muted">
            Top to bottom; ↑ ↓ reorder. Several dielectrics in one gap is normal — a fab lists each prepreg sheet.
            Copper layers are named by position and dielectrics by material, so neither is typed.
          </span>
        </div>

        {faults.length ? (
          <div className="fs-notice warn">
            <b>This stack is not buildable as it stands.</b>
            <ul className="fs-notes">
              {faults.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
            <span className="muted fs-note">
              Saving is allowed — it may be half-finished work — but the solver will model what is here, not what was
              meant.
            </span>
          </div>
        ) : null}

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

/** `unit` says what the value is STORED in, and is what lets the box carry a unit
 *  rather than hiding one in the label. A field with no `unit` is not a dimension —
 *  a Dk, a loss tangent, a percentage — and keeps a plain numeric box. */
/** A rule stored in micrometres is edited in the SI box's base unit (mm), so the two
 *  conversions live beside each other rather than being repeated per field. */
const toBase = (v: number | null, unit: "mm" | "um"): number | null =>
  v === null || v === undefined ? null : unit === "um" ? v / 1000 : v;
const fromBase = (v: number, unit: "mm" | "um"): number => (unit === "um" ? v * 1000 : v);

/* `unit` routes a field to SiInput in that length unit; `pct` routes it to the
   same control as a percentage. A field with neither is genuinely dimensionless
   (Dk, tanδ) and stays a plain number box — wrapping those in a unit parser
   would be uniformity for its own sake. */
const RULE_FIELDS: {
  key: string; label: string; step: number; group: string;
  unit?: "mm" | "um"; pct?: boolean;
}[] = [
  { key: "min_width_2l", label: "2-layer trace width", step: 0.01, group: "Trace / space minimum", unit: "mm" },
  { key: "min_space_2l", label: "2-layer space", step: 0.01, group: "Trace / space minimum", unit: "mm" },
  { key: "min_width_ml", label: "multilayer trace width", step: 0.01, group: "Trace / space minimum", unit: "mm" },
  { key: "min_space_ml", label: "multilayer space", step: 0.01, group: "Trace / space minimum", unit: "mm" },
  { key: "via_min_hole", label: "via hole", step: 0.05, group: "Via minimum", unit: "mm" },
  { key: "via_min_diameter", label: "via pad ⌀", step: 0.05, group: "Via minimum", unit: "mm" },
  { key: "drill_to_copper", label: "drill to copper", step: 0.05, group: "Via minimum", unit: "mm" },
  { key: "via_plating_um", label: "plating", step: 1, group: "Via process", unit: "um" },
  { key: "via_drill_oversize", label: "drill oversize", step: 0.01, group: "Via process", unit: "mm" },
  { key: "etch_outer_um", label: "outer, 1 oz", step: 0.5, group: "Etch undercut per side", unit: "um" },
  { key: "etch_inner_um", label: "inner, 0.5 oz", step: 0.5, group: "Etch undercut per side", unit: "um" },
  { key: "mask_dk", label: "solder mask Dk", step: 0.1, group: "Coating defaults" },
  { key: "mask_tand", label: "solder mask tanδ", step: 0.001, group: "Coating defaults" },
  { key: "mask_c1", label: "mask over substrate", step: 0.005, group: "Coating defaults", unit: "mm" },
  { key: "mask_c2", label: "mask over trace", step: 0.005, group: "Coating defaults", unit: "mm" },
  { key: "mask_expansion", label: "mask opening expansion", step: 0.01, group: "Coating defaults", unit: "mm" },
  { key: "finish_um", label: "finish thickness", step: 0.5, group: "Coating defaults", unit: "um" },
  { key: "impedance_tolerance_pct", label: "impedance tolerance", step: 1, group: "Other", pct: true },
];

export interface RulesEditorProps {
  ruleset: FsRuleSet;
  finishes: FsFinish[];
  onClose: () => void;
  onSaved: (r: FsRuleSet) => void;
  onDeleted: (id: string) => void;
}

export function RulesEditor({ ruleset, finishes, onClose, onSaved, onDeleted }: RulesEditorProps) {
  const modal = useModal(onClose);
  const dialog = useDialog();
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
    // Shared the same way a stackup is: every solve on the platform reaches for these.
    if (
      !(await dialog.confirm(
        `Delete the production rules “${d.name}”? They are shared by every project here, and any ` +
          `profile built against them loses the minima and via sizes it was solved with.`,
        { title: "Delete rules", confirmLabel: "Delete", tone: "danger" },
      ))
    )
      return;
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
    <div className="fs-modal" role="dialog" aria-label="Production rules editor" {...modal.backdropProps}>
      <div className="fs-modal-box card pad" {...modal.cardProps}>
        <div className="fs-modal-head">
          <b>Production rules</b>
          <label className="field">
            <span>Name</span>
            <input className="text" value={String(d.name ?? "")} onChange={(e) => setD({ ...d, name: e.target.value })} />
          </label>
        </div>

        <div className="fs-rules-grid">
          {groups.map((g) => (
            <fieldset key={g} className="fieldset">
              <legend>{g}</legend>
              {RULE_FIELDS.filter((f) => f.group === g).map((f) => (
                <label key={f.key} className="fs-field-row">
                  <span>{f.label}</span>
                  {f.unit ? (
                    <SiInput
                      className="fs-num"
                      assume={f.unit}
                      fixedUnit={f.unit}
                      min={0}
                      value={toBase(d[f.key] as number | null, f.unit)}
                      onChange={(v) => setD({ ...d, [f.key]: fromBase(v, f.unit!) })}
                      onEmpty={() => setD({ ...d, [f.key]: null })}
                      help={<>Type any unit: {f.unit === "mm" ? "0.2, 200um, 7.9mil" : "12.5, 12.5um, 0.0125mm"}.</>}
                    />
                  ) : f.pct ? (
                    <SiInput
                      className="fs-num"
                      quantity="percent"
                      min={0}
                      max={100}
                      value={(d[f.key] as number | null) ?? null}
                      onChange={(v) => setD({ ...d, [f.key]: v })}
                      onEmpty={() => setD({ ...d, [f.key]: null })}
                      help={<>A bare number is percent.</>}
                    />
                  ) : (
                    <NumberInput
                      className="text fs-num"
                      step={f.step}
                      value={(d[f.key] as number | null) ?? null}
                      onChange={(v) => setD({ ...d, [f.key]: v })}
                      onEmpty={() => setD({ ...d, [f.key]: null })}
                    />
                  )}
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
          <fieldset className="fieldset fs-span">
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
                      <SiInput
                        className="fs-num"
                        min={0}
                        value={v.hole}
                        onChange={(n) =>
                          setD({ ...d, via_sizes: sizes.map((x, k) => (k === i ? { ...x, hole: n } : x)) })
                        }
                        help={<>Type any unit: 0.3, 300um, 11.8mil. A bare number means mm.</>}
                      />
                    </td>
                    <td>
                      <SiInput
                        className="fs-num"
                        min={0}
                        value={v.pad}
                        onChange={(n) =>
                          setD({ ...d, via_sizes: sizes.map((x, k) => (k === i ? { ...x, pad: n } : x)) })
                        }
                        help={<>Type any unit: 0.3, 300um, 11.8mil. A bare number means mm.</>}
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
