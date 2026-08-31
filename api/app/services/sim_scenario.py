"""What a harness sheet is asking for, read off the sheet.

A simulation harness carries its scenario as TEXT ITEMS beside the circuit
(`conventions-simulation`): a `.control` block that drives the run and prints
a verdict, an analysis line, a stimulus block of sources, and prose that
documents the lot. `EVSE_20_CTRL` has six such harnesses and every one is
written this way.

Read as a flat list of text, that is a wall nobody can act on. Classified, it
is a menu: these are the runs this sheet offers, this is the analysis, and
this is the stimulus behind them.

Nothing here rewrites a harness. It reads what is there and names it.
"""
from __future__ import annotations

import re

# An analysis line is a directive ngspice runs; everything else beginning with
# a dot is a setting, a model or a parameter.
_ANALYSIS = ("tran", "ac", "dc", "op", "noise", "disto", "pz", "sens", "tf", "four")
_ANALYSIS_RE = re.compile(r"^\s*\.(" + "|".join(_ANALYSIS) + r")\b", re.I)
_CONTROL_RE = re.compile(r"^\s*\.control\b", re.I)
_ECHO_RE = re.compile(r'^\s*echo\s+"(.*)"\s*$')
# `=====  TITLE  =====` and `-- A. section ----` are how these blocks are
# written; the padding is decoration, the words are the name.
_TRIM = re.compile(r"^[\s=\-*_]+|[\s=\-*_]+$")


def _title(text: str, fallback: str) -> str:
    """The name a `.control` block gives itself — its first printed line."""
    for line in text.splitlines():
        hit = _ECHO_RE.match(line)
        if not hit:
            continue
        name = _TRIM.sub("", hit.group(1)).strip()
        if name:
            return name[:80]
    return fallback


def classify(texts: list[dict]) -> dict:
    """Sheet text items -> what each one is.

    `texts` are `sim_geom`'s: `{"at", "text", "directive"}`. A directive is one
    the netlister will emit; prose is excluded from the netlist or does not
    start with a dot.
    """
    scenarios: list[dict] = []
    analyses: list[dict] = []
    stimulus: list[dict] = []
    notes: list[dict] = []

    for i, item in enumerate(texts):
        body = str(item.get("text") or "")
        entry = {"id": f"t{i}", "text": body, "at": item.get("at") or [0, 0]}
        if not item.get("directive"):
            if body.strip():
                notes.append({**entry, "kind": "note", "title": _first_line(body)})
            continue
        if _CONTROL_RE.search(body) or "\n.control" in body:
            scenarios.append({
                **entry, "kind": "control",
                "title": _title(body, f"scenario {len(scenarios) + 1}"),
                "checks": len(re.findall(r'echo\s+"(?:PASS|FAIL)\b', body)),
            })
        elif _ANALYSIS_RE.match(body) and "\n" not in body.strip():
            analyses.append({**entry, "kind": "analysis", "title": body.strip()})
        else:
            stimulus.append({**entry, "kind": "stimulus",
                             "title": _first_line(body)})
    return {"scenarios": scenarios, "analyses": analyses,
            "stimulus": stimulus, "notes": notes}


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = _TRIM.sub("", line).strip()
        if stripped:
            return stripped[:80]
    return "stimulus"


# The verdict table a harness prints is read in the BROWSER
# (`web/src/sim/scenario.ts`), not here: it is parsed out of the run's own log,
# which the browser already has, and a second copy on this side would be a
# second thing to keep in step with the convention.

# ------------------------------------------------------------------ analysis

# The run panel, in the same shape the component inspector uses: a form per
# kind of analysis, a row per number. Someone who knows SPICE types the line;
# someone who does not picks "Transient" and fills in two boxes, and gets the
# same line.

def _a(key: str, label: str, unit: str, default: str, scale: str = "log",
       options: list[str] | None = None) -> dict:
    field = {"key": key, "label": label, "unit": unit, "default": default,
             "scale": scale, "min": 0.0, "max": 0.0, "live": False}
    if options:
        field["options"] = options
    return field


ANALYSIS_FORMS: list[dict] = [
    {"id": "tran", "label": "Transient", "target": "value",
     "template": ".tran {step} {stop}",
     "fields": [_a("step", "Time step", "s", "10u"),
                _a("stop", "Stop time", "s", "5m")]},
    {"id": "ac", "label": "AC sweep", "target": "value",
     "template": ".ac {sweep} {points} {start} {stop}",
     "fields": [_a("sweep", "Sweep", "", "dec", "choice", ["dec", "oct", "lin"]),
                _a("points", "Points per decade", "", "20", "linear"),
                _a("start", "From", "Hz", "1"),
                _a("stop", "To", "Hz", "1meg")]},
    {"id": "dc", "label": "DC sweep", "target": "value",
     "template": ".dc {src} {start} {stop} {step}",
     "fields": [_a("src", "Source", "", "V1", "text"),
                _a("start", "From", "V", "0", "linear"),
                _a("stop", "To", "V", "5", "linear"),
                _a("step", "Step", "V", "0.1", "linear")]},
    {"id": "op", "label": "Operating point", "target": "value",
     "template": ".op", "fields": []},
    {"id": "raw", "label": "SPICE", "target": "value", "template": "{raw}",
     "fields": [_a("raw", "Directive", "", ".tran 10u 5m", "text")]},
]
