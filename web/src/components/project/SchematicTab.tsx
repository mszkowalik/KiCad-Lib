/** Schematic viewer for a project snapshot.
 *
 *  The drawing is `SchematicView` — the same component the simulator and the
 *  editor use — so this page, a simulation overlay and a circuit being drawn
 *  are one renderer with one colour theme. Before that they were a
 *  server-rendered SVG per page plus a click-map of hotspots laid over it, and
 *  the two could disagree about where a part was.
 *
 *  What this page adds on top is its own: parts are clickable for their BOM
 *  row and library link, and a sub-sheet frame navigates into that sheet.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getBoardMap,
  getSimGeometry,
  getSimSheets,
  getSimTheme,
  isAbortError,
  type BoardMap,
  type MapSymbol,
  type SimGeometry,
  type SimSheet,
  type SimSourceRef,
  type SnapshotBoard,
  type SnapshotInfo,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";
import SchematicView from "../../sim/draw/SchematicView";
import { FALLBACK_THEME, type SchTheme } from "../../sim/draw/types";
import PartInfo from "./PartInfo";

interface Props {
  snapshot: SnapshotInfo;
  board: SnapshotBoard;
  variant: string;
}

export default function SchematicTab({ snapshot, board, variant }: Props) {
  const [sheets, setSheets] = useState<SimSheet[] | null>(null);
  const [path, setPath] = useState<string>("");
  const [geometry, setGeometry] = useState<SimGeometry | null>(null);
  const [map, setMap] = useState<BoardMap | null>(null);
  const [selected, setSelected] = useState<MapSymbol | null>(null);
  const [theme, setTheme] = useState<SchTheme>(FALLBACK_THEME);
  const [error, setError] = useState<string | null>(null);

  const source: SimSourceRef = useMemo(
    () => ({ kind: "snapshot", snapshotId: snapshot.id, board: board.name }),
    [snapshot.id, board.name],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    getSimTheme(ctrl.signal)
      .then((r) => setTheme({ ...FALLBACK_THEME, ...r.schematic }))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    if (!board.sch) return;
    const ctrl = new AbortController();
    setSheets(null);
    setPath("");
    setGeometry(null);
    setSelected(null);
    setError(null);
    getSimSheets(source, ctrl.signal)
      .then((r) => {
        setSheets(r.sheets);
        setPath(r.sheets[0]?.path ?? "");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    // The BOM row and the library link behind a part. Hotspots come from the
    // geometry, so a missing map costs the extra detail, never the drawing.
    getBoardMap(snapshot.id, board.name, ctrl.signal).then(setMap).catch(() => setMap(null));
    return () => ctrl.abort();
  }, [source, snapshot.id, board.name, board.sch]);

  useEffect(() => {
    if (!sheets) return;
    const ctrl = new AbortController();
    getSimGeometry(source, path, ctrl.signal)
      .then(setGeometry)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [source, path, sheets]);

  /** Every part the click-map knows, by reference — the map is keyed by page,
   *  and a reference is unique across the board. */
  const parts = useMemo(() => {
    const out = new Map<string, MapSymbol>();
    for (const sheet of Object.values(map?.sheets ?? {})) {
      for (const sym of sheet.symbols) out.set(sym.ref, sym);
    }
    return out;
  }, [map]);

  if (!board.sch) {
    return <p className="muted">This board has no schematic file.</p>;
  }

  const current = sheets?.find((s) => s.path === path);

  return (
    <div>
      {error ? <ErrorBanner message={error} /> : null}
      {sheets === null && !error ? <Spinner label="Reading the schematic" /> : null}
      {sheets !== null ? (
        <>
          <div className="toolbar">
            {/* A dropdown, not a row of buttons: a board has as many sheets as
                it likes, and a toolbar that grows with the data pushes the
                page sideways. */}
            <label className="sim-pick-group">
              <span>Sheet</span>
              <select
                className="text"
                value={path}
                onChange={(e) => {
                  setPath(e.target.value);
                  setSelected(null);
                }}
              >
                {sheets.map((s) => (
                  <option key={s.path} value={s.path}>
                    {"  ".repeat(s.depth)}
                    {s.name} · {s.symbols} parts
                  </option>
                ))}
              </select>
            </label>
            {variant ? <span className="pill neutral">variant: {variant}</span> : null}
            {/* The simulator reads the same checkout as this view, so it needs
                nothing but the snapshot and the board. */}
            {/* Two doors, one room. Simulate is the FORMAL path — the
                harness, the verdicts, the run that counts. Play live is the
                playground: watch it run, turn its knobs — and nothing done
                there can ever write back to this project, because the git
                checkout is the source of truth. */}
            <Link
              className="btn"
              to={`/sim?snapshot=${snapshot.id}&board=${encodeURIComponent(board.name)}`}
              title="Run the harness and read its verdicts"
            >
              Simulate
            </Link>
            <Link
              className="btn"
              to={`/sim?snapshot=${snapshot.id}&board=${encodeURIComponent(board.name)}&mode=live`}
              title="Watch it run and turn its knobs — never writes to the project"
            >
              Play live
            </Link>
            {current ? (
              <span className="muted">
                {current.symbols} parts
                {current.directives ? ` · ${current.directives} SPICE directives` : ""}
              </span>
            ) : null}
          </div>
          {selected ? <PartInfo part={selected} onClose={() => setSelected(null)} /> : null}
          {geometry ? (
            <div className="card schview">
              <SchematicView
                drawing={geometry.draw}
                theme={theme}
                size={[geometry.size[0], geometry.size[1]]}
                resetKey={path}
                extraBounds={geometry.pins.map((p) => [p.at[0], p.at[1]] as [number, number])}
                layers={(view) => (
                  <svg
                    className="sim-layer sim-pick"
                    viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
                    preserveAspectRatio="xMidYMid meet"
                    role="group"
                    aria-label="Parts"
                  >
                    {geometry.subsheets.map((sub) => (
                      <rect
                        key={`s${sub.uuid}`}
                        className="sim-part sheet"
                        x={sub.at[0]}
                        y={sub.at[1]}
                        width={sub.size[0]}
                        height={sub.size[1]}
                        onClick={() => {
                          // A sheet INSTANCE is the parent's path plus this
                          // placement's uuid — the same file placed twice is
                          // two instances with different references.
                          const target = `${geometry.instance_path}/${sub.uuid}`;
                          if (sheets.some((s) => s.path === target)) {
                            setPath(target);
                            setSelected(null);
                          }
                        }}
                      >
                        <title>{`Open sheet ${sub.name}`}</title>
                      </rect>
                    ))}
                    {geometry.symbols.map((sym) => {
                      if (!sym.bbox || sym.power || !sym.ref) return null;
                      const part = parts.get(sym.ref);
                      return (
                        <rect
                          key={`p${sym.index}`}
                          className={`sim-part${selected?.ref === sym.ref ? " on" : ""}`}
                          x={sym.bbox[0]}
                          y={sym.bbox[1]}
                          width={sym.bbox[2] - sym.bbox[0]}
                          height={sym.bbox[3] - sym.bbox[1]}
                          onClick={() => setSelected(
                            part ?? {
                              ref: sym.ref, value: sym.value, lib_id: sym.lib_id,
                              at: sym.at, bbox: sym.bbox ?? [0, 0, 0, 0],
                            },
                          )}
                        >
                          <title>{`${sym.ref} — ${part?.bom?.value || sym.value}`}</title>
                        </rect>
                      );
                    })}
                  </svg>
                )}
              />
            </div>
          ) : (
            <Spinner label="Drawing the sheet" />
          )}
        </>
      ) : null}
    </div>
  );
}
