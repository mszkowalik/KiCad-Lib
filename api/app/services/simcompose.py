"""Build a symbol's simulation model out of library blocks, instead of by hand.

WHY THIS EXISTS. KiCad netlists one element per reference designator, so the
thing `Sim.Name` points at is always package-level: a 74HC21 cannot be two
`sigma_and4` instances in a schematic, it has to be one subcircuit with all
twelve pins. Until now that wrapper was hand-written SPICE, one per part, and
the library accumulated nine of them that hold no behaviour at all — two
instance lines and a parameter pass-through. `sigma_74hc21` and `sigma_buf2`
were written, never linked to anything, and never noticed.

So the wrapper is now DERIVED. The author picks blocks and says which symbol
pin each block port sits on; this module emits the `.subckt`. The generated
text is stored as a normal `SimModel` row with `kind="composed"`, which is why
nothing downstream changed: `mirror.write_sim_lib` emits it like any other
model, `generator.sim_props` points `Sim.Name` at it, and the validator checks
the link exactly as before.

THE ONE RULE THAT SHAPES EVERYTHING: one wrapper port per unique symbol pin
number, never fewer. It is tempting to alias three source pins of a power MOSFET
onto one port `s` and drop the tie resistors. It is wrong: the schematic may
put those pins on three different nets, and one port carries one node, so the
netlist could not express it. Ties are therefore modelled the way
`sigma_nmos_pwr8` already modelled them by hand — as real resistors inside the
subcircuit, which is also the only form that lets you see the tie current.

The payoff of that rule is that the port list is `p1 p2 p4 ...` by
construction, so `Sim.Pins` is derived and cannot be mis-authored. The stored
pin map — the artifact `validate_pin_map` openly cannot check for swaps —
stops being authored state in composed mode.
"""
from __future__ import annotations

import re

from .simmodel import NC, _POWER_PIN_TYPES, _RAIL_PORTS

# Reserved name space for generated wrappers. A hand-written model may not use
# it, so `sigma_sym_*` in the mirror always means "nobody typed this".
WRAPPER_PREFIX = "sigma_sym_"
COMPOSED_KIND = "composed"

# A node value in `nodes` / a resistor endpoint is a symbol PIN NUMBER, or an
# internal net written `@name`. Pin numbers are alphanumeric ("A1"), so the
# sigil is what keeps the two unambiguous.
NET_SIGIL = "@"

# Parameter bindings. Absent means `$shared`.
SHARED = "$shared"      # or `$shared:NAME` to share under a different name
OWN = "$own"            # declared as <REF>_<NAME>, one per block
_BIND_RE = re.compile(r"^\$shared(?::([A-Za-z_]\w*))?$")

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_REF_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def wrapper_name(symbol_name: str) -> str:
    """`SN74HC21` -> `sigma_sym_sn74hc21`.

    Derived, not authored: the wrapper belongs to exactly one symbol and
    outlives no link, so letting anyone name it would only create a second
    thing to keep in step.
    """
    slug = _SLUG_RE.sub("_", symbol_name.strip().lower()).strip("_")
    return WRAPPER_PREFIX + (slug or "unnamed")


def port_name(pin_number: str) -> str:
    """Pin `12` -> port `p12`. Pin `A1` -> port `pa1`."""
    return "p" + _SLUG_RE.sub("_", str(pin_number).strip().lower())


def sort_pins(numbers) -> list[str]:
    """Numeric-aware pin order, so a regenerated wrapper is byte-stable."""
    def key(n: str):
        return (0, int(n), "") if n.isdigit() else (1, 0, n)
    return sorted(numbers, key=key)


def unique_pins(symbol_pins: list[dict]) -> dict[str, dict]:
    """`{number: {"name", "type"}}`, visible pin winning over a hidden stacked
    duplicate — the same collapse `validate_pin_map` and `link_material_sha`
    apply, because KiCad nets stacked pins together and the wrapper only needs
    one port for them."""
    out: dict[str, dict] = {}
    for pin in symbol_pins:
        num = str(pin.get("number") or "")
        if not num:
            continue
        if num not in out or not pin.get("hide"):
            out[num] = {"name": pin.get("name") or "", "type": pin.get("type") or ""}
    return out


# ---------------------------------------------------------------- nodes
def is_net(node: str) -> bool:
    return str(node).startswith(NET_SIGIL)


def net_name(node: str) -> str:
    return str(node)[len(NET_SIGIL):]


def node_spice(node: str) -> str:
    """A node value -> the token that goes in the netlist."""
    return net_name(node) if is_net(node) else port_name(node)


def _nodes_used(composition: dict) -> tuple[set[str], set[str]]:
    """(pin numbers, internal net names) referenced anywhere in the design."""
    pins: set[str] = set()
    nets: set[str] = set()
    for block in composition.get("blocks") or []:
        for node in (block.get("nodes") or {}).values():
            if not node:
                continue
            (nets if is_net(node) else pins).add(net_name(node) if is_net(node) else str(node))
    for res in composition.get("resistors") or []:
        for node in (res.get("a"), res.get("b")):
            if not node:
                continue
            (nets if is_net(node) else pins).add(net_name(node) if is_net(node) else str(node))
    return pins, nets


# ---------------------------------------------------------------- params
def _binding(block: dict, param: str) -> str:
    return str((block.get("params") or {}).get(param) or SHARED).strip()


def _wrapper_param(block: dict, param: str, binding: str) -> str | None:
    """The wrapper parameter this block param resolves to, or None when the
    binding is a literal (the value is written into the instance line and the
    wrapper declares nothing)."""
    if binding == OWN:
        return f"{block['ref'].upper()}_{param.upper()}"
    m = _BIND_RE.match(binding)
    if m:
        return (m.group(1) or param).upper()
    return None


def wrapper_params(composition: dict, catalog: dict) -> tuple[dict[str, str], list[dict]]:
    """The wrapper's `params:` declaration, plus any problems found building it.

    Default is SHARED, because that is what every hand-written wrapper in the
    library already does — 74HC21, buf2, comp_dual_od, bts723gw and rail_buf2
    all pass one identical value to both halves, since both halves are one die.
    `$own` exists for the one that does not: `sigma_tvs_dual_aac` gives each
    TVS leg its own breakdown voltage.
    """
    declared: dict[str, str] = {}
    origin: dict[str, str] = {}
    problems: list[dict] = []
    # A wrapper may hold a default the block model does not: `sigma_tvs_bi`
    # declared VBR=26.7 while its `sigma_tvs_leg` block defaults to 13.3, and
    # a component with no Sim.Params row runs on whichever number the wrapper
    # states. Without this override, composing that part would quietly halve
    # its clamping voltage.
    overrides = {str(k).upper(): str(v) for k, v in
                 (composition.get("defaults") or {}).items()}
    for block in composition.get("blocks") or []:
        spec = catalog.get(block.get("model") or "")
        if spec is None:
            continue
        # SORTED, always. `parsed` is a JSONB cache, and Postgres stores a
        # jsonb object with its keys reordered (shortest first, then bytewise)
        # — so the same model yields one key order in the session that parsed
        # it and another after a round trip. Emitting in dict order made the
        # generated text differ from itself and every mirror write reported
        # the wrapper as behind its design.
        for param, default in sorted((spec.get("params") or {}).items()):
            binding = _binding(block, param)
            name = _wrapper_param(block, param, binding)
            if name is None:
                continue
            where = f"{block['ref']}.{param}"
            if name in declared and declared[name] != str(default):
                # Silent when `defaults` settles it: sharing two block
                # parameters under one name is a deliberate act (a symmetric
                # TVS binds VBR_POS and VBR_NEG to one VBR), and the override
                # states the answer, so the warning would only be wrong.
                if name not in overrides:
                    problems.append({"severity": "warning", "text":
                        f"{where} shares wrapper parameter {name} with {origin[name]}, "
                        f"which defaults to {declared[name]} — keeping that, not {default}"})
                continue
            declared.setdefault(name, str(default))
            origin.setdefault(name, where)
    for name, value in overrides.items():
        if name in declared:
            declared[name] = value
        else:
            problems.append({"severity": "error", "text":
                f"default given for {name}, which no block binds to"})
    return declared, problems


# ---------------------------------------------------------------- validation
def validate_composition(composition: dict, symbol_pins: list[dict], catalog: dict) -> list[dict]:
    """Everything wrong with one composition. `{"severity", "text"}` entries;
    no `error` means `compose` will produce a netlist worth running.

    Structural checks a hand-written wrapper never got: a block port with no
    node, an internal net with one attachment (which ngspice answers with a
    singular matrix, not an error message you can read), and a symbol pin that
    is neither wired nor declared unmodelled.
    """
    problems: list[dict] = []

    def err(text: str) -> None:
        problems.append({"severity": "error", "text": text})

    def warn(text: str) -> None:
        problems.append({"severity": "warning", "text": text})

    pins = unique_pins(symbol_pins)
    blocks = composition.get("blocks") or []
    resistors = composition.get("resistors") or []
    unmodelled = {str(n) for n in (composition.get("unmodelled") or [])}

    if not blocks and not resistors:
        err("a composition needs at least one block")

    seen_refs: set[str] = set()
    for block in blocks:
        ref = str(block.get("ref") or "").strip().lower()
        model = str(block.get("model") or "").strip()
        if not _REF_RE.match(ref):
            err(f"block reference {block.get('ref')!r} must be a letter followed by "
                "letters, digits or underscores")
            continue
        if ref in seen_refs:
            err(f"two blocks are both called {ref!r}")
            continue
        seen_refs.add(ref)
        spec = catalog.get(model)
        if spec is None:
            err(f"block {ref}: no published sim model called {model!r}")
            continue
        nodes = {str(k).lower(): str(v) for k, v in (block.get("nodes") or {}).items()}
        for port in spec["ports"]:
            node = nodes.get(port, "").strip()
            if not node:
                err(f"block {ref}: port {port!r} has no node")
                continue
            if not is_net(node) and node not in pins:
                err(f"block {ref}: port {port!r} sits on pin {node!r}, which the symbol "
                    "does not have")
        for extra in sorted(set(nodes) - {p.lower() for p in spec["ports"]}):
            err(f"block {ref}: {extra!r} is not a port of {model} "
                f"(ports: {' '.join(spec['ports'])})")
        for param in (block.get("params") or {}):
            if param not in (spec.get("params") or {}):
                err(f"block {ref}: {model} declares no parameter {param!r}")

    seen_res: set[str] = set()
    for res in resistors:
        ref = str(res.get("ref") or "").strip().lower()
        if not _REF_RE.match(ref):
            err(f"tie reference {res.get('ref')!r} must be a letter followed by "
                "letters, digits or underscores")
            continue
        if ref in seen_res or ref in seen_refs:
            err(f"tie {ref!r} reuses a reference already taken")
            continue
        seen_res.add(ref)
        for side in ("a", "b"):
            node = str(res.get(side) or "").strip()
            if not node:
                err(f"tie {ref}: side {side} has no node")
            elif not is_net(node) and node not in pins:
                err(f"tie {ref}: side {side} sits on pin {node!r}, which the symbol "
                    "does not have")
        if str(res.get("a")) == str(res.get("b")):
            err(f"tie {ref}: both sides sit on the same node")
        if not str(res.get("value") or "").strip():
            err(f"tie {ref}: no resistance")

    used_pins, used_nets = _nodes_used(composition)

    overlap = sorted(used_pins & unmodelled)
    if overlap:
        err(f"pins are declared unmodelled but still wired: {', '.join(overlap)}")
    ghost = sorted(unmodelled - set(pins))
    if ghost:
        err(f"declared unmodelled but not pins of this symbol: {', '.join(ghost)}")
    forgotten = sort_pins(set(pins) - used_pins - unmodelled)
    if forgotten:
        err(f"pins neither wired nor declared unmodelled: {', '.join(forgotten)} — "
            f"list them in `unmodelled` to say so on purpose (the composed form of {NC!r})")

    # An internal net with one attachment is a floating node. ngspice reports
    # that as a singular matrix at the first timestep, which reads as a
    # convergence problem and is not one.
    counts: dict[str, int] = {}
    for block in blocks:
        for node in (block.get("nodes") or {}).values():
            if node and is_net(str(node)):
                counts[net_name(str(node))] = counts.get(net_name(str(node)), 0) + 1
    for res in resistors:
        for node in (res.get("a"), res.get("b")):
            if node and is_net(str(node)):
                counts[net_name(str(node))] = counts.get(net_name(str(node)), 0) + 1
    for net in sorted(used_nets):
        if counts.get(net, 0) < 2:
            err(f"internal net {NET_SIGIL}{net} has one attachment — it would float, and "
                "ngspice answers a floating node with a singular matrix")

    # The rail heuristic, per block port. Same judgement as validate_pin_map,
    # applied where it now reads correctly: a rail port fed by a signal pin.
    for block in blocks:
        spec = catalog.get(str(block.get("model") or ""))
        if spec is None:
            continue
        ref = str(block.get("ref") or "")
        for port, node in (block.get("nodes") or {}).items():
            node = str(node)
            if not node or is_net(node):
                continue
            ptype = pins.get(node, {}).get("type", "")
            low = str(port).lower()
            if low in _RAIL_PORTS and ptype not in _POWER_PIN_TYPES:
                warn(f"block {ref}: rail port {low!r} is fed by pin {node}, which is "
                     f"{ptype or 'untyped'}")
            elif low not in _RAIL_PORTS and ptype == "power_in":
                warn(f"block {ref}: signal port {low!r} is fed by pin {node}, which is "
                     "power_in")

    _, param_problems = wrapper_params(composition, catalog)
    problems += param_problems
    return problems


# ---------------------------------------------------------------- emit
def _wrap(prefix: str, tokens: list[str], width: int = 92) -> list[str]:
    """SPICE continuation lines, so a wide instance stays readable."""
    lines: list[str] = []
    cur = prefix
    for tok in tokens:
        if cur.strip() and len(cur) + 1 + len(tok) > width:
            lines.append(cur)
            cur = "+     " + tok
        else:
            cur = f"{cur} {tok}" if cur.strip() else cur + tok
    if cur.strip():
        lines.append(cur)
    return lines


def compose(symbol_name: str, composition: dict, symbol_pins: list[dict],
            catalog: dict) -> dict:
    """Composition -> `{source_text, ports, pin_map, problems}`.

    Returns problems and no text when the composition does not validate. The
    caller decides whether that blocks a save; nothing here writes.
    """
    problems = validate_composition(composition, symbol_pins, catalog)
    if any(p["severity"] == "error" for p in problems):
        return {"source_text": "", "ports": [], "pin_map": {}, "problems": problems}

    pins = unique_pins(symbol_pins)
    blocks = composition.get("blocks") or []
    resistors = composition.get("resistors") or []
    unmodelled = {str(n) for n in (composition.get("unmodelled") or [])}
    used_pins, _ = _nodes_used(composition)

    ordered = sort_pins(used_pins)
    ports = [port_name(n) for n in ordered]
    pin_map = {n: port_name(n) for n in ordered}
    pin_map.update({n: NC for n in sort_pins(unmodelled)})

    name = wrapper_name(symbol_name)
    declared, _ = wrapper_params(composition, catalog)

    # Which block ports each pin feeds. This comment block is the review
    # artifact: a generated netlist nobody can read is a generated netlist
    # nobody checks.
    feeds: dict[str, list[str]] = {n: [] for n in ordered}
    for block in blocks:
        for port, node in (block.get("nodes") or {}).items():
            if node and not is_net(str(node)):
                feeds.setdefault(str(node), []).append(f"{block['ref']}.{port}")
    for res in resistors:
        for side in ("a", "b"):
            node = str(res.get(side) or "")
            if node and not is_net(node):
                feeds.setdefault(node, []).append(str(res.get("ref")))
    # SORTED, for the same reason the parameters are: `composition` is stored
    # as JSONB and Postgres reorders an object's keys, so iterating `nodes`
    # gave "x1.pren x1.vcc" in the session that wrote it and "x1.vcc x1.pren"
    # after a round trip. Only the comment moved, and that was enough to make
    # every mirror write call the wrapper behind its own design. ANY list this
    # function derives from a dict has to be ordered explicitly.
    for hits in feeds.values():
        hits.sort()

    out: list[str] = [
        f"* GENERATED for symbol {symbol_name} — composed from library blocks.",
        "* Edit it in the Simulation card on the symbol page. Hand edits are lost",
        "* on the next regeneration, and a block model's new version regenerates it.",
        "* pin -> port -> block ports:",
    ]
    for num in ordered:
        info = pins.get(num, {})
        label = info.get("name") or "-"
        out.append(f"*   {num:>4}  {port_name(num):<8} {label:<10} {info.get('type', ''):<10} "
                   f"{' '.join(feeds.get(num, []))}".rstrip())
    for num in sort_pins(unmodelled):
        info = pins.get(num, {})
        out.append(f"*   {num:>4}  {'-':<8} {info.get('name') or '-':<10} "
                   f"{info.get('type', ''):<10} not modelled".rstrip())

    out += _wrap(f".subckt {name}", ports)
    if declared:
        out += _wrap("+ params:", [f"{k}={v}" for k, v in declared.items()])

    for block in blocks:
        spec = catalog[block["model"]]
        nodes = {str(k).lower(): str(v) for k, v in (block.get("nodes") or {}).items()}
        tokens = [node_spice(nodes[p.lower()]) for p in spec["ports"]]
        tokens.append(block["model"])
        for param in sorted(spec.get("params") or {}):  # see wrapper_params
            binding = _binding(block, param)
            wname = _wrapper_param(block, param, binding)
            tokens.append(f"{param}={{{wname}}}" if wname else f"{param}={binding}")
        out += _wrap(f"  X{block['ref']}", tokens)

    for res in resistors:
        out.append(f"  R{res['ref']} {node_spice(str(res['a']))} "
                   f"{node_spice(str(res['b']))} {res['value']}")

    out.append(".ends")
    return {"source_text": "\n".join(out) + "\n", "ports": ports,
            "pin_map": pin_map, "problems": problems}
