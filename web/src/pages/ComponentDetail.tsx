import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import {
  addComponentFile,
  createVersion,
  errorMessage,
  fetchDatasheet,
  footprintGlbUrl,
  footprintSvgUrl,
  getComponent,
  getModels3d,
  getPricePoints,
  getVersion,
  isAbortError,
  refreshPricePoints,
  setComponentInLibrary,
  setComponentPurchasable,
  setLifecycle,
  setPricePoints,
  symbolSvgUrl,
  uploadDatasheetFile,
  type ComponentDetail as ComponentDetailT,
  type DatasheetRow,
  type Model3DFile,
  type PricePointsResponse,
  type LifecycleState,
  type PinnedRef,
  type PropertyRow,
  type ReviewPart,
  type VersionDetail,
} from "../api";
import { fileHref } from "../viewkind";
import { useDialog } from "../components/Dialog";
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
import { BackLink, ErrorBanner, LifecyclePill, ReviewPill, SignoffPill, Spinner, StatusPill } from "../components/Ui";
import CommentsPanel from "../components/CommentsPanel";
import SignoffCard from "../components/SignoffCard";
import ReviewCard from "../components/ReviewCard";
import WhereUsedCard from "../components/WhereUsedCard";
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

// ------------------------------------------------------ proposal diff view

/** When a draft proposal is viewed against its current published version, each
 *  property is one of these relative to the current version. Copper = proposed. */
type DiffStatus = "same" | "added" | "changed" | "removed";

interface DiffPropRow {
  key: string;
  /** The property in the draft (null when the draft removed it). */
  draft: PropertyRow | null;
  /** The property in the current version (null when the draft added it). */
  base: PropertyRow | null;
  status: DiffStatus;
}

function propEq(a: PropertyRow, b: PropertyRow): boolean {
  return a.is_null === b.is_null && (a.value ?? "") === (b.value ?? "");
}

/** Diffs the draft property set against the current one, preserving draft
 *  order, then appending anything the draft dropped as `removed`. */
function buildPropDiff(draftProps: PropertyRow[], baseProps: PropertyRow[]): DiffPropRow[] {
  const baseByKey = new Map(baseProps.map((p) => [p.key, p]));
  const seen = new Set<string>();
  const rows: DiffPropRow[] = [];
  for (const p of [...draftProps].sort((a, b) => a.position - b.position)) {
    seen.add(p.key);
    const base = baseByKey.get(p.key) ?? null;
    const status: DiffStatus = base === null ? "added" : propEq(p, base) ? "same" : "changed";
    rows.push({ key: p.key, draft: p, base, status });
  }
  for (const b of [...baseProps].sort((a, b) => a.position - b.position)) {
    if (!seen.has(b.key)) rows.push({ key: b.key, draft: null, base: b, status: "removed" });
  }
  return rows;
}

/** Read-only value cell for a property (value or `null`, plus a resolved-template line). */
function PropValueView({ p }: { p: PropertyRow }) {
  if (p.is_null) return <span className="null">null</span>;
  return (
    <>
      <LinkifyValue text={p.value ?? ""} />
      {p.resolved_value !== "" && p.resolved_value !== p.value ? (
        <div className="resolved">
          &rarr; <LinkifyValue text={p.resolved_value} />
        </div>
      ) : null}
    </>
  );
}

const plainVal = (p: PropertyRow): string => (p.is_null ? "null" : p.value ?? "");

/** One property row, rendered plainly (`same`) or with the copper diff
 *  treatment (`added` / `changed` / `removed`). */
function DiffPropertyRow({ row }: { row: DiffPropRow }) {
  const prop = row.draft ?? row.base;
  if (prop === null) return null;
  // KiCad field visibility is curated on the base symbol, not per component —
  // the platform view shows every parameter plainly.
  const trClass = row.status !== "same" ? `diff-${row.status}` : "";
  return (
    <tr className={trClass.trim() || undefined}>
      <td className="mono prop-key">
        {row.status === "removed" ? <span className="strike">{row.key}</span> : row.key}
        {row.status === "added" ? <span className="diff-tag">added</span> : null}
        {row.status === "removed" ? <span className="diff-tag">removed</span> : null}
      </td>
      <td className="mono">
        {row.status === "changed" && row.base && row.draft ? (
          <>
            <span className="diff-old diff-old-line">{plainVal(row.base)}</span>
            <span className="diff-new">
              <PropValueView p={row.draft} />
            </span>
          </>
        ) : row.status === "added" && row.draft ? (
          <span className="diff-new">
            <PropValueView p={row.draft} />
          </span>
        ) : row.status === "removed" && row.base ? (
          <span className="diff-old">{plainVal(row.base)}</span>
        ) : row.draft ? (
          <PropValueView p={row.draft} />
        ) : null}
      </td>
    </tr>
  );
}

/** Meta value that highlights in copper when it differs from the current
 *  version, showing the previous value struck through beside it. */
function DiffMeta({
  changed,
  oldText,
  children,
}: {
  changed: boolean;
  oldText: string;
  children: ReactNode;
}) {
  if (!changed) return <>{children}</>;
  return (
    <span className="diff-meta">
      <span className="diff-new">{children}</span>
      <span className="diff-old"> was {oldText || "—"}</span>
    </span>
  );
}

/** The three verification claims on one card: the component's data, and the
 *  two drawings it pins. Summary pills always; the full ReviewCard mounts on
 *  expand, so the page stays one screen and the cards' fetches only happen
 *  when someone is actually verifying. */
function VerificationSection({
  detail,
  version,
  onChanged,
}: {
  detail: ComponentDetailT;
  version: VersionDetail;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState<"component" | "symbol" | "footprint" | null>(null);
  const parts = detail.review?.parts ?? {};
  const rows: { key: "component" | "symbol" | "footprint"; label: string; id: number | null }[] = [
    { key: "component", label: "Component data", id: detail.id },
    ...(version.symbol
      ? [{ key: "symbol" as const, label: `Symbol — ${version.symbol.name}`, id: version.symbol.id }]
      : []),
    ...(version.footprint
      ? [{
          key: "footprint" as const,
          label: `Footprint — ${version.footprint.name}`,
          id: version.footprint.id,
        }]
      : []),
  ];
  return (
    <section className="card pad meta-card">
      <h3 className="card-title">
        Verification <ReviewPill state={detail.review?.state} provenance={detail.review?.provenance} />
      </h3>
      <ul className="notes-list">
        {rows.map((r) => (
          <li key={r.key} className="note">
            <div className="note-head">
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setOpen(open === r.key ? null : r.key)}
              >
                {open === r.key ? "▾" : "▸"}
              </button>{" "}
              <span>{r.label}</span>{" "}
              <ReviewPill
                state={parts[r.key]?.state}
                provenance={parts[r.key]?.provenance ?? null}
              />
            </div>
            {open === r.key && r.id !== null ? (
              <ReviewCard kind={r.key} id={r.id} label={r.label} onChange={onChanged} />
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}


/** One pinned drawing: a link to it, which version this part was generated
 *  against, whether the library still serves that version, and whether anybody
 *  has verified it.
 *
 * The name is a LINK because a component is the place you find out a land
 * pattern is wrong, and reading it meant copying the name into the template
 * browser. `is_current === false` is the state auto-repoint exists to remove:
 * KiCad is served the newest drawing, so a stale pin means the board in the
 * schematic and the board in the library are not the same drawing. */
function PinnedGeometry({
  kind,
  pin,
  review,
}: {
  kind: "symbols" | "footprints";
  pin: PinnedRef;
  /** Verification of THIS version — omitted when an older component version is
   *  on screen, because the state on file describes the live pins. */
  review?: ReviewPart;
}) {
  const noun = kind === "symbols" ? "symbol" : "footprint";
  return (
    <span className="pin-line">
      <Link to={`/library/templates/${kind}/${pin.id}`} className="mono comp-link">
        {pin.name}
      </Link>{" "}
      <span className="pin-ver">v{pin.version_no}</span>
      {pin.is_current ? null : (
        <span
          className="pill warn"
          title={`This component was generated against v${pin.version_no}, but KiCad is served v${pin.current_version_no}. Publish a new component version to move it onto the current drawing.`}
        >
          library serves v{pin.current_version_no}
        </span>
      )}
      {review ? (
        <ReviewPill
          state={review.state}
          provenance={review.provenance}
          title={`Verification of this ${noun} version${
            review.unanswered?.length ? ` — unanswered: ${review.unanswered.join(", ")}` : ""
          }`}
        />
      ) : null}
    </span>
  );
}

/** Identity string for the pinned symbol (or base ref when unpinned). */
function symKey(v: VersionDetail): string {
  return v.symbol ? `${v.symbol.name} v${v.symbol.version_no}` : v.base_component || "—";
}

/** Identity string for the pinned footprint. */
function fpKey(v: VersionDetail): string {
  return v.footprint ? `${v.footprint.name} v${v.footprint.version_no}` : "not pinned";
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

/** Full price ladder (every quantity break): JLCPCB + LCSC rows are
 *  robot-managed and read-only — JLCPCB is the default price source, LCSC the
 *  fallback for parts JLC doesn't carry; manual levels (any other source) are
 *  editable here and saved wholesale via PUT /price-points. Project BOMs
 *  price from this ladder. */
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

  const ROBOT_SOURCES = ["JLCPCB", "LCSC"];
  const autoPoints = data?.points.filter((p) => ROBOT_SOURCES.includes(p.source)) ?? [];
  const hasJlc = autoPoints.some((p) => p.source === "JLCPCB");
  // JLCPCB is the default price source; LCSC rows appear only IN PLACE of a
  // missing JLCPCB ladder, never alongside it (the API stores both).
  const robotPoints = autoPoints.filter((p) => p.source === (hasJlc ? "JLCPCB" : "LCSC"));
  const manualPoints = data?.points.filter((p) => !ROBOT_SOURCES.includes(p.source)) ?? [];

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
        setNote("Supplier ladders refreshed.");
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
              No price levels yet — refresh the supplier ladders or add manual levels.
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
                {[...robotPoints, ...(draft === null ? manualPoints : [])]
                  .sort((a, b) => a.qty_from - b.qty_from)
                  .map((p) => (
                    <tr key={p.id}>
                      <td
                        className={ROBOT_SOURCES.includes(p.source) ? "muted" : undefined}
                        title={
                          p.source === "LCSC"
                            ? "LCSC retail fallback — JLCPCB has no ladder for this part"
                            : undefined
                        }>
                        {p.source}
                      </td>
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
                Manual levels (JLCPCB/LCSC rows above stay robot-managed). Each line: from
                this quantity up, this unit price applies.
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
                {busy === "refresh" ? "Refreshing…" : "Refresh supplier ladders"}
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

/** Free text folded to three lines with an expand toggle — a long version
 *  comment must not push the whole identity card down the page. */
function FoldedText({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.split("\n").length > 3 || text.length > 240;
  if (!long) return <>{text}</>;
  return (
    <>
      <span className={open ? "" : "clamp3"}>{text}</span>
      <button type="button" className="btn btn-sm" onClick={() => setOpen((v) => !v)}>
        {open ? "show less" : "show more"}
      </button>
    </>
  );
}


/** The lifecycle control in the page header: pill + a select. Deprecated and
 * obsolete hide the part from KiCad (chooser + generated libraries), so those
 * two confirm first. The one automatic transition (in_design -> released on
 * first human sign-off) happens server-side. */
function LifecycleSelect({
  detail,
  onChanged,
}: {
  detail: ComponentDetailT;
  onChanged: () => void;
}) {
  const dialog = useDialog();
  const [busy, setBusy] = useState(false);

  const change = async (state: LifecycleState) => {
    if (state === detail.lifecycle) return;
    if (
      (state === "deprecated" || state === "obsolete") &&
      !(await dialog.confirm(
        `Mark ${detail.name} as ${state}? It disappears from KiCad (chooser and generated libraries) and stays platform-only.`,
        { title: "Change lifecycle", confirmLabel: `Mark ${state}`, tone: "danger" },
      ))
    )
      return;
    setBusy(true);
    try {
      await setLifecycle(detail.id, state);
      onChanged();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Lifecycle change failed" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="btn-row">
      <LifecyclePill
        state={detail.lifecycle}
        title="Usage fitness — released on first human sign-off; deprecated/obsolete are hidden from KiCad"
      />
      <select
        className="text"
        value={detail.lifecycle}
        disabled={busy}
        onChange={(e) => void change(e.target.value as LifecycleState)}
        title="Change the lifecycle state"
      >
        <option value="in_design">in design</option>
        <option value="released">released</option>
        <option value="deprecated">deprecated</option>
        <option value="obsolete">obsolete</option>
      </select>
    </span>
  );
}

export default function ComponentDetail() {
  const { id } = useParams();
  const compId = Number(id);

  // Navigation state set by whoever linked here (Proposals, the filtered Browse
  // list, …): `backTo` is where "← Back" returns to; `showVersion` pre-selects a
  // version (a proposal link opens straight on its draft, no chip click needed).
  const location = useLocation();
  const navState = location.state as { backTo?: string; showVersion?: number | null } | null;
  const backTo = navState?.backTo ?? "/";
  const requestedVersion = navState?.showVersion ?? null;

  const [detail, setDetail] = useState<ComponentDetailT | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedNo, setSelectedNo] = useState<number | null>(null);
  const [version, setVersion] = useState<VersionDetail | null>(null);
  const [versionLoading, setVersionLoading] = useState(false);
  const [versionError, setVersionError] = useState<string | null>(null);
  // Current published version to diff a draft proposal against (null = not diffing).
  const [baseline, setBaseline] = useState<VersionDetail | null>(null);

  const [dsRows, setDsRows] = useState<DatasheetRow[]>([]);
  const [dsBusyId, setDsBusyId] = useState<number | null>(null);
  const [dsBusyKind, setDsBusyKind] = useState<"fetch" | "upload" | null>(null);
  const [dsHints, setDsHints] = useState<Record<number, { msg: string; tone: "warn" | "err" }>>({});

  const [purchasableBusy, setPurchasableBusy] = useState(false);

  const [editing, setEditing] = useState(false);
  const [edit, setEdit] = useState<EditState | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveNotice, setSaveNotice] = useState<string[] | null>(null);
  const { pickers, pickerError } = usePickers(editing);
  const dialog = useDialog();

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
        // A proposal link asks for its draft explicitly — honor it when present.
        const wanted =
          requestedVersion !== null && d.versions.some((v) => v.version_no === requestedVersion)
            ? requestedVersion
            : d.current_version_no ?? fallback;
        setSelectedNo(wanted);
      })
      .catch((err) => {
        if (!isAbortError(err)) setDetailError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [compId, requestedVersion]);

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

  // Viewing a draft proposal? Load the current published version so the meta
  // and properties can be shown as a diff against it (copper = proposed).
  const currentNo = detail?.current_version_no ?? null;
  const baselineNo =
    version?.status === "draft" && currentNo !== null && currentNo !== version.version_no
      ? currentNo
      : null;

  useEffect(() => {
    if (baselineNo === null) {
      setBaseline(null);
      return;
    }
    const ctrl = new AbortController();
    getVersion(compId, baselineNo, ctrl.signal)
      .then(setBaseline)
      .catch(() => setBaseline(null));
    return () => ctrl.abort();
  }, [compId, baselineNo]);

  const hasCurrent = detail !== null && detail.current_version_no !== null;
  const isCurrentSelected =
    hasCurrent && selectedNo !== null && selectedNo === detail.current_version_no;

  // Component-scoped (not versioned), like the library/BOM-only split: virtual
  // parts stay on the board but drop out of every project BOM total.
  const togglePurchasable = async (next: boolean) => {
    if (detail === null) return;
    setPurchasableBusy(true);
    try {
      const res = await setComponentPurchasable(detail.id, next);
      setDetail({ ...detail, purchasable: res.purchasable });
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Changing the BOM role failed" });
    } finally {
      setPurchasableBusy(false);
    }
  };

  /** Library part vs BOM-only part — the endpoint existed for a year with no
   *  caller anywhere. Turning a part back INTO the library needs a pinned
   *  symbol; the server's 422 explains that, so it is shown verbatim. */
  const toggleInLibrary = async (next: boolean) => {
    if (detail === null) return;
    setPurchasableBusy(true);
    try {
      const res = await setComponentInLibrary(detail.id, next);
      setDetail({ ...detail, in_library: res.in_library });
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Changing the library flag failed" });
    } finally {
      setPurchasableBusy(false);
    }
  };

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

  const selectVersion = async (no: number) => {
    if (no === selectedNo) return;
    if (editing && dirty) {
      const confirmed = await dialog.confirm("Discard unsaved changes?", {
        title: "Unsaved changes",
        confirmLabel: "Discard",
        tone: "danger",
      });
      if (!confirmed) return;
    }
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
      await dialog.alert(errorMessage(err), { title: "Adding the file failed" });
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

  const promptAddFile = async () => {
    const label = await dialog.prompt("Label for the new file:", {
      title: "Add file",
      placeholder: 'e.g. "2D drawing (DXF)" or "Enclosure STEP"',
      confirmLabel: "Choose file…",
    });
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
          <BackLink to={backTo} />
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

  // `detail.review.parts` describes the drawings the CURRENT version pins, so
  // its per-drawing pills may only be shown while the current version is the
  // one on screen. An older version pins older drawings with their own records.
  const showsLiveGeometry = version !== null && version.version_no === detail.current_version_no;

  // Diff mode: a draft is selected and its current published baseline loaded.
  const diff = !editing && baseline !== null && version !== null;
  const propRows: DiffPropRow[] =
    diff && baseline && version
      ? buildPropDiff(version.properties, baseline.properties)
      : version
        ? [...version.properties]
            .sort((a, b) => a.position - b.position)
            .map((p) => ({ key: p.key, draft: p, base: null, status: "same" as const }))
        : [];

  return (
    <div className="detail-page">
      <div className="detail-left">
        <div className="detail-top">
          <BackLink to={backTo} />
          <div className="detail-header">
            <h1 className="mono comp-name">{detail.name}</h1>
            {version ? <StatusPill status={version.status} /> : null}
            <SignoffPill
              state={detail.signoff}
              title="Production sign-off — whether a human has checked this part's symbol and land pattern"
            />
            <ReviewPill
              state={detail.review?.state}
              provenance={detail.review?.provenance}
              title={
                detail.review?.blockers?.length
                  ? `Verification — ${detail.review.blockers.join("; ")}`
                  : "Verification against the documentation (component + pinned symbol/footprint)"
              }
            />
            <LifecycleSelect detail={detail} onChanged={() => {
              getComponent(compId).then(setDetail).catch(() => {});
            }} />
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
            Draft — filed before writes published directly, and never approved. Nothing files
            drafts any more; this version is history.
            {diff ? (
              <>
                {" "}
                Changes from the current v{baselineNo} are{" "}
                <span className="diff-new">highlighted</span> below.
              </>
            ) : null}
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
                    {propRows.map((d) => (
                      <DiffPropertyRow key={d.key} row={d} />
                    ))}
                    {propRows.length === 0 ? (
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
                <DiffMeta
                  changed={diff && baseline?.category_path !== version.category_path}
                  oldText={baseline?.category_path ?? ""}
                >
                  {version.category_path || <span className="null">—</span>}
                </DiffMeta>
              </MetaRow>
              <MetaRow label="Symbol">
                <DiffMeta
                  changed={diff && baseline !== null && symKey(baseline) !== symKey(version)}
                  oldText={baseline ? symKey(baseline) : ""}
                >
                  {version.symbol ? (
                    <PinnedGeometry
                      kind="symbols"
                      pin={version.symbol}
                      review={showsLiveGeometry ? detail.review?.parts?.symbol : undefined}
                    />
                  ) : (
                    // no pinned symbol — the base ref is the only information left
                    <span className="mono">
                      {version.base_component || <span className="null">not pinned</span>}
                      {version.base_component ? <span className="null"> (unresolved)</span> : null}
                    </span>
                  )}
                </DiffMeta>
              </MetaRow>
              <MetaRow label="Footprint">
                <DiffMeta
                  changed={diff && baseline !== null && fpKey(baseline) !== fpKey(version)}
                  oldText={baseline ? fpKey(baseline) : ""}
                >
                  {version.footprint ? (
                    <PinnedGeometry
                      kind="footprints"
                      pin={version.footprint}
                      review={showsLiveGeometry ? detail.review?.parts?.footprint : undefined}
                    />
                  ) : (
                    <span className="null">not pinned</span>
                  )}
                </DiffMeta>
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
              <MetaRow label="BOM role">
                <label className="proj-inline-field proj-check">
                  <input
                    type="checkbox"
                    checked={detail.purchasable}
                    disabled={purchasableBusy}
                    onChange={(e) => void togglePurchasable(e.target.checked)}
                  />
                  purchased part
                </label>
                {detail.purchasable ? null : (
                  <span className="muted">
                    {" "}
                    — virtual (test point, logo, fiducial, mounting hole): project BOMs ignore it
                  </span>
                )}
              </MetaRow>
              <MetaRow label="Library">
                <label className="proj-inline-field proj-check">
                  <input
                    type="checkbox"
                    checked={detail.in_library}
                    disabled={purchasableBusy}
                    onChange={(e) => void toggleInLibrary(e.target.checked)}
                  />
                  visible in KiCad
                </label>
                {detail.in_library ? null : (
                  <span className="muted">
                    {" "}
                    — BOM-only: priced and stocked, but hidden from the KiCad catalog
                  </span>
                )}
              </MetaRow>
              {version.comment ? (
                <MetaRow label="Comment">
                  <FoldedText text={version.comment} />
                </MetaRow>
              ) : null}
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

        {/* The pinned drawings, verifiable HERE. A component is where you
            notice a land pattern is wrong, and the check belongs to the
            footprint — so before this the trail was: open the footprint page,
            verify, navigate back and lose your place. Collapsed to summary
            rows: three fully-mounted cards were two screens tall, and most
            visits only need the pills. Expanding mounts the real ReviewCard. */}
        {version && !editing && isCurrentSelected ? (
          <VerificationSection
            detail={detail}
            version={version}
            onChanged={() => {
              getComponent(compId)
                .then(setDetail)
                .catch(() => {});
            }}
          />
        ) : null}

        {/* Kept apart from the meta card's "Approved by" on purpose: library
            approval and a production check are different claims. */}
        {version && !editing && isCurrentSelected ? (
          <SignoffCard
            componentId={compId}
            reviewState={detail.review?.parts?.component?.state ?? detail.review?.state}
            onChange={() => {
              // Keep the page's own badge in step with the card.
              getComponent(compId)
                .then(setDetail)
                .catch(() => {});
            }}
          />
        ) : null}

        <PriceLadderCard compId={compId} />
        {detail ? <WhereUsedCard compId={compId} name={detail.name} /> : null}

        <CommentsPanel kind="components" id={compId} noun="component" />
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
