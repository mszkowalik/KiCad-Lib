"""Per-device MQTT credential derivation.

Byte-for-byte port of the old tool's hash_password.py — the broker's stored
hashes were made with exactly this scheme, so any change would strand the
existing fleet. Scheme: password = base64(sha512(username + salt))[:20],
mosquitto line = "user:$6$salt$base64(sha512(password + salt))".
"""
from __future__ import annotations

import base64
import hashlib


def derive(username: str, password: str, salt: str) -> tuple[str, str, str, str]:
    """Return (username, password, salt, final_hash).

    An empty `password` derives one from the username + salt (the production
    path: every device gets a deterministic per-topic password).
    """
    salt_bytes = salt.encode("utf-8")
    missing_padding = len(salt_bytes) % 4
    if missing_padding:
        salt_bytes += b"=" * (4 - missing_padding)
        salt = salt_bytes.decode("utf-8")
    salt_b64 = base64.b64decode(salt_bytes)

    if not password:
        m = hashlib.sha512()
        m.update(username.encode("utf-8"))
        m.update(salt_b64)
        password = base64.b64encode(m.digest()).decode("utf-8")

    password = password[:20]
    m = hashlib.sha512()
    m.update(password.encode("utf-8"))
    m.update(salt_b64)
    final_hash = base64.b64encode(m.digest()).decode("utf-8")
    return username, password, salt, final_hash


def mosquitto_line(username: str, salt: str, final_hash: str) -> str:
    return f"{username}:$6${salt}${final_hash}"
