"""Structure templates: parameters + stackup -> Geometry (polygon list).

The solver never sees a template. Every template only emits polygons, so a
custom structure is just another polygon list.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Geometry, Region, rect, trapezoid
from .stackups import STACKS, Stackup

TEMPLATES = {
    "microstrip": {"label": "Microstrip / stripline, single-ended",
                   "params": ["w", "etch", "soldermask", "vias"]},
    "cpw": {"label": "Coplanar waveguide (grounded if a reference layer is set)",
            "params": ["w", "gap", "etch", "soldermask", "via_fence", "fence_distance", "fence_width", "vias"]},
    "diff": {"label": "Differential pair (edge coupled)",
             "params": ["w", "s", "etch", "soldermask", "vias"]},
    "diff_cpw": {"label": "Differential coplanar waveguide",
                 "params": ["w", "s", "gap", "etch", "soldermask", "via_fence", "fence_distance", "fence_width", "vias"]},
}


@dataclass
class Params:
    template: str = "microstrip"
    stackup: str = "JLC04161H-7628"
    signal_layer: str = "L1"
    reference_layers: list[str] = field(default_factory=lambda: ["L2"])
    w: float = 0.3            # trace width at the base, mm
    s: float = 0.2            # pair spacing, mm
    gap: float = 0.3          # coplanar gap, mm
    etch: float = 0.0         # width lost per side at the top of the trace, mm
    copper_thickness: float | None = None   # override the stackup's copper, mm
    soldermask: bool = True
    via_fence: bool = False
    fence_distance: float = 0.5  # from the coplanar gap edge to the via PAD edge, mm
    fence_width: float | None = None   # deprecated: barrel diameter override
    via_hole: float = 0.30       # finished hole, mm
    via_pad: float = 0.60        # copper pad diameter, mm
    via_plating_um: float = 18.0 # hole wall copper, um (JLCPCB 18-20 um)
    via_drill_oversize: float = 0.10  # drill = finished hole + this, mm (copper outer diameter)
    via_filled: bool = False     # copper-paste filled: solid barrel instead of a plated wall
    # extra fence rows: pitch from the previous row (mm), outward. None = searched from range.
    via_rows: list = field(default_factory=list)
    mask_expansion: float = 0.05    # mask opening beyond the exposed copper, mm (from the production rules)
    roughness_um: float = 0.0
    # explicit ground via rows seen as walls, always through the whole stack:
    # [{"x": mm (pad centre), "hole": mm, "pad": mm, "mirror": true}]  (hole/pad default to via_hole/via_pad)
    vias: list[dict] = field(default_factory=list)
    # copper layers between the signal layer and a deeper reference:
    #   "fence":    opening edge at the via fence (copper resumes where the vias tie it)
    #   "coplanar": opening edge follows the coplanar ground edge (span + gap)
    #   "width":    opening of `cutout` mm, centred on the structure
    #   "remove":   layer treated as dielectric fill (no copper at all)
    cutout_mode: str = "auto"      # auto = fence if there is a via fence, else coplanar edge, else remove
    cutout: float = 1.0
    custom_stackup: dict | None = None


def build(p: Params) -> Geometry:
    st = STACKS.custom(p.custom_stackup) if p.custom_stackup else STACKS.get(p.stackup)
    sig = st.layer(p.signal_layer)
    refs = [st.layer(n) for n in p.reference_layers]
    if not refs and p.template in ("microstrip", "diff"):
        raise ValueError("microstrip and diff need at least one reference layer")
    T = p.copper_thickness if p.copper_thickness else sig["thickness_mm"]
    si = st.index(p.signal_layer)
    outer_top = si == 0
    finish_mm = 0.0
    if outer_top and not p.soldermask and st.finish and st.finish.get("thickness_um", 0) > 0:
        finish_mm = st.finish["thickness_um"] / 1000.0
    y0 = sig["y_bottom"]
    y1 = y0 + T
    outer_bot = si == len(st.layers) - 1
    if outer_bot:
        # mirror: solve bottom-layer structures as if on top
        raise ValueError("Pick the top-side equivalent layer; bottom layers mirror the top.")
    notes = []

    # ---- reference distance for domain sizing
    dists = [abs(sig["y_bottom"] - r["y_top"]) if r["y_top"] <= y0 else abs(r["y_bottom"] - y1)
             for r in refs]
    h_ref = min(dists) if dists else 1.0
    coplanar = p.template in ("cpw", "diff_cpw")

    # ---- signal conductors
    traces = []   # (xc, w, name)
    if p.template in ("microstrip", "cpw"):
        traces = [(0.0, p.w, "S")]
    else:
        traces = [(-(p.s / 2 + p.w / 2), p.w, "P"), (p.s / 2 + p.w / 2, p.w, "N")]
    span = max(abs(x) + w / 2 for x, w, _ in traces)
    edge_x = span + (p.gap if coplanar else 0.0)

    # ---- domain
    fence_extent = (p.fence_distance + p.via_pad + sum((o or (p.via_pad + 0.2)) for o in p.via_rows)) if p.via_fence else 0
    half = max(12 * h_ref, 8 * span, 3 * (edge_x + fence_extent), 1.0)
    if p.cutout_mode == "width":
        half = max(half, p.cutout / 2 + 10 * h_ref)
    if coplanar:
        half = max(half, edge_x + max(10 * h_ref, 6 * p.gap))
    air_top = max(10 * h_ref, 0.5)
    ymin = 0.0
    ymax = st.total + (air_top if outer_top else 0.0)
    if not outer_top:
        ymax = st.total
    regions: list[Region] = []

    # ---- dielectric layers, full width. Copper layers not used as reference are
    #      filled with the dielectric below them (resin fill).
    for i, l in enumerate(st.layers):
        if l["type"] == "dielectric":
            regions.append(Region(rect(-half, l["y_bottom"], half, l["y_top"]), "dielectric",
                                  l.get("label", "diel"), material=l["material"]))
    # copper layers strictly between the signal layer and a reference layer
    ref_idx = [st.index(n) for n in p.reference_layers]
    between = set()
    for ri in ref_idx:
        lo, hi = sorted((si, ri))
        between.update(j for j in range(lo + 1, hi) if st.layers[j]["type"] == "copper")
    mode = p.cutout_mode
    if mode == "auto":
        mode = "fence" if p.via_fence else ("coplanar" if coplanar else "remove")
    if mode == "fence" and not p.via_fence:
        mode = "coplanar" if coplanar else "width"
        notes.append("Cutout mode 'fence' needs a via fence: fell back to '%s'." % mode)
    if mode == "fence":
        cut_w = 2 * (edge_x + p.fence_distance)      # copper resumes at the via fence
    elif mode == "coplanar":
        cut_w = 2 * edge_x
    else:
        cut_w = p.cutout
    intermediates = []
    for i, l in enumerate(st.layers):
        if l["type"] == "copper" and l["name"] not in p.reference_layers and l["name"] != p.signal_layer:
            fill = _neighbour_dielectric(st, i)
            regions.append(Region(rect(-half, l["y_bottom"], half, l["y_top"]), "dielectric",
                                  "fill", material=fill))
            if i in between and mode != "remove":
                intermediates.append(l)
            elif i in between:
                notes.append(f"Copper layer {l['name']} lies between {p.signal_layer} and its reference: removed (cutout_mode=remove).")
            else:
                notes.append(f"Copper layer {l['name']} is not a reference: modelled as dielectric fill.")
    # the signal layer's own level, where there is no copper, is filled too
    if not outer_top:
        fill = _neighbour_dielectric(st, si)
        regions.append(Region(rect(-half, y0, half, y1), "dielectric", "fill", material=fill))
    else:
        regions.append(Region(rect(-half, y0, half, ymax), "dielectric", "air", eps=1.0))

    # ---- solder mask (outer layers only): conformal, JLCPCB model.
    #      The board always has mask. With the cell's mask off, an opening is cut
    #      around the simulated structure and the finish covers the copper inside it.
    mask_regions: list[Region] = []
    x_open = None
    if outer_top and st.soldermask:
        mg = st.mask_geom
        c1, c2, c3 = mg["above_substrate_mm"], mg["above_trace_mm"], mg["between_traces_mm"]
        if p.soldermask:
            mask_regions.append(Region(rect(-half, y0, half, y0 + c1), "dielectric", "mask", material=st.soldermask))
            for x, w, _ in traces:
                wt = max(w - 2 * p.etch, 0.01)
                mask_regions.append(Region(rect(x - wt / 2 - c2, y0, x + wt / 2 + c2, y1 + c2), "dielectric", "mask", material=st.soldermask))
            if len(traces) == 2:
                mask_regions.append(Region(rect(-p.s / 2, y0, p.s / 2, y0 + c3), "dielectric", "mask", material=st.soldermask))
            if coplanar:
                for x, w, _ in traces:
                    mask_regions.append(Region(rect(x - w / 2 - p.gap, y0, x - w / 2, y0 + c3), "dielectric", "mask", material=st.soldermask))
                    mask_regions.append(Region(rect(x + w / 2, y0, x + w / 2 + p.gap, y0 + c3), "dielectric", "mask", material=st.soldermask))
                for sgn in (-1, 1):
                    mask_regions.append(Region(rect(min(sgn * edge_x, sgn * half), y1, max(sgn * edge_x, sgn * half), y1 + c2), "dielectric", "mask", material=st.soldermask))
            notes.append(f"Solder mask: {c1*1000:.0f} um over substrate, {c2*1000:.0f} um over copper, {c3*1000:.0f} um in gaps, material {st.soldermask}.")
        else:
            # opening: outermost exposed feature + expansion
            x_feat = span
            if coplanar:
                x_feat = edge_x
            if p.via_fence:
                x_feat = edge_x + p.fence_distance + p.via_pad + sum((o if o is not None else p.via_pad + 0.2) for o in p.via_rows)
            x_open = x_feat + p.mask_expansion
            for sgn in (-1, 1):
                xa, xb = sgn * x_open, sgn * half
                mask_regions.append(Region(rect(min(xa, xb), y0, max(xa, xb), y0 + c1), "dielectric", "mask", material=st.soldermask))
                if coplanar:
                    mask_regions.append(Region(rect(min(xa, xb), y1, max(xa, xb), y1 + c2), "dielectric", "mask", material=st.soldermask))
            notes.append(f"Solder mask opening +/-{x_open:.3f} mm around the structure (outermost copper + {p.mask_expansion} mm expansion); mask kept outside it.")
    elif p.soldermask and outer_top and not st.soldermask:
        notes.append("Stackup has no solder mask material: solved without mask.")
    regions += mask_regions

    # ---- reference planes
    for r in refs:
        regions.append(Region(rect(-half, r["y_bottom"], half, r["y_top"]), "conductor", f"GND {r['name']}",
                              role="reference", roughness_um=p.roughness_um))

    # ---- intermediate copper layers with a cutout window
    for l in intermediates:
        for sgn in (-1, 1):
            xa, xb = sgn * cut_w / 2, sgn * half
            regions.append(Region(rect(min(xa, xb), l["y_bottom"], max(xa, xb), l["y_top"]), "conductor",
                                  f"GND {l['name']} (cutout {cut_w:.3f} mm)", role="reference", roughness_um=p.roughness_um))
        notes.append(f"Copper layer {l['name']} between {p.signal_layer} and its reference: kept as ground with a {cut_w:.3f} mm cutout ({'to the via fence' if mode == 'fence' else 'coplanar edge' if mode == 'coplanar' else 'manual'}).")
    if intermediates:
        half_needed = cut_w / 2 + 10 * h_ref
        if half < half_needed:
            notes.append("Domain widened for the cutout.")

    # ---- coplanar grounds and via fence
    if coplanar:
        for sgn in (-1, 1):
            x_in = sgn * edge_x
            x_out = sgn * half
            regions.append(Region(rect(min(x_in, x_out), y0, max(x_in, x_out), y1), "conductor", f"GND {p.signal_layer} coplanar",
                                  role="reference", roughness_um=p.roughness_um))
    if p.via_fence:
        xc = edge_x + p.fence_distance + p.via_pad / 2
        for sgn in (-1, 1):
            regions += _via(st, sgn * xc, p, p.via_hole, p.via_pad, "GND fence via")
        x_row = xc
        for k, off in enumerate(p.via_rows):
            x_row += (off if off is not None else p.via_pad + 0.2)
            for sgn in (-1, 1):
                regions += _via(st, sgn * x_row, p, p.via_hole, p.via_pad, f"GND fence row {k+2}")
        if p.via_rows:
            notes.append(f"{len(p.via_rows)} extra fence row(s) outward, pitches {[round(o, 3) if o is not None else 'range' for o in p.via_rows]} mm.")
        notes.append(f"Via fence ({'from the coplanar gap edge' if coplanar else 'from the trace edge'}): through vias, hole {p.via_hole} mm, pad {p.via_pad} mm, copper outer diameter {p.via_hole + p.via_drill_oversize:.2f} mm, "
                     f"{'copper filled' if p.via_filled else f'{p.via_plating_um:.0f} um plated wall'}, modelled as a solid wall. Valid when the via pitch is below about lambda/10 (4.8 mm in FR-4 at 3 GHz).")

    # ---- explicit ground via rows: through vias, pad centre at x
    for v in p.vias:
        hole, pad = v.get("hole", p.via_hole), v.get("pad", p.via_pad)
        xs = [v["x"], -v["x"]] if v.get("mirror", True) else [v["x"]]
        for x in xs:
            regions += _via(st, x, p, hole, pad, "GND via")
    if p.vias:
        notes.append("Ground via rows: through vias top to bottom, modelled as solid walls with pads on every copper layer. Valid when the via pitch is below about lambda/10 (4.8 mm in FR-4 at 3 GHz).")

    # ---- traces last (painter order)
    for x, w, name in traces:
        wt = max(w - 2 * p.etch, 0.01)
        regions.append(Region(trapezoid(x, y0, y1, w, wt), "conductor", name, role="signal",
                              roughness_um=p.roughness_um))

    geo = Geometry(regions, -half, half, ymin, ymax, notes)
    if outer_top and st.soldermask and p.soldermask:
        _mask_caps(geo, st, y0, y1, half, coplanar)
    if finish_mm > 0 and x_open is not None:
        _apply_finish(geo, y0, y1, x_open, finish_mm, half)
        notes.append(f"Surface finish {st.finish['type']} {st.finish['thickness_um']} um on all copper inside the mask opening (trace, coplanar ground, fence pads). Finish conductivity not modelled.")
    if not st.verified:
        geo.notes.append(f"Stackup {st.id} is not published by the manufacturer: {st.source}")
    return geo


def _neighbour_dielectric(st: Stackup, i: int) -> str:
    for j in (i + 1, i - 1):
        if 0 <= j < len(st.layers) and st.layers[j]["type"] == "dielectric":
            return st.layers[j]["material"]
    raise ValueError("no dielectric next to copper layer")


def _via(st: Stackup, xc: float, p: Params, hole: float, pad: float, name: str) -> list[Region]:
    """A through via at pad centre xc: copper barrel (outer diameter = drill) through
    the stack, plus a pad of diameter `pad` on every copper layer.

    A plated via is a hollow copper tube. At RF the current flows on the copper
    surface (skin depth 1.3 um at 2.4 GHz, plating 18 um), so hollow and
    copper-filled barrels give the same field. The wall is therefore solid in the
    model either way; `via_filled` only changes the note and the DC cross-section.
    """
    barrel = hole + p.via_drill_oversize
    if p.fence_width:
        barrel = p.fence_width
    out = [Region(rect(xc - barrel / 2, 0.0, xc + barrel / 2, st.total), "conductor", name, role="reference")]
    for l in st.copper():
        out.append(Region(rect(xc - pad / 2, l["y_bottom"], xc + pad / 2, l["y_top"]), "conductor", name, role="reference"))
    return out


def _apply_finish(geo: Geometry, y0: float, y1: float, x_open: float, fin: float, half: float):
    """Every top-copper piece inside the mask opening grows by `fin` and gets a
    drawing overlay. Copper straddling the opening edge is split there."""
    extra = []
    for r in list(geo.regions):
        if r.kind != "conductor":
            continue
        ys = [q[1] for q in r.points]
        if abs(min(ys) - y0) > 1e-9 or abs(max(ys) - y1) > 1e-9:
            continue                                   # not a top-copper piece
        xs = [q[0] for q in r.points]
        xa, xb = min(xs), max(xs)
        lo, hi = max(xa, -x_open), min(xb, x_open)
        if hi <= lo:
            continue
        if len(r.points) == 4 and abs(r.points[0][1] - r.points[1][1]) < 1e-12 and abs(r.points[2][0] - r.points[1][0]) > 1e-12 and abs(r.points[3][0] - r.points[0][0]) < 1e-9 and (r.points[2][0] - r.points[3][0]) < (r.points[1][0] - r.points[0][0]) - 1e-9:
            # trapezoid trace: extend its top by fin keeping the side slope
            wb, wt = r.points[1][0] - r.points[0][0], r.points[2][0] - r.points[3][0]
            xc = (r.points[0][0] + r.points[1][0]) / 2
            T = y1 - y0
            wt2 = wb - (wb - wt) * (T + fin) / T
            r.points = trapezoid(xc, y0, y1 + fin, wb, max(wt2, 0.01))
            geo.overlays.append({"kind": "finish", "points": trapezoid(xc, y1, y1 + fin, wb - (wb - wt2) * (T / (T + fin)), max(wt2, 0.01))})
        else:
            extra.append(Region(rect(lo, y0, hi, y1 + fin), "conductor", r.name, role=r.role, sigma=r.sigma, roughness_um=r.roughness_um))
            geo.overlays.append({"kind": "finish", "points": rect(lo, y1, hi, y1 + fin)})
    geo.regions += extra


def _mask_caps(geo: Geometry, st: Stackup, y0: float, y1: float, half: float, coplanar: bool):
    """With the mask on, cap every top-copper reference piece (via pads, plane
    edges) that the trace/coplanar caps do not already cover. Vias are tented."""
    c2 = st.mask_geom["above_trace_mm"]
    caps = []
    for r in geo.regions:
        if r.kind != "conductor" or r.role != "reference":
            continue
        ys = [q[1] for q in r.points]
        if abs(min(ys) - y0) > 1e-9 or abs(max(ys) - y1) > 1e-9:
            continue
        if coplanar:
            continue        # the coplanar ground cap already spans this level
        xs = [q[0] for q in r.points]
        caps.append(Region(rect(max(min(xs) - c2, -half), y0, min(max(xs) + c2, half), y1 + c2),
                           "dielectric", "mask", material=st.soldermask))
    geo.regions += caps
