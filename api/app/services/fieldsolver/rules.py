"""Fab design rules: defaults and warnings.

The built-in sets come from rules.json inside the package; user-defined sets live in
Postgres and are pushed in with `load_user` on every request that needs them.
"""
import json
import re
from .materials import DATA



def _load():
    rules = {}
    for r in json.loads((DATA / "rules.json").read_text())["rules"]:
        r["builtin"] = True
        rules[r["id"]] = r
    return rules


RULES = _load()


def load_user(records: dict[str, dict]) -> None:
    """Replace the user-defined rule sets with what the database holds."""
    for rid in [k for k, v in RULES.items() if not v.get("builtin")]:
        RULES.pop(rid, None)
    for rid, r in records.items():
        RULES[rid] = dict(r, id=rid, builtin=False)


def user_records() -> dict[str, dict]:
    return {k: v for k, v in RULES.items() if not v.get("builtin")}

# editable fields (flat) -> where they live in the rule dict
FIELDS = {
    "min_width_2l": ("trace", "outer_1oz_2layer", "min_width"), "min_space_2l": ("trace", "outer_1oz_2layer", "min_space"),
    "min_width_ml": ("trace", "outer_1oz_multilayer", "min_width"), "min_space_ml": ("trace", "outer_1oz_multilayer", "min_space"),
    "via_min_hole": ("via", "min_hole"), "via_min_diameter": ("via", "min_diameter"),
    "via_plating_um": ("via", "plating_um"), "via_drill_oversize": ("via", "drill_oversize"),
    "via_default_hole": ("via", "default_hole"), "via_default_pad": ("via", "default_pad"),
    "drill_to_copper": ("via", "drill_to_copper_inner"),
    "etch_outer_um": ("etch", "undercut_outer_um"), "etch_inner_um": ("etch", "undercut_inner_um"),
    "mask_dk": ("mask", "dk"), "mask_tand": ("mask", "tand"), "mask_c1": ("mask", "above_substrate_mm"), "mask_c2": ("mask", "above_trace_mm"),
    "mask_expansion": ("mask", "expansion_mm"),
    "finish_um": ("finish", "thickness_um"),
    "mask_min_um": ("soldermask", "min_thickness_um"), "impedance_tolerance_pct": ("impedance_tolerance_pct",),
}


def flat(r: dict) -> dict:
    out = {"id": r["id"], "name": r["name"], "manufacturer": r.get("manufacturer", ""), "builtin": r.get("builtin", False), "source": r.get("source", ""),
           "via_sizes": r.get("via", {}).get("sizes", []), "finish_type": r.get("finish", {}).get("type", "none / OSP")}
    for k, path in FIELDS.items():
        d = r
        for pth in path:
            d = d.get(pth, {}) if isinstance(d, dict) else {}
        out[k] = d if not isinstance(d, dict) else None
    return out


def save(f: dict) -> dict:
    rid = f.get("id") or re.sub(r"[^A-Za-z0-9_-]+", "_", f["name"]).strip("_")
    if rid in RULES and RULES[rid].get("builtin"):
        rid = "user_" + rid
    r = {"id": rid, "name": f["name"], "manufacturer": f.get("manufacturer", "user"), "source": f.get("source", "user-defined rules"),
         "trace": {"outer_1oz_2layer": {}, "outer_1oz_multilayer": {}}, "via": {}, "soldermask": {}, "etch": {}, "mask": {}, "finish": {"type": str(f.get("finish_type") or "none / OSP")}, "builtin": False}
    sizes = [{"name": str(x.get("name") or f"{x['hole']} / {x['pad']}"), "hole": float(x["hole"]), "pad": float(x["pad"])} for x in (f.get("via_sizes") or []) if x.get("hole") and x.get("pad")]
    if sizes:
        r["via"]["sizes"] = sizes
    for k, path in FIELDS.items():
        if f.get(k) is None:
            continue
        d = r
        for pth in path[:-1]:
            d = d.setdefault(pth, {})
        d[path[-1]] = float(f[k])
    RULES[rid] = r
    return r


def delete(rid: str):
    if rid not in RULES or RULES[rid].get("builtin"):
        raise KeyError("not a user rule set")
    del RULES[rid]


def check(rule_id: str, params: dict, layer_count: int) -> list[str]:
    """Human-readable warnings for a template parameter set."""
    r = RULES.get(rule_id)
    if not r:
        return []
    key = "outer_1oz_multilayer" if layer_count > 2 else "outer_1oz_2layer"
    t = r["trace"].get(key, {})
    w = []
    if t.get("min_width") and params["w"] < t["min_width"]:
        w.append(f"Trace width {params['w']:.3f} mm is below the fab minimum {t['min_width']} mm ({key}).")
    if t.get("min_space") and params["template"].startswith("diff") and params["s"] < t["min_space"]:
        w.append(f"Pair spacing {params['s']:.3f} mm is below the fab minimum {t['min_space']} mm.")
    if t.get("min_space") and "cpw" in params["template"] and params["gap"] < t["min_space"]:
        w.append(f"Coplanar gap {params['gap']:.3f} mm is below the fab minimum {t['min_space']} mm.")
    v = r.get("via", {})
    if params.get("via_fence") or params.get("vias"):
        if v.get("min_hole") and params["via_hole"] < v["min_hole"]:
            w.append(f"Via hole {params['via_hole']} mm is below the fab minimum {v['min_hole']} mm.")
        if v.get("min_diameter") and params["via_pad"] < v["min_diameter"]:
            w.append(f"Via pad {params['via_pad']} mm is below the fab minimum {v['min_diameter']} mm.")
        if params["via_pad"] < params["via_hole"] + 2 * 0.1:
            w.append("Via pad leaves less than 0.1 mm annular ring.")
        d2c = v.get("drill_to_copper_inner", 0.2)
        for k, off in enumerate(params.get("via_rows") or []):
            if off is not None and off < params["via_pad"] + d2c:
                w.append(f"Via row {k+2} pitch {off:.2f} mm is closer than pad + drill-to-copper ({params['via_pad'] + d2c:.2f} mm).")
    return w
