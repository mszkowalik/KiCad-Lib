"""The company overhead categories — decision 0091, which makes the list of
decision 0068 a table an administrator edits.

Three facts the rest of the platform relies on:

1. **A category's key is what a position stores.** `run_cost_lines.overhead_category`
   names it by `key`, with no foreign key (an empty value is legal and means
   `FALLBACK`), so a key never changes once created. The label may.
2. **A category is removed only when no live position names it.** The
   positions are moved to another category first, by whoever edits the
   invoices; nothing here moves money on its own.
3. **`FALLBACK` is never removed.** An overhead position stored with no
   category counts as `FALLBACK` (`company_books`, `routers/run_costs`), so
   removing it would leave those positions in a category that does not exist.
"""
from __future__ import annotations

import logging
import re
import unicodedata

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models as M
from . import session_memo

log = logging.getLogger(__name__)

#: The list decision 0068 shipped in code. A fresh deployment starts with it.
SEED = (
    ("leasing", "Leasing"), ("telecom", "Phone and internet"), ("software", "Software and IT services"),
    ("accounting", "Accounting"), ("office", "Office"), ("travel", "Travel"), ("car", "Car and fuel"),
    ("insurance", "Insurance"), ("bank", "Bank fees"), ("rent", "Rent"), ("marketing", "Marketing"),
    ("training", "Training"), ("other", "Other"),
)

#: The category an overhead position with no category counts under.
FALLBACK = "other"

_KEY = re.compile(r"^[a-z0-9_]{1,40}$")
#: Letters NFKD does not take apart into a base letter and a mark.
_LATIN = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss", "đ": "d", "Đ": "D"})

SEED_ACTOR = "migration"


class OverheadError(ValueError):
    """A request the list refuses. The message is shown to the user."""


class InUse(OverheadError):
    """A removal refused because live positions still name the category."""

    def __init__(self, message: str, documents: list[dict]):
        super().__init__(message)
        self.documents = documents


def key_from(label: str) -> str:
    """`Narzędzia i sprzęt` -> `narzedzia_i_sprzet`."""
    s = unicodedata.normalize("NFKD", (label or "").translate(_LATIN))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40].rstrip("_")


def ensure_seeded(db: Session) -> int:
    """Seed an EMPTY list. Never adds to a list an admin has edited: a
    category an admin removed must not come back on the next start."""
    if db.query(M.OverheadCategory.id).first() is not None:
        return 0
    for key, label in SEED:
        db.add(M.OverheadCategory(key=key, label=label, created_by=SEED_ACTOR))
    db.flush()
    return len(SEED)


def run_startup_seed() -> None:
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        n = ensure_seeded(db)
        db.commit()
        if n:
            log.info(f"overhead categories: seeded {n}")
    finally:
        db.close()


def ordered(db: Session) -> list[M.OverheadCategory]:
    """By label, `FALLBACK` last — it is the answer when nothing else fits."""
    rows = db.query(M.OverheadCategory).all()
    return sorted(rows, key=lambda c: (c.key == FALLBACK, c.label.lower()))


def keys(db: Session) -> frozenset[str]:
    """The registered keys, read once per request (a document save checks
    every position)."""
    return session_memo.get(db, "overhead_keys",
                            lambda: frozenset(k for (k,) in db.query(M.OverheadCategory.key).all()))


def labels(db: Session) -> dict[str, str]:
    return {c.key: c.label for c in ordered(db)}


def check_key(db: Session, key: str) -> None:
    """Refuse a position's category that is not on the list."""
    if key and key not in keys(db):
        raise OverheadError(f"overhead category {key!r} does not exist — one of {sorted(keys(db))}, "
                            f"or an admin adds it on Production → Company books → Overhead")


def _live_overhead(db: Session):
    return (db.query(M.RunCostLine)
            .filter(M.RunCostLine.allocate == "overhead", M.RunCostLine.voided_at.is_(None)))


def _category_col():
    """A position's category, with an empty one read as `FALLBACK`."""
    return func.coalesce(func.nullif(M.RunCostLine.overhead_category, ""), FALLBACK)


def usage(db: Session) -> dict[str, int]:
    """Live overhead positions per category, over every company."""
    col = _category_col()
    return dict(_live_overhead(db).with_entities(col, func.count(M.RunCostLine.id)).group_by(col).all())


def documents(db: Session, key: str, scope: list[int] | None = None) -> list[dict]:
    """The supplier documents whose live positions name `key`, newest first.
    `scope` limits them to those companies (a document with no buyer stays)."""
    q = (_live_overhead(db).join(M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id)
         .filter(_category_col() == key))
    if scope is not None:
        q = q.filter((M.RunCostDocument.company_id.in_(scope)) | (M.RunCostDocument.company_id.is_(None)))
    rows = (q.with_entities(M.RunCostDocument.id, M.RunCostDocument.supplier, M.RunCostDocument.doc_number,
                            M.RunCostDocument.doc_date, M.RunCostDocument.currency, M.RunCostDocument.company_id,
                            func.count(M.RunCostLine.id),
                            func.sum(func.coalesce(M.RunCostLine.qty, 0) * func.coalesce(M.RunCostLine.unit_price, 0)))
            .group_by(M.RunCostDocument.id)
            .order_by(M.RunCostDocument.doc_date.desc(), M.RunCostDocument.id.desc())
            .all())
    return [{"id": r[0], "supplier": r[1], "doc_number": r[2], "doc_date": r[3], "currency": r[4],
             "company_id": r[5], "positions": r[6], "net": round(float(r[7] or 0), 2)} for r in rows]


def by_key(db: Session, key: str) -> M.OverheadCategory | None:
    return db.query(M.OverheadCategory).filter_by(key=key).first()


def _check_label(db: Session, label: str, except_id: int | None = None) -> str:
    label = (label or "").strip()
    if not label:
        raise OverheadError("a category needs a label")
    if len(label) > 100:
        raise OverheadError("a label is at most 100 characters")
    same = db.query(M.OverheadCategory).filter(func.lower(M.OverheadCategory.label) == label.lower()).first()
    if same is not None and same.id != except_id:
        raise OverheadError(f"category {same.label!r} ({same.key}) already exists")
    return label


def create(db: Session, label: str, key: str = "", actor: str = "") -> M.OverheadCategory:
    label = _check_label(db, label)
    key = (key or "").strip() or key_from(label)
    if not _KEY.match(key):
        raise OverheadError(f"key {key!r} must be 1-40 characters of a-z, 0-9 and _ "
                            f"(it is what a position stores, and never changes)")
    if by_key(db, key) is not None:
        raise OverheadError(f"category key {key!r} already exists")
    c = M.OverheadCategory(key=key, label=label, created_by=actor)
    db.add(c)
    db.flush()
    return c


def relabel(db: Session, cat: M.OverheadCategory, label: str) -> None:
    cat.label = _check_label(db, label, except_id=cat.id)
    db.flush()


def delete(db: Session, cat: M.OverheadCategory) -> None:
    """Only a category no live position names, and never `FALLBACK`."""
    if cat.key == FALLBACK:
        raise OverheadError(f"{cat.label!r} is where an overhead position without a category goes, "
                            f"and cannot be removed")
    docs = documents(db, cat.key)
    if docs:
        n = sum(d["positions"] for d in docs)
        named = ", ".join(f"{d['doc_number'] or 'no number'} ({d['supplier']}, {d['doc_date']})" for d in docs[:5])
        more = f" and {len(docs) - 5} more" if len(docs) > 5 else ""
        raise InUse(f"{cat.label!r} is used by {n} position(s) on {len(docs)} document(s): {named}{more}. "
                    f"Move them to another category first.", docs)
    db.delete(cat)
    db.flush()
