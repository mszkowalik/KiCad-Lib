"""Supplier price refresh — JLCPCB first, LCSC fallback.

Walks every component in ``Sources/*.yaml``, fetches the latest price
ladder — the JLCPCB assembly ladder (official OpenAPI, batched) when
available, else the LCSC retail ladder — and writes back six properties:

    Price Source, Price Updated, Price @1 USD, Price @100 USD,
    Price @Bulk USD, Price Bulk Qty

``Price Source`` records which ladder priced the entry: ``JLCPCB`` or
``LCSC`` (both robot-managed). Any other value (e.g. ``Manual``) pins the
entry — it is never overwritten.

Skip rules:
  * No "LCSC Part" property                        → skip
  * "Price Source" not blank/JLCPCB/LCSC           → manual entry, leave alone
  * "Price Updated" < 30 days old                  → still fresh, skip —
    UNLESS the source is LCSC and JLCPCB now has a ladder for the part
    (the one-time upgrade to JLC-first pricing)
  * Neither supplier returns a price ladder        → skip, do not add fields
"""

from __future__ import annotations

import datetime as _dt
import json
import urllib.request
from pathlib import Path

from kicad_lib import config, jlc
from kicad_lib.colors import get_logger
from kicad_lib.yaml.rewriter import dq, load_roundtrip, save_roundtrip

log = get_logger(__name__)

PRICE_KEYS = ("Price @1 USD", "Price @100 USD", "Price @Bulk USD", "Price Bulk Qty")
SOURCE_KEY = "Price Source"
UPDATED_KEY = "Price Updated"
AUTO_SOURCES = ("JLCPCB", "LCSC")
STALE_AFTER_DAYS = 30


def _get_prop(comp: dict, key: str) -> str | None:
    for p in comp.get("properties", []) or []:
        if p.get("key") == key:
            v = p.get("value")
            return None if v is None else str(v)
    return None


def _set_prop(comp: dict, key: str, value: str) -> None:
    props = comp.setdefault("properties", [])
    for p in props:
        if p.get("key") == key:
            p["value"] = dq(value)
            return
    props.append({"key": key, "value": dq(value)})


def _is_stale(updated: str | None, today: _dt.date) -> bool:
    if not updated:
        return True
    try:
        d = _dt.date.fromisoformat(updated.strip())
    except ValueError:
        return True
    return (today - d).days >= STALE_AFTER_DAYS


def _price_at(ladder: list[dict], qty: int) -> tuple[int, float] | tuple[None, None]:
    best: tuple[int, float] | tuple[None, None] = (None, None)
    for tier in sorted(ladder, key=lambda t: t["ladder"]):
        if tier["ladder"] <= qty:
            best = (int(tier["ladder"]), float(tier["usdPrice"]))
    if best == (None, None) and ladder:
        t = ladder[0]
        return int(t["ladder"]), float(t["usdPrice"])
    return best


def _fetch_ladder(lcsc: str) -> list[dict] | None:
    req = urllib.request.Request(
        config.LCSC_API_URL.format(lcsc), headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e:
        log.warning(f"  ! LCSC fetch failed for {lcsc}: {e}")
        return None
    result = data.get("result") or {}
    ladder = result.get("productPriceList") or []
    return ladder or None


def _compute_prices(ladder: list[dict]) -> dict[str, str]:
    ladder_qtys = {int(t["ladder"]) for t in ladder}
    bulk_target = 1000 if any(q <= 1000 for q in ladder_qtys) else 5000
    _, p1 = _price_at(ladder, 1)
    _, p100 = _price_at(ladder, 100)
    bulk_q, p_bulk = _price_at(ladder, bulk_target)
    out: dict[str, str] = {}
    if p1 is not None:
        out["Price @1 USD"] = f"{p1:.4f}"
    if p100 is not None:
        out["Price @100 USD"] = f"{p100:.4f}"
    if p_bulk is not None:
        out["Price @Bulk USD"] = f"{p_bulk:.4f}"
        out["Price Bulk Qty"] = str(bulk_q)
    return out


def _auto_priced(comp: dict) -> str | None:
    """The component's LCSC id when its prices are robot-managed (source
    blank or an AUTO_SOURCES value); None when manual or LCSC-less."""
    lcsc = _get_prop(comp, "LCSC Part")
    if not lcsc or not lcsc.startswith("C"):
        return None
    source = _get_prop(comp, SOURCE_KEY)
    if source and source.strip() not in AUTO_SOURCES:
        return None
    return lcsc


def refresh_prices(sources_dir: str | Path = config.SOURCES_DIR) -> int:
    """Refresh stale supplier prices (JLCPCB first, LCSC fallback) across
    all YAML sources.

    Returns the number of components updated.
    """
    today = _dt.date.today()
    updated_count = 0
    skipped_manual = 0
    skipped_fresh = 0
    skipped_no_lcsc = 0
    skipped_no_data = 0

    files = sorted(Path(sources_dir).glob("*.yaml"))

    # One batched JLC call for every robot-priced component up front — cheap
    # (20 codes/request), and needed before the staleness check so fresh
    # LCSC-sourced entries can still upgrade to JLCPCB pricing.
    all_codes: list[str] = []
    for yml in files:
        _, data = load_roundtrip(yml)
        for comp in data.get("components", []) or []:
            code = _auto_priced(comp)
            if code:
                all_codes.append(code)
    jlc_rows = jlc.fetch_component_details(all_codes)

    for yml in files:
        ryaml, data = load_roundtrip(yml)
        file_modified = False
        for comp in data.get("components", []) or []:
            lcsc = _get_prop(comp, "LCSC Part")
            if not lcsc or not lcsc.startswith("C"):
                skipped_no_lcsc += 1
                continue

            source = _get_prop(comp, SOURCE_KEY)
            if source and source.strip() not in AUTO_SOURCES:
                skipped_manual += 1
                continue

            jlc_ladder = jlc.tiers(jlc_rows.get(lcsc))
            upgrade = bool(jlc_ladder) and (source or "").strip() == "LCSC"
            if not upgrade and not _is_stale(_get_prop(comp, UPDATED_KEY), today):
                skipped_fresh += 1
                continue

            # JLCPCB is the default price source; LCSC only when JLC has no ladder
            new_source = "JLCPCB" if jlc_ladder else "LCSC"
            ladder = jlc_ladder or _fetch_ladder(lcsc)
            if not ladder:
                skipped_no_data += 1
                continue

            prices = _compute_prices(ladder)
            if not prices:
                skipped_no_data += 1
                continue

            for k, v in prices.items():
                _set_prop(comp, k, v)
            _set_prop(comp, SOURCE_KEY, new_source)
            _set_prop(comp, UPDATED_KEY, today.isoformat())
            file_modified = True
            updated_count += 1
            log.info(f"  $ {lcsc} ({comp.get('name')}) [{new_source}]: @1={prices.get('Price @1 USD')} @100={prices.get('Price @100 USD')} @bulk={prices.get('Price @Bulk USD')}")

        if file_modified:
            save_roundtrip(ryaml, data, yml)

    log.debug(
        f"  prices: updated={updated_count} fresh={skipped_fresh} "
        f"manual={skipped_manual} no_lcsc={skipped_no_lcsc} no_data={skipped_no_data}"
    )
    return updated_count
