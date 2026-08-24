"""Canonical comparison of KiCad s-expression text — shared by sync.py and push.py.

**A byte hash cannot answer "did I edit this?"** KiCad rewrites the WHOLE file
it saves, and it writes tokens the platform's generator leaves out. Measured on
2026-08-20 against plugin 1.0.8, editing ONE symbol and pressing Ctrl+S changed
the text of all 183 entries in `7Sigma_Base.kicad_sym`:

  * every `(property …)` gained `(show_name no)` and `(do_not_autoplace no)`,
  * every symbol gained `(duplicate_pin_numbers_are_jumpers no)`, and the ones
    written without it gained `(in_pos_files yes)`,
  * `(do_not_autoplace)` became `(do_not_autoplace yes)`,
  * pins came back in a different order in 21 symbols.

Each of those means exactly what its absence meant. Push offered to propose all
183 symbols anyway, and Sync — which refuses to overwrite a file it did not
write last — froze the whole library. Footprints have the same trap from the
other side: KiCad regenerates the `(uuid …)` of every pad and graphic on save,
so an untouched footprint that is merely opened and saved reads as edited.

So both plugins compare a CANONICAL form instead: parse the text, drop the
tokens whose value is the KiCad default, drop uuids, normalise numbers, and
sort the child items of `(symbol …)` / `(footprint …)`, whose order carries no
meaning. Everything else compares verbatim — a moved pad, a renamed pin or a
changed pin type is a real edit and must stay visible.

The canonical form is a COMPARISON KEY ONLY. Nothing here is ever written to a
library file: sync writes the platform's bytes or the user's bytes, never this.
"""
from __future__ import annotations

import hashlib

# Tokens KiCad prints explicitly and the platform's writer omits. A token whose
# value equals the default here says nothing, so it drops out of the canonical
# form and the two spellings compare equal. Extend this table when a KiCad
# release starts printing another default — the symptom is "everything is
# suddenly edited" right after a KiCad upgrade.
DEFAULTS = {
    "show_name": "no",
    "do_not_autoplace": "no",
    "duplicate_pin_numbers_are_jumpers": "no",
    "exclude_from_sim": "no",
    "hide": "no",
    "in_bom": "yes",
    "on_board": "yes",
    "in_pos_files": "yes",
    "embedded_fonts": "no",
    "locked": "no",
    "unlocked": "no",
}

# Nodes whose direct children are an unordered set. KiCad sorts pins on save;
# the platform's writer keeps the authored order. Nothing else is sorted — the
# points of a polyline are a path, not a set.
UNORDERED = {"symbol", "footprint", "kicad_symbol_lib"}

# Regenerated on almost every save, so they are noise (same call as
# services/material.py makes for the material fingerprint).
VOLATILE = {"uuid", "tstamp"}


def tokenize(text: str):
    """s-expression tokens: parens, quoted strings (kept quoted), bare atoms."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c in "()":
            yield c
            i += 1
            continue
        if c == '"':
            j, buf = i + 1, ['"']
            while j < n:
                if text[j] == "\\":
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                if text[j] == '"':
                    break
                buf.append(text[j])
                j += 1
            buf.append('"')
            yield "".join(buf)
            i = j + 1
            continue
        j = i
        while j < n and not text[j].isspace() and text[j] not in '()"':
            j += 1
        yield text[i:j]
        i = j


def parse(text: str) -> list:
    """Nested lists of atoms. Raises IndexError on unbalanced text — callers
    treat any exception as "cannot canonicalise, fall back to the raw bytes"."""
    stack: list[list] = [[]]
    for tok in tokenize(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(tok)
    return stack[0][0]


def _atom(tok: str) -> str:
    """A bare atom, with numbers reduced to one spelling (0, -0.0 and 0.000 are
    the same coordinate). Quoted strings keep their quotes and never reach this."""
    if tok[:1] == '"':
        return tok
    try:
        return repr(round(float(tok), 6) + 0.0)
    except ValueError:
        return tok


def _render(node) -> str:
    if isinstance(node, str):
        return _atom(node)
    head = node[0] if node and isinstance(node[0], str) else ""
    atoms, kids = [], []
    for child in node[1:]:
        if isinstance(child, list):
            tag = child[0] if child and isinstance(child[0], str) else ""
            if tag in VOLATILE:
                continue
            if tag in DEFAULTS:
                # a bare flag `(tag)` means yes — that is KiCad's older spelling
                value = child[1] if len(child) > 1 and isinstance(child[1], str) else "yes"
                if value == DEFAULTS[tag]:
                    continue
                kids.append(f"({tag} {value})")
                continue
            kids.append(_render(child))
        else:
            atoms.append(_atom(child))
    if head in UNORDERED:
        kids.sort()
    return "(" + " ".join([head] + atoms + kids) + ")"


def canon(text: str) -> str:
    """The canonical rendering of one s-expression body."""
    return _render(parse(text))


def canon_hash(text: str) -> str:
    """sha256 of the canonical form, or of the raw text when it does not parse.

    Falling back keeps a malformed file comparable with itself, so an unparsable
    library never reads as "edited by everyone".
    """
    try:
        key = canon(text)
    except Exception:
        key = text
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def raw_hash(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def record(data: bytes | str) -> dict:
    """The state entry for content we wrote: both hashes.

    The raw hash is the fast path and the canonical hash is the one that
    survives a KiCad re-save, so a file is judged untouched if EITHER matches.
    """
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    return {"r": raw_hash(data), "c": canon_hash(text)}


def matches(rec, data: bytes | str) -> bool:
    """True when `data` is still the content `rec` was written for.

    A bare string record is the pre-1.1.0 state file, which held the raw hash
    alone — read it rather than discard it, or every installed file would look
    edited on the first run after the upgrade.
    """
    if rec is None:
        return False
    if isinstance(rec, str):
        return raw_hash(data) == rec
    if not isinstance(rec, dict):
        return False
    if rec.get("r") == raw_hash(data):
        return True
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    return bool(rec.get("c")) and canon_hash(text) == rec["c"]


def entry_spans(text: str) -> list[tuple[str, int, int]]:
    """(name, start, end) of every top-level ``(symbol "NAME" …)`` in a
    .kicad_sym library.

    A balanced scan, so a ")" inside a property value cannot end an entry early,
    and so unit sub-symbols (``NAME_1_1``) stay nested inside their parent
    instead of being mistaken for entries of their own.
    """
    out: list[tuple[str, int, int]] = []
    i, n = 0, len(text)
    needle = '(symbol "'
    while True:
        i = text.find(needle, i)
        if i < 0:
            return out
        # a top-level entry sits one tab in; anything deeper is a unit
        line_start = text.rfind("\n", 0, i) + 1
        if text[line_start:i] != "\t":
            i += len(needle)
            continue
        name_end = text.find('"', i + len(needle))
        name = text[i + len(needle):name_end]
        depth, k, in_str = 0, i, False
        while k < n:
            c = text[k]
            if in_str:
                if c == "\\":
                    k += 2
                    continue
                if c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    out.append((name, i, k + 1))
                    break
            k += 1
        i = k + 1


def split_symbols(text: str) -> list[tuple[str, str]]:
    """Top-level ``(symbol "NAME" …)`` entries of a .kicad_sym library."""
    return [(name, text[start:end]) for name, start, end in entry_spans(text)]


def merge_symbol_lib(upstream_text: str, local_text: str, keep: set) -> str:
    """The platform's library with the named local entries kept as they are.

    Every base symbol lives in ONE generated file, so a whole-file "do not
    clobber" rule makes one edited symbol freeze all 183 of them. The unit of
    protection is the entry: upstream wins everywhere except the entries the
    user actually edited, which survive untouched until they are pushed and
    approved. Entries the user drew locally (no upstream twin) are appended.
    """
    local = dict(split_symbols(local_text))
    out: list[str] = []
    pos, taken = 0, set()
    for name, start, end in entry_spans(upstream_text):
        out.append(upstream_text[pos:start])
        if name in keep and name in local:
            out.append(local[name])
            taken.add(name)
        else:
            out.append(upstream_text[start:end])
        pos = end
    tail = upstream_text[pos:]
    extra = [local[n] for n in sorted(keep) if n not in taken and n in local]
    if extra:
        close = tail.rfind(")")
        if close < 0:
            close = len(tail)
        out.append(tail[:close].rstrip("\n") + "\n")
        out.extend("\t" + e + "\n" for e in extra)
        out.append(tail[close:])
    else:
        out.append(tail)
    return "".join(out)


def drop_symbols(text: str, drop: set) -> str:
    """The library with the named entries removed.

    Sync needs this when the platform stops carrying a symbol library outright:
    the user answers per symbol, so some entries go and the rest stay, and
    deleting the whole file would take the kept ones with them. Returns the text
    unchanged when `drop` names nothing that is in it.
    """
    spans = [(s, e) for name, s, e in entry_spans(text) if name in drop]
    if not spans:
        return text
    out, pos = [], 0
    for start, end in spans:
        # take the entry's own indent and trailing newline with it, or the file
        # accumulates blank tabbed lines every time one is dropped
        line_start = text.rfind("\n", 0, start) + 1
        cut_from = line_start if not text[line_start:start].strip() else start
        cut_to = end + 1 if text[end:end + 1] == "\n" else end
        out.append(text[pos:cut_from])
        pos = cut_to
    out.append(text[pos:])
    return "".join(out)
