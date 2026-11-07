/** Library → Datasheets: the archive. Search reads every archived page, which is
 *  how a person finds "which page do I read" without opening 500 PDFs. Archive
 *  says what is stored. Jobs are the archive-wide runs, and the API refuses them
 *  to a non-admin (decision 0045), so a non-admin reads the status and has no
 *  button. Every job with a dry run shows its list first.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  API_URL,
  classifyDatasheets,
  collapseRestamps,
  errorMessage,
  getBrokenDatasheets,
  getClassifyStatus,
  getDatasheetOutline,
  getDatasheetPage,
  getDatasheetStorage,
  getIndexStatus,
  getRestamps,
  indexDatasheets,
  purgeBrokenDatasheets,
  reclaimDatasheetStorage,
  searchDatasheets,
  stopIndexDatasheets,
  type DatasheetHit,
} from "../api";
import { useAuth } from "../auth";
import DatasheetArchiveCard from "../components/DatasheetArchiveCard";
import DataTable from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import Field, { CheckField } from "../components/Field";
import { StatChip } from "../components/FoldSection";
import TabStrip from "../components/TabStrip";
import { ErrorBanner, Spinner } from "../components/Ui";
import { useLoad } from "../components/useLoad";
import PageShell from "../components/PageShell";

const TABS = [
  { id: "search", label: "Search" },
  { id: "archive", label: "Archive" },
  { id: "jobs", label: "Jobs" },
] as const;
type Tab = (typeof TABS)[number]["id"];

/** The server marks the words it found with `<b>`, and nothing else is trusted:
 *  the text comes out of a vendor's PDF, so it is never set as HTML. */
function Snippet({ text }: { text: string }) {
  const parts = text.split(/<\/?b>/);
  return <>{parts.map((p, i) => (i % 2 ? <b key={i}>{p}</b> : <span key={i}>{p}</span>))}</>;
}

/** One found page as extracted text, with the document's section map beside it. */
function PageView({ hit }: { hit: DatasheetHit }) {
  const id = Number(/\/datasheets\/(\d+)\//.exec(hit.uri)?.[1]);
  const [page, setPage] = useState(hit.page);
  const { data: outline } = useLoad((signal) => getDatasheetOutline(id, signal).catch(() => null), [id], { keep: true });
  const { data: text, error } = useLoad((signal) => getDatasheetPage(id, page, signal), [id, page]);
  return (
    <div className="stack">
      {outline?.sections.length ? (
        <Field label="Section">
          <select className="row-input" value={page} onChange={(e) => setPage(Number(e.target.value))}>
            {!outline.sections.some((s) => s.page === page) ? <option value={page}>page {page}</option> : null}
            {outline.sections.map((s) => <option key={`${s.page}:${s.section}`} value={s.page}>{s.page} · {s.section}</option>)}
          </select>
        </Field>
      ) : null}
      {error ? <ErrorBanner message={error} /> : null}
      {text ? <pre className="source-pre">{text.content}</pre> : error ? null : <Spinner />}
      <p className="muted dim">
        Extracted text, a finding aid only. <a href={`${API_URL}/api/datasheets/${id}/file#page=${page}`} target="_blank" rel="noreferrer">Open the PDF at page {page}</a> before you trust a value.
      </p>
    </div>
  );
}

function SearchTab() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [typed, setTyped] = useState(q);
  const [old, setOld] = useState(false);
  const { data: hits, loading: busy, error } = useLoad(
    (signal) => searchDatasheets(q, { limit: 50, includeSuperseded: old }, signal).then((r) => r.hits),
    [q, old],
    { enabled: !!q, keep: true },
  );

  const go = () => {
    const next = new URLSearchParams(params);
    if (typed.trim()) next.set("q", typed.trim()); else next.delete("q");
    setParams(next, { replace: true });
  };

  return (
    <div className="card pad">
      <div className="toolbar">
        <input className="search" value={typed} placeholder="Search every archived datasheet page…"
          autoFocus onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") go(); }} />
        <button type="button" className="btn btn-primary" onClick={go}>Search</button>
        <CheckField checked={old} onChange={setOld}>Also older versions</CheckField>
        {hits ? <span className="toolbar-total">{hits.length} page(s)</span> : null}
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      {busy ? <Spinner label="Searching" /> : null}
      {hits ? (
        <DataTable
          rows={hits}
          rowKey={(h) => `${h.component}:${h.datasheet}:${h.page}`}
          empty="No archived page holds these words."
          columns={[
            { key: "component", label: "Component", width: 18, className: "mono", get: (h) => h.component,
              render: (h) => <Link to={`/library/components?q=${encodeURIComponent(h.component)}`} onClick={(e) => e.stopPropagation()}>{h.component}</Link> },
            { key: "datasheet", label: "Document", width: 14, get: (h) => h.datasheet },
            { key: "page", label: "Page", width: 8, numeric: true, get: (h) => h.page,
              render: (h) => <a href={`${API_URL}${h.uri}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{h.page} / {h.page_count}</a> },
            { key: "section", label: "Section", width: 26, get: (h) => h.section || "—" },
            { key: "snippet", label: "Text", width: 34, get: (h) => h.snippet.replace(/<\/?b>/g, ""),
              render: (h) => <Snippet text={h.snippet} /> },
          ]}
          expand={(h) => <PageView hit={h} />}
        />
      ) : <p className="muted">Type a part number, a parameter or a phrase. The extracted text is a finding aid: read the page itself before you trust a value.</p>}
    </div>
  );
}

function JobsTab() {
  const { isAdmin } = useAuth();
  const dialog = useDialog();
  type Status = Awaited<ReturnType<typeof getIndexStatus>>;
  const [index, setIndex] = useState<Status | null>(null);
  const [classify, setClassify] = useState<Awaited<ReturnType<typeof getClassifyStatus>> | null>(null);
  const [broken, setBroken] = useState<Awaited<ReturnType<typeof getBrokenDatasheets>> | null>(null);
  const [restamps, setRestamps] = useState<Awaited<ReturnType<typeof getRestamps>> | null>(null);
  const [storage, setStorage] = useState<Awaited<ReturnType<typeof getDatasheetStorage>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getIndexStatus().then(setIndex).catch((err) => setError(errorMessage(err)));
    getClassifyStatus().then(setClassify).catch((err) => setError(errorMessage(err)));
    getBrokenDatasheets().then(setBroken).catch((err) => setError(errorMessage(err)));
    getRestamps().then(setRestamps).catch((err) => setError(errorMessage(err)));
    getDatasheetStorage().then(setStorage).catch((err) => setError(errorMessage(err)));
  }, []);
  useEffect(load, [load]);
  // A job runs in the background: keep reading while one does.
  const running = !!index?.running || !!classify?.running || !!storage?.reclaim.running;
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(load, 2000);
    return () => window.clearInterval(t);
  }, [running, load]);

  const run = async (what: () => Promise<unknown>) => {
    try { await what(); setError(null); } catch (err) { setError(errorMessage(err)); }
    load();
  };
  const ask = async (text: string, title: string, what: () => Promise<unknown>) => {
    if (await dialog.confirm(text, { title, confirmLabel: title, tone: "danger" })) await run(what);
  };

  return (
    <>
      {error ? <ErrorBanner message={error} /> : null}
      <div className="card pad">
        <h2 className="card-title">Page text index</h2>
        <p className="muted dim">What Search reads. A startup sweep picks up what was never indexed.</p>
        {index ? (
          <div className="stat-row">
            <StatChip n={`${index.documents_indexed} / ${index.documents_total}`}>documents</StatChip>
            <StatChip n={index.pages_total.toLocaleString()}>pages</StatChip>
            {Object.entries(index.page_kinds).map(([k, n]) => <StatChip key={k} n={n.toLocaleString()} tone={k === "failed" ? "warn" : undefined}>{k}</StatChip>)}
            {index.running ? <span className="muted">running: {index.done} / {index.total}</span> : null}
            {index.last_error ? <span className="err-text">{index.last_error}</span> : null}
          </div>
        ) : <Spinner />}
        {isAdmin ? (
          <div className="btn-row">
            <button type="button" className="btn btn-sm" disabled={index?.running} onClick={() => void run(() => indexDatasheets("missing"))}>Index what is missing</button>
            <button type="button" className="btn btn-sm" disabled={index?.running} onClick={() => void run(() => indexDatasheets("current"))}>Index current versions</button>
            <button type="button" className="btn btn-sm" disabled={index?.running} onClick={() => void run(() => indexDatasheets("all"))}>Index everything again</button>
            <button type="button" className="btn btn-sm" disabled={!index?.running} onClick={() => void run(stopIndexDatasheets)}>Stop</button>
          </div>
        ) : null}
      </div>

      <div className="card pad">
        <h2 className="card-title">Searchable-PDF detection</h2>
        <p className="muted dim">Says whether a stored document has a text layer.</p>
        {classify ? (
          <div className="stat-row">
            {Object.entries(classify.counts).map(([k, n]) => <StatChip key={k} n={n.toLocaleString()}>{k}</StatChip>)}
            {classify.running ? <span className="muted">running: {classify.done} / {classify.total}</span> : null}
            {classify.last_error ? <span className="err-text">{classify.last_error}</span> : null}
          </div>
        ) : <Spinner />}
        {isAdmin ? (
          <div className="btn-row">
            <button type="button" className="btn btn-sm" disabled={classify?.running} onClick={() => void run(() => classifyDatasheets("missing"))}>Detect what is missing</button>
            <button type="button" className="btn btn-sm" disabled={classify?.running} onClick={() => void run(() => classifyDatasheets("all"))}>Detect everything again</button>
          </div>
        ) : null}
      </div>

      <div className="card pad">
        <h2 className="card-title">Broken files</h2>
        <p className="muted dim">Stored documents nothing can open: empty files, and PDFs that will not parse.</p>
        {broken ? (
          broken.items.length ? (
            <DataTable rows={broken.items} rowKey={(_r) => JSON.stringify(_r)}
              columns={[{ key: "x", label: "Document", width: 100, className: "mono", get: (r) => JSON.stringify(r) }]} />
          ) : <p className="muted">None.</p>
        ) : <Spinner />}
        {isAdmin && broken?.items.length ? (
          <button type="button" className="btn btn-sm btn-danger" onClick={() => void ask(
            `Remove the ${broken.items.length} broken document(s)? Each one falls back to its previous version.`,
            "Remove broken files", purgeBrokenDatasheets)}>Remove {broken.items.length}…</button>
        ) : null}
      </div>

      <div className="card pad">
        <h2 className="card-title">Repeated versions</h2>
        <p className="muted dim">Stored versions that repeat the document before them, because a vendor re-signed the same PDF.</p>
        {restamps ? (
          restamps.items.length ? (
            <DataTable rows={restamps.items} rowKey={(_r) => JSON.stringify(_r)}
              columns={[{ key: "x", label: "Version", width: 100, className: "mono", get: (r) => JSON.stringify(r) }]} />
          ) : <p className="muted">None.</p>
        ) : <Spinner />}
        {isAdmin && restamps?.items.length ? (
          <button type="button" className="btn btn-sm btn-danger" disabled={classify?.running} onClick={() => void ask(
            `Fold the ${restamps.items.length} repeated version(s) into the ones they repeat? Pins move, and orphaned documents are deleted.`,
            "Fold repeated versions", collapseRestamps)}>Fold {restamps.items.length}…</button>
        ) : null}
      </div>

      <div className="card pad">
        <h2 className="card-title">Storage</h2>
        {storage ? (
          <div className="stat-row">
            <StatChip n={storage.documents.toLocaleString()}>documents</StatChip>
            <StatChip n={storage.versions.toLocaleString()}>versions</StatChip>
            <StatChip n={`${(storage.document_bytes / 1e6).toFixed(0)} MB`}>stored</StatChip>
            <StatChip n={storage.documents_shared_by_several_datasheets.toLocaleString()}>shared</StatChip>
            {storage.reclaim.running ? <span className="muted">rewriting the tables…</span> : null}
            {storage.reclaim.last_error ? <span className="err-text">{storage.reclaim.last_error}</span> : null}
          </div>
        ) : <Spinner />}
        {isAdmin ? (
          <div className="btn-row">
            <button type="button" className="btn btn-sm" disabled={storage?.reclaim.running} onClick={() => void ask(
              "Rewrite the datasheet tables, so deleted files leave the disk? It locks those tables while it runs.",
              "Reclaim storage", reclaimDatasheetStorage)}>Reclaim storage…</button>
          </div>
        ) : null}
      </div>
    </>
  );
}

export default function Datasheets() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const tab: Tab = TABS.some((t) => t.id === raw) ? (raw as Tab) : "search";
  return (
    <PageShell>
      <div className="toolbar">
        <h1>Datasheets</h1>
        <span className="toolbar-total">Every datasheet URL is re-fetched once a night. KiCad opens the archived copy of a PDF, and the live link of a web page.</span>
      </div>
      <TabStrip tabs={TABS} value={tab} label="Datasheet sections"
        onChange={(t) => setParams(t === "search" ? {} : { tab: t }, { replace: true })} />
      {tab === "search" ? <SearchTab /> : null}
      {tab === "archive" ? <DatasheetArchiveCard /> : null}
      {tab === "jobs" ? <JobsTab /> : null}
    </PageShell>
  );
}
