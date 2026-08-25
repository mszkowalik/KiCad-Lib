import { useEffect, useMemo, useState } from "react";

import { errorMessage, fetchSvgText, isAbortError } from "../api";
import { ErrorBanner, Spinner } from "./Ui";

/** Before, after, and the difference — for a symbol or a land pattern.
 *
 *  The difference pane is the point of this component. kicad-cli emits its SVG
 *  sized in MILLIMETRES with a viewBox anchored at the drawing's bounding box,
 *  so drawing both versions at one shared px-per-mm scale puts identical
 *  geometry on identical pixels. `mix-blend-mode: difference` over black then
 *  paints every unchanged pixel black and lights up only what moved — a pad
 *  that grew, a pin that shifted, a silk line that thinned.
 *
 *  The honest caveat, which the pane states rather than hides: the viewBox
 *  origin is the bounding box, not the footprint origin. When an edit changes
 *  the bounding box, the two renders are anchored differently and the overlay
 *  reports the whole drawing as moved. That is still the right answer to
 *  "did this change" — it is only an imprecise answer to "where" — and it does
 *  not arise for the common cases (a pad resize inside an unchanged courtyard,
 *  a silkscreen width, a text move). */

const STAGE = 190; // px — the difference stage's usable box

interface Dims {
  text: string;
  wMm: number;
  hMm: number;
}

/** Pull the millimetre size out of the SVG header. Returns null for anything
 *  that does not look like a kicad-cli export, which makes the caller fall
 *  back to plain side-by-side images rather than drawing a wrong overlay. */
function parseDims(text: string): Dims | null {
  const w = /width="([\d.]+)mm"/.exec(text);
  const h = /height="([\d.]+)mm"/.exec(text);
  if (!w || !h) return null;
  const wMm = parseFloat(w[1]);
  const hMm = parseFloat(h[1]);
  if (!(wMm > 0) || !(hMm > 0)) return null;
  return { text, wMm, hMm };
}

function dataUri(text: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(text)}`;
}

export default function GeometryDiff({
  beforePath,
  afterPath,
  beforeLabel,
  afterLabel,
}: {
  beforePath: string | null;
  afterPath: string;
  beforeLabel: string;
  afterLabel: string;
}) {
  const [before, setBefore] = useState<Dims | null>(null);
  const [after, setAfter] = useState<Dims | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    setBefore(null);
    setAfter(null);
    Promise.all([
      fetchSvgText(afterPath, ctrl.signal),
      beforePath ? fetchSvgText(beforePath, ctrl.signal) : Promise.resolve(null),
    ])
      .then(([a, b]) => {
        setAfter(parseDims(a));
        setBefore(b === null ? null : parseDims(b));
        setLoading(false);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(errorMessage(err));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [beforePath, afterPath]);

  // One scale for both, so the overlay is a real comparison and not two
  // pictures each fitted to its own box.
  const scale = useMemo(() => {
    const boxes = [before, after].filter((d): d is Dims => d !== null);
    if (boxes.length === 0) return 1;
    const wMm = Math.max(...boxes.map((d) => d.wMm));
    const hMm = Math.max(...boxes.map((d) => d.hMm));
    return Math.min(STAGE / wMm, STAGE / hMm);
  }, [before, after]);

  if (loading) return <Spinner label="rendering both versions" />;
  if (error !== null) return <ErrorBanner message={error} />;
  if (after === null) return <div className="muted">This version could not be rendered.</div>;

  const sizeSame =
    before !== null && before.wMm === after.wMm && before.hMm === after.hMm;

  const img = (d: Dims) => (
    <img
      src={dataUri(d.text)}
      alt=""
      width={Math.round(d.wMm * scale)}
      height={Math.round(d.hMm * scale)}
    />
  );

  /** One flattened layer of the overlay. The opaque backdrop is the whole
   *  point — see `.diff-layer` in styles.css. */
  const layer = (d: Dims, cls: string) => (
    <div className={`diff-layer ${cls}`}>{img(d)}</div>
  );

  return (
    <div className="diff-panes">
      <div className="diff-pane">
        <span className="diff-pane-label">{beforeLabel}</span>
        <div className="diff-stage">
          {before === null ? (
            <span className="muted">nothing before — this is the first version</span>
          ) : (
            img(before)
          )}
        </div>
      </div>

      <div className="diff-pane">
        <span className="diff-pane-label">{afterLabel}</span>
        <div className="diff-stage">{img(after)}</div>
      </div>

      {before !== null ? (
        <div className="diff-pane">
          <span className="diff-pane-label">Difference</span>
          <div className="diff-stage negative">
            {layer(before, "before")}
            {layer(after, "after")}
          </div>
          <span className="diff-note">
            {sizeSame
              ? "Black is unchanged. Anything lit up moved."
              : `Bounding box changed (${before.wMm}×${before.hMm} mm → ${after.wMm}×${after.hMm} mm),` +
                " so the two renders are anchored differently and the overlay shows more than moved."}
          </span>
        </div>
      ) : null}
    </div>
  );
}
