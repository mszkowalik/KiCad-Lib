"""The matching half of Select Similar: attributes, values, criteria.

Nothing here imports kipy, so the tests run without KiCad. `similar_board.py`
turns board items into `Obj` records; this module decides which of them match.

Semantics follow Altium's Find Similar Objects:
- every attribute row has a match mode: Any, Same or Different;
- Object Kind starts at Same, every other row at Any;
- a value typed into the Value column is a pattern, `*` and `?` are wildcards.

Two rules Altium leaves unstated, decided here:
- an object that does not have an attribute never matches a Same or Different
  row on it (a via has no Pad Number, so "Pad Number Different 1" skips vias);
- with several template objects, Same means "equal to one of them".
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ANY, SAME, DIFFERENT = "Any", "Same", "Different"
MODES = (ANY, SAME, DIFFERENT)

GROUP_KIND = "Kind"
GROUP_OBJECT = "Object Specific"
GROUP_GRAPHICAL = "Graphical"
GROUP_PARAMETERS = "Parameters"
GROUPS = (GROUP_KIND, GROUP_OBJECT, GROUP_GRAPHICAL, GROUP_PARAMETERS)

# Value types. LENGTH values are integer nanometres, ANGLE values degrees.
TEXT, LENGTH, ANGLE, BOOL, NUMBER = "text", "length", "angle", "bool", "number"

KIND_KEY = "kind"
OWNER_KEY = "owner"
FIELD_PREFIX = "field:"

# Rows that start at Same. Object Kind is Altium's default. Owner keeps the
# Altium scope: Altium never matches a footprint's own lines and texts, so a
# board line matches board lines until Owner is set to Any.
DEFAULT_SAME = (KIND_KEY, OWNER_KEY)


@dataclass(frozen=True)
class Attr:
    key: str
    label: str
    group: str
    vtype: str = TEXT


_REGISTRY: Dict[str, Attr] = {}


def define(key: str, label: str, group: str, vtype: str = TEXT) -> Attr:
    attr = Attr(key, label, group, vtype)
    _REGISTRY[key] = attr
    return attr


def attr_for(key: str) -> Attr:
    """The definition of `key`. A footprint field becomes a Parameters row."""
    attr = _REGISTRY.get(key)
    if attr is None and key.startswith(FIELD_PREFIX):
        attr = Attr(key, key[len(FIELD_PREFIX):], GROUP_PARAMETERS, TEXT)
        _REGISTRY[key] = attr
    if attr is None:
        raise KeyError(key)
    return attr


@dataclass
class Obj:
    """One selectable board object.

    `values` maps attribute keys to canonical values, in display order.
    `kiid` is the id KiCad's selection takes; for a footprint field that is
    the id of its text, not its field number.
    """
    kiid: str
    values: Dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.values.get(KIND_KEY, "")

    def describe(self) -> str:
        parent = self.values.get("parent")
        name = (self.values.get("reference") or self.values.get("number")
                or self.values.get("field_name") or self.values.get("name") or "")
        text = f"{self.kind} {name}".strip()
        if parent:
            text += f" of {parent}"
        return text


# --- canonical values -------------------------------------------------------

def norm_angle(degrees: float) -> float:
    """Fold an angle into (-180, 180], the range KiCad's Properties panel shows."""
    a = math.fmod(degrees, 360.0)
    if a <= -180.0:
        a += 360.0
    elif a > 180.0:
        a -= 360.0
    a = round(a, 6)
    return 180.0 if a == -180.0 else a + 0.0  # + 0.0 turns -0.0 into 0.0


def fmt_number(value: float, decimals: int) -> str:
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def fmt(vtype: str, value: Any) -> str:
    if value is None:
        return ""
    if vtype == LENGTH:
        return fmt_number(value / 1e6, 6) + " mm"
    if vtype == ANGLE:
        return fmt_number(value, 3) + "°"
    if vtype == BOOL:
        return "Yes" if value else "No"
    if vtype == NUMBER:
        return fmt_number(value, 6) if isinstance(value, float) else str(value)
    return str(value).replace("\n", "⏎")


_NUMBER = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-zA-Z°%]*)\s*$")
_TRUE = {"yes", "true", "1", "on", "y"}
_FALSE = {"no", "false", "0", "off", "n"}


def parse_value(vtype: str, text: str) -> Tuple[bool, Any]:
    """Parse a typed value. Returns (True, value), or (False, None) when the
    text is not a plain value of that type and must be read as a pattern."""
    if vtype in (LENGTH, ANGLE, NUMBER):
        m = _NUMBER.match(text)
        if not m:
            return False, None
        number, unit = float(m.group(1)), m.group(2).lower()
        if vtype == LENGTH:
            if unit not in ("", "mm"):
                return False, None
            return True, int(round(number * 1e6))
        if vtype == ANGLE:
            if unit not in ("", "°", "deg"):
                return False, None
            return True, norm_angle(number)
        return (True, number) if unit in ("", "%") else (False, None)
    if vtype == BOOL:
        low = text.strip().lower()
        if low in _TRUE:
            return True, True
        if low in _FALSE:
            return True, False
        return False, None
    return False, None


def wildcard(pattern: str) -> "re.Pattern[str]":
    """Altium's wildcards: `*` any run, `?` one character, the rest literal.

    Not fnmatch: a net called D[0] must match the pattern D[0] literally.
    Case-insensitive, and the pattern must cover the whole value.
    """
    parts = []
    for ch in pattern:
        if ch == "*":
            parts.append(".*")
        elif ch == "?":
            parts.append(".")
        else:
            parts.append(re.escape(ch))
    return re.compile("".join(parts) + r"\Z", re.IGNORECASE | re.DOTALL)


# --- criteria ---------------------------------------------------------------

@dataclass
class Criterion:
    """One row of the grid.

    `template_values` are the values of the template objects. `pattern` is
    what the user typed into the Value column, or None while they have not.
    """
    key: str
    mode: str = ANY
    template_values: Tuple[Any, ...] = ()
    pattern: Optional[str] = None

    @property
    def attr(self) -> Attr:
        return attr_for(self.key)

    def display_value(self) -> str:
        if self.pattern is not None:
            return self.pattern
        distinct = list(dict.fromkeys(self.template_values))
        if len(distinct) == 1:
            return fmt(self.attr.vtype, distinct[0])
        return f"<{len(distinct)} values>"

    def _equals(self, value: Any) -> bool:
        vtype = self.attr.vtype
        if self.pattern is None:
            return value in self.template_values
        ok, typed = parse_value(vtype, self.pattern)
        if ok:
            if vtype == ANGLE:
                return abs(norm_angle(value - typed)) < 1e-4
            if vtype == NUMBER:
                return math.isclose(value, typed, rel_tol=1e-9, abs_tol=1e-9)
            return value == typed
        return bool(wildcard(self.pattern).match(fmt(vtype, value)))

    def test(self, obj: Obj) -> bool:
        if self.mode == ANY:
            return True
        if self.key not in obj.values:
            return False
        same = self._equals(obj.values[self.key])
        return same if self.mode == SAME else not same


def criteria_from_templates(templates: Sequence[Obj]) -> List[Criterion]:
    """The grid for these template objects, in the first template's order.

    Rows come from every template, so a footprint and a pad together show the
    union of their attributes."""
    keys: Dict[str, None] = {}
    for obj in templates:
        for key in obj.values:
            keys.setdefault(key, None)
    rows = []
    for key in keys:
        values = tuple(o.values[key] for o in templates if key in o.values)
        mode = SAME if key in DEFAULT_SAME else ANY
        rows.append(Criterion(key, mode, values))
    order = {g: i for i, g in enumerate(GROUPS)}
    rows.sort(key=lambda c: order.get(c.attr.group, len(order)))  # stable
    return rows


def find_matches(objects: Iterable[Obj], criteria: Sequence[Criterion]) -> List[Obj]:
    active = [c for c in criteria if c.mode != ANY]
    return [o for o in objects if all(c.test(o) for c in active)]


def summarize(objects: Sequence[Obj]) -> str:
    """'132 objects: Pad 120, Via 12' — for the status line."""
    if not objects:
        return "No matching objects"
    counts = Counter(o.kind for o in objects)
    parts = ", ".join(f"{k} {n}" for k, n in counts.most_common())
    noun = "object" if len(objects) == 1 else "objects"
    return f"{len(objects)} {noun}: {parts}"
