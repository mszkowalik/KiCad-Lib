"""The KiCad half of Select Similar: read a board into `Obj` records, and
drive KiCad's selection and view.

Everything is read from the raw protobuf messages (`item.proto`), because the
kipy wrappers do not cover every field and their names move between releases.
The messages are KiCad's API contract (`api/proto/board/board_types.proto`).

Facts this module depends on, verified against KiCad 10.0.5:
- A footprint field's selectable id is `field.text.id`. `field.id` is the
  field NUMBER (1 = Reference), so kipy's `Board.add_to_selection`, which
  sends `item.id`, cannot select a field. `select()` builds the request itself.
- `GetItems` returns board-level items only. Pads, fields, and a footprint's
  own texts and shapes are read from `FootprintInstance.definition.items`.
  `AddToSelection` resolves all of them (`BOARD::ResolveItem` walks footprints).
- The `parent` field on items arrives in 10.0.6, so the parent footprint of a
  pad or field is taken from the footprint that carries it, never from `parent`.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Set

from kipy.board import Board
from kipy.proto.board import board_types_pb2 as bt
from kipy.proto.common.commands import editor_commands_pb2 as ec
from kipy.proto.common.types import base_types_pb2
from kipy.util.board_layer import CANONICAL_LAYER_NAMES
from kipy.util.proto import unpack_any

from similar_engine import (ANGLE, BOOL, FIELD_PREFIX, GROUP_GRAPHICAL, GROUP_KIND,
                            GROUP_OBJECT, KIND_KEY, LENGTH, NUMBER, OWNER_KEY, Obj, define,
                            norm_angle)

ZOOM_TO_SELECTION = "common.Control.zoomFitSelection"

# --- attribute vocabulary ---------------------------------------------------
# Keys are shared across kinds on purpose: with Object Kind set to Any,
# "Layer Same" must compare a track's layer with a text's layer.

define(KIND_KEY, "Object Kind", GROUP_KIND)
define(OWNER_KEY, "Owner", GROUP_KIND)

define("parent", "Parent Footprint", GROUP_OBJECT)
define("reference", "Reference", GROUP_OBJECT)
define("value", "Value", GROUP_OBJECT)
define("lib_id", "Library Link", GROUP_OBJECT)
define("number", "Pad Number", GROUP_OBJECT)
define("pin_name", "Pin Name", GROUP_OBJECT)
define("pin_type", "Pin Type", GROUP_OBJECT)
define("pad_type", "Pad Type", GROUP_OBJECT)
define("via_type", "Via Type", GROUP_OBJECT)
define("shape_type", "Shape", GROUP_OBJECT)
define("field_name", "Field Name", GROUP_OBJECT)
define("text", "Text", GROUP_OBJECT)
define("name", "Name", GROUP_OBJECT)
define("layer", "Layer", GROUP_OBJECT)
define("layers", "Layers", GROUP_OBJECT)
define("layer_pair", "Layer Pair", GROUP_OBJECT)
define("net", "Net", GROUP_OBJECT)
define("netclass", "Net Class", GROUP_OBJECT)
define("locked", "Locked", GROUP_OBJECT, BOOL)
define("visible", "Visible", GROUP_OBJECT, BOOL)
define("dnp", "Do Not Populate", GROUP_OBJECT, BOOL)
define("exclude_bom", "Exclude from BOM", GROUP_OBJECT, BOOL)
define("exclude_pos", "Exclude from Position Files", GROUP_OBJECT, BOOL)
define("not_in_schematic", "Not in Schematic", GROUP_OBJECT, BOOL)
define("mounting", "Component Type", GROUP_OBJECT)
define("sheet", "Sheet", GROUP_OBJECT)
define("priority", "Priority", GROUP_OBJECT, NUMBER)
define("zone_connection", "Pad Connections", GROUP_OBJECT)
define("thermal_gap", "Thermal Relief Gap", GROUP_OBJECT, LENGTH)
define("thermal_spoke", "Thermal Spoke Width", GROUP_OBJECT, LENGTH)
define("clearance", "Clearance", GROUP_OBJECT, LENGTH)
define("min_width", "Minimum Width", GROUP_OBJECT, LENGTH)
define("island_mode", "Remove Islands", GROUP_OBJECT)
define("fill_mode", "Fill Mode", GROUP_OBJECT)
define("border_style", "Outline Style", GROUP_OBJECT)
define("keepout_tracks", "Keep Out Tracks", GROUP_OBJECT, BOOL)
define("keepout_vias", "Keep Out Vias", GROUP_OBJECT, BOOL)
define("keepout_pads", "Keep Out Pads", GROUP_OBJECT, BOOL)
define("keepout_copper", "Keep Out Copper Fills", GROUP_OBJECT, BOOL)
define("keepout_footprints", "Keep Out Footprints", GROUP_OBJECT, BOOL)
define("dim_type", "Dimension Type", GROUP_OBJECT)
define("dim_unit", "Units", GROUP_OBJECT)
define("dim_precision", "Precision", GROUP_OBJECT)
define("prefix", "Prefix", GROUP_OBJECT)
define("suffix", "Suffix", GROUP_OBJECT)

define("x", "X", GROUP_GRAPHICAL, LENGTH)
define("y", "Y", GROUP_GRAPHICAL, LENGTH)
define("start_x", "Start X", GROUP_GRAPHICAL, LENGTH)
define("start_y", "Start Y", GROUP_GRAPHICAL, LENGTH)
define("end_x", "End X", GROUP_GRAPHICAL, LENGTH)
define("end_y", "End Y", GROUP_GRAPHICAL, LENGTH)
define("width", "Width", GROUP_GRAPHICAL, LENGTH)
define("length", "Length", GROUP_GRAPHICAL, LENGTH)
define("radius", "Radius", GROUP_GRAPHICAL, LENGTH)
define("arc_angle", "Arc Angle", GROUP_GRAPHICAL, ANGLE)
define("rotation", "Rotation", GROUP_GRAPHICAL, ANGLE)
define("diameter", "Diameter", GROUP_GRAPHICAL, LENGTH)
define("hole", "Hole Diameter", GROUP_GRAPHICAL, LENGTH)
define("hole_y", "Hole Size Y", GROUP_GRAPHICAL, LENGTH)
define("pad_shape", "Pad Shape", GROUP_GRAPHICAL)
define("size_x", "Size X", GROUP_GRAPHICAL, LENGTH)
define("size_y", "Size Y", GROUP_GRAPHICAL, LENGTH)
define("corner_ratio", "Corner Size %", GROUP_GRAPHICAL, NUMBER)
define("padstack", "Padstack Mode", GROUP_GRAPHICAL)
define("line_width", "Line Width", GROUP_GRAPHICAL, LENGTH)
define("line_style", "Line Style", GROUP_GRAPHICAL)
define("filled", "Fill", GROUP_GRAPHICAL, BOOL)
define("box_width", "Box Width", GROUP_GRAPHICAL, LENGTH)
define("box_height", "Box Height", GROUP_GRAPHICAL, LENGTH)
define("text_width", "Text Width", GROUP_GRAPHICAL, LENGTH)
define("text_height", "Text Height", GROUP_GRAPHICAL, LENGTH)
define("thickness", "Thickness", GROUP_GRAPHICAL, LENGTH)
define("italic", "Italic", GROUP_GRAPHICAL, BOOL)
define("bold", "Bold", GROUP_GRAPHICAL, BOOL)
define("mirrored", "Mirrored", GROUP_GRAPHICAL, BOOL)
define("keep_upright", "Keep Upright", GROUP_GRAPHICAL, BOOL)
define("h_justify", "Horizontal Justification", GROUP_GRAPHICAL)
define("v_justify", "Vertical Justification", GROUP_GRAPHICAL)
define("font", "Font", GROUP_GRAPHICAL)
define("knockout", "Knockout", GROUP_GRAPHICAL, BOOL)

# --- enum names ---------------------------------------------------------------
# Names as KiCad's own dialogs print them. Anything not listed is derived from
# the enum name: PSS_TRAPEZOID -> "Trapezoid".
_ENUM_TEXT = {
    "VT_THROUGH": "Through", "VT_BLIND_BURIED": "Blind/Buried", "VT_MICRO": "Micro",
    "PT_PTH": "Through-hole", "PT_SMD": "SMD", "PT_NPTH": "NPTH, Mechanical",
    "PT_EDGE_CONNECTOR": "Edge Connector",
    "PSS_ROUNDRECT": "Rounded Rectangle", "PSS_CHAMFEREDRECT": "Chamfered Rectangle",
    "PST_NORMAL": "Normal", "PST_FRONT_INNER_BACK": "Front/Inner/Back",
    "ZCS_INHERITED": "From Parent", "ZCS_NONE": "None", "ZCS_THERMAL": "Thermal Reliefs",
    "ZCS_FULL": "Solid", "ZCS_PTH_THERMAL": "Thermal Reliefs for PTH",
    "IRM_ALWAYS": "Always", "IRM_NEVER": "Never", "IRM_AREA": "Below Area Limit",
    "ZFM_SOLID": "Solid", "ZFM_HATCHED": "Hatch Pattern",
    "ZBS_SOLID": "Solid", "ZBS_DIAGONAL_FULL": "Fully Hatched",
    "ZBS_DIAGONAL_EDGE": "Hatched", "ZBS_INVISIBLE": "Invisible",
    "FMS_THROUGH_HOLE": "Through-hole", "FMS_SMD": "SMD", "FMS_UNSPECIFIED": "Unspecified",
    "DU_MILLIMETERS": "mm", "DU_MILS": "mils", "DU_INCHES": "in", "DU_AUTOMATIC": "Automatic",
    "HA_LEFT": "Left", "HA_CENTER": "Center", "HA_RIGHT": "Right",
    "VA_TOP": "Top", "VA_CENTER": "Center", "VA_BOTTOM": "Bottom",
}

_SHAPE_TEXT = {"segment": "Line", "arc": "Arc", "circle": "Circle",
               "rectangle": "Rectangle", "polygon": "Polygon", "bezier": "Bezier"}

_DIM_TEXT = {"aligned": "Aligned", "orthogonal": "Orthogonal", "radial": "Radial",
             "leader": "Leader", "center": "Center Mark"}


def enum_text(message, field_name: str) -> str:
    """The display name of an enum field on a protobuf message."""
    fd = message.DESCRIPTOR.fields_by_name[field_name]
    number = getattr(message, field_name)
    value = fd.enum_type.values_by_number.get(number)
    if value is None:
        return str(number)
    name = value.name
    if name in _ENUM_TEXT:
        return _ENUM_TEXT[name]
    words = name.split("_", 1)[-1].replace("_", " ").lower()
    return words[:1].upper() + words[1:]


def _locked(message) -> bool:
    return message.locked == base_types_pb2.LockedState.LS_LOCKED


def _length(a, b) -> int:
    return int(round(math.hypot(b.x_nm - a.x_nm, b.y_nm - a.y_nm)))


def _circle_through(a, m, b):
    """Centre and radius of the circle through three points, None if collinear."""
    ax, ay, bx, by, cx, cy = a.x_nm, a.y_nm, m.x_nm, m.y_nm, b.x_nm, b.y_nm
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy)


def _arc_values(start, mid, end) -> Dict[str, object]:
    """Radius, swept angle and length of the arc start -> mid -> end."""
    circle = _circle_through(start, mid, end)
    if circle is None:
        return {"radius": 0, "arc_angle": 0.0, "length": _length(start, end)}
    ux, uy, r = circle
    a0 = math.atan2(start.y_nm - uy, start.x_nm - ux)
    a1 = math.atan2(mid.y_nm - uy, mid.x_nm - ux)
    a2 = math.atan2(end.y_nm - uy, end.x_nm - ux)
    sweep = (a2 - a0) % (2 * math.pi)
    # The mid point says which way round the arc goes.
    if (a1 - a0) % (2 * math.pi) > sweep:
        sweep -= 2 * math.pi
    return {"radius": int(round(r)), "arc_angle": norm_angle(math.degrees(sweep)),
            "length": int(round(abs(sweep) * r))}


class BoardReader:
    """Reads the open board into `Obj` records. One instance per board."""

    def __init__(self, board: Board):
        self.board = board
        self._layer_names: Dict[int, str] = {}
        self._netclass: Dict[str, str] = {}
        # From the last read(): every id, and the footprint each child is in.
        self.known: Set[str] = set()
        self.parent_of: Dict[str, str] = {}

    # -- names ---------------------------------------------------------------

    def layer_name(self, layer: int) -> str:
        """The board's own layer name (a user may rename F.Silkscreen)."""
        name = self._layer_names.get(layer)
        if name is None:
            try:
                name = self.board.get_layer_name(layer)
            except Exception:
                name = ""
            if not name:
                name = CANONICAL_LAYER_NAMES.get(layer) or bt.BoardLayer.Name(layer)[3:]
            self._layer_names[layer] = name
        return name

    def _layer_set(self, layers: Iterable[int]) -> str:
        """A pad or zone layer list, in KiCad's order; all copper as *.Cu."""
        layers = list(layers)
        copper = [l for l in layers if CANONICAL_LAYER_NAMES.get(l, "").endswith(".Cu")]
        names = [self.layer_name(l) for l in sorted(layers)]
        if len(copper) > 2 and bt.BoardLayer.BL_F_Cu in copper and bt.BoardLayer.BL_B_Cu in copper:
            cu = {self.layer_name(l) for l in copper}
            names = ["*.Cu"] + [n for n in names if n not in cu]
        return ", ".join(names)

    def _load_netclasses(self) -> None:
        self._netclass = {}
        try:
            nets = self.board.get_nets()
            for net_name, nc in self.board.get_netclass_for_nets(nets).items():
                self._netclass[net_name] = nc.name
        except Exception:
            pass  # Net Class rows are dropped, everything else still works

    def _net(self, v: Dict[str, object], net, on_copper: bool = True) -> None:
        if not on_copper:
            return
        v["net"] = net.name
        if self._netclass:
            v["netclass"] = self._netclass.get(net.name, "")

    # -- read ----------------------------------------------------------------

    def read(self) -> List[Obj]:
        self._load_netclasses()
        board = self.board
        objs: List[Obj] = []
        for item in board.get_tracks():
            objs.append(self._track(item.proto))
        for item in board.get_vias():
            objs.append(self._via(item.proto))
        for item in board.get_shapes():
            objs.append(self._shape(item.proto, None))
        for item in board.get_text():
            p = item.proto
            if isinstance(p, bt.BoardTextBox):
                objs.append(self._textbox(p, None))
            else:
                objs.append(self._text(p, None))
        for item in board.get_zones():
            objs.append(self._zone(item.proto, None))
        for item in board.get_dimensions():
            objs.append(self._dimension(item.proto))
        for fp in board.get_footprints():
            objs.extend(self._footprint(fp.proto))
        self.known = {o.kiid for o in objs}
        self.parent_of = {o.kiid: o.values["parent"] for o in objs if "parent" in o.values}
        return objs

    def from_selection(self, messages: Sequence) -> Optional[List[Obj]]:
        """Template objects built from the selection's own copies of the items.

        Reading them from the selection, not from the last read(), means a
        width edited a second ago in the Properties panel is the width shown.
        Returns None when an item is not in the last read() (it was just
        drawn), so the caller reads the board again and retries."""
        objs = []
        for p in messages:
            kiid = kiid_of(p)
            if kiid is None:
                continue  # a group, a marker: nothing Select Similar matches
            if kiid not in self.known:
                return None
            parent = self.parent_of.get(kiid)
            if isinstance(p, (bt.Track, bt.Arc)):
                objs.append(self._track(p))
            elif isinstance(p, bt.Via):
                objs.append(self._via(p))
            elif isinstance(p, bt.Pad):
                objs.append(self._pad(p, parent or ""))
            elif isinstance(p, bt.Field):
                objs.append(self._field(p, parent or ""))
            elif isinstance(p, bt.BoardText):
                objs.append(self._text(p, parent))
            elif isinstance(p, bt.BoardTextBox):
                objs.append(self._textbox(p, parent))
            elif isinstance(p, bt.BoardGraphicShape):
                objs.append(self._shape(p, parent))
            elif isinstance(p, bt.Zone):
                objs.append(self._zone(p, parent))
            elif isinstance(p, bt.Dimension):
                objs.append(self._dimension(p))
            elif isinstance(p, bt.FootprintInstance):
                objs.append(self._footprint(p)[0])
        return objs

    # -- one function per kind -------------------------------------------------

    @staticmethod
    def _head(kind: str, parent: Optional[str]) -> Dict[str, object]:
        v: Dict[str, object] = {KIND_KEY: kind, OWNER_KEY: "Footprint" if parent is not None else "Board"}
        if parent is not None:
            v["parent"] = parent
        return v

    def _track(self, p) -> Obj:
        arc = isinstance(p, bt.Arc)
        v = self._head("Track Arc" if arc else "Track", None)
        v["layer"] = self.layer_name(p.layer)
        self._net(v, p.net)
        v["locked"] = _locked(p)
        v["width"] = p.width.value_nm
        v["start_x"], v["start_y"] = p.start.x_nm, p.start.y_nm
        v["end_x"], v["end_y"] = p.end.x_nm, p.end.y_nm
        if arc:
            v.update(_arc_values(p.start, p.mid, p.end))
        else:
            v["length"] = _length(p.start, p.end)
        return Obj(p.id.value, v)

    def _via(self, p) -> Obj:
        v = self._head("Via", None)
        v["via_type"] = enum_text(p, "type")
        drill = p.pad_stack.drill
        v["layer_pair"] = f"{self.layer_name(drill.start_layer)} - {self.layer_name(drill.end_layer)}"
        self._net(v, p.net)
        v["locked"] = _locked(p)
        v["x"], v["y"] = p.position.x_nm, p.position.y_nm
        if p.pad_stack.copper_layers:
            v["diameter"] = p.pad_stack.copper_layers[0].size.x_nm
        v["hole"] = drill.diameter.x_nm
        return Obj(p.id.value, v)

    def _pad(self, p, parent: str) -> Obj:
        v = self._head("Pad", parent)
        v["number"] = p.number
        if p.HasField("symbol_pin"):
            v["pin_name"] = p.symbol_pin.name
            v["pin_type"] = enum_text(p.symbol_pin, "type")
        v["pad_type"] = enum_text(p, "type")
        stack = p.pad_stack
        v["layers"] = self._layer_set(stack.layers)
        self._net(v, p.net, p.type != bt.PadType.PT_NPTH)
        v["locked"] = _locked(p)
        v["x"], v["y"] = p.position.x_nm, p.position.y_nm
        v["rotation"] = norm_angle(stack.angle.value_degrees)
        v["padstack"] = enum_text(stack, "type")
        if stack.copper_layers:
            top = stack.copper_layers[0]
            v["pad_shape"] = enum_text(top, "shape")
            v["size_x"], v["size_y"] = top.size.x_nm, top.size.y_nm
            if top.shape == bt.PadStackShape.PSS_ROUNDRECT:
                v["corner_ratio"] = round(top.corner_rounding_ratio * 100.0, 4)
        if p.type in (bt.PadType.PT_PTH, bt.PadType.PT_NPTH):
            v["hole"] = stack.drill.diameter.x_nm
            if stack.drill.shape == bt.DrillShape.DS_OBLONG:
                v["hole_y"] = stack.drill.diameter.y_nm
        return Obj(p.id.value, v)

    def _text_attrs(self, v: Dict[str, object], text, layer: int) -> None:
        """Rows shared by board texts, footprint texts and fields."""
        a = text.attributes
        v["text"] = text.text
        v["layer"] = self.layer_name(layer)
        v["x"], v["y"] = text.position.x_nm, text.position.y_nm
        v["text_width"], v["text_height"] = a.size.x_nm, a.size.y_nm
        v["thickness"] = a.stroke_width.value_nm
        v["rotation"] = norm_angle(a.angle.value_degrees)
        v["italic"], v["bold"], v["mirrored"] = a.italic, a.bold, a.mirrored
        v["keep_upright"] = a.keep_upright
        v["h_justify"] = enum_text(a, "horizontal_alignment")
        v["v_justify"] = enum_text(a, "vertical_alignment")
        v["font"] = a.font_name or "KiCad Font"

    def _text(self, p, parent: Optional[str]) -> Obj:
        v = self._head("Text", parent)
        self._text_attrs(v, p.text, p.layer)
        v["locked"] = _locked(p)
        v["knockout"] = p.knockout
        return Obj(p.id.value, v)

    def _textbox(self, p, parent: Optional[str]) -> Obj:
        v = self._head("Text Box", parent)
        box = p.textbox
        a = box.attributes
        v["text"] = box.text
        v["layer"] = self.layer_name(p.layer)
        v["locked"] = _locked(p)
        v["x"], v["y"] = box.top_left.x_nm, box.top_left.y_nm
        v["box_width"] = abs(box.bottom_right.x_nm - box.top_left.x_nm)
        v["box_height"] = abs(box.bottom_right.y_nm - box.top_left.y_nm)
        v["text_width"], v["text_height"] = a.size.x_nm, a.size.y_nm
        v["thickness"] = a.stroke_width.value_nm
        v["rotation"] = norm_angle(a.angle.value_degrees)
        v["italic"], v["bold"], v["mirrored"] = a.italic, a.bold, a.mirrored
        v["font"] = a.font_name or "KiCad Font"
        return Obj(p.id.value, v)

    def _field(self, f, parent: str) -> Obj:
        v = self._head("Field", parent)
        v["field_name"] = f.name
        self._text_attrs(v, f.text.text, f.text.layer)
        v["visible"] = f.visible
        v["locked"] = _locked(f.text)
        v["knockout"] = f.text.knockout
        return Obj(f.text.id.value, v)

    def _shape(self, p, parent: Optional[str]) -> Obj:
        v = self._head("Graphic", parent)
        s = p.shape
        geometry = s.WhichOneof("geometry") or ""
        v["shape_type"] = _SHAPE_TEXT.get(geometry, geometry.title())
        v["layer"] = self.layer_name(p.layer)
        on_copper = CANONICAL_LAYER_NAMES.get(p.layer, "").endswith(".Cu")
        self._net(v, p.net, on_copper)
        v["locked"] = _locked(p)
        v["line_width"] = s.attributes.stroke.width.value_nm
        v["line_style"] = enum_text(s.attributes.stroke, "style")
        v["filled"] = s.attributes.fill.fill_type == base_types_pb2.GraphicFillType.GFT_FILLED
        if geometry == "segment":
            g = s.segment
            v["start_x"], v["start_y"] = g.start.x_nm, g.start.y_nm
            v["end_x"], v["end_y"] = g.end.x_nm, g.end.y_nm
            v["length"] = _length(g.start, g.end)
        elif geometry == "arc":
            g = s.arc
            v["start_x"], v["start_y"] = g.start.x_nm, g.start.y_nm
            v["end_x"], v["end_y"] = g.end.x_nm, g.end.y_nm
            v.update(_arc_values(g.start, g.mid, g.end))
        elif geometry == "circle":
            g = s.circle
            v["x"], v["y"] = g.center.x_nm, g.center.y_nm
            v["radius"] = _length(g.center, g.radius_point)
        elif geometry == "rectangle":
            g = s.rectangle
            v["start_x"], v["start_y"] = g.top_left.x_nm, g.top_left.y_nm
            v["end_x"], v["end_y"] = g.bottom_right.x_nm, g.bottom_right.y_nm
            v["box_width"] = abs(g.bottom_right.x_nm - g.top_left.x_nm)
            v["box_height"] = abs(g.bottom_right.y_nm - g.top_left.y_nm)
        return Obj(p.id.value, v)

    def _zone(self, p, parent: Optional[str]) -> Obj:
        rule_area = p.type == bt.ZoneType.ZT_RULE_AREA
        v = self._head("Rule Area" if rule_area else "Zone", parent)
        v["name"] = p.name
        v["layers"] = self._layer_set(p.layers)
        v["locked"] = _locked(p)
        if rule_area:
            r = p.rule_area_settings
            v["keepout_tracks"] = r.keepout_tracks
            v["keepout_vias"] = r.keepout_vias
            v["keepout_pads"] = r.keepout_pads
            v["keepout_copper"] = r.keepout_copper
            v["keepout_footprints"] = r.keepout_footprints
        else:
            c = p.copper_settings
            self._net(v, c.net, p.type == bt.ZoneType.ZT_COPPER)
            v["priority"] = p.priority
            v["zone_connection"] = enum_text(c.connection, "zone_connection")
            v["thermal_gap"] = c.connection.thermal_spokes.gap.value_nm
            v["thermal_spoke"] = c.connection.thermal_spokes.width.value_nm
            v["clearance"] = c.clearance.value_nm
            v["min_width"] = c.min_thickness.value_nm
            v["island_mode"] = enum_text(c, "island_mode")
            v["fill_mode"] = enum_text(c, "fill_mode")
        v["border_style"] = enum_text(p.border, "style")
        return Obj(p.id.value, v)

    def _dimension(self, p) -> Obj:
        v = self._head("Dimension", None)
        style = p.WhichOneof("dimension_style") or ""
        v["dim_type"] = _DIM_TEXT.get(style, style.title())
        v["layer"] = self.layer_name(p.layer)
        v["locked"] = _locked(p)
        v["dim_unit"] = enum_text(p, "unit")
        v["dim_precision"] = enum_text(p, "precision")
        v["prefix"], v["suffix"] = p.prefix, p.suffix
        v["line_width"] = p.line_thickness.value_nm
        a = p.text.attributes
        v["text_width"], v["text_height"] = a.size.x_nm, a.size.y_nm
        v["thickness"] = a.stroke_width.value_nm
        return Obj(p.id.value, v)

    def _footprint(self, p) -> List[Obj]:
        ref = p.reference_field.text.text.text
        v = self._head("Footprint", None)
        v["reference"] = ref
        v["value"] = p.value_field.text.text.text
        lib = p.definition.id
        v["lib_id"] = f"{lib.library_nickname}:{lib.entry_name}" if lib.library_nickname else lib.entry_name
        v["layer"] = self.layer_name(p.layer)
        v["locked"] = _locked(p)
        attrs = p.attributes
        v["mounting"] = enum_text(attrs, "mounting_style")
        v["dnp"] = attrs.do_not_populate
        v["exclude_bom"] = attrs.exclude_from_bill_of_materials
        v["exclude_pos"] = attrs.exclude_from_position_files
        v["not_in_schematic"] = attrs.not_in_schematic
        v["sheet"] = p.symbol_sheet_name
        v["x"], v["y"] = p.position.x_nm, p.position.y_nm
        v["rotation"] = norm_angle(p.orientation.value_degrees)
        v[FIELD_PREFIX + "Datasheet"] = p.datasheet_field.text.text.text
        v[FIELD_PREFIX + "Description"] = p.description_field.text.text.text

        objs = []
        for f in (p.reference_field, p.value_field, p.datasheet_field, p.description_field):
            if f.text.id.value:
                objs.append(self._field(f, ref))
        for packed in p.definition.items:
            child = unpack_any(packed)
            if isinstance(child, bt.Field):
                v.setdefault(FIELD_PREFIX + child.name, child.text.text.text)
                objs.append(self._field(child, ref))
            elif isinstance(child, bt.Pad):
                objs.append(self._pad(child, ref))
            elif isinstance(child, bt.BoardText):
                objs.append(self._text(child, ref))
            elif isinstance(child, bt.BoardTextBox):
                objs.append(self._textbox(child, ref))
            elif isinstance(child, bt.BoardGraphicShape):
                objs.append(self._shape(child, ref))
            elif isinstance(child, bt.Zone):
                objs.append(self._zone(child, ref))
            # Footprint3DModel and anything newer: not selectable on its own
        return [Obj(p.id.value, v)] + objs


# --- talking to KiCad -----------------------------------------------------------

_MATCHABLE = (bt.Track, bt.Arc, bt.Via, bt.Pad, bt.BoardText, bt.BoardTextBox,
              bt.BoardGraphicShape, bt.Zone, bt.Dimension, bt.FootprintInstance)


def kiid_of(message) -> Optional[str]:
    """The id `Obj.kiid` uses for a message, None for a kind it never matches."""
    if isinstance(message, bt.Field):
        return message.text.id.value
    if isinstance(message, _MATCHABLE):
        return message.id.value
    return None


def get_selection(board: Board) -> List:
    """The selected items as raw messages.

    Not kipy's `Board.get_selection`: that asserts on any item type kipy has
    no wrapper for, and one such item in the selection would fail the call."""
    cmd = ec.GetSelection()
    cmd.header.document.CopyFrom(board.document)
    response = board.client.send(cmd, ec.SelectionResponse)
    messages = []
    for packed in response.items:
        try:
            messages.append(unpack_any(packed))
        except Exception:
            continue
    return messages


def select(board: Board, kiids: Sequence[str], clear_first: bool) -> None:
    """Put `kiids` into KiCad's selection, so its Properties panel edits them."""
    if clear_first:
        board.clear_selection()
    if not kiids:
        return
    cmd = ec.AddToSelection()
    cmd.header.document.CopyFrom(board.document)
    for kiid in kiids:
        cmd.items.add().value = kiid
    board.client.send(cmd, ec.SelectionResponse)


class KiCadBusy(Exception):
    """KiCad is in a tool or a dialog and refuses commands for now."""


class KiCadGone(Exception):
    """No PCB editor to talk to: KiCad closed, restarted, or no board open."""


class Session:
    """The connection to one PCB editor, with kipy's errors made into two."""

    def __init__(self, kicad):
        self.kicad = kicad
        self.board: Optional[Board] = None
        self.reader: Optional[BoardReader] = None
        self._call(self._attach)

    @property
    def board_name(self) -> str:
        return self.board.name if self.board else ""

    def _attach(self) -> None:
        board = self.kicad.get_board()
        if self.board is None or board.name != self.board.name:
            self.reader = BoardReader(board)
        else:
            self.reader.board = board
        self.board = board

    def _call(self, fn):
        from kipy.errors import ApiError, ConnectionError as KipyConnectionError
        from kipy.proto.common import ApiStatusCode
        for attempt in (1, 2):
            try:
                return fn()
            except KipyConnectionError as e:
                raise KiCadGone(str(e)) from None
            except ApiError as e:
                if e.code == ApiStatusCode.AS_BUSY:
                    raise KiCadBusy(str(e)) from None
                if e.code == ApiStatusCode.AS_TOKEN_MISMATCH or attempt == 2:
                    raise KiCadGone(str(e)) from None
                # The usual cause: another board was opened in the PCB editor,
                # and the old document no longer validates. Attach and retry.
                try:
                    self._attach()
                except (ApiError, KipyConnectionError) as e2:
                    raise KiCadGone(str(e2)) from None

    def read(self) -> List[Obj]:
        return self._call(lambda: self.reader.read())

    def selection(self) -> List:
        return self._call(lambda: get_selection(self.board))

    def templates(self, messages: Sequence) -> List[Obj]:
        """Template objects for selected `messages`, reading the board again
        when one of them is newer than the last read."""
        objs = self.reader.from_selection(messages)
        if objs is None:
            self.read()
            objs = self.reader.from_selection(messages) or []
        return objs

    def apply(self, kiids: Sequence[str], select_matching: bool, zoom_matching: bool,
              clear_existing: bool) -> None:
        """Altium's Select Matching / Zoom Matching / Clear Existing.

        KiCad zooms to a selection, not to a list of items, so Zoom Matching
        without Select Matching selects the matches for the zoom, then puts the
        previous selection back (or leaves none, under Clear Existing)."""
        def run():
            if select_matching:
                select(self.board, kiids, clear_existing)
                if zoom_matching and kiids:
                    zoom_to_selection(self.kicad)
            elif zoom_matching and kiids:
                previous = [k for k in map(kiid_of, get_selection(self.board)) if k]
                select(self.board, kiids, True)
                zoom_to_selection(self.kicad)
                select(self.board, [] if clear_existing else previous, True)
            elif clear_existing:
                self.board.clear_selection()
        self._call(run)


def zoom_to_selection(kicad) -> bool:
    """Run KiCad's Zoom to Selection. False if this KiCad does not know it.

    Action names are not API (KiCad says so); this one is
    `ACTIONS::zoomFitSelection` in common/tool/actions.cpp, 10.0 branch."""
    try:
        response = kicad.run_action(ZOOM_TO_SELECTION)
        return response.status == ec.RunActionStatus.RAS_OK
    except Exception:
        return False
