"""Stackup library: layer list top to bottom, with y-coordinates computed."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .materials import DATA, LIB, Material



def _register_custom(layer: dict, sid: str, i: int) -> str:
    """A layer given as dk/tand (no material id) becomes an ad-hoc material."""
    mid = f"custom_{re.sub(r'[^a-z0-9]+', '_', sid.lower())}_{i}"
    LIB.materials[mid] = Material({"id": mid, "manufacturer": "custom", "name": layer.get("label") or f"layer {i}",
                                   "kind": "dielectric", "points": [{"f_hz": float(layer.get("f_hz", 1e9)), "dk": float(layer["dk"]), "tand": float(layer.get("tand", 0.0))}],
                                   "source": f"user value in stackup {sid}"})
    return mid


class Stackup:
    def __init__(self, d: dict, mask_geom: dict):
        self.raw = d
        self.id = d["id"]
        self.name = d["name"]
        self.manufacturer = d["manufacturer"]
        self.source = d.get("source", "")
        self.verified = d.get("verified", True)
        self.soldermask = d.get("soldermask")
        self.finish = d.get("finish") or {"type": "none / OSP", "thickness_um": 0}
        self.mask_geom = mask_geom
        self.builtin = d.get("builtin", False)
        self.layers = [dict(l) for l in d["layers"]]
        for i, l in enumerate(self.layers):
            if l["type"] == "dielectric" and not l.get("material") and "dk" in l:
                l["material"] = _register_custom(l, self.id, i)
        if d.get("mask_dk") is not None and not self.soldermask:
            self.soldermask = _register_custom({"dk": d["mask_dk"], "tand": d.get("mask_tand", 0.02), "label": "solder mask"}, self.id, 99)
        self._place()

    def _place(self):
        total = sum(l["thickness_mm"] for l in self.layers)
        y = total
        for l in self.layers:
            l["y_top"] = y
            y -= l["thickness_mm"]
            l["y_bottom"] = y
        self.total = total

    def copper(self) -> list[dict]:
        return [l for l in self.layers if l["type"] == "copper"]

    def layer(self, name: str) -> dict:
        for l in self.layers:
            if l.get("name") == name:
                return l
        raise KeyError(name)

    def index(self, name: str) -> int:
        return next(i for i, l in enumerate(self.layers) if l.get("name") == name)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "manufacturer": self.manufacturer,
                "source": self.source, "verified": self.verified, "soldermask": self.soldermask,
                "builtin": self.builtin, "layers": self.layers, "total_mm": self.total, "mask_geom": self.mask_geom, "finish": self.finish}


class StackupLibrary:
    def __init__(self, path: Path = DATA / "stackups.json"):
        raw = json.loads(path.read_text())
        self.mask_geom = raw["soldermask_geometry"]
        self.finish_presets = raw.get("finish_presets", [])
        self.stackups = {}
        for s in raw["stackups"]:
            s["builtin"] = True
            self.stackups[s["id"]] = Stackup(s, self.mask_geom)
        self.user: dict[str, dict] = {}

    def load_user(self, records: dict[str, dict]) -> None:
        """Replace the user-defined stackups with what the database holds."""
        for sid in list(self.user):
            self.stackups.pop(sid, None)
        self.user = {}
        for sid, d in records.items():
            d = dict(d, id=sid, builtin=False)
            self.user[sid] = d
            self.stackups[sid] = Stackup(d, d.get("mask_geom", self.mask_geom))

    def save(self, d: dict) -> "Stackup":
        sid = d.get("id") or re.sub(r"[^A-Za-z0-9_-]+", "_", d["name"]).strip("_")
        if sid in self.stackups and self.stackups[sid].builtin:
            sid = "user_" + sid
        d = dict(d, id=sid, builtin=False)
        d.setdefault("manufacturer", "user")
        d.setdefault("verified", False)
        d.setdefault("source", "user-defined stackup")
        st = Stackup(d, d.get("mask_geom", self.mask_geom))
        self.stackups[sid] = st
        self.user[sid] = d
        return st

    def delete(self, sid: str):
        if sid not in self.user:
            raise KeyError("not a user stackup")
        del self.user[sid]; del self.stackups[sid]

    def get(self, sid: str) -> Stackup:
        return self.stackups[sid]

    def to_list(self):
        return [s.to_dict() for s in self.stackups.values()]

    def custom(self, d: dict) -> Stackup:
        """A stackup posted by the client (same schema as the JSON entries)."""
        return Stackup(d, d.get("mask_geom", self.mask_geom))


STACKS = StackupLibrary()
