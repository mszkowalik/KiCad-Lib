/** Graphical procedure editor.
 *
 *  Each step is a row you can read at a glance and open to edit; fields come
 *  from `stepSchema.ts`, so the form always matches the op. Two things fold the
 *  old separate sections in here (user request 2026-07-30): a `flash` step
 *  picks the firmware images and a `download_files` step picks the berryware
 *  bundle, both writing the VERSION's pins — the version stays the single
 *  place a device's payload is defined, the editor just puts the controls
 *  where the work happens.
 *
 *  A value is either typed in or taken from a parameter/earlier capture
 *  (`ValuePicker` writes `{Name}`), so nobody has to remember the brace syntax.
 *
 *  `readOnly` renders the SAME rows for an already-published version (the
 *  deployment view), with the fields as text instead of controls. One
 *  component, so making a published procedure editable later is a flag, not a
 *  second implementation.
 */
import { useState } from "react";
import type { BerryBundleRow, FirmwareAssetRow } from "../../api";
import { fmtBytes } from "./common";
import {
  OPS, OP_BY_NAME, PHASES, getField, setField, varsBefore,
  type Field, type OpSpec,
} from "./stepSchema";

type Step = Record<string, unknown>;

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
  defaultOffsets?: Record<string, Record<string, string>>;
  /** the check vocabulary from /meta — suggestions, never a restriction */
  checkNames?: { name: string; label: string; category: string }[];
  /** show the procedure without controls (a published version) */
  readOnly?: boolean;
}

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
    setOpen(j);
  };
  const remove = (i: number) => {
    onChange(steps.filter((_, j) => j !== i));
    setOpen(null);
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
                  <button type="button" className="btn btn-sm" title="move up"
                          onClick={(e) => { e.stopPropagation(); move(i, -1); }}>↑</button>
                  <button type="button" className="btn btn-sm" title="move down"
                          onClick={(e) => { e.stopPropagation(); move(i, 1); }}>↓</button>
                  <button type="button" className="btn btn-sm" title="insert a step below"
                          onClick={(e) => { e.stopPropagation(); setAdding(i + 1); }}>+</button>
                  <button type="button" className="btn btn-sm row-del" title="remove"
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
                  <div className="fw-form">
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
                  </div>
                )}
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
  field: Field;
  step: Step;
  index: number;
  onPatch: (next: Step) => void;
}

function FieldEditor(p: FieldEditorProps) {
  const { field, step, onPatch } = p;
  const value = getField(step, field.key);
  const set = (v: unknown) => onPatch(setField(step, field.key, v));
  const wide = ["capture", "commands", "images", "bundle", "value"].includes(field.kind);

  return (
    <label className={`fw-field${wide ? " fw-wide" : ""}`}>
      <span className="fw-label" title={field.hint}>{field.label}</span>

      {field.kind === "bool" ? (
        <span>
          <input type="checkbox" checked={Boolean(value)} onChange={(e) => set(e.target.checked || "")} />
          {field.hint ? <span className="muted dim"> {field.hint}</span> : null}
        </span>
      ) : field.kind === "number" ? (
        <input
          className="row-input num"
          inputMode="numeric"
          placeholder={field.placeholder}
          value={value === undefined ? "" : String(value)}
          onChange={(e) => set(e.target.value === "" ? "" : Number(e.target.value))}
        />
      ) : field.kind === "varname" ? (
        <select className="row-input mono" value={String(value ?? "")} onChange={(e) => set(e.target.value)}>
          <option value="">— pick a variable —</option>
          {varsBefore(p.steps, p.index, p.paramKeys).map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      ) : field.kind === "value" ? (
        <ValuePicker
          value={value === undefined ? "" : String(value)}
          placeholder={field.placeholder}
          options={varsBefore(p.steps, p.index, p.paramKeys)}
          onChange={set}
        />
      ) : field.kind === "commands" ? (
        <CommandList
          commands={(step.commands as string[] | undefined) ?? []}
          options={varsBefore(p.steps, p.index, p.paramKeys)}
          onChange={(cmds) => onPatch({ ...step, commands: cmds })}
        />
      ) : field.kind === "capture" ? (
        <CaptureList
          capture={(step.capture as Record<string, string> | undefined) ?? {}}
          onChange={(cap) =>
            onPatch(Object.keys(cap).length ? { ...step, capture: cap } : omit(step, "capture"))
          }
        />
      ) : field.kind === "images" ? (
        <ImagePicker {...p} />
      ) : field.kind === "bundle" ? (
        <BundlePicker {...p} />
      ) : field.kind === "check" ? (
        /* A datalist, not a select: the catalog covers what exists today and a
           new product may prove something nobody has named yet. */
        <>
          <input
            className="row-input mono"
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
      ) : (
        <input
          className={`row-input${field.kind === "path" ? " mono" : ""}`}
          placeholder={field.placeholder}
          value={value === undefined ? "" : String(value)}
          onChange={(e) => set(e.target.value)}
        />
      )}

      {field.hint && field.kind !== "bool" ? (
        <span className="muted dim step-hint">{field.hint}</span>
      ) : null}
    </label>
  );
}

function omit(obj: Step, key: string): Step {
  const next = { ...obj };
  delete next[key];
  return next;
}

/** Literal or {parameter} — no brace syntax to remember. */
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

  return (
    <span className="value-picker">
      <select
        className="row-input value-mode"
        value={mode}
        onChange={(e) => {
          const m = e.target.value as "literal" | "param";
          setMode(m);
          onChange(m === "param" ? "" : value.replace(/[{}]/g, ""));
        }}
      >
        <option value="literal">value</option>
        <option value="param">parameter</option>
      </select>
      {mode === "param" ? (
        <select
          className="row-input mono"
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
          className="row-input"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </span>
  );
}

/** Backlog: one "Setting value" per row, value via the same picker. */
function CommandList({
  commands, options, onChange,
}: {
  commands: string[];
  options: string[];
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
            <input
              className="row-input mono cmd-name"
              placeholder="Setting"
              value={cmd}
              onChange={(e) => update(i, e.target.value, val)}
            />
            <ValuePicker
              value={val}
              options={options}
              placeholder="value"
              onChange={(v) => update(i, cmd, v)}
            />
            <button
              type="button"
              className="btn btn-sm row-del"
              onClick={() => onChange(commands.filter((_, j) => j !== i))}
            >
              ×
            </button>
          </span>
        );
      })}
      <button type="button" className="btn btn-sm" onClick={() => onChange([...commands, ""])}>
        Add command
      </button>
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
          <input
            className="row-input mono cmd-name"
            placeholder="variable"
            value={name}
            onChange={(e) => rewrite(i, e.target.value, path)}
          />
          <input
            className="row-input mono"
            placeholder="Status.Topic"
            value={path}
            onChange={(e) => rewrite(i, name, e.target.value)}
          />
          <button
            type="button"
            className="btn btn-sm row-del"
            onClick={() => onChange(Object.fromEntries(rows.filter((_, j) => j !== i)))}
          >
            ×
          </button>
        </span>
      ))}
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => onChange({ ...capture, "": "" })}
        disabled={rows.some(([k]) => k === "")}
      >
        Capture a value
      </button>
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
            <select
              className="row-input"
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
              className="row-input mono cmd-name"
              value={img.address}
              title="flash offset"
              onChange={(e) =>
                onImagesChange(images.map((x, j) => (j === i ? { ...x, address: e.target.value } : x)))
              }
            />
            <label className="muted" title="write this image in this step">
              <input
                type="checkbox"
                checked={Boolean(on)}
                onChange={(e) => {
                  const all = [...new Set(images.map((x) =>
                    assets.find((a) => a.id === x.firmware_asset_id)?.kind ?? ""))].filter(Boolean);
                  const cur = kinds ?? all;
                  const k = asset?.kind ?? "";
                  const next = e.target.checked ? [...new Set([...cur, k])] : cur.filter((x) => x !== k);
                  onPatch(next.length === all.length ? omit(step, "kinds") : { ...step, kinds: next });
                }}
              />{" "}
              write
            </label>
            <button
              type="button"
              className="btn btn-sm row-del"
              onClick={() => onImagesChange(images.filter((_, j) => j !== i))}
            >
              ×
            </button>
          </span>
        );
      })}
      <select
        className="row-input"
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
      <span className="muted dim">
        Offsets default to the partition map for that chip and kind; override only if the layout says so.
      </span>
    </span>
  );
}

/** The download step's berryware bundle. */
function BundlePicker({ bundles, bundleId, onBundleChange }: FieldEditorProps) {
  const chosen = bundles.find((b) => b.id === bundleId);
  return (
    <span className="img-picker">
      <select
        className="row-input"
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


/** A published step's fields as text: parameters marked, artifacts named. */
function StepFields({
  step, spec, props,
}: {
  step: Step;
  spec: OpSpec;
  props: StepEditorProps;
}) {
  const rows: { label: string; node: React.ReactNode }[] = [];

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
function renderValue(text: string): React.ReactNode {
  const parts = text.split(/(\{\w+\})/g);
  return parts.map((part, i) =>
    /^\{\w+\}$/.test(part)
      ? <span key={i} className="ro-param" title="resolved at run time from a parameter or an earlier capture">{part}</span>
      : <span key={i}>{part}</span>,
  );
}
