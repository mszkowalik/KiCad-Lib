"""JLCPCB API client — official OpenAPI (JOP-signed) + anonymous parts search.

Wraps the full official surface (component library/detail/private stock, PCB
calculate/audit/WIP/order endpoints — ported from the Vumo project's
scripts/jlc_openapi.py) plus the unofficial jlcpcb.com parts-search endpoint
(from Vumo's scripts/jlcpcb.py). Actively used today: private-library sync,
fetch_component_details (JLCPCB assembly stock for ladder refresh).

Auth per JLCPCB's partner API ("JOP" scheme): every request carries an
Authorization header with appid/accesskey/timestamp/nonce and an
HMAC-SHA256 signature over "METHOD\\npath\\ntimestamp\\nnonce\\nbody\\n"
(base64). Credentials come from JLC_APP_ID / JLC_ACCESS_KEY /
JLC_SECRET_KEY (apply at https://api.jlcpcb.com).

The private library endpoint is paginated:
    POST /overseas/openapi/component/getPrivateComponentLibrary
    {"currentPage": n, "pageSize": 30}

Field names in the response are NOT publicly documented, so `_parse_item`
maps defensively across the naming variants JLC uses elsewhere and the
untouched payload is kept in JlcStockItem.raw — if a sync ever shows
zeros/blanks, inspect `raw` and extend the key lists.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import string
import time
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..models import utcnow
from . import ladder

log = logging.getLogger(__name__)

PRIVATE_LIBRARY_URI = "/overseas/openapi/component/getPrivateComponentLibrary"
COMPONENT_DETAIL_URI = "/overseas/openapi/component/getComponentDetailByCode"
_NONCE_ALPHABET = string.ascii_letters + string.digits


class JlcError(RuntimeError):
    pass


def available() -> bool:
    return bool(settings.jlc_app_id and settings.jlc_access_key and settings.jlc_secret_key)


def _auth_header(method: str, url: str, body: str) -> str:
    split = urlsplit(url)
    canonical = split.path + (f"?{split.query}" if split.query else "")
    nonce = "".join(secrets.choice(_NONCE_ALPHABET) for _ in range(32))
    timestamp = int(time.time())
    string_to_sign = f"{method.upper()}\n{canonical}\n{timestamp}\n{nonce}\n{body}\n"
    signature = base64.b64encode(
        hmac.new(settings.jlc_secret_key.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    ).decode()
    return (
        "JOP "
        f'appid="{settings.jlc_app_id}",'
        f'accesskey="{settings.jlc_access_key}",'
        f'timestamp="{timestamp}",'
        f'nonce="{nonce}",'
        f'signature="{signature}"'
    )


def _post(uri: str, payload: dict) -> dict:
    url = f"{settings.jlc_endpoint.rstrip('/')}{uri}"
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    resp = httpx.post(
        url,
        content=body,
        headers={
            "Authorization": _auth_header("POST", url, body),
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise JlcError(f"JLC API HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    # JLC wraps responses as {code, message, data}; code 200 == success
    code = data.get("code")
    if code not in (200, "200", 0, "0", None):
        raise JlcError(f"JLC API error {code}: {data.get('message') or data}")
    return data


def _first(d: dict, *keys: str, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _parse_item(raw: dict) -> dict:
    # Verified response shape (2026-07): componentCode, componentModel,
    # componentSpecification, and the held quantity split by source:
    # jlcpcbParts (bought at JLC) + consignedParts (shipped in by the user)
    # + globalSourcingParts. idleStock is the unreserved subset.
    qty = _int(raw.get("jlcpcbParts")) + _int(raw.get("consignedParts")) + _int(
        raw.get("globalSourcingParts")
    )
    if qty == 0 and not any(k in raw for k in ("jlcpcbParts", "consignedParts", "globalSourcingParts")):
        qty = _int(_first(raw, "stockCount", "stockQty", "stockNumber", "quantity", "count", default=0))
    return {
        "lcsc": str(_first(raw, "componentCode", "lcscPart", "lcscCode", "code", default="")).strip(),
        "description": str(_first(raw, "describe", "description", "componentName", default="")),
        "mpn": str(_first(raw, "componentModel", "componentModelEn", "mpn", "model", default="")),
        "manufacturer": str(_first(raw, "componentBrandEn", "brand", "manufacturer", default="")),
        "package": str(_first(raw, "componentSpecification", "componentSpecificationEn",
                              "encapStandard", "package", default="")),
        "qty": qty,
    }


def fetch_component_details(codes: list[str]) -> dict[str, dict]:
    """Official-API batch detail (JLCPCB ASSEMBLY stock `stockCount`, JLC
    price ladder `priceRanges`, `libraryType`, parameters) keyed by LCSC
    code. Note: `stockCount` here is JLCPCB's assembly-parts pool, NOT LCSC
    retail stock — see ComponentSupply. Raises JlcError without credentials;
    per-chunk API failures are logged and skipped."""
    if not available():
        raise JlcError("JLC API credentials not configured (JLC_APP_ID / JLC_ACCESS_KEY / JLC_SECRET_KEY)")
    out: dict[str, dict] = {}
    seen = sorted({c.strip() for c in codes if c and c.strip()})
    for i in range(0, len(seen), 20):  # undocumented batch limit — stay small
        chunk = seen[i:i + 20]
        try:
            rows = _post(COMPONENT_DETAIL_URI, {"componentCodes": chunk}).get("data") or []
        except (JlcError, httpx.HTTPError) as e:
            log.warning(f"JLC component detail fetch failed for {chunk}: {e}")
            continue
        for row in rows:
            code = str(row.get("componentCode") or "").strip()
            if code:
                out[code] = row
    return out


def fetch_private_library() -> list[dict]:
    """All pages of the private parts library (raw dicts)."""
    if not available():
        raise JlcError("JLC API credentials not configured (JLC_APP_ID / JLC_ACCESS_KEY / JLC_SECRET_KEY)")
    items: list[dict] = []
    page = 1
    while page < 200:  # hard backstop
        data = _post(PRIVATE_LIBRARY_URI, {"currentPage": page, "pageSize": 30})
        payload = data.get("data")
        rows = payload if isinstance(payload, list) else (payload or {}).get("list") or []
        if not rows:
            break
        items.extend(rows)
        if len(rows) < 30:
            break
        page += 1
    return items


def sync(db: Session) -> dict:
    """Replace the cached inventory with a fresh fetch; valuation from the
    LCSC ladder at the held quantity (live-fetched for parts outside the
    library). Returns a summary report."""
    rows = fetch_private_library()
    lcsc_to_comp = {v: k for k, v in ladder.component_lcsc_map(db).items()}
    now = utcnow()
    db.query(M.JlcStockItem).delete()
    parsed_count = valued = 0
    for raw in rows:
        item = _parse_item(raw)
        comp_id = lcsc_to_comp.get(item["lcsc"])
        unit = None
        detail = None
        if comp_id:
            points = db.query(M.ComponentPricePoint).filter_by(component_id=comp_id).all()
            pt = ladder.price_at(points, max(item["qty"], 1))
            if pt is not None and pt.currency.upper() == "USD":
                unit = pt.unit_price
        if unit is None and item["lcsc"]:
            detail = ladder.fetch_detail(item["lcsc"])
            if detail:
                tiers = detail.get("productPriceList") or []
                best = None
                for t in sorted(tiers, key=lambda t: t.get("ladder") or 0):
                    try:
                        if int(t["ladder"]) <= max(item["qty"], 1) or best is None:
                            best = float(t["usdPrice"])
                    except (KeyError, TypeError, ValueError):
                        continue
                unit = best
        # the private-library response carries no description — pull it from
        # LCSC part metadata
        if not item["description"] and item["lcsc"]:
            if detail is None:
                detail = ladder.fetch_detail(item["lcsc"])
            if detail:
                item["description"] = str(
                    detail.get("productIntroEn") or detail.get("productNameEn") or ""
                )[:490]
                if not item["manufacturer"]:
                    item["manufacturer"] = str(detail.get("brandNameEn") or "")
        if unit is not None:
            valued += 1
        db.add(M.JlcStockItem(**item, unit_price_usd=unit, component_id=comp_id,
                              raw=raw, updated_at=now))
        parsed_count += 1
    db.commit()
    report = {"items": parsed_count, "valued": valued, "synced_at": now.isoformat()}
    log.info(f"JLC private stock sync: {report}")
    return report


def private_stock_map(db: Session) -> dict[str, int]:
    """LCSC part -> quantity held at JLC (cached inventory)."""
    return {
        i.lcsc: i.qty
        for i in db.query(M.JlcStockItem).all()
        if i.lcsc
    }


# --------------------------------------------------------------------------
# Full official OpenAPI surface (ported from the Vumo project's
# scripts/jlc_openapi.py, adapted to this module's settings-based JOP auth).
# Nothing below is wired to a router yet — these are building blocks for
# future features (order tracking, PCB quoting, library sync).
# --------------------------------------------------------------------------

COMPONENT_INFOS_URI = "/overseas/openapi/component/getComponentInfos"
COMPONENT_LIBRARY_URI = "/overseas/openapi/component/getComponentLibraryList"
PCB_CALCULATE_URI = "/overseas/openapi/pcb/calculate"
PCB_AUDIT_URI = "/overseas/openapi/pcb/audit/get"
PCB_WIP_URI = "/overseas/openapi/pcb/wip/get"
PCB_ORDER_DETAIL_URI = "/overseas/openapi/pcb/order/detail"


def get_component_infos(last_key: str | None = None) -> dict:
    """One page of "my components". Returns {componentInfos: [...], lastKey: str}."""
    payload = {"lastKey": last_key} if last_key else {}
    return _post(COMPONENT_INFOS_URI, payload).get("data") or {}


def iter_component_infos():
    """Iterate every "my components" row across pages via the lastKey cursor."""
    last_key = None
    seen_keys: set[str] = set()
    while True:
        data = get_component_infos(last_key)
        yield from data.get("componentInfos", [])
        last_key = data.get("lastKey")
        if not last_key or last_key in seen_keys:
            return
        seen_keys.add(last_key)


def get_component_library_list(page: int = 1, page_size: int = 50) -> dict:
    """Paged base/expand (market) component library listing."""
    return _post(COMPONENT_LIBRARY_URI, {"currentPage": page, "pageSize": page_size}).get("data") or {}


def get_private_component_library(page: int = 1, page_size: int = 30) -> dict:
    """One page of the private (consigned) parts library — the raw form of
    what fetch_private_library() aggregates."""
    return _post(PRIVATE_LIBRARY_URI, {"currentPage": page, "pageSize": page_size}).get("data") or {}


def calculate_pcb(*, file_key: str, pcb_param: dict,
                  country: str, post_code: str, city: str,
                  shipping_method: str | None = None,
                  smt_stencil_param: dict | None = None,
                  achieve_date: int | None = None,
                  order_type: int = 1, batch_num: str | None = None) -> dict:
    """Online PCB price calculation. fileKey comes from the Gerber upload
    endpoint (/overseas/openapi/pcb/uploadGerber, not wrapped yet)."""
    payload: dict = {
        "orderType": order_type,
        "pcbParam": pcb_param,
        "country": country,
        "postCode": post_code,
        "city": city,
        "fileKey": file_key,
    }
    if smt_stencil_param is not None:
        payload["smtStencilParam"] = smt_stencil_param
    if achieve_date is not None:
        payload["achieveDate"] = achieve_date
    if shipping_method is not None:
        payload["shippingMethod"] = shipping_method
    if batch_num is not None:
        payload["batchNum"] = batch_num
    return _post(PCB_CALCULATE_URI, payload).get("data") or {}


def get_pcb_audit_info(batch_num: str) -> dict:
    """PCB order audit info by batchNum."""
    return _post(PCB_AUDIT_URI, {"batchNum": batch_num}).get("data") or {}


def get_pcb_wip_process(batch_num: str) -> dict:
    """PCB work-in-progress / production stage by batchNum."""
    return _post(PCB_WIP_URI, {"batchNum": batch_num}).get("data") or {}


def get_pcb_order_detail(batch_num: str) -> dict:
    """PCB order detail by batchNum."""
    return _post(PCB_ORDER_DETAIL_URI, {"batchNum": batch_num}).get("data") or {}


# --------------------------------------------------------------------------
# Unofficial jlcpcb.com parts search (ported from Vumo's scripts/jlcpcb.py).
# Anonymous — no JOP credentials needed. Quirks: `+` acts as an AND
# separator in keywords, the index stores MPNs unhyphenated, and results
# include eval boards whose names merely contain the chip MPN.
# --------------------------------------------------------------------------

PARTS_SEARCH_URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
_PARTS_SEARCH_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://jlcpcb.com",
    "Referer": "https://jlcpcb.com/parts",
}


def search_parts(keyword: str, page_size: int = 10) -> list[dict]:
    """Search the public JLCPCB assembly-parts catalog. Rows carry
    componentCode (Cxxxx), componentModelEn (MPN), componentBrandEn,
    stockCount (assembly pool), componentLibraryType. Raises JlcError on
    HTTP/API failure."""
    body = {"keyword": keyword, "currentPage": 1, "pageSize": page_size}
    try:
        resp = httpx.post(PARTS_SEARCH_URL, json=body, headers=_PARTS_SEARCH_HEADERS, timeout=15)
    except httpx.HTTPError as e:
        raise JlcError(f"JLC parts search failed: {e}") from e
    if resp.status_code != 200:
        raise JlcError(f"JLC parts search HTTP {resp.status_code}")
    payload = resp.json()
    if payload.get("code") != 200:
        raise JlcError(f"JLC parts search error {payload.get('code')}: {payload.get('message')}")
    return payload.get("data", {}).get("componentPageInfo", {}).get("list", []) or []


def _norm_mpn(s: str) -> str:
    return (s or "").upper().replace("-", "").replace("_", "").replace(" ", "")


def find_market_match(mpn: str, brand: str = "") -> tuple[dict | None, str, list[dict]]:
    """Resolve a part in the JLCPCB market catalog by brand+MPN.

    Returns (chosen, status, candidates). Status:
      'exact'      — unique brand+MPN match (or unique brand-strict in an
                     ambiguous set)
      'mpn_only'   — MPN matches but brand differs (data mismatch)
      'ambiguous'  — multiple genuine brand+MPN candidates
      'empty'      — no hits even for MPN alone
    """
    if not mpn:
        return None, "empty", []

    brand_token = brand.split()[0] if brand else ""
    mpn_query = mpn.replace("-", "")  # JLC index uses unhyphenated MPNs

    if brand_token:
        results = search_parts(f"{brand_token}+{mpn_query}")
        if len(results) == 1:
            return results[0], "exact", results
        if len(results) > 1:
            # Narrow to exact-MPN matches first — the AND search also returns
            # eval boards / dev kits whose name contains the chip MPN.
            nm = _norm_mpn(mpn)
            mpn_strict = [r for r in results
                          if _norm_mpn(r.get("componentModelEn", "")) == nm]
            pool = mpn_strict if mpn_strict else results
            if len(pool) == 1:
                return pool[0], "exact", pool
            bt = brand_token.lower()
            brand_strict = [r for r in pool
                            if (r.get("componentBrandEn") or "").lower().startswith(bt)]
            if len(brand_strict) == 1:
                return brand_strict[0], "exact", pool
            return None, "ambiguous", pool

    # Fallback: MPN alone, verify brand client-side
    results = search_parts(mpn)
    if not results:
        return None, "empty", []

    nm = _norm_mpn(mpn)
    mpn_hits = [r for r in results if _norm_mpn(r.get("componentModelEn", "")) == nm]
    if not mpn_hits:
        return None, "empty", results

    if len(mpn_hits) == 1:
        chosen = mpn_hits[0]
        jlc_brand = (chosen.get("componentBrandEn") or "").lower()
        if (not brand_token or brand_token.lower() in jlc_brand
                or jlc_brand in brand_token.lower() or jlc_brand in ("", "--")):
            return chosen, "exact", mpn_hits
        return chosen, "mpn_only", mpn_hits
    return None, "ambiguous", mpn_hits
