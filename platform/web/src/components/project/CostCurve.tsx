/** Cost-vs-volume curve: unit cost per device across production volumes.
 *  Single series → no legend (the title names it); endpoint direct-labeled;
 *  crosshair + tooltip on hover; values table below carries every number. */
import { useMemo, useRef, useState } from "react";
import type { CurvePoint } from "../../api";

const W = 560;
const H = 220;
const PAD = { top: 16, right: 56, bottom: 28, left: 56 };

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const rawStep = max / count;
  const mag = 10 ** Math.floor(Math.log10(rawStep));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= rawStep) ?? 10 * mag;
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.5; v += step) ticks.push(v);
  return ticks;
}

function fmtMoney(v: number | null, currency: string): string {
  if (v == null) return "—";
  const digits = v >= 100 ? 2 : v >= 1 ? 2 : 4;
  return `${v.toLocaleString(undefined, { maximumFractionDigits: digits })} ${currency}`;
}

export default function CostCurve({ points, currency }: { points: CurvePoint[]; currency: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const data = points.filter((p) => p.device_total != null);
  const { xs, ys, yTicks } = useMemo(() => {
    const innerW = W - PAD.left - PAD.right;
    const innerH = H - PAD.top - PAD.bottom;
    const n = Math.max(data.length, 1);
    const xs = data.map((_, i) => PAD.left + (n === 1 ? innerW / 2 : (i * innerW) / (n - 1)));
    const maxY = Math.max(...data.map((p) => p.device_total ?? 0), 0.0001);
    const ticks = niceTicks(maxY);
    const top = ticks[ticks.length - 1];
    const ys = data.map((p) => PAD.top + innerH - ((p.device_total ?? 0) / top) * innerH);
    const yTicks = ticks.map((t) => ({
      value: t,
      y: PAD.top + innerH - (t / top) * innerH,
    }));
    return { xs, ys, yTicks };
  }, [data]);

  if (data.length === 0) {
    return <p className="muted">No priced volumes yet — parts need price ladders first.</p>;
  }

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0;
    for (let i = 1; i < xs.length; i++) {
      if (Math.abs(xs[i] - mx) < Math.abs(xs[best] - mx)) best = i;
    }
    setHover(best);
  };

  const path = xs.map((x, i) => `${i === 0 ? "M" : "L"}${x},${ys[i]}`).join(" ");
  const last = data.length - 1;

  return (
    <div className="chart-wrap">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="chart-svg"
        role="img"
        aria-label="Unit cost per device by production volume"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {yTicks.map((t) => (
          <g key={t.value}>
            <line className="chart-grid" x1={PAD.left} x2={W - PAD.right} y1={t.y} y2={t.y} />
            <text className="chart-tick" x={PAD.left - 8} y={t.y + 3} textAnchor="end">
              {t.value.toLocaleString()}
            </text>
          </g>
        ))}
        {xs.map((x, i) => (
          <text key={data[i].volume} className="chart-tick" x={x} y={H - PAD.bottom + 16} textAnchor="middle">
            {data[i].volume.toLocaleString()}
          </text>
        ))}
        {hover != null ? (
          <line
            className="chart-crosshair"
            x1={xs[hover]}
            x2={xs[hover]}
            y1={PAD.top}
            y2={H - PAD.bottom}
          />
        ) : null}
        <path className="chart-line" d={path} />
        {xs.map((x, i) => (
          <circle
            key={data[i].volume}
            className={`chart-dot${hover === i ? " on" : ""}`}
            cx={x}
            cy={ys[i]}
            r={4}
          />
        ))}
        <text className="chart-endlabel" x={xs[last] + 8} y={ys[last] + 4}>
          {fmtMoney(data[last].device_total, currency)}
        </text>
      </svg>
      {hover != null ? (
        <div className="chart-tip">
          <span className="mono">{data[hover].volume.toLocaleString()} pcs</span>
          <span>
            {fmtMoney(data[hover].device_total, currency)}/device · parts{" "}
            {fmtMoney(data[hover].bom_per_device, currency)} · costs{" "}
            {fmtMoney(data[hover].cost_per_device, currency)}
          </span>
        </div>
      ) : null}
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th className="num">Volume</th>
              <th className="num">Parts / device</th>
              <th className="num">Extra / device</th>
              <th className="num">Costs / device</th>
              <th className="num">Total / device</th>
              <th className="num">Run total</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.volume}>
                <td className="num mono">{p.volume.toLocaleString()}</td>
                <td className="num">{fmtMoney(p.bom_per_device, currency)}</td>
                <td className="num">{fmtMoney(p.extra_per_device, currency)}</td>
                <td className="num">{fmtMoney(p.cost_per_device, currency)}</td>
                <td className="num">{fmtMoney(p.device_total, currency)}</td>
                <td className="num">{fmtMoney(p.run_total, currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
