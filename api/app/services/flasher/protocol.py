"""Tasmota console line handling.

Ports the parsing from the old tool's serial_device.py (verified against real
recorded output in clients/flasher-poc/test_sim.mjs): a line is either whole
JSON, or Tasmota's log format "12:34:56 RSL: RESULT = {...}" where the payload
follows the first '='. Key matching is case-insensitive substring, same as
`is_expected_response` — Tasmota echoes "SSId1" for command "SSID1".
"""
from __future__ import annotations

import json
import re
from typing import Any

_EQ = re.compile(r"=(.*)")
# Device-side timestamp at the start of a log line ("00:00:04.248 ..."), kept
# on the stored log row because it survives server clock skew.
_DEVICE_TS = re.compile(r"^(\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?)\s")


def parse_line(line: str) -> Any:
    """JSON of the whole line, else JSON/string after the first '=', else None."""
    try:
        return json.loads(line)
    except (json.JSONDecodeError, ValueError):
        pass
    m = _EQ.search(line)
    if m:
        body = m.group(1).strip()
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return body
    return None


def matches(parsed: Any, key: str) -> bool:
    k = key.lower()
    if isinstance(parsed, dict):
        return any(k in x.lower() for x in parsed)
    if isinstance(parsed, str):
        return k in parsed.lower()
    return False


def device_ts(line: str) -> str:
    m = _DEVICE_TS.match(line)
    return m.group(1) if m else ""


def dig(obj: Any, path: str) -> Any:
    """Case-insensitive dotted-path lookup ("StatusFWR.Version")."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        hit = next((k for k in cur if k.lower() == part.lower()), None)
        if hit is None:
            return None
        cur = cur[hit]
    return cur


def subst(value: Any, params: dict[str, Any]) -> Any:
    """Interpolate {placeholders}; non-strings pass through untouched."""
    if not isinstance(value, str):
        return value
    return re.sub(r"\{(\w+)\}", lambda m: str(params.get(m.group(1), m.group(0))), value)
