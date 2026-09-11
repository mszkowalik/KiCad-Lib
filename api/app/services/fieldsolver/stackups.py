"""Stackup library: layer list top to bottom, with y-coordinates computed."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .materials import DATA, LIB, Material



def _face_of(value, side: str):
    """One face's outer layer, from either shape.

    `{"top": …, "bottom": …}` is read per face. Anything else is a value that applies
    to BOTH faces — the shape every stackup used before faces existed, and still the
    right shape for a fab that quotes one mask and one finish for the whole board.
    """
    if isinstance(value, dict) and ("top" in value or "bottom" in value):
        return value.get(side)
    return value


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
        self._finish_raw = d.get("finish")
        self.mask_geom = mask_geom
        # The mask INK thickness and the legend are facts about how the board is
        # finished, not about the field: the solver builds its coating from
        # `mask_geom`, and these two exist so a board file can be checked against
        # them. `mask_thickness_is_minimum` matters — a fab that publishes ">= 10 um"
        # is not contradicted by a board that declares more.
        self.mask_thickness_mm = d.get("mask_thickness_mm")
        self.mask_thickness_is_minimum = bool(d.get("mask_thickness_is_minimum"))
        self.mask_source = d.get("mask_source", "")
        # The outer layers are PER FACE. A board is routinely built with legend on one
        # side only, and the two faces can carry different finishes. `_faces` reads
        # either shape: a bare value means both faces, which is what every stackup
        # written before this said, so nothing has to be migrated.
        self.faces = {
            "top": {
                "silkscreen": _face_of(d.get("silkscreen"), "top"),
                "soldermask": _face_of(d.get("soldermask"), "top"),
                "finish": _face_of(d.get("finish"), "top"),
            },
            "bottom": {
                "silkscreen": _face_of(d.get("silkscreen"), "bottom"),
                "soldermask": _face_of(d.get("soldermask"), "bottom"),
                "finish": _face_of(d.get("finish"), "bottom"),
            },
        }
        # `self.soldermask`, `self.finish` and `self.silkscreen` keep meaning THE TOP
        # FACE, because that is the only face the solver builds a coating on
        # (templates.py guards every mask region with `outer_top`). Changing what they
        # mean would silently change every solved geometry.
        self.soldermask = self.faces["top"]["soldermask"]
        self.finish = self.faces["top"]["finish"] or {"type": "none / OSP", "thickness_um": 0}
        self.silkscreen = self.faces["top"]["silkscreen"]
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
                "builtin": self.builtin, "layers": self.layers, "total_mm": self.total,
                "mask_geom": self.mask_geom, "finish": self.finish,
                "mask_thickness_mm": self.mask_thickness_mm,
                "mask_thickness_is_minimum": self.mask_thickness_is_minimum,
                "mask_source": self.mask_source, "silkscreen": self.silkscreen,
                # the per-face truth; the three keys above are the TOP face, kept for
                # the solver, which only ever coats the top
                "faces": self.faces}


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

    @staticmethod
    def normalise(d: dict) -> dict:
        """Put a stackup into the only shape it is allowed to have, and refuse one that
        cannot be built.

        Three rules, all of them things a person should not have to type:

        * **Copper layers are named by POSITION** — L1 at the top through Ln at the
          bottom. A name is not a choice: it is where the layer is, and letting one be
          typed means a stackup whose "L3" is its fourth copper layer.
        * **A dielectric's label is generated** from its material and the copper it
          sits between, because the type and the position are the whole of what a
          reader needs. KiCad wants a name in the file, so one is made rather than
          asked for.
        * **Copper never touches copper.** There is no insulation between two adjacent
          copper layers, so the board is not buildable and the solver would quietly
          model something else. Several dielectrics in a row ARE allowed — a fab lists
          each prepreg sheet.
        """
        layers = [dict(l) for l in d.get("layers", [])]
        if len([l for l in layers if l.get("type") == "copper"]) < 2:
            raise ValueError("a stackup needs at least two copper layers")
        if layers and layers[0].get("type") != "copper":
            raise ValueError("a stackup must start with a copper layer")
        if layers and layers[-1].get("type") != "copper":
            raise ValueError("a stackup must end with a copper layer")
        for i in range(1, len(layers)):
            if layers[i].get("type") == "copper" and layers[i - 1].get("type") == "copper":
                raise ValueError(
                    f"copper layers {i} and {i + 1} sit against each other; a core or "
                    "prepreg has to separate every pair of copper layers"
                )
        cu = 0
        for i, l in enumerate(layers):
            if l.get("type") == "copper":
                cu += 1
                l["name"] = f"L{cu}"
                l.pop("label", None)
            else:
                below = cu + 1
                mat = l.get("material") or ""
                base = LIB.materials[mat].name if mat in LIB.materials else (l.get("label") or "dielectric")
                l["label"] = f"{base} (L{cu}-L{below})" if cu else base
        return dict(d, layers=layers)

    def save(self, d: dict) -> "Stackup":
        sid = d.get("id") or re.sub(r"[^A-Za-z0-9_-]+", "_", d["name"]).strip("_")
        if sid in self.stackups and self.stackups[sid].builtin:
            sid = "user_" + sid
        d = self.normalise(dict(d, id=sid, builtin=False))
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
