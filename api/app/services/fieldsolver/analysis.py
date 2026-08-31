"""Line parameters from the FEM solution: C, L, modes, impedance, loss."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import fem, mesh as meshing
from .geometry import Geometry
from .materials import C0, EPS0, LIB, MU0

MM = 1e-3


@dataclass
class SolveOptions:
    f_design: float = 2.4e9
    f_sweep: list[float] = field(default_factory=lambda: list(np.geomspace(1e7, 3e9, 9)))
    eps_model: str = "djordjevic"          # or "constant"
    refine_passes: int = 3
    refine_fraction: float = 0.15
    max_nodes: int = 60000
    initial_elements: int = 2000
    return_field: bool = True


def _region_eps(geo: Geometry, f: float, model: str):
    """(eps, tand) per region index at frequency f. Air = (1, 0)."""
    out = []
    for r in geo.regions:
        if r.kind == "conductor":
            out.append((1.0, 0.0))
        elif r.material:
            d = LIB.get(r.material).at(f, model)
            out.append((d.eps, d.tand))
        else:
            out.append((r.eps, r.tand))
    return out


def _element_props(geo, msh, f, model, air=False):
    reps = _region_eps(geo, f, model)
    eps = np.ones(len(msh.tris))
    tand = np.zeros(len(msh.tris))
    if not air:
        for ei, ri in enumerate(msh.region_of):
            if ri >= 0:
                eps[ei], tand[ei] = reps[ri]
    return eps, tand


def _solve_all(geo, msh, f, model, air, pre=None):
    """Unit-voltage solutions for every signal conductor (others 0).

    `pre` reuses an existing factorisation as a preconditioner instead of building a new
    sparse LU - see fem.Solver. One LU per run rather than one per sweep point."""
    eps, tand = _element_props(geo, msh, f, model, air)
    K = fem.assemble(msh, eps)
    S = fem.Solver(msh, K, pre)
    sig = [msh.conductors.index(n) for n in geo.signal_names]
    Phi = []
    for k in sig:
        v = np.zeros(len(msh.conductors))
        v[k] = 1.0
        Phi.append(S.solve(v))
    Phi = np.array(Phi)                   # (N, n)
    Cmat = EPS0 * (Phi @ (K @ Phi.T))     # F/m, energy form, symmetric
    return Phi, Cmat, K, eps, tand, sig, S


def _adapt(geo, msh, opts, progress=None):
    """Refine where the field energy concentrates (design freq + air)."""
    for k in range(opts.refine_passes):
        if msh.n_nodes > opts.max_nodes:
            break
        if progress:
            progress(f"mesh refinement {k+1}/{opts.refine_passes} ({msh.n_nodes} nodes)", 0.05 + 0.1 * k, "refine")
        e = np.zeros(len(msh.tris))
        for air in (False, True):
            Phi, *_ = _solve_all(geo, msh, opts.f_design, opts.eps_model, air)
            for phi in Phi:
                e += fem.element_energy(msh, phi)
        # refine the elements holding the top `refine_fraction` of energy
        order = np.argsort(e)[::-1]
        cum = np.cumsum(e[order]) / max(e.sum(), 1e-300)
        n_ref = int(np.searchsorted(cum, 1 - opts.refine_fraction)) + 1
        n_ref = max(n_ref, int(0.05 * len(e)))
        new_area = msh.area.copy()
        new_area[order[:n_ref]] = msh.area[order[:n_ref]] / 4.0
        nxt = meshing.refine(geo, msh, new_area)
        if nxt.n_nodes > opts.max_nodes * 1.5:
            return msh
        msh = nxt
    return msh


def _modes(Cmat, C0mat):
    L = MU0 * EPS0 * np.linalg.inv(C0mat)
    lam, V = np.linalg.eig(L @ Cmat)
    lam, V = lam.real, V.real
    vp = 1 / np.sqrt(lam)
    modes = []
    for m in range(len(lam)):
        v = V[:, m]
        v = v / np.max(np.abs(v))
        i = vp[m] * (Cmat @ v)
        modes.append({"v": v, "i": i, "vp": vp[m], "eps_eff": (C0 / vp[m]) ** 2})
    return L, modes


def _rs(f, sigma, roughness_um):
    rs = math.sqrt(math.pi * f * MU0 / sigma)
    if roughness_um > 0:
        delta = 1 / math.sqrt(math.pi * f * MU0 * sigma)
        rs *= 1 + (2 / math.pi) * math.atan(1.4 * (roughness_um * 1e-6 / delta) ** 2)
    return rs


def _conductor_props(geo, msh):
    sigma = np.full(len(msh.conductors), 5.8e7)
    rough = np.zeros(len(msh.conductors))
    area = np.zeros(len(msh.conductors))
    for r in geo.regions:
        if r.kind == "conductor":
            k = msh.conductors.index(r.name)
            sigma[k] = r.sigma
            rough[k] = r.roughness_um
    for ei, k in enumerate(msh.conductor_of):
        if k >= 0:
            area[k] += msh.area[ei] * MM * MM
    return sigma, rough, area


def line_parameters(geo: Geometry, msh, f, opts, edges, cprops, C0mat, Phi0, sig, pre=None):
    """Everything at one frequency f. `pre` reuses an existing factorisation."""
    Phi, Cmat, K, eps, tand, _, S = _solve_all(geo, msh, f, opts.eps_model, air=False, pre=pre)
    L, modes = _modes(Cmat, C0mat)
    els, conds, lens, normals = edges
    sigma, rough, carea = cprops
    w = 2 * math.pi * f
    out_modes = []
    for md in modes:
        v, i = md["v"], md["i"]
        P = 0.5 * float(v @ i)
        # dielectric loss from the real-medium field
        phi = v @ Phi
        e_el = fem.element_energy(msh, phi)
        Pd = 0.5 * w * EPS0 * float((tand * eps * e_el).sum())
        # conductor loss from the air-medium field carrying the mode currents
        u = np.linalg.solve(C0mat, i) / C0
        phi_air = u @ Phi0
        g = fem.element_grad(msh, phi_air)             # V/mm
        en = (g[els] * normals).sum(axis=1) / MM       # V/m
        js2 = (C0 * EPS0 * en) ** 2 * lens * MM        # A^2/m per edge
        Pc = 0.0
        per_cond = {}
        for k in range(len(msh.conductors)):
            sel = conds == k
            if not sel.any():
                continue
            pac = 0.5 * _rs(f, sigma[k], rough[k]) * js2[sel].sum()
            # DC floor for signal conductors: R_dc * I^2 / 2
            name = msh.conductors[k]
            if name in geo.signal_names:
                Ik = abs(i[geo.signal_names.index(name)])
                pdc = 0.5 * Ik ** 2 / (sigma[k] * carea[k])
                pac = math.sqrt(pac ** 2 + pdc ** 2)
            per_cond[name] = pac
            Pc += pac
        alpha_c = Pc / (2 * P) if P > 0 else 0.0
        alpha_d = Pd / (2 * P) if P > 0 else 0.0
        z = {n: float(v[j] / i[j]) if abs(i[j]) > 0 else None for j, n in enumerate(geo.signal_names)}
        out_modes.append({
            "v": v.tolist(), "i": i.tolist(), "vp": md["vp"], "eps_eff": md["eps_eff"],
            "delay_ps_per_mm": 1e12 * MM / md["vp"],
            "z": z, "alpha_c_db_m": 8.685889638 * alpha_c, "alpha_d_db_m": 8.685889638 * alpha_d,
            "alpha_db_m": 8.685889638 * (alpha_c + alpha_d),
        })
    return ({"f": f, "C": Cmat.tolist(), "L": L.tolist(), "modes": out_modes,
             "eps_regions": _region_eps(geo, f, opts.eps_model)}, Phi, eps, S)


def summarize(geo: Geometry, res_design, C0mat):
    """Named results for the common cases."""
    names = geo.signal_names
    modes = res_design["modes"]
    s = {"signals": names}
    if len(names) == 1:
        m = modes[0]
        s.update({"Z0": m["z"][names[0]], "eps_eff": m["eps_eff"],
                  "delay_ps_per_mm": m["delay_ps_per_mm"], "alpha_db_m": m["alpha_db_m"],
                  "alpha_c_db_m": m["alpha_c_db_m"], "alpha_d_db_m": m["alpha_d_db_m"]})
    elif len(names) == 2:
        # classify by the sign of the voltage vector
        odd = min(modes, key=lambda m: m["v"][0] * m["v"][1])
        even = max(modes, key=lambda m: m["v"][0] * m["v"][1])
        zo, ze = odd["z"][names[0]], even["z"][names[0]]
        s.update({"Zodd": zo, "Zeven": ze, "Zdiff": 2 * zo, "Zcomm": ze / 2,
                  "eps_eff_odd": odd["eps_eff"], "eps_eff_even": even["eps_eff"],
                  "delay_odd_ps_per_mm": odd["delay_ps_per_mm"],
                  "delay_even_ps_per_mm": even["delay_ps_per_mm"],
                  "alpha_odd_db_m": odd["alpha_db_m"], "alpha_even_db_m": even["alpha_db_m"],
                  "alpha_odd_c_db_m": odd["alpha_c_db_m"], "alpha_odd_d_db_m": odd["alpha_d_db_m"],
                  "Z0_single": None})
        C = np.array(res_design["C"]); L = np.array(res_design["L"])
        s["Z0_single"] = float(math.sqrt(L[0, 0] / C[0, 0]))
        s["coupling_k"] = float(-C[0, 1] / math.sqrt(C[0, 0] * C[1, 1]))
    return s


def _mode_field(geo, res, Phi):
    """Display potential: the only mode, or the odd mode of a pair, sign-fixed."""
    if len(geo.signal_names) == 2:
        mode = min(res["modes"], key=lambda m: m["v"][0] * m["v"][1])
    else:
        mode = res["modes"][0]
    v = np.array(mode["v"]) if len(geo.signal_names) > 1 else np.array([1.0])
    i_mode = np.array(mode["i"])
    if v[0] < 0:
        v, i_mode = -v, -i_mode
    return v @ Phi, i_mode, mode


def solve(geo: Geometry, opts: SolveOptions | None = None, progress=None,
          on_design=None, on_frame=None) -> dict:
    opts = opts or SolveOptions()
    if progress:
        progress("meshing", 0.02, "mesh")
    area0 = (geo.xmax - geo.xmin) * (geo.ymax - geo.ymin) / opts.initial_elements
    msh = meshing.build(geo, max_area=area0)
    msh = _adapt(geo, msh, opts, progress)
    if progress:
        progress(f"solving at design frequency ({msh.n_nodes} nodes)", 0.4, "solve")
    edges = fem.conductor_boundary_edges(msh)
    cprops = _conductor_props(geo, msh)
    Phi0, C0mat, *_ , sig, _S0 = _solve_all(geo, msh, opts.f_design, opts.eps_model, air=True)
    design, Phi, eps, S_design = line_parameters(geo, msh, opts.f_design, opts, edges, cprops, C0mat, Phi0, sig)
    field_out = None
    if opts.return_field:
        phi, i_mode, _ = _mode_field(geo, design, Phi)
        u = np.linalg.solve(C0mat, i_mode) / C0
        phi_air = u @ Phi0
        field_out = {
            "nodes": np.round(msh.nodes, 5).tolist(), "tris": msh.tris.tolist(),
            "phi": np.round(phi, 7).tolist(), "phi_air": np.round(phi_air, 6).tolist(),
            "region_of": msh.region_of.tolist(), "conductor_of": msh.conductor_of.tolist(),
            "i_signal": float(abs(i_mode[0])),
            "note": "phi: potential of the mode (V, signal at 1 V). phi_air: air-problem potential carrying the mode currents; H = eps0*c*(z x grad phi_air) [A/m], H lines = its equipotentials.",
        }
    if on_design is not None:
        partial = {"design": design, "summary": summarize(geo, design, C0mat), "sweep": [],
                   "C0": C0mat.tolist(), "mesh": {"nodes": msh.n_nodes, "elements": len(msh.tris)},
                   "notes": list(geo.notes)}
        if field_out is not None:
            partial["field"] = field_out
        on_design(partial)
    sweep = []
    for k, f in enumerate(opts.f_sweep):
        if progress:
            progress(f"frequency sweep {k+1}/{len(opts.f_sweep)}: {f/1e9:.2f} GHz", 0.45 + 0.5 * (k + 1) / len(opts.f_sweep), "sweep")
        r, Phi_f, _, _ = line_parameters(geo, msh, f, opts, edges, cprops, C0mat, Phi0, sig, pre=S_design)
        sweep.append({"f": f, "modes": [{k: m[k] for k in ("eps_eff", "alpha_db_m", "alpha_c_db_m", "alpha_d_db_m", "z", "v")} for m in r["modes"]]})
        if on_frame is not None and opts.return_field:
            phi_f, i_f, m_f = _mode_field(geo, r, Phi_f)
            on_frame({"f": f, "phi": np.round(phi_f, 7).tolist(), "i_signal": float(abs(i_f[0])),
                      "z": float(m_f["z"][geo.signal_names[0]]), "eps_eff": float(m_f["eps_eff"]),
                      "alpha_db_m": float(m_f["alpha_db_m"])})
    out = {
        "design": design, "summary": summarize(geo, design, C0mat), "sweep": sweep,
        "C0": C0mat.tolist(), "mesh": {"nodes": msh.n_nodes, "elements": len(msh.tris)},
        "notes": list(geo.notes),
    }
    if field_out is not None:
        out["field"] = field_out
    return out
