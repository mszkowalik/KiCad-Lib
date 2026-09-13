"""Pad numbers on the footprint preview.

KiCad's own footprint editor prints each pad's number on the pad. `kicad-cli
fp export svg` does NOT: pad numbers are a canvas display option, not a
plotted item, so every preview in this platform showed anonymous copper and a
reviewer had to count pins to find pad 1. The one switch kicad-cli offers,
`--sketch-pads-on-fab-layers`, is not it — it redraws every pad as a fab-layer
outline as well, which buries the land pattern under a second copy of itself.

So the numbers are drawn the way KiCad draws anything: as footprint text.
`with_pad_labels` returns a COPY of the source with one `fp_text user` per
numbered pad, centred on the pad and sized to fit it, and `raise_pad_labels`
lifts the plotted result above the drill holes. Nothing is stored — the text
exists for the length of one render, and `services/render.py` hashes the
annotated text, so a preview cached before this existed is not served in its
place.

Four decisions, each forced by a footprint in this library:

- **`Eco1.User`, not `F.Fab`.** The label has to be legible ON a pad, so it
  needs a colour no other layer in a footprint uses: in KiCad's default board
  theme Eco1.User is pale mint (#B4DBD2) against red copper, magenta
  courtyard, yellow silk and grey fab. A footprint that carries real
  Eco1.User geometry would mix with the labels — no library footprint does,
  and a preview-only layer beats a preview-only hack on the SVG.
- **The long axis wins.** A 0.25 x 0.875 mm pin pad fits "12" only along its
  length, so the text turns 90 degrees when the pad is taller than it is wide,
  exactly as the editor does it. The pad's own rotation is added on top.
- **A custom pad is measured by its primitives.** `(size ...)` on a custom pad
  is the anchor, which is routinely 0.14 mm on a corner pad whose real land is
  ten times that (`QFN-28_4x4mm_P0.5mm` pads 1, 7, 8, 14 ...). Sizing from the
  anchor produced invisible labels.
- **One label per number per land.** `..._ThermalVias` footprints stack nine
  via pads inside the exposed pad and give every one of them the pad's own
  number: nine copies of "17" on top of each other. A pad whose centre sits
  inside a larger pad of the SAME number is left to that pad. Two DIFFERENT
  numbers on one land is a real thing (USB-C A1/B12 share a pad centre) and
  those labels are spread along the pad instead of stacked.
"""
from __future__ import annotations

import math
import re

from ..util.sexpr import _norm, find_node, iter_nodes, parse_sexpr

# The layer the labels are plotted on, and the colour kicad-cli gives it. The
# two are ONE fact: the colour is Eco1.User in KiCad's built-in board theme,
# which is what `settings.footprint_theme = ""` selects. Point footprint
# renders at a theme of our own and this colour has to be re-read from it
# (`raise_pad_labels` finds the labels by it), or the labels stop being lifted
# above the holes.
_LABEL_LAYER = "Eco1.User"
_LABEL_COLOUR = "#B4DBD2"

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


def raise_pad_labels(svg: bytes) -> bytes:
    """Move the label groups to the end of the SVG, above the drill holes.

    kicad-cli plots holes LAST, as white discs over everything, so a label at
    the centre of a through-hole pad came out as two crescents of a digit
    (`USB_B_SOFNG_USB-B01`). No layer can be plotted after them — the order is
    KiCad's, not a setting — so the finished SVG is re-stacked instead: every
    top-level group drawn in the label colour is moved to just before
    `</svg>`, which is what the editor's own canvas shows.

    Anything unexpected leaves the SVG exactly as it came: labels under the
    holes are a worse picture, not a failed render.
    """
    try:
        text = svg.decode("utf-8")
    except UnicodeDecodeError:
        return svg
    groups = [g for g in _top_level_groups(text) if _LABEL_COLOUR in text[g[0]:g[1]].split(">", 1)[0]]
    if not groups or "</svg>" not in text:
        return svg
    moved = "".join(text[start:stop] for start, stop in groups)
    kept = []
    cursor = 0
    for start, stop in groups:
        kept.append(text[cursor:start])
        cursor = stop
    kept.append(text[cursor:])
    rebuilt = "".join(kept)
    end = rebuilt.rfind("</svg>")
    return (rebuilt[:end] + moved + rebuilt[end:]).encode("utf-8")


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
