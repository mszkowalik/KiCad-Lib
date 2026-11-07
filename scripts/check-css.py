#!/usr/bin/env python3
"""Every class in web/src/styles.css has a user in web/src, or a written reason why not.

The UI has one stylesheet (web/CLAUDE.md), and a rule with no element is worse than
no rule: people maintain it and believe it applies. The check reads the selectors
of the stylesheet and every string in web/src, and a class is used when its whole
name is a word in one of those strings. A comment does not count. It needs no
running server and no node, and it imports nothing from the app.

A name built at run time (`stk-${kind}`) has no string to find, so it goes in ALLOW
below with its reason. The check fails on a class with no user and no reason, and
on a pattern in ALLOW that matches no class in the stylesheet, so the list cannot
rot.

    python3 scripts/check-css.py        fail on anything unexplained
"""
from __future__ import annotations

import fnmatch
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHEET = ROOT / "web/src/styles.css"
WEB = ROOT / "web/src"

# Patterns, and why no string has to spell the name. `a.b` is class b on the same
# element as class a. A literal class name in the code is always better than a line
# here, so keep this short.
ALLOW = [
    ("check-ok check-err check-unknown", "CheckGrid: `check-${TONE[status]}`"),
    ("diff-added diff-changed diff-removed", "ComponentDetail: `diff-${row.status}`"),
    ("fl-*", "the flash log: `fl-${row.dir}`"),
    ("sim-trace-*", "Plots: `sim-trace-${index % 6}`"),
    ("stk-copper stk-core stk-dielectric stk-finish stk-mask stk-overlay stk-paste stk-prepreg",
     "StackupTable: `stk-${kind}`"),
    ("stk-v-*", "StackupTable: `stk-v-${severity}`"),
    ("tree-indent-*", "the invoice tree: `tree-indent-${depth}`"),
    ("v-*", "BenchStation: `bench-verdict v-${status}`"),
    ("change-kind.*", "ChangesFeed: `change-kind ${kind}`, and the kind comes from the API"),
    ("sim-part.switch", "useSimOverlay: `sim-part ${part.kind}`, and the kind comes from the API"),
    ("diff-layer.after", "GeometryDiff: `diff-layer ${cls}`"),
    ("stat-chip.acc", "StatChip: `stat-chip ${tone}`"),
    ("preview-fill.preview-board", "GeometryPreview adds it to the frame for a footprint"),
    ("u-over u-under u-select", "uPlot draws these elements itself"),
]

CSS_NOISE = re.compile(r'/\*.*?\*/|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', re.S)
CLASS = re.compile(r"\.(-?[_a-zA-Z][_a-zA-Z0-9-]*)")
COMPOUND = re.compile(r"(?:\.-?[_a-zA-Z][_a-zA-Z0-9-]*)+")
WORD = re.compile(r"-?[_a-zA-Z][_a-zA-Z0-9-]*")
ESCAPE = re.compile(r"\\.", re.S)
QUOTED = {
    '"': re.compile(r'"(?:[^"\\\n]|\\.)*"', re.S),
    "'": re.compile(r"'(?:[^'\\\n]|\\.)*'", re.S),
}
REGEX = re.compile(r"/(?![*/])(?:[^/\\\n\[]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/[a-z]*")
BEFORE_REGEX = "(,=:[!&|?{;"


def declared() -> tuple[dict[str, int], dict[str, set[str]]]:
    """Each class named in a selector, with the line of its first rule, and the
    forms it has for ALLOW: `b` and, for a selector `.a.b`, also `a.b`. An at-rule
    prelude is no selector, and the steps of a @keyframes block are not either."""
    text = CSS_NOISE.sub(lambda m: "\n" * m.group().count("\n"), SHEET.read_text(encoding="utf-8"))
    lines: dict[str, int] = {}
    forms: dict[str, set[str]] = {}
    start = i = 0
    while i < len(text):
        c = text[i]
        if c == "{":
            prelude = text[start:i]
            if prelude.lstrip().startswith(("@keyframes", "@font-face")):
                depth, i = 1, i + 1
                while depth and i < len(text):
                    depth += {"{": 1, "}": -1}.get(text[i], 0)
                    i += 1
                start = i
                continue
            if not prelude.lstrip().startswith("@"):
                line = text.count("\n", 0, start + len(prelude) - len(prelude.lstrip())) + 1
                for compound in COMPOUND.findall(re.sub(r"\[[^\]]*\]", "", prelude)):
                    names = CLASS.findall(compound)
                    for name in names:
                        lines.setdefault(name, line)
                        forms.setdefault(name, {name}).update(f"{a}.{name}" for a in names if a != name)
            start = i + 1
        elif c in ";}":
            start = i + 1
        i += 1
    return lines, forms


def strings(text: str) -> list[str]:
    """Each string in a .ts or .tsx file, and each plain part of a template. A scanner
    and not a regex, because an interpolation may hold a nested template:
    `a ${b ? `c ${d}` : "e"}`. Words in JSX text can hold a quote or two slashes, so a
    quote with no partner on its line is a plain character, and `://` opens no comment."""
    found: list[str] = []
    i, n, depths, in_template = 0, len(text), [], False
    while i < n:
        c = text[i]
        if in_template:
            start = i
            while i < n and text[i] != "`" and not text.startswith("${", i):
                i += 2 if text[i] == "\\" else 1
            found.append(text[start:i])
            in_template = False
            if text.startswith("${", i):
                depths.append(1)
                i += 2
            else:
                i += 1
        elif text.startswith("//", i) and text[i - 1:i] != ":":
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c in QUOTED:
            m = QUOTED[c].match(text, i)
            if m:
                found.append(m.group()[1:-1])
                i = m.end()
            else:
                i += 1
        elif c == "`":
            in_template = True
            i += 1
        elif c == "/":
            before = text[:i].rstrip()[-7:]
            m = REGEX.match(text, i) if before[-1:] in BEFORE_REGEX or before.endswith("return") else None
            i = m.end() if m else i + 1
        elif c in "{}" and depths:
            depths[-1] += 1 if c == "{" else -1
            if depths[-1] == 0:
                depths.pop()
                in_template = True
            i += 1
        else:
            i += 1
    return found


def used() -> set[str]:
    words: set[str] = set()
    for path in WEB.rglob("*.ts*"):
        for s in strings(path.read_text(encoding="utf-8")):
            words.update(WORD.findall(ESCAPE.sub(" ", s)))
    return words


def main() -> int:
    lines, forms = declared()
    words = used()
    patterns = [p for names, _why in ALLOW for p in names.split()]
    every_form = set().union(*forms.values())
    explained = lambda name: any(fnmatch.fnmatchcase(f, p) for f in forms[name] for p in patterns)
    dead = sorted(name for name in lines if name not in words and not explained(name))
    stale = [p for p in patterns if not fnmatch.filter(every_form, p)]
    for name in dead:
        print(f"dead: .{name} (styles.css:{lines[name]}). Remove its rules, or give the reason in ALLOW in this script.")
    for pattern in stale:
        print(f"stale: {pattern} is in ALLOW, and no class in styles.css matches it.")
    print(f"checked the classes: {len(lines)} declared, {len(dead)} with no user and no reason, "
          f"{len(stale)} stale, {len(patterns)} patterns with a reason")
    return 1 if dead or stale else 0


if __name__ == "__main__":
    sys.exit(main())
