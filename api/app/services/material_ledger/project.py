"""Build the material ledger from today's rows (decision 0097, phase 1).

`rebuild` empties the shadow tables and projects them again from the pool's
own event list (`run_actuals._pool_events`, transfers included), the step
clicks and twins, the transformations and the invoice positions aimed at work.
Nothing reads the result but `state` and `parity` until phase 2. Section 8 of
docs/material-ledger/design.md gives the mapping table by table.

Three rules shape it:

* **Moves are written in the pool's replay order**, so `ORDER BY at, rank, id`
  replays them as `pool_state` does, same-day ties included.
* **A draw becomes one move per lot binding**, plus one move with no lot for
  what no binding covers. All of them name the draw (`source_id`), so a
  reader can take them back together as the one draw the pool replays. The draw's frozen price values each of them
  (`value_usd`). The lot gives up the binding's own price (`lot_value_usd`).
  The two differ while `lot_pricing` is off.
* **A state map makes an internal part a state of another item.** The output
  lot of its transformation is a lot of that item, with the map's
  properties, and `pool_key` keeps the old identity, so parity compares like
  with like.

Phase 1 projects no links: the history records what a click drew, not where
each piece went. A product unit's lot gets +1 at its first click and -1 at a
scrap; a shipment is not projected yet.
"""
from __future__ import annotations

import time
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.orm import Session

from ... import models as M
from .. import run_actuals

EPS = 1e-9

# Emptied and built again on every rebuild. Children first for the inserts'
# reverse; TRUNCATE takes them together.
SHADOW = ("material_moves", "material_event_lots", "material_links", "material_properties",
          "material_cost_aims", "material_lots", "material_events")


def _event_row(eid: int, source_kind: str, source_id: int | None, **kw) -> dict:
    row = {"id": eid, "kind": "", "at": "", "actor": "", "company_id": None, "run_id": None,
           "process_version_id": None, "step_key": "", "step_label": "", "step_kind": "", "units": None,
           "chosen": "", "station": "", "programming_run_id": None, "deployment_version_id": None,
           "file_set_id": None, "params": None, "note": "", "reverses_event_id": None,
           "source_kind": source_kind, "source_id": source_id}
    row.update(kw)
    row["note"] = (row["note"] or "")[:500]
    row["step_label"] = (row["step_label"] or "")[:200]
    return row


def _lot_row(lid: int, item_id: int, source_kind: str, source_id: int | None, **kw) -> dict:
    row = {"id": lid, "item_id": item_id, "company_id": None, "identifier": None, "device_unit_id": None,
           "split_from_lot_id": None, "created_event_id": None, "origin_run_id": None, "found": False,
           "source_kind": source_kind, "source_id": source_id, "label": "", "at": ""}
    row.update(kw)
    return row


class _Builder:
    def __init__(self, db: Session):
        self.db = db
        self.items: dict[str, M.MaterialItem] = {it.key: it for it in db.query(M.MaterialItem).all()}
        self.maps = {m.component_id: m for m in db.query(M.MaterialStateMap).all()}
        self.events: list[dict] = []
        self.lots: list[dict] = []
        self.moves: list[dict] = []
        self.event_lots: list[dict] = []
        self.properties: list[dict] = []
        self.aims: list[dict] = []
        self.ev_by_src: dict[tuple[str, int], int] = {}
        self.lot_by_src: dict[tuple[str, int], int] = {}
        self.lot_item: dict[int, int] = {}
        self.lot_key: dict[int, str] = {}  # the pool identity of the row a lot stands for
        self.new_items = 0
        self.findings: dict[str, list] = defaultdict(list)

    # ---------------------------------------------------------- the records
    def item(self, key: str, *, kind: str = "part", component_id: int | None = None, mpn: str = "",
             lcsc: str = "", project_id: int | None = None) -> M.MaterialItem:
        it = self.items.get(key)
        if it is None:
            it = M.MaterialItem(key=key, kind=kind, component_id=component_id, mpn=(mpn or "")[:200],
                                lcsc=(lcsc or "")[:50], project_id=project_id,
                                tracking="serial" if kind == "product" else "count")
            self.db.add(it)
            self.db.flush()
            self.items[key] = it
            self.new_items += 1
        return it

    def part_item(self, row) -> M.MaterialItem:
        return self.item(run_actuals._key(row), component_id=getattr(row, "component_id", None),
                         mpn=getattr(row, "mpn", "") or "", lcsc=getattr(row, "lcsc", "") or "")

    def event(self, source_kind: str, source_id: int, **kw) -> int:
        k = (source_kind, source_id)
        if k not in self.ev_by_src:
            eid = len(self.events) + 1
            self.events.append(_event_row(eid, source_kind, source_id, **kw))
            self.ev_by_src[k] = eid
        return self.ev_by_src[k]

    def lot(self, source_kind: str, source_id: int, item_id: int, **kw) -> int:
        k = (source_kind, source_id)
        if k not in self.lot_by_src:
            lid = len(self.lots) + 1
            self.lots.append(_lot_row(lid, item_id, source_kind, source_id, **kw))
            self.lot_by_src[k] = lid
            self.lot_item[lid] = item_id
        return self.lot_by_src[k]

    def move(self, event_id: int, item_id: int, qty: float, *, at: str, rank: int, pool_key: str,
             source_kind: str, source_id: int | None, lot_id: int | None = None, company_id: int | None = None,
             run_id: int | None = None, value_usd: float | None = None, lot_value_usd: float | None = None,
             value_source: str = "frozen", bind_source: str = "") -> None:
        self.moves.append({"id": len(self.moves) + 1, "event_id": event_id, "item_id": item_id, "lot_id": lot_id,
                           "company_id": company_id, "run_id": run_id, "qty": qty, "value_usd": value_usd,
                           "lot_value_usd": lot_value_usd, "value_source": value_source,
                           "bind_source": bind_source or "", "at": at or "", "rank": rank, "pool_key": pool_key,
                           "source_kind": source_kind, "source_id": source_id})

    # ---------------------------------------------------- clicks and units
    def clicks(self) -> None:
        db = self.db
        self.runs = {r.id: r for r in db.query(M.ProductionRun).all()}
        for sr in db.query(M.StepRun).order_by(M.StepRun.id).all():
            run = self.runs.get(sr.run_id)
            self.event("step_run", sr.id, kind="step", at=sr.made_at or "", actor=sr.actor or "",
                       company_id=run.company_id if run else None, run_id=sr.run_id,
                       process_version_id=sr.process_version_id, step_key=sr.step_key or "",
                       step_label=sr.step_label or "", step_kind=sr.kind or "", units=sr.qty,
                       chosen=sr.chosen or "", note=sr.note or "")
        macs = {d_id: mac for d_id, mac in db.query(M.DeviceUnit.id, M.DeviceUnit.mac).all()}
        steps_of: dict[int, list] = defaultdict(list)
        for ts in (db.query(M.TwinStep.id, M.TwinStep.twin_id, M.TwinStep.step_run_id,
                            M.TwinStep.programming_run_id, M.TwinStep.deployment_version_id)
                   .order_by(M.TwinStep.id).all()):
            steps_of[ts.twin_id].append(ts)
        ev_at = {e["id"]: e["at"] for e in self.events}
        ev_kind = {e["id"]: e["step_kind"] for e in self.events}
        for tw in db.query(M.Twin).order_by(M.Twin.id).all():
            it = self.item(f"p{tw.project_id}", kind="product", project_id=tw.project_id)
            origin = self.runs.get(tw.origin_run_id)
            evs = [(self.ev_by_src.get(("step_run", ts.step_run_id)), ts) for ts in steps_of.get(tw.id, [])]
            evs = [(e, ts) for e, ts in evs if e is not None]
            dangling = len(steps_of.get(tw.id, [])) - len(evs)
            if dangling:
                self.findings["twin_steps_without_click"].append(tw.id)
            first = min(evs, key=lambda p: (ev_at[p[0]] or "9999", p[0]))[0] if evs else None
            lot = self.lot("twin", tw.id, it.id, company_id=origin.company_id if origin else None,
                           identifier=macs.get(tw.device_unit_id) if tw.device_unit_id else None,
                           device_unit_id=tw.device_unit_id, origin_run_id=tw.origin_run_id,
                           found=bool(tw.found), created_event_id=first,
                           at=(ev_at[first] if first else "") or "")
            for e, ts in evs:
                self.event_lots.append({"id": len(self.event_lots) + 1, "event_id": e, "lot_id": lot,
                                        "programming_run_id": ts.programming_run_id,
                                        "deployment_version_id": ts.deployment_version_id, "source_id": ts.id})
            if first is not None:
                self.move(first, it.id, 1.0, at=ev_at[first], rank=0, pool_key=it.key, lot_id=lot,
                          company_id=origin.company_id if origin else None, value_source="none",
                          source_kind="twin", source_id=tw.id)
            for e, _ts in evs:
                if ev_kind[e] == "scrap":
                    self.move(e, it.id, -1.0, at=ev_at[e], rank=2, pool_key=it.key, lot_id=lot,
                              company_id=origin.company_id if origin else None, value_source="none",
                              source_kind="twin", source_id=tw.id)

    def transformations(self) -> None:
        for t in (self.db.query(M.ProcessTransformation)
                  .filter(M.ProcessTransformation.voided_at.is_(None))
                  .order_by(M.ProcessTransformation.id).all()):
            out = self.db.get(M.ComponentStockAdjustment, t.output_adjustment_id) if t.output_adjustment_id else None
            units = int(t.qty) if float(t.qty or 0).is_integer() else None
            self.event("transformation", t.id, kind="transform", at=t.made_at or "", actor=t.actor or "",
                       company_id=out.company_id if out else None, run_id=t.production_run_id,
                       process_version_id=t.process_version_id, step_key=t.recipe_key or "",
                       step_label=t.recipe_label or "", units=units, note=t.note or "")

    # ------------------------------------------------------------ the pool
    def pool(self) -> None:
        db = self.db
        events, doc_by_id, _surcharge = run_actuals._pool_events(db, with_transfers=True)
        # Every lot exists before the first move: a draw may be bound to a lot
        # the replay reaches later (a purchase dated after the draw).
        for when, kind, row in events:
            if kind == "buy":
                it = self.part_item(row)
                doc = doc_by_id[row.document_id]
                self.lot("line", row.id, it.id, company_id=doc.company_id, label=f"L{row.id}",
                         at=when or "")
                self.lot_key[self.lot_by_src[("line", row.id)]] = run_actuals._key(row)
            elif kind == "adj" and (row.qty_delta or 0) > 0:
                mapped = self.maps.get(row.component_id) if row.transformation_id else None
                it = (self.item(f"c{mapped.item_component_id}", component_id=mapped.item_component_id)
                      if mapped else self.part_item(row))
                lid = self.lot("adjustment", row.id, it.id, company_id=row.company_id, label=f"A{row.id}",
                               at=when or "")
                self.lot_key[lid] = run_actuals._key(row)
        bindings: dict[int, list] = defaultdict(list)
        for b in db.query(M.ComponentConsumptionLot).order_by(M.ComponentConsumptionLot.id).all():
            bindings[b.consumption_id].append(b)
        doc_of_line = dict(db.query(M.RunCostLine.id, M.RunCostLine.document_id)
                           .filter(M.RunCostLine.id.in_(
                               [r.transfer_line_id for _w, k, r in events
                                if k == "use" and r.transfer_line_id] or [-1])).all())
        for when, kind, row in events:
            if kind == "buy":
                self._buy(when, row, doc_by_id[row.document_id])
            elif kind == "adj":
                self._adj(when, row)
            else:
                self._use(when, row, bindings.get(row.id, []), doc_by_id, doc_of_line)

    def _doc_event(self, doc: M.RunCostDocument) -> int:
        return self.event("document", doc.id, kind="transfer" if (doc.doc_type or "") == "transfer" else "receive",
                          at=doc.doc_date or "", company_id=doc.company_id,
                          note=f"{doc.supplier or ''} {doc.doc_number or ''}".strip())

    def _buy(self, when: str, li: M.RunCostLine, doc: M.RunCostDocument) -> None:
        ev = self._doc_event(doc)
        lot = self.lot_by_src[("line", li.id)]
        self.lots[lot - 1]["created_event_id"] = ev
        it_id = self.lot_item[lot]
        self.move(ev, it_id, li.qty or 0.0, at=when, rank=1, pool_key=run_actuals._key(li), lot_id=lot,
                  company_id=doc.company_id, value_source="invoice", source_kind="line", source_id=li.id)

    def _adj(self, when: str, a: M.ComponentStockAdjustment) -> None:
        q = a.qty_delta or 0.0
        ev = self.ev_by_src.get(("transformation", a.transformation_id)) if a.transformation_id else None
        if ev is None:
            ev = self.event("adjustment", a.id, kind="count", at=when, actor=a.actor or "",
                            company_id=a.company_id, run_id=a.charge_run_id,
                            note=f"{a.reason or ''}: {a.note or ''}")
        lot = self.lot_by_src.get(("adjustment", a.id)) if q > 0 else None
        if lot is not None:
            self.lots[lot - 1]["created_event_id"] = ev
        it_id = self.lot_item[lot] if lot is not None else self.part_item(a).id
        unit = a.unit_cost_usd
        self.move(ev, it_id, q, at=when, rank=0, pool_key=run_actuals._key(a), lot_id=lot,
                  company_id=a.company_id, run_id=a.charge_run_id,
                  value_usd=None if unit is None else q * unit,
                  lot_value_usd=(q * (unit or 0.0)) if q > 0 else None,
                  value_source="average" if unit is None else "adjustment",
                  source_kind="adjustment", source_id=a.id)
        mapped = self.maps.get(a.component_id) if (a.transformation_id and q > 0) else None
        if mapped is not None and lot is not None:
            for name, value in (mapped.properties or {}).items():
                self.properties.append({"id": len(self.properties) + 1, "lot_id": lot, "event_id": ev,
                                        "name": str(name)[:60], "value": value, "cleared": False})

    def _use(self, when: str, c: M.ComponentConsumption, binds: list, doc_by_id: dict,
             doc_of_line: dict) -> None:
        ev = None
        if c.step_run_id:
            ev = self.ev_by_src.get(("step_run", c.step_run_id))
            if ev is None:
                self.findings["draws_naming_a_missing_click"].append(c.id)
        if ev is None and c.transformation_id:
            ev = self.ev_by_src.get(("transformation", c.transformation_id))
        if ev is None and c.transfer_line_id and doc_of_line.get(c.transfer_line_id) in doc_by_id:
            ev = self._doc_event(doc_by_id[doc_of_line[c.transfer_line_id]])
        if ev is None:
            ev = self.event("consumption", c.id, kind="consume", at=when, company_id=c.company_id,
                            run_id=c.run_id, note=c.note or "")
        key = run_actuals._key(c)
        unit = c.unit_cost_usd
        source = "average" if unit is None else "frozen"
        covered = 0.0
        for b in binds:
            lot = (self.lot_by_src.get(("line", b.lot_line_id)) if b.lot_line_id
                   else self.lot_by_src.get(("adjustment", b.lot_adjustment_id)) if b.lot_adjustment_id
                   else None)
            if lot is None:
                continue
            q = b.qty or 0.0
            covered += q
            it_id = self.lot_item[lot]
            if self.lot_key.get(lot) != key:
                self.findings["draws_bound_to_a_lot_of_another_identity"].append(c.id)
            self.move(ev, it_id, -q, at=when, rank=2, pool_key=key, lot_id=lot, company_id=c.company_id,
                      run_id=c.run_id, value_usd=None if unit is None else -q * unit,
                      lot_value_usd=-q * (b.unit_cost_usd or 0.0), value_source=source,
                      bind_source=b.source or "", source_kind="consumption", source_id=c.id)
        rest = (c.qty or 0.0) - covered
        if abs(rest) > EPS:
            if rest < 0:
                self.findings["draws_bound_beyond_their_quantity"].append(c.id)
            self.move(ev, self.part_item(c).id, -rest, at=when, rank=2, pool_key=key,
                      company_id=c.company_id, run_id=c.run_id,
                      value_usd=None if unit is None else -rest * unit, value_source=source,
                      bind_source="unallocated" if rest > 0 else "over_bound",
                      source_kind="consumption", source_id=c.id)

    # ------------------------------------------------------------- the aims
    def cost_aims(self) -> None:
        db = self.db
        rows = []
        for lid, tid in (db.query(M.RunCostLine.id, M.RunCostLine.transformation_id)
                         .filter(M.RunCostLine.transformation_id.isnot(None),
                                 M.RunCostLine.voided_at.is_(None)).all()):
            ev = self.ev_by_src.get(("transformation", tid))
            if ev is not None:
                rows.append({"line_id": lid, "event_id": ev, "run_id": None, "step_key": "",
                             "source_kind": "transformation"})
        for lid, srid in db.query(M.CostLineStep.line_id, M.CostLineStep.step_run_id).all():
            ev = self.ev_by_src.get(("step_run", srid))
            if ev is not None:
                rows.append({"line_id": lid, "event_id": ev, "run_id": None, "step_key": "",
                             "source_kind": "click"})
        for lid, rid, key in db.query(M.CostLineStepKey.line_id, M.CostLineStepKey.run_id,
                                      M.CostLineStepKey.step_key).all():
            rows.append({"line_id": lid, "event_id": None, "run_id": rid, "step_key": key,
                         "source_kind": "step_key"})
        for n, r in enumerate(rows, start=1):
            r["id"] = n
        self.aims = rows

    # ----------------------------------------------------------- the write
    def write(self) -> None:
        db = self.db
        for table, rows in (("material_events", self.events), ("material_lots", self.lots),
                            ("material_moves", self.moves), ("material_event_lots", self.event_lots),
                            ("material_properties", self.properties), ("material_cost_aims", self.aims)):
            if rows:
                db.execute(M.Base.metadata.tables[table].insert(), rows)
        for table in SHADOW:
            db.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT max(id) FROM {table}), 0) + 1, false)"))


def rebuild(db: Session) -> dict:
    """Empty the shadow and project it again. The caller commits; a dry run
    is a caller that rolls back."""
    t0 = time.monotonic()
    db.execute(text("TRUNCATE " + ", ".join(SHADOW) + " RESTART IDENTITY"))
    b = _Builder(db)
    b.clicks()
    b.transformations()
    b.pool()
    b.cost_aims()
    b.write()
    db.flush()
    return {
        "events": len(b.events), "lots": len(b.lots), "moves": len(b.moves),
        "event_lots": len(b.event_lots), "properties": len(b.properties), "cost_aims": len(b.aims),
        "items": len(b.items), "new_items": b.new_items,
        "state_maps": len(b.maps),
        "findings": {k: {"count": len(v), "sample": sorted(set(v))[:20]} for k, v in b.findings.items()},
        "seconds": round(time.monotonic() - t0, 2),
    }
