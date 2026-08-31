"""The circuit the simulator opens when there is nothing to open yet.

An empty sheet is a bad first screen: it teaches nothing, and the parts that
need a model (`sigma_opamp`, `sigma_rail_inv`, `sigma_rail_and4`,
`sigma_rail_dff_sr`) are
exactly the ones a person will not guess how to wire. So this builds one
worked sheet out of the palette, with every block a drawn symbol — no hidden
`X` lines, as `conventions-simulation` requires of a harness.

It is an ordinary sketch document. Opening it saves it like any other, so the
user edits and re-runs it without leaving the page, and nothing here is a
special case downstream.

Four blocks, left to right, top to bottom:

1. Supplies. +5 V and -5 V against ground, as `VCC` and `VEE` rails.
2. An amplifier. `sigma_opamp` in the non-inverting form, gain 1 + R2/R1 = 11,
   driven by a 100 mV 1 kHz sine.
3. A clock chain. `sigma_rail_inv` inverts a 1 kHz square wave, a second one
   inverts it back — two inverters in series ARE the buffer, and drawing them
   says so — and the buffered clock drives a `sigma_rail_dff_sr` wired D from
   QN, which divides it by two. Its active-low PRESET and CLEAR sit on VCC,
   drawn rather than assumed, because the model declares them and every port
   a model declares has to be claimed by a pin.
4. A gate. `sigma_rail_and4` ANDs the buffered clock with Q, with its two
   spare inputs tied to the rail where a reader can see them.

The logic here is the RAIL-FOLLOWING family: it takes its supply from its vcc
and vee pins and has no VDD parameter. That is why the rails are drawn.

Geometry rule: every coordinate is a multiple of 1.27 mm. A pin off the grid
does not connect, and nothing says so.
"""
from __future__ import annotations

import uuid as uuidlib

G = 1.27


def _u() -> str:
    return str(uuidlib.uuid4())


_POWER = 0


def _pwr(lib_id: str, x: float, y: float, value: str = "", angle: float = 0) -> dict:
    """A power flag. It needs a reference too: the writer falls back to `U?`
    without one, and KiCad then netlists the flag as a device — `U? __U?`,
    one per flag, and the deck does not load."""
    global _POWER
    _POWER += 1
    return _sym(lib_id, x, y, f"#PWR{_POWER:02d}", value, angle)


def _sym(lib_id: str, x: float, y: float, ref: str = "", value: str = "",
         angle: float = 0, **fields) -> dict:
    f: dict[str, str] = {}
    if ref:
        f["Reference"] = ref
    if value:
        f["Value"] = value
    f.update({k.replace("__", "."): v for k, v in fields.items()})
    return {"id": _u(), "lib_id": lib_id, "at": [x, y, angle], "mirror": "",
            "unit": 1, "fields": f}


def _wire(*pts: tuple[float, float]) -> dict:
    return {"id": _u(), "pts": [[p[0], p[1]] for p in pts]}


def _label(text: str, x: float, y: float, angle: float = 0) -> dict:
    return {"id": _u(), "text": text, "at": [x, y, angle], "kind": "local"}


def _text(text: str, x: float, y: float, *, excluded: bool = False, h: float = 1.27) -> dict:
    return {"id": _u(), "at": [x, y, 0], "text": text, "h": h, "excluded": excluded}


# The analysis is a SHEET directive and the harness says `run`, rather than the
# harness saying `tran` itself. That is the difference between a run that
# returns verdicts alone and one that returns verdicts AND waveforms: ngspice
# writes the rawfile it was given for a DECK analysis, and writes nothing at
# all when the analysis happens inside the control block (measured 2026-08-30).
# `run` also picks up whatever analysis the Scenario panel injects, so the
# checks still run when the user asks for a different sweep.
_ANALYSIS = ".tran 5u 5m"

# Net names carry the leading slash KiCad gives a local label. `VCC` and `VEE`
# are power nets and carry none.
_CONTROL = "\n".join([
    ".control",
    'echo "Amplifier, buffer, gate and flip-flop"',
    "run",
    'echo "-- A. THE AMPLIFIER ----"',
    "let gain = (vecmax(v(/ampout)) - vecmin(v(/ampout))) / "
    "(vecmax(v(/in)) - vecmin(v(/in)))",
    "if gain > 10.4 and gain < 11.6",
    '  echo "PASS  A1  closed-loop gain is 1 + R2/R1"',
    "else",
    '  echo "FAIL  A1  closed-loop gain is off"',
    "end",
    'echo "-- B. THE LOGIC ----"',
    "let swing = vecmax(v(/bclk)) - vecmin(v(/bclk))",
    "if swing > 4.5",
    '  echo "PASS  B1  two inverters buffer the clock full swing"',
    "else",
    '  echo "FAIL  B1  buffered clock does not reach the rails"',
    "end",
    "let qbar = vecmax(v(/q)) - vecmin(v(/q))",
    "if qbar > 4.5",
    '  echo "PASS  B2  the flip-flop toggles"',
    "else",
    '  echo "FAIL  B2  the flip-flop never toggles"',
    "end",
    "let gated = vecmax(v(/gated))",
    "if gated > 4.5",
    '  echo "PASS  B3  the gate passes the clock while Q is high"',
    "else",
    '  echo "FAIL  B3  the gate never opens"',
    "end",
    ".endc",
])


def document() -> dict:
    """The example as an editor document, ready to save as a sketch."""
    global _POWER
    _POWER = 0
    symbols: list[dict] = []
    wires: list[dict] = []
    labels: list[dict] = []

    # ------------------------------------------------------------ supplies
    symbols += [
        _sym("Simulator:V", 25.4, 50.8, "V2", "DC 5"),
        _pwr("Simulator:VRAIL", 25.4, 43.18, value="VCC"),
        _pwr("Simulator:GND", 25.4, 58.42),
        _sym("Simulator:V", 25.4, 76.2, "V3", "DC -5"),
        _pwr("Simulator:VRAIL", 25.4, 68.58, value="VEE"),
        _pwr("Simulator:GND", 25.4, 83.82),
    ]
    wires += [
        _wire((25.4, 45.72), (25.4, 43.18)),
        _wire((25.4, 55.88), (25.4, 58.42)),
        _wire((25.4, 71.12), (25.4, 68.58)),
        _wire((25.4, 81.28), (25.4, 83.82)),
    ]

    # ----------------------------------------------------------- amplifier
    symbols += [
        _sym("Simulator:V", 38.1, 63.5, "V1", "SIN(0 0.1 1k)"),
        _pwr("Simulator:GND", 38.1, 72.39),
        _sym("Simulator:OPAMP", 76.2, 55.88, "U1", "OPAMP"),
        _pwr("Simulator:VRAIL", 76.2, 48.26, value="VCC"),
        _pwr("Simulator:VRAIL", 76.2, 63.5, value="VEE", angle=180),
        _sym("Simulator:R", 60.96, 66.04, "R1", "1k"),
        _pwr("Simulator:GND", 60.96, 73.66),
        _sym("Simulator:R", 74.93, 80.01, "R2", "10k", angle=90),
    ]
    wires += [
        _wire((38.1, 68.58), (38.1, 72.39)),
        _wire((38.1, 58.42), (38.1, 53.34), (68.58, 53.34)),
        _wire((68.58, 58.42), (50.8, 58.42)),
        _wire((60.96, 58.42), (60.96, 62.23)),
        _wire((60.96, 69.85), (60.96, 73.66)),
        _wire((83.82, 55.88), (91.44, 55.88), (91.44, 80.01), (78.74, 80.01)),
        _wire((71.12, 80.01), (50.8, 80.01), (50.8, 58.42)),
    ]
    labels += [_label("IN", 46.99, 53.34), _label("AMPOUT", 86.36, 55.88)]

    # --------------------------------------------------------- clock chain
    symbols += [
        _sym("Simulator:V", 38.1, 127, "V4", "PULSE(0 5 0 100n 100n 500u 1m)"),
        _pwr("Simulator:GND", 38.1, 135.89),
        _sym("Simulator:INV", 69.85, 121.92, "U2", "INV"),
        _pwr("Simulator:VRAIL", 69.85, 115.57, value="VCC"),
        _pwr("Simulator:GND", 69.85, 128.27),
        _sym("Simulator:INV", 97.79, 121.92, "U3", "INV"),
        _pwr("Simulator:VRAIL", 97.79, 115.57, value="VCC"),
        _pwr("Simulator:GND", 97.79, 128.27),
        _sym("Simulator:DFF", 135.89, 121.92, "U4", "DFF"),
        _pwr("Simulator:VRAIL", 135.89, 111.76, value="VCC"),
        _pwr("Simulator:GND", 135.89, 132.08),
        # PREN and CLRN are ACTIVE LOW, so idle is the rail. They are wired
        # short and outward, clear of the D-from-QN loop that runs up x=120.65.
        _pwr("Simulator:VRAIL", 123.19, 116.84, value="VCC"),
        _pwr("Simulator:VRAIL", 123.19, 127.0, value="VCC", angle=180),
    ]
    wires += [
        _wire((38.1, 132.08), (38.1, 135.89)),
        _wire((38.1, 121.92), (63.5, 121.92)),
        _wire((77.47, 121.92), (91.44, 121.92)),
        _wire((105.41, 121.92), (114.3, 121.92), (114.3, 124.46), (128.27, 124.46)),
        _wire((143.51, 119.38), (153.67, 119.38)),
        # D from QN — the divide-by-two. It goes right, over the top and back,
        # so it crosses nothing: a wire that crosses another is a wire someone
        # will read as a connection.
        _wire((143.51, 124.46), (160.02, 124.46), (160.02, 104.14),
              (120.65, 104.14), (120.65, 119.38), (128.27, 119.38)),
        _wire((128.27, 116.84), (123.19, 116.84)),
        _wire((128.27, 127.0), (123.19, 127.0)),
    ]
    labels += [
        _label("CLK", 46.99, 121.92),
        _label("NCLK", 82.55, 121.92),
        _label("BCLK", 109.22, 121.92),
        _label("Q", 148.59, 119.38),
    ]

    # ---------------------------------------------------------------- gate
    symbols += [
        _sym("Simulator:AND", 114.3, 165.1, "U5", "AND4"),
        _pwr("Simulator:VRAIL", 114.3, 154.94, value="VCC"),
        _pwr("Simulator:GND", 114.3, 175.26),
        _pwr("Simulator:VRAIL", 99.06, 156.21, value="VCC"),
    ]
    wires += [
        _wire((106.68, 160.02), (99.06, 160.02)),
        _wire((106.68, 162.56), (99.06, 162.56)),
        _wire((99.06, 160.02), (99.06, 162.56)),
        _wire((99.06, 160.02), (99.06, 156.21)),
        _wire((106.68, 165.1), (96.52, 165.1)),
        _wire((106.68, 167.64), (96.52, 167.64)),
        _wire((121.92, 162.56), (133.35, 162.56)),
    ]
    labels += [
        _label("BCLK", 99.06, 165.1),
        _label("Q", 99.06, 167.64),
        _label("GATED", 127, 162.56),
    ]

    texts = [
        _text(
            "Amplifier, buffer, gate and flip-flop.\n"
            "U1 is a non-inverting amplifier: gain = 1 + R2/R1 = 11.\n"
            "U2 and U3 are two inverters in series, which is a buffer.\n"
            "U4 divides the buffered clock by two (D from QN).\n"
            "Its PRESET and CLEAR are active low and sit on VCC.\n"
            "U5 ANDs the buffered clock with Q. Its spare inputs sit on VCC.\n"
            "Run it, then probe /AMPOUT, /BCLK, /Q and /GATED.",
            25.4, 20.32, excluded=True, h=1.778),
        _text(_ANALYSIS, 25.4, 187.96),
        _text(_CONTROL, 25.4, 193.04),
    ]

    return {
        "name": "example",
        "uuid": _u(),
        "paper": "A3",
        "symbols": symbols,
        "wires": wires,
        "labels": labels,
        "texts": texts,
        # Where three wire ends meet. The browser recomputes these while
        # drawing; a document built here has to state them.
        "junctions": [[60.96, 58.42], [99.06, 160.02]],
    }
