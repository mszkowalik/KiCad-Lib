"""The office organizers: which box holds what (decision 0104). Rules in
`services/organizers.py` and docs/reference/organizers.md."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import companies as company_svc
from ..services import fx, journal, organizers as svc
from .util import acting_name, audit, col_cap

router = APIRouter(prefix="/api/organizers", tags=["organizers"])

_NOTE = col_cap(M.OrganizerMove, "note")
_MPN = col_cap(M.MaterialItem, "mpn")
_LCSC = col_cap(M.MaterialItem, "lcsc")
_ORG = col_cap(M.OrganizerBox, "organizer")
_CODE = col_cap(M.OrganizerBox, "code")


class PartIn(BaseModel):
    component_id: int | None = None
    mpn: str = Field(default="", max_length=_MPN)
    lcsc: str = Field(default="", max_length=_LCSC)


class BoxesIn(BaseModel):
    organizer: str = Field(max_length=_ORG)
    codes: list[str]


class BoxPatch(BaseModel):
    code: str | None = Field(default=None, max_length=_CODE)
    note: str | None = Field(default=None, max_length=col_cap(M.OrganizerBox, "note"))


class RenameIn(BaseModel):
    name: str = Field(max_length=_ORG)
    new_name: str = Field(max_length=_ORG)


class CountIn(PartIn):
    company_id: int
    qty: float = Field(ge=0)
    at: str = Field(default="", max_length=20)
    note: str = Field(default="", max_length=_NOTE)


class TakeIn(PartIn):
    qty: float = Field(gt=0)
    purpose: str = Field(max_length=12)
    company_id: int | None = None
    run_id: int | None = None
    at: str = Field(default="", max_length=20)
    note: str = Field(default="", max_length=_NOTE - 60)


class MoveIn(PartIn):
    qty: float = Field(gt=0)
    to_box_id: int
    company_id: int | None = None
    at: str = Field(default="", max_length=20)
    note: str = Field(default="", max_length=_NOTE - 60)


class ResearchIn(PartIn):
    qty: float = Field(gt=0)
    company_id: int
    purpose: str = Field(default="research", max_length=12)
    at: str = Field(default="", max_length=20)
    note: str = Field(default="", max_length=_NOTE - 60)


class ImportRow(PartIn):
    organizer: str = Field(max_length=_ORG)
    code: str = Field(max_length=_CODE)
    company_id: int | None = None
    qty: float = Field(default=0, ge=0)
    note: str = Field(default="", max_length=_NOTE - 200)


class ImportIn(BaseModel):
    rows: list[ImportRow]
    at: str = Field(max_length=20)
    source_ref: str = Field(default="", max_length=100)
    dry_run: bool = True


def _box(db: Session, box_id: int) -> M.OrganizerBox:
    box = db.get(M.OrganizerBox, box_id)
    if box is None:
        raise HTTPException(404, "no such box")
    return box


def _allowed(db: Session, request: Request | None) -> list[int]:
    """The companies this caller may touch. A box is shared; its pieces are not."""
    return company_svc.visible_ids(db, getattr(request.state, "user", None) if request is not None else None)


def _scope(db: Session, request: Request | None) -> list[int] | None:
    scope = company_svc.scope_ids(db, request)
    return scope if company_svc.narrows(db, scope) else None


@router.get("", openapi_extra={"x-agent-tool": "list_organizers"})
def overview(request: Request = None, db: Session = Depends(get_db)):
    """Every organizer box and what it holds, with the totals."""
    return svc.overview(db, _scope(db, request))


@router.get("/moves", openapi_extra={"x-agent-tool": "list_organizer_moves"})
def moves(box_id: int | None = None, item_id: int | None = None, purpose: str = "", limit: int = 200,
          request: Request = None, db: Session = Depends(get_db)):
    """A box's or a part's history. `purpose=research` is what R&D has used, and
    what it cost: `value_usd` is the draw's price, which is 0 for a piece with
    no purchase behind it."""
    return svc.history(db, box_id=box_id, item_id=item_id, purpose=purpose, company_ids=_scope(db, request),
                       limit=min(max(limit, 1), 1000))


@router.get("/research", openapi_extra={"x-agent-tool": "list_organizer_research"})
def research(limit: int = 500, request: Request = None, db: Session = Depends(get_db)):
    """What R&D has used, and what it cost: 0 for a piece no purchase covers.
    Stored in USD. It belongs to no batch, so a screen shows it in PLN at today's
    rate (decision 0103)."""
    return {"rows": svc.research_list(db, _scope(db, request), min(max(limit, 1), 2000)),
            "pln_per_usd": fx.pln_per_usd(db)}


@router.post("/research")
def research_use(body: ResearchIn, request: Request = None, db: Session = Depends(get_db)):
    """Pieces in no box that were used for R&D or for a project the platform does
    not track, or that are lost (`purpose=loss`). A take from a box is `.../take`."""
    company_svc.get(db, body.company_id)
    if body.company_id not in _allowed(db, request):
        raise HTTPException(404, "no such company")
    actor = acting_name()
    lost = body.purpose == svc.LOSS
    with journal.batch(db, kind="organizer.research", source_ref=(body.mpn or body.lcsc)[:100], actor=actor) as h:
        it = svc.part_item(db, body.component_id, body.mpn, body.lcsc)
        if lost:
            res = svc.write_off(db, it, body.qty, body.company_id, at=body.at, note=body.note, actor=actor)
        else:
            res = svc.research_use(db, it, body.qty, body.company_id, at=body.at, note=body.note, actor=actor,
                                   purpose=body.purpose)
    audit(db, "organizer.research", "adjustment" if lost else "draw", res["adjustment_id"] if lost else res["draw_id"],
          {"item": it.key, "company_id": body.company_id, **res, "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {**res, "batch_id": h["batch_id"]}


@router.post("/boxes")
def add_boxes(body: BoxesIn, db: Session = Depends(get_db)):
    """A new organizer is its boxes. A code that exists already is left alone."""
    actor = acting_name()
    with journal.batch(db, kind="organizer.boxes", source_ref=body.organizer, actor=actor) as h:
        made = svc.make_boxes(db, body.organizer, body.codes, actor)
    audit(db, "organizer.boxes.add", "organizer_box", None,
          {"organizer": body.organizer, "codes": [b.code for b in made], "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {"made": [{"id": b.id, "code": b.code} for b in made], "batch_id": h["batch_id"]}


@router.post("/rename")
def rename_organizer(body: RenameIn, db: Session = Depends(get_db)):
    """A name is a label on its boxes, so a rename moves every box at once."""
    new = body.new_name.strip()
    if not new:
        raise HTTPException(422, "name the organizer")
    boxes = db.query(M.OrganizerBox).filter_by(organizer=body.name).all()
    if not boxes:
        raise HTTPException(404, "no such organizer")
    if db.query(M.OrganizerBox.id).filter_by(organizer=new).first():
        raise HTTPException(409, f"an organizer named {new} exists already")
    actor = acting_name()
    with journal.batch(db, kind="organizer.rename", source_ref=new, actor=actor) as h:
        for b in boxes:
            b.organizer = new
        db.flush()
    audit(db, "organizer.rename", "organizer_box", None,
          {"from": body.name, "to": new, "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {"boxes": len(boxes), "batch_id": h["batch_id"]}


@router.patch("/boxes/{box_id}")
def patch_box(box_id: int, body: BoxPatch, db: Session = Depends(get_db)):
    box = _box(db, box_id)
    actor = acting_name()
    with journal.batch(db, kind="organizer.box", source_ref=box.code, actor=actor):
        if body.code is not None:
            code = body.code.strip()
            if not code:
                raise HTTPException(422, "a box needs a code")
            other = db.query(M.OrganizerBox).filter_by(organizer=box.organizer, code=code).first()
            if other is not None and other.id != box.id:
                raise HTTPException(409, f"{box.organizer} has a box {code} already")
            box.code = code
        if body.note is not None:
            box.note = body.note.strip()
        db.flush()
    audit(db, "organizer.box.edit", "organizer_box", box.id, body.model_dump(exclude_unset=True), actor=actor)
    db.commit()
    return {"id": box.id, "code": box.code, "note": box.note}


@router.delete("/boxes/{box_id}")
def delete_box(box_id: int, db: Session = Depends(get_db)):
    """Only a box that never held anything: a move is history. A journal batch, so
    the delete can be undone and the batch that made the box stays reversible."""
    box = _box(db, box_id)
    if db.query(M.OrganizerMove.id).filter_by(box_id=box.id).first():
        raise HTTPException(409, f"box {box.code} has a history: it stays")
    actor = acting_name()
    with journal.batch(db, kind="organizer.box.delete", source_ref=box.code, actor=actor):
        audit(db, "organizer.box.delete", "organizer_box", box.id,
              {"organizer": box.organizer, "code": box.code}, actor=actor)
        db.delete(box)
        db.flush()
    db.commit()
    return {"deleted": box_id}


@router.post("/boxes/{box_id}/count", openapi_extra={"x-agent-tool": "organizer_count"})
def count(box_id: int, body: CountIn, request: Request = None, db: Session = Depends(get_db)):
    """What the box holds, read off the box. Also how a part goes into a box."""
    box = _box(db, box_id)
    company_svc.get(db, body.company_id)
    if body.company_id not in _allowed(db, request):
        raise HTTPException(404, "no such company")
    actor = acting_name()
    with journal.batch(db, kind="organizer.count", source_ref=box.code, actor=actor) as h:
        it = svc.part_item(db, body.component_id, body.mpn, body.lcsc)
        res = svc.set_count(db, box, it, body.company_id, body.qty, at=body.at, note=body.note, actor=actor)
    audit(db, "organizer.count", "organizer_box", box.id,
          {"item": it.key, "company_id": body.company_id, **res, "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {**res, "batch_id": h["batch_id"]}


@router.post("/boxes/{box_id}/take", openapi_extra={"x-agent-tool": "organizer_take"})
def take(box_id: int, body: TakeIn, request: Request = None, db: Session = Depends(get_db)):
    """Take pieces from a box. It is a draw: for R&D it is charged to no batch, and
    for a batch it is charged to that batch. The answer names the write batch."""
    box = _box(db, box_id)
    actor = acting_name()
    with journal.batch(db, kind="organizer.take", source_ref=box.code, actor=actor) as h:
        it = svc.part_item(db, body.component_id, body.mpn, body.lcsc)
        res = svc.take(db, box, it, body.qty, body.purpose, company_id=body.company_id, run_id=body.run_id,
                       at=body.at, note=body.note, actor=actor, allowed=_allowed(db, request))
    audit(db, "organizer.take", "organizer_box", box.id,
          {"item": it.key, "purpose": body.purpose, "run_id": body.run_id, **res, "batch_id": h["batch_id"]},
          actor=actor)
    db.commit()
    return {**res, "batch_id": h["batch_id"]}


@router.post("/boxes/{box_id}/move", openapi_extra={"x-agent-tool": "organizer_move"})
def move(box_id: int, body: MoveIn, request: Request = None, db: Session = Depends(get_db)):
    """Move pieces to another box. No money moves: the pieces stay in stock."""
    box = _box(db, box_id)
    to = _box(db, body.to_box_id)
    actor = acting_name()
    with journal.batch(db, kind="organizer.move", source_ref=f"{box.code}>{to.code}", actor=actor) as h:
        it = svc.part_item(db, body.component_id, body.mpn, body.lcsc)
        res = svc.move(db, box, to, it, body.qty, company_id=body.company_id, at=body.at, note=body.note,
                       actor=actor, allowed=_allowed(db, request))
    audit(db, "organizer.move", "organizer_box", box.id,
          {"item": it.key, "to": to.code, **res, "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {**res, "batch_id": h["batch_id"]}


@router.post("/boxes/{box_id}/clear")
def clear(box_id: int, body: PartIn, db: Session = Depends(get_db)):
    """Take an empty part's row off a box."""
    box = _box(db, box_id)
    actor = acting_name()
    with journal.batch(db, kind="organizer.clear", source_ref=box.code, actor=actor) as h:
        it = svc.part_item(db, body.component_id, body.mpn, body.lcsc)
        svc.clear(db, box, it, actor)
    db.commit()
    return {"batch_id": h["batch_id"]}


@router.post("/import")
def run_import(body: ImportIn, request: Request = None, db: Session = Depends(get_db)):
    """Load boxes and their contents from a list, dry run by default. One
    reversible write: the Write log undoes all of it."""
    allowed = _allowed(db, request)
    rows = [r.model_dump() for r in body.rows]
    for r in rows:
        named = r["component_id"] or r["mpn"].strip() or r["lcsc"].strip()
        if named and r["company_id"] not in allowed:
            raise HTTPException(422, f"box {r['code']}: name a company you belong to")
    actor = acting_name()
    if body.dry_run:
        res = svc.import_rows(db, rows, at=body.at, actor=actor)
        db.rollback()
        return {**res, "dry_run": True}
    with journal.batch(db, kind="organizer.import", source_ref=body.source_ref or "import", actor=actor) as h:
        res = svc.import_rows(db, rows, at=body.at, actor=actor)
    audit(db, "organizer.import", "organizer_box", None,
          {**res["totals"], "source": body.source_ref, "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {**res, "dry_run": False, "batch_id": h["batch_id"]}
