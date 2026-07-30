"""Draft proposals for symbol and footprint GEOMETRY — the one implementation.

Two callers share this module and must never diverge:

* ``services/jaravis.py`` — the ``propose_symbol_edit`` / ``propose_footprint_edit``
  agent tools (Jaravis chat and the MCP server).
* ``routers/libraries.py`` — ``POST /api/{symbols,footprints}/{id}/propose``,
  the web UI's paste box.

Both produce an ordinary DRAFT version that the user approves in the Proposals
view, so the visual before/after review is identical whichever door the text
came through.

**Pasted text is normalised first.** KiCad's editors put an s-expression on the
clipboard, but not necessarily the exact file body: a footprint may arrive
wrapped in an outer node, and a symbol may arrive as a bare ``(symbol ...)``
with no surrounding library. ``normalize_footprint_text`` /
``normalize_symbol_text`` reduce both shapes to what the parsers expect, so the
user can paste straight from the editor without hand-editing the text.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models as M

SYMBOL_LIB_HEADER = (
    '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "kicad_symbol_editor")\n'
    '\t(generator_version "10.0")\n'
)
MODEL_PREFIX = "${SEVENSIGMA_DIR}/3DModels/"


# --------------------------------------------------------------------------
# clipboard normalisation


def slice_node(text: str, tag: str) -> str | None:
    """Return the source slice of the first ``(tag ...)`` expression in `text`.

    A hand-rolled scan rather than a parse-and-serialise round trip: it keeps
    the author's own formatting and comments byte-for-byte, which matters
    because the result is stored as the version's source. Quoted strings and
    backslash escapes are honoured so a ``")"`` inside a property value cannot
    close the expression early.
    """
    needle = "(" + tag
    n = len(text)
    i = 0
    while True:
        i = text.find(needle, i)
        if i < 0:
            return None
        after = i + len(needle)
        # reject a longer token that merely starts the same way ("(footprints")
        if after < n and (text[after].isalnum() or text[after] in "_-"):
            i = after
            continue
        depth = 0
        k = i
        in_str = False
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
                    return text[i:k + 1]
            k += 1
        return None  # unbalanced from here on — let the parser report it


def normalize_footprint_text(text: str) -> str:
    """Reduce a pasted payload to a bare ``(footprint ...)`` body.

    A ``.kicad_mod`` file already is one, so this is a no-op for file text.
    """
    body = slice_node(text.strip(), "footprint")
    return body + "\n" if body else text


def normalize_symbol_text(text: str) -> str:
    """Ensure a pasted payload is a ``.kicad_sym`` LIBRARY, not a bare symbol."""
    t = text.strip()
    lib = slice_node(t, "kicad_symbol_lib")
    if lib:
        return lib + "\n"
    sym = slice_node(t, "symbol")
    if sym:
        return SYMBOL_LIB_HEADER + sym + "\n)\n"
    return text


# --------------------------------------------------------------------------
# name derivation — a paste already carries its own name


def derive_footprint_name(source_text: str) -> str | None:
    """The name in a pasted footprint's header, or None if there is no header.

    Creation reads the name out of the payload instead of asking for it: the
    header has to match anyway, so a second field could only ever disagree.
    """
    from ..util.sexpr import _norm, parse_sexpr

    body = slice_node(source_text.strip(), "footprint")
    if not body:
        return None
    try:
        node = parse_sexpr(body)
    except Exception:
        return None
    if isinstance(node, list) and node and isinstance(node[0], list):
        node = node[0]  # the footprint node IS the root
    if not (isinstance(node, list) and len(node) > 1 and _norm(node[0]) == "footprint"):
        return None
    return _norm(node[1]) or None


def derive_symbol_name(source_text: str) -> str | None:
    """The entry name of the first symbol in a pasted `.kicad_sym` payload."""
    from .generator import load_symbol_lib_from_text

    try:
        lib = load_symbol_lib_from_text(normalize_symbol_text(source_text))
    except Exception:
        return None
    return next((s.entryName for s in lib.symbols if s.entryName), None)


# --------------------------------------------------------------------------
# footprints


def propose_footprint_version(
    db: Session, name: str, source_text: str, comment: str, actor: str = "jaravis"
) -> dict:
    """Create a draft `FootprintVersion`. Returns the result dict, or one
    carrying an ``error`` key — the caller decides how to surface it."""
    from ..util.sexpr import _norm, find_node, parse_sexpr
    from .parse_cache import footprint_parsed

    name = name.strip()
    if not name or not source_text.strip():
        return {"error": "name and source_text must not be empty"}
    source_text = normalize_footprint_text(source_text)
    if slice_node(source_text, "footprint") is None:
        return {"error": "this is not a whole footprint — the text contains no (footprint ...) "
                         "block. A canvas selection is not enough: copy the footprint itself, "
                         "or paste the .kicad_mod file text."}
    try:
        parsed = footprint_parsed(source_text)
        tree = parse_sexpr(source_text)
    except Exception as e:
        return {"error": f"source_text does not parse as a .kicad_mod footprint: {e}"}
    # the footprint node may BE the tree root rather than a child (same
    # fallback as parse_cache.footprint_parsed)
    fp_node = find_node(tree, "footprint") or (tree[0] if tree and isinstance(tree[0], list) else tree)
    valid = isinstance(fp_node, list) and len(fp_node) > 1 and _norm(fp_node[0]) == "footprint"
    header = _norm(fp_node[1]) if valid else ""
    if header != name:
        return {"error": f"footprint header is {header!r} but must be exactly {name!r} "
                         "(no easyeda2kicad:/7Sigma: prefix inside the file)",
                "header": header}
    bad_models = [m for m in parsed.get("models") or [] if not m.startswith(MODEL_PREFIX)]
    if bad_models:
        # the `error` string carries its own context: it is what a browser shows
        return {"error": f"3D model paths must start with {MODEL_PREFIX} — offending: "
                         + ", ".join(bad_models),
                "offending": bad_models}

    warnings: list[str] = []
    for m in parsed.get("models") or []:
        rel = m[len(MODEL_PREFIX):]
        if db.query(M.Model3D).filter_by(rel_path=rel).first() is None:
            warnings.append(f"referenced 3D model not in the library: {rel}")
    # A partial paste is legal s-expression but loses the fields KiCad needs.
    # Warn rather than refuse: dropping a pad can be a deliberate correction.
    if '"Reference"' not in source_text and "fp_text reference" not in source_text:
        warnings.append("no Reference field — a canvas-only copy loses it")
    if '"Value"' not in source_text and "fp_text value" not in source_text:
        warnings.append("no Value field — a canvas-only copy loses it")

    fp = db.query(M.Footprint).filter_by(name=name).first()
    is_new = fp is None
    old_pads = None
    if is_new:
        fp = M.Footprint(name=name)  # current_version_id stays None until approved
        db.add(fp)
        db.flush()
    else:
        cur = next((v for v in fp.versions if v.id == fp.current_version_id), None)
        old_pads = (cur.parsed or {}).get("pad_count") if cur else None
    pads = parsed.get("pad_count")
    if old_pads and pads is not None and pads < old_pads:
        warnings.append(f"pad count dropped from {old_pads} to {pads}")

    new_no = max((v.version_no for v in fp.versions), default=0) + 1
    fv = M.FootprintVersion(footprint_id=fp.id, version_no=new_no, source_text=source_text,
                            parsed=parsed, models=parsed.get("models"), status="draft",
                            created_by=actor, comment=comment or None)
    db.add(fv)
    db.flush()
    db.add(M.AuditLog(actor=actor, action="proposal.create", entity_type="footprint_version",
                      entity_id=str(fv.id), details={"footprint": name, "new": is_new}))
    db.commit()
    return {
        "ok": True, "proposal_id": fv.id, "footprint": name, "version_no": new_no,
        "is_new_footprint": is_new, "pad_count": pads, "previous_pad_count": old_pads,
        "warnings": warnings,
        "status": "draft — awaiting user approval in the Proposals view",
    }


# --------------------------------------------------------------------------
# symbols


def propose_symbol_version(
    db: Session, name: str, source_text: str, comment: str, actor: str = "jaravis"
) -> dict:
    """Create a draft `SymbolVersion`. Same contract as the footprint side."""
    from .generator import load_symbol_lib_from_text
    from .parse_cache import symbol_parsed

    name = name.strip()
    if not name or not source_text.strip():
        return {"error": "name and source_text must not be empty"}
    source_text = normalize_symbol_text(source_text)
    if slice_node(source_text, "symbol") is None:
        return {"error": "this is not a whole symbol — the text contains no (symbol ...) block. "
                         "A canvas selection is not enough: copy the symbol itself, or paste "
                         "the .kicad_sym file text."}
    try:
        lib = load_symbol_lib_from_text(source_text)
    except Exception as e:
        return {"error": f"source_text does not parse as a .kicad_sym library: {e}"}
    entry_names = [s.entryName for s in lib.symbols]
    if name not in entry_names:
        return {"error": f"source_text contains no symbol named {name!r} — it holds: "
                         + (", ".join(entry_names) or "nothing"),
                "symbols_found": entry_names}
    try:
        parsed = symbol_parsed(source_text)
    except Exception as e:
        return {"error": f"symbol metadata extraction failed: {e}"}

    warnings: list[str] = []
    sym = db.query(M.Symbol).filter_by(name=name).first()
    is_new = sym is None
    old_pins = None
    if is_new:
        sym = M.Symbol(name=name)  # current_version_id stays None until approved
        db.add(sym)
        db.flush()
    else:
        cur = next((v for v in sym.versions if v.id == sym.current_version_id), None)
        old_pins = (cur.parsed or {}).get("pin_count") if cur else None
    pins = parsed.get("pin_count")
    if old_pins and pins is not None and pins < old_pins:
        warnings.append(f"pin count dropped from {old_pins} to {pins}")

    new_no = max((v.version_no for v in sym.versions), default=0) + 1
    sv = M.SymbolVersion(symbol_id=sym.id, version_no=new_no, source_text=source_text,
                         parsed=parsed, status="draft", created_by=actor,
                         comment=comment or None)
    db.add(sv)
    db.flush()
    db.add(M.AuditLog(actor=actor, action="proposal.create", entity_type="symbol_version",
                      entity_id=str(sv.id), details={"symbol": name, "new": is_new}))
    db.commit()
    return {
        "ok": True, "proposal_id": sv.id, "symbol": name, "version_no": new_no,
        "is_new_symbol": is_new, "pin_count": pins, "previous_pin_count": old_pins,
        "warnings": warnings,
        "status": "draft — awaiting user approval in the Proposals view",
    }
