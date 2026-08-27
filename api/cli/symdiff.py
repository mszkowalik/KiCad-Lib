#!/usr/bin/env python3
"""Which symbols in a .kicad_sym library ACTUALLY changed.

KiCad's symbol editor rewrites the whole library file on every save. Editing
one symbol in `7Sigma_Base.kicad_sym` changed the text of all 197 entries: it
added `(show_name no)` 1284 times and `(do_not_autoplace no)` 1274 times,
re-sorted the pins of 21 symbols and moved custom properties ahead of the
`ki_*` ones. A text diff of that file says "everything changed" and is useless
for deciding what to push.

So this compares the CANONICAL form of each entry — the same comparison
`services/pcm_plugin/kicad_canon.py` makes for the sync and push plugins,
which hit this wall from the other side. Two spellings of one drawing compare
equal; a moved pin, a changed type or a redrawn body does not.

    python cli/symdiff.py OLD.kicad_sym NEW.kicad_sym
    python cli/symdiff.py OLD.kicad_sym NEW.kicad_sym --extract out/

`--extract` writes one single-symbol library per changed entry, ready to hand
to `propose_symbol_edit`. Push only what this prints: the server now refuses a
no-op publish, but a push of 197 entries still means 197 round trips to find
out.

Exit status is 1 when anything changed, so it works in a hook.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.pcm_plugin.kicad_canon import canon_hash

_ENTRY = re.compile(r'^\t\(symbol "(.*)"$')


def split_library(path: pathlib.Path) -> tuple[list[str], dict[str, str]]:
    """(header lines, {entry name: whole single-symbol library text}).

    Deliberately a line scan rather than a parse-and-reserialise: the text is
    what gets pushed, and it must keep the author's formatting byte for byte.
    Same reasoning as `normalize_symbol_text` in geometry_proposals.
    """
    lines = path.read_text(encoding="utf-8").split("\n")
    first = next((i for i, ln in enumerate(lines) if _ENTRY.match(ln)), None)
    if first is None:
        raise SystemExit(f"{path}: no (symbol ...) entries found — is this a .kicad_sym library?")
    head = lines[:first]
    out: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = _ENTRY.match(lines[i])
        if m:
            end = next((k for k in range(i + 1, len(lines)) if lines[k] == "\t)"), None)
            if end is None:
                raise SystemExit(f"{path}: entry {m.group(1)!r} is not closed")
            out[m.group(1)] = "\n".join(head + lines[i:end + 1] + [")", ""])
            i = end
        i += 1
    return head, out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old", type=pathlib.Path, help="baseline library")
    ap.add_argument("new", type=pathlib.Path, help="library to compare")
    ap.add_argument("--extract", type=pathlib.Path, metavar="DIR",
                    help="write one single-symbol library per changed entry")
    args = ap.parse_args()

    _, old = split_library(args.old)
    _, new = split_library(args.new)

    # Hash once per entry. canon_hash falls back to the raw text on a parse
    # failure, so a malformed entry compares with itself instead of reading as
    # changed by everyone.
    changed = sorted(n for n in set(old) & set(new) if canon_hash(old[n]) != canon_hash(new[n]))
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    same = len(set(old) & set(new)) - len(changed)

    print(f"{args.old.name} -> {args.new.name}")
    print(f"  {same} unchanged (formatting differences ignored)")
    for label, names in (("changed", changed), ("added", added), ("removed", removed)):
        if names:
            print(f"  {len(names)} {label}:")
            for n in names:
                print(f"      {n}")
    if not (changed or added or removed):
        print("  nothing to push")
        return 0

    if args.extract:
        args.extract.mkdir(parents=True, exist_ok=True)
        for n in changed + added:
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", n)
            (args.extract / f"{safe}.kicad_sym").write_text(new[n], encoding="utf-8")
        print(f"\n  wrote {len(changed) + len(added)} file(s) to {args.extract}/")
        if removed:
            print("  (removed entries are reported only — deleting a symbol is a "
                  "platform decision, not a file one)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
