"""The parts an in-browser schematic starts with.

A schematic drawn from scratch cannot begin at the catalogue: a resistor, a
supply and a switch have to be there before there is anything to look a
catalogue part up for. This module holds those primitives as real KiCad symbol
definitions, in the same s-expression the library format uses, for one reason
above all others — **the file the browser saves has to open in KiCad**. A
made-up shape would draw here and be missing there.

Every definition is written to netlist the way SPICE expects with no model at
all: R, L, C and the power symbols are what `conventions-simulation` calls the
parts KiCad builds from the Value field, and `V`/`I` are SPICE primitives. So a
circuit drawn from these simulates immediately, and nothing here needs a
`Sim.Device` row.

The Value field is the SPICE value, verbatim. `10k` on a resistor, `PULSE(0 5
0 1u 1u 1m 2m)` on a source — that is the netlist, so the editor's value box
is a SPICE value box and needs no translation layer.
"""
from __future__ import annotations

from ..util.sexpr import parse_sexpr, sanitize_symbol_text
from . import pcm, sch_draw

_FONT = '(effects (font (size 1.27 1.27)))'


def _pin(kind: str, x: float, y: float, angle: float, length: float, number: str, name: str = "") -> str:
    # An EMPTY name, not the "~" KiCad's own libraries write. A definition
    # embedded in a `.kicad_sch` does not get "~" folded away the way one
    # loaded from a `.kicad_sym` does, and the tilde then turns up inside every
    # generated net name: `Net-(R1-~-Pad1)` instead of `Net-(R1-Pad1)`.
    return (
        f'(pin {kind} line (at {x} {y} {angle}) (length {length}) '
        f'(name "{name}" {_FONT}) (number "{number}" {_FONT}))'
    )


def _stroke(width: float = 0.254, fill: str = "none") -> str:
    return f'(stroke (width {width}) (type default)) (fill (type {fill}))'


# A two-pin part drawn vertically, pin 1 at the top. Same convention KiCad's
# own Device library uses, so a schematic drawn here reads like any other.
_R_BODY = f'(rectangle (start -1.016 -2.54) (end 1.016 2.54) {_stroke()})'
_C_BODY = (
    f'(polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762)) {_stroke(0.508)})'
    f'(polyline (pts (xy -2.032 0.762) (xy 2.032 0.762)) {_stroke(0.508)})'
)
_L_BODY = "".join(
    f'(arc (start 0 {a}) (mid {0.6323} {a - 0.635}) (end 0 {a - 1.27}) {_stroke()})'
    for a in (2.54, 1.27, 0.0, -1.27)
)
_D_BODY = (
    f'(polyline (pts (xy -1.27 1.27) (xy -1.27 -1.27)) {_stroke()})'
    f'(polyline (pts (xy 1.27 1.27) (xy -1.27 0) (xy 1.27 -1.27) (xy 1.27 1.27)) {_stroke(0.254, "outline")})'
)
_V_BODY = (
    f'(circle (center 0 0) (radius 2.54) {_stroke()})'
    f'(polyline (pts (xy -0.762 1.27) (xy 0.762 1.27)) {_stroke()})'
    f'(polyline (pts (xy 0 0.508) (xy 0 2.032)) {_stroke()})'
    f'(polyline (pts (xy -0.762 -1.27) (xy 0.762 -1.27)) {_stroke()})'
)
_I_BODY = (
    f'(circle (center 0 0) (radius 2.54) {_stroke()})'
    f'(polyline (pts (xy 0 -1.524) (xy 0 1.524)) {_stroke()})'
    f'(polyline (pts (xy -0.635 0.762) (xy 0 1.524) (xy 0.635 0.762)) {_stroke()})'
)
_SW_BODY = (
    f'(circle (center -2.032 0) (radius 0.508) {_stroke(0.254, "outline")})'
    f'(circle (center 2.032 0) (radius 0.508) {_stroke(0.254, "outline")})'
    f'(polyline (pts (xy -1.524 0.254) (xy 1.778 1.524)) {_stroke()})'
)
# Open and closed as resistances, not as a model: big enough to be an open
# circuit, small enough to be a wire, and both far from any value a user would
# type, so a glance at the netlist says which state it is in.
SWITCH_OPEN_R = "1G"
SWITCH_CLOSED_R = "10m"

# A small-signal silicon diode, the shape of a 1N4148. Every number is a
# STARTING POINT a user is expected to change for the part in front of them —
# `conventions-simulation` is explicit that a default nobody has checked is
# fine and a default nobody knows is unchecked is not, so the inspector shows
# them all rather than burying them.
DIODE_PARAMS = "IS=2.5n RS=0.6 N=1.9 CJO=4p BV=100"


def _sim_fields(device: str, params: str) -> str:
    """Hidden `Sim.*` properties. They decide what the netlister makes of the
    part, and nobody wants them printed on the drawing."""
    hidden = '(show_name no) (do_not_autoplace no) (hide yes) ' + _FONT
    return (f'(property "Sim.Device" "{device}" (at 0 0 0) {hidden})'
            f'(property "Sim.Params" "{params}" (at 0 0 0) {hidden})')


_SW_CLOSED_BODY = (
    f'(circle (center -2.032 0) (radius 0.508) {_stroke(0.254, "outline")})'
    f'(circle (center 2.032 0) (radius 0.508) {_stroke(0.254, "outline")})'
    f'(polyline (pts (xy -1.524 0) (xy 1.524 0)) {_stroke()})'
)


def _two_pin(lib_id: str, ref: str, value: str, body: str, *, vertical: bool = True,
             reach: float = 3.81, stub: float = 1.27, kind: str = "passive",
             field_off: float = 2.54, extra: str = "") -> str:
    # A `.kicad_sch` names each embedded definition by its FULL library id and
    # its unit sub-symbols by the bare name. Getting that pair wrong is not a
    # cosmetic difference: eeschema fails to load the file outright, because
    # no definition answers the placement's lib_id.
    name = lib_id.split(":", 1)[1]
    if vertical:
        pins = _pin(kind, 0, reach, 270, stub, "1") + _pin(kind, 0, -reach, 90, stub, "2")
        at_ref, at_val = f"(at {field_off} 0 90)", f"(at {-field_off} 0 90)"
    else:
        pins = _pin(kind, -reach, 0, 0, stub, "1") + _pin(kind, reach, 0, 180, stub, "2")
        at_ref, at_val = f"(at 0 {field_off} 0)", f"(at 0 {-field_off} 0)"
    return f'''(symbol "{lib_id}"
  (pin_numbers (hide yes)) (pin_names (offset 0) (hide yes))
  (exclude_from_sim no) (in_bom yes) (on_board yes)
  (property "Reference" "{ref}" {at_ref} (show_name no) (do_not_autoplace no) {_FONT})
  (property "Value" "{value}" {at_val} (show_name no) (do_not_autoplace no) {_FONT})
  {extra}
  (symbol "{name}_0_1" {body})
  (symbol "{name}_1_1" {pins})
)'''


def _power(lib_id: str, value: str, body: str, angle: float) -> str:
    """A power symbol is a NET NAME, not a device: its Value is the net and its
    single pin is hidden. Ground's value is literally `0`, which is the node
    ngspice already treats as ground — an explicit source to it would be a
    short (see `conventions-simulation`)."""
    name = lib_id.split(":", 1)[1]
    return f'''(symbol "{lib_id}"
  (power global) (pin_numbers (hide yes)) (pin_names (offset 0) (hide yes))
  (exclude_from_sim no) (in_bom no) (on_board yes)
  (property "Reference" "#PWR" (at 0 -3.81 0) (show_name no) (do_not_autoplace no) (hide yes) {_FONT})
  (property "Value" "{value}" (at 0 {3.556 if angle == 90 else -3.81} 0) (show_name no) (do_not_autoplace no) {_FONT})
  (symbol "{name}_0_1" {body})
  (symbol "{name}_1_1" {_pin("power_in", 0, 0, angle, 0, "1", value)})
)'''


_GND_BODY = (
    f'(polyline (pts (xy 0 0) (xy 0 -1.27)) {_stroke()})'
    f'(polyline (pts (xy -1.27 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27)) {_stroke()})'
)
_RAIL_BODY = (
    f'(polyline (pts (xy 0 0) (xy 0 1.27)) {_stroke()})'
    f'(polyline (pts (xy -0.762 1.27) (xy 0 2.54) (xy 0.762 1.27)) {_stroke()})'
)

# --------------------------------------------------- parts that need a model
#
# R, C, L, V, I and the diode netlist with nothing behind them. An amplifier
# or a flip-flop does not: it is a `.subckt`, and the library already holds
# the ones below (`sigma_opamp`, `sigma_inv`, `sigma_and4`, `sigma_dff` —
# `conventions-simulation`: reference only OUR models, never a KiCad install
# file). So these primitives carry the four link fields the mirror puts on a
# catalogue part, pointed at the same file.
#
# The path is the PCM-INSTALLED one, not the mirror's `${SEVENSIGMA_DIR}`
# form. Both resolve on the server, but only this one also resolves in the
# user's own KiCad after they install the library package — and a sheet drawn
# here is meant to be opened there.


def _model_fields(model: str, pins: str, params: str) -> str:
    hidden = '(show_name no) (do_not_autoplace no) (hide yes) ' + _FONT
    rows = [("Sim.Device", "SUBCKT"), ("Sim.Name", model),
            ("Sim.Library", pcm.SIM_LIB_INSTALLED), ("Sim.Pins", pins),
            ("Sim.Params", params)]
    return "".join(f'(property "{k}" "{v}" (at 0 0 0) {hidden})' for k, v in rows)


def _ic(lib_id: str, ref: str, value: str, body: str, pins: list[tuple],
        *, model: str, params: str, field_x: float, field_y: float,
        names_hidden: bool = False) -> str:
    """A multi-pin primitive. `pins` is (number, name, x, y, angle, length) in
    pin order, and that order IS the subcircuit's port order, so `Sim.Pins`
    is derived from it and cannot drift from the drawing.

    `field_x`/`field_y` put the reference and the value BESIDE the body, not
    above and below it: the supply pins come out of the top and bottom edges,
    and a reference printed there lands on the pin."""
    name = lib_id.split(":", 1)[1]
    sim_pins = " ".join(f"{n}={p}" for n, p, *_ in pins)
    pin_defs = "".join(
        _pin("passive" if p in ("vcc", "vee") else "input" if p in ("in", "in+", "in-", "clk", "d", "a", "b", "c") else "output",
             x, y, ang, ln, n, p.upper())
        for n, p, x, y, ang, ln in pins
    )
    return f'''(symbol "{lib_id}"
  (pin_numbers (hide yes)) (pin_names (offset 0.508){" (hide yes)" if names_hidden else ""})
  (exclude_from_sim no) (in_bom yes) (on_board yes)
  (property "Reference" "{ref}" (at {_num(field_x)} {_num(field_y)} 0) (show_name no) (do_not_autoplace no) {_FONT})
  (property "Value" "{value}" (at {_num(field_x)} {_num(-field_y)} 0) (show_name no) (do_not_autoplace no) {_FONT})
  {_model_fields(model, sim_pins, params)}
  (symbol "{name}_0_1" {body})
  (symbol "{name}_1_1" {pin_defs})
)'''


def _num(v: float) -> str:
    return f"{v:g}"


# An op-amp drawn the way every schematic draws one: a triangle, the inputs on
# the sloping side, the rails on the apexes above and below.
_OPAMP_BODY = (
    f'(polyline (pts (xy -5.08 5.08) (xy 5.08 0) (xy -5.08 -5.08) (xy -5.08 5.08)) {_stroke(0.254, "background")})'
    f'(polyline (pts (xy -4.318 2.54) (xy -3.048 2.54)) {_stroke()})'
    f'(polyline (pts (xy -3.683 1.905) (xy -3.683 3.175)) {_stroke()})'
    f'(polyline (pts (xy -4.318 -2.54) (xy -3.048 -2.54)) {_stroke()})'
)
_INV_BODY = (
    f'(polyline (pts (xy -3.81 3.81) (xy 3.81 0) (xy -3.81 -3.81) (xy -3.81 3.81)) {_stroke(0.254, "background")})'
    f'(circle (center 4.445 0) (radius 0.635) {_stroke()})'
)


def _box(half_w: float, half_h: float, letters: str = "") -> str:
    body = f'(rectangle (start {_num(-half_w)} {_num(half_h)}) (end {_num(half_w)} {_num(-half_h)}) {_stroke(0.254, "background")})'
    if letters:
        body += (f'(text "{letters}" (at 0 {_num(half_h - 2.54)} 0) {_FONT})')
    return body


_GATE_BODY = _box(5.08, 7.62, "&")
_DFF_BODY = _box(5.08, 7.62)


# lib_id -> the symbol definition, exactly as a `.kicad_sym` file writes it.
DEFINITIONS: dict[str, str] = {
    "Simulator:R": _two_pin("Simulator:R", "R", "10k", _R_BODY),
    "Simulator:C": _two_pin("Simulator:C", "C", "100n", _C_BODY, reach=3.81, stub=2.794, field_off=3.175),
    "Simulator:L": _two_pin("Simulator:L", "L", "10m", _L_BODY),
    # A diode needs `Sim.Device D`. Without it KiCad emits `D1 __D1` — the
    # reference, a model name, and NO NODES: the part vanishes from the
    # circuit and nothing says so. With it, KiCad writes a real `.model` from
    # the parameters and wires the diode in.
    "Simulator:D": _two_pin("Simulator:D", "D", "D", _D_BODY, vertical=False,
                            extra=_sim_fields("D", DIODE_PARAMS)),
    "Simulator:V": _two_pin("Simulator:V", "V", "DC 5", _V_BODY, reach=5.08, stub=2.54, field_off=3.81),
    "Simulator:I": _two_pin("Simulator:I", "I", "DC 1m", _I_BODY, reach=5.08, stub=2.54, field_off=3.81),
    "Simulator:SW": _two_pin(
        "Simulator:SW", "SW", "open", _SW_BODY, vertical=False, reach=5.08, stub=2.54,
        extra=_sim_fields("R", f"r={SWITCH_OPEN_R}")),
    "Simulator:SW_CLOSED": _two_pin(
        "Simulator:SW_CLOSED", "SW", "closed", _SW_CLOSED_BODY, vertical=False, reach=5.08,
        stub=2.54, extra=_sim_fields("R", f"r={SWITCH_CLOSED_R}")),
    # Everything below is a `.subckt` in the platform's own model library.
    # The pin ORDER is the port order of that subcircuit, and `Sim.Pins` is
    # built from it, so the map cannot drift from the picture.
    "Simulator:OPAMP": _ic(
        "Simulator:OPAMP", "U", "OPAMP", _OPAMP_BODY,
        [("1", "in+", -7.62, 2.54, 0, 2.54),
         ("2", "in-", -7.62, -2.54, 0, 2.54),
         ("3", "vcc", 0, 7.62, 270, 5.08),
         ("4", "vee", 0, -7.62, 90, 5.08),
         ("5", "out", 7.62, 0, 180, 2.54)],
        model="sigma_opamp", params="GAIN=100k POLE=20 VOFF=1m ROUT=50",
        field_x=8.89, field_y=6.35, names_hidden=True),
    "Simulator:INV": _ic(
        "Simulator:INV", "U", "INV", _INV_BODY,
        [("1", "in", -6.35, 0, 0, 2.54),
         ("2", "out", 7.62, 0, 180, 2.54),
         ("3", "vcc", 0, 6.35, 270, 4.445),
         ("4", "vee", 0, -6.35, 90, 4.445)],
        model="sigma_inv", params="VDD=5 TPLH=20n TPHL=15n ROUT=50",
        field_x=6.35, field_y=5.08, names_hidden=True),
    "Simulator:AND": _ic(
        "Simulator:AND", "U", "AND4", _GATE_BODY,
        [("1", "a", -7.62, 5.08, 0, 2.54),
         ("2", "b", -7.62, 2.54, 0, 2.54),
         ("3", "c", -7.62, 0, 0, 2.54),
         ("4", "d", -7.62, -2.54, 0, 2.54),
         ("5", "y", 7.62, 2.54, 180, 2.54),
         ("6", "vcc", 0, 10.16, 270, 2.54),
         ("7", "vee", 0, -10.16, 90, 2.54)],
        model="sigma_and4", params="VDD=5 TPD=20n ROUT=50", field_x=7.62, field_y=8.89),
    "Simulator:DFF": _ic(
        "Simulator:DFF", "U", "DFF", _DFF_BODY,
        [("1", "d", -7.62, 2.54, 0, 2.54),
         ("2", "clk", -7.62, -2.54, 0, 2.54),
         ("3", "q", 7.62, 2.54, 180, 2.54),
         ("4", "qn", 7.62, -2.54, 180, 2.54),
         ("5", "vcc", 0, 10.16, 270, 2.54),
         ("6", "vee", 0, -10.16, 90, 2.54)],
        model="sigma_dff", params="VDD=5 TPD=25n ROUT=50", field_x=8.89, field_y=8.89),
    "Simulator:GND": _power("Simulator:GND", "0", _GND_BODY, 270),
    "Simulator:VRAIL": _power("Simulator:VRAIL", "VCC", _RAIL_BODY, 90),
}

# What the palette shows, in the order it shows it. `sim` says how a live
# session can steer the part, which is what makes a switch clickable on the
# drawing rather than a row in a side panel.
PALETTE: list[dict] = [
    {"lib_id": "Simulator:R", "label": "Resistor", "key": "r", "prefix": "R",
     "value": "10k", "unit": "Ω", "sim": "passive"},
    {"lib_id": "Simulator:C", "label": "Capacitor", "key": "c", "prefix": "C",
     "value": "100n", "unit": "F", "sim": "passive"},
    {"lib_id": "Simulator:L", "label": "Inductor", "key": "l", "prefix": "L",
     "value": "10m", "unit": "H", "sim": "passive"},
    {"lib_id": "Simulator:D", "label": "Diode", "key": "d", "prefix": "D",
     "value": "D", "unit": "", "sim": "device"},
    {"lib_id": "Simulator:V", "label": "Voltage source", "key": "v", "prefix": "V",
     "value": "DC 5", "unit": "V", "sim": "source"},
    {"lib_id": "Simulator:I", "label": "Current source", "key": "i", "prefix": "I",
     "value": "DC 1m", "unit": "A", "sim": "source"},
    # No default value: a switch's Value is its STATE, and the state belongs
    # to the library definition it is drawn as. A value pinned at placement
    # time would still read "open" after the contact closed.
    {"lib_id": "Simulator:SW", "label": "Switch", "key": "s", "prefix": "SW",
     "value": "", "unit": "", "sim": "switch"},
    {"lib_id": "Simulator:OPAMP", "label": "Op-amp", "key": "o", "prefix": "U",
     "value": "OPAMP", "unit": "", "sim": "device"},
    {"lib_id": "Simulator:INV", "label": "Inverter", "key": "n", "prefix": "U",
     "value": "INV", "unit": "", "sim": "device"},
    {"lib_id": "Simulator:AND", "label": "AND gate", "key": "a", "prefix": "U",
     "value": "AND4", "unit": "", "sim": "device"},
    {"lib_id": "Simulator:DFF", "label": "D flip-flop", "key": "f", "prefix": "U",
     "value": "DFF", "unit": "", "sim": "device"},
    {"lib_id": "Simulator:GND", "label": "Ground", "key": "g", "prefix": "#PWR",
     "value": "0", "unit": "", "sim": "power"},
    {"lib_id": "Simulator:VRAIL", "label": "Power rail", "key": "p", "prefix": "#PWR",
     "value": "VCC", "unit": "", "sim": "power"},
]

# The switch is the one part whose PICTURE carries state. A live session flips
# it by resistance, and the drawing has to follow or the reading is a lie.
SWITCH_OPEN = "Simulator:SW"
SWITCH_CLOSED = "Simulator:SW_CLOSED"


# --------------------------------------------------------------- parameters

# What a part is ASKED for, rather than what SPICE wants typed. A voltage
# source is not a string — it is a choice of waveform and a few numbers, and
# `PULSE(0 5 0 1u 1u 1m 2m)` is the seven of them in an order nobody
# remembers. Each form carries a template; the browser fills it in and parses
# it back, so the Value field stays the SPICE value and nothing is translated
# behind the user's back.
#
# `target`:  "value"  the fields build the Value field
#            "params" each field is one `Sim.Params` key
# `live`:    the field can be steered by `alter` on a RUNNING transient.
#            A source with a waveform cannot (measured — ngspice accepts the
#            command and keeps the script), and neither can a `.model`
#            parameter; those are changed by editing and running again.

def _f(key: str, label: str, unit: str, default: str, *, scale: str = "log",
       lo: float = 0.0, hi: float = 0.0, live: bool = True) -> dict:
    return {"key": key, "label": label, "unit": unit, "default": default,
            "scale": scale, "min": lo, "max": hi, "live": live}


def _passive(label: str, unit: str, default: str, lo: float, hi: float) -> list[dict]:
    return [{
        "id": "value", "label": label, "target": "value", "template": "{v}",
        "fields": [_f("v", label, unit, default, lo=lo, hi=hi)],
    }]


def _source(unit: str, dc: str, amp: str) -> list[dict]:
    return [
        {"id": "dc", "label": "DC", "target": "value", "template": "DC {dc}",
         "fields": [_f("dc", "Value", unit, dc, scale="linear", lo=-100, hi=100)]},
        {"id": "sin", "label": "Sine", "target": "value",
         "template": "SIN({off} {amp} {freq})",
         "fields": [
             _f("off", "Offset", unit, "0", scale="linear", lo=-100, hi=100, live=False),
             _f("amp", "Amplitude", unit, amp, scale="linear", lo=0, hi=100, live=False),
             _f("freq", "Frequency", "Hz", "1k", lo=1e-3, hi=1e9, live=False),
         ]},
        {"id": "pulse", "label": "Pulse", "target": "value",
         "template": "PULSE({v1} {v2} {td} {tr} {tf} {tw} {per})",
         "fields": [
             _f("v1", "Low", unit, "0", scale="linear", lo=-100, hi=100, live=False),
             _f("v2", "High", unit, amp, scale="linear", lo=-100, hi=100, live=False),
             _f("td", "Delay", "s", "0", lo=0, hi=1, live=False),
             _f("tr", "Rise", "s", "1u", lo=1e-12, hi=1, live=False),
             _f("tf", "Fall", "s", "1u", lo=1e-12, hi=1, live=False),
             _f("tw", "Width", "s", "1m", lo=1e-12, hi=1000, live=False),
             _f("per", "Period", "s", "2m", lo=1e-12, hi=1000, live=False),
         ]},
        {"id": "raw", "label": "SPICE", "target": "value", "template": "{raw}",
         "fields": [_f("raw", "Value", "", dc, scale="text", live=False)]},
    ]


PARAM_FORMS: dict[str, list[dict]] = {
    "Simulator:R": _passive("Resistance", "Ω", "10k", 1e-3, 1e9),
    "Simulator:C": _passive("Capacitance", "F", "100n", 1e-15, 1.0),
    "Simulator:L": _passive("Inductance", "H", "10m", 1e-12, 1e3),
    "Simulator:V": _source("V", "5", "1"),
    "Simulator:I": _source("A", "1m", "1m"),
    # A diode is a `.model`, so every number is a `Sim.Params` key and none of
    # them can be altered on a running transient.
    "Simulator:D": [{
        "id": "model", "label": "Diode", "target": "params", "template": "",
        "fields": [
            _f("IS", "Saturation current", "A", "2.5n", lo=1e-18, hi=1e-3, live=False),
            _f("RS", "Series resistance", "Ω", "0.6", lo=1e-3, hi=1e3, live=False),
            _f("N", "Emission coefficient", "", "1.9", scale="linear", lo=1, hi=3, live=False),
            _f("CJO", "Junction capacitance", "F", "4p", lo=1e-15, hi=1e-6, live=False),
            _f("BV", "Reverse breakdown", "V", "100", lo=1, hi=2000, live=False),
        ],
    }],
    # A contact is its two resistances, and the state is which one it is drawn
    # as — that is a button, not a number, so the inspector shows no rows.
    # A subcircuit's numbers are `Sim.Params` keys, like the diode's. None of
    # them survive an `alter` on a running transient: they are read when the
    # subcircuit is expanded, which happens once, before the run.
    "Simulator:OPAMP": [{
        "id": "model", "label": "Op-amp", "target": "params", "template": "",
        "fields": [
            _f("GAIN", "Open-loop gain", "V/V", "100k", lo=1e2, hi=1e7, live=False),
            _f("POLE", "Dominant pole", "Hz", "20", lo=0.1, hi=1e6, live=False),
            _f("VOFF", "Input offset", "V", "1m", lo=1e-9, hi=1, live=False),
            _f("ROUT", "Output resistance", "\u03a9", "50", lo=1e-3, hi=1e6, live=False),
        ],
    }],
    "Simulator:INV": [{
        "id": "model", "label": "Inverter", "target": "params", "template": "",
        "fields": [
            _f("VDD", "Logic level", "V", "5", scale="linear", lo=1, hi=15, live=False),
            _f("TPLH", "Delay low to high", "s", "20n", lo=1e-12, hi=1e-3, live=False),
            _f("TPHL", "Delay high to low", "s", "15n", lo=1e-12, hi=1e-3, live=False),
            _f("ROUT", "Output resistance", "\u03a9", "50", lo=1e-3, hi=1e6, live=False),
        ],
    }],
    "Simulator:AND": [{
        "id": "model", "label": "AND gate", "target": "params", "template": "",
        "fields": [
            _f("VDD", "Logic level", "V", "5", scale="linear", lo=1, hi=15, live=False),
            _f("TPD", "Propagation delay", "s", "20n", lo=1e-12, hi=1e-3, live=False),
            _f("ROUT", "Output resistance", "\u03a9", "50", lo=1e-3, hi=1e6, live=False),
        ],
    }],
    "Simulator:DFF": [{
        "id": "model", "label": "D flip-flop", "target": "params", "template": "",
        "fields": [
            _f("VDD", "Logic level", "V", "5", scale="linear", lo=1, hi=15, live=False),
            _f("TPD", "Clock to output", "s", "25n", lo=1e-12, hi=1e-3, live=False),
            _f("ROUT", "Output resistance", "\u03a9", "50", lo=1e-3, hi=1e6, live=False),
        ],
    }],
    "Simulator:SW": [],
    "Simulator:SW_CLOSED": [],
    "Simulator:GND": [],
    "Simulator:VRAIL": [],
}


def lib_symbols_block() -> str:
    """`(lib_symbols ...)` holding every primitive — what a saved sheet
    embeds, and what the parser below reads."""
    return "(lib_symbols\n" + "\n".join(DEFINITIONS.values()) + "\n)"


def draw_library() -> dict[str, dict]:
    """The primitives as draw data, through the same parser a real sheet goes
    through. Anything that would not survive `sch_draw` never reaches the
    palette either."""
    root = parse_sexpr(sanitize_symbol_text("(kicad_sch " + lib_symbols_block() + ")"))
    return sch_draw.library(root)


def palette() -> dict:
    """Palette entries with the graphics to draw each button's preview."""
    libs = draw_library()
    return {
        "parts": [{**entry, "draw": libs.get(entry["lib_id"]),
                   "forms": PARAM_FORMS.get(entry["lib_id"], [])} for entry in PALETTE],
        "libs": libs,
        # The one part whose PICTURE carries state. Both definitions go to the
        # browser so the editor can swap the drawing when the contact closes —
        # a switch that reads "closed" while its blade is drawn open is worse
        # than no picture at all.
        "switch": {"open": SWITCH_OPEN, "closed": SWITCH_CLOSED,
                   "open_r": SWITCH_OPEN_R, "closed_r": SWITCH_CLOSED_R},
    }
