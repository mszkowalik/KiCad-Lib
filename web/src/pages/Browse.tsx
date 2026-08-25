import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  bulkSignoff,
  errorMessage,
  getCategories,
  isAbortError,
  listComponents,
  type CategoryNode,
  type ComponentListItem,
  type ComponentListResponse,
} from "../api";
import CategoryTree from "../components/CategoryTree";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import { ErrorBanner, LifecyclePill, ReviewPill, SignoffPill, Spinner } from "../components/Ui";
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
  | "category"
  | "signoff"
  | "review";

const COL_LABELS: Record<ColKey, string> = {
  mfg_pn: "Mfg PN",
  manufacturer: "Manufacturer",
  value: "Value",
  description: "Description",
  footprint: "Footprint",
  lcsc: "LCSC",
  price_bulk: "Price @1k",
  category: "Category",
  signoff: "Sign-off",
  review: "Review",
};

/** The label the sign-off column PRINTS. The filter box matches what the user
 *  can see, so typing "re-check" finds the stale rows. */
const SIGNOFF_TEXT: Record<string, string> = {
  signed: "signed",
  stale: "re-check",
  revoked: "revoked",
  unsigned: "not signed",
};

/** Printed labels for the review column — filter matches what the user sees,
 *  including the lifecycle words shown alongside for deprecated/obsolete. */
const REVIEW_TEXT: Record<string, string> = {
  checked: "checked",
  partial: "partial",
  failed: "checks fail",
  unreviewed: "unreviewed",
};

/** Sign-off states worst-first: what needs attention sorts to the top. */
const SIGNOFF_ORDER: Record<string, number> = {
  revoked: 0,
  stale: 1,
  unsigned: 2,
  signed: 3,
};

const REVIEW_ORDER: Record<string, number> = {
  failed: 0,
  unreviewed: 1,
  partial: 2,
  checked: 3,
};

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
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [signing, setSigning] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const dialog = useDialog();

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
  }, [q, categoryId, refresh]);

  const selectCategory = (id: number | null) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (id == null) next.delete("cat");
      else next.set("cat", String(id));
      return next;
    });

  // Sorting, filtering and chunked rendering all live in DataTable now — the
  // same behaviour every other list in the platform gets, from one place.
  // `visible` comes back from it so "select all" still means the FILTERED set.
  const [visible, setVisible] = useState<ComponentListItem[]>([]);
  const total = data?.total ?? 0;

  // ---- bulk production sign-off -------------------------------------------
  // Signing a BOM's worth of parts one page at a time is the whole reason this
  // exists, so the selection follows the FILTERED rows: filter to "not signed"
  // (or to a footprint, a category, a search) and Select all means that set.
  const selectable = visible.filter((c) => c.signoff !== "signed");
  const allSelected = selectable.length > 0 && selectable.every((c) => selected.has(c.id));

  const toggleAll = () =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) selectable.forEach((c) => next.delete(c.id));
      else selectable.forEach((c) => next.add(c.id));
      return next;
    });

  const toggleOne = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const signSelected = async () => {
    const ids = [...selected];
    if (ids.length === 0) return;
    const ok = await dialog.confirm(
      `Sign off ${ids.length} component${ids.length === 1 ? "" : "s"} for production? ` +
        "This records that YOU checked each one's symbol and land pattern.",
      { title: "Sign off for production", confirmLabel: "Sign off", tone: "ok" },
    );
    if (!ok) return;
    setSigning(true);
    try {
      const res = await bulkSignoff(ids);
      setSelected(new Set());
      setRefresh((n) => n + 1);
      if (res.skipped.length > 0) {
        await dialog.alert(
          `Signed ${res.total}. Skipped ${res.skipped.length}: ` +
            res.skipped.map((s) => `${s.component ?? s.component_id} (${s.reason})`).join(", "),
          { title: "Bulk sign-off" },
        );
      }
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Bulk sign-off failed" });
    } finally {
      setSigning(false);
    }
  };

  const cols: Column<ComponentListItem>[] = [
    {
      key: "select",
      label: (
        <input
          type="checkbox"
          checked={allSelected}
          disabled={signing || selectable.length === 0}
          onChange={toggleAll}
          aria-label="Select every unsigned component shown"
        />
      ),
      width: 3,
      interactive: false,
      className: "ctr",
      get: () => "",
      render: (c) => (
        <input
          type="checkbox"
          checked={selected.has(c.id)}
          disabled={signing || c.signoff === "signed"}
          onChange={() => toggleOne(c.id)}
          aria-label={`Select ${c.name} for sign-off`}
          title={c.signoff === "signed" ? "already signed off" : `Select ${c.name} for sign-off`}
        />
      ),
    },
    {
      key: "mfg_pn",
      label: COL_LABELS.mfg_pn,
      width: 12,
      get: (c) => c.mfg_pn,
      render: (c) => (
        <Link
          to={`/library/components/${c.id}`}
          state={{ backTo: `/${params.toString() ? `?${params.toString()}` : ""}` }}
          className="mono comp-link"
        >
          {c.mfg_pn || <span className="muted">—</span>}
        </Link>
      ),
    },
    { key: "manufacturer", label: COL_LABELS.manufacturer, width: 10, get: (c) => c.manufacturer },
    { key: "value", label: COL_LABELS.value, width: 8, className: "mono", get: (c) => c.value },
    { key: "description", label: COL_LABELS.description, width: 20, get: (c) => c.description },
    { key: "footprint", label: COL_LABELS.footprint, width: 12, className: "mono", get: (c) => c.footprint },
    { key: "lcsc", label: COL_LABELS.lcsc, width: 7, className: "mono", get: (c) => c.lcsc },
    {
      key: "datasheet",
      label: "DS",
      width: 3,
      interactive: false,
      className: "ctr",
      get: () => "",
      render: (c) =>
        c.datasheet ? (
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
        ) : null,
    },
    {
      key: "price_bulk",
      label: COL_LABELS.price_bulk,
      width: 7,
      numeric: true,
      get: (c) => c.price_bulk,
      title: (c) => (c.bulk_qty ? `Unit price at qty ${c.bulk_qty}` : undefined),
    },
    { key: "category", label: COL_LABELS.category, width: 10, get: (c) => c.category_path },
    {
      key: "signoff",
      label: COL_LABELS.signoff,
      width: 4,
      className: "ctr",
      // Filter on the PRINTED word (typing "re-check" finds the stale rows);
      // sort on rank, worst first.
      get: (c) => SIGNOFF_TEXT[c.signoff] ?? c.signoff,
      sortValue: (c) => SIGNOFF_ORDER[c.signoff] ?? 9,
      render: (c) => <SignoffPill state={c.signoff} />,
    },
    {
      key: "review",
      label: COL_LABELS.review,
      width: 4,
      className: "ctr",
      get: (c) => {
        const life =
          c.lifecycle === "deprecated" || c.lifecycle === "obsolete" ? ` ${c.lifecycle}` : "";
        return (REVIEW_TEXT[c.review] ?? c.review) + life;
      },
      sortValue: (c) => REVIEW_ORDER[c.review] ?? 9,
      render: (c) => (
        <>
          <ReviewPill state={c.review} provenance={c.review_provenance} />
          {c.lifecycle === "deprecated" || c.lifecycle === "obsolete" ? (
            <LifecyclePill state={c.lifecycle} title="Hidden from KiCad" />
          ) : null}
        </>
      ),
    },
  ];

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
            {data === null
              ? ""
              : visible.length === total
                ? `${total} component${total === 1 ? "" : "s"}`
                : `${visible.length} of ${total} components`}
          </span>
          <button
            type="button"
            className="btn btn-sm btn-ok"
            disabled={selected.size === 0 || signing}
            onClick={() => void signSelected()}
          >
            {signing ? "Signing off…" : `Sign off selected (${selected.size})`}
          </button>
          {selected.size > 0 && !signing ? (
            <button type="button" className="btn btn-sm" onClick={() => setSelected(new Set())}>
              Clear selection
            </button>
          ) : null}
          <Link to="/library/components/new" className="btn btn-sm new-comp-btn">
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
            <DataTable
              columns={cols}
              rows={data.items}
              rowKey={(c) => c.id}
              persistKey="browse"
              onVisibleChange={setVisible}
              empty="No components match."
            />
          </div>
        ) : null}
      </main>
    </div>
  );
}
