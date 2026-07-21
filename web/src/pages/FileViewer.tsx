/** /view?src=<same-origin path>&name=<filename> — in-browser file viewer.
 *
 *  Dispatch by extension:
 *    step/iges  → occt-import-js wasm → three.js (structure tree w/ toggles)
 *    3mf, wrl   → three.js loaders    (structure tree w/ toggles)
 *    dxf        → dxf-viewer          (layer panel w/ toggles)
 *    dwg        → server dwg2dxf (LibreDWG) → dxf-viewer; graceful fallback
 *    glb/gltf   → <model-viewer>
 *    image      → <img>; pdf → <iframe> (normally PDFs link directly)
 *    anything else → download card
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  dwgToDxfUrl,
  errorMessage,
  getViewerCapabilities,
  isAbortError,
} from "../api";
import { Spinner } from "../components/Ui";
import { absoluteFileUrl, viewKindOf } from "../viewkind";

const MeshView = lazy(() => import("../components/MeshView"));
const DxfView = lazy(() => import("../components/DxfView"));
const ModelViewer = lazy(() => import("../components/ModelViewer"));

function DwgPane({ srcPath }: { srcPath: string }) {
  const [canConvert, setCanConvert] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getViewerCapabilities(ctrl.signal)
      .then((caps) => setCanConvert(caps.dwg_convert))
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, []);

  if (error !== null) return <div className="viewer-note err-text">{error}</div>;
  if (canConvert === null) return <Spinner label="Checking DWG support" />;
  if (!canConvert) {
    return (
      <div className="viewer-note">
        <p>
          DWG preview needs the server-side LibreDWG converter, which isn't installed. Install it
          with <code>brew install libredwg</code> (macOS) — the Docker image builds it in — then
          reload this page.
        </p>
        <a className="btn" href={absoluteFileUrl(srcPath)} download>
          Download the DWG instead
        </a>
      </div>
    );
  }
  return <DxfView url={dwgToDxfUrl(srcPath)} />;
}

export default function FileViewer() {
  const [params] = useSearchParams();
  const src = params.get("src") ?? "";
  const name = params.get("name") ?? (src.split("/").pop() || "file");
  const kind = viewKindOf(name);
  const fullUrl = absoluteFileUrl(src);

  let body;
  if (!src) {
    body = <div className="viewer-note err-text">No file given — missing ?src= parameter.</div>;
  } else if (kind === "step" || kind === "iges" || kind === "3mf" || kind === "wrl") {
    body = <MeshView url={fullUrl} format={kind} />;
  } else if (kind === "dxf") {
    body = <DxfView url={fullUrl} />;
  } else if (kind === "dwg") {
    body = <DwgPane srcPath={src} />;
  } else if (kind === "glb") {
    body = (
      <div className="viewer-glb">
        <ModelViewer src={fullUrl} />
      </div>
    );
  } else if (kind === "image") {
    body = <img className="viewer-img" src={fullUrl} alt={name} />;
  } else if (kind === "pdf") {
    body = <iframe className="viewer-pdf" src={fullUrl} title={name} />;
  } else {
    body = (
      <div className="viewer-note">
        <p>
          No in-browser preview for <span className="mono">{name}</span>.
        </p>
        <a className="btn" href={fullUrl} download>
          Download
        </a>
      </div>
    );
  }

  return (
    <div className="main-solo">
      <div className="page viewer-page">
        <div className="viewer-head">
          <h1 className="mono" title={name}>
            {name}
          </h1>
          {src ? (
            <a className="btn btn-sm" href={fullUrl} download={name}>
              Download
            </a>
          ) : null}
        </div>
        <div className="card viewer-body">
          <Suspense
            fallback={
              <div className="viewer-note">
                <Spinner label="Loading viewer…" />
              </div>
            }
          >
            {body}
          </Suspense>
        </div>
      </div>
    </div>
  );
}
