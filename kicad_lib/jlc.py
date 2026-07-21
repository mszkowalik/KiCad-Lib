"""Minimal JLCPCB OpenAPI client for the repo pipeline.

Stdlib-only (urllib) port of the batch component-detail call from
``platform/api/app/services/jlc.py`` — the platform copies logic from
``kicad_lib/``, never the other way around, so this file must not import
anything from ``platform/``.

Auth per JLCPCB's partner API ("JOP" scheme): every request carries an
Authorization header with appid/accesskey/timestamp/nonce and an
HMAC-SHA256 signature over ``METHOD\\npath\\ntimestamp\\nnonce\\nbody\\n``
(base64). Credentials come from ``JLC_APP_ID`` / ``JLC_ACCESS_KEY`` /
``JLC_SECRET_KEY`` — read from the environment, falling back to
``platform/.env`` so the pipeline and the platform share one set.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import string
import time
import urllib.request
from urllib.parse import urlsplit

from kicad_lib import config
from kicad_lib.colors import get_logger

log = get_logger(__name__)

COMPONENT_DETAIL_URI = "/overseas/openapi/component/getComponentDetailByCode"
_NONCE_ALPHABET = string.ascii_letters + string.digits


def available() -> bool:
    return bool(config.JLC_APP_ID and config.JLC_ACCESS_KEY and config.JLC_SECRET_KEY)


def _auth_header(method: str, url: str, body: str) -> str:
    split = urlsplit(url)
    canonical = split.path + (f"?{split.query}" if split.query else "")
    nonce = "".join(secrets.choice(_NONCE_ALPHABET) for _ in range(32))
    timestamp = int(time.time())
    string_to_sign = f"{method.upper()}\n{canonical}\n{timestamp}\n{nonce}\n{body}\n"
    signature = base64.b64encode(
        hmac.new(config.JLC_SECRET_KEY.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    ).decode()
    return (
        "JOP "
        f'appid="{config.JLC_APP_ID}",'
        f'accesskey="{config.JLC_ACCESS_KEY}",'
        f'timestamp="{timestamp}",'
        f'nonce="{nonce}",'
        f'signature="{signature}"'
    )


def _post(uri: str, payload: dict) -> dict:
    url = f"{config.JLC_ENDPOINT.rstrip('/')}{uri}"
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    req = urllib.request.Request(
        url,
        data=body.encode(),
        method="POST",
        headers={
            "Authorization": _auth_header("POST", url, body),
            "Content-Type": "application/json",
        },
    )
    data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    # JLC wraps responses as {code, message, data}; code 200 == success
    code = data.get("code")
    if code not in (200, "200", 0, "0", None):
        raise RuntimeError(f"JLC API error {code}: {data.get('message') or data}")
    return data


def fetch_component_details(codes: list[str]) -> dict[str, dict]:
    """Official-API batch detail rows (JLC price ladder ``priceRanges``,
    assembly ``stockCount``) keyed by LCSC code. {} when credentials are
    absent; per-chunk API failures are logged and skipped."""
    if not available():
        return {}
    out: dict[str, dict] = {}
    seen = sorted({c.strip() for c in codes if c and c.strip()})
    for i in range(0, len(seen), 20):  # undocumented batch limit — stay small
        chunk = seen[i : i + 20]
        try:
            rows = _post(COMPONENT_DETAIL_URI, {"componentCodes": chunk}).get("data") or []
        except Exception as e:
            log.warning(f"  ! JLC detail fetch failed for {chunk}: {e}")
            continue
        for row in rows:
            code = str(row.get("componentCode") or "").strip()
            if code:
                out[code] = row
    return out


def tiers(row: dict | None) -> list[dict]:
    """A detail row's ``priceRanges`` as LCSC-ladder-shaped dicts
    (``{"ladder": qty_from, "usdPrice": price}``), so pricing code can
    treat both suppliers identically. [] when absent."""
    if not isinstance(row, dict):
        return []
    out: list[dict] = []
    for r in row.get("priceRanges") or []:
        try:
            q, p = int(r["startQuantity"]), float(r["unitPrice"])
        except (KeyError, TypeError, ValueError):
            continue
        if q >= 1 and p > 0:
            out.append({"ladder": q, "usdPrice": p})
    return sorted(out, key=lambda t: t["ladder"])
