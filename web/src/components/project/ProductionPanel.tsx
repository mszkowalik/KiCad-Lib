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
  productionFileUrl,
  renderGerbers,
  uploadProductionFiles,
  type CplCheck,
  type ProductionSet,
} from "../../api";
import { Link } from "react-router-dom";
import DataTable from "../DataTable";
import { useDialog } from "../Dialog";
import FilePick from "../FilePick";
import { fmtBytes } from "../flasher/common";
import FoldSection, { StatChip } from "../FoldSection";
import { ErrorBanner, Spinner } from "../Ui";
import { LAYER_COLORS } from "./BoardTab";
import { localWhen } from "../../format";
import { useLoad } from "../useLoad";

/** The CPL against the per-part JLC rotation (decision 0110). A check that
 *  passes draws nothing; a wrong rotation links to the part whose
 *  `FT Rotation Offset` says what JLC needs. */
function CplCheckCard({ runId, check }: { runId: number; check: CplCheck }) {
  if (check.error) {
    return <div className="banner-warn">Could not check the rotations in {check.file}: {check.error}</div>;
  }
  if (check.mismatches.length === 0) return null;
  return (
    <>
      <div className="banner-warn">
        {check.mismatches.length} of {check.checked} checked placement(s) in {check.file} have a rotation JLCPCB
        will place wrong. Export again with Fabrication Toolkit's Auto Translate off, after "Update Symbols from
        Library", or use a generated set, which applies the correction itself.
      </div>
      <FoldSection
        bare
        title="Wrong rotations"
        count={check.mismatches.length}
        foldKey={`run:${runId}:cpl-check`}
        chips={<StatChip n={check.mismatches.length} tone="warn">wrong rotation</StatChip>}
      >
        <div className="table-wrap">
          <DataTable
            rows={check.mismatches}
            rowKey={(r) => r.ref}
            columns={[
              { key: "ref", label: "Designator", width: 18, className: "mono", get: (r) => r.ref },
              { key: "lcsc", label: "Part", width: 34, className: "mono", get: (r) => r.lcsc,
                render: (r) => r.component_id
                  ? <Link className="comp-link" to={`/library/components/${r.component_id}`}>{r.lcsc}</Link>
                  : r.lcsc },
              { key: "file", label: "In the file", width: 24, numeric: true, get: (r) => r.file, render: (r) => `${r.file}°` },
              { key: "expected", label: "JLC needs", width: 24, numeric: true, get: (r) => r.expected, render: (r) => `${r.expected}°` },
            ]}
          />
        </div>
      </FoldSection>
    </>
  );
}

/** Which layer a Gerber file holds, by its name, for the board's own colours. */
const GERBER_LAYERS: [RegExp, string][] = [
  [/f[_-]?cu|\.gtl$/i, "F.Cu"],
  [/b[_-]?cu|\.gbl$/i, "B.Cu"],
  [/in1|\.g2$/i, "In1.Cu"],
  [/in2|\.g3$/i, "In2.Cu"],
  [/f[_-]?silk|\.gto$/i, "F.SilkS"],
  [/b[_-]?silk|\.gbo$/i, "B.SilkS"],
  [/f[_-]?mask|\.gts$/i, "F.Mask"],
  [/b[_-]?mask|\.gbs$/i, "B.Mask"],
  [/f[_-]?paste|\.gtp$/i, "F.Paste"],
  [/b[_-]?paste|\.gbp$/i, "B.Paste"],
  [/edge|\.gm1$/i, "Edge.Cuts"],
];

/** The colour goes to the server's gerbv render as well as to the swatch, so it
 *  is a value here and not a CSS variable. */
function layerColor(filename: string): string {
  if (/\.drl$|\.xln$/i.test(filename)) return "#e0e0e0";
  const hit = GERBER_LAYERS.find(([re]) => re.test(filename));
  return LAYER_COLORS[hit ? hit[1] : "Dwgs.User"];
}

const DEFAULT_VISIBLE = [/f[_-]?cu|\.gtl$/i, /f[_-]?silk|\.gto$/i, /edge|\.gm1$/i];

export default function ProductionPanel({ runId }: { runId: number }) {
  const { data: info, error, setError, reload: load } = useLoad((signal) => getRunProduction(runId, signal), [runId]);
  const [busy, setBusy] = useState<string | null>(null);
  const [viewSetId, setViewSetId] = useState<number | null>(null);
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [gerberUrl, setGerberUrl] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);
  const dialog = useDialog();

  useEffect(() => {
    setViewSetId(null);
    setGerberUrl(null);
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
        <FilePick multiple onPick={(files) => act("upload", () => uploadProductionFiles(runId, files))}>
          {busy === "upload" ? "Uploading…" : "Upload files…"}
        </FilePick>
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
          <FoldSection
            bare
            title="Production sets"
            count={info.sets.length}
            foldKey={`run:${runId}:production-sets`}
            chips={<StatChip n={`v${info.sets[0].version_no}`} tone="ok">current</StatChip>}
          >
          <DataTable
            rows={info.sets}
            rowKey={(s) => s.id}
            rowClass={(s) => (viewSet?.id === s.id ? "row-selected" : "")}
            columns={[
              { key: "version", label: "Version", width: 14, className: "mono", get: (s) => s.version_no,
                render: (s) => (
                  <>
                    v{s.version_no}
                    {s.id === info.sets[0].id ? <span className="pill ok">current</span> : null}
                  </>
                ) },
              { key: "source", label: "Source", width: 12, get: (s) => s.source },
              { key: "comment", label: "Comment", width: 30, className: "muted", get: (s) => s.comment },
              { key: "added", label: "Added", width: 18, className: "muted", get: (s) => s.created_at,
                render: (s) => localWhen(s.created_at) },
              { key: "files", label: "Files", width: 8, numeric: true, get: (s) => s.files.filter((f) => !f.extracted).length },
              { key: "act", label: "", width: 18, interactive: false, get: () => "",
                render: (s) => (
                  <>
                    <button className="btn btn-sm" onClick={() => setViewSetId(s.id)}>View</button>{" "}
                    <button className="btn btn-sm btn-danger"
                      onClick={async () => {
                        const confirmed = await dialog.confirm(
                          `Delete production set v${s.version_no}?`,
                          { title: "Delete production set", confirmLabel: "Delete", tone: "danger" },
                        );
                        if (confirmed) act("del", () => deleteProductionSet(s.id));
                      }}>
                      Delete
                    </button>
                  </>
                ) },
            ]}
          />
          </FoldSection>

          {viewSet ? (
            <>
              <div className="card-subtitle">Files in v{viewSet.version_no}</div>
              <ul className="model-files">
                {viewSet.files.filter((f) => !f.extracted).map((f) => (
                  <li key={f.id}>
                    <a href={productionFileUrl(f.id)}>{f.filename}</a>{" "}
                    <span className="pill neutral">{f.kind.replace("_", " ")}</span>{" "}
                    <span className="muted">{fmtBytes(f.size_bytes)}</span>
                  </li>
                ))}
              </ul>

              {info.jlc_bom ? (
                <>
                  <div className="banner-ok">
                    JLCPCB assembles {info.jlc_designators.length} placement(s) across{" "}
                    {info.jlc_bom.rows.length} part(s) — this is the assembly subset, not the
                    total BOM.
                  </div>
                  <FoldSection
                    bare
                    title="JLC BOM"
                    count={info.jlc_bom.rows.length}
                    foldKey={`run:${runId}:jlc-bom`}
                    chips={
                      <>
                        <StatChip n={info.jlc_designators.length.toLocaleString()}>placements</StatChip>
                        {info.jlc_bom.rows.some((r) => !r.lcsc) ? (
                          <StatChip n={info.jlc_bom.rows.filter((r) => !r.lcsc).length} tone="warn">no LCSC code</StatChip>
                        ) : null}
                      </>
                    }
                  >
                    <div className="table-wrap">
                      <DataTable
                        rows={info.jlc_bom.rows}
                        rowKey={(r) => r.designators.join(",") || r.comment}
                        columns={[
                          { key: "comment", label: "Comment", width: 26, get: (r) => r.comment },
                          { key: "des", label: "Designators", width: 34, className: "mono", get: (r) => r.designators.join(", ") },
                          { key: "fp", label: "Footprint", width: 26, className: "muted", get: (r) => r.footprint },
                          { key: "lcsc", label: "LCSC", width: 14, className: "mono", get: (r) => r.lcsc || "—" },
                        ]}
                      />
                    </div>
                  </FoldSection>
                </>
              ) : null}

              {info.cpl_check ? <CplCheckCard runId={runId} check={info.cpl_check} /> : null}

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
