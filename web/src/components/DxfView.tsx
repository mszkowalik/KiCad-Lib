/** DXF viewer (dxf-viewer package, three.js-based) with a layer panel —
 *  checkboxes toggle per-layer visibility. Also renders server-converted DWG
 *  (the /api/view/dwg2dxf endpoint returns plain DXF).
 *
 *  Text entities need real font outlines; Roboto is shipped in
 *  public/fonts/ (parse-verified against the bundled opentype.js). */
import { useEffect, useRef, useState } from "react";
import { DxfViewer, type LayerInfo } from "dxf-viewer";
import * as THREE from "three";

const FONT_URLS = ["/fonts/Roboto-Regular.ttf"];
const CANVAS_BG = new THREE.Color(0x1e2125); // matches the 3D board viewer

export default function DxfView({ url }: { url: string }) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<DxfViewer | null>(null);
  const [layers, setLayers] = useState<LayerInfo[]>([]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let disposed = false;
    const viewer = new DxfViewer(mount, {
      autoResize: true,
      clearColor: CANVAS_BG,
      colorCorrection: true,
      antialias: true,
    });
    viewerRef.current = viewer;
    setStatus("loading");
    setLayers([]);
    setHidden(new Set());

    viewer
      .Load({ url, fonts: FONT_URLS })
      .then(() => {
        if (disposed) return;
        setLayers(Array.from(viewer.GetLayers()));
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (disposed) return;
        setMessage(err instanceof Error ? err.message : String(err));
        setStatus("error");
      });

    return () => {
      disposed = true;
      viewerRef.current = null;
      viewer.Destroy();
    };
  }, [url]);

  const toggle = (name: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      viewerRef.current?.ShowLayer(name, !next.has(name));
      return next;
    });
  };

  return (
    <div className="meshview">
      <div ref={mountRef} className="meshview-canvas dxf-canvas">
        {status === "loading" ? (
          <span className="meshview-status">Loading drawing…</span>
        ) : status === "error" ? (
          <span className="meshview-status err-text">{message}</span>
        ) : null}
      </div>
      {status === "ready" && layers.length > 0 ? (
        <aside className="meshview-side">
          <h3>Layers</h3>
          <ul>
            {layers.map((layer) => (
              <li key={layer.name}>
                <label className="meshview-item" title={layer.displayName}>
                  <input
                    type="checkbox"
                    checked={!hidden.has(layer.name)}
                    onChange={() => toggle(layer.name)}
                  />
                  <span
                    className="layer-swatch"
                    style={{
                      backgroundColor: `#${layer.color.toString(16).padStart(6, "0")}`,
                    }}
                  />
                  <span>{layer.displayName || layer.name}</span>
                </label>
              </li>
            ))}
          </ul>
        </aside>
      ) : null}
    </div>
  );
}
