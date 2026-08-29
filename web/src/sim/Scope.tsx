/** Traces of the vectors you picked, with the playhead on them.
 *
 *  One SVG polyline per trace over a shared axis. The run is already decimated
 *  server-side when it is long (min/max pairs per bucket, so a burst of
 *  ringing shows as a band instead of vanishing between samples), which is why
 *  this can draw every point it was given and still stay light.
 */
import { useMemo } from "react";
import { at, eng, vectorRange, type SimPlot } from "./payload";

export interface Trace {
  /** Vector name as the run spells it, e.g. `v(/lowpass)`. */
  name: string;
  label: string;
  unit: string;
}

interface Props {
  plot: SimPlot;
  traces: Trace[];
  sample: number;
  onScrub: (sample: number) => void;
  onRemove: (name: string) => void;
}

const W = 1000;
const H = 260;
const PAD = 4;

export default function Scope({ plot, traces, sample, onScrub, onRemove }: Props) {
  const series = useMemo(
    () => traces.map((t) => ({ trace: t, data: plot.byName.get(t.name) })).filter((s) => s.data),
    [plot, traces],
  );
  const range = useMemo(
    () => vectorRange(series.map((s) => s.data as Float32Array)),
    [series],
  );

  if (!traces.length) {
    return (
      <p className="muted">
        No traces yet — click a wire on the sheet, or a row in the net list, to plot it.
      </p>
    );
  }

  const n = plot.scale.length;
  const x = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * W);
  const y = (v: number) => H - PAD - ((v - range.min) / (range.max - range.min)) * (H - 2 * PAD);

  const pick = (event: React.MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const share = (event.clientX - box.left) / box.width;
    onScrub(Math.max(0, Math.min(n - 1, Math.round(share * (n - 1)))));
  };

  return (
    <div className="sim-scope">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="sim-scope-plot"
        onClick={pick}
        role="img"
        aria-label="Simulation traces"
      >
        {range.min < 0 && range.max > 0 ? (
          <line className="sim-scope-axis" x1={0} x2={W} y1={y(0)} y2={y(0)} />
        ) : null}
        {series.map((s, index) => (
          <polyline
            key={s.trace.name}
            className={`sim-trace sim-trace-${index % 6}`}
            points={Array.from(s.data as Float32Array, (v, i) => `${x(i)},${y(v)}`).join(" ")}
          />
        ))}
        <line className="sim-playhead" x1={x(sample)} x2={x(sample)} y1={0} y2={H} />
      </svg>
      <div className="sim-legend">
        {series.map((s, index) => (
          <button
            key={s.trace.name}
            type="button"
            className={`pill neutral sim-legend-item sim-trace-${index % 6}`}
            onClick={() => onRemove(s.trace.name)}
            title="Remove this trace"
          >
            {s.trace.label} = {eng(at(s.data, sample), s.trace.unit)}
          </button>
        ))}
        <span className="muted">
          {eng(range.min, series[0]?.trace.unit ?? "")} … {eng(range.max, series[0]?.trace.unit ?? "")}
        </span>
      </div>
    </div>
  );
}
