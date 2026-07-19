"""LCSC metadata client — ported from kicad_lib/easyeda/api.py (copied, not
imported). In-memory cache only; the platform DB is the persistent store."""
from __future__ import annotations

import threading

import httpx

LCSC_API_URL = "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={}"

_cache: dict[str, dict | None] = {}
_lock = threading.Lock()


def fetch_metadata(lcsc_id: str) -> dict | None:
    """Returns {manufacturer, mpn, description, datasheet, category, package}
    or None on failure. Thread-safe, memoized."""
    with _lock:
        if lcsc_id in _cache:
            return _cache[lcsc_id]
    result_meta: dict | None = None
    try:
        resp = httpx.get(
            LCSC_API_URL.format(lcsc_id),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
        result = resp.json().get("result")
        if isinstance(result, dict):
            result_meta = {
                "manufacturer": result.get("brandNameEn", ""),
                "mpn": result.get("productModel", ""),
                "description": result.get("productIntroEn") or result.get("productNameEn") or "",
                "datasheet": result.get("pdfUrl", ""),
                "category": result.get("catalogName", ""),
                "package": result.get("encapStandard", ""),
            }
    except Exception:
        result_meta = None
    with _lock:
        _cache[lcsc_id] = result_meta
    return result_meta
