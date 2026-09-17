/** Graphical procedure editor.
 *
 *  Each step is a row you can read at a glance and open to see, and — in edit
 *  mode — to change. Fields come from `stepSchema.ts`, so the form always
 *  matches the op. Three things fold the old separate sections in here (user
 *  request 2026-07-30, extended 2026-09-17): a `flash` step picks the firmware
 *  images, a `download_files` step picks the berryware bundle, and a
 *  `mark_laser` step picks or UPLOADS its artwork — every one of them writing
 *  the VERSION's pins. The version stays the single place a device's payload
 *  is defined; the editor only puts the controls where the work happens.
 *
 *  **Every control is typed.** A duration is an `SiInput` (type "500ms"), a
 *  count is a `NumberInput`, a flag is a `CheckField`, a variable is a select
 *  over what earlier steps captured, and a value is a literal or a parameter
 *  through `ValuePicker` — nobody has to remember the brace syntax. Lists
 *  (commands, captures, images) are rows that move, duplicate and delete.
 *
 *  `readOnly` renders the SAME rows for a version that is not being edited,
 *  with the fields as text instead of controls. One component, so the read
 *  view and the editor can never disagree about what a step contains.
 */
import { useEffect, useState, type ReactNode } from "react";
import {
  errorMessage,
  getDeviceFileVersion,
  type BerryBundleRow,
  type DeploymentFileRow,
  type FirmwareAssetRow,
} from "../../api";
import Field, { CheckField, FieldGrid } from "../Field";
import FilePick from "../FilePick";
import NumberInput from "../NumberInput";
import SiInput from "../SiInput";
import type { AgentRoll } from "../../flasher/benchAgent";
import { rollFromName, type RollGeometry } from "../../flasher/label";
import LabelPreview from "./LabelPreview";
import { fmtBytes, lbrnThumbnail } from "./common";
import {
  OPS, OP_BY_NAME, PHASES, getField, setField, varsBefore,
  type Field as FieldSpec, type OpSpec,
} from "./stepSchema";

type Step = Record<string, unknown>;

/** One artwork the marking step may pin: the newest published version of a
 *  `.lbrn2` in the project pool, or the one the version already pins. */
export interface ArtworkChoice {
  device_file_version_id: number;
  filename: string;
  version_no: number;
  size_bytes: number;
}

export interface StepEditorProps {
  steps: Step[];
  onChange: (steps: Step[]) => void;
  /** parameter names available (param set keys + non-secret defaults) */
  paramKeys: string[];
  /** firmware pinned by this version, and the pool to add from */
  images: { firmware_asset_id: number; address: string }[];
  assets: FirmwareAssetRow[];
  onImagesChange: (images: { firmware_asset_id: number; address: string }[]) => void;
  /** berryware: the bundle this version pins, and the ones to choose from */
  bundleId: number | null;
  bundles: BerryBundleRow[];
  onBundleChange: (bundleId: number) => void;
  /** artwork: what the version pins (any kind — the picker filters), the
   *  project's artwork pool to pick from, and the two ways a step changes it.
   *  A pick and an upload both end in `onArtworkChange`, which the owner turns
   *  into ONE patch carrying the step and the new pin together. */
  pinnedFiles?: DeploymentFileRow[];
  artworkPool?: ArtworkChoice[];
  onArtworkChange?: (index: number, step: Step, file: ArtworkChoice) => void;
  onArtworkUpload?: (file: File) => Promise<ArtworkChoice>;
  defaultOffsets?: Record<string, Record<string, string>>;
  /** the check vocabulary from /meta — suggestions, never a restriction */
  checkNames?: { name: string; label: string; category: string }[];
  /** the rolls the bench printer's PPD offers, when the agent is reachable
   *  from this browser — drives the roll picker and the label preview's
   *  printable area. Empty away from the bench. */
  rolls?: AgentRoll[];
  /** show the procedure without controls */
  readOnly?: boolean;
}

/** The roll a print step names, with the printer's geometry when the agent
 *  reported it and the nominal size from the name otherwise. */
function rollOf(step: Step, rolls: AgentRoll[] | undefined): RollGeometry | null {
  const size = String(step.roll ?? "").trim() || "w72h154";
  const known = rolls?.find((r) => r.size === size);
  if (known) {
    return { size: known.size, name: known.name, label: known.label_mm, printable: known.printable_mm };
  }
  return rollFromName(size);
}

/** A serial the way a device answers one: 12 hex characters, the longest the
 *  engine allows and the shape a MAC without separators has. The preview's
 *  fit check is only honest at the longest value. */
const SAMPLE_SERIAL = "D4E9F4F4DFD4";

export default function StepEditor(props: StepEditorProps) {
  const { steps, onChange, readOnly = false } = props;
  const [open, setOpen] = useState<number | null>(null);
  const [adding, setAdding] = useState<number | null>(null);

  const patch = (i: number, next: Step) => onChange(steps.map((s, j) => (j === i ? next : s)));
  const move = (i: number, delta: number) => {
    const j = i + delta;
    if (j < 0 || j >= steps.length) return;
    const next = [...steps];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
    setOpen(open === i ? j : open === j ? i : open);
  };
  const remove = (i: number) => {
    onChange(steps.filter((_, j) => j !== i));
    setOpen(null);
  };
  const duplicate = (i: number) => {
    const next = [...steps];
    next.splice(i + 1, 0, JSON.parse(JSON.stringify(steps[i])) as Step);
    onChange(next);
    setOpen(i + 1);
  };
  const insert = (at: number, op: string) => {
    const spec = OP_BY_NAME[op];
    const step: Step = { op, label: spec?.title ?? op };
    const next = [...steps];
    next.splice(at, 0, step);
    onChange(next);
    setAdding(null);
    setOpen(at);
  };

  return (
    <div className="step-editor">
      {steps.length === 0 ? (
        <p className="muted">
          {readOnly ? "This version has no steps." : "No steps yet — add the first one below."}
        </p>
      ) : null}

      {steps.map((step, i) => {
        const spec = OP_BY_NAME[String(step.op)];
        return (
          <div key={i} className={`step-card${open === i ? " open" : ""}`}>
            <div className="step-row" onClick={() => setOpen(open === i ? null : i)}>
              <span className="step-num">{i + 1}</span>
              <span className="pill neutral step-op-pill">{String(step.op)}</span>
              <span className="step-title">{String(step.label ?? spec?.title ?? step.op)}</span>
              <span className="muted dim step-sum">{summarise(step, spec, props)}</span>
              {readOnly ? (
                <span className="step-btns muted dim">{open === i ? "▾" : "▸"}</span>
              ) : (
                <span className="step-btns btn-row">
                  <button type="button" className="btn btn-sm" title="Move up" disabled={i === 0}
                          onClick={(e) => { e.stopPropagation(); move(i, -1); }}>↑</button>
                  <button type="button" className="btn btn-sm" title="Move down"
                          disabled={i === steps.length - 1}
                          onClick={(e) => { e.stopPropagation(); move(i, 1); }}>↓</button>
                  <button type="button" className="btn btn-sm" title="Duplicate this step below"
                          onClick={(e) => { e.stopPropagation(); duplicate(i); }}>⧉</button>
                  <button type="button" className="btn btn-sm" title="Insert a step below"
                          onClick={(e) => { e.stopPropagation(); setAdding(i + 1); }}>+</button>
                  <button type="button" className="btn btn-sm row-del" title="Remove this step"
                          onClick={(e) => { e.stopPropagation(); remove(i); }}>×</button>
                </span>
              )}
            </div>

            {open === i && spec ? (
              <div className="step-body">
                <p className="muted dim">{spec.blurb}</p>
                {readOnly ? (
                  <StepFields step={step} spec={spec} props={props} />
                ) : (
                  <FieldGrid className="step-form">
                    {spec.fields.map((f) => (
                      <FieldEditor
                        key={f.key}
                        field={f}
                        step={step}
                        index={i}
                        onPatch={(next) => patch(i, next)}
                        {...props}
                      />
                    ))}
                  </FieldGrid>
                )}
              </div>
            ) : open === i ? (
              <div className="step-body">
                <p className="banner-warn">
                  Unknown op <span className="mono">{String(step.op)}</span> — the engine will
                  refuse it. Edit as JSON to repair or remove it.
                </p>
              </div>
            ) : null}

            {!readOnly && adding === i + 1 ? (
              <AddStep onPick={(op) => insert(i + 1, op)} onCancel={() => setAdding(null)} />
            ) : null}
          </div>
        );
      })}

      {readOnly ? null : adding === 0 || steps.length === 0 ? (
        <AddStep onPick={(op) => insert(steps.length, op)} onCancel={() => setAdding(null)} />
      ) : (
        <div className="btn-row">
          <button type="button" className="btn btn-sm" onClick={() => setAdding(0)}>
            Add a step at the end
          </button>
        </div>
      )}
    </div>
  );
}

/** One line of "what this step actually does", for the collapsed row. */
function summarise(step: Step, spec: OpSpec | undefined, props: StepEditorProps): string {
  if (!spec) return "unknown op";
  const bits: string[] = [];
  for (const f of spec.fields) {
    if (!f.summary || f.key === "label") continue;
    if (f.kind === "images") {
      const kinds = (step.kinds as string[] | undefined) ?? null;
      const chosen = props.images.filter(
        (img) => !kinds || kinds.includes(kindOf(img.firmware_asset_id, props.assets)),
      );
      bits.push(chosen.length
        ? chosen.map((img) => `${nameOf(img.firmware_asset_id, props.assets)}@${img.address}`).join(" + ")
        : "no image pinned");
      continue;
    }
    if (f.kind === "bundle") {
      const b = props.bundles.find((x) => x.id === props.bundleId);
      bits.push(b ? `${b.label} (${b.file_count} files)` : "no bundle pinned");
      continue;
    }
    if (f.kind === "artwork") {
      const art = artworkOf(step, props);
      bits.push(art ? `${art.filename} v${art.version_no}` : "no artwork pinned");
      continue;
    }
    if (f.kind === "commands") {
      const cmds = (step.commands as string[] | undefined) ?? [];
      bits.push(cmds.join(" ; ") || "no commands");
      continue;
    }
    const v = getField(step, f.key);
    if (v !== undefined && v !== "") bits.push(`${f.key.split(".").pop()}=${String(v)}`);
  }
  return bits.join(" · ");
}

const nameOf = (id: number, assets: FirmwareAssetRow[]) =>
  assets.find((a) => a.id === id)?.filename ?? `#${id}`;
const kindOf = (id: number, assets: FirmwareAssetRow[]) =>
  assets.find((a) => a.id === id)?.kind ?? "";

/** The artwork THIS step engraves: the pinned file its `template` names, or
 *  the only pinned artwork when it names none — the engine's own rule. */
function artworkOf(step: Step, props: StepEditorProps): DeploymentFileRow | null {
  const art = (props.pinnedFiles ?? []).filter((f) => f.kind === "artwork");
  const named = String(step.template ?? "");
  if (named) return art.find((f) => f.filename === named) ?? null;
  return art.length === 1 ? art[0] : null;
}

function AddStep({ onPick, onCancel }: { onPick: (op: string) => void; onCancel: () => void }) {
  return (
    <div className="step-add">
      {PHASES.map((p) => (
        <div key={p.key} className="step-add-group">
          <span className="fw-label">{p.label}</span>
          <div className="step-add-ops">
            {OPS.filter((o) => o.phase === p.key).map((o) => (
              <button key={o.op} type="button" className="btn btn-sm" title={o.blurb}
                      onClick={() => onPick(o.op)}>
                {o.title}
              </button>
            ))}
          </div>
        </div>
      ))}
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

interface FieldEditorProps extends StepEditorProps {
  field: FieldSpec;
  step: Step;
  index: number;
  onPatch: (next: Step) => void;
}

/** One field of one step, as the control its kind calls for. */
function FieldEditor(p: FieldEditorProps) {
  const { field, step, onPatch } = p;
  const value = getField(step, field.key);
  const set = (v: unknown) => onPatch(setField(step, field.key, v));
  const wide = ["capture", "commands", "images", "bundle", "artwork", "value", "label"].includes(field.kind);
  const vars = () => varsBefore(p.steps, p.index, p.paramKeys);

  if (field.kind === "bool") {
    return (
      <Field wide={false} className="step-field-check">
        <CheckField checked={Boolean(value)} onChange={(on) => set(on || "")} title={field.hint}>
          {field.label}
          {field.hint ? <span className="muted dim"> — {field.hint}</span> : null}
        </CheckField>
      </Field>
    );
  }

  let control: ReactNode;
  switch (field.kind) {
    case "number":
      control = (
        <NumberInput
          className="text num-input mono"
          value={typeof value === "number" ? value : value ? Number(value) : null}
          onChange={(n) => set(n)}
          onEmpty={() => set("")}
          placeholder={field.placeholder}
          step={1}
        />
      );
      break;
    case "seconds":
      control = (
        <SiInput
          className="text num-input"
          quantity="time"
          value={typeof value === "number" ? value : value ? Number(value) : null}
          onChange={(n) => set(n)}
          onEmpty={() => set("")}
          placeholder={field.placeholder}
          min={0}
        />
      );
      break;
    case "varname":
      control = (
        <select className="text mono" value={String(value ?? "")} onChange={(e) => set(e.target.value)}>
          <option value="">— pick a variable —</option>
          {vars().map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      );
      break;
    case "value":
      control = (
        <ValuePicker
          value={value === undefined ? "" : String(value)}
          placeholder={field.placeholder}
          options={vars()}
          onChange={set}
        />
      );
      break;
    case "commands":
      control = (
        <CommandList
          commands={(step.commands as string[] | undefined) ?? []}
          options={vars()}
          suggestions={commandsUsed(p.steps)}
          onChange={(cmds) => onPatch({ ...step, commands: cmds })}
        />
      );
      break;
    case "capture":
      control = (
        <CaptureList
          capture={(step.capture as Record<string, string> | undefined) ?? {}}
          onChange={(cap) =>
            onPatch(Object.keys(cap).length ? { ...step, capture: cap } : omit(step, "capture"))
          }
        />
      );
      break;
    case "images":
      control = <ImagePicker {...p} />;
      break;
    case "bundle":
      control = <BundlePicker {...p} />;
      break;
    case "artwork":
      control = <ArtworkPicker {...p} />;
      break;
    case "roll":
      control = <RollPicker {...p} />;
      break;
    case "label":
      control = <LabelField {...p} />;
      break;
    case "check":
      /* A datalist, not a select: the catalog covers what exists today and a
         new product may prove something nobody has named yet. */
      control = (
        <>
          <input
            className="text mono"
            list="check-catalog"
            placeholder="nothing — this step proves no functionality"
            value={value === undefined ? "" : String(value)}
            onChange={(e) => set(e.target.value.trim())}
          />
          <datalist id="check-catalog">
            {(p.checkNames ?? []).map((c) => (
              <option key={c.name} value={c.name}>{`${c.label} · ${c.category}`}</option>
            ))}
          </datalist>
        </>
      );
      break;
    default:
      control = (
        <input
          className={`text${field.kind === "path" ? " mono" : ""}`}
          placeholder={field.placeholder}
          value={value === undefined ? "" : String(value)}
          onChange={(e) => set(e.target.value)}
        />
      );
  }

  return (
    <Field label={field.label} hint={field.hint} wide={wide}>
      {control}
    </Field>
  );
}

function omit(obj: Step, key: string): Step {
  const next = { ...obj };
  delete next[key];
  return next;
}

/** Every command name this procedure already sends, for the datalist under a
 *  new backlog row: a procedure re-uses a handful of Tasmota settings, and
 *  typing the third `SSId1` from memory is how a typo gets published. */
function commandsUsed(steps: Step[]): string[] {
  const out = new Set<string>();
  for (const s of steps) {
    if (typeof s.cmd === "string" && s.cmd) out.add(s.cmd);
    for (const line of (s.commands as string[] | undefined) ?? []) {
      const name = line.split(" ")[0];
      if (name) out.add(name);
    }
  }
  return [...out].sort();
}

/** Literal or {parameter} — no brace syntax to remember. Two buttons say
 *  which, and the control beside them is the one that mode needs. */
function ValuePicker({
  value, options, placeholder, onChange,
}: {
  value: string;
  options: string[];
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  const asParam = /^\{(\w+)\}$/.exec(value);
  const [mode, setMode] = useState<"literal" | "param">(asParam ? "param" : "literal");
  useEffect(() => {
    if (asParam) setMode("param");
  }, [value]);   // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (m: "literal" | "param") => {
    if (m === mode) return;
    setMode(m);
    onChange(m === "param" ? "" : value.replace(/[{}]/g, ""));
  };

  return (
    <span className="field-inline">
      <span className="cmd-tools">
        <button type="button" className={`btn btn-sm${mode === "literal" ? " btn-primary" : ""}`}
                title="A fixed value, stored in the step" onClick={() => pick("literal")}>
          value
        </button>
        <button type="button" className={`btn btn-sm${mode === "param" ? " btn-primary" : ""}`}
                title="Resolved at run time from a parameter or an earlier capture"
                onClick={() => pick("param")}>
          parameter
        </button>
      </span>
      {mode === "param" ? (
        <select
          className="text mono"
          value={asParam ? asParam[1] : ""}
          onChange={(e) => onChange(e.target.value ? `{${e.target.value}}` : "")}
        >
          <option value="">— pick —</option>
          {options.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      ) : (
        <input
          className="text"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </span>
  );
}

/** The tools every list row carries: move up, move down, delete. */
function RowTools({
  index, count, onMove, onRemove,
}: {
  index: number;
  count: number;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  return (
    <span className="cmd-tools">
      <button type="button" className="btn btn-sm" title="Move up" disabled={index === 0}
              onClick={() => onMove(-1)}>↑</button>
      <button type="button" className="btn btn-sm" title="Move down" disabled={index === count - 1}
              onClick={() => onMove(1)}>↓</button>
      <button type="button" className="btn btn-sm row-del" title="Remove" onClick={onRemove}>×</button>
    </span>
  );
}

function swap<T>(rows: T[], i: number, delta: number): T[] {
  const j = i + delta;
  if (j < 0 || j >= rows.length) return rows;
  const next = [...rows];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

/** Backlog: one "Setting value" per row, in the order the device gets them.
 *  The value goes through the same picker as any other, so a password is a
 *  parameter here exactly as it is in a set_and_check step. */
function CommandList({
  commands, options, suggestions, onChange,
}: {
  commands: string[];
  options: string[];
  suggestions: string[];
  onChange: (cmds: string[]) => void;
}) {
  const split = (line: string): [string, string] => {
    const at = line.indexOf(" ");
    return at < 0 ? [line, ""] : [line.slice(0, at), line.slice(at + 1)];
  };
  const update = (i: number, cmd: string, val: string) =>
    onChange(commands.map((c, j) => (j === i ? (val ? `${cmd} ${val}` : cmd) : c)));

  return (
    <span className="cmd-list">
      {commands.map((line, i) => {
        const [cmd, val] = split(line);
        return (
          <span key={i} className="cmd-row">
            <span className="cmd-idx">{i + 1}</span>
            <input
              className="text mono cmd-name"
              placeholder="Setting"
              list="backlog-commands"
              value={cmd}
              onChange={(e) => update(i, e.target.value, val)}
            />
            <ValuePicker
              value={val}
              options={options}
              placeholder="value"
              onChange={(v) => update(i, cmd, v)}
            />
            <RowTools
              index={i}
              count={commands.length}
              onMove={(d) => onChange(swap(commands, i, d))}
              onRemove={() => onChange(commands.filter((_, j) => j !== i))}
            />
          </span>
        );
      })}
      <datalist id="backlog-commands">
        {suggestions.map((s) => <option key={s} value={s} />)}
      </datalist>
      {commands.length === 0 ? (
        <span className="muted dim">No commands yet — the device would receive an empty Backlog.</span>
      ) : null}
      <span>
        <button type="button" className="btn btn-sm" onClick={() => onChange([...commands, ""])}>
          Add command
        </button>
      </span>
    </span>
  );
}

/** capture: variable name ← dotted response path. */
function CaptureList({
  capture, onChange,
}: {
  capture: Record<string, string>;
  onChange: (cap: Record<string, string>) => void;
}) {
  const rows = Object.entries(capture);
  const rewrite = (i: number, name: string, path: string) => {
    const next: Record<string, string> = {};
    rows.forEach(([k, v], j) => {
      const key = j === i ? name : k;
      if (key) next[key] = j === i ? path : v;
    });
    onChange(next);
  };
  return (
    <span className="cmd-list">
      {rows.map(([name, path], i) => (
        <span key={i} className="cmd-row">
          <span className="cmd-idx">{i + 1}</span>
          <input
            className="text mono cmd-name"
            placeholder="variable"
            value={name}
            onChange={(e) => rewrite(i, e.target.value, path)}
          />
          <span className="muted">←</span>
          <input
            className="text mono"
            placeholder="Status.Topic"
            title="dotted path into the response"
            value={path}
            onChange={(e) => rewrite(i, name, e.target.value)}
          />
          <RowTools
            index={i}
            count={rows.length}
            onMove={(d) => onChange(Object.fromEntries(swap(rows, i, d)))}
            onRemove={() => onChange(Object.fromEntries(rows.filter((_, j) => j !== i)))}
          />
        </span>
      ))}
      <span>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => onChange({ ...capture, "": "" })}
          disabled={rows.some(([k]) => k === "")}
        >
          Capture a value
        </button>
      </span>
    </span>
  );
}

/** The flash step's firmware: what the version pins, plus add/remove. */
function ImagePicker(p: FieldEditorProps) {
  const { images, assets, onImagesChange, defaultOffsets, step, onPatch } = p;
  const kinds = (step.kinds as string[] | undefined) ?? null;
  const flashable = assets.filter((a) => a.flashable !== false);
  const offsetFor = (a: FirmwareAssetRow) =>
    a.default_address || defaultOffsets?.[a.chip]?.[a.kind] || "0x0";

  return (
    <span className="img-picker">
      {images.map((img, i) => {
        const asset = assets.find((a) => a.id === img.firmware_asset_id);
        const on = !kinds || (asset && kinds.includes(asset.kind));
        return (
          <span key={i} className="cmd-row">
            <span className="cmd-idx">{i + 1}</span>
            <select
              className="text"
              value={img.firmware_asset_id}
              onChange={(e) => {
                const next = assets.find((a) => a.id === Number(e.target.value));
                onImagesChange(images.map((x, j) =>
                  j === i
                    ? { firmware_asset_id: Number(e.target.value),
                        address: next ? offsetFor(next) : x.address }
                    : x));
              }}
            >
              {flashable.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.filename} ({a.kind}, {a.chip || "?"}, {fmtBytes(a.size_bytes)})
                </option>
              ))}
            </select>
            <input
              className="text mono num-input"
              value={img.address}
              title="Flash offset. Defaults to the partition map for the chip and kind; override only if the layout says so."
              onChange={(e) =>
                onImagesChange(images.map((x, j) => (j === i ? { ...x, address: e.target.value } : x)))
              }
            />
            <CheckField
              checked={Boolean(on)}
              title="Write this image in this step. Untick to leave it for another flash step."
              onChange={(checked) => {
                const all = [...new Set(images.map((x) =>
                  assets.find((a) => a.id === x.firmware_asset_id)?.kind ?? ""))].filter(Boolean);
                const cur = kinds ?? all;
                const k = asset?.kind ?? "";
                const next = checked ? [...new Set([...cur, k])] : cur.filter((x) => x !== k);
                onPatch(next.length === all.length ? omit(step, "kinds") : { ...step, kinds: next });
              }}
            >
              write
            </CheckField>
            <RowTools
              index={i}
              count={images.length}
              onMove={(d) => onImagesChange(swap(images, i, d))}
              onRemove={() => onImagesChange(images.filter((_, j) => j !== i))}
            />
          </span>
        );
      })}
      <select
        className="text"
        value=""
        onChange={(e) => {
          const a = assets.find((x) => x.id === Number(e.target.value));
          if (a) onImagesChange([...images, { firmware_asset_id: a.id, address: offsetFor(a) }]);
        }}
      >
        <option value="">+ add a firmware image…</option>
        {flashable
          .filter((a) => !images.some((img) => img.firmware_asset_id === a.id))
          .map((a) => (
            <option key={a.id} value={a.id}>
              {a.filename} ({a.kind}, {a.chip || "?"})
            </option>
          ))}
      </select>
    </span>
  );
}

/** The download step's berryware bundle. */
function BundlePicker({ bundles, bundleId, onBundleChange }: FieldEditorProps) {
  const chosen = bundles.find((b) => b.id === bundleId);
  return (
    <span className="img-picker">
      <select
        className="text"
        value={bundleId ?? ""}
        onChange={(e) => onBundleChange(Number(e.target.value))}
      >
        <option value="">— pick a bundle —</option>
        {bundles.map((b) => (
          <option key={b.id} value={b.id}>
            {b.label} · {b.file_count} files{b.used_by ? ` · used by ${b.used_by}` : ""}
          </option>
        ))}
      </select>
      {chosen ? (
        <span className="muted dim">
          {chosen.files.map((f) => f.filename).join(", ")}
        </span>
      ) : null}
    </span>
  );
}

/** The LightBurn thumbnail of a pinned artwork, fetched on demand: the file
 *  is 150 kB of XML and only the picker and the preview want the picture. */
function useArtworkThumb(versionId: number | null): string | null {
  const [thumb, setThumb] = useState<string | null>(null);
  useEffect(() => {
    setThumb(null);
    if (!versionId) return;
    const ac = new AbortController();
    getDeviceFileVersion(versionId, ac.signal)
      .then((v) => setThumb(v.binary ? null : lbrnThumbnail(v.content)))
      .catch(() => setThumb(null));
    return () => ac.abort();
  }, [versionId]);
  return thumb;
}

/** The marking step's artwork: pick one from the project pool, or upload a
 *  new .lbrn2. Either way the step's `template` and the version's pin change
 *  together, in one patch, because a step naming a file the version does not
 *  pin is exactly what the publish gate refuses. */
function ArtworkPicker(p: FieldEditorProps) {
  const { step, index, artworkPool = [], onArtworkChange, onArtworkUpload } = p;
  const current = artworkOf(step, p);
  const thumb = useArtworkThumb(current?.device_file_version_id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const choices: ArtworkChoice[] = [...artworkPool];
  if (current && !choices.some((c) => c.device_file_version_id === current.device_file_version_id)) {
    choices.unshift({
      device_file_version_id: current.device_file_version_id, filename: current.filename,
      version_no: current.version_no, size_bytes: current.size_bytes,
    });
  }

  const pick = (id: number) => {
    const file = choices.find((c) => c.device_file_version_id === id);
    if (file) onArtworkChange?.(index, { ...step, template: file.filename }, file);
  };
  const upload = async (files: File[]) => {
    if (!onArtworkUpload || !files[0]) return;
    setBusy(true);
    setError(null);
    try {
      const made = await onArtworkUpload(files[0]);
      onArtworkChange?.(index, { ...step, template: made.filename }, made);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="artwork-pick">
      {thumb ? <img className="artwork-thumb" src={thumb} alt={current?.filename ?? "artwork"} /> : null}
      <span className="artwork-fields">
        <select
          className="text mono"
          value={current?.device_file_version_id ?? ""}
          onChange={(e) => pick(Number(e.target.value))}
          disabled={busy}
        >
          <option value="">— pick an artwork from the pool —</option>
          {choices.map((c) => (
            <option key={c.device_file_version_id} value={c.device_file_version_id}>
              {c.filename} · v{c.version_no} · {fmtBytes(c.size_bytes)}
            </option>
          ))}
        </select>
        <span className="field-inline">
          <FilePick
            accept=".lbrn2,.lbrn"
            disabled={busy || !onArtworkUpload}
            onPick={(files) => void upload(files)}
            title="Upload a LightBurn project. It joins the project pool, is published, and replaces this step's artwork."
          >
            {busy ? "Uploading…" : "Upload a new .lbrn2…"}
          </FilePick>
          {current ? (
            <span className="muted dim">
              pinned: {current.filename} v{current.version_no} · {fmtBytes(current.size_bytes)}
            </span>
          ) : (
            <span className="muted dim">nothing pinned yet</span>
          )}
        </span>
        {error ? <span className="field-error">{error}</span> : null}
      </span>
    </span>
  );
}

/** The print step's roll: the printer's own list when the agent is reachable,
 *  a text box otherwise — never a list kept in the browser. A roll the step
 *  names that the printer does not list stays selectable, so opening a
 *  version away from the bench cannot silently change it. */
function RollPicker(p: FieldEditorProps) {
  const { field, step, onPatch, rolls } = p;
  const value = String(step.roll ?? "");
  const set = (v: string) => onPatch(setField(step, "roll", v));
  if (!rolls?.length) {
    return (
      <input
        className="text mono"
        placeholder={field.placeholder}
        value={value}
        onChange={(e) => set(e.target.value.trim())}
        title="The bench agent is not reachable from here, so the printer's own roll list is not available — type the PPD name."
      />
    );
  }
  const listed = rolls.some((r) => r.size === value);
  return (
    <select className="text mono" value={value} onChange={(e) => set(e.target.value)}>
      <option value="">— the bench's default roll —</option>
      {value && !listed ? <option value={value}>{value} (not on this printer)</option> : null}
      {rolls.map((r) => (
        <option key={r.size} value={r.size}>
          {r.name || r.size} · {r.label_mm[0]} × {r.label_mm[1]} mm
        </option>
      ))}
    </select>
  );
}

/** The label, drawn from the step's own fields, for a sample serial the
 *  author can change. Stores nothing on the step. */
function LabelField(p: FieldEditorProps) {
  const { step, rolls } = p;
  const [sample, setSample] = useState(SAMPLE_SERIAL);
  return (
    <span className="artwork-fields">
      <span className="field-inline">
        <span className="muted dim">sample value</span>
        <input
          className="text mono num-input label-sample"
          value={sample}
          maxLength={12}
          onChange={(e) => setSample(e.target.value.toUpperCase())}
          title="A serial to draw. The real one comes from the device at run time; 12 characters is the longest the engine allows."
        />
      </span>
      <LabelPreview
        value={sample.trim()}
        roll={rollOf(step, rolls)}
        dots={Number(step.dots ?? 3)}
        rotate={step.rotate !== false}
      />
    </span>
  );
}

/** A step's fields as text — the read view. Parameters marked, artifacts named. */
function StepFields({
  step, spec, props,
}: {
  step: Step;
  spec: OpSpec;
  props: StepEditorProps;
}) {
  const rows: { label: string; node: ReactNode }[] = [];

  for (const f of spec.fields) {
    if (f.key === "label") continue;

    if (f.kind === "images") {
      const kinds = (step.kinds as string[] | undefined) ?? null;
      const chosen = props.images.filter(
        (img) => !kinds || kinds.includes(kindOf(img.firmware_asset_id, props.assets)),
      );
      rows.push({
        label: f.label,
        node: chosen.length ? (
          <span>
            {chosen.map((img) => (
              <span key={img.address} className="mono">
                {nameOf(img.firmware_asset_id, props.assets)} @ {img.address}{" "}
              </span>
            ))}
            {kinds ? <span className="muted dim">(kinds: {kinds.join(", ")})</span> : null}
          </span>
        ) : (
          <span className="muted">nothing pinned</span>
        ),
      });
      continue;
    }

    if (f.kind === "bundle") {
      const b = props.bundles.find((x) => x.id === props.bundleId) ?? props.bundles[0];
      rows.push({
        label: f.label,
        node: b ? (
          <span>
            <span className="pill ok">{b.label}</span>{" "}
            <span className="muted dim">{b.file_count} files</span>
          </span>
        ) : (
          <span className="muted">nothing pinned</span>
        ),
      });
      continue;
    }

    if (f.kind === "artwork") {
      const art = artworkOf(step, props);
      rows.push({
        label: f.label,
        node: art ? (
          <span>
            <span className="mono">{art.filename}</span>{" "}
            <span className="muted dim">v{art.version_no} · {fmtBytes(art.size_bytes)}</span>
          </span>
        ) : (
          <span className="muted">nothing pinned</span>
        ),
      });
      continue;
    }

    if (f.kind === "label") {
      rows.push({
        label: f.label,
        node: (
          <LabelPreview
            value={SAMPLE_SERIAL}
            roll={rollOf(step, props.rolls)}
            dots={Number(step.dots ?? 3)}
            rotate={step.rotate !== false}
            caption={`sample ${SAMPLE_SERIAL}`}
          />
        ),
      });
      continue;
    }

    if (f.kind === "commands") {
      const cmds = (step.commands as string[] | undefined) ?? [];
      if (!cmds.length) continue;
      rows.push({
        label: f.label,
        node: (
          <span className="ro-list">
            {cmds.map((c, i) => (
              <span key={i} className="mono">{renderValue(c)}</span>
            ))}
          </span>
        ),
      });
      continue;
    }

    if (f.kind === "capture") {
      const cap = (step.capture as Record<string, string> | undefined) ?? {};
      const entries = Object.entries(cap);
      if (!entries.length) continue;
      rows.push({
        label: f.label,
        node: (
          <span className="ro-list">
            {entries.map(([name, path]) => (
              <span key={name} className="mono">
                {name} ← {path}
              </span>
            ))}
          </span>
        ),
      });
      continue;
    }

    const v = getField(step, f.key);
    if (v === undefined || v === "" || v === false) continue;
    rows.push({
      label: f.label,
      node: v === true ? <span className="pill ok">yes</span>
        : f.kind === "seconds" ? <span className="mono">{String(v)} s</span>
        : <span className="mono">{renderValue(String(v))}</span>,
    });
  }

  if (!rows.length) return <p className="muted">No parameters — the op needs none.</p>;
  return (
    <dl className="ro-fields">
      {rows.map((r, i) => (
        <div key={i} className="ro-field">
          <dt className="fw-label">{r.label}</dt>
          <dd>{r.node}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Highlight {parameters} inside a stored value so a reader can tell a literal
 *  from something resolved at run time. */
function renderValue(text: string): ReactNode {
  const parts = text.split(/(\{\w+\})/g);
  return parts.map((part, i) =>
    /^\{\w+\}$/.test(part)
      ? <span key={i} className="ro-param" title="resolved at run time from a parameter or an earlier capture">{part}</span>
      : <span key={i}>{part}</span>,
  );
}
