"""Goal seek, parameter sweeps, sensitivity and tolerance on top of `solve`."""
from __future__ import annotations

import dataclasses
import math

import numpy as np

from .analysis import SolveOptions, solve
from .templates import Params, build

FAST = dict(f_sweep=[], return_field=False, refine_passes=2, max_nodes=30000)


def quick(p: Params, f_design: float, key: str) -> float:
    r = solve(build(p), SolveOptions(f_design=f_design, **FAST))
    return r["summary"][key]


def goal_seek(p: Params, f_design: float, key: str, target: float, var: str,
              lo: float, hi: float, tol: float = 0.002, max_iter: int = 20, progress=None) -> dict:
    """Find `var` in [lo, hi] so that summary[key] == target. Bisection on a
    monotonic response, then a secant polish. Returns the value and the trace."""
    trace = []

    def f(x):
        if progress:
            progress(f"solve {len(trace)+1}: {var} = {x:.4f} mm", min(0.95, len(trace) / 10), "seek")
        q = dataclasses.replace(p, **{var: x})
        y = quick(q, f_design, key)
        trace.append({var: x, key: y})
        if progress:
            progress(f"solve {len(trace)}: {var} = {x:.4f} mm -> {key} = {y:.2f}", min(0.95, len(trace) / 10), "seek")
        return y - target

    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return {"ok": False, "reason": f"target not bracketed: {key}({lo})={flo+target:.2f}, {key}({hi})={fhi+target:.2f}", "trace": trace}
    a, b, fa, fb = lo, hi, flo, fhi
    for _ in range(max_iter):
        # regula falsi with bisection safeguard (Illinois)
        x = b - fb * (b - a) / (fb - fa)
        if not (min(a, b) < x < max(a, b)):
            x = 0.5 * (a + b)
        fx = f(x)
        if abs(fx) <= tol * abs(target):
            return {"ok": True, var: x, key: fx + target, "trace": trace}
        if fx * fa < 0:
            b, fb = x, fx
            fa *= 0.5
        else:
            a, fa = x, fx
            fb *= 0.5
    return {"ok": True, var: x, key: fx + target, "trace": trace, "warning": "max iterations"}


def sweep(p: Params, f_design: float, var: str, values: list[float], keys: list[str]) -> list[dict]:
    out = []
    for x in values:
        q = dataclasses.replace(p, **{var: x})
        r = solve(build(q), SolveOptions(f_design=f_design, **FAST))
        row = {var: x}
        row.update({k: r["summary"].get(k) for k in keys})
        out.append(row)
    return out


def sensitivity(p: Params, f_design: float, key: str, vars_rel: dict[str, float]) -> dict:
    """d(key)/d(var) by central differences. vars_rel: var -> absolute step."""
    base = quick(p, f_design, key)
    out = {"base": base, "d": {}}
    for var, h in vars_rel.items():
        x0 = getattr(p, var)
        yp = quick(dataclasses.replace(p, **{var: x0 + h}), f_design, key)
        ym = quick(dataclasses.replace(p, **{var: max(x0 - h, 1e-4)}), f_design, key)
        out["d"][var] = (yp - ym) / (x0 + h - max(x0 - h, 1e-4))
    return out


def tolerance(p: Params, f_design: float, key: str, tol: dict[str, float]) -> dict:
    """Worst-case and RSS spread of `key` for absolute tolerances on parameters.
    Dielectric thickness/Dk tolerances are applied through custom_stackup scaling."""
    sens = sensitivity(p, f_design, key, {v: t for v, t in tol.items() if hasattr(p, v)})
    terms = {v: abs(sens["d"][v] * t) for v, t in tol.items() if v in sens["d"]}
    return {"base": sens["base"], "terms": terms,
            "worst_case": sum(terms.values()),
            "rss": math.sqrt(sum(t * t for t in terms.values())),
            "sensitivity": sens["d"]}


def required_cutout(p: Params, f_design: float, key: str, tol: float = 0.01, progress=None) -> dict:
    """Smallest cutout in the intermediate layers for which Z is within `tol`
    of Z with those layers fully removed."""
    from .stackups import STACKS
    st = STACKS.custom(p.custom_stackup) if p.custom_stackup else STACKS.get(p.stackup)
    sig = st.index(p.signal_layer)
    dists = []
    for n in p.reference_layers:
        r = st.layer(n); sl = st.layer(p.signal_layer)
        dists.append(abs(r["y_top"] - sl["y_bottom"]) if r["y_top"] <= sl["y_bottom"] else abs(r["y_bottom"] - sl["y_top"]))
    h = min(dists) if dists else 0.2
    if progress:
        progress("reference: intermediate layer removed", 0.05, "ref")
    z_inf = quick(dataclasses.replace(p, cutout_mode="remove"), f_design, key)
    span = p.w if not p.template.startswith("diff") else 2 * p.w + p.s
    curve = []

    def z_at(c):
        z = quick(dataclasses.replace(p, cutout_mode="width", cutout=c), f_design, key)
        curve.append({"cutout": c, key: z, "dev_pct": 100 * (z - z_inf) / z_inf})
        if progress:
            progress(f"cutout {c:.3f} mm -> {key} = {z:.2f} ({curve[-1]['dev_pct']:+.2f} %)", min(0.9, 0.1 + 0.08 * len(curve)), "march")
        return z

    # geometric march up from the trace span, then bisect
    lo, hi = None, None
    c = span + 0.05
    for _ in range(10):
        z = z_at(c)
        if abs(z - z_inf) / z_inf <= tol:
            hi = c; break
        lo = c
        c = c * 1.5 + h
    if hi is None:
        return {"ok": False, "reason": "no cutout up to %.2f mm reached the tolerance" % c, "z_removed": z_inf, "curve": curve}
    if lo is None:
        return {"ok": True, "cutout": hi, "z_removed": z_inf, "curve": curve, "note": "already inside tolerance at the smallest opening tested"}
    for _ in range(6):
        mid = 0.5 * (lo + hi)
        if abs(z_at(mid) - z_inf) / z_inf <= tol:
            hi = mid
        else:
            lo = mid
        if hi - lo < 0.02:
            break
    return {"ok": True, "cutout": round(hi, 3), "z_removed": z_inf, "curve": curve, "tolerance_pct": 100 * tol}
