"""JLCPCB web-session credentials + the order/invoice reads they unlock.

Split from `jlc_stock.py` because this is a different authority: `jlc_stock`
runs on the JOP partner credentials in `settings`, while everything here needs
a stored browser session (see `services/jlc_web.py` for why the official API
cannot serve this data at all).

Read endpoints deliberately return JLC's payload close to raw. Mapping an
invoice onto runs and draws is a separate, reviewable step — a fetch must
never write money rows as a side effect.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import jlc_web
from .util import audit

router = APIRouter(prefix="/api/jlc/web", tags=["jlc-web"])


class SessionBody(BaseModel):
    cookies: str
    label: str = ""


def _guard(db: Session) -> None:
    if not jlc_web.available(db):
        raise HTTPException(
            409,
            "no JLCPCB browser session stored — paste cookies at Settings > JLC session first",
        )


def _run(fn, *args, **kwargs):
    """Map the service's two failure modes onto distinct HTTP codes: an expired
    session is the user's to fix (401), anything else is upstream (502)."""
    try:
        return fn(*args, **kwargs)
    except jlc_web.JlcSessionExpired as e:
        raise HTTPException(401, str(e)) from e
    except jlc_web.JlcWebError as e:
        raise HTTPException(502, str(e)) from e


# ------------------------------------------------------------------ session
@router.get("/session")
def get_session(db: Session = Depends(get_db)):
    return jlc_web.session_status(db)


@router.put("/session")
def put_session(body: SessionBody, db: Session = Depends(get_db)):
    try:
        summary = jlc_web.set_session_cookies(db, body.cookies, body.label)
    except jlc_web.JlcWebError as e:
        raise HTTPException(400, str(e)) from e
    # Never audit the cookie values — only that a session was replaced.
    audit(db, "jlc.web.session.set", "jlc_web_session", 1,
          {"cookie_names": summary["cookie_names"], "label": body.label})
    db.commit()
    return {**jlc_web.session_status(db), "cookie_names": summary["cookie_names"]}


@router.delete("/session")
def delete_session(db: Session = Depends(get_db)):
    jlc_web.clear_session(db)
    audit(db, "jlc.web.session.clear", "jlc_web_session", 1, {})
    db.commit()
    return jlc_web.session_status(db)


@router.post("/session/check")
def check_session(db: Session = Depends(get_db)):
    """Liveness, not presence — cookies can be stored and already dead."""
    _guard(db)
    return jlc_web.check_session(db)


# ------------------------------------------------------------------- orders
@router.get("/orders")
def list_orders(page: int = 1, page_size: int = 25, status: str = "", search: str = "",
                db: Session = Depends(get_db)):
    _guard(db)
    return _run(jlc_web.list_order_batches, db, page=page, page_size=page_size,
                status=status, search=search)


@router.get("/orders/{batch_num}")
def order_detail(batch_num: str, db: Session = Depends(get_db)):
    _guard(db)
    return _run(jlc_web.get_order_detail, db, batch_num)


@router.get("/orders/{batch_num}/invoice")
def order_invoice(batch_num: str, db: Session = Depends(get_db)):
    """The manufacturing invoice, raw. `presaleDetailResultVOList` carries the
    per-component / per-SMT-order billed consumption."""
    _guard(db)
    return _run(jlc_web.get_manufacturing_invoice, db, batch_num)


@router.get("/parts-orders")
def parts_orders(page: int = 1, page_size: int = 25, status: str = "", search: str = "",
                 db: Session = Depends(get_db)):
    _guard(db)
    return _run(jlc_web.list_parts_orders, db, page=page, page_size=page_size,
                status=status, search=search)


@router.get("/parts-orders/{order_batch_no}/invoice")
def parts_invoice(order_batch_no: str, db: Session = Depends(get_db)):
    _guard(db)
    return _run(jlc_web.get_parts_invoice, db, order_batch_no)
