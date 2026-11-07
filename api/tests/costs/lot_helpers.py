"""Test set-up: draws that already hold lots.

No writer picks lots any more (decision 0105). Bound draws still exist: JLC names
the lots of what it drew, and the history job of 2026-10 bound the older draws. The
guards on those bindings are what the tests check, so a test must be able to make
one. This is the old job's rule: oldest first, split across lots.
"""
from app import models as M
from app.services import lots as L
from app.services import run_actuals as ra


def pick(db, company_id, component_id, mpn, lcsc, qty, day) -> dict:
    """The lots `qty` units take on `day`, oldest first. `company_id` limits them
    to that company's purchases. Writes nothing."""
    want = set(ra._identity_keys(component_id, mpn or "", lcsc or ""))
    db.flush()
    lots = L.lot_state(db)["lots"]
    docs = dict(db.query(M.RunCostDocument.id, M.RunCostDocument.company_id).all())
    found = []
    for key, lot in lots.items():
        if (lot["date"] or "9999") > (day or "9999") or lot["qty_remaining"] <= L.CLOSED_EPS:
            continue
        if company_id is not None and docs.get(lot["document_id"]) != company_id:
            continue
        if set(ra._identity_keys(lot["component_id"], lot["mpn"], lot["lcsc"])) & want:
            found.append((lot["date"] or "", lot["id"], key, lot))
    need, out = float(qty), []
    for _d, _i, key, lot in sorted(found, key=lambda x: x[:3]):
        if need <= L.CLOSED_EPS:
            break
        take = min(lot["qty_remaining"], need)
        need -= take
        out.append({"lot_line_id": lot["id"] if lot["kind"] == "line" else None,
                    "lot_id": lot["id"] if lot["kind"] == "stock" else None,
                    "lot": key, "qty": round(take, 6), "unit_cost_usd": lot["unit_cost_usd"]})
    return {"bindings": out, "uncovered": round(max(need, 0.0), 6)}


def bind(db, draw, picked: dict, source: str = "fifo_history") -> None:
    for b in picked["bindings"]:
        db.add(M.MaterialMoveLot(move_id=draw.id, lot_line_id=b.get("lot_line_id"), lot_id=b.get("lot_id"),
                                 qty=b["qty"], unit_cost_usd=b["unit_cost_usd"] or 0.0, source=source))
    db.flush()
