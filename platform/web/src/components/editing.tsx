/** Shared building blocks for the component edit / create forms:
 *  base-symbol + category selects, properties editor table, datasheets editor. */
import { useEffect, useState } from "react";
import {
  errorMessage,
  getCategories,
  getFootprints,
  getSymbols,
  isAbortError,
  type CategoryNode,
  type FootprintListItem,
  type PropertyIn,
  type SymbolListItem,
} from "../api";

// ------------------------------------------------------------------- state

export interface EditRow {
  rid: number;
  key: string;
  value: string;
  is_null: boolean;
  hide: boolean;
  show_name: boolean;
  layout: Record<string, unknown> | null;
}

export interface EditDs {
  rid: number;
  id: number | null;
  label: string;
  source_url: string;
}

let ridSeq = 0;
/** Session-unique id for React keys on editor rows. */
export function nextRid(): number {
  return ridSeq++;
}

export function newEditRow(key: string, value = ""): EditRow {
  return {
    rid: nextRid(),
    key,
    value,
    is_null: false,
    hide: true,
    show_name: false,
    layout: null,
  };
}

/** Folds a pending, not-yet-added "Add property" row into the final list and
 *  maps to the POST body shape. Returns an error on duplicate keys. */
export function buildProperties(
  rows: EditRow[],
  newKey: string,
  newValue: string,
): { properties: PropertyIn[] } | { error: string } {
  let all = rows;
  const pending = newKey.trim();
  if (pending) {
    if (all.some((r) => r.key === pending)) {
      return { error: `Duplicate property key: ${pending}` };
    }
    all = [...all, newEditRow(pending, newValue)];
  }
  return {
    properties: all.map((r) => ({
      key: r.key,
      value: r.is_null ? null : r.value,
      is_null: r.is_null,
      hide: r.hide,
      show_name: r.show_name,
      layout: r.layout,
    })),
  };
}

// ----------------------------------------------------------------- pickers

export interface Pickers {
  symbols: SymbolListItem[];
  footprints: FootprintListItem[];
  cats: { id: number; label: string }[];
}

export function flattenCats(nodes: CategoryNode[], depth = 0): { id: number; label: string }[] {
  const out: { id: number; label: string }[] = [];
  for (const n of nodes) {
    out.push({ id: n.id, label: `${"— ".repeat(depth)}${n.name}` });
    out.push(...flattenCats(n.children, depth + 1));
  }
  return out;
}

/** Loads symbol/footprint/category pickers once, when `enabled` first becomes true. */
export function usePickers(enabled: boolean): { pickers: Pickers | null; pickerError: string | null } {
  const [pickers, setPickers] = useState<Pickers | null>(null);
  const [pickerError, setPickerError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || pickers !== null) return;
    const ctrl = new AbortController();
    setPickerError(null);
    Promise.all([getSymbols(ctrl.signal), getFootprints(ctrl.signal), getCategories(ctrl.signal)])
      .then(([symbols, footprints, cats]) =>
        setPickers({ symbols, footprints, cats: flattenCats(cats) }),
      )
      .catch((err) => {
        if (!isAbortError(err)) setPickerError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [enabled, pickers]);

  return { pickers, pickerError };
}

// ----------------------------------------------------------------- selects

export function BaseSymbolSelect({
  value,
  pickers,
  onChange,
}: {
  value: string;
  pickers: Pickers | null;
  onChange: (v: string) => void;
}) {
  const inList = pickers !== null && pickers.symbols.some((s) => s.name === value);
  return (
    <select
      className="sel"
      value={value}
      disabled={pickers === null}
      onChange={(e) => onChange(e.target.value)}
    >
      {value === "" ? <option value="">— choose —</option> : null}
      {pickers === null ? (
        value !== "" ? (
          <option value={value}>{value} (loading…)</option>
        ) : null
      ) : (
        <>
          {!inList && value !== "" ? <option value={value}>{value}</option> : null}
          {pickers.symbols.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name} ({s.pin_count ?? "?"} pins)
            </option>
          ))}
        </>
      )}
    </select>
  );
}

export function CategorySelect({
  value,
  pickers,
  fallbackLabel,
  onChange,
}: {
  value: number | "";
  pickers: Pickers | null;
  fallbackLabel: string;
  onChange: (v: number | "") => void;
}) {
  const inList = pickers !== null && value !== "" && pickers.cats.some((c) => c.id === value);
  return (
    <select
      className="sel"
      value={value === "" ? "" : String(value)}
      disabled={pickers === null}
      onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
    >
      {value === "" ? <option value="">— choose —</option> : null}
      {pickers === null ? (
        value !== "" ? (
          <option value={String(value)}>{fallbackLabel} (loading…)</option>
        ) : null
      ) : (
        <>
          {!inList && value !== "" ? <option value={String(value)}>{fallbackLabel}</option> : null}
          {pickers.cats.map((c) => (
            <option key={c.id} value={String(c.id)}>
              {c.label}
            </option>
          ))}
        </>
      )}
    </select>
  );
}

export function FootprintDatalist({ id, pickers }: { id: string; pickers: Pickers | null }) {
  return (
    <datalist id={id}>
      {pickers?.footprints.map((f) => (
        <option key={f.name} value={`7Sigma:${f.name}`} />
      ))}
    </datalist>
  );
}

// -------------------------------------------------------- properties editor

export function PropertiesEditor({
  rows,
  newKey,
  newValue,
  fpDatalistId,
  onRows,
  onNew,
  onError,
}: {
  rows: EditRow[];
  newKey: string;
  newValue: string;
  fpDatalistId: string;
  onRows: (rows: EditRow[]) => void;
  onNew: (patch: { newKey?: string; newValue?: string }) => void;
  onError: (msg: string) => void;
}) {
  const updateRow = (rid: number, patch: Partial<EditRow>) =>
    onRows(rows.map((r) => (r.rid === rid ? { ...r, ...patch } : r)));

  const addRow = () => {
    const key = newKey.trim();
    if (!key) return;
    if (rows.some((r) => r.key === key)) {
      onError(`Duplicate property key: ${key}`);
      return;
    }
    onRows([...rows, newEditRow(key, newValue)]);
    onNew({ newKey: "", newValue: "" });
  };

  return (
    <table className="data props props-edit">
      <thead>
        <tr>
          <th>Key</th>
          <th>Value</th>
          <th className="ctr">Null</th>
          <th className="ctr">Hide</th>
          <th className="ctr" aria-label="Actions"></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.rid}>
            <td className={"mono prop-key" + (r.hide ? " dim" : "")}>{r.key}</td>
            <td>
              {r.is_null ? (
                <span className="null">null</span>
              ) : (
                <input
                  type="text"
                  className="text mono row-input"
                  value={r.value}
                  list={r.key === "Footprint" ? fpDatalistId : undefined}
                  onChange={(e) => updateRow(r.rid, { value: e.target.value })}
                  aria-label={`Value of ${r.key}`}
                />
              )}
            </td>
            <td className="ctr">
              <input
                type="checkbox"
                checked={r.is_null}
                onChange={(e) => updateRow(r.rid, { is_null: e.target.checked })}
                aria-label={`${r.key} is null`}
              />
            </td>
            <td className="ctr">
              <input
                type="checkbox"
                checked={r.hide}
                onChange={(e) => updateRow(r.rid, { hide: e.target.checked })}
                aria-label={`${r.key} hidden`}
              />
            </td>
            <td className="ctr">
              <button
                type="button"
                className="row-del"
                onClick={() => onRows(rows.filter((x) => x.rid !== r.rid))}
                aria-label={`Delete ${r.key}`}
                title={`Delete ${r.key}`}
              >
                &#x2715;
              </button>
            </td>
          </tr>
        ))}
        <tr className="add-row">
          <td>
            <input
              type="text"
              className="text mono row-input"
              placeholder="New key"
              value={newKey}
              onChange={(e) => onNew({ newKey: e.target.value })}
              aria-label="New property key"
            />
          </td>
          <td colSpan={3}>
            <input
              type="text"
              className="text mono row-input"
              placeholder="Value"
              value={newValue}
              onChange={(e) => onNew({ newValue: e.target.value })}
              aria-label="New property value"
            />
          </td>
          <td className="ctr">
            <button type="button" className="btn btn-sm" disabled={!newKey.trim()} onClick={addRow}>
              Add
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  );
}

// --------------------------------------------------------- datasheet editor

export function DatasheetsEditor({
  rows,
  onRows,
}: {
  rows: EditDs[];
  onRows: (rows: EditDs[]) => void;
}) {
  const update = (rid: number, patch: Partial<EditDs>) =>
    onRows(rows.map((d) => (d.rid === rid ? { ...d, ...patch } : d)));

  return (
    <div className="ds-edit">
      {rows.map((d, i) => (
        <div key={d.rid} className="ds-row">
          <input
            type="text"
            className="text mono row-input ds-label-input"
            value={d.label}
            placeholder="Label"
            onChange={(e) => update(d.rid, { label: e.target.value })}
            aria-label={`Datasheet ${i + 1} label`}
          />
          {i === 0 ? <span className="tag-hidden">primary</span> : null}
          <input
            type="text"
            className="text mono row-input ds-url-input"
            value={d.source_url}
            placeholder="https://…"
            onChange={(e) => update(d.rid, { source_url: e.target.value })}
            aria-label={`Datasheet ${i + 1} URL`}
          />
          <button
            type="button"
            className="row-del"
            onClick={() => onRows(rows.filter((x) => x.rid !== d.rid))}
            aria-label={`Delete datasheet ${d.label || i + 1}`}
            title="Delete datasheet"
          >
            &#x2715;
          </button>
        </div>
      ))}
      <div className="ds-row">
        <button
          type="button"
          className="btn btn-sm"
          onClick={() =>
            onRows([...rows, { rid: nextRid(), id: null, label: "Datasheet", source_url: "" }])
          }
        >
          Add datasheet
        </button>
        <span className="rail-hint">first row is the KiCad-native Datasheet field</span>
      </div>
    </div>
  );
}
