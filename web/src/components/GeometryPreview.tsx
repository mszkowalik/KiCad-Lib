/** The ONE way a KiCad symbol or footprint is shown in this app.
 *
 *  Every preview — component page, template page, templates list, review
 *  workbench, paste box — goes through `GeometryPreview`. Before it there
 *  were six near-identical `<img>` shells with four different missing/error
 *  stories and THREE different canvas colours (`#1e2125`, `var(--surface-2)`,
 *  and `var(--paper, #fff)` where `--paper` was defined nowhere, so the review
 *  workbench drew light strokes on white). One component, one canvas.
 *
 *  **Why the canvas colour matters.** kicad-cli renders with the dark
 *  Skyline-7S theme: light strokes on a TRANSPARENT background. The viewer's
 *  light/dark preference is never passed to the renderer, so the picture is
 *  dark-theme output in both themes and the frame has to supply the matching
 *  dark ground itself. That ground is `--kicad-canvas` in `styles.css`, and it
 *  must stay equal to `schematic.background` in
 *  `api/app/services/themes/Skyline-7S.json`.
 *
 *  **Two loading strategies, on purpose.** A single large preview `fetch`es,
 *  so a 404 can carry the server's own explanation ("no published version")
 *  instead of a broken-image icon. A list of miniatures cannot: one fetch per
 *  row loads every render at once and defeats the point of `loading="lazy"`,
 *  so `lazy` switches to a plain `<img>` that falls back to a placeholder on
 *  error. Pass `lazy` when the preview is one of many.
 *
 *  **A multi-unit symbol is paged, not tiled.** `kicad-cli sym export svg`
 *  plots one file per unit and the platform drew whichever sorted first, so a
 *  dual op-amp looked single and a 10-bank STM32 showed one bank with nothing
 *  on screen admitting the rest existed. The server now takes `?unit=N` and
 *  answers with `X-Unit-Count`; this component reads that header and draws the
 *  ‹ A · 1/10 › control. No call site passes anything — the count is a fact
 *  about the drawing, and only the renderer knows it.
 */
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { API_URL, errorMessage, isAbortError } from "../api";
import { useStickyState } from "../useStickyState";
import { Spinner } from "./Ui";
import Viewer3D from "./Viewer3D";

/** KiCad's own unit suffix: 1 -> A, 26 -> Z, 27 -> AA. Mirrors
 *  `api/app/services/svg_units.py::unit_letter`. */
function unitLetter(unit: number): string {
  let out = "";
  for (let n = unit; n > 0; n = Math.floor((n - 1) / 26)) {
    out = String.fromCharCode(65 + ((n - 1) % 26)) + out;
  }
  return out || "A";
}

/** `?unit=` is added only past the first, so a single-unit symbol and every
 *  footprint keep the URL they have always had — and with it their place in
 *  the browser cache and the server's `immutable` promise. */
export function unitUrl(src: string, unit: number): string {
  if (unit <= 1) return src;
  return `${src}${src.includes("?") ? "&" : "?"}unit=${unit}`;
}

/** The ‹ A · 1/10 › pager. ONE control for every view of a multi-unit symbol —
 *  the preview here and the before/after panes in `GeometryDiff` — so the two
 *  cannot drift on what a unit is called or how far it can be stepped. Renders
 *  nothing at all below two units, which is most of the library.
 *
 *  `className` places it: the preview floats it over the drawing
 *  (`unit-nav-float`), the diff sits it in the flow under the panes. */
export function UnitPager({
  unit,
  count,
  onChange,
  className = "",
}: {
  unit: number;
  count: number;
  onChange: (unit: number) => void;
  className?: string;
}) {
  if (count <= 1) return null;
  const step = (by: number) => onChange(Math.min(Math.max(unit + by, 1), count));
  return (
    <div className={`seg unit-nav ${className}`.trim()} role="group" aria-label="Symbol unit">
      <button type="button" onClick={() => step(-1)} disabled={unit <= 1} aria-label="Previous unit">
        ‹
      </button>
      {/* The letter is the half that is usable: KiCad prints the unit after
          the reference — U7A, U7B — so it is what you look for on a sheet.
          The fraction says how much of the part is off screen. */}
      <span className="unit-nav-label">
        {unitLetter(unit)} · {unit}/{count}
      </span>
      <button type="button" onClick={() => step(1)} disabled={unit >= count} aria-label="Next unit">
        ›
      </button>
    </div>
  );
}

interface UnitNav {
  /** The `src` these numbers describe — see the `nav` state. */
  src: string | null;
  unit: number;
  count: number;
}

type State =
  | { kind: "loading" }
  | { kind: "ok"; src: string }
  | { kind: "missing"; message: string }
  | { kind: "error"; message: string };

export interface GeometryPreviewProps {
  /** The SVG endpoint. `null` means there is nothing pinned or published —
   *  the placeholder is shown and no request is made. */
  src: string | null;
  /** What to say when there is nothing to draw. The server's own 404 detail
   *  wins over this when it sends one. */
  missingText: string;
  alt?: string;
  /** Sizing only. The canvas, border and radius belong to `.preview-fill`;
   *  callers add the box (`template-preview`, `workbench-preview`, …). */
  className?: string;
  style?: CSSProperties;
  /** One of many — use a lazy `<img>` rather than a fetch. See the header. */
  lazy?: boolean;
  /** CONTROLLED unit paging, for a caller that produced the SVG itself. The
   *  paste box POSTs unsaved text and hands over a `blob:` URL, and a blob
   *  carries no response headers — so it has no `X-Unit-Count` to read and
   *  must be told. Omit all three and the component learns the count from its
   *  own response, which is what every other call site does. */
  unitCount?: number;
  unit?: number;
  onUnitChange?: (unit: number) => void;
}

export default function GeometryPreview({
  src,
  missingText,
  alt = "Preview",
  className = "",
  style,
  lazy = false,
  unitCount: controlledCount,
  unit: controlledUnit,
  onUnitChange,
}: GeometryPreviewProps) {
  const [state, setState] = useState<State>({ kind: "loading" });
  // Which unit is on screen, and how many there are — tagged with the `src`
  // they were learned from, so pointing the component at another drawing
  // resets to unit 1 without an effect that would fetch the old unit first.
  const [nav, setNav] = useState<UnitNav>({ src, unit: 1, count: 1 });
  const controlled = onUnitChange !== undefined;
  const unit = controlled ? (controlledUnit ?? 1) : nav.src === src ? nav.unit : 1;
  const unitCount = controlled ? (controlledCount ?? 1) : nav.src === src ? nav.count : 1;
  const frame = `preview-fill ${className}`.trim();

  useEffect(() => {
    if (src === null || lazy) return;
    let objectUrl: string | null = null;
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    // `include`, not the `same-origin` default, for the reason `api.ts` gives:
    // dev runs the SPA on :5173 and the API on :8020, so every preview request
    // is cross-origin and the session cookie is left behind. The API is
    // default-deny, so the panel answered 401 and drew its error story instead
    // of the symbol.
    // A controlled caller owns the URL and the count: its `src` is already the
    // unit it asked for, so neither the query nor the header applies.
    fetch(controlled ? src : unitUrl(src, unit), { credentials: "include", signal: ctrl.signal })
      .then(async (res) => {
        // Sent on every symbol render (routers/libraries.py::_svg_response)
        // and exposed through CORS in main.py. Absent on a footprint, and
        // absent on an error response — either way the part has one unit.
        const count = Number(res.headers.get("X-Unit-Count") ?? "1");
        if (!controlled) {
          setNav({ src, unit, count: Number.isFinite(count) && count > 0 ? count : 1 });
        }
        if (res.status === 404) {
          // The endpoints answer 404 with a sentence worth showing — "this
          // version pins no footprint", "no published version". Prefer it.
          let detail = "";
          try {
            const body = (await res.json()) as { detail?: unknown };
            if (typeof body.detail === "string") detail = body.detail;
          } catch {
            // ignore a non-JSON body
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
  }, [src, missingText, lazy, unit, controlled]);

  if (src === null) {
    return (
      <div className={frame} style={style}>
        <span className="placeholder">{missingText}</span>
      </div>
    );
  }

  if (lazy) {
    return (
      <div className={frame} style={style}>
        {state.kind === "missing" ? (
          <span className="placeholder">{state.message}</span>
        ) : (
          <img
            src={src}
            alt={alt}
            loading="lazy"
            // A cross-origin <img> carries NO cookie, not even a SameSite=lax
            // one, so under a dev server aimed at the API's own origin every
            // thumbnail came back 401 and drew the placeholder. This attribute
            // is what makes the browser attach the session; the API answers
            // with an explicit origin and allow_credentials (main.py), which is
            // what a credentialed image load requires. Only when the API is on
            // another origin — deployed, API_URL is "" and the request is
            // same-origin, where the attribute would buy nothing.
            crossOrigin={API_URL ? "use-credentials" : undefined}
            onError={() => setState({ kind: "missing", message: missingText })}
          />
        )}
      </div>
    );
  }

  let body;
  if (state.kind === "loading") body = <Spinner label="Rendering…" />;
  else if (state.kind === "ok") body = <img src={state.src} alt={alt} />;
  else if (state.kind === "missing") body = <span className="placeholder">{state.message}</span>;
  else body = <span className="placeholder err-text">{state.message}</span>;

  return (
    <div className={frame} style={style}>
      {body}
      <UnitPager
        unit={unit}
        count={unitCount}
        className="unit-nav-float"
        onChange={(next) =>
          controlled ? onUnitChange(next) : setNav({ src, count: unitCount, unit: next })
        }
      />
    </div>
  );
}

/** A footprint, with the 2D/3D switch that goes with one.
 *
 *  The switch, the `Viewer3D` swap and the "a symbol has no board" rule were
 *  written twice — once on the component page, once on the template page —
 *  and they had already drifted apart in which state they remembered. The two
 *  call sites differ only in WHICH endpoint addresses the drawing: a component
 *  version that pins a footprint, or the footprint template itself. Pass the
 *  two URLs; `glbUrl === null` means there is no board to render and the
 *  switch is not drawn.
 */
export function FootprintPreview({
  title,
  svgUrl,
  glbUrl,
  missingText,
  stickyKey,
  className = "",
  extra,
}: {
  /** The card's own heading, drawn beside the switch. */
  title: ReactNode;
  svgUrl: string | null;
  glbUrl: string | null;
  missingText: string;
  /** Where the 2D/3D choice is remembered (`useStickyState` key). */
  stickyKey: string;
  className?: string;
  /** Shown under the 3D view only — the component page's model-file links. */
  extra?: ReactNode;
}) {
  const [mode, setMode] = useStickyState<"2d" | "3d">(stickyKey, "2d");
  const show3d = glbUrl !== null && mode === "3d";

  return (
    <>
      <div className="panel-head">
        {title}
        {glbUrl !== null ? (
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
        ) : null}
      </div>
      {show3d ? (
        <>
          <Viewer3D src={glbUrl} missingText={missingText} className={className} />
          {extra}
        </>
      ) : (
        <GeometryPreview src={svgUrl} missingText={missingText} alt="Footprint" className={className} />
      )}
    </>
  );
}
