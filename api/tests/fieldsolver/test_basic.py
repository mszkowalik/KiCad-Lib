"""The solver against closed forms: a parallel-plate line whose C, Z0 and eps_eff
are exact, and its conductor loss against the analytic surface-impedance result.

Run from `api/`:  python -m pytest tests/fieldsolver -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import math
import numpy as np
from app.services.fieldsolver.geometry import Geometry, Region, rect
from app.services.fieldsolver.analysis import solve, SolveOptions
from app.services.fieldsolver.materials import EPS0, MU0, C0

def parallel_plate(eps=1.0):
    # wide plates: W=10 mm, gap 0.1 mm; C ~ eps0*eps*W/h per metre
    W, h = 10.0, 0.1
    regs = [Region(rect(-W/2, 0, W/2, h), "dielectric", "d", eps=eps),
            Region(rect(-W/2, -0.05, W/2, 0), "conductor", "GND", role="reference"),
            Region(rect(-W/2, h, W/2, h+0.05), "conductor", "S", role="signal")]
    return Geometry(regs, -W/2, W/2, -0.05, h+0.05)

def test_parallel_plate_capacitance():
    r = solve(parallel_plate(4.0), SolveOptions(f_sweep=[], refine_passes=1, return_field=False))
    C = r["design"]["C"][0][0]
    assert abs(C / (EPS0*4.0*10/0.1) - 1) < 1e-3
    assert abs(r["summary"]["eps_eff"] - 4.0) < 1e-3
    z = math.sqrt(MU0/(EPS0*4.0)) * 0.1/10
    assert abs(r["summary"]["Z0"]/z - 1) < 1e-3


def test_parallel_plate_conductor_loss():
    """Air-filled wide parallel plate: R = 2 Rs / W, alpha = R / (2 Z)."""
    from app.services.fieldsolver.analysis import solve, SolveOptions
    f = 2.4e9
    r = solve(parallel_plate(1.0), SolveOptions(f_design=f, f_sweep=[], refine_passes=1, return_field=False))
    Rs = math.sqrt(math.pi * f * MU0 / 5.8e7)
    W, h = 10e-3, 0.1e-3
    Z = math.sqrt(MU0 / EPS0) * h / W
    alpha = 2 * Rs / W / (2 * Z) * 8.685889638
    assert abs(r["summary"]["alpha_c_db_m"] / alpha - 1) < 0.02
