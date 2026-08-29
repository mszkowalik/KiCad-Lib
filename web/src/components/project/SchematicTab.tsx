/** Schematic viewer: server-rendered page SVGs (cached by sha, symbol
 *  preview theme), page picker, variant-aware. Symbols are clickable
 *  (info + library link) and sub-sheet frames navigate between pages —
 *  hotspots come from the snapshot's click-map (mm coords over the SVG). */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getBoardMap,
  getSchematicPages,
  isAbortError,
  schematicPageUrl,
  type BoardMap,
  type MapSymbol,
  type SnapshotBoard,
  type SnapshotInfo,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";
import PartInfo from "./PartInfo";

interface Props {
  snapshot: SnapshotInfo;
  board: SnapshotBoard;
  variant: string;
}

export default function SchematicTab({ snapshot, board, variant }: Props) {
  const [pages, setPages] = useState<string[] | null>(null);
  const [page, setPage] = useState<string | null>(null);
  const [map, setMap] = useState<BoardMap | null>(null);
  const [selected, setSelected] = useState<MapSymbol | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!board.sch) return;
    const ctrl = new AbortController();
    setPages(null);
    setPage(null);
    setSelected(null);
    setError(null);
    getSchematicPages(snapshot.id, board.name, variant, ctrl.signal)
      .then((r) => {
        setPages(r.pages);
        setPage(r.pages[0] ?? null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getBoardMap(snapshot.id, board.name, ctrl.signal)
      .then(setMap)
      .catch(() => setMap(null)); // hotspots are an enhancement, never block
    return () => ctrl.abort();
  }, [snapshot.id, board.name, board.sch, variant]);

  if (!board.sch) {
    return <p className="muted">This board has no schematic file.</p>;
  }

  const sheet = page && map ? map.sheets[page] : null;
  const [pageW, pageH] = sheet?.size ?? [297, 210];
  const pct = (v: number, total: number) => `${(v / total) * 100}%`;

  const resolveTarget = (target: string): string | null => {
    if (!pages) return null;
    if (pages.includes(target)) return target;
    const suffix = target.replace(/^.*?-/, "-");
    return pages.find((p) => p.endsWith(suffix)) ?? null;
  };

  return (
    <div>
      {error ? <ErrorBanner message={error} /> : null}
      {pages === null && !error ? (
        <Spinner label="Rendering schematic (first view of a snapshot takes a few seconds)" />
      ) : null}
      {pages !== null ? (
        <>
          <div className="toolbar">
            <div className="seg" role="group" aria-label="Schematic pages">
              {pages.map((p) => (
                <button
                  key={p}
                  type="button"
                  className={page === p ? "on" : ""}
                  onClick={() => {
                    setPage(p);
                    setSelected(null);
                  }}
                  title={p}
                >
                  {p.replace(/\.svg$/, "").replace(`${board.name}-`, "") || board.name}
                </button>
              ))}
            </div>
            {variant ? <span className="pill neutral">variant: {variant}</span> : null}
            {/* The simulator reads the same checkout as these renders, so it
                needs nothing but the snapshot and the board. */}
            <Link
              className="btn"
              to={`/sim?snapshot=${snapshot.id}&board=${encodeURIComponent(board.name)}`}
              title="Open this schematic in the simulator"
            >
              Simulate
            </Link>
            {sheet ? (
              <span className="muted">
                {sheet.symbols.length} clickable parts
                {sheet.subsheets.length ? ` · ${sheet.subsheets.length} sub-sheets` : ""}
              </span>
            ) : null}
          </div>
          {selected ? <PartInfo part={selected} onClose={() => setSelected(null)} /> : null}
          {page ? (
            <div className="card schview">
              <div className="overlay-wrap">
                <img
                  src={schematicPageUrl(snapshot.id, board.name, page, variant)}
                  alt={`Schematic page ${page}`}
                />
                {sheet?.symbols.map((s) => (
                  <button
                    key={s.ref}
                    type="button"
                    className={`hotspot${selected?.ref === s.ref ? " on" : ""}`}
                    title={`${s.ref} — ${s.bom?.value || s.value}`}
                    style={{
                      left: pct(s.bbox[0], pageW),
                      top: pct(s.bbox[1], pageH),
                      width: pct(s.bbox[2] - s.bbox[0], pageW),
                      height: pct(s.bbox[3] - s.bbox[1], pageH),
                    }}
                    onClick={() => setSelected(s)}
                  />
                ))}
                {sheet?.subsheets.map((sub) => {
                  const target = resolveTarget(sub.target_svg);
                  return (
                    <button
                      key={`${sub.name}-${sub.at[0]}-${sub.at[1]}`}
                      type="button"
                      className="hotspot sheet-hotspot"
                      title={target ? `Open sheet ${sub.name}` : sub.name}
                      disabled={!target}
                      style={{
                        left: pct(sub.at[0], pageW),
                        top: pct(sub.at[1], pageH),
                        width: pct(sub.size[0], pageW),
                        height: pct(sub.size[1], pageH),
                      }}
                      onClick={() => {
                        if (target) {
                          setPage(target);
                          setSelected(null);
                        }
                      }}
                    />
                  );
                })}
              </div>
            </div>
          ) : (
            <p className="muted">No pages.</p>
          )}
        </>
      ) : null}
    </div>
  );
}
