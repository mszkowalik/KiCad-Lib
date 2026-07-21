"""S-expression helpers.

KiCad 10 writes several new symbol tokens on save (`(in_pos_files yes)`,
`(duplicate_pin_numbers_are_jumpers no)`, ...); kiutils (both upstream and the
Wittmann-MEE fork) raises `Unrecognized property key` on them — and
SymbolLib.from_file silently DROPS the affected symbol. Instead of patching
the installed package (lost on reinstall — see the root CLAUDE.md gotcha), we
strip the tokens from source text before any kiutils parse. KiCad treats the
absent fields as defaults and re-adds them on save.

If a new KiCad token surfaces later, add it to _KICAD10_ONLY_TOKENS — the
symptom is a "No symbol found in source" warning during mirror rebuild.
"""
from __future__ import annotations

import re

_KICAD10_ONLY_TOKENS = (
    "in_pos_files",
    "duplicate_pin_numbers_are_jumpers",
)
_TOKENS_RE = re.compile(r"\(\s*(?:" + "|".join(_KICAD10_ONLY_TOKENS) + r")\s+[^)]*\)\s*")


def sanitize_symbol_text(text: str) -> str:
    """Remove KiCad-10-only tokens that kiutils cannot parse."""
    return _TOKENS_RE.sub("", text)


def parse_sexpr(text: str):
    """Parse s-expression text into nested Python lists (kiutils' own parser)."""
    from kiutils.utils import sexpr

    return sexpr.parse_sexp(text)


def _norm(atom) -> str:
    """Normalize a parsed atom to a plain string (strip quotes defensively)."""
    s = str(atom)
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s


def iter_nodes(node, tag: str):
    """Yield direct children of `node` that are lists starting with `tag`."""
    for child in node:
        if isinstance(child, list) and child and _norm(child[0]) == tag:
            yield child


def find_node(node, tag: str):
    for child in iter_nodes(node, tag):
        return child
    return None


def walk_nodes(node, tag: str):
    """Yield all descendant lists (depth-first) starting with `tag`."""
    if isinstance(node, list):
        if node and _norm(node[0]) == tag:
            yield node
        for child in node:
            yield from walk_nodes(child, tag)


def node_value(node, tag: str, default=None):
    """Return the single value of a child node like (tag value)."""
    child = find_node(node, tag)
    if child is not None and len(child) > 1:
        return _norm(child[1])
    return default
