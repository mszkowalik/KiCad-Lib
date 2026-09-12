"""Which unit of a symbol a render shows, and how many there are.

`kicad-cli sym export svg` plots ONE FILE PER UNIT — `NAME_unit1.svg`,
`NAME_unit2.svg`, … — and has no switch to make it do otherwise. Every preview
in the platform took `sorted(glob)[0]`, so a dual op-amp drew as a single one
and a 10-unit STM32 showed one of its ten banks with nothing on screen saying
the other nine existed.

This module answers both halves of the fix: it picks the unit that was asked
for, and it reports the COUNT so the viewer can draw its ‹ 1 / 10 › arrows.
The count travels back as the `X-Unit-Count` response header, which is why
`main.py` exposes that header to a cross-origin dev browser.

Two traps it exists to hold:

* **`sorted()` is not unit order.** It puts `_unit10` between `_unit1` and
  `_unit2`, so the tenth bank would have been "the first unit".
* **Unit letters are KiCad's, not an index.** KiCad prints `U12A`, `U12B`, so
  unit 1 is A and the viewer must say A, not 0 and not 1-of.

`render/svg_units.py` is a byte-identical copy for the render container —
edit both, or the `guard` job fails the build (docs/reference/deployment.md).
"""
from __future__ import annotations

import re
from pathlib import Path

_UNIT_SUFFIX_RE = re.compile(r"_unit(\d+)$", re.IGNORECASE)


def unit_number(path: Path) -> int:
    """`STM32_unit10.svg` -> 10. An unnumbered file sorts last."""
    m = _UNIT_SUFFIX_RE.search(path.stem)
    return int(m.group(1)) if m else 1 << 30


def unit_letter(unit: int) -> str:
    """KiCad's own unit suffix: 1 -> A, 26 -> Z, 27 -> AA (as in U12A)."""
    out = ""
    n = unit
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out or "A"


def select_unit(paths: list[Path], unit: int | None = None) -> tuple[bytes, int]:
    """One unit's SVG and the number of units the symbol has.

    `unit` is 1-based, the way KiCad numbers them, and is CLAMPED rather than
    rejected: the viewer keeps the unit it was on while it moves between
    versions of a drawing, and a symbol that lost a unit must still render
    instead of erroring out from under the reader.
    """
    ordered = sorted(paths, key=unit_number)
    if not ordered:
        raise ValueError("no SVG to select from")
    index = 0 if unit is None else max(1, min(unit, len(ordered))) - 1
    return ordered[index].read_bytes(), len(ordered)
