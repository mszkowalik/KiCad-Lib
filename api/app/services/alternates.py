"""Approved alternates: a part another part may stand in for (decision 0108).

One direction: a row says `component_id` may be replaced by `alternate_id`, and
nothing about the reverse. Both are library components. A project may refuse
an approved alternate, for every position of the part or for some designators
(`ProjectAlternateBlock`); a refused alternate is not approved there.

What an approval changes, and what it does not:

* the standing substitution finding (0038 item 7) ends for a substitution whose
  fitted part is an approved alternate — `substitutions.drift`;
* a plan counts an approved alternate's stock and open purchases as the part
  — `planning._parts`;
* a purchase proposal names the alternate flagged `buy`;
* a batch draw still takes the part that was fitted (0038 item 8).

Unversioned, like a supplier link (0055): approving costs no verification.
Deleting the row is the undo; the audit row keeps who did what.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from .. import models as M


class AlternateError(ValueError):
    """A write the rules refuse; the router answers it with 409 or 422."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def refs_of(text: str | None) -> set[str]:
    return {r.strip().upper() for r in (text or "").replace(";", ",").split(",") if r.strip()}


def _blocked(blocks: list[M.ProjectAlternateBlock], alternate_id: int, refs: str | None) -> bool:
    """A block with no designators refuses every position; one with designators
    refuses only the positions it names. Without positions to compare, any
    block of the pair refuses."""
    want = refs_of(refs)
    for b in blocks:
        if b.alternate_id != alternate_id:
            continue
        if not b.refs.strip() or not want or (want & refs_of(b.refs)):
            return True
    return False


def component_by_lcsc(db: Session, lcsc: str | None) -> int | None:
    """The library component whose current version names this LCSC code. A
    fitted part the platform never stocked (C7223 on V2) is known only here."""
    code = (lcsc or "").strip()
    if not code:
        return None
    row = (db.query(M.Component.id)
           .join(M.ComponentProperty, M.ComponentProperty.component_version_id == M.Component.current_version_id)
           .filter(M.ComponentProperty.key == "LCSC Part", M.ComponentProperty.value == code).first())
    return row[0] if row else None


def approved_ids(db: Session, component_id: int | None, project_id: int | None = None,
                 refs: str | None = None) -> set[int]:
    """The alternates approved for a part, less any its project refuses."""
    if not component_id:
        return set()
    ids = {a for (a,) in db.query(M.ComponentAlternate.alternate_id).filter_by(component_id=component_id)}
    if project_id is None or not ids:
        return ids
    blocks = db.query(M.ProjectAlternateBlock).filter_by(project_id=project_id, component_id=component_id).all()
    return {a for a in ids if not _blocked(blocks, a, refs)}


def is_approved(db: Session, component_id: int | None, alternate_id: int | None,
                project_id: int | None = None, refs: str | None = None) -> bool:
    return bool(alternate_id) and alternate_id in approved_ids(db, component_id, project_id, refs)


def pairs(db: Session) -> dict[int, set[int]]:
    """Every approval at once, part -> its alternates, for a whole-plan read."""
    out: dict[int, set[int]] = defaultdict(set)
    for c, a in db.query(M.ComponentAlternate.component_id, M.ComponentAlternate.alternate_id):
        out[c].add(a)
    return dict(out)


def buy_alternates(db: Session) -> dict[int, int]:
    """part -> the alternate a purchase proposal names (`buy`)."""
    return {c: a for c, a in db.query(M.ComponentAlternate.component_id, M.ComponentAlternate.alternate_id)
            .filter(M.ComponentAlternate.buy.is_(True))}


def _component(db: Session, cid: int | None, what: str) -> M.Component:
    c = db.get(M.Component, cid) if cid else None
    if c is None:
        raise AlternateError(f"the {what} is not a library component", 404)
    return c


def add(db: Session, component_id: int, alternate_id: int, *, buy: bool = False, note: str = "",
        actor: str = "user") -> M.ComponentAlternate:
    _component(db, component_id, "part")
    _component(db, alternate_id, "alternate")
    if component_id == alternate_id:
        raise AlternateError("a part is not an alternate of itself")
    if db.query(M.ComponentAlternate.id).filter_by(component_id=component_id, alternate_id=alternate_id).first():
        raise AlternateError("that alternate is already approved for this part", 409)
    row = M.ComponentAlternate(component_id=component_id, alternate_id=alternate_id, buy=False,
                               note=(note or "")[:500], created_by=(actor or "user")[:100])
    db.add(row)
    db.flush()
    if buy:
        set_buy(db, row, True)
    return row


def set_buy(db: Session, row: M.ComponentAlternate, buy: bool) -> None:
    """At most one alternate of a part carries `buy` (decision 0108 item 3)."""
    if buy:
        for other in db.query(M.ComponentAlternate).filter(M.ComponentAlternate.component_id == row.component_id,
                                                           M.ComponentAlternate.id != row.id,
                                                           M.ComponentAlternate.buy.is_(True)):
            other.buy = False
    row.buy = bool(buy)
    db.flush()


def add_block(db: Session, project_id: int, component_id: int, alternate_id: int, *, refs: str = "",
              note: str = "", actor: str = "user") -> M.ProjectAlternateBlock:
    if db.get(M.Project, project_id) is None:
        raise AlternateError("no such project", 404)
    if not db.query(M.ComponentAlternate.id).filter_by(component_id=component_id,
                                                       alternate_id=alternate_id).first():
        raise AlternateError("that alternate is not approved for this part, so there is nothing to refuse")
    norm = ",".join(sorted(refs_of(refs)))[:200]
    if db.query(M.ProjectAlternateBlock.id).filter_by(project_id=project_id, component_id=component_id,
                                                      alternate_id=alternate_id, refs=norm).first():
        raise AlternateError("this project already refuses that alternate there", 409)
    row = M.ProjectAlternateBlock(project_id=project_id, component_id=component_id, alternate_id=alternate_id,
                                  refs=norm, note=(note or "")[:500], created_by=(actor or "user")[:100])
    db.add(row)
    db.flush()
    return row


def _names(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {c.id: c.name for c in db.query(M.Component).filter(M.Component.id.in_(ids))}


def for_component(db: Session, component_id: int) -> dict:
    """What the component page shows: its approved alternates, the parts it
    may itself stand in for, and every project refusal of either."""
    mine = db.query(M.ComponentAlternate).filter_by(component_id=component_id).order_by(
        M.ComponentAlternate.id).all()
    of = db.query(M.ComponentAlternate).filter_by(alternate_id=component_id).order_by(
        M.ComponentAlternate.id).all()
    blocks = db.query(M.ProjectAlternateBlock).filter(
        (M.ProjectAlternateBlock.component_id == component_id)
        | (M.ProjectAlternateBlock.alternate_id == component_id)).order_by(M.ProjectAlternateBlock.id).all()
    names = _names(db, {r.alternate_id for r in mine} | {r.component_id for r in of}
                   | {b.component_id for b in blocks} | {b.alternate_id for b in blocks})
    projects = {p.id: p.name for p in db.query(M.Project).filter(
        M.Project.id.in_({b.project_id for b in blocks} or {-1}))}

    def row(r: M.ComponentAlternate) -> dict:
        return {"id": r.id, "component_id": r.component_id, "component_name": names.get(r.component_id, ""),
                "alternate_id": r.alternate_id, "alternate_name": names.get(r.alternate_id, ""),
                "buy": r.buy, "note": r.note, "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else ""}

    return {
        "alternates": [row(r) for r in mine],
        "alternate_of": [row(r) for r in of],
        "blocks": [{"id": b.id, "project_id": b.project_id, "project_name": projects.get(b.project_id, ""),
                    "component_id": b.component_id, "component_name": names.get(b.component_id, ""),
                    "alternate_id": b.alternate_id, "alternate_name": names.get(b.alternate_id, ""),
                    "refs": b.refs, "note": b.note, "created_by": b.created_by,
                    "created_at": b.created_at.isoformat() if b.created_at else ""} for b in blocks],
    }
