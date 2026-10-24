"""Reading board messages into objects. Needs kipy (the plugin's venv has it),
not a running KiCad: the board is a stub that hands back hand-built messages."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from kipy.proto.board import board_types_pb2 as bt
    from kipy.proto.common.commands import editor_commands_pb2 as ec
    from kipy.util.proto import pack_any
except ImportError:  # pragma: no cover
    bt = None

if bt is not None:
    import similar_board as sb
    from similar_engine import FIELD_PREFIX


def wrap(message):
    return SimpleNamespace(proto=message)


class StubBoard:
    def __init__(self, tracks=(), footprints=()):
        self.tracks, self.footprints = list(tracks), list(footprints)
        self.sent = []
        self.document = ec.GetSelection().header.document  # an empty DocumentSpecifier
        self.client = SimpleNamespace(send=lambda cmd, resp: self.sent.append(cmd) or resp())

    def get_tracks(self): return [wrap(t) for t in self.tracks]
    def get_vias(self): return []
    def get_shapes(self): return []
    def get_text(self): return []
    def get_zones(self): return []
    def get_dimensions(self): return []
    def get_footprints(self): return [wrap(f) for f in self.footprints]
    def get_nets(self): return []
    def get_netclass_for_nets(self, nets): return {}
    def get_layer_name(self, layer): return {bt.BL_F_SilkS: "F.Silkscreen"}.get(layer, "")
    def clear_selection(self): self.sent.append("clear")


def footprint():
    fp = bt.FootprintInstance()
    fp.id.value = "fp-1"
    fp.layer = bt.BL_F_Cu
    fp.reference_field.id.id = 1
    fp.reference_field.name = "Reference"
    fp.reference_field.text.id.value = "ref-text"
    fp.reference_field.text.text.text = "R7"
    fp.reference_field.text.layer = bt.BL_F_SilkS
    fp.reference_field.visible = True
    fp.value_field.text.id.value = "val-text"
    fp.value_field.text.text.text = "10k"

    user = bt.Field()
    user.name = "LCSC Part"
    user.text.id.value = "lcsc-text"
    user.text.text.text = "C25804"
    fp.definition.items.append(pack_any(user))

    smd = bt.Pad()
    smd.id.value = "pad-smd"
    smd.number = "1"
    smd.type = bt.PT_SMD
    smd.net.name = "GND"
    smd.pad_stack.layers.extend([bt.BL_F_Cu, bt.BL_F_Paste, bt.BL_F_Mask])
    layer = smd.pad_stack.copper_layers.add()
    layer.layer = bt.BL_F_Cu
    layer.shape = bt.PSS_ROUNDRECT
    layer.size.x_nm, layer.size.y_nm = 1_000_000, 600_000
    layer.corner_rounding_ratio = 0.25
    fp.definition.items.append(pack_any(smd))

    npth = bt.Pad()
    npth.id.value = "pad-npth"
    npth.type = bt.PT_NPTH
    npth.pad_stack.layers.extend([bt.BL_F_Cu, bt.BL_In1_Cu, bt.BL_B_Cu, bt.BL_F_Mask])
    npth.pad_stack.drill.diameter.x_nm = 1_000_000
    npth.pad_stack.drill.diameter.y_nm = 2_000_000
    npth.pad_stack.drill.shape = bt.DS_OBLONG
    fp.definition.items.append(pack_any(npth))
    return fp


def arc_track():
    a = bt.Arc()
    a.id.value = "arc-1"
    a.layer = bt.BL_F_Cu
    a.width.value_nm = 200_000
    # quarter circle of radius 1 mm, centre (0, 0): (1,0) -> (0.7071,0.7071) -> (0,1)
    a.start.x_nm, a.start.y_nm = 1_000_000, 0
    a.mid.x_nm, a.mid.y_nm = 707_107, 707_107
    a.end.x_nm, a.end.y_nm = 0, 1_000_000
    return a


@unittest.skipIf(bt is None, "kipy is not installed")
class Reader(unittest.TestCase):
    def setUp(self):
        self.board = StubBoard(tracks=[arc_track()], footprints=[footprint()])
        self.reader = sb.BoardReader(self.board)
        self.objs = {o.kiid: o for o in self.reader.read()}

    def test_a_field_is_selected_by_its_text_id(self):
        ref = self.objs["ref-text"]
        self.assertEqual(ref.kind, "Field")
        self.assertEqual(ref.values["field_name"], "Reference")
        self.assertEqual(ref.values["parent"], "R7")
        self.assertEqual(ref.values["layer"], "F.Silkscreen")  # the board's own name
        self.assertIn("lcsc-text", self.objs)

    def test_user_fields_become_footprint_parameters(self):
        fp = self.objs["fp-1"]
        self.assertEqual(fp.values[FIELD_PREFIX + "LCSC Part"], "C25804")
        self.assertEqual(fp.values["reference"], "R7")

    def test_pads_carry_their_footprint(self):
        pad = self.objs["pad-smd"]
        self.assertEqual((pad.kind, pad.values["owner"], pad.values["parent"]), ("Pad", "Footprint", "R7"))
        self.assertEqual(pad.values["pad_shape"], "Rounded Rectangle")
        self.assertEqual(pad.values["corner_ratio"], 25.0)
        self.assertNotIn("hole", pad.values)

    def test_npth_has_no_net_and_an_oval_hole(self):
        pad = self.objs["pad-npth"]
        self.assertNotIn("net", pad.values)
        self.assertEqual((pad.values["hole"], pad.values["hole_y"]), (1_000_000, 2_000_000))
        self.assertTrue(pad.values["layers"].startswith("*.Cu"))

    def test_arc_track_geometry(self):
        arc = self.objs["arc-1"]
        self.assertEqual(arc.kind, "Track Arc")
        self.assertAlmostEqual(arc.values["radius"], 1_000_000, delta=2)
        self.assertAlmostEqual(arc.values["arc_angle"], 90.0, places=3)
        self.assertAlmostEqual(arc.values["length"], 1_570_796, delta=3)

    def test_selection_of_an_unread_item_asks_for_a_new_read(self):
        stranger = bt.Pad()
        stranger.id.value = "drawn-just-now"
        self.assertIsNone(self.reader.from_selection([stranger]))

    def test_selection_keeps_the_parent_of_a_pad(self):
        pad = unpack_pad(footprint(), "pad-smd")
        pad.net.name = "VCC"  # edited after the last read: the selection copy wins
        [obj] = self.reader.from_selection([pad])
        self.assertEqual((obj.values["parent"], obj.values["net"]), ("R7", "VCC"))

    def test_select_sends_text_ids(self):
        sb.select(self.board, ["ref-text", "pad-smd"], clear_first=True)
        self.assertEqual(self.board.sent[0], "clear")
        self.assertEqual([i.value for i in self.board.sent[1].items], ["ref-text", "pad-smd"])

    def test_kiid_of(self):
        field = footprint().reference_field
        self.assertEqual(sb.kiid_of(field), "ref-text")
        self.assertIsNone(sb.kiid_of(bt.Group()))


def unpack_pad(fp, kiid):
    from kipy.util.proto import unpack_any
    for packed in fp.definition.items:
        item = unpack_any(packed)
        if isinstance(item, bt.Pad) and item.id.value == kiid:
            return item
    raise KeyError(kiid)


if __name__ == "__main__":
    unittest.main()
