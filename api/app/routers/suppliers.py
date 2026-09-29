"""The supplier register and a component's suppliers and prices — decision 0055.

The register is SHARED reference data, so its writes are admin-only and listed
in `tests/auth/test_role_gates.py`; reading it is open. A component's links,
its own supplier order and the prices typed against a link are library work,
open to any signed-in user. The rules live in `services/suppliers.py`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import ladder, suppliers
from ..services.suppliers import SupplierError
from .users import require_admin
from .util import acting_name, audit

router = APIRouter(prefix="/api", tags=["suppliers"])


def _actor(admin: M.User | None) -> str:
    return admin.username if admin is not None else "dev"


def _refuse(e: SupplierError):
    raise HTTPException(422, str(e)) from None


def supplier_json(s: M.Supplier, linked: int = 0) -> dict:
    return {"id": s.id, "name": s.name, "website": s.website, "notes": s.notes,
            "connector": s.connector, "position": s.position, "linked_components": linked}


# ------------------------------------------------------------------ register
@router.get("/suppliers")
def list_suppliers(db: Session = Depends(get_db)):
    """The register in library order. Open to everybody: the order decides
    every BOM price, so anybody reading a BOM needs to see it."""
    linked = dict(db.query(M.ComponentSupplier.supplier_id, func.count(M.ComponentSupplier.id))
                  .group_by(M.ComponentSupplier.supplier_id).all())
    return [supplier_json(s, linked.get(s.id, 0)) for s in suppliers.ordered(db)]


class SupplierIn(BaseModel):
    name: str
    website: str = ""
    notes: str = ""


class SupplierPatch(BaseModel):
    website: str | None = None
    notes: str | None = None


class OrderIn(BaseModel):
    ids: list[int]


@router.put("/suppliers/order")
def set_library_order(body: OrderIn, db: Session = Depends(get_db),
                      admin: M.User = Depends(require_admin)):
    """Reorder the register. Writes a price-history snapshot for every priced
    component, so runs already priced keep the order of their own date."""
    try:
        n = suppliers.set_library_order(db, body.ids)
    except SupplierError as e:
        _refuse(e)
    audit(db, "supplier.order", "supplier", "library",
          details={"order": [s.name for s in suppliers.ordered(db)], "snapshots": n},
          actor=_actor(admin))
    db.commit()
    return list_suppliers(db)


@router.post("/suppliers")
def create_supplier(body: SupplierIn, db: Session = Depends(get_db),
                    admin: M.User = Depends(require_admin)):
    try:
        s = suppliers.create(db, body.name, body.website, body.notes, actor=acting_name())
    except SupplierError as e:
        _refuse(e)
    audit(db, "supplier.create", "supplier", s.id, details={"name": s.name}, actor=_actor(admin))
    db.commit()
    return supplier_json(s)


@router.patch("/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, body: SupplierPatch, db: Session = Depends(get_db),
                    admin: M.User = Depends(require_admin)):
    """Website and notes only. The name is the key prices refer to and never
    changes (`models.Supplier`)."""
    s = db.get(M.Supplier, supplier_id)
    if s is None:
        raise HTTPException(404, "supplier not found")
    if body.website is not None:
        s.website = body.website.strip()
    if body.notes is not None:
        s.notes = body.notes.strip()
    db.commit()
    return supplier_json(s)


@router.delete("/suppliers/{supplier_id}")
def delete_supplier(supplier_id: int, db: Session = Depends(get_db),
                    admin: M.User = Depends(require_admin)):
    s = db.get(M.Supplier, supplier_id)
    if s is None:
        raise HTTPException(404, "supplier not found")
    name = s.name
    try:
        suppliers.delete(db, s)
    except SupplierError as e:
        _refuse(e)
    audit(db, "supplier.delete", "supplier", supplier_id, details={"name": name}, actor=_actor(admin))
    db.commit()
    return {"ok": True}


# ------------------------------------------------- a component's suppliers
def _component(db: Session, comp_id: int) -> M.Component:
    comp = db.get(M.Component, comp_id)
    if comp is None:
        raise HTTPException(404, "component not found")
    return comp


def _link(db: Session, comp_id: int, link_id: int) -> M.ComponentSupplier:
    row = db.get(M.ComponentSupplier, link_id)
    if row is None or row.component_id != comp_id:
        raise HTTPException(404, "supplier link not found on this component")
    return row


@router.get("/components/{comp_id}/price-points")
def list_price_points(comp_id: int, db: Session = Depends(get_db)):
    """Everything the component page's Suppliers panel shows: every price
    point with its rank, the source that prices the part, the links in the
    order that picks it, and the stock pools."""
    _component(db, comp_id)
    rows = ladder.live_points(db, [comp_id])[comp_id]
    legacy_summary = []
    if not rows:
        # A part priced only by its legacy summary row: the BOM prices it from
        # there (`project_bom._component_data`), so the panel must show it.
        pr = db.query(M.ComponentPrice).filter_by(component_id=comp_id).first()
        if pr is not None and pr.source not in ladder.AUTO_SOURCES:
            legacy_summary = ladder.summary_points(pr)
            suppliers.attach_ranks(db, {comp_id: legacy_summary})
    winner = ladder.effective_points(rows or legacy_summary)
    registered = {s.name for s in suppliers.ordered(db)}
    priced = {p.source for p in rows}
    supply = db.query(M.ComponentSupply).filter_by(component_id=comp_id).first()
    private = db.query(M.JlcStockItem).filter_by(component_id=comp_id).first()
    links = suppliers.links_for(db, comp_id)
    return {
        "points": [
            {"id": p.id, "source": p.source, "qty_from": p.qty_from, "unit_price": p.unit_price,
             "currency": p.currency, "updated_at": p.updated_at.isoformat(), "rank": p.rank}
            for p in rows
        ],
        # Hand-entered prices that name no supplier: the old "Manual" rows,
        # and a price that lives only in the summary. Each can be attributed
        # to a link.
        "legacy_sources": sorted({p.source for p in rows if p.source not in registered}),
        "legacy_summary": [
            {"source": p.source, "qty_from": p.qty_from, "unit_price": p.unit_price,
             "currency": p.currency}
            for p in legacy_summary
        ],
        "effective_source": winner[0].source if winner else None,
        "own_order": any(ln.position is not None for ln in links),
        "suppliers": [
            {"id": ln.id, "supplier_id": ln.supplier_id, "supplier": ln.supplier.name,
             "connector": ln.supplier.connector, "part_number": ln.part_number, "url": ln.url,
             "note": ln.note, "position": ln.position, "origin": ln.origin,
             "has_prices": ln.supplier.name in priced}
            for ln in links
        ],
        # Three DISTINCT pools: stock = LCSC retail, jlc_stock = JLCPCB
        # assembly parts, private_qty = the user's own JLC library.
        "supply": {
            "stock": supply.stock, "jlc_stock": supply.jlc_stock,
            "moq": supply.moq, "order_multiple": supply.order_multiple,
            "checked_at": supply.checked_at.isoformat() if supply.checked_at else None,
        } if supply else None,
        "private_qty": private.qty if private else 0,
    }


@router.post("/components/{comp_id}/price-points/refresh")
def refresh_price_points(comp_id: int, db: Session = Depends(get_db)):
    comp = _component(db, comp_id)
    cv = next((v for v in comp.versions if v.id == comp.current_version_id), None)
    lcsc = ladder.lcsc_part_of(cv) if cv else ""
    if not lcsc:
        raise HTTPException(422, "component has no LCSC Part")
    if not ladder.refresh_component(db, comp_id, lcsc):
        raise HTTPException(502, "neither JLCPCB nor LCSC returned a price ladder")
    return list_price_points(comp_id, db)


class LinkIn(BaseModel):
    supplier_id: int
    part_number: str = ""
    url: str = ""
    note: str = ""


class LinkPatch(BaseModel):
    part_number: str | None = None
    url: str | None = None
    note: str | None = None


class TierIn(BaseModel):
    qty_from: int
    unit_price: float
    currency: str = "USD"


class ComponentOrderIn(BaseModel):
    # None returns the component to the library order.
    link_ids: list[int] | None


class AttributeIn(BaseModel):
    source: str
    link_id: int


@router.post("/components/{comp_id}/suppliers")
def add_link(comp_id: int, body: LinkIn, db: Session = Depends(get_db)):
    _component(db, comp_id)
    s = db.get(M.Supplier, body.supplier_id)
    if s is None:
        raise HTTPException(404, "supplier not found")
    if s.connector:
        raise HTTPException(422, f"the {s.name} link follows the LCSC Part property — set that instead")
    if db.query(M.ComponentSupplier.id).filter_by(component_id=comp_id, supplier_id=s.id).first():
        raise HTTPException(409, f"this component is already linked to {s.name}")
    suppliers.link(db, comp_id, s, body.part_number, body.url, body.note, actor=acting_name())
    db.commit()
    return list_price_points(comp_id, db)


@router.patch("/components/{comp_id}/suppliers/{link_id}")
def update_link(comp_id: int, link_id: int, body: LinkPatch, db: Session = Depends(get_db)):
    row = _link(db, comp_id, link_id)
    if row.supplier.connector and body.part_number is not None and body.part_number != row.part_number:
        raise HTTPException(422, f"the {row.supplier.name} part number follows the LCSC Part property")
    suppliers.link(db, comp_id, row.supplier, body.part_number, body.url, body.note)
    db.commit()
    return list_price_points(comp_id, db)


@router.delete("/components/{comp_id}/suppliers/{link_id}")
def delete_link(comp_id: int, link_id: int, db: Session = Depends(get_db)):
    row = _link(db, comp_id, link_id)
    try:
        suppliers.remove_link(db, row)
    except SupplierError as e:
        _refuse(e)
    db.commit()
    return list_price_points(comp_id, db)


@router.put("/components/{comp_id}/suppliers/{link_id}/prices")
def set_link_prices(comp_id: int, link_id: int, tiers: list[TierIn], db: Session = Depends(get_db)):
    """Replace the prices typed against one link. The first prices a link gets
    move it to the top of the component's order."""
    row = _link(db, comp_id, link_id)
    try:
        suppliers.set_link_prices(db, row, [(t.qty_from, t.unit_price, t.currency) for t in tiers])
    except SupplierError as e:
        _refuse(e)
    db.commit()
    return list_price_points(comp_id, db)


@router.put("/components/{comp_id}/supplier-order")
def set_component_order(comp_id: int, body: ComponentOrderIn, db: Session = Depends(get_db)):
    _component(db, comp_id)
    try:
        suppliers.set_component_order(db, comp_id, body.link_ids)
    except SupplierError as e:
        _refuse(e)
    db.commit()
    return list_price_points(comp_id, db)


@router.post("/components/{comp_id}/price-points/attribute")
def attribute_legacy(comp_id: int, body: AttributeIn, db: Session = Depends(get_db)):
    """Move a price that names no supplier ("Manual") onto a supplier link."""
    row = _link(db, comp_id, body.link_id)
    try:
        suppliers.attribute_legacy(db, row, body.source)
    except SupplierError as e:
        _refuse(e)
    db.commit()
    return list_price_points(comp_id, db)
