import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  bulkSignoff,
  errorMessage,
  getCategories,
  listComponents,
  type ComponentListItem,
} from "../api";
import CategoryTree from "../components/CategoryTree";
import DataTable, { type Column } from "../components/DataTable";
import { NarrowChip } from "../components/FoldSection";
import { useDialog } from "../components/Dialog";
import { useDebounced } from "../components/useDebounced";
import {
  ErrorBanner,
  LifecyclePill,
  REVIEW_RANK,
  ReviewPill,
  reviewWord,
  SIGNOFF_RANK,
  SignoffPill,
  signoffWord,
  Spinner,
} from "../components/Ui";
import { useStickyState } from "../useStickyState";
import { plural } from "../format";
import { useLoad } from "../components/useLoad";

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

export default function Browse() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const catParam = params.get("cat");
  const categoryId = catParam != null && catParam !== "" ? Number(catParam) : null;

  const [input, setInput] = useState(q);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [signing, setSigning] = useState(false);
  const dialog = useDialog();

  // Remember the selected library + search across navigation. A link from the top
  // bar has no parameters, so on the first mount with none we restore the last
  // Browse location; otherwise we save the current one.
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

  // Debounced search: commit the input to the URL after a short pause. Only a
  // settled input may write. `q` is not a dependency: on back/forward the URL
  // changes first, and the input then follows it, so nothing has to be written.
  const settledInput = useDebounced(input, DEBOUNCE_MS);
  useEffect(() => {
    if (settledInput === q) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (settledInput) next.set("q", settledInput);
        else next.delete("q");
        return next;
      },
      { replace: true },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settledInput]);

  const { data: tree, error: treeError, reload: reloadTree } = useLoad(getCategories, []);

  const { data, error, loading, reload } = useLoad(
    (signal) =>
      listComponents({ q: q || undefined, category_id: categoryId ?? undefined, page_size: PAGE_SIZE }, signal),
    [q, categoryId],
    { keep: true },
  );

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
  // The state chips. They count what the browser holds, so they stay away while
  // the server has more rows than one fetch returns: part of a list is not a count.
  const [narrow, setNarrow] = useState<"" | "failed" | "unsigned" | "stale" | "signed">("");
  const narrowOf = (c: ComponentListItem, n: typeof narrow) => (n === "failed" ? c.review === "failed" : c.signoff === n);
  const chipCount = (n: typeof narrow) => (data?.items ?? []).filter((c) => narrowOf(c, n)).length;
  const complete = !!data && data.items.length >= data.total;

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
      `Sign off ${plural(ids.length, "component")} for production? ` +
        "This records that YOU checked each one's symbol and land pattern.",
      { title: "Sign off for production", confirmLabel: "Sign off", tone: "ok" },
    );
    if (!ok) return;
    setSigning(true);
    try {
      const res = await bulkSignoff(ids);
      setSelected(new Set());
      void reload();
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
      label: "Mfg PN",
      width: 11,
      get: (c) => c.mfg_pn,
      render: (c) => (
        <Link
          to={`/library/components/${c.id}`}
          state={{ backTo: `/library/components${params.toString() ? `?${params.toString()}` : ""}` }}
          className="mono comp-link"
        >
          {c.mfg_pn || <span className="muted">—</span>}
        </Link>
      ),
    },
    { key: "manufacturer", label: "Manufacturer", width: 11, get: (c) => c.manufacturer },
    { key: "value", label: "Value", width: 6, className: "mono", get: (c) => c.value },
    { key: "description", label: "Description", width: 12, get: (c) => c.description },
    { key: "footprint", label: "Footprint", width: 12, className: "mono", get: (c) => c.footprint },
    { key: "lcsc", label: "LCSC", width: 7, className: "mono", get: (c) => c.lcsc },
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
      label: "Price @1k",
      width: 8,
      numeric: true,
      get: (c) => c.price_bulk,
      title: (c) => (c.bulk_qty ? `Unit price at qty ${c.bulk_qty}` : undefined),
    },
    { key: "category", label: "Category", width: 7, get: (c) => c.category_path },
    {
      key: "signoff",
      label: "Sign-off",
      // A pill is inline-block, so the column's ellipsis cannot shorten it —
      // too narrow simply cuts the word in half. 10% fits the longest label
      // ("not signed", measured at a 1400 px window); the review column below
      // is sized for the same reason.
      width: 10,
      className: "ctr",
      // Filter on the PRINTED word (typing "re-check" finds the stale rows);
      // sort on rank, worst first.
      get: (c) => signoffWord(c.signoff),
      sortValue: (c) => SIGNOFF_RANK[c.signoff] ?? 9,
      render: (c) => <SignoffPill state={c.signoff} />,
    },
    {
      key: "review",
      label: "Review",
      // Wider than sign-off: ReviewPill adds the actor glyph too
      // ("checked 🤖"), which is the state most rows are in.
      width: 10,
      className: "ctr",
      get: (c) => {
        const life =
          c.lifecycle === "deprecated" || c.lifecycle === "obsolete" ? ` ${c.lifecycle}` : "";
        return reviewWord(c.review) + life;
      },
      sortValue: (c) => REVIEW_RANK[c.review] ?? 9,
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
            onChanged={reloadTree}
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
                ? `${plural(total, "component")}`
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

        {complete ? (
          <div className="stat-row">
            <NarrowChip n={chipCount("failed")} tone="err" value="failed" current={narrow} onNarrow={setNarrow}>review failed</NarrowChip>
            <NarrowChip n={chipCount("unsigned")} tone="warn" value="unsigned" current={narrow} onNarrow={setNarrow}>not signed</NarrowChip>
            <NarrowChip n={chipCount("stale")} tone="warn" value="stale" current={narrow} onNarrow={setNarrow}>re-check</NarrowChip>
            <NarrowChip n={chipCount("signed")} tone="ok" value="signed" current={narrow} onNarrow={setNarrow}>signed</NarrowChip>
          </div>
        ) : null}

        {data === null && loading ? (
          <div className="block-loading">
            <Spinner label="Loading components" />
          </div>
        ) : data !== null ? (
          <div className={"card table-wrap" + (loading ? " is-loading" : "")}>
            <DataTable
              columns={cols}
              rows={narrow && complete ? data.items.filter((c) => narrowOf(c, narrow)) : data.items}
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
