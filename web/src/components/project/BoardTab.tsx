/** Board views: stacked per-layer SVGs with visibility toggles (2D, with
 *  clickable footprints from the snapshot's click-map), GLB in
 *  <model-viewer> (3D), STEP download, ERC/DRC counts. Production files
 *  (gerbers etc.) live with production runs — see the Runs tab. */
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import {
  boardGlbUrl,
  boardStepUrl,
  boardLayerSvgUrl,
  errorMessage,
  getBoardChecks,
  getBoardMap,
  isAbortError,
  type BoardChecks,
  type BoardMap,
  type MapSymbol,
  type SnapshotBoard,
  type SnapshotInfo,
} from "../../api";
import { Spinner } from "../Ui";
import PartInfo from "./PartInfo";

const ModelViewer = lazy(() => import("../ModelViewer"));

/** KiCad default (dark) theme layer colors — swatches only, so the toggle
 *  list matches what the rendered SVGs actually look like. */
const LAYER_COLORS: Record<string, string> = {
  "F.Cu": "#c83434", "B.Cu": "#4d7fc4", "In1.Cu": "#7fc87f", "In2.Cu": "#ce7d2c",
  "In3.Cu": "#dfcd15", "In4.Cu": "#a7a7a7", "F.SilkS": "#f3eded", "B.SilkS": "#e8b2a7",
  "F.Mask": "#9b26d5", "B.Mask": "#02fff8", "F.Paste": "#a4a4a4", "B.Paste": "#00b3b3",
  "Edge.Cuts": "#d0d2cd", "F.Fab": "#afafaf", "B.Fab": "#585d84",
  "F.CrtYd": "#d3d04b", "B.CrtYd": "#26e9e9", "Dwgs.User": "#c2c2c2", "Cmts.User": "#7f7f7f",
};

const DEFAULT_VISIBLE = new Set(["F.Cu", "B.Cu", "F.SilkS", "Edge.Cuts"]);

interface Props {
  snapshot: SnapshotInfo;
  board: SnapshotBoard;
}

export default function BoardTab({ snapshot, board }: Props) {
  const [mode, setMode] = useState<"2d" | "3d">("2d");
  const layers = useMemo(() => board.layers ?? [], [board]);
  const [visible, setVisible] = useState<Set<string>>(
    () => new Set(layers.filter((l) => DEFAULT_VISIBLE.has(l.name)).map((l) => l.name)),
  );
  const [zoom, setZoom] = useState(100);
  const [checks, setChecks] = useState<BoardChecks | null>(null);
  const [checksError, setChecksError] = useState<string | null>(null);
  const [checksLoading, setChecksLoading] = useState(false);
  const [map, setMap] = useState<BoardMap | null>(null);
  const [clickParts, setClickParts] = useState(true);
  const [selected, setSelected] = useState<MapSymbol | null>(null);

  useEffect(() => {
    setVisible(new Set(layers.filter((l) => DEFAULT_VISIBLE.has(l.name)).map((l) => l.name)));
    setChecks(null);
    setChecksError(null);
    setSelected(null);
    const ctrl = new AbortController();
    getBoardMap(snapshot.id, board.name, ctrl.signal)
      .then(setMap)
      .catch(() => setMap(null)); // hotspots are an enhancement, never block
    return () => ctrl.abort();
  }, [snapshot.id, board.name, layers]);

  const toggle = (name: string) => {
    setVisible((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const loadChecks = () => {
    setChecksLoading(true);
    getBoardChecks(snapshot.id, board.name)
      .then((c) => {
        setChecks(c);
        setChecksLoading(false);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setChecksError(errorMessage(err));
        setChecksLoading(false);
      });
  };

  const violationCount = (report: Record<string, unknown> | null): string => {
    if (!report) return "n/a";
    if ("error" in report) return "failed";
    const direct = (report.violations as unknown[] | undefined)?.length;
    if (direct != null) return String(direct);
    const sheets = report.sheets as { violations?: unknown[] }[] | undefined;
    if (sheets) return String(sheets.reduce((n, s) => n + (s.violations?.length ?? 0), 0));
    return "?";
  };

  if (!board.pcb) {
    return <p className="muted">This board has no .kicad_pcb file.</p>;
  }

  // Ordered bottom-to-top so front layers draw over back layers.
  const stackOrder = [...layers]
    .filter((l) => visible.has(l.name))
    .sort((a, b) => {
      const rank = (n: string) =>
        n === "Edge.Cuts" ? 100 : n.startsWith("F.") ? 50 : n.startsWith("In") ? 20 : 10;
      return rank(a.name) - rank(b.name);
    });

  const pcbMap = map?.pcb ?? null;
  const pct = (v: number, axis: 0 | 1) =>
    pcbMap ? `${((v - pcbMap.origin[axis]) / pcbMap.size[axis]) * 100}%` : "0%";

  return (
    <div>
      <div className="toolbar">
        <div className="seg" role="group" aria-label="Board view mode">
          <button type="button" className={mode === "2d" ? "on" : ""} onClick={() => setMode("2d")}>
            2D layers
          </button>
          <button type="button" className={mode === "3d" ? "on" : ""} onClick={() => setMode("3d")}>
            3D
          </button>
        </div>
        {mode === "2d" ? (
          <>
            <label className="proj-inline-field">
              Zoom
              <input
                type="range"
                min={25}
                max={400}
                value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))}
              />
              <span className="mono">{zoom}%</span>
            </label>
            <label className="proj-inline-field proj-check">
              <input
                type="checkbox"
                checked={clickParts}
                onChange={(e) => setClickParts(e.target.checked)}
                disabled={!pcbMap}
              />
              click parts
            </label>
          </>
        ) : null}
        <span className="toolbar-total" />
        <a className="btn btn-sm" href={boardStepUrl(snapshot.id, board.name)}>
          STEP
        </a>
        <button className="btn btn-sm" disabled={checksLoading} onClick={loadChecks}>
          {checksLoading ? "Running…" : "ERC / DRC"}
        </button>
      </div>

      {checksError ? <div className="banner-error">{checksError}</div> : null}
      {checks ? (
        <div className="counts counts-sm">
          <div className="count-tile">
            <div className="v">{violationCount(checks.erc)}</div>
            <div className="muted">ERC violations</div>
          </div>
          <div className="count-tile">
            <div className="v">{violationCount(checks.drc)}</div>
            <div className="muted">DRC violations</div>
          </div>
        </div>
      ) : null}

      {selected ? <PartInfo part={selected} onClose={() => setSelected(null)} /> : null}

      {mode === "3d" ? (
        <div className="card boardview-3d">
          <Suspense fallback={<Spinner label="Loading 3D viewer" />}>
            <ModelViewer src={boardGlbUrl(snapshot.id, board.name)} />
          </Suspense>
        </div>
      ) : (
        <div className="board-2d-grid">
          <div className="card pad layer-list">
            <div className="card-title">Layers</div>
            {layers.map((l) => (
              <label key={l.name} className="layer-row">
                <input
                  type="checkbox"
                  checked={visible.has(l.name)}
                  onChange={() => toggle(l.name)}
                />
                <span
                  className="layer-swatch"
                  style={{ background: LAYER_COLORS[l.name] ?? "var(--muted)" }}
                />
                <span className="mono">{l.name}</span>
                {l.user_name ? <span className="muted">{l.user_name}</span> : null}
              </label>
            ))}
            <div className="btn-row">
              <button
                className="btn btn-sm"
                onClick={() => setVisible(new Set(layers.map((l) => l.name)))}
              >
                All
              </button>
              <button className="btn btn-sm" onClick={() => setVisible(new Set())}>
                None
              </button>
            </div>
          </div>
          <div className="card boardview">
            <div className="layerstack" style={{ width: `${zoom}%` }}>
              {stackOrder.length === 0 ? (
                <p className="muted pad">No layers selected.</p>
              ) : (
                <>
                  {stackOrder.map((l, i) => (
                    <img
                      key={l.name}
                      src={boardLayerSvgUrl(snapshot.id, board.name, l.name)}
                      alt={i === 0 ? `Board layers: ${stackOrder.map((s) => s.name).join(", ")}` : ""}
                      className={i === 0 ? "layer-base" : "layer-overlay"}
                      loading="lazy"
                    />
                  ))}
                  {clickParts && pcbMap
                    ? pcbMap.footprints.map((fp) => (
                        <button
                          key={fp.ref}
                          type="button"
                          className={`hotspot${selected?.ref === fp.ref ? " on" : ""}`}
                          title={`${fp.ref} — ${fp.bom?.value || fp.value}${fp.side === "B" ? " (bottom)" : ""}`}
                          style={{
                            left: pct(fp.bbox[0], 0),
                            top: pct(fp.bbox[1], 1),
                            width: `${((fp.bbox[2] - fp.bbox[0]) / pcbMap.size[0]) * 100}%`,
                            height: `${((fp.bbox[3] - fp.bbox[1]) / pcbMap.size[1]) * 100}%`,
                          }}
                          onClick={() => setSelected(fp)}
                        />
                      ))
                    : null}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
