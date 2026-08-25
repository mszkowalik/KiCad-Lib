/** The interactive table EVERY list in the platform goes through: sortable
 *  header, per-column filter row, fixed column widths (truncating with an
 *  ellipsis) so tables never scroll horizontally, optional expandable rows,
 *  and progressive rendering so a long list paints immediately.
 *
 *  It started as the BOM/costs table and is now the single answer to "this
 *  list needs sorting and filtering" — which is the point: a hand-rolled
 *  `<table className="data">` gets a different filter box, a different sort
 *  affordance and a different empty state every time somebody writes one.
 *  Reuses the browser's CSS (.th-sort/.sort-ind/.filter-row/.filter-input).
 *
 *  **Rows render in chunks.** `pageSize` rows are laid out at first paint and
 *  another chunk is added whenever the reader nears the end. Filtering and
 *  sorting still run over the WHOLE `rows` array, so this never narrows what a
 *  filter can find — it only bounds how much DOM exists at once. Server-side
 *  paging is a different mechanism for a different problem and lives in the
 *  two lists whose data genuinely does not fit (the change feed, the device
 *  list). */
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useStickyState } from "../useStickyState";
import { Spinner } from "./Ui";
import { useInfiniteScroll, useVisibleCount } from "./useInfiniteScroll";

export interface Column<T> {
  key: string;
  /** A node, not just a string: a header sometimes has to hold a control —
   *  the component browser's "select every unsigned row" checkbox lives in
   *  one. Sortable headers still need it to read as a label. */
  label: ReactNode;
  /** Value used for sorting and filtering (rendering too unless `render`). */
  get: (row: T) => string | number | null | undefined;
  /** Sort key, when sorting must not follow the printed text. The review and
   *  sign-off columns are the reason: they sort worst-first by RANK, because
   *  sorting them means "show me what still needs looking at", while their
   *  filter has to match the word the user can actually see. */
  sortValue?: (row: T) => string | number;
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
  /** This column's filter box is reported to the caller instead of being
   *  applied to `rows`. Set it on any table whose data is SERVER-paged: the
   *  browser holds one page, so filtering locally would search a slice and
   *  report "no rows match" about data it never saw. */
  serverFilter?: boolean;
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
  /** Sort applied before the user touches a header. */
  defaultSort?: { key: string; dir: Dir };
  /** Render an expanded panel under a row. Returning content makes the row
   *  clickable; the panel is only rendered while that row is open, which is
   *  what keeps a detail request from firing for rows nobody opened. */
  expand?: (row: T) => ReactNode;
  /** How many rows to lay out per chunk. */
  pageSize?: number;
  /** Rendered after the last row while more data is being fetched from the
   *  server — only meaningful for a server-paged list. */
  footer?: ReactNode;
  /** Sorting is the server's job (server-paged tables). Header clicks are
   *  reported through `onSortChange` and never applied to `rows`. */
  serverSort?: boolean;
  onSortChange?: (sort: { key: string; dir: Dir } | null) => void;
  /** Called (debounced by the caller if it wants) with the current values of
   *  every `serverFilter` column. */
  onServerFilters?: (filters: Record<string, string>) => void;
  /** Remember this table's sort and filters across navigation, under this key
   *  (see `useStickyState`). The component browser has always done this and
   *  losing it on the way through DataTable would be a regression; any list
   *  worth filtering wants it. */
  persistKey?: string;
  /** The rows that survived filtering and sorting, in display order — for a
   *  toolbar that acts on "everything shown" (the browser's bulk sign-off
   *  selects the FILTERED set, which is the whole point of filtering first). */
  onVisibleChange?: (rows: T[]) => void;
  /** Which row is open, when the PARENT owns that state. The review workbench
   *  needs this: its Prev/Next buttons step through the filtered list from
   *  inside the open panel, which internal-only state cannot express. Omit
   *  both and the table manages its own open row. */
  openKey?: string | number | null;
  onOpenChange?: (key: string | number | null) => void;
  /** Click anywhere in a row to act on it (open its page). Mutually exclusive
   *  with `expand`, which already owns the row click; links inside a clickable
   *  row must `stopPropagation()`. */
  onRowClick?: (row: T) => void;
}

type Dir = "asc" | "desc";

/** Per-instance scratch keys for tables that do not ask to be remembered. */
let anonTables = 0;

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowClass,
  group,
  empty,
  defaultSort,
  expand,
  pageSize = 60,
  footer,
  serverSort = false,
  onSortChange,
  onServerFilters,
  persistKey,
  onVisibleChange,
  openKey: openKeyProp,
  onOpenChange,
  onRowClick,
}: Props<T>) {
  // One hook either way: an unkeyed table gets a per-instance scratch key, so
  // there is no second code path to keep in step. The counter matters — every
  // unkeyed table sharing the literal key `table::sort` would have meant two
  // of them on one page silently sharing a sort and a filter set.
  const ownKeyRef = useRef<string | null>(null);
  if (ownKeyRef.current === null) ownKeyRef.current = `anon-${++anonTables}`;
  const key = persistKey ?? ownKeyRef.current;
  const [sort, setSort] = useStickyState<{ key: string; dir: Dir } | null>(
    `table:${key}:sort`,
    defaultSort ?? null,
  );
  const [filters, setFilters] = useStickyState<Record<string, string>>(`table:${key}:filters`, {});
  const [ownKey, setOwnKey] = useState<string | number | null>(null);
  const controlled = openKeyProp !== undefined;
  const openKey = controlled ? openKeyProp : ownKey;
  const setOpenKey = (k: string | number | null) => {
    if (!controlled) setOwnKey(k);
    onOpenChange?.(k);
  };

  const anyFilter = Object.values(filters).some((v) => v.trim() !== "");

  const visible = useMemo(() => {
    let out = rows;
    // A server-filtered column has already been applied by the server — running
    // it again here would filter the page a second time by the same text.
    const active = columns.filter(
      (c) => !c.serverFilter && (filters[c.key] ?? "").trim() !== "",
    );
    if (active.length > 0) {
      out = out.filter((row) =>
        active.every((c) =>
          String(c.get(row) ?? "")
            .toLowerCase()
            .includes(filters[c.key].trim().toLowerCase()),
        ),
      );
    }
    const col = sort !== null && !serverSort ? columns.find((c) => c.key === sort.key) : undefined;
    if (sort !== null && col !== undefined) {
      const mul = sort.dir === "asc" ? 1 : -1;
      const key = col.sortValue ?? col.get;
      // A `sortValue` returning a number sorts numerically even when the column
      // is not right-aligned — the rank columns are exactly that case.
      const asNumber = col.numeric || typeof key(out[0]) === "number";
      out = [...out].sort((a, b) => {
        if (asNumber) {
          const av = parseFloat(String(key(a) ?? ""));
          const bv = parseFloat(String(key(b) ?? ""));
          const an = Number.isNaN(av);
          const bn = Number.isNaN(bv);
          if (an && bn) return 0;
          if (an) return 1; // unparsable always last
          if (bn) return -1;
          return (av - bv) * mul;
        }
        return (
          String(key(a) ?? "")
            .toLowerCase()
            .localeCompare(String(key(b) ?? "").toLowerCase()) * mul
        );
      });
    }
    if (group) {
      // stable: keeps the (possibly sorted) order within each group
      out = [...out].sort((a, b) => group(a) - group(b));
    }
    return out;
  }, [rows, columns, filters, sort, group, serverSort]);

  // A filter or sort change is a different list — restart the chunking so the
  // reader is not left scrolled into rows that have moved.
  const resetKey = useMemo(
    () => JSON.stringify([filters, sort]),
    [filters, sort],
  );
  // Report the filtered rows, but ONLY when they actually changed.
  //
  // `visible` is a useMemo over `columns` and `group`, and callers build both
  // inline — so both have a new identity on every render, `visible` is a new
  // array on every render, and a naive effect here calls back on every render.
  // The caller stores that array in state, which re-renders it, which rebuilds
  // `columns`... React caught it as "Maximum update depth exceeded" on all
  // three review-queue tabs. Comparing the CONTENT breaks the cycle without
  // asking every caller to memoise its column definitions.
  const lastEmitted = useRef<T[] | null>(null);
  useEffect(() => {
    const prev = lastEmitted.current;
    const same =
      prev !== null && prev.length === visible.length && prev.every((r, i) => r === visible[i]);
    if (same) return;
    lastEmitted.current = visible;
    onVisibleChange?.(visible);
    // `onVisibleChange` is usually an inline arrow; depending on it would fire
    // this on every render of the parent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const { count, hasMore, more } = useVisibleCount(visible.length, pageSize, resetKey);
  const sentinel = useInfiniteScroll(more, hasMore, false);
  const shown = useMemo(() => visible.slice(0, count), [visible, count]);

  const cycleSort = (key: string) =>
    setSort((prev) => {
      const next =
        prev === null || prev.key !== key
          ? ({ key, dir: "asc" } as const)
          : prev.dir === "asc"
            ? ({ key, dir: "desc" } as const)
            : null;
      onSortChange?.(next);
      return next;
    });

  const setFilter = (key: string, value: string) =>
    setFilters((f) => {
      const next = { ...f, [key]: value };
      if (onServerFilters) {
        const server: Record<string, string> = {};
        for (const c of columns) if (c.serverFilter) server[c.key] = next[c.key] ?? "";
        onServerFilters(server);
      }
      return next;
    });

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
                  title={typeof c.label === "string" ? `Sort by ${c.label}` : "Sort"}
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
                    onClick={() => {
                      setFilters({});
                      onServerFilters?.({});
                    }}
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
                  onChange={(e) => setFilter(c.key, e.target.value)}
                  aria-label={typeof c.label === "string" ? `Filter ${c.label}` : `Filter ${c.key}`}
                />
              )}
            </td>
          ))}
        </tr>
      </thead>
      <tbody>
        {shown.map((row) => {
          const key = rowKey(row);
          const open = expand !== undefined && openKey === key;
          return (
            <Fragment key={key}>
              <tr
                className={
                  [
                    rowClass?.(row) ?? "",
                    expand || onRowClick ? "row-expandable" : "",
                    open ? "row-open" : "",
                  ]
                    .join(" ")
                    .trim() || undefined
                }
                onClick={
                  expand
                    ? () => setOpenKey(open ? null : key)
                    : onRowClick
                      ? () => onRowClick(row)
                      : undefined
                }
              >
                {columns.map((c) => {
                  const text = String(c.get(row) ?? "");
                  return (
                    <td
                      key={c.key}
                      className={
                        [c.numeric ? "num" : "", c.className ?? ""].join(" ").trim() || undefined
                      }
                      title={c.title ? c.title(row) : text || undefined}
                    >
                      {c.render ? c.render(row) : text}
                    </td>
                  );
                })}
              </tr>
              {open ? (
                <tr className="row-expansion">
                  {/* The clamp that keeps every other row one line tall has to
                      be lifted for this cell, or the panel is invisible. */}
                  <td colSpan={columns.length}>{expand(row)}</td>
                </tr>
              ) : null}
            </Fragment>
          );
        })}
        {visible.length === 0 ? (
          <tr>
            <td colSpan={columns.length} className="empty">
              {anyFilter ? "No rows match the filters." : (empty ?? "No rows.")}
            </td>
          </tr>
        ) : null}
        {hasMore ? (
          <tr className="row-sentinel">
            <td colSpan={columns.length}>
              {/* The observer watches this cell. It sits INSIDE the table so it
                  scrolls with the rows; a sentinel outside would be on screen
                  from the start on a short list and load everything at once. */}
              <div ref={sentinel} className="scroll-sentinel">
                <Spinner label={`${count} of ${visible.length}`} />
              </div>
            </td>
          </tr>
        ) : null}
        {footer ? (
          <tr className="row-sentinel">
            <td colSpan={columns.length}>{footer}</td>
          </tr>
        ) : null}
      </tbody>
    </table>
  );
}
