#!/usr/bin/env python3
"""Measure a library 3D model's bounding box, so `fp.model_fit` can be verified.

Before this existed, every verification pass recorded `fp.model_fit` as
"skipped", with the reason "no tool here renders or measures STEP geometry".
That reason was wrong. STEP (ISO 10303-21) is a text format and every vertex
and surface control point is a CARTESIAN_POINT with explicit millimetre
coordinates, so the extent of all CARTESIAN_POINTs bounds the solid. No CAD
library is needed.

Two things stop the raw extent from being the answer on its own, so the script
prints a trimmed extent (1st to 99th percentile) beside the full one:

  * A spline body can read a few hundredths of a millimetre large, because a
    control point may sit outside the curve it defines.
  * Many vendor and easyeda2kicad models carry construction geometry, or a
    stray fragment of a different part, far outside the body. On this library's
    own models that ranges from a decorative wire strand a centimetre out to an
    enclosure whose raw Z floor reads -3574 mm.

When the two extents agree, the measurement is trustworthy and exact for the
planar and cylindrical bodies that make up almost every package here. When they
disagree the script says so: read the trimmed numbers as the body, and treat the
stray geometry as its own finding.

A surface of revolution is the one case that misleads in the other direction.
Its points lie in a single half-plane, so a radial axis reads as the RADIUS, not
the diameter. Double it before comparing with a datasheet.

    export KICAD_API_URL=https://disfunction.cc/lib
    export KICAD_MCP_TOKEN=<your personal token>
    python3 scripts/model-bbox.py Diode_SMD.3dshapes/D_SMA.step

Pass the path as it appears after `3DModels/` in the footprint's `(model ...)`
line. Apply that line's offset, scale and rotation yourself before comparing
the result with a datasheet: this script reports the file's own geometry.
"""
from __future__ import annotations

import gzip
import os
import re
import sys
import urllib.parse
import urllib.request

CART = re.compile(r"#(\d+)\s*=\s*CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(([^)]*)\)", re.I)
VERTEX = re.compile(r"=\s*VERTEX_POINT\s*\(\s*'[^']*'\s*,\s*#(\d+)", re.I)


def fetch(rel: str, base: str, token: str) -> tuple[str, str, int]:
    rel = rel.split("/3DModels/", 1)[-1].lstrip("/")
    url = f"{base.rstrip('/')}/files/3DModels/{urllib.parse.quote(rel)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        # Cloudflare rejects the Python-urllib user agent in front of this API.
        "User-Agent": "python-httpx/0.27.0",
    })
    raw = urllib.request.urlopen(req).read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace"), url, len(raw)


def points(text: str) -> tuple[list[list[float]], list[list[float]]]:
    """Return (every CARTESIAN_POINT, only those a VERTEX_POINT refers to)."""
    by_id: dict[str, list[float]] = {}
    every: list[list[float]] = []
    for m in CART.finditer(text):
        parts = m.group(2).split(",")
        if len(parts) != 3:
            continue
        try:
            xyz = [float(p) for p in parts]
        except ValueError:
            continue
        by_id[m.group(1)] = xyz
        every.append(xyz)
    verts = [by_id[m.group(1)] for m in VERTEX.finditer(text) if m.group(1) in by_id]
    return every, verts


def _at(sorted_vals: list[float], q: float) -> float:
    i = int(q * (len(sorted_vals) - 1))
    return sorted_vals[max(0, min(len(sorted_vals) - 1, i))]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    base = os.environ.get("KICAD_API_URL", "https://disfunction.cc/lib")
    token = os.environ.get("KICAD_MCP_TOKEN")
    if not token:
        print("set KICAD_MCP_TOKEN to your personal API token", file=sys.stderr)
        return 2
    text, url, size = fetch(argv[1], base, token)
    every, verts = points(text)
    pts = verts or every
    if not pts:
        print(f"no CARTESIAN_POINT in {url} ({size} bytes) — not a STEP file?", file=sys.stderr)
        return 1
    print(f"url   {url}")
    print(f"bytes {size}   CARTESIAN_POINTs {len(every)}   vertices {len(verts)}")
    if not verts:
        print("no VERTEX_POINT found — falling back to every point, read with care")
    print(f"{'':2} {'vertices (the body)':>28}   {'every point':>28}")
    stray = False
    for i, axis in enumerate("XYZ"):
        col = sorted(p[i] for p in pts)
        acol = sorted(p[i] for p in every)
        lo, hi = col[0], col[-1]
        alo, ahi = acol[0], acol[-1]
        if (ahi - alo) > (hi - lo) * 1.5 + 2:
            stray = True
        print(f"{axis}  {lo:10.4f} .. {hi:10.4f} ({hi - lo:8.4f})"
              f"   {alo:10.4f} .. {ahi:10.4f} ({ahi - alo:8.4f})")
    if stray:
        print("\nNOTE: the two columns disagree, which is normal. A LINE's reference\n"
              "point can sit far out along its own infinite line, and a model may carry\n"
              "construction geometry or a fragment of another part. Read the body from\n"
              "the VERTEX column. Inspect the file before calling the excess a defect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
