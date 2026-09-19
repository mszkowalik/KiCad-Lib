"""Editable runtime configuration — the Admin page's Configuration tab.

Thin: parse, call `services/appconfig.py`, shape the response. The precedence
rules, the editable whitelist and why some fields are absent live there.

**Every route here is admin-only** (decision 0045). These knobs are the
deployment, not a person's preferences: `set_override` writes the value onto
the live settings singleton, so a change lands on the next request rather than
at the next restart. An ordinary user could otherwise rotate `httplib_token`
and break every installed `.kicad_httplib`, repoint `render_url` at a host of
their choosing, or move `public_base_url` out from under every generated link.
A GET is gated with the writes: the non-secret half names the render service
and the deployment's own address, and a read that only an admin can act on is
of no use to anybody else. Secrets were never returned — `appconfig.describe`
reports `is_set` and nothing more.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import appconfig
from .users import require_admin
from .util import audit

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _actor(admin: M.User | None) -> str:
    """`require_admin` returns None when auth is off (dev), the same posture
    `routers/users.py` takes."""
    return admin.username if admin is not None else "dev"


class SettingIn(BaseModel):
    value: str


@router.get("")
def list_settings(db: Session = Depends(get_db),
                  admin: M.User = Depends(require_admin)):
    """Every editable field with its live value, source and restart flag.

    Secrets report only whether they are set — the value is never sent back.
    """
    items = appconfig.describe(db)
    groups: list[dict] = []
    for item in items:
        if not groups or groups[-1]["group"] != item["group"]:
            groups.append({"group": item["group"], "items": []})
        groups[-1]["items"].append(item)
    return {"groups": groups}


@router.put("/{key}")
def set_setting(key: str, body: SettingIn, db: Session = Depends(get_db),
                admin: M.User = Depends(require_admin)):
    try:
        knob = appconfig.set_override(db, key, body.value)
    except KeyError:
        raise HTTPException(404, f"{key} is not an editable setting") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    # Never write a secret's value into the audit trail.
    audit(db, "settings.set", "setting", key,
          details={"value": "(hidden)" if knob.secret else body.value},
          actor=_actor(admin))
    db.commit()
    return {"ok": True, "restart_required": knob.restart}


@router.delete("/{key}")
def revert_setting(key: str, db: Session = Depends(get_db),
                   admin: M.User = Depends(require_admin)):
    """Drop the override and fall back to the environment or code default."""
    try:
        knob = appconfig.clear_override(db, key)
    except KeyError:
        raise HTTPException(404, f"{key} is not an editable setting") from None
    audit(db, "settings.revert", "setting", key, actor=_actor(admin))
    db.commit()
    return {"ok": True, "restart_required": knob.restart}
