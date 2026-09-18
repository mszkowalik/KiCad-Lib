"""Read and write the one `mqtt_config` row.

The broker credential reads every customer device on the fleet. It is stored
encrypted, it is admin-only, and it is never handed back out — see the
`models.MqttConfig` docstring for why it is not an `AppSetting` and not an
environment variable.

Everything that needs the broker goes through `load()`, which returns a plain
snapshot with the password already decrypted. Callers must not hold that
snapshot longer than the connection attempt that needs it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models as M
from . import crypto

ROW_ID = 1


@dataclass(frozen=True)
class MqttSettings:
    """A decrypted snapshot. Never serialise this — it holds the password."""

    enabled: bool
    host: str
    port: int
    tls: bool
    username: str
    password: str
    flush_s: int
    keepalive_s: int
    client_id: str

    @property
    def usable(self) -> bool:
        """Enabled AND pointed at a host. Either alone starts nothing."""
        return bool(self.enabled and self.host)


def get_row(db: Session, create: bool = False) -> M.MqttConfig | None:
    row = db.get(M.MqttConfig, ROW_ID)
    if row is None and create:
        row = M.MqttConfig(id=ROW_ID)
        db.add(row)
        db.flush()
    return row


def load(db: Session) -> MqttSettings:
    """The current configuration, with the password decrypted.

    A row that cannot be decrypted (SECRET_KEY changed) yields an empty
    password rather than raising: the monitor then fails to authenticate and
    says so, which is a far better failure than the API refusing to start.
    """
    row = get_row(db)
    if row is None:
        return MqttSettings(False, "", 8883, True, "", "", 15, 60, "7sigma-platform")
    password = ""
    if row.secrets_enc:
        try:
            password = (json.loads(crypto.decrypt_token(row.secrets_enc)) or {}).get(
                "password", "")
        except (ValueError, TypeError):
            password = ""
    return MqttSettings(
        enabled=row.enabled,
        host=row.host,
        port=row.port,
        tls=row.tls,
        username=row.username,
        password=password,
        flush_s=row.flush_s,
        keepalive_s=row.keepalive_s,
        client_id=row.client_id or "7sigma-platform",
    )


def public(db: Session) -> dict:
    """What an admin may SEE. The password is reported as set or not set."""
    row = get_row(db)
    if row is None:
        return {
            "enabled": False, "host": "", "port": 8883, "tls": True,
            "username": "", "password_set": False, "flush_s": 15,
            "keepalive_s": 60, "client_id": "7sigma-platform",
            "updated_by": "", "updated_at": None,
        }
    return {
        "enabled": row.enabled,
        "host": row.host,
        "port": row.port,
        "tls": row.tls,
        "username": row.username,
        # Never the value. See the model docstring.
        "password_set": bool(row.secrets_enc),
        "flush_s": row.flush_s,
        "keepalive_s": row.keepalive_s,
        "client_id": row.client_id,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def save(db: Session, actor: str, **fields) -> dict:
    """Apply an admin's edit. `password=None` leaves the stored one alone.

    An empty-string password CLEARS it — that is the only way to remove a
    credential, and it has to be explicit so a form that simply does not send
    the field can never wipe it by accident.
    """
    row = get_row(db, create=True)
    for key in ("enabled", "host", "port", "tls", "username",
                "flush_s", "keepalive_s", "client_id"):
        if key in fields and fields[key] is not None:
            setattr(row, key, fields[key])
    password = fields.get("password")
    if password is not None:
        row.secrets_enc = (
            crypto.encrypt_token(json.dumps({"password": password})) if password else ""
        )
    row.host = (row.host or "").strip()
    row.updated_by = actor
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return public(db)
