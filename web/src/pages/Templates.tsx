import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getFootprints,
  getSymbols,
  isAbortError,
  type FootprintListItem,
  type SymbolListItem,
  type TemplateKind,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import GeometryPaste from "../components/GeometryPaste";
import TemplateThumb from "../components/TemplateThumb";
import { ErrorBanner, Spinner } from "../components/Ui";

const symbolColumns: Column<SymbolListItem>[] = [
  {
    key: "thumb",
    label: "",
    width: 10,
    interactive: false,
    get: () => "",
    render: (r) => <TemplateThumb kind="symbols" id={r.id} name={r.name} versionId={r.version_id} />,
  },
  {
    key: "name",
    label: "Name",
    width: 42,
    get: (r) => r.name,
    className: "mono",
    render: (r) => (
      <Link to={`/library/templates/symbols/${r.id}`} className="comp-link">
        {r.name}
      </Link>
    ),
  },
  { key: "pins", label: "Pins", width: 16, numeric: true, get: (r) => r.pin_count },
  { key: "version", label: "Version", width: 16, numeric: true, get: (r) => r.version_no },
  { key: "notes", label: "Notes", width: 16, numeric: true, get: (r) => r.comment_count },
];

const footprintColumns: Column<FootprintListItem>[] = [
  {
    key: "thumb",
    label: "",
    width: 10,
    interactive: false,
    get: () => "",
    render: (r) => <TemplateThumb kind="footprints" id={r.id} name={r.name} versionId={r.version_id} />,
  },
  {
    key: "name",
    label: "Name",
    width: 42,
    get: (r) => r.name,
    className: "mono",
    render: (r) => (
      <Link to={`/library/templates/footprints/${r.id}`} className="comp-link">
        {r.name}
      </Link>
    ),
  },
  { key: "pads", label: "Pads", width: 16, numeric: true, get: (r) => r.pad_count },
  { key: "version", label: "Version", width: 16, numeric: true, get: (r) => r.version_no },
  { key: "notes", label: "Notes", width: 16, numeric: true, get: (r) => r.comment_count },
];

export default function Templates() {
  // The active tab lives in the URL (?tab=footprints) — linkable, and it no
  // longer resets on every visit.
  const [searchParams, setSearchParams] = useSearchParams();
  const tab: TemplateKind = searchParams.get("tab") === "footprints" ? "footprints" : "symbols";
  const setTab = (t: TemplateKind) =>
    setSearchParams(t === "symbols" ? {} : { tab: t }, { replace: true });
  const [symbols, setSymbols] = useState<SymbolListItem[] | null>(null);
  const [footprints, setFootprints] = useState<FootprintListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    setError(null);
    return Promise.all([getSymbols(signal), getFootprints(signal)])
      .then(([s, f]) => {
        setSymbols(s);
        setFootprints(f);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  /** A filed creation makes the parent row immediately (its version stays a
   *  draft), so the list is stale the moment the paste box succeeds. */
  const reload = () => load();

  const loading = symbols === null || footprints === null;

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Templates</h1>
          <span className="toolbar-total">
            {symbols && footprints
              ? `${symbols.length} symbols · ${footprints.length} footprints`
              : ""}
          </span>
        </div>
        <p className="muted">
          Base symbols and footprints in the library — the graphical templates that
          components are built from. Open one to see its KiCad preview, source and notes.
        </p>

        <div className="seg proj-tabs" role="tablist" aria-label="Template type">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "symbols"}
            className={tab === "symbols" ? "on" : ""}
            onClick={() => setTab("symbols")}
          >
            Symbols{symbols ? ` (${symbols.length})` : ""}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "footprints"}
            className={tab === "footprints" ? "on" : ""}
            onClick={() => setTab("footprints")}
          >
            Footprints{footprints ? ` (${footprints.length})` : ""}
          </button>
        </div>

        {error ? <ErrorBanner message={error} /> : null}
        {loading && !error ? <Spinner label="Loading templates" /> : null}

        {!loading && tab === "symbols" ? (
          <div className="card table-wrap">
            <DataTable<SymbolListItem>
              rows={symbols ?? []}
              rowKey={(r) => r.id}
              empty="No symbols."
              columns={symbolColumns}
            />
          </div>
        ) : null}
        {!loading && tab === "footprints" ? (
          <div className="card table-wrap">
            <DataTable<FootprintListItem>
              rows={footprints ?? []}
              rowKey={(r) => r.id}
              empty="No footprints."
              columns={footprintColumns}
            />
          </div>
        ) : null}

        {!loading ? (
          <details className="card pad" key={tab}>
            <summary>New {tab === "symbols" ? "symbol" : "footprint"} from the clipboard</summary>
            <GeometryPaste kind={tab} onFiled={() => void reload()} />
          </details>
        ) : null}
      </div>
    </div>
  );
}
