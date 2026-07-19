/** Production files of a run: versioned sets (repo import / upload /
 *  kicad-cli generated), JLC assembly info from bom.csv, and a gerber
 *  viewer (server-side gerbv composite of selected layers). */
import { useEffect, useMemo, useState } from "react";
import {
  deleteProductionSet,
  errorMessage,
  generateProductionFab,
  getRunProduction,
  importProductionFromRepo,
  isAbortError,
  productionFileUrl,
  renderGerbers,
  uploadProductionFiles,
  type ProductionInfo,
  type ProductionSet,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";

/** Layer colors matching the KiCad-default board palette, by filename. */
const GERBER_COLOR_RULES: [RegExp, string][] = [
  [/f[_-]?cu|\.gtl$/i, "#c83434"],
  [/b[_-]?cu|\.gbl$/i, "#4d7fc4"],
  [/in1|\.g2$/i, "#7fc87f"],
  [/in2|\.g3$/i, "#ce7d2c"],
  [/f[_-]?silk|\.gto$/i, "#f3eded"],
  [/b[_-]?silk|\.gbo$/i, "#e8b2a7"],
  [/f[_-]?mask|\.gts$/i, "#9b26d5"],
  [/b[_-]?mask|\.gbs$/i, "#02fff8"],
  [/f[_-]?paste|\.gtp$/i, "#a4a4a4"],
  [/b[_-]?paste|\.gbp$/i, "#00b3b3"],
  [/edge|\.gm1$/i, "#d0d2cd"],
  [/\.drl$|\.xln$/i, "#e0e0e0"],
];

function layerColor(filename: string): string {
  for (const [re, color] of GERBER_COLOR_RULES) {
    if (re.test(filename)) return color;
  }
  return "#c2c2c2";
}

const DEFAULT_VISIBLE = [/f[_-]?cu|\.gtl$/i, /f[_-]?silk|\.gto$/i, /edge|\.gm1$/i];

export default function ProductionPanel({ runId }: { runId: number }) {
  const [info, setInfo] = useState<ProductionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showJlcBom, setShowJlcBom] = useState(false);
  const [viewSetId, setViewSetId] = useState<number | null>(null);
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [gerberUrl, setGerberUrl] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);

  const load = (signal?: AbortSignal) => {
    getRunProduction(runId, signal)
      .then((i) => {
        setInfo(i);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  };

  useEffect(() => {
    const ctrl = new AbortController();
    setInfo(null);
    setViewSetId(null);
    setGerberUrl(null);
    load(ctrl.signal);
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const currentSet: ProductionSet | null = info?.sets[0] ?? null;
  const viewSet = info?.sets.find((s) => s.id === viewSetId) ?? currentSet;
  const gerberFiles = useMemo(
    () => (viewSet?.files ?? []).filter((f) => f.kind === "gerber" || f.kind === "drill"),
    [viewSet],
  );

  useEffect(() => {
    setSelection(
      new Set(
        gerberFiles
          .filter((f) => DEFAULT_VISIBLE.some((re) => re.test(f.filename)))
          .map((f) => f.filename),
      ),
    );
    setGerberUrl(null);
  }, [gerberFiles]);

  const act = (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    fn()
      .then(() => {
        setBusy(null);
        load();
      })
      .catch((err) => {
        setError(errorMessage(err));
        setBusy(null);
      });
  };

  const renderView = () => {
    if (!viewSet) return;
    const files = gerberFiles
      .filter((f) => selection.has(f.filename))
      .map((f) => ({ file: f.filename, color: layerColor(f.filename) }));
    if (files.length === 0) return;
    setRendering(true);
    renderGerbers(viewSet.id, files)
      .then((url) => {
        setGerberUrl((old) => {
          if (old) URL.revokeObjectURL(old);
          return url;
        });
        setRendering(false);
      })
      .catch((err) => {
        setError(errorMessage(err));
        setRendering(false);
      });
  };

  if (info === null && !error) return <Spinner label="Loading production files" />;

  return (
    <div>
      <div className="card-subtitle">Production files (sent to JLCPCB)</div>
      {error ? <ErrorBanner message={error} /> : null}

      <div className="btn-row">
        {info?.repo_available ? (
          <button className="btn btn-sm" disabled={busy !== null}
            onClick={() => act("repo", () => importProductionFromRepo(runId))}>
            {busy === "repo" ? "Importing…" : "Re-import repo production/"}
          </button>
        ) : null}
        <label className="btn btn-sm">
          {busy === "upload" ? "Uploading…" : "Upload files…"}
          <input type="file" multiple hidden
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              if (files.length) act("upload", () => uploadProductionFiles(runId, files));
              e.target.value = "";
            }} />
        </label>
        <button className="btn btn-sm" disabled={busy !== null}
          title="kicad-cli gerbers/drill/position bundle"
          onClick={() => act("gen", () => generateProductionFab(runId))}>
          {busy === "gen" ? "Generating…" : "Generate with kicad-cli"}
        </button>
      </div>

      {info && info.sets.length === 0 ? (
        <div className="banner-warn">
          No production files yet.{" "}
          {info.repo_available
            ? "The repo has a production/ directory — use Re-import."
            : "The repo has no production/ directory at this snapshot — upload the JLCPCB exporter output or generate a kicad-cli bundle."}
        </div>
      ) : null}

      {info && info.sets.length > 0 ? (
        <>
          <table className="data">
            <thead>
              <tr>
                <th>Version</th>
                <th>Source</th>
                <th>Comment</th>
                <th>Added</th>
                <th className="num">Files</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {info.sets.map((s) => (
                <tr key={s.id} className={viewSet?.id === s.id ? "row-selected" : ""}>
                  <td className="mono">
                    v{s.version_no}
                    {s.id === info.sets[0].id ? <span className="pill ok">current</span> : null}
                  </td>
                  <td>{s.source}</td>
                  <td className="muted">{s.comment}</td>
                  <td className="muted">{new Date(s.created_at).toLocaleString()}</td>
                  <td className="num">{s.files.filter((f) => !f.extracted).length}</td>
                  <td className="nowrap">
                    <button className="btn btn-sm" onClick={() => setViewSetId(s.id)}>
                      View
                    </button>{" "}
                    <button className="btn btn-sm btn-danger"
                      onClick={() => {
                        if (window.confirm(`Delete production set v${s.version_no}?`)) {
                          act("del", () => deleteProductionSet(s.id));
                        }
                      }}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {viewSet ? (
            <>
              <div className="card-subtitle">Files in v{viewSet.version_no}</div>
              <ul className="model-files">
                {viewSet.files.filter((f) => !f.extracted).map((f) => (
                  <li key={f.id}>
                    <a href={productionFileUrl(f.id)}>{f.filename}</a>{" "}
                    <span className="pill neutral">{f.kind.replace("_", " ")}</span>{" "}
                    <span className="muted">{(f.size_bytes / 1024).toFixed(1)} kB</span>
                  </li>
                ))}
              </ul>

              {info.jlc_bom ? (
                <>
                  <div className="banner-ok">
                    JLCPCB assembles {info.jlc_designators.length} placement(s) across{" "}
                    {info.jlc_bom.rows.length} part(s) — this is the assembly subset, not the
                    total BOM.{" "}
                    <button className="btn btn-sm" onClick={() => setShowJlcBom((v) => !v)}>
                      {showJlcBom ? "Hide" : "Show"} JLC BOM
                    </button>
                  </div>
                  {showJlcBom ? (
                    <div className="table-wrap">
                      <table className="data">
                        <thead>
                          <tr>
                            <th>Comment</th>
                            <th>Designators</th>
                            <th>Footprint</th>
                            <th>LCSC</th>
                          </tr>
                        </thead>
                        <tbody>
                          {info.jlc_bom.rows.map((r, i) => (
                            <tr key={i}>
                              <td>{r.comment}</td>
                              <td className="mono cell-fp">{r.designators.join(", ")}</td>
                              <td className="muted">{r.footprint}</td>
                              <td className="mono">{r.lcsc || "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </>
              ) : null}

              {gerberFiles.length > 0 ? (
                <>
                  <div className="card-subtitle">Gerber viewer</div>
                  <div className="board-2d-grid">
                    <div className="card pad layer-list">
                      {gerberFiles.map((f) => (
                        <label key={f.id} className="layer-row">
                          <input type="checkbox" checked={selection.has(f.filename)}
                            onChange={() =>
                              setSelection((prev) => {
                                const next = new Set(prev);
                                if (next.has(f.filename)) next.delete(f.filename);
                                else next.add(f.filename);
                                return next;
                              })
                            } />
                          <span className="layer-swatch" style={{ background: layerColor(f.filename) }} />
                          <span className="mono cell-fp" title={f.filename}>{f.filename}</span>
                        </label>
                      ))}
                      <div className="btn-row">
                        <button className="btn btn-sm btn-primary" disabled={rendering || selection.size === 0}
                          onClick={renderView}>
                          {rendering ? "Rendering…" : "Render"}
                        </button>
                      </div>
                    </div>
                    <div className="card boardview">
                      {gerberUrl ? (
                        <img src={gerberUrl} alt="Gerber composite" className="gerber-img" />
                      ) : (
                        <p className="muted pad">
                          Select layers and press Render — gerbv composites them server-side.
                        </p>
                      )}
                    </div>
                  </div>
                </>
              ) : null}
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
