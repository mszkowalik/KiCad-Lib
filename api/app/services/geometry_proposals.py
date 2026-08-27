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

import re

from sqlalchemy.orm import Session

from .. import models as M
from . import material

# KiCad names a copied item after the pseudo-library it invents for the
# clipboard: `(footprint "clipboard:11d1f418-7567-4c54-…")`. That is an
# artifact of the copy, not a name anybody chose, so it is never stored and
# never offered as the name of a new template.
PLACEHOLDER_NAME_RE = re.compile(
    r"^(?:clipboard:|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$)", re.I
)
_QUOTED = r'"(?:[^"\\]|\\.)*"'
_FP_HEADER_RE = re.compile(r"^\(\s*footprint\s+(" + _QUOTED + r"|[^\s()]+)")
_SYM_ENTRY_RE = re.compile(r'\(\s*symbol\s+"((?:[^"\\]|\\.)*)"')


def is_placeholder_name(name: str | None) -> bool:
    """True for a name KiCad invented for the clipboard, not one a person chose."""
    return bool(name) and bool(PLACEHOLDER_NAME_RE.match(name or ""))


def set_footprint_header(text: str, name: str) -> str:
    """Rewrite a footprint's header name.

    The header is a label; the authoritative name is the row being edited (or
    the one the user typed when creating). Rewriting rather than refusing is
    what lets a straight clipboard paste work at all.
    """
    m = _FP_HEADER_RE.match(text.lstrip())
    if not m:
        return text
    lead = len(text) - len(text.lstrip())
    esc = name.replace("\\", "\\\\").replace('"', '\\"')
    return text[:lead + m.start(1)] + f'"{esc}"' + text[lead + m.end(1):]


def set_symbol_entry_name(text: str, name: str) -> str:
    """Rename a `.kicad_sym` library's first symbol AND its unit entries.

    Units are named `<entry>_<unit>_<style>`, so renaming only the parent would
    orphan every unit and the symbol would render empty.
    """
    m = _SYM_ENTRY_RE.search(text)
    if not m:
        return text
    old = m.group(1)
    if old == name:
        return text
    esc = name.replace("\\", "\\\\").replace('"', '\\"')
    pattern = re.compile(r'(\(\s*symbol\s+")' + re.escape(old) + r'(_[^"]*)?(")')
    return pattern.sub(lambda mm: mm.group(1) + esc + (mm.group(2) or "") + mm.group(3), text)


# --------------------------------------------------------------------------
# footprints

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


def derive_footprint_name(source_text: str, allow_placeholder: bool = False) -> str | None:
    """The name in a pasted footprint's header, or None if there is no header.

    Creation reads the name out of the payload instead of asking for it: the
    header has to match anyway, so a second field could only ever disagree. A
    clipboard placeholder is NOT a usable name, so it reads as None and the
    form asks — except for rendering, which only needs a label and passes
    `allow_placeholder`.
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
    header = _norm(node[1]) or None
    return header if allow_placeholder else (None if is_placeholder_name(header) else header)


def derive_symbol_name(source_text: str, allow_placeholder: bool = False) -> str | None:
    """The entry name of the first symbol in a pasted `.kicad_sym` payload.

    Placeholder handling matches `derive_footprint_name`."""
    from .generator import load_symbol_lib_from_text

    try:
        lib = load_symbol_lib_from_text(normalize_symbol_text(source_text))
    except Exception:
        return None
    tops = [s.entryName for s in lib.symbols if s.entryName and "_" not in s.entryName]
    entry = next(iter(tops or [s.entryName for s in lib.symbols if s.entryName]), None)
    return entry if allow_placeholder else (None if is_placeholder_name(entry) else entry)


# --------------------------------------------------------------------------
# "the same drawing, spelled differently" is NOT a new version


def _unchanged(kind: str, parent, source_text: str) -> dict | None:
    """The live version's answer when `source_text` is the same drawing.

    KiCad rewrites the WHOLE library file it saves, in whatever spelling that
    release prefers. Opening `7Sigma_Base.kicad_sym` in KiCad 10 and saving
    added `(show_name no)` 1284 times and `(do_not_autoplace no)` 1274 times,
    re-sorted the pins of 21 symbols and reordered properties — across 197
    symbols, of which 183 had not been touched.

    Nothing downstream treats that as free. Every call here bumps
    `version_no`, `_publish_geometry` repoints every component onto the new
    row, and a repoint carries the verification only when the material
    fingerprint matches. So pushing a re-saved library once would have written
    197 versions, published a component version for each of ~420 components,
    and buried the real edit among them.

    `kicad_canon` already answers exactly this question for the sync and push
    plugins, which hit the same wall from the other side — it drops
    default-valued tokens and uuids, normalises numbers and sorts the children
    whose order carries no meaning. Reuse it rather than growing a second
    dialect: a guard that disagrees with the plugin about what "edited" means
    is worse than no guard.

    `force=True` on the caller skips this. It exists because re-publishing
    identical source was a usable escape hatch: `machine_check_on_publish` is
    the ONLY caller of the validator, so republishing was the one way to
    re-run it after a checklist gained a machine item (see the note in
    api/CLAUDE.md about checklist v2 un-answering all 418 components). Keep
    the no-op the default and the force explicit.

    Returns the no-op payload, or None when this really is a new drawing.
    """
    from .pcm_plugin.kicad_canon import canon_hash

    cur = next((v for v in parent.versions if v.id == parent.current_version_id), None)
    if cur is None or not cur.source_text:
        return None
    if canon_hash(source_text) != canon_hash(cur.source_text):
        return None
    return {
        "ok": True, "unchanged": True, kind: parent.name,
        "version_no": cur.version_no, "proposal_id": cur.id,
        f"is_new_{kind}": False,
        "status": "unchanged — same drawing, no new version created",
        "detail": "The payload differs from the live version only in formatting "
                  "(KiCad default tokens, uuids, number spelling or node order).",
        "warnings": [],
    }


# --------------------------------------------------------------------------
# footprints


def propose_footprint_version(
    db: Session, name: str, source_text: str, comment: str, actor: str = "jaravis",
    publish: bool = True, minor_change: bool | None = None, force: bool = False,
) -> dict:
    """Create — and by default PUBLISH — a `FootprintVersion`.

    Auto-publish (user design 2026-08-23): the version goes live at once with
    a machine validation record; review happens on the review axis.
    ``minor_change=True`` waives the re-verification (``recheck_required=False``
    — carries sign-offs and review records across the changed drawing, with
    the actor's name on the waiver). ``publish=False`` keeps the old
    draft-gated behaviour. Returns the result dict, or one carrying an
    ``error`` key — the caller decides how to surface it."""
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
    header_note = None
    if header != name:
        # The header is a label; `name` is authoritative (the row being edited,
        # or what the user typed). Rewrite rather than refuse — a straight
        # clipboard paste always carries KiCad's invented "clipboard:<uuid>",
        # so refusing on mismatch would reject the primary way text arrives.
        source_text = set_footprint_header(source_text, name)
        if not is_placeholder_name(header):
            # a real, different name is worth saying out loud
            header_note = f"header said {header!r}; filed as {name!r}"
        parsed = footprint_parsed(source_text)
    bad_models = [m for m in parsed.get("models") or [] if not m.startswith(MODEL_PREFIX)]
    if bad_models:
        # the `error` string carries its own context: it is what a browser shows
        return {"error": f"3D model paths must start with {MODEL_PREFIX} — offending: "
                         + ", ".join(bad_models),
                "offending": bad_models}

    warnings: list[str] = [header_note] if header_note else []
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
        noop = None if force else _unchanged("footprint", fp, source_text)
        if noop is not None:
            return noop
        cur = next((v for v in fp.versions if v.id == fp.current_version_id), None)
        old_pads = (cur.parsed or {}).get("pad_count") if cur else None
    pads = parsed.get("pad_count")
    if old_pads and pads is not None and pads < old_pads:
        warnings.append(f"pad count dropped from {old_pads} to {pads}")

    new_no = max((v.version_no for v in fp.versions), default=0) + 1
    fv = M.FootprintVersion(footprint_id=fp.id, version_no=new_no, source_text=source_text,
                            parsed=parsed, models=parsed.get("models"), status="draft",
                            created_by=actor, comment=comment or None,
                            # What a production sign-off compares against. Stamped
                            # at creation so the approval dialog can say whether
                            # anything reaching the board changed.
                            material_sha=material.material_sha("footprint", source_text))
    db.add(fv)
    db.flush()
    db.add(M.AuditLog(actor=actor, action="proposal.create", entity_type="footprint_version",
                      entity_id=str(fv.id), details={"footprint": name, "new": is_new}))
    if not publish:
        db.commit()
        return {
            "ok": True, "proposal_id": fv.id, "footprint": name, "version_no": new_no,
            "is_new_footprint": is_new, "pad_count": pads, "previous_pad_count": old_pads,
            "warnings": warnings,
            "status": "draft — awaiting user approval in the Proposals view",
        }
    return _publish_geometry(db, "footprint", fp, fv, actor, minor_change, comment, {
        "ok": True, "proposal_id": fv.id, "footprint": name, "version_no": new_no,
        "is_new_footprint": is_new, "pad_count": pads, "previous_pad_count": old_pads,
        "warnings": warnings,
    })


# --------------------------------------------------------------------------
# symbols


def propose_symbol_version(
    db: Session, name: str, source_text: str, comment: str, actor: str = "jaravis",
    publish: bool = True, minor_change: bool | None = None, force: bool = False,
) -> dict:
    """Create — and by default PUBLISH — a `SymbolVersion`. Same contract as
    the footprint side (see `propose_footprint_version` on auto-publish and
    `minor_change`)."""
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
    name_note = None
    if name not in entry_names:
        # Same reasoning as the footprint header: rename rather than refuse, so
        # a clipboard payload (named after KiCad's clipboard pseudo-library)
        # lands on the row the user opened. Only safe for a SINGLE-entry
        # library — with several, we cannot know which one they meant.
        tops = [n for n in entry_names if "_" not in n] or entry_names
        if len(tops) != 1:
            return {"error": f"source_text contains no symbol named {name!r} — it holds: "
                             + (", ".join(entry_names) or "nothing")
                             + ". Paste one symbol at a time.",
                    "symbols_found": entry_names}
        source_text = set_symbol_entry_name(source_text, name)
        if not is_placeholder_name(tops[0]):
            name_note = f"pasted symbol was {tops[0]!r}; filed as {name!r}"
        try:
            lib = load_symbol_lib_from_text(source_text)
        except Exception as e:
            return {"error": f"renaming the pasted symbol to {name!r} broke it: {e}"}
        if name not in [s.entryName for s in lib.symbols]:
            return {"error": f"could not rename the pasted symbol to {name!r}"}
    try:
        parsed = symbol_parsed(source_text)
    except Exception as e:
        return {"error": f"symbol metadata extraction failed: {e}"}

    warnings: list[str] = [name_note] if name_note else []
    sym = db.query(M.Symbol).filter_by(name=name).first()
    is_new = sym is None
    old_pins = None
    if is_new:
        sym = M.Symbol(name=name)  # current_version_id stays None until approved
        db.add(sym)
        db.flush()
    else:
        noop = None if force else _unchanged("symbol", sym, source_text)
        if noop is not None:
            return noop
        cur = next((v for v in sym.versions if v.id == sym.current_version_id), None)
        old_pins = (cur.parsed or {}).get("pin_count") if cur else None
    pins = parsed.get("pin_count")
    if old_pins and pins is not None and pins < old_pins:
        warnings.append(f"pin count dropped from {old_pins} to {pins}")

    new_no = max((v.version_no for v in sym.versions), default=0) + 1
    sv = M.SymbolVersion(symbol_id=sym.id, version_no=new_no, source_text=source_text,
                         parsed=parsed, status="draft", created_by=actor,
                         comment=comment or None,
                         # See the footprint twin — the sign-off comparison basis.
                         material_sha=material.material_sha("symbol", source_text))
    db.add(sv)
    db.flush()
    db.add(M.AuditLog(actor=actor, action="proposal.create", entity_type="symbol_version",
                      entity_id=str(sv.id), details={"symbol": name, "new": is_new}))
    if not publish:
        db.commit()
        return {
            "ok": True, "proposal_id": sv.id, "symbol": name, "version_no": new_no,
            "is_new_symbol": is_new, "pin_count": pins, "previous_pin_count": old_pins,
            "warnings": warnings,
            "status": "draft — awaiting user approval in the Proposals view",
        }
    return _publish_geometry(db, "symbol", sym, sv, actor, minor_change, comment, {
        "ok": True, "proposal_id": sv.id, "symbol": name, "version_no": new_no,
        "is_new_symbol": is_new, "pin_count": pins, "previous_pin_count": old_pins,
        "warnings": warnings,
    })


def _publish_geometry(db: Session, kind: str, parent, version, actor: str,
                      minor_change: bool | None, comment: str, payload: dict) -> dict:
    """The shared publish tail: publish flow, repoint, commit, mirror refresh."""
    from ..config import settings
    from .publish import publish_geometry_version, refresh_mirror_for_geometry
    from .repoint import repoint_for
    from .review import version_state

    recheck = None if minor_change is None else (not minor_change)
    publish_geometry_version(db, kind, parent, version, actor,
                             recheck_required=recheck, recheck_note=comment)
    repointed = repoint_for(db, kind, parent) if settings.auto_repoint_components else None
    db.commit()
    mirror = refresh_mirror_for_geometry(db, settings, kind, parent)
    state = version_state(db, kind, parent.id, version.id)
    return {
        **payload,
        "status": "published",
        "review_state": state["state"],
        "machine_check": {"failed": state["failed"], "skipped": state["skipped"],
                          "answered": state["answered"], "total": state["total"]},
        "repointed": repointed,
        "mirror_warnings": mirror.get("warnings", []),
    }
