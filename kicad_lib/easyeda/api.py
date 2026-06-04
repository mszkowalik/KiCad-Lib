"""
LCSC API client for the KiCad Library Management System.

Handles communication with the LCSC web API to fetch component metadata
(manufacturer, MPN, description, datasheet, package) and maps it to the YAML
property keys used in the library definitions.
"""

import json
import threading
import urllib.request
from pathlib import Path

from kicad_lib import config
from kicad_lib.colors import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# LCSC metadata → YAML property mapping
# ---------------------------------------------------------------------------

LCSC_PROPERTY_MAP: dict[str, str] = {
    "description": "ki_description",
    "manufacturer": "Manufacturer 1",
    "mpn": "Manufacturer Part Number 1",
    "datasheet": "Datasheet",
}

LCSC_STATIC_PROPS: dict[str, str] = {
    "Supplier 1": "LCSC",
}

# ---------------------------------------------------------------------------
# Metadata fetching (with persistent disk cache)
# ---------------------------------------------------------------------------

_cache: dict[str, dict[str, str] | None] = {}
_cache_lock = threading.Lock()
_cache_dirty = False  # true when in-memory cache has unsaved entries


def _load_cache() -> None:
    """Load the on-disk cache into memory (called once at import time)."""
    global _cache
    path = Path(config.LCSC_METADATA_CACHE)
    if not path.exists():
        return
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            with _cache_lock:
                _cache.update(data)
    except Exception as e:
        log.warning(f"Could not load LCSC cache from {path}: {e}")


def save_cache() -> None:
    """Flush the in-memory cache to disk. Call after a batch of fetches."""
    global _cache_dirty
    with _cache_lock:
        if not _cache_dirty:
            return
        snapshot = dict(_cache)
        _cache_dirty = False
    path = Path(config.LCSC_METADATA_CACHE)
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
    except Exception as e:
        log.warning(f"Could not save LCSC cache to {path}: {e}")


def fetch_metadata(lcsc_id: str) -> dict[str, str] | None:
    """Fetch component metadata from the LCSC API.

    Returns a dict with keys: manufacturer, mpn, description, datasheet,
    category, package.  Returns ``None`` on failure.  Results are cached in
    memory and persisted to disk across runs.  Thread-safe.
    """
    global _cache_dirty
    with _cache_lock:
        if lcsc_id in _cache:
            return _cache[lcsc_id]

    url = config.LCSC_API_URL.format(lcsc_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        result = data.get("result")
        if not result or not isinstance(result, dict):
            with _cache_lock:
                _cache[lcsc_id] = None
                _cache_dirty = True
            return None
        meta = {
            "manufacturer": result.get("brandNameEn", ""),
            "mpn": result.get("productModel", ""),
            "description": result.get("productIntroEn") or result.get("productNameEn") or "",
            "datasheet": result.get("pdfUrl", ""),
            "category": result.get("catalogName", ""),
            "package": result.get("encapStandard", ""),
        }
        with _cache_lock:
            _cache[lcsc_id] = meta
            _cache_dirty = True
        return meta
    except Exception as e:
        log.warning(f"Could not fetch LCSC metadata for {lcsc_id}: {e}")
        with _cache_lock:
            _cache[lcsc_id] = None
            _cache_dirty = True
        return None


def build_property_updates(meta: dict[str, str], lcsc_id: str) -> dict[str, str]:
    """Build a YAML property dict from LCSC metadata.

    Maps metadata fields to their corresponding YAML property keys and adds
    the static supplier properties.
    """
    props: dict[str, str] = {}
    for meta_key, yaml_key in LCSC_PROPERTY_MAP.items():
        val = meta.get(meta_key, "")
        if val:
            props[yaml_key] = val

    props.update(LCSC_STATIC_PROPS)
    props["Supplier Part Number 1"] = lcsc_id
    return props


# Load the disk cache immediately so all callers benefit from the first import.
_load_cache()
