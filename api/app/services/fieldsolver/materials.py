"""Material library and the Djordjevic-Sarkar wideband Debye model.

Geometry and results are frequency dependent only through this module and the
skin effect in `analysis.py`.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"

EPS0 = 8.8541878128e-12
MU0 = 4e-7 * math.pi
C0 = 299792458.0


@dataclass
class DielectricAt:
    eps: float
    tand: float


class Material:
    def __init__(self, d: dict):
        self.id = d["id"]
        self.manufacturer = d["manufacturer"]
        self.name = d["name"]
        self.kind = d["kind"]
        self.source = d.get("source", "")
        self.points = d.get("points", [])
        self.sigma = d.get("sigma")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "manufacturer": self.manufacturer, "name": self.name,
            "kind": self.kind, "source": self.source, "points": self.points,
            "sigma": self.sigma,
        }

    def reference_point(self, f_hz: float) -> dict:
        """The datasheet point nearest (in log frequency) to `f_hz`."""
        return min(self.points, key=lambda p: abs(math.log(p["f_hz"]) - math.log(f_hz)))

    def at(self, f_hz: float, model: str = "djordjevic") -> DielectricAt:
        """Complex permittivity at `f_hz`.

        model="djordjevic": causal wideband Debye fitted through the nearest
        datasheet point. model="constant": that point as given.
        """
        p = self.reference_point(f_hz)
        if model == "constant" or p["tand"] == 0:
            return DielectricAt(p["dk"], p["tand"])
        return djordjevic_sarkar(p["dk"], p["tand"], p["f_hz"], f_hz)


def djordjevic_sarkar(dk_ref: float, tand_ref: float, f_ref: float, f: float,
                      f1: float = 1e3, f2: float = 1e12) -> DielectricAt:
    """Svensson/Djordjevic-Sarkar model through one (dk, tand) point.

    eps(w) = eps_inf + (d_eps / ln(w2/w1)) * ln((w2 + j w) / (w1 + j w)).
    For w1 << w << w2 the imaginary part is -(pi/2) d_eps / ln(w2/w1), so the
    slope d_eps/ln(w2/w1) follows from tand at the reference point.
    """
    w1, w2 = 2 * math.pi * f1, 2 * math.pi * f2
    wr, w = 2 * math.pi * f_ref, 2 * math.pi * f
    slope = dk_ref * tand_ref * 2 / math.pi
    # exact real part of the log term at the reference frequency
    term_r = _clog(complex(w2, wr) / complex(w1, wr))
    eps_inf = dk_ref - slope * term_r.real
    term = _clog(complex(w2, w) / complex(w1, w))
    eps_c = eps_inf + slope * term
    eps_r = eps_c.real
    tand = -eps_c.imag / eps_r
    return DielectricAt(eps_r, tand)


def _clog(z: complex) -> complex:
    return complex(math.log(abs(z)), math.atan2(z.imag, z.real))


class Library:
    def __init__(self, path: Path = DATA / "materials.json"):
        raw = json.loads(path.read_text())
        self.materials = {m["id"]: Material(m) for m in raw["materials"]}

    def get(self, mid: str) -> Material:
        return self.materials[mid]

    def to_list(self) -> list[dict]:
        return [m.to_dict() for m in self.materials.values()]


LIB = Library()
