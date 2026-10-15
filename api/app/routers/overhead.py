"""The company overhead categories — decision 0091.

The list is SHARED reference data, so its writes are admin-only and listed in
`tests/auth/test_role_gates.py`; reading it is open, because every invoice
editor offers it. The rules live in `services/overhead.py`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import companies as company_svc
from ..services import overhead
from .users import require_admin
from .util import acting_name, audit

router = APIRouter(prefix="/api/overhead-categories", tags=["overhead"])


def _actor(admin: M.User | None) -> str:
    return admin.username if admin is not None else "dev"


def _category(db: Session, key: str) -> M.OverheadCategory:
    c = overhead.by_key(db, key)
    if c is None:
        raise HTTPException(404, f"no overhead category {key!r}")
    return c


@router.get("")
def list_categories(db: Session = Depends(get_db)):
    """Every category, by label with the fallback last, and how many live
    positions name it (over every company). A key positions name that is not
    on the list — put back by an undo after its category was removed — is
    listed too, with `registered: false`, so it can be added again."""
    used = overhead.usage(db)
    rows = [{"key": c.key, "label": c.label, "positions": used.get(c.key, 0),
             "registered": True, "fallback": c.key == overhead.FALLBACK} for c in overhead.ordered(db)]
    known = {r["key"] for r in rows}
    rows += [{"key": k, "label": k, "positions": n, "registered": False, "fallback": False}
             for k, n in sorted(used.items()) if k not in known]
    return rows


@router.get("/{key}/documents")
def category_documents(key: str, db: Session = Depends(get_db), request: Request = None):
    """The supplier documents whose live positions name this category, in the
    companies the header scope shows."""
    return overhead.documents(db, key, company_svc.scope_ids(db, request))


class CategoryIn(BaseModel):
    label: str
    key: str = ""


class CategoryPatch(BaseModel):
    label: str


@router.post("")
def create_category(body: CategoryIn, db: Session = Depends(get_db),
                    admin: M.User = Depends(require_admin)):
    """A new category. `key` is derived from the label when empty, and never
    changes afterwards."""
    try:
        c = overhead.create(db, body.label, body.key, actor=acting_name())
    except overhead.OverheadError as e:
        raise HTTPException(422, str(e)) from None
    audit(db, "overhead_category.create", "overhead_category", c.id,
          details={"key": c.key, "label": c.label}, actor=_actor(admin))
    db.commit()
    return {"key": c.key, "label": c.label}


@router.patch("/{key}")
def relabel_category(key: str, body: CategoryPatch, db: Session = Depends(get_db),
                     admin: M.User = Depends(require_admin)):
    """The label only. The key is what positions store."""
    c = _category(db, key)
    before = c.label
    try:
        overhead.relabel(db, c, body.label)
    except overhead.OverheadError as e:
        raise HTTPException(422, str(e)) from None
    audit(db, "overhead_category.relabel", "overhead_category", c.id,
          details={"key": c.key, "previous": before, "label": c.label}, actor=_actor(admin))
    db.commit()
    return {"key": c.key, "label": c.label}


@router.delete("/{key}")
def delete_category(key: str, db: Session = Depends(get_db),
                    admin: M.User = Depends(require_admin)):
    """Only a category no live position names; 409 lists the documents that
    still do."""
    c = _category(db, key)
    cid, label = c.id, c.label
    try:
        overhead.delete(db, c)
    except overhead.InUse as e:
        raise HTTPException(409, {"error": str(e), "documents": e.documents}) from None
    except overhead.OverheadError as e:
        raise HTTPException(422, str(e)) from None
    audit(db, "overhead_category.delete", "overhead_category", cid,
          details={"key": key, "label": label}, actor=_actor(admin))
    db.commit()
    return {"ok": True}
