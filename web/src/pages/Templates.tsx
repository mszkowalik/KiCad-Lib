import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  errorMessage,
  getFootprints,
  getSimModels,
  getSymbols,
  listModels3d,
  proposeNewSimModel,
  type FootprintListItem,
  type SimModelListItem,
  type SymbolListItem,
  type TemplateKind,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import GeometryPaste from "../components/GeometryPaste";
import Models3dPanel from "../components/Models3dPanel";
import TabStrip from "../components/TabStrip";
import TemplateThumb from "../components/TemplateThumb";
import { ErrorBanner, Spinner } from "../components/Ui";
import { useLoad } from "../components/useLoad";
import PageShell from "../components/PageShell";

type Tab = TemplateKind | "sim" | "models";

/** The columns of a drawing list. A symbol and a footprint differ in one count. */
function drawingColumns<T extends SymbolListItem | FootprintListItem>(
  kind: TemplateKind,
  countLabel: string,
  count: (r: T) => number | null,
): Column<T>[] {
  return [
    {
      key: "thumb",
      label: "",
      width: 10,
      interactive: false,
      get: () => "",
      render: (r) => <TemplateThumb kind={kind} id={r.id} name={r.name} versionId={r.version_id} />,
    },
    {
      key: "name",
      label: "Name",
      width: 42,
      get: (r) => r.name,
      className: "mono",
      render: (r) => (
        <Link to={`/library/templates/${kind}/${r.id}`} className="comp-link">
          {r.name}
        </Link>
      ),
    },
    { key: "count", label: countLabel, width: 16, numeric: true, get: count },
    { key: "version", label: "Version", width: 16, numeric: true, get: (r) => r.version_no },
    { key: "notes", label: "Notes", width: 16, numeric: true, get: (r) => r.comment_count },
  ];
}

const symbolColumns = drawingColumns<SymbolListItem>("symbols", "Pins", (r) => r.pin_count);
const footprintColumns = drawingColumns<FootprintListItem>("footprints", "Pads", (r) => r.pad_count);

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
          maxLength={600}
          onChange={(e) => setComment(e.target.value)}
          aria-label="Version comment"
        />
        <button
          type="button"
          className="btn btn-primary"
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
  const tab: Tab =
    tabParam === "footprints" || tabParam === "sim" || tabParam === "models" ? tabParam : "symbols";
  const setTab = (t: Tab) =>
    setSearchParams(t === "symbols" ? {} : { tab: t }, { replace: true });
  const { data: lists, error, reload: load } = useLoad(
    (signal) => Promise.all([getSymbols(signal), getFootprints(signal), getSimModels(signal)]),
    [],
  );
  const symbols = lists?.[0] ?? null;
  const footprints = lists?.[1] ?? null;
  const simModels = lists?.[2] ?? null;

  // Only the count. The list is the tab's own, and a failure here must not take
  // the other three tabs down, so a missing count just prints no number.
  const { data: modelCount, reload: loadModelCount } = useLoad(
    (signal) => listModels3d("", 1, signal).then((r) => r.total_matching),
    [],
  );

  const loading = symbols === null || footprints === null || simModels === null;

  return (
    <PageShell>
      <div className="toolbar">
        <h1>Templates</h1>
        <span className="toolbar-total">
          {symbols && footprints && simModels
            ? `${symbols.length} symbols · ${footprints.length} footprints · ${simModels.length} sim models` +
              (modelCount !== null ? ` · ${modelCount} 3D models` : "")
            : ""}
        </span>
      </div>
      <p className="muted">
        Base symbols, footprints and simulation models — the shared templates that
        components are built from. Open one to see its preview or source and notes.
        The 3D models tab holds the files that footprints name.
      </p>

      <TabStrip<Tab>
        label="Template type"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "symbols", label: `Symbols${symbols ? ` (${symbols.length})` : ""}` },
          { id: "footprints", label: `Footprints${footprints ? ` (${footprints.length})` : ""}` },
          { id: "sim", label: `Sim models${simModels ? ` (${simModels.length})` : ""}` },
          { id: "models", label: `3D models${modelCount !== null ? ` (${modelCount})` : ""}` },
        ]}
      />

      {error && tab !== "models" ? <ErrorBanner message={error} /> : null}
      {loading && !error && tab !== "models" ? <Spinner label="Loading templates" /> : null}
      {tab === "models" ? <Models3dPanel onChanged={() => loadModelCount()} /> : null}

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

      {!loading && (tab === "symbols" || tab === "footprints") ? (
        <details className="card pad" key={tab}>
          <summary>New {tab === "symbols" ? "symbol" : "footprint"} from the clipboard</summary>
          {/* A paste publishes at once, so the list is stale the moment it succeeds. */}
          <GeometryPaste kind={tab} onFiled={() => void load()} />
        </details>
      ) : null}
      {!loading && tab === "sim" ? (
        <details className="card pad" key="sim-new">
          <summary>New sim model from the clipboard</summary>
          <SimModelPaste onFiled={() => void load()} />
        </details>
      ) : null}
    </PageShell>
  );
}
