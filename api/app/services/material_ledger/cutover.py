"""The one-time move of stock, work and units into the material ledger
(decision 0098).

`run(conn)` copies the nine old tables into the ledger's tables and renames
them `legacy_<name>`, in the caller's transaction. It runs only when the old
tables exist and the ledger holds no move yet, so a second start does
nothing. Any failure raises: the caller lets the transaction roll back and the
start fail, so the old image can run again on untouched tables.

**Ids are kept.** A draw keeps its id as a move, a click and a transformation
keep theirs as events, a twin keeps its id as a unit lot, a positive
adjustment's id becomes its stored lot's id (so `A675` stays `A675`), a
binding keeps its id. Where two old tables would give one new table the same
id, the second one gets a new id and every reference to it is rewritten; on
the production copy of 2026-10-23 only the whole-step cost links needed that.

An old row with no event of its own (a draw no click, transformation or
transfer holds; an adjustment no transformation made) gets an event of kind
`stock` of its own, with a new id. A transfer document's draws share one.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import MetaData, Table, text
from sqlalchemy.engine import Connection

log = logging.getLogger("uvicorn.error")

OLD = ("component_consumptions", "component_consumption_lots", "component_stock_adjustments",
       "process_transformations", "cost_line_steps", "cost_line_step_keys", "step_runs", "twin_steps", "twins")

#: The phase-1 shadow of decision 0097: rebuilt from the old tables, holding no
#: fact of its own, in shapes the ledger no longer has.
SHADOW = ("material_moves", "material_event_lots", "material_links", "material_properties",
          "material_cost_aims", "material_lots", "material_events")


def _has_table(conn: Connection, name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"public.{name}"}).scalar())


def _has_column(conn: Connection, table: str, column: str) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first())


def drop_shadow(conn: Connection) -> bool:
    """Before `create_all`: drop the phase-1 shadow, recognised by its
    `material_moves.pool_key`. The items and the state maps are kept: they
    hold what people decided."""
    if not (_has_table(conn, "material_moves") and _has_column(conn, "material_moves", "pool_key")):
        return False
    for t in SHADOW:
        conn.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
    log.info("material ledger: dropped the phase-1 shadow")
    return True


def needed(conn: Connection) -> bool:
    return _has_table(conn, "component_consumptions") and not conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM material_moves)")).scalar()


def run(conn: Connection) -> dict:
    """Copy, then rename. Returns the counts it wrote."""
    from ..run_actuals import _key

    md = MetaData()
    old = {n: Table(n, md, autoload_with=conn) for n in OLD}

    def rows(name: str, order: str = "id") -> list:
        return conn.execute(old[name].select().order_by(text(order))).mappings().all()

    run_company = dict(conn.execute(text("SELECT id, company_id FROM production_runs")).all())
    macs = dict(conn.execute(text("SELECT id, mac FROM device_units")).all())
    doc_of_line = dict(conn.execute(text("SELECT id, document_id FROM run_cost_lines")).all())

    # ---------------------------------------------------------------- items
    items: dict[str, int] = dict(conn.execute(text("SELECT key, id FROM material_items")).all())

    def item(component_id=None, mpn="", lcsc="", project_id=None) -> int:
        key = f"p{project_id}" if project_id is not None else _key(
            SimpleNamespace(component_id=component_id, mpn=mpn or "", lcsc=lcsc or ""))
        if key not in items:
            items[key] = conn.execute(text(
                "INSERT INTO material_items (key, kind, component_id, mpn, lcsc, project_id, uom, tracking, "
                "identifier_kind, created_at) VALUES (:k, :kind, :c, :m, :l, :p, 'pcs', :tr, '', now()) "
                "RETURNING id"),
                {"k": key, "kind": "product" if project_id is not None else "part",
                 "c": component_id or None, "m": (mpn or "")[:200], "l": (lcsc or "")[:50], "p": project_id,
                 "tr": "serial" if project_id is not None else "count"}).scalar()
        return items[key]

    clicks, makes = rows("step_runs"), rows("process_transformations")
    twins, twin_steps = rows("twins"), rows("twin_steps")
    draws, binds = rows("component_consumptions"), rows("component_consumption_lots")
    adjs = rows("component_stock_adjustments")
    click_costs, step_costs = rows("cost_line_steps"), rows("cost_line_step_keys")

    # ---------------------------------------------------------------- ids
    def allocate(first: list, second: list) -> dict[int, int]:
        """Keep the ids of `first`; keep those of `second` that are free, give
        the others ids after the highest."""
        taken = {r["id"] for r in first}
        top = max([r["id"] for r in first + second] or [0])
        out = {}
        for r in second:
            if r["id"] in taken:
                top += 1
                out[r["id"]] = top
            else:
                out[r["id"]] = r["id"]
            taken.add(out[r["id"]])
        return out

    make_id = allocate(clicks, makes)
    # A stored lot is named by its adjustment: keep that id (A675 stays A675)
    # and let a twin move when they collide.
    positive = [a for a in adjs if (a["qty_delta"] or 0) > 0]
    lot_of_adj = {a["id"]: a["id"] for a in positive}
    unit_id = allocate(positive, twins)
    move_of_adj = allocate(draws, adjs)
    aim_of_key = allocate(click_costs, step_costs)

    next_event = [max([r["id"] for r in clicks] + list(make_id.values()) or [0])]

    def new_event(**kw) -> int:
        next_event[0] += 1
        ev = {"id": next_event[0], "kind": "stock", "at": "", "actor": "", "project_id": None, "company_id": None,
              "run_id": None, "process_version_id": None, "step_key": "", "step_label": "", "step_kind": "",
              "units": None, "chosen": "", "assembler": "", "reference": "", "note": "", "qty": None,
              "scrap": None, "output_component_id": None, "input_value_usd": None, "output_lot_id": None,
              "voided_at": None, "void_reason": "", "created_at": None}
        ev.update(kw)
        ev["note"] = (ev["note"] or "")[:500]
        ev["created_at"] = ev["created_at"] or datetime.now(timezone.utc)
        events.append(ev)
        return ev["id"]

    # ---------------------------------------------------------------- events
    events: list[dict] = []
    for c in clicks:
        events.append({"id": c["id"], "kind": "step", "at": c["made_at"] or "", "actor": c["actor"] or "",
                       "project_id": c["project_id"], "company_id": run_company.get(c["run_id"]),
                       "run_id": c["run_id"], "process_version_id": c["process_version_id"],
                       "step_key": c["step_key"] or "", "step_label": c["step_label"] or "",
                       "step_kind": c["kind"] or "step", "units": c["qty"], "chosen": c["chosen"] or "",
                       "assembler": c["assembler"] or "", "reference": c["reference"] or "", "note": c["note"] or "",
                       "qty": None, "scrap": None, "output_component_id": None, "input_value_usd": None,
                       "output_lot_id": None, "voided_at": None, "void_reason": "", "created_at": c["created_at"]})
    adj_company = {a["id"]: a["company_id"] for a in adjs}
    for t in makes:
        events.append({"id": make_id[t["id"]], "kind": "make", "at": t["made_at"] or "", "actor": t["actor"] or "",
                       "project_id": t["project_id"], "company_id": adj_company.get(t["output_adjustment_id"]),
                       "run_id": t["production_run_id"], "process_version_id": t["process_version_id"],
                       "step_key": t["recipe_key"] or "", "step_label": t["recipe_label"] or "", "step_kind": "",
                       "units": None, "chosen": "", "assembler": "", "reference": "", "note": t["note"] or "",
                       "qty": t["qty"], "scrap": t["scrap"], "output_component_id": t["output_component_id"],
                       "input_value_usd": t["input_value_usd"],
                       "output_lot_id": lot_of_adj.get(t["output_adjustment_id"]),
                       "voided_at": t["voided_at"], "void_reason": t["void_reason"] or "",
                       "created_at": t["created_at"]})
    click_ids = {c["id"] for c in clicks}

    # ---------------------------------------------------------------- lots
    lots: list[dict] = []
    first_at: dict[int, str] = {}
    at_of_click = {c["id"]: c["made_at"] or "" for c in clicks}
    for ts in twin_steps:
        d = at_of_click.get(ts["step_run_id"], "")
        if d and (ts["twin_id"] not in first_at or d < first_at[ts["twin_id"]]):
            first_at[ts["twin_id"]] = d
    for tw in twins:
        lots.append({"id": unit_id[tw["id"]], "kind": "unit", "item_id": item(project_id=tw["project_id"]),
                     "company_id": run_company.get(tw["origin_run_id"]), "label": "",
                     "at": first_at.get(tw["id"], ""), "created_event_id": None, "split_from_lot_id": None,
                     "identifier": macs.get(tw["device_unit_id"]) if tw["device_unit_id"] else None,
                     "project_id": tw["project_id"], "origin_run_id": tw["origin_run_id"], "run_id": tw["run_id"],
                     "process_version_id": tw["process_version_id"], "device_unit_id": tw["device_unit_id"],
                     "status": tw["status"] or "active",
                     "stack_key": tw["stack_key"] or "", "found": bool(tw["found"]), "note": tw["note"] or "",
                     "named_at": tw["named_at"], "finished_at": tw["finished_at"],
                     "scrapped_at": tw["scrapped_at"], "created_at": tw["created_at"]})

    # ---------------------------------------------------------------- moves
    made_by = {t["output_adjustment_id"]: make_id[t["id"]] for t in makes if t["output_adjustment_id"]}
    transfer_event: dict[int, int] = {}
    moves: list[dict] = []
    for c in draws:
        if c["step_run_id"] in click_ids:
            ev = c["step_run_id"]
        elif c["transformation_id"] in make_id:
            ev = make_id[c["transformation_id"]]
        elif c["transfer_line_id"]:
            doc = doc_of_line.get(c["transfer_line_id"])
            if doc not in transfer_event:
                transfer_event[doc] = new_event(at=c["consumed_at"] or "", company_id=c["company_id"],
                                                note=f"in-house transfer, document {doc}",
                                                created_at=c["created_at"])
            ev = transfer_event[doc]
        else:
            ev = new_event(at=c["consumed_at"] or "", company_id=c["company_id"], run_id=c["run_id"],
                           note=c["note"] or "", created_at=c["created_at"])
        moves.append({"id": c["id"], "kind": "draw", "event_id": ev,
                      "item_id": item(c["component_id"], c["mpn"], c["lcsc"]), "component_id": c["component_id"],
                      "mpn": c["mpn"] or "", "lcsc": c["lcsc"] or "", "qty": -(c["qty"] or 0.0),
                      "unit_cost_usd": c["unit_cost_usd"], "at": c["consumed_at"] or "", "run_id": c["run_id"],
                      "company_id": c["company_id"], "project_id": None, "basis": c["basis"] or "", "reason": "",
                      "import_ref": c["import_ref"] or "", "note": c["note"] or "", "actor": "",
                      "voided_at": c["voided_at"], "void_reason": c["void_reason"] or "",
                      "transfer_line_id": c["transfer_line_id"], "lot_id": None, "created_at": c["created_at"]})
    for a in adjs:
        if a["id"] in made_by:
            ev = made_by[a["id"]]
        else:
            ev = new_event(at=a["adjusted_at"] or "", actor=a["actor"] or "", company_id=a["company_id"],
                           run_id=a["charge_run_id"], project_id=a["project_id"],
                           note=f"{a['reason'] or ''}: {a['note'] or ''}", created_at=a["created_at"])
        lot = lot_of_adj.get(a["id"])
        it = item(a["component_id"], a["mpn"], a["lcsc"])
        if lot is not None:
            lots.append({"id": lot, "kind": "stock", "item_id": it, "company_id": a["company_id"],
                         "label": f"A{lot}", "at": a["adjusted_at"] or "", "created_event_id": ev,
                         "split_from_lot_id": None, "identifier": None, "project_id": None, "origin_run_id": None,
                         "run_id": None, "process_version_id": None, "device_unit_id": None, "status": "active",
                         "stack_key": "", "found": False, "note": "", "named_at": None, "finished_at": None,
                         "scrapped_at": None, "created_at": a["created_at"]})
        moves.append({"id": move_of_adj[a["id"]], "kind": "adjust", "event_id": ev, "item_id": it,
                      "component_id": a["component_id"], "mpn": a["mpn"] or "", "lcsc": a["lcsc"] or "",
                      "qty": a["qty_delta"] or 0.0, "unit_cost_usd": a["unit_cost_usd"], "at": a["adjusted_at"] or "",
                      "run_id": a["charge_run_id"], "company_id": a["company_id"], "project_id": a["project_id"],
                      "basis": "", "reason": a["reason"] or "", "import_ref": a["import_ref"] or "",
                      "note": a["note"] or "", "actor": a["actor"] or "", "voided_at": None, "void_reason": "",
                      "transfer_line_id": None, "lot_id": lot, "created_at": a["created_at"]})

    move_lots = [{"id": b["id"], "move_id": b["consumption_id"], "lot_line_id": b["lot_line_id"],
                  "lot_id": lot_of_adj.get(b["lot_adjustment_id"]) if b["lot_adjustment_id"] else None,
                  "qty": b["qty"], "unit_cost_usd": b["unit_cost_usd"], "source": b["source"] or "",
                  "ext_ref": b["ext_ref"] or "", "note": b["note"] or "", "created_at": b["created_at"]}
                 for b in binds]
    event_lots = [{"id": ts["id"], "event_id": ts["step_run_id"], "lot_id": unit_id[ts["twin_id"]],
                   "programming_run_id": ts["programming_run_id"],
                   "deployment_version_id": ts["deployment_version_id"], "created_at": ts["created_at"]}
                  for ts in twin_steps]
    aims = ([{"id": x["id"], "kind": "click", "line_id": x["line_id"], "event_id": x["step_run_id"], "run_id": None,
              "step_key": "", "created_at": x["created_at"]} for x in click_costs]
            + [{"id": aim_of_key[x["id"]], "kind": "step", "line_id": x["line_id"], "event_id": None,
                "run_id": x["run_id"], "step_key": x["step_key"], "created_at": x["created_at"]} for x in step_costs])

    # ---------------------------------------------------------------- write
    new = MetaData()
    for table, data in (("material_events", events), ("material_lots", lots), ("material_moves", moves),
                        ("material_move_lots", move_lots), ("material_event_lots", event_lots),
                        ("material_cost_aims", aims)):
        if data:
            conn.execute(Table(table, new, autoload_with=conn).insert(), data)
    # What still names an old id outside these tables.
    for old_id, nid in make_id.items():
        if old_id != nid:
            conn.execute(text("UPDATE run_cost_lines SET transformation_id = :n WHERE transformation_id = :o"),
                         {"n": nid, "o": old_id})
    for table in ("material_events", "material_lots", "material_moves", "material_move_lots",
                  "material_event_lots", "material_cost_aims", "material_items"):
        conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                          f"COALESCE((SELECT max(id) FROM {table}), 0) + 1, false)"))
    for name in OLD:
        conn.execute(text(f"ALTER TABLE {name} RENAME TO legacy_{name}"))
        conn.execute(text(f"DROP TRIGGER IF EXISTS row_change_capture ON legacy_{name}"))
    out = {"events": len(events), "lots": len(lots), "moves": len(moves), "move_lots": len(move_lots),
           "event_lots": len(event_lots), "cost_aims": len(aims), "items": len(items),
           "renumbered": {"transformations": sum(1 for o, n in make_id.items() if o != n),
                          "twins": sum(1 for o, n in unit_id.items() if o != n),
                          "adjustments": sum(1 for o, n in move_of_adj.items() if o != n),
                          "step_cost_links": sum(1 for o, n in aim_of_key.items() if o != n)}}
    log.info(f"material ledger: cut-over written {out}")
    return out
