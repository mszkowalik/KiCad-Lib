"""Cross-section geometry: a painter-ordered list of polygons in millimetres."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Region:
    """One polygon. Later regions in the list win where regions overlap."""
    points: list[tuple[float, float]]
    kind: str                       # "dielectric" | "conductor"
    name: str                       # dielectric label or conductor name
    role: str = ""                  # conductors: "signal" | "reference"
    material: str | None = None     # material id (dielectrics)
    eps: float = 1.0                # used when material is None
    tand: float = 0.0
    sigma: float = 5.8e7            # conductors
    roughness_um: float = 0.0       # RMS roughness for Hammerstad (conductors)

    def bbox(self):
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass
class Geometry:
    regions: list[Region]
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    notes: list[str] = field(default_factory=list)
    overlays: list[dict] = field(default_factory=list)   # drawing only: {"points", "kind": "finish"}

    @property
    def signal_names(self) -> list[str]:
        seen = []
        for r in self.regions:
            if r.kind == "conductor" and r.role == "signal" and r.name not in seen:
                seen.append(r.name)
        return seen

    def to_dict(self) -> dict:
        return {
            "xmin": self.xmin, "xmax": self.xmax, "ymin": self.ymin, "ymax": self.ymax,
            "notes": self.notes, "overlays": self.overlays,
            "regions": [{
                "points": r.points, "kind": r.kind, "name": r.name, "role": r.role,
                "material": r.material, "eps": r.eps, "tand": r.tand,
            } for r in self.regions],
        }

    @staticmethod
    def from_dict(d: dict) -> "Geometry":
        regs = [Region(points=[tuple(p) for p in r["points"]], kind=r["kind"], name=r["name"],
                       role=r.get("role", ""), material=r.get("material"),
                       eps=float(r.get("eps", 1.0)), tand=float(r.get("tand", 0.0)),
                       sigma=float(r.get("sigma", 5.8e7)),
                       roughness_um=float(r.get("roughness_um", 0.0)))
                for r in d["regions"]]
        return Geometry(regs, d["xmin"], d["xmax"], d["ymin"], d["ymax"], list(d.get("notes", [])))


def rect(x0, y0, x1, y1) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def trapezoid(xc, y0, y1, w_bottom, w_top) -> list[tuple[float, float]]:
    """Etched trace: wider at the bottom (y0), narrower at the top (y1)."""
    return [(xc - w_bottom / 2, y0), (xc + w_bottom / 2, y0),
            (xc + w_top / 2, y1), (xc - w_top / 2, y1)]
