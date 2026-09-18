"""The fleet MQTT broker: configuration, monitor health, and what it found.

**Every route here is admin-only** (user decision 2026-09-18). The stored
credential reads the topics of every customer device on the broker, so this
sits behind `require_admin` rather than behind the ordinary signed-in gate that
covers the rest of the API — including the read-only routes, because the
discovery list names customer hardware the platform does not own.

The password is never returned by any route. `GET /config` reports
`password_set`, and there is no endpoint that reveals the value.

Presence data is READ through `/api/flasher/devices/{id}` for one device, which
is not admin-only — a device's own online state is ordinary device information.
Only the fleet-wide view and the credential live here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import mqtt_config, mqtt_monitor
from .users import require_admin
from .util import audit

router = APIRouter(prefix="/api/mqtt", tags=["mqtt"])


class MqttConfigIn(BaseModel):
    enabled: bool | None = None
    host: str | None = None
    port: int | None = None
    tls: bool | None = None
    username: str | None = None
    # Omit to keep the stored password; "" to clear it. See mqtt_config.save.
    password: str | None = None
    flush_s: int | None = None
    keepalive_s: int | None = None
    client_id: str | None = None


@router.get("/config")
def get_config(db: Session = Depends(get_db), admin: M.User = Depends(require_admin)):
    return mqtt_config.public(db)


@router.put("/config")
def put_config(body: MqttConfigIn, db: Session = Depends(get_db),
               admin: M.User = Depends(require_admin)):
    """Save the broker configuration.

    Takes effect on the next API restart: the subscriber is armed once at
    startup with the credential in hand, so that a live fleet credential is
    never re-read on a request path. The response says so.
    """
    if body.port is not None and not (1 <= body.port <= 65535):
        raise HTTPException(400, "port must be 1–65535")
    if body.flush_s is not None and body.flush_s < 5:
        raise HTTPException(400, "write interval must be at least 5 seconds")
    actor = admin.username if admin is not None else "dev"
    fields = body.model_dump(exclude_unset=True)
    saved = mqtt_config.save(db, actor=actor, **fields)
    # Which fields moved, never what they moved to — the credential must not
    # reach the audit log any more than it reaches a response.
    audit(db, "update", "mqtt_config", 1, {"fields": sorted(fields.keys())}, actor=actor)
    db.commit()
    return {**saved, "restart_required": True,
            "running": mqtt_monitor.STATE.get("connected", False)}


@router.get("/status")
def status(db: Session = Depends(get_db), admin: M.User = Depends(require_admin)):
    """Health of the subscriber, and the shape of what it has found.

    `unlinked` is the interesting number: topics live on the broker that match
    no device this platform programmed.
    """
    total = db.scalar(select(func.count()).select_from(M.DevicePresence)) or 0
    online = db.scalar(
        select(func.count()).select_from(M.DevicePresence)
        .where(M.DevicePresence.online.is_(True))) or 0
    unlinked = db.scalar(
        select(func.count()).select_from(M.DevicePresence)
        .where(M.DevicePresence.device_unit_id.is_(None))) or 0
    return {
        "monitor": dict(mqtt_monitor.STATE),
        "configured": mqtt_config.public(db),
        "topics": total,
        "online": online,
        "offline": total - online,
        "unlinked": unlinked,
        # A device whose programmed MAC disagrees with its topic's. Never
        # repaired automatically — see mqtt_monitor's MAC section.
        "mac_mismatches": len(mqtt_monitor.mac_mismatches(db)),
    }


@router.get("/mac-mismatches")
def mac_mismatches(db: Session = Depends(get_db),
                   admin: M.User = Depends(require_admin)):
    """Devices whose programmed MAC disagrees with the MAC in their MQTT topic.

    The platform never resolves these by itself. A mismatch means a swapped
    board, a config restored onto different hardware, or a hand-typed topic —
    all of which need a person, and none of which are improved by the platform
    picking a side and destroying the evidence.
    """
    return {"items": mqtt_monitor.mac_mismatches(db)}


@router.get("/unlinked")
def unlinked(limit: int = Query(200, le=1000), db: Session = Depends(get_db),
             admin: M.User = Depends(require_admin)):
    """Devices the broker knows and the platform does not — the discoveries.

    Field replacements, hand-provisioned units, and anything programmed before
    the flasher recorded it.
    """
    rows = db.scalars(
        select(M.DevicePresence)
        .where(M.DevicePresence.device_unit_id.is_(None))
        .order_by(M.DevicePresence.last_seen_at.desc().nullslast())
        .limit(limit)).all()
    return {
        "items": [
            {
                "topic": r.topic,
                "online": r.online,
                "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
                "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
                "inverter": r.inverter,
                "inverter_sn": r.inverter_sn,
                "dongle_version": r.dongle_version,
                "mac_from_topic": mqtt_monitor.mac_from_topic(r.topic),
            }
            for r in rows
        ]
    }


@router.post("/link")
def link(db: Session = Depends(get_db), admin: M.User = Depends(require_admin)):
    """Re-resolve presence rows against device units, and fill MISSING MACs.

    Idempotent, and it never overwrites a MAC that programming already
    recorded — a disagreement is reported by `/mac-mismatches` instead.
    """
    actor = admin.username if admin is not None else "dev"
    linked = mqtt_monitor.link_devices(db)
    filled = mqtt_monitor.backfill_macs(db, actor=actor)
    return {"linked": linked, "macs_filled": filled}
