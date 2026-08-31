/** Loss and εeff against frequency, as SVG so it stays sharp and selectable.
 *
 *  Colours come from the palette variables, so the chart follows the theme; the
 *  x axis is logarithmic because the sweep spans decades.
 */
export interface Series {
  name: string;
  x: number[];
  y: number[];
  axis: "l" | "r";
  color: string;
  dash?: string;
}

export interface ChartProps {
  series: Series[];
  xlabel: string;
  ylabel: string;
  y2label?: string;
  xfmt: (v: number) => string;
  /** Dashed vertical markers, e.g. the design frequency. */
  marks?: { x: number; label: string }[];
}

const W = 900;
const H = 300;
const L = 66;
const R = 66;
const T = 16;
const B = 46;
const PW = W - L - R;
const PH = H - T - B;

const fmtn = (v: number): string =>
  Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(2) : v.toPrecision(3);

export default function Chart({ series, xlabel, ylabel, y2label, xfmt, marks }: ChartProps) {
  if (!series.length || !series[0].x.length) return null;
  const xs = series[0].x;
  const tx = (v: number) => Math.log10(v);
  const xmin = tx(Math.min(...xs));
  const xmax = tx(Math.max(...xs));
  const X = (v: number) => L + ((tx(v) - xmin) / (xmax - xmin || 1)) * PW;

  const axes: Record<string, { lo: number; hi: number }> = {};
  for (const a of ["l", "r"] as const) {
    const ys = series.filter((s) => s.axis === a).flatMap((s) => s.y);
    if (!ys.length) continue;
    let lo = a === "r" ? Math.min(...ys) : Math.min(0, ...ys);
    let hi = Math.max(...ys);
    if (a === "r") {
      const m = hi - lo || hi * 0.05 || 1;
      lo -= 0.1 * m;
      hi += 0.1 * m;
    } else hi *= 1.05;
    axes[a] = { lo, hi: hi || 1 };
  }
  const Y = (v: number, a: "l" | "r") => T + PH - ((v - axes[a].lo) / (axes[a].hi - axes[a].lo || 1)) * PH;

  const ticks: { v: number; major: boolean }[] = [];
  for (let d = Math.floor(xmin); d <= Math.ceil(xmax); d++) {
    for (const m of [1, 2, 5]) {
      const v = m * Math.pow(10, d);
      if (tx(v) >= xmin - 1e-9 && tx(v) <= xmax + 1e-9) ticks.push({ v, major: m === 1 });
    }
  }
  const majors = ticks.filter((t) => t.major).length;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="fs-chart" role="img" aria-label={`${ylabel} against ${xlabel}`}>
      <rect x={L} y={T} width={PW} height={PH} className="fs-chart-plot" />
      {ticks.map((t) => (
        <g key={`x${t.v}`}>
          <line x1={X(t.v)} y1={T} x2={X(t.v)} y2={T + PH} className={t.major ? "fs-grid major" : "fs-grid"} />
          {t.major || majors < 3 ? (
            <text x={X(t.v)} y={T + PH + 15} textAnchor="middle" className="fs-chart-tick">
              {xfmt(t.v)}
            </text>
          ) : null}
        </g>
      ))}
      {(["l", "r"] as const)
        .filter((a) => axes[a])
        .flatMap((a) =>
          [0, 0.25, 0.5, 0.75, 1].map((f) => {
            const v = axes[a].lo + (axes[a].hi - axes[a].lo) * f;
            return (
              <g key={`${a}${f}`}>
                {a === "l" ? <line x1={L} y1={Y(v, a)} x2={L + PW} y2={Y(v, a)} className="fs-grid" /> : null}
                <text
                  x={a === "l" ? L - 6 : L + PW + 6}
                  y={Y(v, a) + 4}
                  textAnchor={a === "l" ? "end" : "start"}
                  className="fs-chart-tick"
                >
                  {fmtn(v)}
                </text>
              </g>
            );
          }),
        )}
      {(marks ?? []).map((m) =>
        X(m.x) >= L && X(m.x) <= L + PW ? (
          <g key={m.label}>
            <line x1={X(m.x)} y1={T} x2={X(m.x)} y2={T + PH} className="fs-chart-mark" />
            <text x={X(m.x) + 4} y={T + PH - 6} className="fs-chart-tick">
              {m.label}
            </text>
          </g>
        ) : null,
      )}
      {series.map((s) => (
        <g key={s.name}>
          <path
            d={s.x.map((v, i) => `${i ? "L" : "M"}${X(v)},${Y(s.y[i], s.axis)}`).join(" ")}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeDasharray={s.dash}
          />
          {s.x.map((v, i) => (
            <circle key={v} cx={X(v)} cy={Y(s.y[i], s.axis)} r={2.4} fill={s.color}>
              <title>{`${s.name}: ${xfmt(v)}, ${fmtn(s.y[i])}`}</title>
            </circle>
          ))}
        </g>
      ))}
      <text x={L + PW / 2} y={H - 6} textAnchor="middle" className="fs-chart-axis">
        {xlabel}
      </text>
      <text x={14} y={T + PH / 2} textAnchor="middle" transform={`rotate(-90 14 ${T + PH / 2})`} className="fs-chart-axis">
        {ylabel}
      </text>
      {y2label ? (
        <text
          x={W - 12}
          y={T + PH / 2}
          textAnchor="middle"
          transform={`rotate(90 ${W - 12} ${T + PH / 2})`}
          className="fs-chart-axis"
        >
          {y2label}
        </text>
      ) : null}
      {series.map((s, i) => {
        const lx = L + 10 + series.slice(0, i).reduce((a, q) => a + 34 + q.name.length * 6.2, 0);
        return (
          <g key={`lg${s.name}`}>
            <line x1={lx} y1={T + 12} x2={lx + 22} y2={T + 12} stroke={s.color} strokeWidth={2} strokeDasharray={s.dash} />
            <text x={lx + 26} y={T + 16} className="fs-chart-tick">
              {s.name}
              {s.axis === "r" ? " →" : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
