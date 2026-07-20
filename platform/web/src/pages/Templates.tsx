import { useEffect, useState } from "react";
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
import { ErrorBanner, Spinner } from "../components/Ui";

const symbolColumns: Column<SymbolListItem>[] = [
  {
    key: "name",
    label: "Name",
    width: 52,
    get: (r) => r.name,
    className: "mono",
    render: (r) => (
      <Link to={`/templates/symbols/${r.id}`} className="comp-link">
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
    key: "name",
    label: "Name",
    width: 52,
    get: (r) => r.name,
    className: "mono",
    render: (r) => (
      <Link to={`/templates/footprints/${r.id}`} className="comp-link">
        {r.name}
      </Link>
    ),
  },
  { key: "pads", label: "Pads", width: 16, numeric: true, get: (r) => r.pad_count },
  { key: "version", label: "Version", width: 16, numeric: true, get: (r) => r.version_no },
  { key: "notes", label: "Notes", width: 16, numeric: true, get: (r) => r.comment_count },
];

export default function Templates() {
  const [tab, setTab] = useState<TemplateKind>("symbols");
  const [symbols, setSymbols] = useState<SymbolListItem[] | null>(null);
  const [footprints, setFootprints] = useState<FootprintListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setError(null);
    Promise.all([getSymbols(ctrl.signal), getFootprints(ctrl.signal)])
      .then(([s, f]) => {
        setSymbols(s);
        setFootprints(f);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, []);

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
      </div>
    </div>
  );
}
