import { Suspense, lazy, useEffect, useState } from "react";

import { errorMessage, isAbortError } from "../api";
import { Spinner } from "./Ui";

/** Lazy: pulls in the model-viewer/three.js chunk only when 3D is opened. */
const ModelViewer = lazy(() => import("./ModelViewer"));

/** GLB board view via Google's `<model-viewer>`: the API renders a footprint
 *  with copper, mask and silkscreen on a board slab plus the placed 3D model
 *  (kicad-cli). model-viewer's neutral studio lighting is bright and it
 *  auto-frames the model with managed near/far planes, so orbiting never clips.
 *  The first server render takes a few seconds; it is cached after that.
 *
 *  It takes a URL rather than an entity, because the same board view is
 *  reachable two ways: through a COMPONENT version (which pins a footprint
 *  version) and directly from the footprint template. Those are different
 *  endpoints and the viewer has no business knowing which one it was given. */

type State =
  | { kind: "loading" }
  | { kind: "ready"; src: string }
  | { kind: "missing"; message: string }
  | { kind: "error"; message: string };

export default function Viewer3D({
  src,
  missingText,
  className = "",
}: {
  src: string;
  missingText: string;
  /** Extra classes for the frame. `.preview-fill` is `flex: 1`, so it only has
   *  a height when its parent gives it one — the component page's preview
   *  panel does, a plain card does not, and the viewer collapsed to nothing
   *  there. The template page passes `template-preview` for its 360px box. */
  className?: string;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let objectUrl: string | null = null;
    const ctrl = new AbortController();
    setState({ kind: "loading" });

    (async () => {
      try {
        // Fetched here rather than handed to <model-viewer> as a URL: that is
        // what gives a clean 404 (nothing pinned) and a spinner during the slow
        // first server render, instead of a silently empty canvas.
        const res = await fetch(src, { credentials: "include", signal: ctrl.signal });
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
          setState({ kind: "error", message: `Board view failed (HTTP ${res.status})` });
          return;
        }
        const blob = await res.blob();
        objectUrl = URL.createObjectURL(blob);
        setState({ kind: "ready", src: objectUrl });
      } catch (err) {
        if (!isAbortError(err)) setState({ kind: "error", message: errorMessage(err) });
      }
    })();

    return () => {
      ctrl.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src, missingText]);

  return (
    <div className={`preview-fill viewer3d-wrap ${className}`.trim()}>
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
          {state.kind === "missing" ? <span className="placeholder">{state.message}</span> : null}
          {state.kind === "error" ? (
            <span className="placeholder err-text">{state.message}</span>
          ) : null}
        </div>
      )}
    </div>
  );
}
