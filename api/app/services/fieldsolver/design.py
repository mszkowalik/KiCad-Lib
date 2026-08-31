"""Design mode: target impedance in, a table of candidate geometries out.

The user fixes stackup, layers, structure and target. The solver varies the
secondary parameter (coplanar gap, pair spacing) over a fab-friendly set and
finds the width for each, with and without solder mask on outer layers.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

# Each worker holds a mesh and its factorisation, so an unbounded pool on a 10-core
# machine can take tens of gigabytes. Cap it, and override with FIELDSOLVER_WORKERS.
WORKERS = max(1, min(int(os.environ.get("FIELDSOLVER_WORKERS", 4)), (os.cpu_count() or 2)))


def kill_stray_workers() -> None:
    """Terminate pool workers left behind by a cancelled or crashed search.

    Each worker holds a mesh and its factorisation, so a leaked one costs hundreds of
    megabytes; a fleet of them once took 40 GB and pushed the machine into swap.
    """
    import signal
    import subprocess

    try:
        pids = subprocess.run(["pgrep", "-P", str(os.getpid())], capture_output=True, text=True).stdout.split()
        for pid in pids:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
            if "multiprocessing.spawn" in cmd:
                os.kill(int(pid), signal.SIGTERM)
                os.waitpid(int(pid), os.WNOHANG)
    except Exception:
        pass


def _stop_pool(ex, futs):
    """Cancel what has not started and make sure no worker outlives the request."""
    for f in futs:
        f.cancel()
    procs = list(getattr(ex, "_processes", {}).values())
    for proc in procs:
        if proc.is_alive():
            proc.terminate()
    for proc in procs:                       # reap the zombies, do not just signal them
        try:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=2)
        except Exception:
            pass
    ex.shutdown(wait=False, cancel_futures=True)

from .analysis import SolveOptions, solve
from .templates import Params, build

COARSE = dict(f_sweep=[], return_field=False, refine_passes=1, max_nodes=15000, initial_elements=1500)
GAPS = [0.15, 0.2, 0.25, 0.3, 0.4, 0.5]
SPACINGS = [0.1, 0.15, 0.2, 0.25, 0.3, 0.4]
DIFF_CPW = [(0.15, 0.2), (0.2, 0.2), (0.2, 0.3), (0.3, 0.3), (0.2, 0.4), (0.3, 0.5)]


def _key(template: str) -> str:
    return "Zdiff" if template.startswith("diff") else "Z0"


def _row(args):
    p, f, key, target, w_lo, w_hi, min_w = args
    trace = []

    def f_of(w):
        q = dataclasses.replace(p, w=w)
        r = solve(build(q), SolveOptions(f_design=f, **COARSE))
        trace.append((w, r["summary"][key], r["summary"]))
        return r["summary"][key] - target

    a, b = w_lo, w_hi
    fa, fb = f_of(a), f_of(b)
    ok = fa * fb < 0
    if ok:
        for _ in range(12):
            x = b - fb * (b - a) / (fb - fa)
            if not (min(a, b) < x < max(a, b)):
                x = 0.5 * (a + b)
            fx = f_of(x)
            if abs(fx) < 0.003 * target:
                break
            if fx * fa < 0:
                b, fb = x, fx; fa *= 0.5
            else:
                a, fa = x, fx; fb *= 0.5
    w, z, s = min(trace, key=lambda t: abs(t[1] - target))
    # sensitivity from the two closest points
    tr = sorted(trace, key=lambda t: abs(t[0] - w))[:2]
    dzdw = (tr[1][1] - tr[0][1]) / (tr[1][0] - tr[0][0]) if len(tr) == 2 and tr[1][0] != tr[0][0] else None
    row = {"w": round(w, 4), key: z, "ok": ok and abs(z - target) < 0.02 * target,
           "feasible": w >= min_w, "dZ_dw": dzdw, "solves": len(trace),
           "s": p.s if p.template.startswith("diff") else None,
           "gap": p.gap if p.template in ("cpw", "diff_cpw") else None,
           "soldermask": p.soldermask, "via_fence": p.via_fence}
    for k in ("eps_eff", "alpha_db_m", "eps_eff_odd", "alpha_odd_db_m", "Z0_single", "coupling_k", "Zodd", "Zeven", "Zcomm", "Z0"):
        if k in s:
            row[k] = s[k]
    return row


def design(base: Params, f: float, target: float, min_w: float = 0.09, min_gap: float = 0.09,
           w_lo: float = 0.06, w_hi: float = 4.0, masks: tuple[bool, ...] | None = None, progress=None) -> dict:
    key = _key(base.template)
    from .stackups import STACKS
    st = STACKS.custom(base.custom_stackup) if base.custom_stackup else STACKS.get(base.stackup)
    outer = st.index(base.signal_layer) == 0
    mask_opts = masks if masks is not None else ((True, False) if outer and st.soldermask else (False,))
    variants = []
    for m in mask_opts:
        if base.template == "microstrip":
            variants.append(dataclasses.replace(base, soldermask=m))
        elif base.template == "cpw":
            variants += [dataclasses.replace(base, soldermask=m, gap=g) for g in GAPS if g >= min_gap]
        elif base.template == "diff":
            variants += [dataclasses.replace(base, soldermask=m, s=s) for s in SPACINGS if s >= min_gap]
        elif base.template == "diff_cpw":
            variants += [dataclasses.replace(base, soldermask=m, s=s, gap=g) for s, g in DIFF_CPW if s >= min_gap and g >= min_gap]
    jobs = [(v, f, key, target, w_lo, w_hi, min_w) for v in variants]
    rows = [None] * len(jobs)
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(_row, j): i for i, j in enumerate(jobs)}
        done = 0
        for fut in as_completed(futs):
            rows[futs[fut]] = fut.result()
            done += 1
            if progress:
                progress(f"option {done}/{len(jobs)} solved", done / len(jobs), "variants")
    return {"key": key, "target": target, "rows": rows,
            "note": "Coarse mesh (about 0.5 % on Z). Pick a row and Solve for the full result."}


def _snap_rows(args):
    """One secondary-parameter variant: continuous solution, then grid neighbours."""
    p, f, key, target, w_lo, w_hi, step, tol_pct = args
    trace = []

    def z_of(w):
        for t in trace:
            if abs(t[0] - w) < 1e-9:
                return t[1], t[2]
        q = dataclasses.replace(p, w=w)
        r = solve(build(q), SolveOptions(f_design=f, **COARSE))
        trace.append((w, r["summary"][key], r["summary"]))
        return r["summary"][key], r["summary"]

    rows = []
    if step:
        # W lands on the grid anyway: bisect directly over the grid points
        # (secant-guided), so every solve is already a final candidate.
        ws = _grid(w_lo, w_hi, step)
        if len(ws) == 1:
            z, s = z_of(ws[0])
            rows.append(_mk(p, ws[0], z, s, key, target, tol_pct, len(trace), snapped=True))
            return rows
        lo, hi = 0, len(ws) - 1
        fa, fb = z_of(ws[lo])[0] - target, z_of(ws[hi])[0] - target
        if fa * fb > 0:
            k = lo if abs(fa) < abs(fb) else hi
            z, s = z_of(ws[k])
            rows.append(_mk(p, ws[k], z, s, key, target, tol_pct, len(trace), snapped=True))
            return rows
        while hi - lo > 1:
            t = fa / (fa - fb)
            k = max(lo + 1, min(hi - 1, lo + int(round(t * (hi - lo)))))
            fk = z_of(ws[k])[0] - target
            if fk * fa <= 0:
                hi, fb = k, fk
            else:
                lo, fa = k, fk
        for k in (lo, hi):
            z, s = z_of(ws[k])
            rows.append(_mk(p, ws[k], z, s, key, target, tol_pct, len(trace), snapped=True))
        return rows
    a, b = w_lo, w_hi
    fa, fb = z_of(a)[0] - target, z_of(b)[0] - target
    if fa * fb > 0:
        # no crossing in range: report the closer end
        w, (z, s) = (a, z_of(a)) if abs(fa) < abs(fb) else (b, z_of(b))
        rows.append(_mk(p, w, z, s, key, target, tol_pct, len(trace), snapped=False))
        return rows
    for _ in range(10):
        x = b - fb * (b - a) / (fb - fa)
        if not (min(a, b) < x < max(a, b)):
            x = 0.5 * (a + b)
        fx = z_of(x)[0] - target
        if abs(fx) < 0.003 * target or abs(b - a) < (step or 0.002) / 4:
            break
        if fx * fa < 0:
            b, fb = x, fx; fa *= 0.5
        else:
            a, fa = x, fx; fb *= 0.5
    w_star = min(trace, key=lambda t: abs(t[1] - target))[0]
    z, s = z_of(w_star)
    rows.append(_mk(p, w_star, z, s, key, target, tol_pct, len(trace), snapped=False))
    return rows


def _mk(p, w, z, s, key, target, tol_pct, n, snapped):
    dev = 100 * (z - target) / target
    row = {"w": round(w, 4), key: z, "dev_pct": dev, "within": abs(dev) <= tol_pct, "snapped": snapped, "solves": n,
           "s": p.s if p.template.startswith("diff") else None,
           "gap": p.gap if p.template in ("cpw", "diff_cpw") else None,
           "fence_distance": p.fence_distance if p.via_fence else None,
           "via_rows": list(p.via_rows) if p.via_fence and p.via_rows else None,
           "soldermask": p.soldermask}
    for k in ("eps_eff", "alpha_db_m", "eps_eff_odd", "alpha_odd_db_m", "Z0_single", "coupling_k", "Zodd", "Zeven", "Zcomm"):
        if k in s:
            row[k] = s[k]
    return row


def _grid(lo, hi, step):
    if not step:
        return [lo, 0.5 * (lo + hi), hi] if hi > lo else [lo]
    n0, n1 = math.ceil(lo / step - 1e-9), math.floor(hi / step + 1e-9)
    return [round(k * step, 6) for k in range(n0, n1 + 1)] or [lo]


def search(base: Params, f: float, target: float, tol_pct: float, ranges: dict, step: float | None,
           masks: tuple[bool, ...], max_variants: int = 36, progress=None) -> dict:
    """Enumerate S / gap on the grid inside their allowed ranges, find W for each,
    snap W to the grid, and return every candidate sorted by deviation."""
    key = _key(base.template)
    w_lo, w_hi = ranges.get("w", [0.06, 4.0])
    variants = []
    for m in masks:
        b = dataclasses.replace(base, soldermask=m)
        if base.template == "microstrip":
            variants.append(b)
        elif base.template == "cpw":
            variants += [dataclasses.replace(b, gap=g) for g in _grid(*ranges.get("gap", [0.15, 0.5]), step)]
        elif base.template == "diff":
            variants += [dataclasses.replace(b, s=s) for s in _grid(*ranges.get("s", [0.1, 0.4]), step)]
        else:
            variants += [dataclasses.replace(b, s=s, gap=g) for s in _grid(*ranges.get("s", [0.1, 0.4]), step)
                         for g in _grid(*ranges.get("gap", [0.15, 0.5]), step)]
    if base.via_fence and "fence" in ranges and getattr(base, "fence_from_range", True):
        variants = [dataclasses.replace(v, fence_distance=d) for v in variants for d in _grid(*ranges["fence"], step)]
    if base.via_fence and any(o is None for o in base.via_rows):
        pitches = _grid(*ranges.get("rowpitch", [base.via_pad + 0.2, 2 * (base.via_pad + 0.2)]), step)
        import itertools
        idx = [k for k, o in enumerate(base.via_rows) if o is None]
        expanded = []
        for v in variants:
            for combo in itertools.product(pitches, repeat=len(idx)):
                rows = list(v.via_rows)
                for k, val in zip(idx, combo):
                    rows[k] = val
                expanded.append(dataclasses.replace(v, via_rows=rows))
        variants = expanded
    dropped = 0
    if len(variants) > max_variants:
        keep = np.linspace(0, len(variants) - 1, max_variants).round().astype(int)
        dropped = len(variants) - max_variants
        variants = [variants[i] for i in sorted(set(keep))]
    jobs = [(v, f, key, target, w_lo, w_hi, step, tol_pct) for v in variants]
    rows = []
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(_snap_rows, j) for j in jobs]
        try:
            for k, fut in enumerate(as_completed(futs)):
                rows += fut.result()
                if progress:
                    # progress raises when the job is cancelled: drop the pending work with it
                    progress(f"variant {k+1}/{len(jobs)} solved", (k + 1) / len(jobs), "variants")
        except BaseException:
            _stop_pool(ex, futs)
            raise
    # rank: within tolerance first, then fewest decimals (rounder), then deviation
    def decimals(x):
        s = f"{x:.4f}".rstrip("0").rstrip(".")
        return len(s.split(".")[1]) if "." in s else 0
    rows.sort(key=lambda r: (not r["within"], decimals(r["w"]) + decimals(r["s"] or 0) + decimals(r["gap"] or 0) + decimals(r["fence_distance"] or 0), abs(r["dev_pct"])))
    return {"key": key, "target": target, "tolerance_pct": tol_pct, "step": step, "rows": rows,
            "note": ("Coarse mesh (about 0.5 % on Z). " + (f"{dropped} variants dropped to stay under {max_variants}. " if dropped else "")
                     + "Pick a row and recalculate for the full result.")}
