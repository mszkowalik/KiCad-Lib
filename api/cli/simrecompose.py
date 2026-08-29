#!/usr/bin/env python3
"""Turn the hand-written wrapper sim models into composed ones, then delete them.

A wrapper whose whole body is `X` instance lines and tie resistors holds no
behaviour — it is wiring, and wiring is what `services/simcompose.py` generates.
This script reads each such wrapper, works out the block design it encodes, and
saves that design on the symbol's link. The generated `.subckt` then replaces
the hand-written one.

The rework is INTERFACE-PRESERVING by construction. Every wrapper parameter
keeps its name (`$shared:NAME` bindings) and its declared default
(`defaults`), so no component's `Sim.Params` row has to change and no part
that relies on a wrapper default changes behaviour. `--verify` proves it,
by diffing the declared interface of the old and new text.

    docker compose exec api python -m cli.simrecompose plan
    docker compose exec api python -m cli.simrecompose apply --verify
    docker compose exec api python -m cli.simrecompose prune
    docker compose exec api python -m cli.simrecompose refresh
    docker compose exec api python -m cli.simrecompose orphans

`plan` writes nothing. `apply` composes and publishes. `prune` deletes the
wrappers nothing needs any more. `orphans` reports building blocks that no
longer reach a symbol — a report only, because an unused primitive is library
surface someone put there on purpose, not litter.
"""
from __future__ import annotations

import argparse
import re
import sys

sys.path.insert(0, "/srv")

from app.db import SessionLocal  # noqa: E402
from app import models as M  # noqa: E402
from app.services import material  # noqa: E402
from app.services.simcompose import COMPOSED_KIND, NET_SIGIL, compose  # noqa: E402
from app.services.simmodel import NC, _logical_lines, parse_subckt  # noqa: E402
from app.services.sim_store import (  # noqa: E402
    block_catalog,
    delete_sim_model,
    set_symbol_sim_composition,
)

_X_RE = re.compile(r"^X(\S+)\s+(.*)$", re.IGNORECASE)
_R_RE = re.compile(r"^R(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", re.IGNORECASE)
_REF_PARAM_RE = re.compile(r"^\{([A-Za-z_]\w*)\}$")
# A tie resistance is package copper: a literal, with or without a SPICE
# magnitude suffix. `{R1}` is not — it is a knob, which makes the model a
# resistor NETWORK with behaviour of its own (`sigma_dip8` is eight of them),
# and those stay hand-written.
_LITERAL_RE = re.compile(r"^[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?[a-zA-Z]*$")


def wrapper_body(source_text: str) -> list[str] | None:
    """The element lines of a subcircuit, or None when it holds anything that
    is not an instance or a plain two-terminal resistor.

    That test is the whole classification. `sigma_and4` fails it on its first
    `B` source and stays a hand-written primitive, which is correct — the
    composer wires blocks, it does not invent behaviour.
    """
    lines = _logical_lines(source_text)
    body: list[str] = []
    for line in lines:
        low = line.lower()
        if low.startswith(".subckt") or low.startswith(".ends"):
            continue
        if _X_RE.match(line):
            body.append(line)
            continue
        m = _R_RE.match(line)
        if m and _LITERAL_RE.match(m.group(4)):
            body.append(line)
            continue
        return None
    # No instance at all means no block, and a composition of nothing but ties
    # is a part in its own right rather than a wrapper around one.
    if not any(_X_RE.match(line) for line in body):
        return None
    return body or None


def derive(model: M.SimModel, source_text: str, pin_map: dict,
           catalog: dict) -> dict | None:
    """The block design a hand-written wrapper encodes, or None if it is not
    one. `pin_map` is the link's `{pin: port}`; its inverse is what turns a
    wrapper port back into the symbol pin it stands for."""
    body = wrapper_body(source_text)
    if body is None:
        return None
    parsed = parse_subckt(source_text)
    inverse = {str(v).lower(): str(k) for k, v in (pin_map or {}).items() if str(v) != NC}

    def ref_of(raw: str, letter: str) -> str:
        """`X1` gives the reference `1`, which is legal SPICE and illegal as a
        parameter prefix (`$own` would build `1_TPD`). Prefix the element
        letter so the reference stays traceable and stays a name."""
        ref = raw.lower()
        return ref if ref[:1].isalpha() else letter + ref

    def node(tok: str) -> str:
        low = tok.lower()
        if low in inverse:
            return inverse[low]
        if low in parsed["ports"]:
            # A port with no pin: the link is broken, not the wrapper.
            raise ValueError(f"port {low!r} of {model.name} is claimed by no pin")
        return NET_SIGIL + low

    blocks: list[dict] = []
    resistors: list[dict] = []
    for line in body:
        m = _X_RE.match(line)
        if m:
            ref, rest = ref_of(m.group(1), "x"), m.group(2).split()
            bare = [t for t in rest if "=" not in t]
            pairs = [t for t in rest if "=" in t]
            block_model = bare[-1]
            spec = catalog.get(block_model)
            if spec is None:
                raise ValueError(f"{model.name} instantiates unknown {block_model!r}")
            nodes_in = bare[:-1]
            if len(nodes_in) != len(spec["ports"]):
                raise ValueError(
                    f"{model.name}.X{ref} passes {len(nodes_in)} nodes to "
                    f"{block_model}, which declares {len(spec['ports'])} ports")
            params: dict[str, str] = {}
            for pair in pairs:
                key, _, value = pair.partition("=")
                ref_param = _REF_PARAM_RE.match(value)
                # `TPD={TPD}` is a pass-through of a wrapper parameter, so it
                # becomes a shared binding under that exact name — which is how
                # the rework keeps every component's Sim.Params keys working.
                params[key] = f"$shared:{ref_param.group(1)}" if ref_param else value
            blocks.append({"ref": ref, "model": block_model,
                           "nodes": {p: node(n) for p, n in zip(spec["ports"], nodes_in,
                                                                strict=True)},
                           "params": params})
            continue
        m = _R_RE.match(line)
        ref, a, b, value = ref_of(m.group(1), "r"), m.group(2), m.group(3), m.group(4)
        resistors.append({"ref": ref, "a": node(a), "b": node(b), "value": value})

    unmodelled = [str(k) for k, v in (pin_map or {}).items() if str(v) == NC]
    return {"blocks": blocks, "resistors": resistors,
            "unmodelled": sorted(unmodelled),
            # Copied verbatim, so a component with no Sim.Params row keeps the
            # number the hand-written wrapper gave it.
            "defaults": dict(parsed["params"])}


def candidates(db) -> list[tuple[M.SymbolSimLink, M.Symbol, M.SimModel, str, dict]]:
    """Every `model`-mode link whose model is pure wiring."""
    catalog = block_catalog(db)
    out = []
    for link in db.query(M.SymbolSimLink).all():
        if link.mode == COMPOSED_KIND:
            continue
        model = link.sim_model
        mv = next((v for v in model.versions if v.id == model.current_version_id), None)
        if mv is None:
            continue
        if wrapper_body(mv.source_text) is None:
            continue
        sym = db.get(M.Symbol, link.symbol_id)
        if sym is None:
            continue
        out.append((link, sym, model, mv.source_text, catalog))
    return out


def interface(source_text: str) -> tuple[list[str], dict]:
    p = parse_subckt(source_text)
    return p["ports"], p["params"]


def cmd_plan(db, args) -> int:
    rows = candidates(db)
    if not rows:
        print("nothing to compose — no link points at a pure-wiring model")
        return 0
    for link, sym, model, src, catalog in rows:
        try:
            comp = derive(model, src, link.pin_map, catalog)
        except ValueError as e:
            print(f"SKIP  {sym.name:22} {model.name:22} {e}")
            continue
        sv = next((v for v in sym.versions if v.id == sym.current_version_id), None)
        pins = material.symbol_material(sv.source_text)["pins"]
        built = compose(sym.name, comp, pins, catalog)
        errs = [p["text"] for p in built["problems"] if p["severity"] == "error"]
        blocks = ", ".join(f"{b['ref']}:{b['model']}" for b in comp["blocks"])
        ties = len(comp["resistors"])
        state = "ERROR" if errs else "ok"
        print(f"{state:5} {sym.name:22} {model.name:22} blocks[{blocks}] ties={ties}")
        for e in errs:
            print(f"        ! {e}")
        if args.show and not errs:
            print(built["source_text"])
    return 0


def cmd_apply(db, args) -> int:
    rows = candidates(db)
    failed = 0
    for link, sym, model, src, catalog in rows:
        try:
            comp = derive(model, src, link.pin_map, catalog)
        except ValueError as e:
            print(f"SKIP  {sym.name}: {e}")
            failed += 1
            continue
        old_ports, old_params = interface(src)
        res = set_symbol_sim_composition(
            db, sym.name, comp, actor="rework",
            comment=f"Composed from {model.name}, which was pure wiring. "
                    "Parameter names and defaults are carried over unchanged, "
                    "so no component's Sim.Params row moves.",
        )
        if "error" in res:
            print(f"FAIL  {sym.name}: {res['error']}")
            for p in res.get("problems", []):
                print(f"        ! {p}")
            failed += 1
            continue
        note = ""
        if args.verify:
            new_ports, new_params = interface(res["source_text"])
            # A composed wrapper binds EVERY parameter its blocks declare, so
            # it usually offers more knobs than the hand-written one did — the
            # leg's VF_IT that sigma_tvs_dual_aac never passed through. That is
            # a widening: existing Sim.Params keys still resolve and every
            # carried-over default is unchanged. Only a LOST parameter or a
            # MOVED default changes what a part does.
            lost = sorted(set(old_params) - set(new_params))
            gained = sorted(set(new_params) - set(old_params))
            moved = {k: (old_params[k], new_params[k]) for k in old_params
                     if k in new_params and old_params[k] != new_params[k]}
            drift = []
            if lost:
                drift.append(f"lost params {lost}")
            if moved:
                drift.append(f"moved defaults {moved}")
            if len(new_ports) != len(old_ports):
                drift.append(f"ports {len(old_ports)} -> {len(new_ports)}")
            if drift:
                note = "  DRIFT: " + "; ".join(drift)
                failed += 1
            elif gained:
                note = f"  interface widened by {gained}"
            else:
                note = "  interface unchanged"
        print(f"ok    {sym.name:22} -> {res['model']} v{res['version_no']}{note}")
        for w in res.get("heuristic_warnings", []):
            print(f"        ~ {w}")
    return 1 if failed else 0


def cmd_prune(db, args) -> int:
    """Delete every hand-written wrapper that composing has made unreachable."""
    removed, kept = 0, 0
    for model in sorted(db.query(M.SimModel).all(), key=lambda m: m.name):
        if model.kind == COMPOSED_KIND:
            continue
        mv = next((v for v in model.versions if v.id == model.current_version_id), None)
        if mv is None or wrapper_body(mv.source_text) is None:
            continue
        if args.dry_run:
            print(f"would delete {model.name}")
            removed += 1
            continue
        res = delete_sim_model(db, model.name, actor="rework")
        if "error" in res:
            print(f"kept  {model.name}: {res['error']}")
            kept += 1
        else:
            print(f"deleted {model.name}")
            removed += 1
    print(f"-- {removed} removed, {kept} still needed")
    return 0


def cmd_refresh(db, args) -> int:
    """Re-save every composed link, republishing any wrapper whose generated
    text has moved.

    Needed after a change to the GENERATOR rather than to a block model — a
    block publish already regenerates its dependents, but a fix to
    `simcompose` itself reaches nothing until each design is composed again.
    Republishes only where the text actually differs.
    """
    changed = failed = 0
    links = db.query(M.SymbolSimLink).filter(M.SymbolSimLink.mode == COMPOSED_KIND).all()
    for link in links:
        sym = db.get(M.Symbol, link.symbol_id)
        if sym is None:
            continue
        res = set_symbol_sim_composition(
            db, sym.name, link.composition or {}, actor="rework",
            comment="Regenerated after a change to the composer itself.")
        if "error" in res:
            print(f"FAIL  {sym.name}: {res['error']}")
            for pr in res.get("problems", []):
                print(f"        ! {pr}")
            failed += 1
            continue
        moved = res["model_status"] == "published"
        changed += moved
        print(f"{'republished' if moved else 'unchanged   '} {sym.name:24} {res['model']}")
    print(f"-- {len(links)} composed links, {changed} republished, {failed} failed")
    return 1 if failed else 0


def cmd_orphans(db, args) -> int:
    """Building blocks no symbol can reach. A report, never a deletion."""
    used: set[str] = set()
    reach: dict[str, list[str]] = {}
    for model in db.query(M.SimModel).all():
        mv = next((v for v in model.versions if v.id == model.current_version_id), None)
        reach[model.name] = list((mv.parsed or {}).get("instantiates") or []) if mv else []
    frontier = [m.sim_model.name for m in db.query(M.SymbolSimLink).all()]
    while frontier:
        name = frontier.pop()
        if name in used:
            continue
        used.add(name)
        frontier += reach.get(name, [])
    for model in sorted(db.query(M.SimModel).all(), key=lambda m: m.name):
        if model.name not in used:
            print(f"orphan  {model.name:24} kind={model.kind}")
    print(f"-- {len(used)} of {len(reach)} models are reachable from a symbol")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--show", action="store_true")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("apply"); p.add_argument("--verify", action="store_true")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("prune"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_prune)
    p = sub.add_parser("refresh"); p.set_defaults(fn=cmd_refresh)
    p = sub.add_parser("orphans"); p.set_defaults(fn=cmd_orphans)
    args = ap.parse_args()
    with SessionLocal() as db:
        return args.fn(db, args)


if __name__ == "__main__":
    raise SystemExit(main())
