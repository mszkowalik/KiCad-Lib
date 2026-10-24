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
# Tasmota repeats every command it is given as "CMD: <command>", with the
# device time in front when the log carries it.
_ECHO = re.compile(r"^(?:\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?\s+)?CMD:\s")


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


def is_echo(line: str) -> bool:
    """The device repeating the command it was sent — never its reply.

    `parse_line` takes the text after the first '=' of a line that is not
    JSON, and `matches` accepts the key as a substring of it. An echo is the
    command itself, so a command with an '=' in it matched its own key: run
    8980 (2026-10-24) sent a `Br` whose text after the first '=' held
    `SOLIS_HYBRID.json`, "hy-BR-id" matched `Br` 0.06 s after the command, and
    the size check read `None`.
    """
    return bool(_ECHO.match(line))


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
