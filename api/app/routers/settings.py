"""Editable runtime configuration — the Configuration card on the Setup page.

Thin: parse, call `services/appconfig.py`, shape the response. The precedence
rules, the editable whitelist and why some fields are absent live there.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import appconfig
from .util import audit

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingIn(BaseModel):
    value: str


@router.get("")
def list_settings(db: Session = Depends(get_db)):
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
def set_setting(key: str, body: SettingIn, db: Session = Depends(get_db)):
    try:
        knob = appconfig.set_override(db, key, body.value)
    except KeyError:
        raise HTTPException(404, f"{key} is not an editable setting") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    # Never write a secret's value into the audit trail.
    audit(db, "settings.set", "setting", key,
          details={"value": "(hidden)" if knob.secret else body.value})
    db.commit()
    return {"ok": True, "restart_required": knob.restart}


@router.delete("/{key}")
def revert_setting(key: str, db: Session = Depends(get_db)):
    """Drop the override and fall back to the environment or code default."""
    try:
        knob = appconfig.clear_override(db, key)
    except KeyError:
        raise HTTPException(404, f"{key} is not an editable setting") from None
    audit(db, "settings.revert", "setting", key)
    db.commit()
    return {"ok": True, "restart_required": knob.restart}
