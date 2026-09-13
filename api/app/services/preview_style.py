"""How a footprint preview looks: pad numbers, layer visibility, hole colour.

The target is **KiCad's own footprint editor**, because that is the picture
every user already knows. `kicad-cli fp export svg` is a PLOTTER, not the
editor, and differs from it in three ways that this module undoes.

1. **It prints no pad numbers.** They are a canvas display option, not a
   plotted item, so a preview showed anonymous copper and reading a pinout
   meant counting pins from the pin-1 mark. The one switch kicad-cli offers,
   `--sketch-pads-on-fab-layers`, is not it — it redraws every pad as a
   fab-layer outline as well, which buries the land pattern under a second
   copy of itself. So `with_pad_labels` writes one `fp_text` per numbered pad
   into a COPY of the source and lets KiCad draw it.
2. **It plots every layer, mask and paste included.** Two translucent washes
   over the copper turn KiCad's red pads into mauve ones. `PREVIEW_LAYERS` is
   the editor's own default visibility, passed to `--layers`.
3. **It plots holes last, in the paper colour, over everything.** A pad number
   at the centre of a through-hole pad came out as two crescents of a digit
   (`USB_B_SOFNG_USB-B01`). `style_preview_svg` re-stacks the finished SVG —
   no layer can be plotted after the holes, the order is KiCad's, not a
   setting — and paints the holes in the editor's plated-hole cyan.

Nothing here is stored. The text exists for the length of one render, and
`services/render.py` hashes the annotated source, so a preview cached before a
rule changed is not served in its place.

**The colours below are the theme's, and the pair has to stay a pair.**
`settings.footprint_theme` names `themes/Skyline-7S.json`; `_LABEL_COLOUR` is
its `board.eco1_user` and `_HOLE_COLOUR` its `board.plated_hole`, because the
finished SVG carries colours, not layer names — it is how a group is found
again. Change one of them in the theme and change it here. The canvas the
browser paints behind the drawing is the same fact once more: it is
`board.background`, as `--kicad-board-canvas` in `web/src/styles.css`.

Four sizing rules, each forced by a footprint in this library:

- **The long axis wins.** A 0.25 x 0.875 mm pin pad fits "12" only along its
  length, so the text turns 90 degrees when the pad is taller than it is wide,
  exactly as the editor does it. The pad's own rotation is added on top.
- **A custom pad is measured by its primitives.** `(size ...)` on a custom pad
  is the anchor, which is routinely 0.14 mm on a corner pad whose real land is
  ten times that (`QFN-28_4x4mm_P0.5mm` pads 1, 7, 8, 14 ...). Sizing from the
  anchor produced invisible labels.
- **One label per number per land.** `..._ThermalVias` footprints stack via
  pads inside the exposed pad and give every one of them the pad's own number.
  A pad whose centre sits inside a larger pad of the SAME number is left to
  that pad.
- **Two numbers on one land are spread, not stacked.** A USB-C receptacle
  gives A1 and B12 the same pad centre.
"""
from __future__ import annotations

import math
import re

from ..util.sexpr import _norm, find_node, iter_nodes, parse_sexpr

# What the footprint editor shows by default. Mask, paste and adhesive are the
# ones left out on purpose: they are translucent washes over the copper, and
# with them the pads read mauve instead of KiCad's red. An unknown name in the
# list is ignored by kicad-cli rather than refused, so the User.n range costs
# nothing on a footprint that uses none of it.
PREVIEW_LAYERS = ",".join([
    "F.Cu", "B.Cu",
    "F.SilkS", "B.SilkS",
    "F.Fab", "B.Fab",
    "F.CrtYd", "B.CrtYd",
    "Edge.Cuts", "Margin",
    "Dwgs.User", "Cmts.User", "Eco1.User", "Eco2.User",
    *[f"User.{n}" for n in range(1, 10)],
])

# The layer the labels are drawn on, and the colour the theme gives it — see
# the docstring: these two are one fact, and `style_preview_svg` finds the
# labels in the finished SVG by the colour.
#
# NOT rgb(255,255,255): KiCad discards a pure-white layer colour and plots the
# layer in its fallback grey (#C2C2C2) instead, which is also Dwgs.User's
# colour, so the labels both looked wrong and could not be told apart again.
# 254 is white to the eye and survives.
_LABEL_LAYER = "Eco1.User"
_LABEL_COLOUR = "#FEFEFE"
# `board.plated_hole` in the theme. kicad-cli plots a drill as a disc in the
# paper colour — white inside a pad, black where the hole has no copper — and
# the editor draws both in this cyan.
_HOLE_COLOUR = "#1AC4D2"
_PLOTTED_HOLES = ("#FFFFFF", "#000000")

# How a label is proportioned inside its pad. 0.8 of the short axis leaves a
# margin; 0.78 per character is a little wider than KiCad's stroke font
# actually advances, so a long number shrinks before it touches the pad edge
# rather than after. The cap is what keeps an exposed pad's number from
# shouting: 0.6 mm reads at any preview size, and without it a 1.7 mm thermal
# pad printed a "17" taller than the die outline.
_SHORT_AXIS_RATIO = 0.8
_CHAR_ADVANCE = 0.78
_THICKNESS_RATIO = 0.15
_MAX_SIZE_MM = 0.6
# Below this the stroke font is a smudge at any preview size, and a via-sized
# pad ends up with a hairline scribble on it. Those labels are dropped.
_MIN_SIZE_MM = 0.12
# Two pads are "the same land" when their centres agree to this, in mm.
_SAME_CENTRE_MM = 0.01


def with_pad_labels(source_text: str) -> str:
    """The .kicad_mod text plus one `fp_text user` label per numbered pad.

    Returns `source_text` unchanged when it has no labellable pad or cannot be
    parsed — a preview of a broken footprint is still worth drawing, and the
    renderer's own error is the one worth reporting.
    """
    try:
        labels = _labels(source_text)
    except Exception:  # noqa: BLE001 — a malformed source is the renderer's story to tell
        return source_text
    if not labels:
        return source_text
    cut = source_text.rstrip().rfind(")")
    if cut < 0:
        return source_text
    return source_text[:cut] + "\n".join(labels) + "\n" + source_text[cut:]


def style_preview_svg(svg: bytes) -> bytes:
    """Paint the holes the editor's colour, then lift the labels above them.

    Both steps work on top-level groups: kicad-cli writes one per plotted
    layer plus one for the holes, and each states its colour in the opening
    tag. Anything unexpected leaves the SVG exactly as it came — a plainer
    picture is not a failed render.
    """
    try:
        text = svg.decode("utf-8")
    except UnicodeDecodeError:
        return svg
    groups = _top_level_groups(text)
    if not groups or "</svg>" not in text:
        return svg

    # Holes first, so the rewrite cannot move the label spans out from under
    # the offsets collected above.
    pieces: list[str] = []
    labels: list[str] = []
    cursor = 0
    for start, stop in groups:
        block = text[start:stop]
        head = block.split(">", 1)[0]
        if f"stroke:{_LABEL_COLOUR}" in head:
            pieces.append(text[cursor:start])
            labels.append(block)
            cursor = stop
        elif _is_hole_group(head):
            pieces.append(text[cursor:start])
            for plotted in _PLOTTED_HOLES:
                block = block.replace(plotted, _HOLE_COLOUR)
            pieces.append(block)
            cursor = stop
    if not labels and cursor == 0:
        return svg
    pieces.append(text[cursor:])
    rebuilt = "".join(pieces)
    end = rebuilt.rfind("</svg>")
    return (rebuilt[:end] + "".join(labels) + rebuilt[end:]).encode("utf-8")


def _is_hole_group(head: str) -> bool:
    """A hole is FILLED and strokes nothing. The plot's outer group is black
    too but strokes black, and a label strokes its colour over `fill:none` —
    so the fill/stroke pair, not the colour alone, is what identifies one."""
    return "stroke:none" in head and any(f"fill:{c}" in head for c in _PLOTTED_HOLES)


def _top_level_groups(text: str) -> list[tuple[int, int]]:
    """(start, end) of every outermost `<g ...>...</g>`, in document order."""
    spans: list[tuple[int, int]] = []
    depth = 0
    start = 0
    for m in re.finditer(r"<g\b|</g>", text):
        if m.group(0) == "</g>":
            depth -= 1
            if depth < 0:  # not the SVG we think it is; claim nothing
                return []
            if depth == 0:
                spans.append((start, m.end()))
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return spans


class _Pad:
    __slots__ = ("angle", "height", "number", "width", "x", "y")

    def __init__(self, number: str, x: float, y: float, angle: float,
                 width: float, height: float):
        self.number = number
        self.x = x
        self.y = y
        self.angle = angle
        self.width = width
        self.height = height

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains(self, other: _Pad) -> bool:
        """`other`'s centre lies inside this pad (rotation ignored: a thermal
        via sits well inside the exposed pad either way)."""
        return (abs(other.x - self.x) <= self.width / 2
                and abs(other.y - self.y) <= self.height / 2)


def _labels(source_text: str) -> list[str]:
    tree = parse_sexpr(source_text)
    fp = find_node(tree, "footprint")
    if fp is None:
        fp = tree[0] if tree and isinstance(tree[0], list) else tree
    # Direct children only: a `(pad ...)` can appear nowhere else, and walking
    # the whole tree would also pick up whatever a generator left inside a
    # custom pad's primitives.
    pads = [p for p in (_pad(node) for node in iter_nodes(fp, "pad")) if p is not None]
    pads = _drop_covered_duplicates(pads)

    out: list[str] = []
    for group in _by_centre(pads):
        out.extend(_group_labels(group))
    return out


def _pad(node) -> _Pad | None:
    number = _norm(node[1]) if len(node) > 1 else ""
    # An NPTH mechanical hole carries `(pad "" np_thru_hole ...)`. There is
    # nothing to name, and KiCad prints nothing on it either.
    if not number:
        return None
    at = find_node(node, "at")
    if at is None or len(at) < 3:
        return None
    try:
        x, y = float(_norm(at[1])), float(_norm(at[2]))
        angle = float(_norm(at[3])) if len(at) > 3 else 0.0
    except ValueError:
        return None
    width, height = _extent(node)
    if width <= 0 or height <= 0:
        return None
    return _Pad(number, x, y, angle, width, height)


def _extent(node) -> tuple[float, float]:
    """The pad's drawn width and height in its own frame, in mm."""
    size = find_node(node, "size")
    try:
        width = float(_norm(size[1])) if size is not None and len(size) > 2 else 0.0
        height = float(_norm(size[2])) if size is not None and len(size) > 2 else 0.0
    except ValueError:
        width = height = 0.0
    primitives = find_node(node, "primitives")
    if primitives is None:
        return width, height
    # A custom pad: the anchor above is a dot, the land is in the primitives.
    # Every primitive states its geometry as coordinate pairs — (xy x y) in a
    # polygon, (start|end|center x y) elsewhere — so the bounding box of every
    # pair, widened by the stroke, measures all of them without a shape table.
    xs: list[float] = []
    ys: list[float] = []
    stroke = 0.0
    for item in _walk(primitives):
        tag = _norm(item[0]) if item and not isinstance(item[0], list) else ""
        try:
            if tag in ("xy", "start", "end", "center", "mid") and len(item) > 2:
                xs.append(float(_norm(item[1])))
                ys.append(float(_norm(item[2])))
            elif tag == "width" and len(item) > 1:
                stroke = max(stroke, float(_norm(item[1])))
        except ValueError:
            continue
    if not xs:
        return width, height
    return max(width, max(xs) - min(xs) + stroke), max(height, max(ys) - min(ys) + stroke)


def _walk(node):
    """Every list in the tree, the node itself included."""
    if isinstance(node, list):
        if node:
            yield node
        for child in node:
            yield from _walk(child)


def _drop_covered_duplicates(pads: list[_Pad]) -> list[_Pad]:
    """Thermal vias inherit the exposed pad's number — label the pad, not the
    vias. A same-numbered pad whose centre is inside a bigger one is dropped."""
    keep: list[_Pad] = []
    for pad in pads:
        covered = any(other is not pad
                      and other.number == pad.number
                      and other.area > pad.area
                      and other.contains(pad)
                      for other in pads)
        if not covered:
            keep.append(pad)
    return keep


def _by_centre(pads: list[_Pad]) -> list[list[_Pad]]:
    """Pads sharing a centre, grouped; first-seen order kept."""
    groups: dict[tuple[int, int], list[_Pad]] = {}
    order: list[tuple[int, int]] = []
    for pad in pads:
        key = (round(pad.x / _SAME_CENTRE_MM), round(pad.y / _SAME_CENTRE_MM))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(pad)
    return [groups[k] for k in order]


def _group_labels(group: list[_Pad]) -> list[str]:
    """One NUMBER, one label — however many pads share the land.

    Two cases live here. A `..._ThermalVias` exposed pad is two stacked pads
    with one number (copper and paste are split), and one number means one
    label. A USB-C receptacle gives A1 and B12 the same pad centre, and there
    centring both would write one number over the other — so distinct numbers
    are spread along the pad's long axis, each sized for its share of it.
    """
    numbers = sorted({pad.number for pad in group})
    count = len(numbers)
    biggest = max(group, key=lambda p: p.area)
    short, long = min(biggest.width, biggest.height), max(biggest.width, biggest.height)
    share = long / count
    widest = max(len(n) for n in numbers)
    size = min(short * _SHORT_AXIS_RATIO, share / (_CHAR_ADVANCE * widest), _MAX_SIZE_MM)
    if size < _MIN_SIZE_MM:
        return []
    turned = biggest.height > biggest.width
    angle = biggest.angle + (90.0 if turned else 0.0)

    out: list[str] = []
    for i, number in enumerate(numbers):
        # Along the long axis, centred as a set: one label lands on the pad
        # centre, two straddle it, and so on.
        offset = (i - (count - 1) / 2) * share
        dx, dy = (0.0, offset) if turned else (offset, 0.0)
        # KiCad rotates counter-clockwise on a y-down axis.
        rad = math.radians(biggest.angle)
        x = biggest.x + dx * math.cos(rad) + dy * math.sin(rad)
        y = biggest.y - dx * math.sin(rad) + dy * math.cos(rad)
        out.append(_text(number, x, y, angle, size))
    return out


def _text(number: str, x: float, y: float, angle: float, size: float) -> str:
    thickness = round(size * _THICKNESS_RATIO, 4)
    size = round(size, 4)
    return (
        f'\t(fp_text user "{number}"\n'
        f"\t\t(at {round(x, 4)} {round(y, 4)} {round(angle % 360, 2)})\n"
        f'\t\t(layer "{_LABEL_LAYER}")\n'
        f"\t\t(effects\n"
        f"\t\t\t(font\n"
        f"\t\t\t\t(size {size} {size})\n"
        f"\t\t\t\t(thickness {thickness})\n"
        f"\t\t\t)\n"
        f"\t\t)\n"
        f"\t)"
    )
