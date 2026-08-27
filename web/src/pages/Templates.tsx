import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getFootprints,
  getSimModels,
  getSymbols,
  isAbortError,
  proposeNewSimModel,
  type FootprintListItem,
  type SimModelListItem,
  type SymbolListItem,
  type TemplateKind,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import GeometryPaste from "../components/GeometryPaste";
import TemplateThumb from "../components/TemplateThumb";
import { ErrorBanner, Spinner } from "../components/Ui";

type Tab = TemplateKind | "sim";

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

const simColumns: Column<SimModelListItem>[] = [
  {
    key: "name",
    label: "Name",
    width: 26,
    get: (r) => r.name,
    className: "mono",
    render: (r) => (
      <Link to={`/library/templates/sim/${r.id}`} className="comp-link">
        {r.name}
      </Link>
    ),
  },
  { key: "kind", label: "Kind", width: 12, get: (r) => r.kind },
  {
    key: "ports",
    label: "Ports",
    width: 34,
    get: (r) => r.ports.join(" "),
    className: "mono cell-desc",
  },
  {
    key: "params",
    label: "Params",
    width: 10,
    numeric: true,
    get: (r) => Object.keys(r.params).length,
  },
  { key: "links", label: "Symbols", width: 10, numeric: true, get: (r) => r.linked_symbols },
  { key: "version", label: "Version", width: 8, numeric: true, get: (r) => r.version_no },
];

/** Paste box for a brand-new sim model. Unlike GeometryPaste there is no
 *  preview to render — the server's parse of ports and params is the echo —
 *  and the name comes out of the `.subckt` line, so there is no name field. */
function SimModelPaste({ onFiled }: { onFiled: () => void }) {
  const [text, setText] = useState("");
  const [comment, setComment] = useState("");
  const [kind, setKind] = useState<"part" | "primitive">("part");
  const [filing, setFiling] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const file = async () => {
    if (filing) return;
    setFiling(true);
    setNotice(null);
    try {
      const res = await proposeNewSimModel(text, comment, kind);
      setNotice(`Published ${res.model} v${res.version_no} — ports: ${res.ports.join(" ")}`);
      setText("");
      setComment("");
      onFiled();
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setFiling(false);
    }
  };

  return (
    <div>
      <p className="muted">
        Publishes immediately. The model's name is the <span className="mono">.subckt</span>{" "}
        name — it must start with <span className="mono">sigma_</span>, and symbols reference
        it by that name. Follow the conventions-simulation skill for parameters.
      </p>
      <textarea
        className="text skill-textarea sim-src mono"
        rows={10}
        value={text}
        spellCheck={false}
        placeholder={".subckt sigma_example in out vcc gnd params: GAIN=100k\n…\n.ends"}
        onChange={(e) => setText(e.target.value)}
        aria-label="Subcircuit source"
      />
      <div className="btn-row">
        <select
          className="row-input sim-kind-pick"
          value={kind}
          aria-label="Model kind"
          onChange={(e) => setKind(e.target.value as "part" | "primitive")}
        >
          <option value="part">part — symbols link to it</option>
          <option value="primitive">primitive — a building block</option>
        </select>
        <input
          className="text"
          placeholder="Where the numbers come from"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          aria-label="Version comment"
        />
        <button
          type="button"
          className="btn btn-accent"
          disabled={filing || !text.trim() || !comment.trim()}
          onClick={() => void file()}
        >
          {filing ? "Publishing…" : "Publish model"}
        </button>
      </div>
      {notice ? <p className="muted">{notice}</p> : null}
    </div>
  );
}

export default function Templates() {
  // The active tab lives in the URL (?tab=footprints) — linkable, and it no
  // longer resets on every visit.
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tab: Tab = tabParam === "footprints" || tabParam === "sim" ? tabParam : "symbols";
  const setTab = (t: Tab) =>
    setSearchParams(t === "symbols" ? {} : { tab: t }, { replace: true });
  const [symbols, setSymbols] = useState<SymbolListItem[] | null>(null);
  const [footprints, setFootprints] = useState<FootprintListItem[] | null>(null);
  const [simModels, setSimModels] = useState<SimModelListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    setError(null);
    return Promise.all([getSymbols(signal), getFootprints(signal), getSimModels(signal)])
      .then(([s, f, m]) => {
        setSymbols(s);
        setFootprints(f);
        setSimModels(m);
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

  const loading = symbols === null || footprints === null || simModels === null;

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Templates</h1>
          <span className="toolbar-total">
            {symbols && footprints && simModels
              ? `${symbols.length} symbols · ${footprints.length} footprints · ${simModels.length} sim models`
              : ""}
          </span>
        </div>
        <p className="muted">
          Base symbols, footprints and simulation models — the shared templates that
          components are built from. Open one to see its preview or source and notes.
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
          <button
            type="button"
            role="tab"
            aria-selected={tab === "sim"}
            className={tab === "sim" ? "on" : ""}
            onClick={() => setTab("sim")}
          >
            Sim models{simModels ? ` (${simModels.length})` : ""}
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
        {!loading && tab === "sim" ? (
          <div className="card table-wrap">
            <DataTable<SimModelListItem>
              rows={simModels ?? []}
              rowKey={(r) => r.id}
              empty="No sim models."
              columns={simColumns}
            />
          </div>
        ) : null}

        {!loading && tab !== "sim" ? (
          <details className="card pad" key={tab}>
            <summary>New {tab === "symbols" ? "symbol" : "footprint"} from the clipboard</summary>
            <GeometryPaste kind={tab} onFiled={() => void reload()} />
          </details>
        ) : null}
        {!loading && tab === "sim" ? (
          <details className="card pad" key="sim-new">
            <summary>New sim model from the clipboard</summary>
            <SimModelPaste onFiled={() => void reload()} />
          </details>
        ) : null}
      </div>
    </div>
  );
}
