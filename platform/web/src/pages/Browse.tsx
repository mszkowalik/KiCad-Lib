import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  errorMessage,
  getCategories,
  isAbortError,
  listComponents,
  type CategoryNode,
  type ComponentListItem,
  type ComponentListResponse,
} from "../api";
import CategoryTree from "../components/CategoryTree";
import { ErrorBanner, Spinner } from "../components/Ui";
import { useStickyState } from "../useStickyState";

const PAGE_SIZE = 1000;
const DEBOUNCE_MS = 300;

function ExternalLinkIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path
        d="M5 2.5H2.5v7h7V7M7 2h3v3M10 2 5.5 6.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      />
    </svg>
  );
}

// -------------------------------------------------- client-side sort/filter

type ColKey =
  | "mfg_pn"
  | "manufacturer"
  | "value"
  | "description"
  | "footprint"
  | "lcsc"
  | "price_bulk"
  | "category";

const COL_LABELS: Record<ColKey, string> = {
  mfg_pn: "Mfg PN",
  manufacturer: "Manufacturer",
  value: "Value",
  description: "Description",
  footprint: "Footprint",
  lcsc: "LCSC",
  price_bulk: "Price @1k",
  category: "Category",
};

function colValue(c: ComponentListItem, col: ColKey): string {
  return col === "category" ? c.category_path : c[col];
}

function sortRows(
  rows: ComponentListItem[],
  sort: { col: ColKey; dir: "asc" | "desc" },
): ComponentListItem[] {
  const mul = sort.dir === "asc" ? 1 : -1;
  const out = [...rows];
  if (sort.col === "price_bulk") {
    // numeric; empty/unparsable always last regardless of direction
    out.sort((a, b) => {
      const av = parseFloat(a.price_bulk);
      const bv = parseFloat(b.price_bulk);
      const an = Number.isNaN(av);
      const bn = Number.isNaN(bv);
      if (an && bn) return 0;
      if (an) return 1;
      if (bn) return -1;
      return (av - bv) * mul;
    });
  } else {
    const col = sort.col;
    out.sort(
      (a, b) => colValue(a, col).toLowerCase().localeCompare(colValue(b, col).toLowerCase()) * mul,
    );
  }
  return out;
}

export default function Browse() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const catParam = params.get("cat");
  const categoryId = catParam != null && catParam !== "" ? Number(catParam) : null;

  const [input, setInput] = useState(q);
  const [tree, setTree] = useState<CategoryNode[] | null>(null);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [data, setData] = useState<ComponentListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Remember the selected library + search across navigation. The "← back" link
  // from a component goes to a bare "/", so on the first mount with no params we
  // restore the last Browse location; otherwise we save the current one.
  const [lastSearch, setLastSearch] = useStickyState<string>("browse:lastSearch", "");
  const restored = useRef(false);
  useEffect(() => {
    if (!restored.current) {
      restored.current = true;
      if (!params.toString() && lastSearch) {
        setParams(new URLSearchParams(lastSearch), { replace: true });
        return;
      }
    }
    setLastSearch(params.toString());
    // one-shot restore on mount, then mirror the URL — deps intentionally [params].
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  // Keep the input in sync when q changes from the outside (back/forward nav).
  useEffect(() => {
    setInput(q);
  }, [q]);

  // Debounced search: commit the input to the URL after a short pause.
  useEffect(() => {
    if (input === q) return;
    const t = window.setTimeout(() => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (input) next.set("q", input);
          else next.delete("q");
          return next;
        },
        { replace: true },
      );
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [input, q, setParams]);

  const [treeRefresh, setTreeRefresh] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    getCategories(ctrl.signal)
      .then((t) => {
        setTree(t);
        setTreeError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setTreeError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [treeRefresh]);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    listComponents(
      {
        q: q || undefined,
        category_id: categoryId ?? undefined,
        page_size: PAGE_SIZE,
      },
      ctrl.signal,
    )
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(errorMessage(err));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [q, categoryId]);

  const selectCategory = (id: number | null) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (id == null) next.delete("cat");
      else next.set("cat", String(id));
      return next;
    });

  // Column sort + per-column filters — client-side, remembered across navigation.
  const [sort, setSort] = useStickyState<{ col: ColKey; dir: "asc" | "desc" } | null>(
    "browse:sort",
    null,
  );
  const [filters, setFilters] = useStickyState<Partial<Record<ColKey, string>>>("browse:filters", {});

  const anyFilter = Object.values(filters).some((v) => v !== undefined && v.trim() !== "");

  const visible = useMemo(() => {
    if (data === null) return [];
    let rows = data.items;
    const active = (Object.entries(filters) as Array<[ColKey, string]>).filter(
      ([, v]) => v.trim() !== "",
    );
    if (active.length > 0) {
      rows = rows.filter((c) =>
        active.every(([col, v]) =>
          colValue(c, col).toLowerCase().includes(v.trim().toLowerCase()),
        ),
      );
    }
    if (sort !== null) rows = sortRows(rows, sort);
    return rows;
  }, [data, filters, sort]);

  const cycleSort = (col: ColKey) =>
    setSort((prev) =>
      prev === null || prev.col !== col
        ? { col, dir: "asc" }
        : prev.dir === "asc"
          ? { col, dir: "desc" }
          : null,
    );

  const setFilter = (col: ColKey, v: string) => setFilters((f) => ({ ...f, [col]: v }));

  const sortTh = (col: ColKey, className?: string) => (
    <th className={className}>
      <button
        type="button"
        className="th-sort"
        onClick={() => cycleSort(col)}
        title={`Sort by ${COL_LABELS[col]}`}
      >
        {COL_LABELS[col]}
        {sort?.col === col ? (
          <span className="sort-ind">{sort.dir === "asc" ? "▲" : "▼"}</span>
        ) : null}
      </button>
    </th>
  );

  const filterTd = (col: ColKey) => (
    <td>
      <input
        type="text"
        className="text filter-input"
        placeholder="filter…"
        value={filters[col] ?? ""}
        onChange={(e) => setFilter(col, e.target.value)}
        aria-label={`Filter ${COL_LABELS[col]}`}
      />
    </td>
  );

  const total = data?.total ?? 0;

  return (
    <div className="browse">
      <aside className="sidebar">
        {treeError ? (
          <ErrorBanner message={`Categories failed to load: ${treeError}`} />
        ) : tree === null ? (
          <div className="sidebar-loading">
            <Spinner label="Loading categories" />
          </div>
        ) : (
          <CategoryTree
            tree={tree}
            selectedId={categoryId}
            onSelect={selectCategory}
            onChanged={() => setTreeRefresh((n) => n + 1)}
          />
        )}
      </aside>

      <main className="main">
        <div className="toolbar">
          <input
            type="search"
            className="text search"
            placeholder="Search name, value, part number…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            aria-label="Search components"
          />
          {loading && data !== null ? <Spinner /> : null}
          <span className="toolbar-total">
            {data !== null
              ? anyFilter
                ? `${visible.length} of ${total} components`
                : `${total} component${total === 1 ? "" : "s"}` +
                  (data.items.length < total ? ` (showing first ${data.items.length})` : "")
              : ""}
          </span>
          <Link to="/components/new" className="btn btn-sm new-comp-btn">
            New component
          </Link>
        </div>

        {error ? <ErrorBanner message={`Components failed to load: ${error}`} /> : null}

        {data === null && loading ? (
          <div className="block-loading">
            <Spinner label="Loading components" />
          </div>
        ) : data !== null ? (
          <div className={"card table-wrap" + (loading ? " is-loading" : "")}>
            <table className="data browse-table">
              <thead>
                <tr>
                  {sortTh("mfg_pn")}
                  {sortTh("manufacturer")}
                  {sortTh("value")}
                  {sortTh("description")}
                  {sortTh("footprint")}
                  {sortTh("lcsc")}
                  <th className="ctr" aria-label="Datasheet">
                    DS
                  </th>
                  {sortTh("price_bulk", "num")}
                  {sortTh("category")}
                </tr>
                <tr className="filter-row">
                  {filterTd("mfg_pn")}
                  {filterTd("manufacturer")}
                  {filterTd("value")}
                  {filterTd("description")}
                  {filterTd("footprint")}
                  {filterTd("lcsc")}
                  <td className="ctr">
                    {anyFilter ? (
                      <button
                        type="button"
                        className="row-del clear-filters"
                        onClick={() => setFilters({})}
                        title="Clear filters"
                        aria-label="Clear filters"
                      >
                        &#x2715;
                      </button>
                    ) : null}
                  </td>
                  {filterTd("price_bulk")}
                  {filterTd("category")}
                </tr>
              </thead>
              <tbody>
                {visible.map((c) => (
                  <tr key={c.id}>
                    <td title={c.mfg_pn}>
                      <Link to={`/components/${c.id}`} className="mono comp-link">
                        {c.mfg_pn || <span className="muted">—</span>}
                      </Link>
                    </td>
                    <td title={c.manufacturer}>{c.manufacturer}</td>
                    <td className="mono" title={c.value}>
                      {c.value}
                    </td>
                    <td title={c.description}>{c.description}</td>
                    <td className="mono" title={c.footprint}>
                      {c.footprint}
                    </td>
                    <td className="mono" title={c.lcsc}>
                      {c.lcsc}
                    </td>
                    <td className="ctr">
                      {c.datasheet ? (
                        <a
                          href={c.datasheet}
                          target="_blank"
                          rel="noreferrer"
                          className="ds-link"
                          title={c.datasheet}
                          aria-label={`Datasheet for ${c.name}`}
                        >
                          <ExternalLinkIcon />
                        </a>
                      ) : null}
                    </td>
                    <td
                      className="num"
                      title={c.bulk_qty ? `Unit price at qty ${c.bulk_qty}` : undefined}
                    >
                      {c.price_bulk}
                    </td>
                    <td title={c.category_path}>{c.category_path}</td>
                  </tr>
                ))}
                {visible.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="empty">
                      No components match.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        ) : null}
      </main>
    </div>
  );
}
