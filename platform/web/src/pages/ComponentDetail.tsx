import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Link, useParams } from "react-router-dom";
import {
  addComment,
  addComponentFile,
  createVersion,
  deleteComment,
  errorMessage,
  fetchDatasheet,
  footprintGlbUrl,
  footprintSvgUrl,
  getComments,
  getComponent,
  getModels3d,
  getPricePoints,
  getVersion,
  isAbortError,
  refreshPricePoints,
  setPricePoints,
  symbolSvgUrl,
  uploadDatasheetFile,
  type ComponentComment,
  type ComponentDetail as ComponentDetailT,
  type DatasheetRow,
  type Model3DFile,
  type PricePointsResponse,
  type VersionDetail,
} from "../api";
import { fileHref } from "../viewkind";
import {
  BaseSymbolSelect,
  buildProperties,
  CategorySelect,
  DatasheetsEditor,
  FootprintDatalist,
  nextRid,
  PropertiesEditor,
  usePickers,
  type EditDs,
  type EditRow,
} from "../components/editing";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { useStickyState } from "../useStickyState";

const FP_DATALIST_ID = "fp-options";

/** Lazy: pulls in the model-viewer/three.js chunk only when 3D is opened. */
const ModelViewer = lazy(() => import("../components/ModelViewer"));

/** Renders http(s) values as links (new tab), plain text otherwise. */
function LinkifyValue({ text }: { text: string }) {
  if (/^https?:\/\//.test(text)) {
    return (
      <a href={text} target="_blank" rel="noreferrer" className="val-link">
        {text}
      </a>
    );
  }
  return <>{text}</>;
}

// ------------------------------------------------------------ SVG preview

type PreviewState =
  | { kind: "loading" }
  | { kind: "ok"; src: string }
  | { kind: "missing"; message: string }
  | { kind: "error"; message: string };

/** Fetches an SVG endpoint and shows it via <img>, filling its container.
 *  `url` null means the version has nothing pinned — placeholder, no request. */
function PreviewFill({ url, missingText }: { url: string | null; missingText: string }) {
  const [state, setState] = useState<PreviewState>({ kind: "loading" });

  useEffect(() => {
    if (url === null) return;
    let objectUrl: string | null = null;
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    fetch(url, { signal: ctrl.signal })
      .then(async (res) => {
        if (res.status === 404) {
          let detail = "";
          try {
            const body = (await res.json()) as { detail?: unknown };
            if (typeof body.detail === "string") detail = body.detail;
          } catch {
            // ignore non-JSON body
          }
          setState({ kind: "missing", message: detail || missingText });
          return;
        }
        if (!res.ok) {
          setState({ kind: "error", message: `Preview failed (HTTP ${res.status})` });
          return;
        }
        const blob = await res.blob();
        objectUrl = URL.createObjectURL(blob);
        setState({ kind: "ok", src: objectUrl });
      })
      .catch((err) => {
        if (!isAbortError(err)) setState({ kind: "error", message: errorMessage(err) });
      });
    return () => {
      ctrl.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, missingText]);

  let body;
  if (url === null) {
    body = <span className="placeholder">{missingText}</span>;
  } else if (state.kind === "loading") {
    body = <Spinner label="Rendering…" />;
  } else if (state.kind === "ok") {
    body = <img src={state.src} alt="Preview" />;
  } else if (state.kind === "missing") {
    body = <span className="placeholder">{state.message}</span>;
  } else {
    body = <span className="placeholder err-text">{state.message}</span>;
  }

  return <div className="preview-fill">{body}</div>;
}

// -------------------------------------------------------------- 3D viewer

type Viewer3DState =
  | { kind: "loading" }
  | { kind: "ready"; src: string }
  | { kind: "missing"; message: string }
  | { kind: "error"; message: string };

/** GLB board view via Google's <model-viewer>: the API renders the footprint
 *  with copper/mask/silk on a board slab plus the placed 3D model
 *  (kicad-cli). model-viewer's neutral studio lighting is bright and it
 *  auto-frames the model with managed near/far planes (no orbit clipping).
 *  First server render takes a few seconds; it is cached after. */
function Viewer3D({ compId, versionNo }: { compId: number; versionNo: number }) {
  const [state, setState] = useState<Viewer3DState>({ kind: "loading" });

  useEffect(() => {
    let objectUrl: string | null = null;
    const ctrl = new AbortController();
    setState({ kind: "loading" });

    (async () => {
      try {
        // Fetch the GLB ourselves: gives clean 404 handling (no pinned
        // footprint) and a spinner during the slow first server render.
        const res = await fetch(footprintGlbUrl(compId, versionNo), { signal: ctrl.signal });
        if (res.status === 404) {
          let detail = "";
          try {
            const body = (await res.json()) as { detail?: unknown };
            if (typeof body.detail === "string") detail = body.detail;
          } catch {
            // ignore non-JSON body
          }
          setState({ kind: "missing", message: detail || "No pinned footprint" });
          return;
        }
        if (!res.ok) {
          setState({ kind: "error", message: `Board view failed (HTTP ${res.status})` });
          return;
        }
        const blob = await res.blob();
        objectUrl = URL.createObjectURL(blob);
        setState({ kind: "ready", src: objectUrl });
      } catch (err) {
        if (!isAbortError(err)) {
          setState({ kind: "error", message: errorMessage(err) });
        }
      }
    })();

    return () => {
      ctrl.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [compId, versionNo]);

  return (
    <div className="preview-fill viewer3d-wrap">
      {state.kind === "ready" ? (
        <Suspense
          fallback={
            <div className="viewer3d-overlay">
              <Spinner label="Loading viewer…" />
            </div>
          }
        >
          <ModelViewer src={state.src} />
        </Suspense>
      ) : (
        <div className="viewer3d-overlay">
          {state.kind === "loading" ? <Spinner label="Rendering board…" /> : null}
          {state.kind === "missing" ? (
            <span className="placeholder">{state.message}</span>
          ) : null}
          {state.kind === "error" ? (
            <span className="placeholder err-text">{state.message}</span>
          ) : null}
        </div>
      )}
    </div>
  );
}

/** Raw 3D model files behind the pinned footprint (STEP/WRL from the file
 *  mirror), linked through the /view page — STEP opens with a subelement
 *  tree, WRL with a mesh view. */
function ModelFilesRow({ compId, versionNo }: { compId: number; versionNo: number }) {
  const [files, setFiles] = useState<Model3DFile[]>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    setFiles([]);
    getModels3d(compId, versionNo, ctrl.signal)
      .then(setFiles)
      .catch(() => {
        /* cosmetic row — no error surface */
      });
    return () => ctrl.abort();
  }, [compId, versionNo]);

  if (files.length === 0) return null;
  return (
    <div className="model-files">
      <span className="muted">Model files:</span>
      {files.map((f) => (
        <a
          key={f.url}
          className="mono"
          href={fileHref(f.url, f.name)}
          target="_blank"
          rel="noreferrer"
          title={`${f.name} (${Math.round(f.size_bytes / 1024)} kB)`}
        >
          {f.name}
        </a>
      ))}
    </div>
  );
}

// ---------------------------------------------------------- preview panels

function SymbolPanel({ caption, url }: { caption: string; url: string | null }) {
  return (
    <section className="card preview-panel">
      <div className="panel-head">
        <h3 className="card-title panel-cap" title={caption}>
          {caption}
        </h3>
      </div>
      <PreviewFill url={url} missingText="No pinned symbol" />
    </section>
  );
}

function FootprintPanel({
  caption,
  svgUrl,
  compId,
  versionNo,
}: {
  caption: string;
  svgUrl: string | null;
  compId: number;
  versionNo: number | null;
}) {
  const [mode, setMode] = useStickyState<"2d" | "3d">("component:fpMode", "2d");
  return (
    <section className="card preview-panel">
      <div className="panel-head">
        <h3 className="card-title panel-cap" title={caption}>
          {caption}
        </h3>
        <div className="seg" role="group" aria-label="Footprint view mode">
          <button
            type="button"
            className={mode === "2d" ? "on" : ""}
            aria-pressed={mode === "2d"}
            onClick={() => setMode("2d")}
          >
            2D
          </button>
          <button
            type="button"
            className={mode === "3d" ? "on" : ""}
            aria-pressed={mode === "3d"}
            onClick={() => setMode("3d")}
          >
            3D
          </button>
        </div>
      </div>
      {mode === "2d" || versionNo === null ? (
        <PreviewFill url={svgUrl} missingText="No pinned footprint" />
      ) : (
        <>
          <Viewer3D compId={compId} versionNo={versionNo} />
          <ModelFilesRow compId={compId} versionNo={versionNo} />
        </>
      )}
    </section>
  );
}

// ------------------------------------------------------------------- notes

/** Component-scoped notes (Facebook-style, not versioned) — the user's
 *  future-reference notebook. Fetched once per component id. */
function NotesPanel({ compId }: { compId: number }) {
  const [comments, setComments] = useState<ComponentComment[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  /** "auto" follows the content (open when any note exists); an explicit
   *  user toggle ("open"/"closed") wins for the rest of the visit. */
  const [openState, setOpenState] = useState<"auto" | "open" | "closed">("auto");
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const open =
    openState === "open" || (openState === "auto" && (comments?.length ?? 0) > 0);

  useEffect(() => {
    const ctrl = new AbortController();
    setComments(null);
    setLoadError(null);
    setActionError(null);
    setDraft("");
    setOpenState("auto");
    getComments(compId, ctrl.signal)
      .then((list) => {
        setComments(list);
      })
      .catch((err) => {
        if (!isAbortError(err)) setLoadError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [compId]);

  const submit = async () => {
    const text = draft.trim();
    if (!text || posting) return;
    setPosting(true);
    setActionError(null);
    try {
      const c = await addComment(compId, text);
      setComments((prev) => [...(prev ?? []), c]);
      setDraft("");
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setPosting(false);
    }
  };

  const del = async (c: ComponentComment) => {
    if (!window.confirm("Delete this note?")) return;
    setBusyId(c.id);
    setActionError(null);
    try {
      await deleteComment(c.id);
      setComments((prev) => (prev ?? []).filter((x) => x.id !== c.id));
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <section className="card notes-panel">
      <button
        type="button"
        className="notes-head"
        aria-expanded={open}
        onClick={() => setOpenState(open ? "closed" : "open")}
      >
        <svg
          className={"chev" + (open ? " open" : "")}
          width="10"
          height="10"
          viewBox="0 0 10 10"
          aria-hidden="true"
        >
          <path d="M3 1.5 L7 5 L3 8.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
        <span>Notes{comments !== null ? ` (${comments.length})` : ""}</span>
        {comments === null && loadError === null ? <Spinner /> : null}
      </button>
      {open ? (
        <>
          {loadError ? (
            <p className="pad-note err-text">Notes failed to load: {loadError}</p>
          ) : comments !== null && comments.length === 0 ? (
            <p className="muted pad-note">No notes yet.</p>
          ) : (
            <ul className="notes-list">
              {(comments ?? []).map((c) => (
                <li key={c.id} className="note">
                  <div className="note-head mono">
                    <span className="note-author">{c.author}</span>
                    <span className="note-date">{new Date(c.created_at).toLocaleString()}</span>
                    <button
                      type="button"
                      className="row-del note-del"
                      disabled={busyId !== null}
                      onClick={() => void del(c)}
                      aria-label="Delete note"
                      title="Delete note"
                    >
                      &#x2715;
                    </button>
                  </div>
                  <div className="note-body">{c.body}</div>
                </li>
              ))}
            </ul>
          )}
          {actionError ? <p className="pad-note err-text">{actionError}</p> : null}
          <div className="note-form">
            <textarea
              className="text note-textarea"
              rows={2}
              placeholder="Add a note about this component…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              aria-label="Add a note"
            />
            <button
              type="button"
              className="btn btn-sm"
              disabled={posting || draft.trim() === ""}
              onClick={() => void submit()}
            >
              {posting ? "Adding…" : "Add note"}
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}

// -------------------------------------------------------------- meta / kv

function MetaRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

/** One labeled stock-pool pill: green when stocked, red when 0, neutral when
 *  unknown. The pools are separate inventories that routinely disagree. */
function PoolPill({ label, value, title }: { label: string; value: number | null; title: string }) {
  const tone = value == null ? "neutral" : value > 0 ? "ok" : "err";
  return (
    <span className={`pill ${tone}`} title={title}>
      {label} {value == null ? "?" : value.toLocaleString()}
    </span>
  );
}

/** Full price ladder (every quantity break): LCSC rows are robot-managed and
 *  read-only; manual levels (any other source) are editable here and saved
 *  wholesale via PUT /price-points. Project BOMs price from this ladder. */
function PriceLadderCard({ compId }: { compId: number }) {
  interface DraftPoint {
    qty_from: string;
    unit_price: string;
    currency: string;
    source: string;
  }
  const [data, setData] = useState<PricePointsResponse | null>(null);
  const [draft, setDraft] = useState<DraftPoint[] | null>(null); // null = view mode
  const [busy, setBusy] = useState<"save" | "refresh" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setData(null);
    setDraft(null);
    setError(null);
    setNote(null);
    getPricePoints(compId, ctrl.signal)
      .then(setData)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [compId]);

  const lcscPoints = data?.points.filter((p) => p.source === "LCSC") ?? [];
  const manualPoints = data?.points.filter((p) => p.source !== "LCSC") ?? [];

  const startEdit = () =>
    setDraft(
      manualPoints.map((p) => ({
        qty_from: String(p.qty_from),
        unit_price: String(p.unit_price),
        currency: p.currency,
        source: p.source,
      })),
    );

  const save = () => {
    if (draft === null) return;
    const points = draft
      .filter((d) => d.qty_from.trim() !== "" && d.unit_price.trim() !== "")
      .map((d) => ({
        qty_from: Math.max(1, parseInt(d.qty_from, 10) || 1),
        unit_price: Number(d.unit_price) || 0,
        currency: d.currency.trim().toUpperCase() || "USD",
        source: d.source.trim() || "Manual",
      }));
    setBusy("save");
    setError(null);
    setPricePoints(compId, points)
      .then((r) => {
        setData(r);
        setDraft(null);
        setBusy(null);
        setNote(null);
      })
      .catch((err) => {
        setError(errorMessage(err));
        setBusy(null);
      });
  };

  const refresh = () => {
    setBusy("refresh");
    setError(null);
    refreshPricePoints(compId)
      .then((r) => {
        setData(r);
        setBusy(null);
        setNote("LCSC ladder refreshed.");
      })
      .catch((err) => {
        setError(errorMessage(err));
        setBusy(null);
      });
  };

  const patchDraft = (i: number, patch: Partial<DraftPoint>) =>
    setDraft((d) => (d === null ? d : d.map((row, j) => (j === i ? { ...row, ...patch } : row))));

  return (
    <section className="card pad ladder-card">
      <h3 className="card-title">Pricing</h3>
      {error ? <ErrorBanner message={error} /> : null}
      {note ? <p className="muted">{note}</p> : null}
      {data === null && !error ? <Spinner label="Loading pricing" /> : null}

      {data !== null ? (
        <>
          <div className="stock-pools">
            <PoolPill
              label="LCSC"
              value={data.supply ? data.supply.stock : null}
              title="LCSC retail stock (lcsc.com webshop)"
            />
            <PoolPill
              label="JLCPCB"
              value={data.supply ? data.supply.jlc_stock : null}
              title="JLCPCB assembly-parts stock (jlcpcb.com/parts) — a separate pool from LCSC retail"
            />
            {data.private_qty > 0 ? (
              <span className="pill ok" title="Held in your private JLC parts library">
                own {data.private_qty.toLocaleString()}
              </span>
            ) : null}
            {data.supply ? (
              <span className="muted">
                MOQ {data.supply.moq ?? "?"}
                {data.supply.checked_at
                  ? ` · checked ${data.supply.checked_at.slice(0, 10)}`
                  : ""}
              </span>
            ) : null}
          </div>
          {data.points.length === 0 && draft === null ? (
            <p className="muted">
              No price levels yet — refresh the LCSC ladder or add manual levels.
            </p>
          ) : null}
          {data.points.length > 0 ? (
            <table className="data ladder-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th className="num">From qty</th>
                  <th className="num">Unit price</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {[...lcscPoints, ...(draft === null ? manualPoints : [])]
                  .sort((a, b) => a.qty_from - b.qty_from)
                  .map((p) => (
                    <tr key={p.id}>
                      <td className={p.source === "LCSC" ? "muted" : undefined}>{p.source}</td>
                      <td className="num mono">{p.qty_from.toLocaleString()}</td>
                      <td className="num mono">
                        {p.unit_price} {p.currency}
                      </td>
                      <td className="muted">{p.updated_at.slice(0, 10)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          ) : null}

          {draft !== null ? (
            <div className="ladder-edit">
              <p className="muted">
                Manual levels (LCSC rows above stay robot-managed). Each line: from this
                quantity up, this unit price applies.
              </p>
              {draft.map((d, i) => (
                <div key={i} className="ladder-edit-row">
                  ≥
                  <input className="text step-qty" type="number" min="1" value={d.qty_from}
                    aria-label={`Level ${i + 1} from quantity`}
                    onChange={(e) => patchDraft(i, { qty_from: e.target.value })} />
                  pcs:
                  <input className="text step-price" type="number" step="0.0001" min="0"
                    value={d.unit_price}
                    aria-label={`Level ${i + 1} unit price`}
                    onChange={(e) => patchDraft(i, { unit_price: e.target.value })} />
                  <input className="text step-cur" value={d.currency} maxLength={3}
                    aria-label={`Level ${i + 1} currency`}
                    onChange={(e) => patchDraft(i, { currency: e.target.value.toUpperCase() })} />
                  <input className="text step-src" value={d.source} placeholder="Manual"
                    title="Source label, e.g. Manual, Mouser, TME"
                    aria-label={`Level ${i + 1} source`}
                    onChange={(e) => patchDraft(i, { source: e.target.value })} />
                  <button type="button" className="row-del" title="Remove level"
                    onClick={() => setDraft((dd) => dd?.filter((_, j) => j !== i) ?? null)}>
                    &#x2715;
                  </button>
                </div>
              ))}
              <div className="btn-row">
                <button type="button" className="btn btn-sm"
                  onClick={() =>
                    setDraft((dd) => [
                      ...(dd ?? []),
                      { qty_from: "1", unit_price: "", currency: "USD", source: "Manual" },
                    ])
                  }>
                  ＋ Add price level
                </button>
                <button type="button" className="btn btn-sm btn-accent" disabled={busy !== null}
                  onClick={save}>
                  {busy === "save" ? "Saving…" : "Save levels"}
                </button>
                <button type="button" className="btn btn-sm" disabled={busy !== null}
                  onClick={() => setDraft(null)}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="btn-row">
              <button type="button" className="btn btn-sm" onClick={startEdit}>
                {manualPoints.length > 0 ? "Edit manual levels" : "＋ Add manual levels"}
              </button>
              <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={refresh}>
                {busy === "refresh" ? "Refreshing…" : "Refresh LCSC ladder"}
              </button>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}

// -------------------------------------------------------------- edit state

interface EditState {
  base_component: string;
  category_id: number | "";
  rows: EditRow[];
  datasheets: EditDs[];
  dsTouched: boolean;
  comment: string;
  newKey: string;
  newValue: string;
}

// -------------------------------------------------------------------- page

export default function ComponentDetail() {
  const { id } = useParams();
  const compId = Number(id);

  const [detail, setDetail] = useState<ComponentDetailT | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedNo, setSelectedNo] = useState<number | null>(null);
  const [version, setVersion] = useState<VersionDetail | null>(null);
  const [versionLoading, setVersionLoading] = useState(false);
  const [versionError, setVersionError] = useState<string | null>(null);

  const [dsRows, setDsRows] = useState<DatasheetRow[]>([]);
  const [dsBusyId, setDsBusyId] = useState<number | null>(null);
  const [dsBusyKind, setDsBusyKind] = useState<"fetch" | "upload" | null>(null);
  const [dsHints, setDsHints] = useState<Record<number, { msg: string; tone: "warn" | "err" }>>({});

  const [editing, setEditing] = useState(false);
  const [edit, setEdit] = useState<EditState | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveNotice, setSaveNotice] = useState<string[] | null>(null);
  const { pickers, pickerError } = usePickers(editing);

  useEffect(() => {
    if (!Number.isFinite(compId)) {
      setDetailError("Invalid component id.");
      return;
    }
    const ctrl = new AbortController();
    setDetail(null);
    setDetailError(null);
    setSelectedNo(null);
    getComponent(compId, ctrl.signal)
      .then((d) => {
        setDetail(d);
        const fallback = d.versions.length > 0 ? d.versions[d.versions.length - 1].version_no : null;
        setSelectedNo(d.current_version_no ?? fallback);
      })
      .catch((err) => {
        if (!isAbortError(err)) setDetailError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [compId]);

  useEffect(() => {
    if (!Number.isFinite(compId) || selectedNo === null) return;
    const ctrl = new AbortController();
    setVersion(null);
    setDsRows([]);
    setDsHints({});
    setVersionLoading(true);
    setVersionError(null);
    getVersion(compId, selectedNo, ctrl.signal)
      .then((v) => {
        setVersion(v);
        setDsRows(v.datasheets);
        setVersionLoading(false);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setVersionError(errorMessage(err));
        setVersionLoading(false);
      });
    return () => ctrl.abort();
  }, [compId, selectedNo]);

  const hasCurrent = detail !== null && detail.current_version_no !== null;
  const isCurrentSelected =
    hasCurrent && selectedNo !== null && selectedNo === detail.current_version_no;

  const enterEdit = () => {
    if (version === null) return;
    setEdit({
      base_component: version.base_component,
      category_id: version.category_id ?? "",
      rows: [...version.properties]
        .sort((a, b) => a.position - b.position)
        .map((p) => ({
          rid: nextRid(),
          key: p.key,
          value: p.value ?? "",
          is_null: p.is_null,
          hide: p.hide,
          show_name: p.show_name,
          layout: p.layout,
        })),
      datasheets: dsRows.map((d) => ({
        rid: nextRid(),
        id: d.id,
        label: d.label,
        source_url: d.source_url ?? "",
      })),
      dsTouched: false,
      comment: "",
      newKey: "",
      newValue: "",
    });
    setEditing(true);
    setDirty(false);
    setSaveError(null);
    setSaveNotice(null);
  };

  const exitEdit = () => {
    setEditing(false);
    setEdit(null);
    setDirty(false);
    setSaveError(null);
  };

  const selectVersion = (no: number) => {
    if (no === selectedNo) return;
    if (editing && dirty && !window.confirm("Discard unsaved changes?")) return;
    exitEdit();
    setSelectedNo(no);
  };

  const patchEdit = (patch: Partial<EditState>) => {
    setEdit((prev) => (prev ? { ...prev, ...patch } : prev));
    setDirty(true);
  };

  const fetchDs = async (dsId: number) => {
    setDsBusyId(dsId);
    setDsBusyKind("fetch");
    setDsHints((h) => {
      const next = { ...h };
      delete next[dsId];
      return next;
    });
    try {
      const r = await fetchDatasheet(dsId);
      // Re-read the version's datasheet rows — version history changed server-side.
      if (selectedNo !== null) {
        try {
          const v = await getVersion(compId, selectedNo);
          setDsRows(v.datasheets);
        } catch {
          // keep the stale rows; the hint below still reports the outcome
        }
      }
      if (r.result === "skipped_unstable_non_pdf") {
        setDsHints((h) => ({
          ...h,
          [dsId]: {
            msg: "source is a web page — kept a single local copy, not versioned",
            tone: "warn",
          },
        }));
      } else if (r.looks_like_pdf === false) {
        setDsHints((h) => ({
          ...h,
          [dsId]: { msg: "downloaded HTML page, not a PDF — check the URL", tone: "warn" },
        }));
      } else if (r.component_bumped_to != null) {
        setDsHints((h) => ({
          ...h,
          [dsId]: {
            msg: `PDF content changed — component auto-bumped to v${r.component_bumped_to}`,
            tone: "warn",
          },
        }));
        // the version rail gained a new (current) version
        getComponent(compId)
          .then(setDetail)
          .catch(() => {});
      }
    } catch (err) {
      setDsHints((h) => ({ ...h, [dsId]: { msg: errorMessage(err), tone: "err" } }));
    } finally {
      setDsBusyId(null);
    }
  };

  // ---- local file uploads (per-row replace + new attachment rows) ----
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  /** Which upload the next picked file belongs to: a row id, or "new". */
  const uploadTargetRef = useRef<number | "new" | null>(null);
  const newFileLabelRef = useRef("");

  const pickFile = (target: number | "new", label = "") => {
    uploadTargetRef.current = target;
    newFileLabelRef.current = label;
    fileInputRef.current?.click();
  };

  const refreshDsRows = async () => {
    if (selectedNo === null) return;
    try {
      const v = await getVersion(compId, selectedNo);
      setDsRows(v.datasheets);
    } catch {
      // keep stale rows; the hint still reports the outcome
    }
  };

  const uploadDs = async (dsId: number, file: File) => {
    setDsBusyId(dsId);
    setDsHints((h) => {
      const next = { ...h };
      delete next[dsId];
      return next;
    });
    try {
      const r = await uploadDatasheetFile(dsId, file);
      await refreshDsRows();
      if (r.result === "unchanged") {
        setDsHints((h) => ({
          ...h,
          [dsId]: { msg: "identical to the stored copy — no new version", tone: "warn" },
        }));
      } else if (r.component_bumped_to != null) {
        setDsHints((h) => ({
          ...h,
          [dsId]: {
            msg: `file replaced — component auto-bumped to v${r.component_bumped_to}`,
            tone: "warn",
          },
        }));
        getComponent(compId)
          .then(setDetail)
          .catch(() => {});
      }
    } catch (err) {
      setDsHints((h) => ({ ...h, [dsId]: { msg: errorMessage(err), tone: "err" } }));
    } finally {
      setDsBusyId(null);
    }
  };

  const addFile = async (label: string, file: File) => {
    setDsBusyId(-1); // sentinel: disables the row buttons while adding
    try {
      const r = await addComponentFile(compId, label, file);
      setDsRows(r.datasheets);
      if (r.component_bumped_to != null) {
        setDsHints((h) => ({
          ...h,
          [r.id]: { msg: `file added — component version v${r.component_bumped_to}`, tone: "warn" },
        }));
      }
      // the version rail gained a new (current) version
      getComponent(compId)
        .then(setDetail)
        .catch(() => {});
    } catch (err) {
      window.alert(`Adding the file failed: ${errorMessage(err)}`);
    } finally {
      setDsBusyId(null);
    }
  };

  const onFilePicked = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file later
    const target = uploadTargetRef.current;
    uploadTargetRef.current = null;
    if (!file || target === null) return;
    if (target === "new") void addFile(newFileLabelRef.current, file);
    else void uploadDs(target, file);
  };

  const promptAddFile = () => {
    const label = window.prompt(
      'Label for the new file (e.g. "2D drawing (DXF)", "Enclosure STEP"):',
    );
    if (!label || !label.trim()) return;
    pickFile("new", label.trim());
  };

  const save = async () => {
    if (edit === null || version === null) return;
    const catId = edit.category_id;
    if (catId === "") {
      setSaveError("Choose a category before saving.");
      return;
    }
    const built = buildProperties(edit.rows, edit.newKey, edit.newValue);
    if ("error" in built) {
      setSaveError(built.error);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const res = await createVersion(compId, {
        base_component: edit.base_component,
        category_id: catId,
        properties: built.properties,
        removed_properties:
          version.removed_properties.length > 0 ? version.removed_properties : null,
        datasheets: edit.dsTouched
          ? edit.datasheets.map((d) => ({
              id: d.id,
              label: d.label.trim() || "Datasheet",
              source_url: d.source_url.trim() || null,
            }))
          : null,
        comment: edit.comment.trim() || null,
      });
      const d = await getComponent(compId);
      setDetail(d);
      exitEdit();
      setSaveNotice(res.mirror_warnings.length > 0 ? res.mirror_warnings : null);
      setSelectedNo(res.version_no);
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  // ------------------------------------------------------------- rendering

  if (detailError) {
    return (
      <div className="main-solo">
        <div className="page">
          <Link to="/" className="backlink">
            &larr; Browse
          </Link>
          <ErrorBanner message={`Component failed to load: ${detailError}`} />
        </div>
      </div>
    );
  }

  if (detail === null) {
    return (
      <div className="main-solo">
        <div className="page block-loading">
          <Spinner label="Loading component" />
        </div>
      </div>
    );
  }

  const versions = [...detail.versions].sort((a, b) => a.version_no - b.version_no);
  const symCaption = version?.symbol
    ? `Symbol — ${version.symbol.name} v${version.symbol.version_no}`
    : "Symbol — not pinned";
  const fpCaption = version?.footprint
    ? `Footprint — ${version.footprint.name} v${version.footprint.version_no}`
    : "Footprint — not pinned";

  return (
    <div className="detail-page">
      <div className="detail-left">
        <div className="detail-top">
          <Link to="/" className="backlink">
            &larr; Browse
          </Link>
          <div className="detail-header">
            <h1 className="mono comp-name">{detail.name}</h1>
            {version ? <StatusPill status={version.status} /> : null}
          </div>
          <div className="version-rail" role="tablist" aria-label="Versions">
            {versions.map((v) => {
              const isCurrent = v.version_no === detail.current_version_no;
              const isSelected = v.version_no === selectedNo;
              const isDraft = v.status === "draft";
              return (
                <button
                  key={v.version_no}
                  type="button"
                  role="tab"
                  aria-selected={isSelected}
                  className={
                    "vchip" +
                    (isSelected ? " selected" : "") +
                    (isCurrent ? " current" : "") +
                    (isDraft ? " draft" : "")
                  }
                  title={
                    isDraft
                      ? `v${v.version_no} (draft proposal)`
                      : v.created_by === "system"
                        ? `v${v.version_no} — auto: ${v.comment ?? "datasheet update"}`
                        : isCurrent
                          ? `v${v.version_no} (current)`
                          : `v${v.version_no}`
                  }
                  onClick={() => selectVersion(v.version_no)}
                >
                  v{v.version_no}
                </button>
              );
            })}
            <span className="rail-spacer" />
            {!editing && hasCurrent ? (
              isCurrentSelected ? (
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={version === null}
                  onClick={enterEdit}
                >
                  Edit
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled
                    title="Switch to the current version to edit"
                  >
                    Edit
                  </button>
                  <span className="rail-hint">switch to current version to edit</span>
                </>
              )
            ) : null}
          </div>
        </div>

        {version?.status === "draft" ? (
          <div className="banner-warn" role="status">
            Draft proposal — approve or reject in <Link to="/proposals">Proposals</Link>.
          </div>
        ) : null}
        {saveNotice ? (
          <div className="banner-warn" role="status">
            Saved with mirror warnings: {saveNotice.join("; ")}
          </div>
        ) : null}
        {versionError ? <ErrorBanner message={`Version failed to load: ${versionError}`} /> : null}
        {saveError ? <ErrorBanner message={saveError} /> : null}

        {versionLoading ? (
          <div className="block-loading">
            <Spinner label={`Loading v${selectedNo ?? ""}`} />
          </div>
        ) : null}

        {version && !editing ? (
          <section className="card pad meta-card">
            <dl className="kv">
              <MetaRow label="Status">
                <StatusPill status={version.status} />
              </MetaRow>
              <MetaRow label="Created">
                <span className="mono">{new Date(version.created_at).toLocaleString()}</span>
                {version.created_by ? <span className="muted"> by {version.created_by}</span> : null}
              </MetaRow>
              <MetaRow label="Approved by">
                {version.approved_by ?? <span className="null">—</span>}
              </MetaRow>
              <MetaRow label="Category">
                {version.category_path || <span className="null">—</span>}
              </MetaRow>
              <MetaRow label="Symbol">
                {version.symbol ? (
                  <span className="mono">
                    {version.symbol.name} <span className="pin-ver">v{version.symbol.version_no}</span>
                  </span>
                ) : (
                  // no pinned symbol — the base ref is the only information left
                  <span className="mono">
                    {version.base_component || <span className="null">not pinned</span>}
                    {version.base_component ? <span className="null"> (unresolved)</span> : null}
                  </span>
                )}
              </MetaRow>
              <MetaRow label="Footprint">
                {version.footprint ? (
                  <span className="mono">
                    {version.footprint.name}{" "}
                    <span className="pin-ver">v{version.footprint.version_no}</span>
                  </span>
                ) : (
                  <span className="null">not pinned</span>
                )}
              </MetaRow>
              {version.datasheet_pins.map((pin) => (
                <MetaRow key={pin.datasheet_id} label={pin.label}>
                  {pin.pdf_version_no !== null ? (
                    <span className="mono">
                      PDF <span className="pin-ver">v{pin.pdf_version_no}</span>
                    </span>
                  ) : (
                    <span className="null">no local copy at the time</span>
                  )}
                </MetaRow>
              ))}
              {version.comment ? <MetaRow label="Comment">{version.comment}</MetaRow> : null}
            </dl>
          </section>
        ) : null}

        {version && editing && edit ? (
          <section className="card pad edit-card">
            {pickerError ? (
              <ErrorBanner message={`Pickers failed to load: ${pickerError}`} />
            ) : null}
            <div className="edit-grid">
              <label>
                Base symbol
                <BaseSymbolSelect
                  value={edit.base_component}
                  pickers={pickers}
                  onChange={(v) => patchEdit({ base_component: v })}
                />
              </label>
              <label>
                Category
                <CategorySelect
                  value={edit.category_id}
                  pickers={pickers}
                  fallbackLabel={version.category_path}
                  onChange={(v) => patchEdit({ category_id: v })}
                />
              </label>
            </div>
            <p className="muted edit-hint">
              The <span className="mono">Footprint</span> property drives the pinned footprint —
              its value field suggests <span className="mono">7Sigma:</span> footprints.
            </p>
            <div className="edit-actions">
              <input
                type="text"
                className="text comment"
                placeholder="what changed?"
                value={edit.comment}
                onChange={(e) => patchEdit({ comment: e.target.value })}
              />
              <button
                type="button"
                className="btn btn-accent"
                disabled={saving || edit.category_id === "" || !edit.base_component}
                onClick={() => void save()}
              >
                {saving ? "Saving…" : "Save"}
              </button>
              <button type="button" className="btn" disabled={saving} onClick={exitEdit}>
                Cancel
              </button>
            </div>
            <FootprintDatalist id={FP_DATALIST_ID} pickers={pickers} />
          </section>
        ) : null}

        <PriceLadderCard compId={compId} />

        {version ? (
          <section className="card ds-card">
            <h3 className="card-title pad-title">Datasheets &amp; files</h3>
            {!editing ? (
              <>
                {dsRows.length === 0 ? (
                  <p className="muted pad-note">No datasheets or files.</p>
                ) : (
                <ul className="ds-list">
                  {dsRows.map((d, i) => {
                    const hint = dsHints[d.id];
                    return (
                      <li key={d.id} className="ds-row">
                        <span className="ds-label mono">
                          {d.label}
                          {i === 0 ? <span className="tag-hidden">primary</span> : null}
                        </span>
                        {d.source_url ? (
                          <a
                            className="ds-url mono"
                            href={d.source_url}
                            target="_blank"
                            rel="noreferrer"
                            title={d.source_url}
                          >
                            {d.source_url}
                          </a>
                        ) : (
                          <span className="null ds-url">no URL</span>
                        )}
                        {d.has_file ? (
                          <>
                            <a
                              className="ds-local"
                              href={fileHref(`/api/datasheets/${d.id}/file`, d.filename ?? d.label)}
                              target="_blank"
                              rel="noreferrer"
                              title={
                                d.filename
                                  ? `${d.filename}${
                                      d.size_bytes != null
                                        ? ` (${Math.round(d.size_bytes / 1024)} kB)`
                                        : ""
                                    }`
                                  : "stored copy"
                              }
                            >
                              local copy
                            </a>
                            {d.pdf_version_no !== null ? (
                              <span className="tag-hidden pdf-ver" title="Current stored version">
                                PDF v{d.pdf_version_no}
                              </span>
                            ) : null}
                            {d.versions.length > 1 ? (
                              <details className="ds-history">
                                <summary>history ({d.versions.length})</summary>
                                <ul>
                                  {[...d.versions].reverse().map((v) => (
                                    <li key={v.version_no} className="mono">
                                      <a
                                        href={fileHref(
                                          `/api/datasheets/${d.id}/versions/${v.version_no}/file`,
                                          d.filename ?? d.label,
                                        )}
                                        target="_blank"
                                        rel="noreferrer"
                                      >
                                        v{v.version_no}
                                      </a>{" "}
                                      · {new Date(v.fetched_at).toLocaleDateString()} ·{" "}
                                      {Math.round(v.size_bytes / 1024)} kB
                                    </li>
                                  ))}
                                </ul>
                              </details>
                            ) : null}
                          </>
                        ) : null}
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={!d.source_url || dsBusyId !== null}
                          onClick={() => void fetchDs(d.id)}
                        >
                          {dsBusyId === d.id && dsBusyKind === "fetch" ? "Fetching…" : "Fetch"}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={dsBusyId !== null}
                          title="Replace the stored copy with a file from your computer (versioned)"
                          onClick={() => pickFile(d.id)}
                        >
                          {dsBusyId === d.id && dsBusyKind === "upload" ? "Uploading…" : "Upload"}
                        </button>
                        {hint ? <span className={`ds-hint ${hint.tone}`}>{hint.msg}</span> : null}
                      </li>
                    );
                  })}
                </ul>
                )}
                <div className="ds-addfile">
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={dsBusyId !== null}
                    onClick={promptAddFile}
                  >
                    {dsBusyId === -1 ? "Uploading…" : "＋ Add file…"}
                  </button>
                  <span className="muted">
                    PDF, DXF, DWG, STEP, 3MF… — stored versioned, viewable in the browser
                  </span>
                </div>
                <input ref={fileInputRef} type="file" hidden onChange={onFilePicked} />
              </>
            ) : edit ? (
              <DatasheetsEditor
                rows={edit.datasheets}
                onRows={(rows) => patchEdit({ datasheets: rows, dsTouched: true })}
              />
            ) : null}
          </section>
        ) : null}

        {version ? (
          <section className="card props-panel">
            <h3 className="card-title pad-title">Properties</h3>
            <div className="props-scroll">
              {!editing ? (
                <table className="data props">
                  <thead>
                    <tr>
                      <th>Key</th>
                      <th>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...version.properties]
                      .sort((a, b) => a.position - b.position)
                      .map((p) => (
                        <tr key={p.key} className={p.hide ? "dim" : undefined}>
                          <td className="mono prop-key">
                            {p.key}
                            {p.hide ? <span className="tag-hidden">hidden</span> : null}
                          </td>
                          <td className="mono">
                            {p.is_null ? (
                              <span className="null">null</span>
                            ) : (
                              <>
                                <LinkifyValue text={p.value ?? ""} />
                                {p.resolved_value !== "" && p.resolved_value !== p.value ? (
                                  <div className="resolved">
                                    &rarr; <LinkifyValue text={p.resolved_value} />
                                  </div>
                                ) : null}
                              </>
                            )}
                          </td>
                        </tr>
                      ))}
                    {version.properties.length === 0 ? (
                      <tr>
                        <td colSpan={2} className="empty">
                          No properties.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              ) : edit ? (
                <PropertiesEditor
                  rows={edit.rows}
                  newKey={edit.newKey}
                  newValue={edit.newValue}
                  fpDatalistId={FP_DATALIST_ID}
                  onRows={(rows) => patchEdit({ rows })}
                  onNew={(patch) => patchEdit(patch)}
                  onError={setSaveError}
                />
              ) : null}
            </div>
            {version.removed_properties.length > 0 ? (
              <p className="muted removed-note">
                Removed properties: {version.removed_properties.join(", ")}
              </p>
            ) : null}
          </section>
        ) : null}

        <NotesPanel compId={compId} />
      </div>

      <div className="detail-right">
        <SymbolPanel
          caption={symCaption}
          url={version?.symbol ? symbolSvgUrl(compId, version.version_no) : null}
        />
        <FootprintPanel
          caption={fpCaption}
          svgUrl={version?.footprint ? footprintSvgUrl(compId, version.version_no) : null}
          compId={compId}
          versionNo={version ? version.version_no : null}
        />
      </div>
    </div>
  );
}
