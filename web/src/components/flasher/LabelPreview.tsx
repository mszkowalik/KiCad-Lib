/** The label as the printer will produce it — drawn, not described.
 *
 *  A `print_label` step is four numbers and a value template, and the one
 *  thing that decides whether the label works — 12 characters at 3 dots need
 *  47.5 mm, and a 25 mm roll prints 22.9 mm across — used to be found out when
 *  the agent refused the job. This draws the layout `flasher/label.ts` mirrors
 *  from the agent, at the roll's true proportions, turned when the step says
 *  so, and prints the agent's own refusal under it before anything is queued.
 *
 *  The printable area is the PRINTER's statement, from its PPD on the bench.
 *  With the agent reachable the roll carries it; without, the label is drawn
 *  at its nominal size and the caption says so, rather than guessing a margin.
 */
import { useMemo } from "react";
import { layoutLabel, type RollGeometry } from "../../flasher/label";

export default function LabelPreview({
  value,
  roll,
  dots,
  rotate,
  caption,
}: {
  value: string;
  roll: RollGeometry | null;
  dots: number;
  rotate: boolean;
  /** a line under the picture, before the verdict — what the value is */
  caption?: string;
}) {
  const out = useMemo(() => {
    if (!roll) return { layout: null, error: "no roll named — the label has no size to draw at" };
    if (!value) return { layout: null, error: "nothing to print yet" };
    try {
      return { layout: layoutLabel(value, roll, dots, rotate), error: null };
    } catch (err) {
      return { layout: null, error: err instanceof Error ? err.message : String(err) };
    }
  }, [value, roll, dots, rotate]);

  const L = out.layout;
  const [lw, lh] = roll?.label ?? [50, 25];
  const [pw, ph] = roll?.printable ?? roll?.label ?? [50, 25];
  // The printable box sits inside the label. Its offsets are in the PPD too,
  // but the agent reports the size only; centring is within 0.3 mm of the
  // measured w72h154 box and this is a picture, not the job.
  const px = (lw - pw) / 2;
  const py = (lh - ph) / 2;
  const bad = !!out.error || !!L?.problem;

  return (
    <div className={`label-preview${bad ? " label-preview-bad" : ""}`}>
      <svg
        viewBox={`-1 -1 ${lw + 2} ${lh + 2}`}
        className="label-preview-svg"
        role="img"
        aria-label={L ? `label ${value} on ${roll?.name ?? roll?.size}` : "label preview"}
      >
        {/* the label, then the printable area inside it */}
        <rect x={0} y={0} width={lw} height={lh} rx={1.2} className="label-paper" />
        <rect x={px} y={py} width={pw} height={ph} className="label-printable" />
        {L ? (
          <g
            transform={L.rotate ? `translate(${px} ${py + ph}) rotate(-90)` : `translate(${px} ${py})`}
            clipPath="url(#label-clip)"
          >
            <defs>
              <clipPath id="label-clip">
                <rect x={0} y={0} width={L.across} height={L.down} />
              </clipPath>
            </defs>
            {L.bars.map((b, i) => (
              <rect key={i} x={b.x} y={L.barsY} width={b.w} height={L.barsH} className="label-bar" />
            ))}
            <text
              x={L.text.x}
              y={L.text.y}
              fontSize={L.text.size}
              textAnchor="middle"
              className="label-text"
            >
              {value}
            </text>
          </g>
        ) : null}
      </svg>
      <div className="label-preview-note muted dim">
        {caption ? <span>{caption} · </span> : null}
        {roll ? (
          <span>
            {roll.name || roll.size} · {lw.toFixed(1)} × {lh.toFixed(1)} mm
            {roll.printable
              ? ` · prints ${pw.toFixed(1)} × ${ph.toFixed(1)} mm`
              : " · nominal size, the printable area is on the bench's printer"}
          </span>
        ) : null}
        {L && !L.problem ? (
          <span> · {L.width.toFixed(1)} mm of barcode{L.rotate ? ", turned" : ""}</span>
        ) : null}
      </div>
      {out.error || L?.problem ? (
        <div className="label-preview-verdict field-error">{out.error ?? L?.problem}</div>
      ) : null}
    </div>
  );
}
