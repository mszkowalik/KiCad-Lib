"""Matching rules. Pure Python: runs with any Python 3.9+, no KiCad, no kipy.

    python3 -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from similar_engine import (ANGLE, ANY, BOOL, DIFFERENT, FIELD_PREFIX, GROUP_GRAPHICAL,  # noqa: E402
                            GROUP_KIND, GROUP_OBJECT, GROUP_PARAMETERS, KIND_KEY, LENGTH,
                            OWNER_KEY, SAME, Criterion, Obj, attr_for,
                            criteria_from_templates, define, find_matches, fmt, norm_angle,
                            parse_value, summarize, wildcard)

define(KIND_KEY, "Object Kind", GROUP_KIND)
define(OWNER_KEY, "Owner", GROUP_KIND)
define("net", "Net", GROUP_OBJECT)
define("number", "Pad Number", GROUP_OBJECT)
define("locked", "Locked", GROUP_OBJECT, BOOL)
define("width", "Width", GROUP_GRAPHICAL, LENGTH)
define("rotation", "Rotation", GROUP_GRAPHICAL, ANGLE)


def obj(kiid, kind, owner="Board", **values):
    return Obj(kiid, {KIND_KEY: kind, OWNER_KEY: owner, **values})


BOARD = [
    obj("t1", "Track", net="GND", width=250_000, locked=False),
    obj("t2", "Track", net="GND", width=500_000, locked=True),
    obj("t3", "Track", net="D[0]", width=250_000, locked=False),
    obj("v1", "Via", net="GND", locked=False),
    obj("p1", "Pad", "Footprint", net="GND", number="1", rotation=90.0),
    obj("p2", "Pad", "Footprint", net="VCC", number="2", rotation=-270.0),
]


def row(criteria, key):
    return next(c for c in criteria if c.key == key)


class Defaults(unittest.TestCase):
    def test_kind_and_owner_start_same_and_the_rest_any(self):
        crit = criteria_from_templates([BOARD[0]])
        self.assertEqual(row(crit, KIND_KEY).mode, SAME)
        self.assertEqual(row(crit, OWNER_KEY).mode, SAME)
        self.assertEqual({c.mode for c in crit if c.key not in (KIND_KEY, OWNER_KEY)}, {ANY})

    def test_default_grid_finds_every_object_of_the_kind(self):
        crit = criteria_from_templates([BOARD[0]])
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t1", "t2", "t3"])

    def test_rows_are_ordered_by_group(self):
        groups = [c.attr.group for c in criteria_from_templates([BOARD[0]])]
        self.assertEqual(groups, sorted(groups, key=[GROUP_KIND, GROUP_OBJECT, GROUP_GRAPHICAL,
                                                      GROUP_PARAMETERS].index))


class Modes(unittest.TestCase):
    def test_same_and_different(self):
        crit = criteria_from_templates([BOARD[0]])
        row(crit, "width").mode = SAME
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t1", "t3"])
        row(crit, "width").mode = DIFFERENT
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t2"])

    def test_kind_any_crosses_kinds_on_shared_keys(self):
        crit = criteria_from_templates([BOARD[0]])
        row(crit, KIND_KEY).mode = ANY
        row(crit, OWNER_KEY).mode = ANY
        row(crit, "net").mode = SAME
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t1", "t2", "v1", "p1"])

    def test_missing_attribute_matches_neither_same_nor_different(self):
        crit = [Criterion("width", DIFFERENT, (250_000,))]
        # vias and pads have no Width: Different must not sweep them in
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t2"])

    def test_several_templates_mean_one_of_them(self):
        crit = criteria_from_templates([BOARD[0], BOARD[1]])
        row(crit, "width").mode = SAME
        self.assertEqual(row(crit, "width").display_value(), "<2 values>")
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t1", "t2", "t3"])


class Patterns(unittest.TestCase):
    def test_wildcards_are_star_and_question_mark_only(self):
        self.assertTrue(wildcard("D[0]").match("D[0]"))
        self.assertFalse(wildcard("D[0]").match("D0"))
        self.assertTrue(wildcard("g?d").match("GND"))
        self.assertTrue(wildcard("*_3V3").match("IOB_3V3"))
        self.assertFalse(wildcard("GND").match("GND_ISO"))

    def test_text_pattern(self):
        crit = [Criterion("net", SAME, ("GND",), pattern="D*")]
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t3"])

    def test_typed_length_is_a_value_in_mm(self):
        crit = [Criterion("width", SAME, (250_000,), pattern="0.5")]
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t2"])
        crit[0].pattern = "0.5 mm"
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t2"])

    def test_length_wildcard_reads_the_displayed_text(self):
        crit = [Criterion("width", SAME, (250_000,), pattern="0.2*")]
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t1", "t3"])

    def test_imperial_text_is_not_converted(self):
        # The user's rule: no unit conversion without asking. "10mil" is not
        # a number in mm, so it is a pattern, and it matches nothing.
        self.assertEqual(parse_value(LENGTH, "10mil"), (False, None))

    def test_angles_compare_folded(self):
        crit = [Criterion("rotation", SAME, (90.0,))]
        # -270 and 90 are one orientation once stored folded
        board = [obj("a", "Pad", rotation=norm_angle(90.0)), obj("b", "Pad", rotation=norm_angle(-270.0))]
        self.assertEqual(len(find_matches(board, crit)), 2)
        crit[0].pattern = "-270"
        self.assertEqual(len(find_matches(board, crit)), 2)

    def test_bool_words(self):
        crit = [Criterion("locked", SAME, (False,), pattern="yes")]
        self.assertEqual([o.kiid for o in find_matches(BOARD, crit)], ["t2"])


class Formatting(unittest.TestCase):
    def test_lengths_in_mm_without_trailing_zeros(self):
        self.assertEqual(fmt(LENGTH, 250_000), "0.25 mm")
        self.assertEqual(fmt(LENGTH, 330_686_109), "330.686109 mm")
        self.assertEqual(fmt(LENGTH, 0), "0 mm")

    def test_angle_range_is_kicads(self):
        self.assertEqual(norm_angle(270.0), -90.0)
        self.assertEqual(norm_angle(-180.0), 180.0)
        self.assertEqual(norm_angle(-0.0), 0.0)

    def test_footprint_fields_are_parameters(self):
        self.assertEqual(attr_for(FIELD_PREFIX + "LCSC Part").group, GROUP_PARAMETERS)
        self.assertEqual(attr_for(FIELD_PREFIX + "LCSC Part").label, "LCSC Part")

    def test_summary(self):
        self.assertEqual(summarize(BOARD[:4]), "4 objects: Track 3, Via 1")
        self.assertEqual(summarize([]), "No matching objects")


if __name__ == "__main__":
    unittest.main()
