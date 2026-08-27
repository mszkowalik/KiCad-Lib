import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getSymbolSimLink,
  isAbortError,
  removeSymbolSimLink,
  saveSymbolSimLink,
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

/** The symbol's simulation link: which sim model it uses and how its pins map
 *  to the model's subcircuit ports. Saving PUBLISHES — the mirror rebuilds and
 *  every component of the symbol gets its Sim fields immediately. */
export default function SimLinkCard({ symbolId }: { symbolId: number }) {
  const [info, setInfo] = useState<SymbolSimLinkInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modelName, setModelName] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const dialog = useDialog();

  useEffect(() => {
    const ctrl = new AbortController();
    setInfo(null);
    setError(null);
    setNotice(null);
    setWarnings([]);
    getSymbolSimLink(symbolId, ctrl.signal)
      .then((d) => {
        setInfo(d);
        setModelName(d.link?.model_name ?? "");
        setDraft(d.link?.pin_map ?? {});
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [symbolId]);

  const pins = useMemo(() => (info ? uniquePins(info) : []), [info]);
  const model = info?.models.find((m) => m.name === modelName) ?? null;
  const nc = info?.nc ?? "-";

  // Which ports are still unclaimed — the same structural rule the server
  // enforces, surfaced live so the Save click rarely bounces.
  const claimed = pins.map((p) => draft[p.number]).filter((v) => v && v !== nc);
  const unmappedPins = pins.filter((p) => !draft[p.number]);
  const missingPorts = model ? model.ports.filter((port) => !claimed.includes(port)) : [];
  const doubled = model
    ? model.ports.filter((port) => claimed.filter((c) => c === port).length > 1)
    : [];
  const complete =
    model !== null && unmappedPins.length === 0 && missingPorts.length === 0 && doubled.length === 0;

  const pickModel = (name: string) => {
    setModelName(name);
    setNotice(null);
    setWarnings([]);
    // Keep the draft where the link already used this model; start clean otherwise.
    setDraft(info?.link && info.link.model_name === name ? info.link.pin_map : {});
  };

  const save = async () => {
    if (!info || !model || saving) return;
    setSaving(true);
    setNotice(null);
    setWarnings([]);
    try {
      const res = await saveSymbolSimLink(symbolId, model.name, draft);
      setWarnings([...(res.heuristic_warnings ?? []), ...res.mirror_warnings]);
      setNotice(`Linked to ${res.model} — the library now serves the Sim fields.`);
      const fresh = await getSymbolSimLink(symbolId);
      setInfo(fresh);
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!info?.link || saving) return;
    const ok = await dialog.confirm(
      `Remove the ${info.link.model_name} link? Every component of this symbol loses its ` +
        `Sim fields on the next library fetch.`,
      { title: "Remove sim link", confirmLabel: "Remove", tone: "danger" },
    );
    if (!ok) return;
    setSaving(true);
    setNotice(null);
    setWarnings([]);
    try {
      await removeSymbolSimLink(symbolId);
      setNotice("Link removed.");
      const fresh = await getSymbolSimLink(symbolId);
      setInfo(fresh);
      setModelName("");
      setDraft({});
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

          <div className="btn-row">
            <select
              className="row-input sim-model-pick"
              value={modelName}
              aria-label="Sim model"
              onChange={(e) => pickModel(e.target.value)}
            >
              <option value="">— no model —</option>
              {info.models.map((m) => (
                <option key={m.id} value={m.name}>
                  {m.name} ({m.ports.join(" ")})
                </option>
              ))}
            </select>
            {model ? (
              <Link
                to={`/library/templates/sim/${model.id}`}
                className="comp-link"
              >
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
                    <td className="mono">{p.number}{p.stacked > 1 ? ` ×${p.stacked}` : ""}</td>
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

          {model && !complete ? (
            <p className="muted rail-hint">
              {unmappedPins.length > 0
                ? `Unmapped pins: ${unmappedPins.map((p) => p.number).join(", ")}. `
                : ""}
              {missingPorts.length > 0 ? `Ports without a pin: ${missingPorts.join(", ")}. ` : ""}
              {doubled.length > 0 ? `Ports claimed twice: ${doubled.join(", ")}.` : ""}
            </p>
          ) : null}

          <div className="btn-row">
            <button
              type="button"
              className="btn btn-accent"
              disabled={saving || !complete}
              onClick={() => void save()}
            >
              {saving ? "Saving…" : info.link ? "Save link" : "Link model"}
            </button>
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
                by {info.link.updated_by}
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
