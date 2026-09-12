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
 */
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { errorMessage, isAbortError } from "../api";
import { useStickyState } from "../useStickyState";
import { Spinner } from "./Ui";
import Viewer3D from "./Viewer3D";

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
}

export default function GeometryPreview({
  src,
  missingText,
  alt = "Preview",
  className = "",
  style,
  lazy = false,
}: GeometryPreviewProps) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const frame = `preview-fill ${className}`.trim();

  useEffect(() => {
    if (src === null || lazy) return;
    let objectUrl: string | null = null;
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    fetch(src, { signal: ctrl.signal })
      .then(async (res) => {
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
  }, [src, missingText, lazy]);

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
