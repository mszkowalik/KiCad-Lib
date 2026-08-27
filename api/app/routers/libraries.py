"""Symbol & footprint templates — list (edit-UI picker + Templates browser),
per-template detail, and pixel-exact KiCad previews."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.geometry_proposals import (
    derive_footprint_name,
    derive_symbol_name,
    is_placeholder_name,
    normalize_footprint_text,
    normalize_symbol_text,
    propose_footprint_version,
    propose_symbol_version,
    set_footprint_header,
    set_symbol_entry_name,
)
from ..services.mirror import write_manifest
from ..services.publish import set_footprint_package_name
from ..services.render import render_svg
from .util import audit

router = APIRouter(prefix="/api", tags=["libraries"])


def _current(parent) -> object | None:
    """The parent's live version object, or None if unpublished."""
    return next((v for v in parent.versions if v.id == parent.current_version_id), None)


def _comment_counts(db: Session, target_type: str) -> dict[int, int]:
    rows = (
        db.query(M.Comment.target_id, func.count(M.Comment.id))
        .filter(M.Comment.target_type == target_type)
        .group_by(M.Comment.target_id)
        .all()
    )
    return {tid: n for tid, n in rows}


def _used_by(db: Session, parent, ver_attr: str) -> list[dict]:
    """Components whose CURRENT version pins one of this template's versions."""
    ver_ids = [v.id for v in parent.versions]
    if not ver_ids:
        return []
    col = getattr(M.ComponentVersion, ver_attr)
    rows = (
        db.query(M.Component.id, M.Component.name)
        .join(M.ComponentVersion, M.ComponentVersion.id == M.Component.current_version_id)
        .filter(col.in_(ver_ids))
        .order_by(M.Component.name)
        .all()
    )
    return [{"id": cid, "name": name} for cid, name in rows]


# ---------------------------------------------------------------- list
@router.get("/symbols")
def list_symbols(db: Session = Depends(get_db)):
    symbols = (
        db.query(M.Symbol).options(selectinload(M.Symbol.versions)).order_by(M.Symbol.name).all()
    )
    counts = _comment_counts(db, "symbol")
    out = []
    for s in symbols:
        cur = _current(s)
        out.append({
            "id": s.id,
            "name": s.name,
            "version_no": cur.version_no if cur else None,
            # the preview URL's cache key — see _preview()
            "version_id": cur.id if cur else None,
            "pin_count": (cur.parsed or {}).get("pin_count") if cur else None,
            "comment_count": counts.get(s.id, 0),
        })
    return out


@router.get("/footprints")
def list_footprints(db: Session = Depends(get_db)):
    footprints = (
        db.query(M.Footprint).options(selectinload(M.Footprint.versions)).order_by(M.Footprint.name).all()
    )
    counts = _comment_counts(db, "footprint")
    out = []
    for f in footprints:
        cur = _current(f)
        out.append({
            "id": f.id,
            "name": f.name,
            "version_no": cur.version_no if cur else None,
            # the preview URL's cache key — see _preview()
            "version_id": cur.id if cur else None,
            "pad_count": (cur.parsed or {}).get("pad_count") if cur else None,
            "comment_count": counts.get(f.id, 0),
        })
    return out


# ---------------------------------------------------------------- detail
@router.get("/symbols/{sym_id}")
def get_symbol(sym_id: int, db: Session = Depends(get_db)):
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    cur = _current(s)
    return {
        "id": s.id,
        "name": s.name,
        "kind": "symbol",
        "version_no": cur.version_no if cur else None,
            # the preview URL's cache key — see _preview()
            "version_id": cur.id if cur else None,
        "created_at": cur.created_at.isoformat() if cur else None,
        "created_by": cur.created_by if cur else None,
        "comment": cur.comment if cur else None,
        "parsed": (cur.parsed or {}) if cur else {},
        "source_text": cur.source_text if cur else None,
        "used_by": _used_by(db, s, "symbol_version_id"),
    }


@router.get("/footprints/{fp_id}")
def get_footprint(fp_id: int, db: Session = Depends(get_db)):
    f = db.get(M.Footprint, fp_id)
    if f is None:
        raise HTTPException(404, "footprint not found")
    cur = _current(f)
    return {
        "id": f.id,
        "name": f.name,
        "display_name": f.display_name or "",
        "kind": "footprint",
        "version_no": cur.version_no if cur else None,
            # the preview URL's cache key — see _preview()
            "version_id": cur.id if cur else None,
        "created_at": cur.created_at.isoformat() if cur else None,
        "created_by": cur.created_by if cur else None,
        "comment": cur.comment if cur else None,
        "parsed": (cur.parsed or {}) if cur else {},
        "source_text": cur.source_text if cur else None,
        "models": (cur.models or []) if cur else [],
        "used_by": _used_by(db, f, "footprint_version_id"),
    }


# ------------------------------------------------------- paste-box proposals
class GeometryProposal(BaseModel):
    """A pasted `.kicad_mod` / `.kicad_sym` body plus its review comment."""

    source_text: str
    comment: str = ""
    #: creation only — required when the payload carries no usable name of its
    #: own, which is every straight clipboard paste
    name: str = ""
    #: True = "small change, no re-verification needed": carries verifications
    #: and production sign-offs across the changed drawing (recheck waiver)
    minor_change: bool | None = None
    #: True = publish even when the payload is the same drawing as the live
    #: version. The default no-op is what stops a KiCad re-save writing a
    #: version for every entry in the library; force it only to re-run the
    #: machine validation on unchanged geometry.
    force: bool = False


@router.post("/footprints/{fp_id}/propose")
def propose_footprint(fp_id: int, body: GeometryProposal, db: Session = Depends(get_db)):
    """Publish a footprint version from pasted editor text (auto-publish).

    The name comes from the row, never from the request, so the paste box can
    never rename a footprint by accident. Everything else — clipboard
    normalisation, header/model validation, the draft row and the audit entry —
    is `geometry_proposals`, the same code path the agent tool uses."""
    f = db.get(M.Footprint, fp_id)
    if f is None:
        raise HTTPException(404, "footprint not found")
    res = propose_footprint_version(db, f.name, body.source_text, body.comment, actor="user",
                                    minor_change=body.minor_change, force=body.force)
    if "error" in res:
        raise HTTPException(400, detail=res)
    return res


@router.post("/symbols/{sym_id}/propose")
def propose_symbol(sym_id: int, body: GeometryProposal, db: Session = Depends(get_db)):
    """Publish a base-symbol version from pasted editor text (see above)."""
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    res = propose_symbol_version(db, s.name, body.source_text, body.comment, actor="user",
                                 minor_change=body.minor_change, force=body.force)
    if "error" in res:
        raise HTTPException(400, detail=res)
    return res


def _propose_new(kind: str, body: GeometryProposal, db: Session):
    """Create a brand-new symbol/footprint from pasted text.

    The name is READ OUT of the payload — a footprint header has to match the
    row name anyway, so a separate name field could only ever disagree with it.
    An existing name is refused here rather than silently becoming an edit: the
    agent tool's "new name = create, known name = edit" overload is fine for a
    tool call that states the name, but on a form labelled *new* it would file a
    version against a template the user never opened.
    """
    is_fp = kind == "footprint"
    derive = derive_footprint_name if is_fp else derive_symbol_name
    propose = propose_footprint_version if is_fp else propose_symbol_version

    # A typed name wins: a clipboard payload is named after KiCad's clipboard
    # pseudo-library, so `derive` deliberately returns None for it and the form
    # asks instead. Otherwise the name comes from the pasted text.
    name = body.name.strip() or derive(body.source_text or "")
    if not name:
        raise HTTPException(400, detail={
            "error": f"this text carries no usable {kind} name — KiCad names a clipboard copy "
                     f"after its own clipboard library. Type the {kind} name to file it.",
            "needs_name": True})
    model = M.Footprint if is_fp else M.Symbol
    if db.query(model).filter_by(name=name).first() is not None:
        raise HTTPException(400, detail={
            "error": f"{kind} {name!r} already exists — open it and use Propose an edit, "
                     "which files a new version against it",
            "existing_name": name})
    res = propose(db, name, body.source_text, body.comment, actor="user")
    if "error" in res:
        raise HTTPException(400, detail=res)
    return res


@router.post("/footprints/propose")
def propose_new_footprint(body: GeometryProposal, db: Session = Depends(get_db)):
    """File a DRAFT for a footprint that does not exist yet (see `_propose_new`)."""
    return _propose_new("footprint", body, db)


@router.post("/symbols/propose")
def propose_new_symbol(body: GeometryProposal, db: Session = Depends(get_db)):
    """File a DRAFT for a base symbol that does not exist yet (see `_propose_new`)."""
    return _propose_new("symbol", body, db)


class GeometrySource(BaseModel):
    """Unsaved geometry to render — the paste box's look-before-you-file."""

    source_text: str
    name: str = ""


def _render_source(kind: str, body: GeometrySource):
    """Render arbitrary (unsaved) source so the paste box can preview it.

    Reuses `render_svg`, which is content-addressed, so re-previewing the same
    text is free. Normalise first: the point is to show what WOULD be filed,
    and filing normalises. Nothing is written — this touches no table."""
    is_fp = kind == "footprint"
    text = (normalize_footprint_text if is_fp else normalize_symbol_text)(body.source_text or "")
    if not text.strip():
        raise HTTPException(400, detail={"error": "nothing to preview"})
    # Rendering only needs a LABEL, and kicad-cli looks the item up BY that
    # label — so the name handed to it and the name inside the text must agree.
    # A clipboard payload is called `clipboard:<uuid>`, whose colon reads as a
    # library separator and makes the symbol lookup fail, so rewrite both to a
    # safe placeholder rather than refuse to draw the thing.
    name = body.name.strip() or (
        derive_footprint_name(text, allow_placeholder=True) if is_fp
        else derive_symbol_name(text, allow_placeholder=True))
    if not name:
        raise HTTPException(400, detail={
            "error": f"cannot read a {kind} name from this text — so it cannot be rendered"})
    if is_placeholder_name(name) or ":" in name:
        name = "preview"
    text = set_footprint_header(text, name) if is_fp else set_symbol_entry_name(text, name)
    try:
        svg = render_svg(kind, name, text)
    except Exception as e:  # noqa: BLE001 — surface render failures to the UI
        raise HTTPException(502, detail={"error": f"render failed: {e}"}) from e
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "no-cache"})


@router.post("/footprints/preview.svg")
def preview_footprint_source(body: GeometrySource):
    return _render_source("footprint", body)


@router.post("/symbols/preview.svg")
def preview_symbol_source(body: GeometrySource):
    return _render_source("symbol", body)


class FootprintMeta(BaseModel):
    """Unversioned footprint metadata (see the note on M.Footprint)."""

    display_name: str


@router.patch("/footprints/{fp_id}")
def set_footprint_display_name(fp_id: int, body: FootprintMeta, db: Session = Depends(get_db)):
    """Set the short package name that `{Footprint_Name}` templates resolve to.

    The Templates-browser door onto the same write the `set_footprint_package_name`
    agent tool uses; the shared body lives in `services/publish.py`."""
    f = db.get(M.Footprint, fp_id)
    if f is None:
        raise HTTPException(404, "footprint not found")
    return set_footprint_package_name(db, settings, f, body.display_name)


@router.delete("/footprints/{fp_id}")
def delete_footprint(fp_id: int, db: Session = Depends(get_db)):
    """Retire a footprint and all its versions, plus its file in the mirror.

    **Refuses if ANY component version references it** — including historical
    versions, not just current ones. A footprint version is pinned by
    `ComponentVersion.footprint_version_id`, so deleting one that an old version
    points at would silently orphan that version's geometry and make the
    component's history unreproducible.

    Unlike a component or geometry edit there is no draft/approve path here and
    no version to roll back to, so the audit row carries the full source text:
    that plus the pre-delete export is the only way back.
    """
    f = (
        db.query(M.Footprint)
        .options(selectinload(M.Footprint.versions))
        .filter_by(id=fp_id)
        .first()
    )
    if f is None:
        raise HTTPException(404, "footprint not found")

    version_ids = [v.id for v in f.versions]
    refs = (
        db.query(M.ComponentVersion)
        .filter(M.ComponentVersion.footprint_version_id.in_(version_ids))
        .count()
        if version_ids
        else 0
    )
    if refs:
        raise HTTPException(
            409,
            f"footprint {f.name!r} is referenced by {refs} component version(s) — "
            "repoint them first, then delete",
        )

    cur = _current(f)
    name, n_versions = f.name, len(f.versions)
    source = cur.source_text if cur is not None else ""
    f.current_version_id = None
    db.flush()
    for v in list(f.versions):
        db.delete(v)
    db.delete(f)
    audit(db, "footprint.delete", "footprint", fp_id,
          {"name": name, "versions_removed": n_versions, "source_text": source})
    db.commit()

    removed = False
    path = settings.mirror_dir / "Footprints" / "7Sigma.pretty" / f"{name}.kicad_mod"
    if path.exists():
        path.unlink()
        removed = True
    return {"deleted": fp_id, "name": name, "versions_removed": n_versions,
            "mirror_file_removed": removed, "manifest_files": write_manifest(settings)}


# ---------------------------------------------------------------- preview
def _preview(kind: str, parent, db: Session, v: int | None = None) -> Response:
    """The current version, rendered.

    ``v`` is a CACHE KEY, not a selector: it never changes what is rendered.
    The URL used to be `/api/footprints/28/preview.svg` for every version of
    footprint 28, so nothing ever told a browser — or an `<img>` already in the
    DOM — that the drawing had moved. Pushing a new land pattern left the old
    picture on screen until a hard reload, which reads as "the upload did not
    work" (reported 2026-08-24 on D_SOD-323, whose pads went 0.6x0.45 ->
    0.7x0.7). Callers pass the live version id; a new version is a new URL, so
    staleness is impossible and the response can then be cached hard — these
    are kicad-cli renders, the most expensive GET in the app.

    A stale `v` (an older id) still renders the CURRENT drawing. That is
    deliberate: this endpoint means "what does this template look like now",
    and a caller holding an old id is out of date about the version, not
    entitled to an old picture. `GET /api/{kind}/{id}/versions/...` is where
    history lives.
    """
    cur = _current(parent)
    if cur is None:
        raise HTTPException(404, "no published version to preview")
    try:
        svg = render_svg(kind, parent.name, cur.source_text)
    except Exception as e:  # noqa: BLE001 — surface render failures to the UI
        raise HTTPException(502, f"render failed: {e}") from e
    # Immutable ONLY when the caller keyed the URL to the version it wanted and
    # that is the version we rendered. Otherwise the URL is version-agnostic
    # and must never be held.
    fresh = v is not None and v == cur.id
    cache = ("public, max-age=31536000, immutable" if fresh else "no-cache")
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": cache,
                             "X-Version-Id": str(cur.id)})


@router.get("/symbols/{sym_id}/preview.svg")
def symbol_preview(sym_id: int, v: int | None = None, db: Session = Depends(get_db)):
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    return _preview("symbol", s, db, v)


@router.get("/footprints/{fp_id}/preview.svg")
def footprint_preview(fp_id: int, v: int | None = None, db: Session = Depends(get_db)):
    f = db.get(M.Footprint, fp_id)
    if f is None:
        raise HTTPException(404, "footprint not found")
    return _preview("footprint", f, db, v)


# ------------------------------------------------- a NAMED version, rendered
def _version_preview(kind: str, parent, version_no: int, db: Session) -> Response:
    """What this template looked like at version N.

    The sibling above is deliberately not this: there `v` is a cache key and
    the CURRENT drawing is always what comes back. Here the version number is
    a genuine SELECTOR, which is what the change feed's before/after panes
    need — "what did this look like before the edit" has no other answer.

    Version rows are immutable, so unlike `_preview` this can always promise
    `immutable`: the bytes for a given (template, version) can never change.
    """
    model = M.SymbolVersion if kind == "symbol" else M.FootprintVersion
    owner_col = model.symbol_id if kind == "symbol" else model.footprint_id
    ver = (db.query(model)
           .filter(owner_col == parent.id, model.version_no == version_no)
           .first())
    if ver is None:
        raise HTTPException(404, f"{kind} has no version {version_no}")
    try:
        svg = render_svg(kind, parent.name, ver.source_text)
    except Exception as e:  # noqa: BLE001 — surface render failures to the UI
        raise HTTPException(502, f"render failed: {e}") from e
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=31536000, immutable",
                             "X-Version-Id": str(ver.id)})


# The 3D board view of a footprint, on its own. `components` has had one since
# the component page grew a 2D/3D switch, but it hangs off a COMPONENT version
# and a template page has no component — so the footprint page could only ever
# show the flat render. Same renderer, same GLB, addressed by the drawing
# itself.
def _footprint_glb(fp: M.Footprint, ver: M.FootprintVersion, immutable: bool) -> Response:
    try:
        data = render_svg("footprint3d", fp.name, ver.source_text)
    except Exception as e:  # noqa: BLE001 — surface render failures to the UI
        raise HTTPException(502, f"render failed: {e}") from e
    cache = ("public, max-age=31536000, immutable" if immutable else "max-age=300")
    return Response(content=data, media_type="model/gltf-binary",
                    headers={"Cache-Control": cache})


@router.get("/footprints/{fp_id}/preview.glb")
def footprint_glb(fp_id: int, db: Session = Depends(get_db)):
    f = db.get(M.Footprint, fp_id)
    if f is None:
        raise HTTPException(404, "footprint not found")
    cur = _current(f)
    if cur is None:
        raise HTTPException(404, "no published version to preview")
    return _footprint_glb(f, cur, immutable=False)


@router.get("/footprints/{fp_id}/versions/{version_no}/preview.glb")
def footprint_version_glb(fp_id: int, version_no: int, db: Session = Depends(get_db)):
    f = db.get(M.Footprint, fp_id)
    if f is None:
        raise HTTPException(404, "footprint not found")
    ver = (db.query(M.FootprintVersion)
           .filter(M.FootprintVersion.footprint_id == fp_id,
                   M.FootprintVersion.version_no == version_no)
           .first())
    if ver is None:
        raise HTTPException(404, f"footprint has no version {version_no}")
    return _footprint_glb(f, ver, immutable=True)


@router.get("/symbols/{sym_id}/versions/{version_no}/preview.svg")
def symbol_version_preview(sym_id: int, version_no: int, db: Session = Depends(get_db)):
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    return _version_preview("symbol", s, version_no, db)


@router.get("/footprints/{fp_id}/versions/{version_no}/preview.svg")
def footprint_version_preview(fp_id: int, version_no: int, db: Session = Depends(get_db)):
    f = db.get(M.Footprint, fp_id)
    if f is None:
        raise HTTPException(404, "footprint not found")
    return _version_preview("footprint", f, version_no, db)
