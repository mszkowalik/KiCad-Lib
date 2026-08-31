/** Cross-section renderer for the field solver.
 *
 *  Canvas, not SVG: a solved mesh is 150 000 triangles and the DOM will not take
 *  that. Every colour is read from the page's CSS custom properties through
 *  getComputedStyle, the same trick useSimOverlay uses — the canvas cannot resolve
 *  var() itself, and the palette has to follow the light/dark theme.
 */
import type { FsField, FsGeometry } from "../../api";

export type FieldView = "phi" | "E" | "Elines" | "Ey" | "H" | "Hx" | "Js" | "none";

export interface View {
  cx: number;
  cy: number;
  halfw: number;
}

export interface Palette {
  text: string;
  muted: string;
  line: string;
  surface: string;
  hot: string;
  cold: string;
  zero: string;
  copper: string;
  signal: string;
  reference: string;
  mask: string;
  finish: string;
  accent: string;
}

const rgb = (s: string): [number, number, number] => {
  const t = s.trim();
  const m = t.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (m) {
    const h = m[1].length === 3 ? m[1].replace(/./g, (c) => c + c) : m[1];
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  const n = t.match(/-?\d+(\.\d+)?/g);
  return n && n.length >= 3 ? [Number(n[0]), Number(n[1]), Number(n[2])] : [128, 128, 128];
};

const mix = (a: [number, number, number], b: [number, number, number], t: number): string =>
  `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;

/** Read the theme once per paint: the values change with prefers-color-scheme. */
export function palette(el: HTMLElement): Palette {
  const s = getComputedStyle(el);
  const v = (name: string, fallback: string) => s.getPropertyValue(name).trim() || fallback;
  return {
    text: v("--text", "#1b2430"),
    muted: v("--muted", "#5c6a7b"),
    line: v("--line", "#d7dfe8"),
    surface: v("--surface", "#ffffff"),
    hot: v("--sim-hot", "#c0392f"),
    cold: v("--sim-cold", "#1f63d6"),
    zero: v("--sim-zero", "#5c6a7b"),
    copper: v("--copper", "#b26a34"),
    signal: v("--fs-signal", v("--copper", "#b26a34")),
    reference: v("--fs-reference", "#8b8f96"),
    mask: v("--fs-mask", "rgba(60,150,60,.35)"),
    finish: v("--fs-finish", "#e9c46a"),
    accent: v("--accent", "#1f63d6"),
  };
}

/** Diverging map for signed data (potential): cold — zero — hot. */
const diverging = (p: Palette) => {
  const c = rgb(p.cold);
  const z = rgb(p.surface);
  const h = rgb(p.hot);
  return (t: number) => (t <= 0.5 ? mix(c, z, Math.max(0, t) * 2) : mix(z, h, Math.min(1, (t - 0.5) * 2)));
};

/** Sequential map for magnitudes: zero — cold — accent — hot. */
const sequential = (p: Palette) => {
  const stops: [number, [number, number, number]][] = [
    [0, rgb(p.surface)],
    [0.35, rgb(p.cold)],
    [0.7, rgb(p.copper)],
    [1, rgb(p.hot)],
  ];
  return (t: number) => {
    const u = Math.max(0, Math.min(1, t));
    for (let i = 1; i < stops.length; i++) {
      if (u <= stops[i][0]) {
        const [a, ca] = stops[i - 1];
        const [b, cb] = stops[i];
        return mix(ca, cb, (u - a) / (b - a || 1));
      }
    }
    return mix(stops[3][1], stops[3][1], 0);
  };
};

export function fitView(g: FsGeometry): View {
  const conds = g.regions.filter((r) => r.kind === "conductor");
  const half = g.xmax;
  const xs = conds.flatMap((r) => r.points.map((q) => q[0])).filter((x) => Math.abs(x) < half * 0.999);
  const ys = conds.flatMap((r) => r.points.map((q) => q[1]));
  const cx = xs.length ? (Math.min(...xs) + Math.max(...xs)) / 2 : 0;
  const cy = ys.length ? (Math.min(...ys) + Math.max(...ys)) / 2 : 0;
  const wide = xs.length ? Math.max(...xs) - Math.min(...xs) : half;
  const tall = ys.length ? Math.max(...ys) - Math.min(...ys) : half;
  return { cx, cy, halfw: Math.max(wide, tall * 2, 0.4) * 1.6 };
}

export interface DrawArgs {
  canvas: HTMLCanvasElement;
  geometry: FsGeometry;
  field?: FsField | null;
  view: FieldView;
  viewport: View;
  /** Frequency shown, only used for captions. */
  label?: string;
  /** Reference potential for the Δ view, and the common scale across frames. */
  deltaRef?: number[] | null;
  deltaScale?: number;
}

const niceStep = (v: number): number => {
  const d = Math.pow(10, Math.floor(Math.log10(v)));
  const m = v / d;
  return d * (m >= 5 ? 5 : m >= 2 ? 2 : 1);
};

export function drawCrossSection(a: DrawArgs): void {
  const { canvas, geometry: g, field: F, view } = a;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const box = canvas.getBoundingClientRect();
  const wpx = Math.max(1, Math.round(box.width * dpr));
  const hpx = Math.max(1, Math.round(box.height * dpr));
  if (canvas.width !== wpx || canvas.height !== hpx) {
    canvas.width = wpx;
    canvas.height = hpx;
  }
  const p = palette(canvas);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = p.surface;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.font = `${11 * dpr}px system-ui, sans-serif`;

  const halfw = a.viewport.halfw;
  const halfh = (halfw * canvas.height) / canvas.width;
  const X = (x: number) => ((x - (a.viewport.cx - halfw)) / (2 * halfw)) * canvas.width;
  const Y = (y: number) => canvas.height - ((y - (a.viewport.cy - halfh)) / (2 * halfh)) * canvas.height;

  const cmapDiv = diverging(p);
  const cmapSeq = sequential(p);

  if (F && view !== "none" && view !== "Js") {
    const useAir = view === "H" || view === "Hx";
    const isDelta = view === "phi" && false;
    const isLines = view === "Elines";
    const isComp = view === "Ey" || view === "Hx";
    const isMag = view === "E" || view === "H" || isLines;
    const base = useAir ? F.phi_air : F.phi;
    const pot = a.deltaRef && a.deltaRef.length === F.phi.length && view === "phi" && a.deltaScale
      ? F.phi.map((v, i) => v - (a.deltaRef as number[])[i])
      : base;

    let val: Float64Array | null = null;
    if (isMag || isComp) {
      val = new Float64Array(F.tris.length);
      for (let i = 0; i < F.tris.length; i++) {
        const [ia, ib, ic] = F.tris[i];
        const A = F.nodes[ia];
        const B = F.nodes[ib];
        const C = F.nodes[ic];
        const det = (B[0] - A[0]) * (C[1] - A[1]) - (C[0] - A[0]) * (B[1] - A[1]);
        const gx = ((B[1] - C[1]) * pot[ia] + (C[1] - A[1]) * pot[ib] + (A[1] - B[1]) * pot[ic]) / det;
        const gy = ((C[0] - B[0]) * pot[ia] + (A[0] - C[0]) * pot[ib] + (B[0] - A[0]) * pot[ic]) / det;
        val[i] = isComp ? -gy * 1e3 : Math.hypot(gx, gy) * 1e3;
        if (useAir) val[i] *= 8.8541878e-12 * 299792458;
      }
    }

    let pmin = Infinity;
    let pmax = -Infinity;
    if (isMag && val) {
      const arr = Array.from(val).filter((_, i) => F.conductor_of[i] < 0).sort((x, y) => x - y);
      pmax = arr[Math.floor(arr.length * 0.995)] || 1;
      pmin = pmax / 1000;
    } else if (isComp && val) {
      const arr = Array.from(val).filter((_, i) => F.conductor_of[i] < 0).map(Math.abs).sort((x, y) => x - y);
      pmax = arr[Math.floor(arr.length * 0.99)] || 1;
      pmin = -pmax;
    } else {
      for (const v of pot) {
        if (v < pmin) pmin = v;
        if (v > pmax) pmax = v;
      }
      if (isDelta) {
        const m = Math.max(Math.abs(pmin), Math.abs(pmax), 1e-9);
        pmin = -m;
        pmax = m;
      }
    }
    const col = (v: number) =>
      isMag
        ? cmapSeq(Math.max(0, Math.min(1, Math.log(Math.max(v, pmin) / pmin) / Math.log(pmax / pmin))))
        : cmapDiv((v - pmin) / (pmax - pmin || 1));

    const visible: number[] = [];
    for (let i = 0; i < F.tris.length; i++) {
      if (F.conductor_of[i] >= 0) continue;
      const t = F.tris[i];
      const q = t.map((n) => F.nodes[n]);
      if (q.every((z) => X(z[0]) < -50 || X(z[0]) > canvas.width + 50 || Y(z[1]) < -50 || Y(z[1]) > canvas.height + 50)) {
        continue;
      }
      visible.push(i);
      const v = val ? val[i] : (pot[t[0]] + pot[t[1]] + pot[t[2]]) / 3;
      ctx.fillStyle = col(v);
      ctx.beginPath();
      ctx.moveTo(X(q[0][0]), Y(q[0][1]));
      ctx.lineTo(X(q[1][0]), Y(q[1][1]));
      ctx.lineTo(X(q[2][0]), Y(q[2][1]));
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = ctx.fillStyle;
      ctx.lineWidth = 0.6 * dpr;
      ctx.stroke();
    }
    if (isLines) {
      ctx.fillStyle = p.surface;
      ctx.globalAlpha = 0.62;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.globalAlpha = 1;
    }

    // contours: equipotentials, or magnetic field lines in the H view
    const lp = useAir ? F.phi_air : pot;
    let lmin = Infinity;
    let lmax = -Infinity;
    for (const v of lp) {
      if (v < lmin) lmin = v;
      if (v > lmax) lmax = v;
    }
    const nlev = isLines ? 0 : useAir ? 16 : 12;
    ctx.strokeStyle = useAir ? p.surface : p.text;
    ctx.globalAlpha = 0.45;
    ctx.lineWidth = dpr;
    ctx.beginPath();
    for (let k = 1; k < nlev; k++) {
      const lev = lmin + ((lmax - lmin) * k) / nlev;
      for (const i of visible) {
        const t = F.tris[i];
        const pts: [number, number][] = [];
        for (let e = 0; e < 3; e++) {
          const ia = t[e];
          const ib = t[(e + 1) % 3];
          const fa = lp[ia] - lev;
          const fb = lp[ib] - lev;
          if ((fa < 0 && fb >= 0) || (fa >= 0 && fb < 0)) {
            const sg = fa / (fa - fb);
            const pa = F.nodes[ia];
            const pb = F.nodes[ib];
            pts.push([X(pa[0] + sg * (pb[0] - pa[0])), Y(pa[1] + sg * (pb[1] - pa[1]))]);
          }
        }
        if (pts.length === 2) {
          ctx.moveTo(pts[0][0], pts[0][1]);
          ctx.lineTo(pts[1][0], pts[1][1]);
        }
      }
    }
    ctx.stroke();
    ctx.globalAlpha = 1;

    if (isLines) drawFieldLines(ctx, g, F, pot, X, Y, dpr, p);

    drawColourBar(ctx, canvas, dpr, p, isMag ? cmapSeq : cmapDiv, pmin, pmax, unitOf(view), isMag);
  }

  // geometry on top of the field
  const labels = new Map<string, { x: number; y: number; t: string; tall: number; area: number }>();
  for (const reg of g.regions) {
    ctx.beginPath();
    reg.points.forEach((q, i) => (i ? ctx.lineTo(X(q[0]), Y(q[1])) : ctx.moveTo(X(q[0]), Y(q[1]))));
    ctx.closePath();
    if (reg.kind === "conductor") {
      ctx.fillStyle = reg.role === "signal" ? p.signal : p.reference;
      ctx.fill();
      ctx.strokeStyle = p.text;
      ctx.setLineDash([]);
      const px = reg.points.map((q) => X(q[0]));
      const py = reg.points.map((q) => Y(q[1]));
      const tall = Math.max(...py) - Math.min(...py);
      const area = (Math.max(...px) - Math.min(...px)) * tall;
      const cand = {
        x: reg.role === "signal" ? (Math.min(...px) + Math.max(...px)) / 2 : Math.max(6 * dpr, Math.min(...px) + 4 * dpr),
        y: (Math.min(...py) + Math.max(...py)) / 2,
        t: reg.name,
        tall,
        area,
      };
      const prev = labels.get(reg.name);
      if (!prev || cand.area > prev.area) labels.set(reg.name, cand);
    } else if (reg.name === "mask") {
      ctx.fillStyle = p.mask;
      ctx.fill();
      ctx.strokeStyle = p.mask;
      ctx.setLineDash([]);
    } else {
      ctx.strokeStyle = p.muted;
      ctx.setLineDash([4 * dpr, 3 * dpr]);
    }
    ctx.lineWidth = dpr;
    ctx.stroke();
  }
  for (const ov of g.overlays ?? []) {
    ctx.beginPath();
    ov.points.forEach((q, i) => (i ? ctx.lineTo(X(q[0]), Y(q[1])) : ctx.moveTo(X(q[0]), Y(q[1]))));
    ctx.closePath();
    ctx.fillStyle = ov.kind === "finish" ? p.finish : p.muted;
    ctx.fill();
    ctx.strokeStyle = p.finish;
    ctx.setLineDash([]);
    ctx.lineWidth = dpr;
    ctx.stroke();
  }
  if (F && view === "Js") drawSurfaceCurrent(ctx, canvas, g, F, X, Y, dpr, p);

  ctx.setLineDash([]);
  ctx.font = `${11 * dpr}px system-ui, sans-serif`;
  for (const l of labels.values()) {
    if (l.x < 0 || l.x > canvas.width || l.y < 0 || l.y > canvas.height) continue;
    const w = ctx.measureText(l.t).width;
    const yy = l.tall >= 12 * dpr ? l.y + 4 * dpr : l.y - 6 * dpr;
    ctx.fillStyle = p.surface;
    ctx.globalAlpha = 0.85;
    ctx.fillRect(l.x - 2 * dpr, yy - 10 * dpr, w + 4 * dpr, 13 * dpr);
    ctx.globalAlpha = 1;
    ctx.fillStyle = p.text;
    ctx.fillText(l.t, l.x, yy);
  }
  const bar = niceStep(halfw / 2);
  ctx.fillStyle = p.text;
  ctx.fillRect(12 * dpr, canvas.height - 18 * dpr, X(a.viewport.cx + bar) - X(a.viewport.cx), 3 * dpr);
  ctx.font = `${12 * dpr}px system-ui, sans-serif`;
  ctx.fillText(`${bar} mm`, 12 * dpr, canvas.height - 24 * dpr);
  if (a.label) {
    ctx.fillStyle = p.muted;
    ctx.font = `${11 * dpr}px system-ui, sans-serif`;
    ctx.fillText(a.label, 12 * dpr, 14 * dpr);
  }
}

const unitOf = (v: FieldView): string => (v === "H" || v === "Hx" ? " A/m" : v === "E" || v === "Elines" || v === "Ey" ? " V/m" : " V");

function drawColourBar(
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  dpr: number,
  p: Palette,
  cmap: (t: number) => string,
  pmin: number,
  pmax: number,
  unit: string,
  log: boolean,
): void {
  const bx = canvas.width - 26 * dpr;
  const by = 16 * dpr;
  const bh = canvas.height - 60 * dpr;
  for (let i = 0; i < bh; i++) {
    ctx.fillStyle = cmap(1 - i / bh);
    ctx.fillRect(bx, by + i, 14 * dpr, 1);
  }
  ctx.strokeStyle = p.line;
  ctx.lineWidth = dpr;
  ctx.strokeRect(bx, by, 14 * dpr, bh);
  const fm = (v: number) => (Math.abs(v) >= 1000 ? `${(v / 1000).toPrecision(3)}k` : v.toPrecision(3));
  ctx.fillStyle = p.text;
  ctx.font = `${11 * dpr}px system-ui, sans-serif`;
  ctx.textAlign = "right";
  ctx.fillText(fm(pmax) + unit + (log ? " (log)" : ""), bx - 4 * dpr, by + 10 * dpr);
  ctx.fillText(fm(pmin) + unit, bx - 4 * dpr, by + bh);
  ctx.textAlign = "left";
}

// --------------------------------------------------------------- field lines

interface Locator {
  bins: (number[] | undefined)[];
  bi: (x: number, y: number) => number;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

function triLocator(F: FsField): Locator {
  let x0 = Infinity;
  let x1 = -Infinity;
  let y0 = Infinity;
  let y1 = -Infinity;
  for (const n of F.nodes) {
    if (n[0] < x0) x0 = n[0];
    if (n[0] > x1) x1 = n[0];
    if (n[1] < y0) y0 = n[1];
    if (n[1] > y1) y1 = n[1];
  }
  const nb = 90;
  const dx = (x1 - x0) / nb || 1;
  const dy = (y1 - y0) / nb || 1;
  const bins: (number[] | undefined)[] = new Array(nb * nb);
  const bi = (x: number, y: number) =>
    Math.max(0, Math.min(nb - 1, Math.floor((x - x0) / dx))) + nb * Math.max(0, Math.min(nb - 1, Math.floor((y - y0) / dy)));
  for (let t = 0; t < F.tris.length; t++) {
    const q = F.tris[t].map((n) => F.nodes[n]);
    const ax = Math.min(q[0][0], q[1][0], q[2][0]);
    const bx = Math.max(q[0][0], q[1][0], q[2][0]);
    const ay = Math.min(q[0][1], q[1][1], q[2][1]);
    const by = Math.max(q[0][1], q[1][1], q[2][1]);
    for (let i = Math.floor((ax - x0) / dx); i <= Math.floor((bx - x0) / dx); i++) {
      for (let j = Math.floor((ay - y0) / dy); j <= Math.floor((by - y0) / dy); j++) {
        const k = Math.max(0, Math.min(nb - 1, i)) + nb * Math.max(0, Math.min(nb - 1, j));
        (bins[k] || (bins[k] = [])).push(t);
      }
    }
  }
  return { bins, bi, x0, x1, y0, y1 };
}

function triAt(F: FsField, loc: Locator, x: number, y: number): number {
  if (x < loc.x0 || x > loc.x1 || y < loc.y0 || y > loc.y1) return -1;
  for (const t of loc.bins[loc.bi(x, y)] ?? []) {
    const [a, b, c] = F.tris[t];
    const A = F.nodes[a];
    const B = F.nodes[b];
    const C = F.nodes[c];
    const d = (B[1] - C[1]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[1] - C[1]);
    const l1 = ((B[1] - C[1]) * (x - C[0]) + (C[0] - B[0]) * (y - C[1])) / d;
    const l2 = ((C[1] - A[1]) * (x - C[0]) + (A[0] - C[0]) * (y - C[1])) / d;
    if (l1 >= -1e-9 && l2 >= -1e-9 && l1 + l2 <= 1 + 1e-9) return t;
  }
  return -1;
}

function gradIn(F: FsField, phi: number[], t: number): [number, number] {
  const [a, b, c] = F.tris[t];
  const A = F.nodes[a];
  const B = F.nodes[b];
  const C = F.nodes[c];
  const det = (B[0] - A[0]) * (C[1] - A[1]) - (C[0] - A[0]) * (B[1] - A[1]);
  return [
    ((B[1] - C[1]) * phi[a] + (C[1] - A[1]) * phi[b] + (A[1] - B[1]) * phi[c]) / det,
    ((C[0] - B[0]) * phi[a] + (A[0] - C[0]) * phi[b] + (B[0] - A[0]) * phi[c]) / det,
  ];
}

/** Streamlines of E = -grad(phi), seeded around every signal conductor. Each seed
 *  runs whichever way the field points AWAY from that copper: E leaves a conductor
 *  above the reference potential and enters one below it, so a single fixed
 *  direction would leave the negative trace of a pair almost bare. */
function drawFieldLines(
  ctx: CanvasRenderingContext2D,
  g: FsGeometry,
  F: FsField,
  pot: number[],
  X: (x: number) => number,
  Y: (y: number) => number,
  dpr: number,
  p: Palette,
): void {
  const loc = triLocator(F);
  const span = Math.max(g.xmax - g.xmin, g.ymax - g.ymin);
  const off = span * 4e-4;
  const step = span * 2e-3;
  ctx.strokeStyle = p.text;
  ctx.globalAlpha = 0.8;
  ctx.lineWidth = 1.2 * dpr;
  ctx.beginPath();
  for (const reg of g.regions.filter((r) => r.kind === "conductor" && r.role === "signal")) {
    const pts = reg.points;
    const segs: { a: [number, number]; b: [number, number]; L: number }[] = [];
    let peri = 0;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i];
      const b = pts[(i + 1) % pts.length];
      const L = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (L > 0) {
        segs.push({ a, b, L });
        peri += L;
      }
    }
    const cx = pts.reduce((s, q) => s + q[0], 0) / pts.length;
    const cy = pts.reduce((s, q) => s + q[1], 0) / pts.length;
    const n = 26;
    for (let k = 0; k < n; k++) {
      let d = ((k + 0.5) / n) * peri;
      const sg = segs.find((s) => (d -= s.L) <= 0) ?? segs[segs.length - 1];
      const tp = Math.max(0, Math.min(1, (sg.L + d) / sg.L));
      const px = sg.a[0] + tp * (sg.b[0] - sg.a[0]);
      const py = sg.a[1] + tp * (sg.b[1] - sg.a[1]);
      let nx = -(sg.b[1] - sg.a[1]) / sg.L;
      let ny = (sg.b[0] - sg.a[0]) / sg.L;
      if ((px - cx) * nx + (py - cy) * ny < 0) {
        nx = -nx;
        ny = -ny;
      }
      let x = px + off * nx;
      let y = py + off * ny;
      const t0 = triAt(F, loc, x, y);
      if (t0 < 0 || F.conductor_of[t0] >= 0) continue;
      const gr = gradIn(F, pot, t0);
      const sign = -gr[0] * nx - gr[1] * ny >= 0 ? 1 : -1;
      ctx.moveTo(X(x), Y(y));
      for (let i = 0; i < 900; i++) {
        const t = triAt(F, loc, x, y);
        if (t < 0 || F.conductor_of[t] >= 0) break;
        const gg = gradIn(F, pot, t);
        const m = Math.hypot(gg[0], gg[1]);
        if (!m) break;
        x += (step * -sign * gg[0]) / m;
        y += (step * -sign * gg[1]) / m;
        ctx.lineTo(X(x), Y(y));
      }
    }
  }
  ctx.stroke();
  ctx.globalAlpha = 1;
}

/** Surface current density on the copper: Js = eps0*c*|grad(phi_air)| at the
 *  conductor surface — the same quantity the conductor-loss integral uses. */
function drawSurfaceCurrent(
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  g: FsGeometry,
  F: FsField,
  X: (x: number) => number,
  Y: (y: number) => number,
  dpr: number,
  p: Palette,
): void {
  const EPS0C = 8.8541878e-12 * 299792458;
  const loc = triLocator(F);
  const span = Math.max(g.xmax - g.xmin, g.ymax - g.ymin);
  const off = span * 4e-4;
  const segs: { x0: number; y0: number; x1: number; y1: number; js: number }[] = [];
  for (const reg of g.regions.filter((r) => r.kind === "conductor")) {
    const pts = reg.points;
    const cx = pts.reduce((s, q) => s + q[0], 0) / pts.length;
    const cy = pts.reduce((s, q) => s + q[1], 0) / pts.length;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i];
      const b = pts[(i + 1) % pts.length];
      const L = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (!L) continue;
      let nx = -(b[1] - a[1]) / L;
      let ny = (b[0] - a[0]) / L;
      if ((0.5 * (a[0] + b[0]) - cx) * nx + (0.5 * (a[1] + b[1]) - cy) * ny < 0) {
        nx = -nx;
        ny = -ny;
      }
      const px = Math.hypot(X(b[0]) - X(a[0]), Y(b[1]) - Y(a[1]));
      const n = Math.max(1, Math.min(400, Math.round(px / (3 * dpr))));
      for (let k = 0; k < n; k++) {
        const t0 = k / n;
        const t1 = (k + 1) / n;
        const tm = (t0 + t1) / 2;
        const mx = a[0] + tm * (b[0] - a[0]) + off * nx;
        const my = a[1] + tm * (b[1] - a[1]) + off * ny;
        const tt = triAt(F, loc, mx, my);
        if (tt < 0 || F.conductor_of[tt] >= 0) continue;
        const gr = gradIn(F, F.phi_air, tt);
        segs.push({
          x0: a[0] + t0 * (b[0] - a[0]),
          y0: a[1] + t0 * (b[1] - a[1]),
          x1: a[0] + t1 * (b[0] - a[0]),
          y1: a[1] + t1 * (b[1] - a[1]),
          js: EPS0C * Math.hypot(gr[0], gr[1]) * 1e3,
        });
      }
    }
  }
  if (!segs.length) return;
  const sorted = segs.map((s) => s.js).sort((x, y) => x - y);
  const jmax = sorted[Math.floor(sorted.length * 0.99)] || 1;
  const jmin = jmax / 300;
  const cmap = sequential(p);
  ctx.lineCap = "round";
  ctx.setLineDash([]);
  for (const sg of segs) {
    const t = Math.max(0, Math.min(1, Math.log(Math.max(sg.js, jmin) / jmin) / Math.log(jmax / jmin)));
    ctx.strokeStyle = cmap(t);
    ctx.lineWidth = (1.6 + 4.4 * t * t) * dpr;
    ctx.beginPath();
    ctx.moveTo(X(sg.x0), Y(sg.y0));
    ctx.lineTo(X(sg.x1), Y(sg.y1));
    ctx.stroke();
  }
  drawColourBar(ctx, canvas, dpr, p, cmap, jmin, jmax, " A/m", true);
}
