"""JLC pick-and-place correction (decision 0110).

The rotation cases are the ones confirmed in JLC's placement preview on
EVSE_20_CTRL, 2026-11-13: the reference, its board angle and side, the
component's correction, and the rotation JLC showed as right.
"""
import pytest

from app import models as M
from app.services import jlc_placement as J
from app.services import signoff


@pytest.mark.parametrize("ref,angle,side,offset,expected", [
    ("U29 TLV9061 SOT-23-5 -BL", 0, "top", 270, 270),
    ("U1 STM32H743 LQFP-100", 0, "top", 270, 270),
    ("U27 PCF8574 QFN-16 -TL", 90, "top", 0, 90),
    ("U300 TPS7A1650 DFN-8", 90, "top", 0, 90),
    ("U16 TPS7A2012 SOT-23-5 -BR", 0, "top", 180, 180),
    ("U301 TLV9061 bottom", 90, "bottom", 270, 0),
    ("U26 SN74LVC1G123 SSOP-8 bottom", 180, "bottom", 180, 180),
    ("U302 TLV3201 bottom", -90, "bottom", 180, 90),
])
def test_rotation_matches_the_jlc_preview(ref, angle, side, offset, expected):
    assert J.cpl_rotation(angle, side, offset) == expected, ref


def test_no_offset_is_the_board_angle():
    assert J.cpl_rotation(-90, "top", None) == 270
    assert J.cpl_rotation(0, "bottom", None) == 180


@pytest.mark.parametrize("raw,expected", [
    ("90", 90.0), ("-90", -90.0), (" 180.0 ", 180.0), ("", None), (None, None), ("x", None),
])
def test_parse_rotation(raw, expected):
    assert J.parse_rotation(raw) == expected


def test_parse_position():
    assert J.parse_position("1.468,0") == (1.468, 0.0)
    assert J.parse_position("1.468") is None
    assert J.parse_position(None) is None


def test_position_offset_turns_with_the_part():
    p = J.Placement("U19", x=10.0, y=-20.0, angle=90.0, side="top", smd=True, dnp=False, excluded=False)
    # +1 mm along the footprint's x, part turned 90 deg CCW: the offset points up.
    assert J.cpl_position(p, (1.0, 0.0)) == (10.0, 21.0)
    assert J.cpl_position(p, None) == (10.0, 20.0)


PCB = """(kicad_pcb (version 20250101)
  (footprint "7Sigma:SOT-23-5" (layer "F.Cu") (at 100 50 90)
    (property "Reference" "U1") (attr smd))
  (footprint "7Sigma:SOT-23-5" (layer "B.Cu") (at 110 60)
    (property "Reference" "U2") (attr smd dnp))
  (footprint "7Sigma:Conn" (layer "F.Cu") (at 120 70 180)
    (property "Reference" "J1") (attr through_hole exclude_from_pos_files))
)"""


def test_board_placements_reads_side_angle_and_attrs():
    pl = J.board_placements(PCB)
    assert pl["U1"].side == "top" and pl["U1"].angle == 90.0 and pl["U1"].smd
    assert pl["U2"].side == "bottom" and pl["U2"].angle == 0.0 and pl["U2"].dnp
    assert pl["J1"].excluded and not pl["J1"].smd


def test_a_through_hole_part_is_placed_at_the_centre_of_its_pads():
    # Pads at local x 0 and 5.08: the centre is 2.54 along the part's own x.
    pcb = """(kicad_pcb
      (footprint "7Sigma:TB" (layer "F.Cu") (at 100 50)
        (property "Reference" "J2") (attr through_hole)
        (pad "1" thru_hole circle (at 0 0) (size 2 2))
        (pad "2" thru_hole circle (at 5.08 0) (size 2 2)))
      (footprint "7Sigma:TB" (layer "F.Cu") (at 100 50 90)
        (property "Reference" "J3") (attr through_hole)
        (pad "1" thru_hole circle (at 0 0 90) (size 2 2))
        (pad "2" thru_hole circle (at 5.08 0 90) (size 2 2))))"""
    pl = J.board_placements(pcb)
    assert (pl["J2"].x, pl["J2"].y) == (102.54, 50.0)
    # Turned 90 deg counter-clockwise, the part's +x points UP (y down in KiCad).
    assert (round(pl["J3"].x, 3), round(pl["J3"].y, 3)) == (100.0, 47.46)


def _fp(pads):
    body = "".join(f'(pad "{n}" smd roundrect (at {x} {y}) (size 1 0.6) (layers "F.Cu"))'
                   for n, x, y in pads)
    return f'(footprint "X" (layer "F.Cu") {body})'


# Our SOT-23-5: pin 1 top-left (KiCad y points down).
OURS = [("1", -1.1, -1.0), ("2", -1.1, 0.0), ("3", -1.1, 1.0), ("4", 1.1, 1.0), ("5", 1.1, -1.0)]


def _turn(pads, deg, dx=0.0, dy=0.0):
    return [(n, round(J._rot(x, y, deg)[0] + dx, 6), round(J._rot(x, y, deg)[1] + dy, 6)) for n, x, y in pads]


def test_measure_bl_land_needs_270():
    # A "-BL" land: pin 1 bottom-left = ours turned 90 deg counter-clockwise.
    res = J.measure(_fp(OURS), _fp(_turn(OURS, 90)))
    assert res["rotation_offset"] == 270 and res["confidence"] == "high"
    assert res["position_offset"] == [0.0, 0.0]


def test_measure_reads_easyeda2kicad_unquoted_pad_numbers():
    # easyeda2kicad writes (pad 1 smd …) without quotes; ours says (pad "1" …).
    jlc = _fp(_turn(OURS, 90)).replace('(pad "', "(pad ").replace('" smd', " smd")
    assert "(pad 1 smd" in jlc
    assert J.measure(_fp(OURS), jlc)["rotation_offset"] == 270


def test_measure_br_land_needs_180():
    res = J.measure(_fp(OURS), _fp(_turn(OURS, 180)))
    assert res["rotation_offset"] == 180


def test_measure_reports_the_origin_shift():
    # JLC's land sits 1.5 mm to the right of ours: its origin is at x = -1.5 in ours.
    res = J.measure(_fp(OURS), _fp(_turn(OURS, 0, dx=1.5)))
    assert res["rotation_offset"] == 0
    assert res["position_offset"] == [-1.5, 0.0]


def test_measure_two_pad_part_is_decided_by_its_numbering():
    # A diode's 0 and 180 deg differ, and the pad numbers say which one fits.
    chip = [("1", -0.5, 0.0), ("2", 0.5, 0.0)]
    assert J.measure(_fp(chip), _fp(_turn(chip, 180)))["rotation_offset"] == 180


def test_measure_symmetric_land_is_low_confidence():
    # Like the U.FL: repeated pad numbers placed symmetrically average to the
    # centre, so every quarter turn fits and the copper cannot decide.
    sym = [("1", -1.0, 0.0), ("1", 1.0, 0.0), ("2", 0.0, -1.0), ("2", 0.0, 1.0)]
    assert J.measure(_fp(sym), _fp(sym))["confidence"] == "low"


def test_measure_refuses_different_numbering():
    res = J.measure(_fp(OURS), _fp([("A", 0, 0), ("B", 1, 0)]))
    assert "error" in res and "rotation_offset" not in res


def test_check_cpl_flags_a_wrong_rotation_only_where_an_offset_is_known():
    expected = {"rows": [
        {"ref": "U29", "rotation": 270.0, "offset": 270.0, "lcsc": "C398358"},
        {"ref": "C1", "rotation": 0.0, "offset": None, "lcsc": "C1525"},
    ]}
    cpl = b"Designator,Mid X,Mid Y,Rotation,Layer\nU29,1,2,180,top\nC1,3,4,90,top\n"
    res = J.check_cpl(expected, cpl)
    assert res["checked"] == 1
    assert res["mismatches"] == [{"ref": "U29", "file": 180.0, "expected": 270.0, "lcsc": "C398358",
                                  "component_id": None}]


def test_check_cpl_accepts_minus_90_for_270():
    expected = {"rows": [{"ref": "U1", "rotation": 270.0, "offset": 270.0, "lcsc": "C1"}]}
    assert J.check_cpl(expected, b"Designator,Rotation\nU1,-90\n")["mismatches"] == []


def _cv(props):
    cv = M.ComponentVersion(base_component="SOT23-5", category_id=1, removed_properties=[])
    cv.properties = [M.ComponentProperty(position=i, key=k, value=v, is_null=False)
                     for i, (k, v) in enumerate(props)]
    return cv


def test_writing_a_rotation_offset_keeps_the_signoff_and_the_verification():
    old = _cv([("Value", "TLV9061IDBVR"), ("LCSC Part", "C398358")])
    new = _cv([("Value", "TLV9061IDBVR"), ("LCSC Part", "C398358"),
               ("FT Rotation Offset", "270"), ("FT Position Offset", "0,0")])
    assert signoff.data_carries(old, new) == (True, "")
    changed = _cv([("Value", "TLV9061IDBVR"), ("LCSC Part", "C398358"), ("FT Rotation Offset", "180")])
    assert signoff.data_carries(new, changed) == (True, "")
