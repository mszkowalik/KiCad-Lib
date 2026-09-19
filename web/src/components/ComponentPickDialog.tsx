/** Pick a LIBRARY component for something that names a part.
 *
 *  Until this existed the link could only be made two ways: by the resolver
 *  (`Resolve parts`, which matches on MPN and gives up when the match is not
 *  unique), or by an API client passing `component_id` directly — which the
 *  manual line form never sent, so a line the matcher could not place stayed
 *  unlinked forever. An unlinked part line keys as `m<MPN>` in the cost pool
 *  and can never meet a BOM draw, so the component silently costs nothing.
 *
 *  The dialog writes `component_id`, and writes `mpn` with it when the line had
 *  none: the pool normalises MPN keys, and a line linked to a part but carrying
 *  a different spelling would split that part into two pool entries.
 *
 *  It also serves the batch Materials tab, which picks the part a substitution
 *  FITTED — hence `subject` rather than a cost line, and `allowFreeText`. A
 *  part the supplier provided from its own shelf was never bought by us, so it
 *  legitimately has no library component and no invoice line; refusing to name
 *  it would mean the substitution could not be recorded at all.
 */
import { useEffect, useRef, useState } from "react";
import {
  errorMessage,
  isAbortError,
  listComponents,
  updateCostLine,
  type ComponentListItem,
} from "../api";
import { ErrorBanner, Spinner } from "./Ui";
import { useModal } from "./modal";

/** What is being named. A cost line satisfies it structurally; so does a BOM
 *  position with nothing but a designator. */
export interface PickSubject {
  id?: number;
  label?: string | null;
  kind?: string;
  mpn?: string | null;
  component_id?: number | null;
  component_name?: string | null;
}

export default function ComponentPickDialog({
  line, onClose, onPick, allowFreeText = false, title, confirmLabel,
}: {
  line: PickSubject;
  onClose: (changed: boolean) => void;
  /** Given, the dialog RETURNS the choice instead of writing it. A draft line
   *  has no id to PATCH, and a saved line inside a batch edit must not be
   *  written before the batch is. */
  onPick?: (componentId: number | null, mpn: string) => void;
  /** Allow a part that is NOT in the library, named by what was typed. Only
   *  meaningful with `onPick` — there is nothing to PATCH a free-text part
   *  onto. */
  allowFreeText?: boolean;
  title?: string;
  confirmLabel?: string;
}) {
  const modal = useModal(() => onClose(false));
  // Seed the search with the line's own MPN: the common case is a part the
  // resolver could not place uniquely, and the operator is about to type the
  // same string it already holds.
  const [query, setQuery] = useState(line.mpn || line.label || "");
  const [hits, setHits] = useState<ComponentListItem[] | null>(null);
  const [chosen, setChosen] = useState<number | null>(line.component_id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setHits([]); return; }
    const ac = new AbortController();
    // Debounced: the search runs on every keystroke otherwise, and the part
    // catalogue is large enough for that to queue requests behind each other.
    timer.current = window.setTimeout(() => {
      listComponents({ q, page_size: 25 }, ac.signal)
        .then((r) => setHits(r.items))
        .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    }, 250);
    return () => { window.clearTimeout(timer.current); ac.abort(); };
  }, [query]);

  const save = async (componentId: number | null, freeText = "") => {
    const hit = (hits || []).find((h) => h.id === componentId);
    if (onPick) {
      onPick(
        componentId,
        freeText || (componentId && !line.mpn ? (hit?.mfg_pn || "") : (line.mpn || "")),
      );
      onClose(true);
      return;
    }
    if (line.id === undefined) return;
    setBusy(true);
    setError(null);
    try {
      await updateCostLine(line.id, {
        component_id: componentId,
        // Only FILL an empty MPN. Overwriting one the invoice printed would
        // lose what the supplier actually billed.
        ...(componentId && !line.mpn && hit?.mfg_pn ? { mpn: hit.mfg_pn } : {}),
      });
      onClose(true);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card" {...modal.cardProps}>
        <h2 className="card-title">{title ?? "Link to a library component"}</h2>
        <p className="card-subtitle">
          “{line.label || line.kind}”
          {line.mpn ? <> — MPN <span className="mono">{line.mpn}</span></> : null}
          {line.component_name ? <> · linked to <strong>{line.component_name}</strong></> : null}
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        <input
          className="text modal-input"
          value={query}
          autoFocus
          placeholder="Search by MPN, name or manufacturer"
          onChange={(e) => setQuery(e.target.value)}
        />
        {hits === null ? (
          <Spinner label="Searching…" />
        ) : hits.length === 0 ? (
          <p className="dim">
            {query.trim().length < 2
              ? "Type at least two characters."
              : allowFreeText
                ? "No component matches — use it as typed below if the supplier provided it."
                : "No component matches. A part bought but not in the library has to be added first."}
          </p>
        ) : (
          <div className="pick-list">
            <table className="data">
              <tbody>
                {hits.map((h) => (
                  <tr key={h.id} onClick={() => setChosen(h.id)}>
                    <td className="ctr">
                      <input
                        type="radio"
                        name="component-pick"
                        checked={chosen === h.id}
                        onChange={() => setChosen(h.id)}
                      />
                    </td>
                    <td>
                      {h.name}
                      {h.mfg_pn && h.mfg_pn !== h.name ? (
                        <span className="mono"> · {h.mfg_pn}</span>
                      ) : null}
                      <div className="dim">
                        {[h.manufacturer, h.category_path].filter(Boolean).join(" · ")}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="btn-row modal-actions">
          <button type="button" className="btn" onClick={() => onClose(false)} disabled={busy}>
            Cancel
          </button>
          {allowFreeText && query.trim().length >= 2 ? (
            <button
              type="button"
              className="btn"
              onClick={() => save(null, query.trim())}
              disabled={busy}
              title="Record the part by name alone. Right for something the supplier
                     provided from its own shelf — we never bought it, so it has no
                     library component and no invoice line."
            >
              Use “{query.trim()}” as typed
            </button>
          ) : null}
          {line.component_id ? (
            <button
              type="button"
              className="btn"
              onClick={() => save(null)}
              disabled={busy}
              title="Unlink: the line keeps its MPN and falls back to keying the pool by that string"
            >
              Unlink
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => save(chosen)}
            disabled={busy || chosen === null || chosen === line.component_id}
          >
            {busy ? "Saving…" : (confirmLabel ?? "Link")}
          </button>
        </div>
      </div>
    </div>
  );
}
