import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getSymbolSimLink,
  isAbortError,
  previewSimComposition,
  removeSymbolSimLink,
  saveSimComposition,
  saveSymbolSimLink,
  SIM_OWN,
  SIM_SHARED,
  type SimBlock,
  type SimBlockSpec,
  type SimComposition,
  type SimCompositionPreview,
  type SimTie,
  type SymbolSimLinkInfo,
} from "../api";
import { useDialog } from "./Dialog";
import { ErrorBanner, Spinner } from "./Ui";

/** One row per unique pin NUMBER, visible pin's name/type winning over a
 *  hidden stacked duplicate's — the map only has to name each number once
 *  (KiCad nets stacked pins together). Mirrors simmodel.validate_pin_map. */
function uniquePins(info: SymbolSimLinkInfo) {
  const byNumber = new Map<string, { number: string; name: string; type: string; stacked: number }>();
  for (const p of info.pins) {
    if (!p.number) continue;
    const seen = byNumber.get(p.number);
    if (!seen) {
      byNumber.set(p.number, { number: p.number, name: p.name, type: p.type, stacked: 1 });
    } else {
      seen.stacked += 1;
      if (!p.hide) {
        seen.name = p.name;
        seen.type = p.type;
      }
    }
  }
  return [...byNumber.values()].sort((a, b) =>
    a.number.localeCompare(b.number, undefined, { numeric: true }),
  );
}

const EMPTY: SimComposition = { blocks: [], resistors: [], unmodelled: [], defaults: {} };

/** Every node a composition mentions, so a cell can offer the nets already in
 *  use instead of making the author retype one. */
function knownNets(c: SimComposition): string[] {
  const out = new Set<string>();
  for (const b of c.blocks) {
    for (const v of Object.values(b.nodes || {})) if (v?.startsWith("@")) out.add(v);
  }
  for (const r of c.resistors) {
    for (const v of [r.a, r.b]) if (v?.startsWith("@")) out.add(v);
  }
  return [...out].sort();
}

/** Pin -> the block ports and ties sitting on it. The inverse of the editor,
 *  and the view that makes a missed pin or a crossed rail visible. */
function coverage(c: SimComposition): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  const add = (node: string, label: string) => {
    if (!node || node.startsWith("@")) return;
    (out[node] ||= []).push(label);
  };
  for (const b of c.blocks) {
    for (const [port, node] of Object.entries(b.nodes || {})) add(node, `${b.ref}.${port}`);
  }
  for (const r of c.resistors) {
    add(r.a, `R${r.ref}`);
    add(r.b, `R${r.ref}`);
  }
  return out;
}

function nextRef(taken: Set<string>, stem: string) {
  for (let i = 1; ; i += 1) {
    const ref = `${stem}${i}`;
    if (!taken.has(ref)) return ref;
  }
}

/** A node cell: a symbol pin, or an internal net whose name is typed beside
 *  the picker. Nodes are never shared as one PORT — see simcompose.py. */
function NodePick({
  value,
  pins,
  nets,
  onChange,
  label,
}: {
  value: string;
  pins: ReturnType<typeof uniquePins>;
  nets: string[];
  onChange: (v: string) => void;
  label: string;
}) {
  const isNet = value.startsWith("@");
  return (
    <div className="sim-node-cell">
      <select
        className="row-input"
        aria-label={label}
        value={isNet ? "@" : value}
        onChange={(e) => onChange(e.target.value === "@" ? "@" : e.target.value)}
      >
        <option value="">— pick —</option>
        {pins.map((p) => (
          <option key={p.number} value={p.number}>
            pin {p.number}
            {p.name ? ` ${p.name}` : ""} ({p.type})
          </option>
        ))}
        {nets.map((n) => (
          <option key={n} value={n}>
            {n} (internal)
          </option>
        ))}
        <option value="@">internal net…</option>
      </select>
      {isNet ? (
        <input
          className="row-input sim-net-name"
          aria-label={`${label} net name`}
          placeholder="net name"
          value={value.slice(1)}
          onChange={(e) => onChange("@" + e.target.value.replace(/[^A-Za-z0-9_]/g, ""))}
        />
      ) : null}
    </div>
  );
}

/** The parameter bindings of one block. Collapsed by default: sharing is
 *  right for every dual-gate package in this library, because both halves are
 *  one die. `own` exists for the part where they are not. */
function BlockParams({
  block,
  spec,
  onChange,
}: {
  block: SimBlock;
  spec: SimBlockSpec;
  onChange: (params: Record<string, string>) => void;
}) {
  const names = Object.keys(spec.params);
  if (names.length === 0) return null;
  const bindingOf = (p: string) => block.params?.[p] ?? SIM_SHARED;
  const kindOf = (p: string) => {
    const b = bindingOf(p);
    if (b === SIM_OWN) return "own";
    if (b === SIM_SHARED || b.startsWith(`${SIM_SHARED}:`)) return "shared";
    return "fixed";
  };
  const set = (p: string, v: string) => onChange({ ...(block.params || {}), [p]: v });
  const custom = names.filter((p) => bindingOf(p).startsWith(`${SIM_SHARED}:`)).length;
  return (
    <details className="sim-params">
      <summary>
        parameters ({names.length}
        {custom ? `, ${custom} renamed` : ""})
      </summary>
      <table className="kv sim-map-table">
        <tbody>
          <tr>
            <th>Parameter</th>
            <th>Default</th>
            <th>Binding</th>
            <th>Wrapper name / value</th>
          </tr>
          {names.map((p) => {
            const kind = kindOf(p);
            const binding = bindingOf(p);
            return (
              <tr key={p}>
                <td className="mono">{p}</td>
                <td className="muted mono">{spec.params[p]}</td>
                <td>
                  <select
                    className="row-input"
                    aria-label={`${block.ref} ${p} binding`}
                    value={kind}
                    onChange={(e) =>
                      set(
                        p,
                        e.target.value === "own"
                          ? SIM_OWN
                          : e.target.value === "shared"
                            ? SIM_SHARED
                            : spec.params[p],
                      )
                    }
                  >
                    <option value="shared">shared</option>
                    <option value="own">per block</option>
                    <option value="fixed">fixed value</option>
                  </select>
                </td>
                <td>
                  {kind === "shared" ? (
                    <input
                      className="row-input"
                      aria-label={`${block.ref} ${p} wrapper name`}
                      placeholder={p}
                      value={binding.startsWith(`${SIM_SHARED}:`) ? binding.slice(8) : ""}
                      onChange={(e) =>
                        set(p, e.target.value ? `${SIM_SHARED}:${e.target.value}` : SIM_SHARED)
                      }
                    />
                  ) : kind === "fixed" ? (
                    <input
                      className="row-input"
                      aria-label={`${block.ref} ${p} value`}
                      value={binding}
                      onChange={(e) => set(p, e.target.value)}
                    />
                  ) : (
                    <span className="muted mono">
                      {block.ref.toUpperCase()}_{p.toUpperCase()}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </details>
  );
}

/** The symbol's simulation model. Two modes, and the switch is permanent
 *  rather than a migration aid: a composition wires blocks together, so
 *  anything with behaviour of its own — a behavioural source, a `.model`
 *  card — stays a hand-written model that this card merely links. */
export default function SimLinkCard({ symbolId }: { symbolId: number }) {
  const [info, setInfo] = useState<SymbolSimLinkInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"model" | "composed">("composed");
  const [modelName, setModelName] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [comp, setComp] = useState<SimComposition>(EMPTY);
  const [preview, setPreview] = useState<SimCompositionPreview | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [showSource, setShowSource] = useState(false);
  const dialog = useDialog();
  const previewSeq = useRef(0);

  const load = useCallback((signal?: AbortSignal) => {
    return getSymbolSimLink(symbolId, signal).then((d) => {
      setInfo(d);
      setModelName(d.link?.model_name ?? "");
      setDraft(d.link?.pin_map ?? {});
      const composed = d.link?.mode === "composed" && d.link.composition;
      setComp(composed ? { ...EMPTY, ...d.link!.composition! } : EMPTY);
      setMode(d.link ? (d.link.mode === "composed" ? "composed" : "model") : "composed");
      return d;
    });
  }, [symbolId]);

  useEffect(() => {
    const ctrl = new AbortController();
    setInfo(null);
    setError(null);
    setNotice(null);
    setWarnings([]);
    setPreview(null);
    load(ctrl.signal).catch((err) => {
      if (!isAbortError(err)) setError(errorMessage(err));
    });
    return () => ctrl.abort();
  }, [load]);

  // Preview is debounced and sequenced: the editor changes on every keystroke
  // and a late response must not overwrite a newer one.
  useEffect(() => {
    if (!info || mode !== "composed") return;
    if (comp.blocks.length === 0 && comp.resistors.length === 0) {
      setPreview(null);
      return;
    }
    const seq = (previewSeq.current += 1);
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      previewSimComposition(symbolId, comp, ctrl.signal)
        .then((p) => {
          if (seq === previewSeq.current) setPreview(p);
        })
        .catch((err) => {
          if (!isAbortError(err) && seq === previewSeq.current) {
            setPreview({
              name: info.wrapper_name, params: {}, source_text: "", ports: [], pin_map: {},
              sim_pins: "", errors: [errorMessage(err)], warnings: [],
            });
          }
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [comp, info, mode, symbolId]);

  const pins = useMemo(() => (info ? uniquePins(info) : []), [info]);
  const specs = useMemo(
    () => Object.fromEntries((info?.blocks ?? []).map((b) => [b.name, b])),
    [info],
  );
  const nets = useMemo(() => knownNets(comp), [comp]);
  const cover = useMemo(() => coverage(comp), [comp]);
  const model = info?.models.find((m) => m.name === modelName) ?? null;
  const nc = info?.nc ?? "-";

  // ---- single-model mode, unchanged rules ----
  const claimed = pins.map((p) => draft[p.number]).filter((v) => v && v !== nc);
  const unmappedPins = pins.filter((p) => !draft[p.number]);
  const missingPorts = model ? model.ports.filter((port) => !claimed.includes(port)) : [];
  const doubled = model
    ? model.ports.filter((port) => claimed.filter((c) => c === port).length > 1)
    : [];
  const linkComplete =
    model !== null && unmappedPins.length === 0 && missingPorts.length === 0 && doubled.length === 0;

  // ---- composed mode ----
  const loose = pins.filter(
    (p) => !(cover[p.number] || []).length && !comp.unmodelled.includes(p.number),
  );
  const composeReady =
    (comp.blocks.length > 0 || comp.resistors.length > 0) &&
    preview !== null &&
    preview.errors.length === 0;

  const patchBlock = (i: number, patch: Partial<SimBlock>) =>
    setComp((c) => ({ ...c, blocks: c.blocks.map((b, j) => (j === i ? { ...b, ...patch } : b)) }));
  const patchTie = (i: number, patch: Partial<SimTie>) =>
    setComp((c) => ({
      ...c,
      resistors: c.resistors.map((r, j) => (j === i ? { ...r, ...patch } : r)),
    }));

  const addBlock = (from?: SimBlock) =>
    setComp((c) => {
      const taken = new Set([...c.blocks.map((b) => b.ref), ...c.resistors.map((r) => r.ref)]);
      return {
        ...c,
        blocks: [
          ...c.blocks,
          from
            ? { ...from, ref: nextRef(taken, "u"), nodes: {} }
            : { ref: nextRef(taken, "u"), model: "", nodes: {}, params: {} },
        ],
      };
    });

  const addTie = () =>
    setComp((c) => {
      const taken = new Set([...c.blocks.map((b) => b.ref), ...c.resistors.map((r) => r.ref)]);
      return { ...c, resistors: [...c.resistors, { ref: nextRef(taken, "t"), a: "", b: "", value: "0.2m" }] };
    });

  const toggleUnmodelled = (num: string) =>
    setComp((c) => ({
      ...c,
      unmodelled: c.unmodelled.includes(num)
        ? c.unmodelled.filter((n) => n !== num)
        : [...c.unmodelled, num],
    }));

  const after = async (res: { heuristic_warnings?: string[]; mirror_warnings: string[] }, msg: string) => {
    setWarnings([...(res.heuristic_warnings ?? []), ...res.mirror_warnings]);
    setNotice(msg);
    await load();
  };

  const saveLink = async () => {
    if (!info || !model || saving) return;
    setSaving(true);
    setNotice(null);
    setWarnings([]);
    try {
      const res = await saveSymbolSimLink(symbolId, model.name, draft);
      await after(res, `Linked to ${res.model} — the library now serves the Sim fields.`);
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const saveComposed = async () => {
    if (!info || saving || !composeReady) return;
    setSaving(true);
    setNotice(null);
    setWarnings([]);
    try {
      const res = await saveSimComposition(symbolId, comp);
      await after(
        res,
        `Published ${res.model} v${res.version_no} from ${comp.blocks.length} block(s).`,
      );
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!info?.link || saving) return;
    const composed = info.link.mode === "composed";
    const ok = await dialog.confirm(
      `Remove the ${info.link.model_name} link? Every component of this symbol loses its ` +
        `Sim fields on the next library fetch.` +
        (composed ? " The generated wrapper is deleted with it." : ""),
      { title: "Remove sim link", confirmLabel: "Remove", tone: "danger" },
    );
    if (!ok) return;
    setSaving(true);
    setNotice(null);
    setWarnings([]);
    try {
      await removeSymbolSimLink(symbolId);
      setNotice("Link removed.");
      await load();
      setModelName("");
      setDraft({});
      setComp(EMPTY);
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card pad">
      <h2 className="card-title">Simulation model</h2>
      {error ? <ErrorBanner message={error} /> : null}
      {!info && !error ? <Spinner label="Loading sim link" /> : null}
      {info ? (
        <>
          {info.link && info.link.stale.length > 0 ? (
            <div className="banner-warn">
              Sim fields are WITHHELD from the library until this map is re-confirmed:{" "}
              {info.link.stale.join("; ")}. Review the map below and save it again.
            </div>
          ) : null}

          <div className="btn-row sim-mode-row">
            <div className="seg-toggle" role="group" aria-label="Simulation model mode">
              <button
                type="button"
                className={`btn ${mode === "composed" ? "btn-accent" : ""}`}
                onClick={() => setMode("composed")}
              >
                Composed
              </button>
              <button
                type="button"
                className={`btn ${mode === "model" ? "btn-accent" : ""}`}
                onClick={() => setMode("model")}
              >
                Single model
              </button>
            </div>
            <span className="muted rail-hint">
              {mode === "composed"
                ? `Builds ${info.wrapper_name} from library blocks. One port per pin, so Sim.Pins is derived.`
                : "Links one hand-written subcircuit and stores the pin map you type."}
            </span>
          </div>

          {mode === "model" ? (
            <>
              <div className="btn-row">
                <select
                  className="row-input sim-model-pick"
                  value={modelName}
                  aria-label="Sim model"
                  onChange={(e) => {
                    setModelName(e.target.value);
                    setNotice(null);
                    setWarnings([]);
                    setDraft(
                      info.link && info.link.model_name === e.target.value
                        ? info.link.pin_map
                        : {},
                    );
                  }}
                >
                  <option value="">— no model —</option>
                  {info.models.map((m) => (
                    <option key={m.id} value={m.name}>
                      {m.name} ({m.ports.join(" ")})
                    </option>
                  ))}
                </select>
                {model ? (
                  <Link to={`/library/templates/sim/${model.id}`} className="comp-link">
                    open model
                  </Link>
                ) : null}
              </div>

              {model ? (
                <table className="kv sim-map-table">
                  <tbody>
                    <tr>
                      <th>Pin</th>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Model port</th>
                    </tr>
                    {pins.map((p) => (
                      <tr key={p.number}>
                        <td className="mono">
                          {p.number}
                          {p.stacked > 1 ? ` ×${p.stacked}` : ""}
                        </td>
                        <td className="mono">{p.name || "—"}</td>
                        <td className="muted">{p.type}</td>
                        <td>
                          <select
                            className="row-input"
                            value={draft[p.number] ?? ""}
                            aria-label={`Port for pin ${p.number}`}
                            onChange={(e) =>
                              setDraft((d) => ({ ...d, [p.number]: e.target.value }))
                            }
                          >
                            <option value="">— pick —</option>
                            <option value={nc}>not connected ({nc})</option>
                            {model.ports.map((port) => (
                              <option key={port} value={port}>
                                {port}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="muted">
                  No model linked. Components of this symbol carry no Sim fields; pick a model
                  above to map its ports to the pins.
                </p>
              )}

              {model && !linkComplete ? (
                <p className="muted rail-hint">
                  {unmappedPins.length > 0
                    ? `Unmapped pins: ${unmappedPins.map((p) => p.number).join(", ")}. `
                    : ""}
                  {missingPorts.length > 0
                    ? `Ports without a pin: ${missingPorts.join(", ")}. `
                    : ""}
                  {doubled.length > 0 ? `Ports claimed twice: ${doubled.join(", ")}.` : ""}
                </p>
              ) : null}
            </>
          ) : (
            <div className="sim-compose">
              <div className="sim-blocks">
                {comp.blocks.map((block, i) => {
                  const spec = specs[block.model];
                  return (
                    <div className="sim-block" key={`${block.ref}-${i}`}>
                      <div className="btn-row sim-block-head">
                        <input
                          className="row-input sim-ref"
                          aria-label={`Block ${i + 1} reference`}
                          value={block.ref}
                          onChange={(e) =>
                            patchBlock(i, {
                              ref: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""),
                            })
                          }
                        />
                        <select
                          className="row-input sim-model-pick"
                          aria-label={`Block ${i + 1} model`}
                          value={block.model}
                          onChange={(e) =>
                            patchBlock(i, { model: e.target.value, nodes: {}, params: {} })
                          }
                        >
                          <option value="">— pick a block —</option>
                          {info.blocks.map((b) => (
                            <option key={b.name} value={b.name}>
                              {b.name} ({b.ports.join(" ")})
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          className="btn"
                          disabled={!spec}
                          onClick={() => addBlock(block)}
                        >
                          duplicate
                        </button>
                        <button
                          type="button"
                          className="btn btn-danger"
                          onClick={() =>
                            setComp((c) => ({ ...c, blocks: c.blocks.filter((_, j) => j !== i) }))
                          }
                        >
                          remove
                        </button>
                      </div>
                      {spec ? (
                        <>
                          <table className="kv sim-map-table">
                            <tbody>
                              <tr>
                                <th>Port</th>
                                <th>Node</th>
                              </tr>
                              {spec.ports.map((port) => (
                                <tr key={port}>
                                  <td className="mono">{port}</td>
                                  <td>
                                    <NodePick
                                      label={`${block.ref} ${port}`}
                                      value={block.nodes?.[port] ?? ""}
                                      pins={pins}
                                      nets={nets}
                                      onChange={(v) =>
                                        patchBlock(i, { nodes: { ...(block.nodes || {}), [port]: v } })
                                      }
                                    />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <BlockParams
                            block={block}
                            spec={spec}
                            onChange={(params) => patchBlock(i, { params })}
                          />
                        </>
                      ) : null}
                    </div>
                  );
                })}

                {comp.resistors.map((tie, i) => (
                  <div className="sim-block sim-tie" key={`${tie.ref}-${i}`}>
                    <div className="btn-row sim-block-head">
                      <input
                        className="row-input sim-ref"
                        aria-label={`Tie ${i + 1} reference`}
                        value={tie.ref}
                        onChange={(e) =>
                          patchTie(i, {
                            ref: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""),
                          })
                        }
                      />
                      <span className="muted rail-hint">tie</span>
                      <NodePick
                        label={`tie ${tie.ref} side a`}
                        value={tie.a}
                        pins={pins}
                        nets={nets}
                        onChange={(v) => patchTie(i, { a: v })}
                      />
                      <NodePick
                        label={`tie ${tie.ref} side b`}
                        value={tie.b}
                        pins={pins}
                        nets={nets}
                        onChange={(v) => patchTie(i, { b: v })}
                      />
                      <input
                        className="row-input sim-ref"
                        aria-label={`Tie ${tie.ref} resistance`}
                        value={tie.value}
                        onChange={(e) => patchTie(i, { value: e.target.value })}
                      />
                      <button
                        type="button"
                        className="btn btn-danger"
                        onClick={() =>
                          setComp((c) => ({
                            ...c,
                            resistors: c.resistors.filter((_, j) => j !== i),
                          }))
                        }
                      >
                        remove
                      </button>
                    </div>
                  </div>
                ))}

                <div className="btn-row">
                  <button type="button" className="btn" onClick={() => addBlock()}>
                    + block
                  </button>
                  <button type="button" className="btn" onClick={addTie}>
                    + tie
                  </button>
                  <span className="muted rail-hint">
                    A tie is package copper, or a termination. Two pins are never merged onto
                    one port — the schematic may put them on different nets.
                  </span>
                </div>

                {preview && Object.keys(preview.params).length > 0 ? (
                  <details className="sim-params">
                    <summary>wrapper defaults ({Object.keys(preview.params).length})</summary>
                    <p className="muted rail-hint">
                      What a component with no Sim.Params row runs on. Blank keeps the block
                      model's own default.
                    </p>
                    <table className="kv sim-map-table">
                      <tbody>
                        <tr>
                          <th>Parameter</th>
                          <th>Default</th>
                        </tr>
                        {Object.entries(preview.params).map(([k, v]) => (
                          <tr key={k}>
                            <td className="mono">{k}</td>
                            <td>
                              <input
                                className="row-input"
                                aria-label={`Default for ${k}`}
                                placeholder={v}
                                value={comp.defaults?.[k] ?? ""}
                                onChange={(e) =>
                                  setComp((c) => {
                                    const next = { ...(c.defaults || {}) };
                                    if (e.target.value) next[k] = e.target.value;
                                    else delete next[k];
                                    return { ...c, defaults: next };
                                  })
                                }
                              />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                ) : null}
              </div>

              <div className="sim-coverage">
                <h3 className="card-subtitle">Pin coverage</h3>
                <table className="kv sim-map-table">
                  <tbody>
                    <tr>
                      <th>Pin</th>
                      <th>Type</th>
                      <th>Goes to</th>
                    </tr>
                    {pins.map((p) => {
                      const at = cover[p.number] || [];
                      const off = comp.unmodelled.includes(p.number);
                      return (
                        <tr key={p.number} className={!at.length && !off ? "sim-loose" : ""}>
                          <td className="mono">
                            {p.number}
                            {p.name ? ` ${p.name}` : ""}
                          </td>
                          <td className="muted">{p.type}</td>
                          <td>
                            {at.length ? (
                              <span className="mono">{at.join(" ")}</span>
                            ) : (
                              <label className="sim-unmodelled">
                                <input
                                  type="checkbox"
                                  checked={off}
                                  onChange={() => toggleUnmodelled(p.number)}
                                />{" "}
                                not modelled
                              </label>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {loose.length > 0 ? (
                  <p className="muted rail-hint">
                    Wire or tick every pin: {loose.map((p) => p.number).join(", ")} is neither.
                  </p>
                ) : null}
              </div>

              <div className="sim-preview">
                <div className="btn-row">
                  <h3 className="card-subtitle">
                    {preview?.name ?? info.wrapper_name}
                    {preview && preview.errors.length === 0
                      ? ` — ${preview.ports.length} ports`
                      : ""}
                  </h3>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowSource((s) => !s)}
                    disabled={!preview || preview.errors.length > 0}
                  >
                    {showSource ? "hide netlist" : "show netlist"}
                  </button>
                </div>
                {preview && preview.errors.length > 0 ? (
                  <div className="banner-warn">
                    {preview.errors.map((e) => (
                      <div key={e}>{e}</div>
                    ))}
                  </div>
                ) : null}
                {preview && preview.warnings.length > 0 ? (
                  <p className="muted rail-hint">{preview.warnings.join(" · ")}</p>
                ) : null}
                {preview && preview.errors.length === 0 ? (
                  <p className="muted rail-hint mono">Sim.Pins {preview.sim_pins}</p>
                ) : null}
                {showSource && preview?.source_text ? (
                  <textarea
                    className="skill-textarea sim-src"
                    readOnly
                    value={preview.source_text}
                    aria-label="Generated subcircuit"
                  />
                ) : null}
              </div>
            </div>
          )}

          <div className="btn-row">
            {mode === "composed" ? (
              <button
                type="button"
                className="btn btn-accent"
                disabled={saving || !composeReady}
                onClick={() => void saveComposed()}
              >
                {saving ? "Publishing…" : "Publish model"}
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-accent"
                disabled={saving || !linkComplete}
                onClick={() => void saveLink()}
              >
                {saving ? "Saving…" : info.link ? "Save link" : "Link model"}
              </button>
            )}
            {info.link ? (
              <button
                type="button"
                className="btn btn-danger"
                disabled={saving}
                onClick={() => void remove()}
              >
                Remove link
              </button>
            ) : null}
            {info.link ? (
              <span className="muted rail-hint">
                {info.link.mode === "composed" ? "composed" : "linked"} by {info.link.updated_by}
                {info.link.updated_at
                  ? `, ${new Date(info.link.updated_at).toLocaleString()}`
                  : ""}
              </span>
            ) : null}
          </div>
          {notice ? <p className="muted">{notice}</p> : null}
          {warnings.length > 0 ? (
            <div className="banner-warn">
              {warnings.map((w) => (
                <div key={w}>{w}</div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
