/** Interactive data table shared by the BOM / costs views: sortable header,
 *  per-column filter row and fixed column widths (truncating with an
 *  ellipsis) so tables never scroll horizontally — the same treatment as the
 *  component browser and JLC stock tables. Reuses the browser's CSS
 *  (.th-sort/.sort-ind/.filter-row/.filter-input). */
import { useMemo, useState, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  label: string;
  /** Value used for sorting and filtering (rendering too unless `render`). */
  get: (row: T) => string | number | null | undefined;
  render?: (row: T) => ReactNode;
  /** Right-aligned, numerically sorted. */
  numeric?: boolean;
  /** Column width in % — give every column one; they should sum to ~100. */
  width: number;
  /** Extra class for body cells (e.g. "mono"). */
  className?: string;
  /** Set false for action/icon columns — no filter input, no sort button. */
  interactive?: boolean;
  /** Optional title attribute for body cells (defaults to the text value). */
  title?: (row: T) => string | undefined;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  rowClass?: (row: T) => string;
  /** Rows sort within their group; groups keep order (e.g. extra items
   *  pinned after schematic lines regardless of sorting). */
  group?: (row: T) => number;
  empty?: string;
}

type Dir = "asc" | "desc";

export default function DataTable<T>({ columns, rows, rowKey, rowClass, group, empty }: Props<T>) {
  const [sort, setSort] = useState<{ key: string; dir: Dir } | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});

  const anyFilter = Object.values(filters).some((v) => v.trim() !== "");

  const visible = useMemo(() => {
    let out = rows;
    const active = columns.filter((c) => (filters[c.key] ?? "").trim() !== "");
    if (active.length > 0) {
      out = out.filter((row) =>
        active.every((c) =>
          String(c.get(row) ?? "")
            .toLowerCase()
            .includes(filters[c.key].trim().toLowerCase()),
        ),
      );
    }
    const col = sort !== null ? columns.find((c) => c.key === sort.key) : undefined;
    if (sort !== null && col !== undefined) {
      const mul = sort.dir === "asc" ? 1 : -1;
      out = [...out].sort((a, b) => {
        if (col.numeric) {
          const av = parseFloat(String(col.get(a) ?? ""));
          const bv = parseFloat(String(col.get(b) ?? ""));
          const an = Number.isNaN(av);
          const bn = Number.isNaN(bv);
          if (an && bn) return 0;
          if (an) return 1; // unparsable always last
          if (bn) return -1;
          return (av - bv) * mul;
        }
        return (
          String(col.get(a) ?? "")
            .toLowerCase()
            .localeCompare(String(col.get(b) ?? "").toLowerCase()) * mul
        );
      });
    }
    if (group) {
      // stable: keeps the (possibly sorted) order within each group
      out = [...out].sort((a, b) => group(a) - group(b));
    }
    return out;
  }, [rows, columns, filters, sort, group]);

  const cycleSort = (key: string) =>
    setSort((prev) =>
      prev === null || prev.key !== key
        ? { key, dir: "asc" }
        : prev.dir === "asc"
          ? { key, dir: "desc" }
          : null,
    );

  const clearCol = columns.find((c) => c.interactive === false);

  return (
    <table className="data data-fixed">
      <colgroup>
        {columns.map((c) => (
          <col key={c.key} style={{ width: `${c.width}%` }} />
        ))}
      </colgroup>
      <thead>
        <tr>
          {columns.map((c) =>
            c.interactive === false ? (
              <th key={c.key} className={c.numeric ? "num" : undefined}>
                {c.label}
              </th>
            ) : (
              <th key={c.key} className={c.numeric ? "num" : undefined}>
                <button
                  type="button"
                  className="th-sort"
                  onClick={() => cycleSort(c.key)}
                  title={`Sort by ${c.label}`}
                >
                  {c.label}
                  {sort?.key === c.key ? (
                    <span className="sort-ind">{sort.dir === "asc" ? "▲" : "▼"}</span>
                  ) : null}
                </button>
              </th>
            ),
          )}
        </tr>
        <tr className="filter-row">
          {columns.map((c) => (
            <td key={c.key} className={c.interactive === false ? "ctr" : undefined}>
              {c.interactive === false ? (
                anyFilter && clearCol?.key === c.key ? (
                  <button
                    type="button"
                    className="row-del clear-filters"
                    onClick={() => setFilters({})}
                    title="Clear filters"
                    aria-label="Clear filters"
                  >
                    &#x2715;
                  </button>
                ) : null
              ) : (
                <input
                  type="text"
                  className="text filter-input"
                  placeholder="filter…"
                  value={filters[c.key] ?? ""}
                  onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                  aria-label={`Filter ${c.label}`}
                />
              )}
            </td>
          ))}
        </tr>
      </thead>
      <tbody>
        {visible.map((row) => (
          <tr key={rowKey(row)} className={rowClass?.(row) || undefined}>
            {columns.map((c) => {
              const text = String(c.get(row) ?? "");
              return (
                <td
                  key={c.key}
                  className={[c.numeric ? "num" : "", c.className ?? ""].join(" ").trim() || undefined}
                  title={c.title ? c.title(row) : text || undefined}
                >
                  {c.render ? c.render(row) : text}
                </td>
              );
            })}
          </tr>
        ))}
        {visible.length === 0 ? (
          <tr>
            <td colSpan={columns.length} className="empty">
              {anyFilter ? "No rows match the filters." : (empty ?? "No rows.")}
            </td>
          </tr>
        ) : null}
      </tbody>
    </table>
  );
}
