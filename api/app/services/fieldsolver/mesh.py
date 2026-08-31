"""Constrained Delaunay mesh of a Geometry, with element classification and
adaptive refinement."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

from .geometry import Geometry


def _tr():
    """Import the mesher on first use.

    The images install `triangle` for every architecture — amd64 from the wheel,
    arm64 from source (see api/Dockerfile). Importing it at module scope would
    still make a machine without it fail to start the whole API, so the import
    waits until a solve asks for it and the router answers 503 instead.
    """
    try:
        import triangle
    except ImportError as e:                                    # pragma: no cover
        raise RuntimeError(
            "the field solver needs the `triangle` mesher and it is not installed. "
            "Rebuild the api image (`docker compose build api`), which installs it "
            "for this architecture."
        ) from e
    return triangle


@dataclass
class Mesh:
    nodes: np.ndarray          # (n, 2) mm
    tris: np.ndarray           # (m, 3)
    region_of: np.ndarray      # (m,) index into geometry.regions, -1 = none (air by default)
    conductor_of: np.ndarray   # (m,) conductor index or -1
    node_conductor: np.ndarray # (n,) conductor index or -1
    conductors: list[str]      # conductor names, index = conductor id
    segments: np.ndarray
    area: np.ndarray           # (m,)

    @property
    def n_nodes(self): return len(self.nodes)


def _pslg(geo: Geometry):
    lines = [box(geo.xmin, geo.ymin, geo.xmax, geo.ymax).exterior]
    for r in geo.regions:
        poly = Polygon(r.points)
        if not poly.is_valid:
            poly = poly.buffer(0)
        lines.append(poly.exterior)
    noded = unary_union(lines)
    pts: dict[tuple[float, float], int] = {}
    segs = []

    def pid(p):
        key = (round(p[0], 9), round(p[1], 9))
        if key not in pts:
            pts[key] = len(pts)
        return pts[key]

    geoms = noded.geoms if hasattr(noded, "geoms") else [noded]
    for g in geoms:
        c = list(g.coords)
        for a, b in zip(c[:-1], c[1:]):
            ia, ib = pid(a), pid(b)
            if ia != ib:
                segs.append((ia, ib))
    verts = np.array(list(pts.keys()), float)
    return verts, np.array(segs, int)


def _classify(geo: Geometry, nodes, tris):
    cent = nodes[tris].mean(axis=1)
    region_of = np.full(len(tris), -1, int)
    preps = []
    for r in geo.regions:
        poly = Polygon(r.points)
        if not poly.is_valid:
            poly = poly.buffer(0)
        preps.append((poly.bounds, prep(poly)))
    from shapely.geometry import Point
    # painter order: iterate in order, later regions overwrite
    for ri, (bnd, pp) in enumerate(preps):
        x0, y0, x1, y1 = bnd
        cand = np.where((cent[:, 0] >= x0) & (cent[:, 0] <= x1) &
                        (cent[:, 1] >= y0) & (cent[:, 1] <= y1))[0]
        for ei in cand:
            if pp.contains(Point(cent[ei])):
                region_of[ei] = ri
    return region_of


def _conductor_maps(geo: Geometry, tris, region_of, n_nodes):
    conductors: list[str] = []
    for r in geo.regions:
        if r.kind == "conductor" and r.name not in conductors:
            conductors.append(r.name)
    cond_index = {n: i for i, n in enumerate(conductors)}
    conductor_of = np.full(len(tris), -1, int)
    for ei, ri in enumerate(region_of):
        if ri >= 0 and geo.regions[ri].kind == "conductor":
            conductor_of[ei] = cond_index[geo.regions[ri].name]
    node_conductor = np.full(n_nodes, -1, int)
    for ei in np.where(conductor_of >= 0)[0]:
        node_conductor[tris[ei]] = conductor_of[ei]
    return conductors, conductor_of, node_conductor


def _areas(nodes, tris):
    p = nodes[tris]
    return 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
                        - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))


def build(geo: Geometry, max_area: float | None = None, min_angle: float = 30.0) -> Mesh:
    verts, segs = _pslg(geo)
    if max_area is None:
        max_area = (geo.xmax - geo.xmin) * (geo.ymax - geo.ymin) / 2000.0
    t = _tr().triangulate({"vertices": verts, "segments": segs}, f"pq{min_angle}a{max_area:.12g}")
    return _finish(geo, t)


def refine(geo: Geometry, mesh: Mesh, new_area: np.ndarray, min_angle: float = 30.0) -> Mesh:
    """Re-triangulate with a per-element maximum area."""
    t = _tr().triangulate({"vertices": mesh.nodes, "triangles": mesh.tris,
                        "segments": mesh.segments, "triangle_max_area": new_area.reshape(-1, 1)},
                       f"rpq{min_angle}a")
    return _finish(geo, t)


def _finish(geo: Geometry, t) -> Mesh:
    nodes = np.asarray(t["vertices"], float)
    tris = np.asarray(t["triangles"], int)
    region_of = _classify(geo, nodes, tris)
    conductors, conductor_of, node_conductor = _conductor_maps(geo, tris, region_of, len(nodes))
    return Mesh(nodes, tris, region_of, conductor_of, node_conductor, conductors,
                np.asarray(t["segments"], int), _areas(nodes, tris))
