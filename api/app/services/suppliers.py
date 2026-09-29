"""The supplier register, component-to-supplier links, and the supplier order
that decides which source prices a part — decision 0055. Read
docs/reference/suppliers.md before changing the order rule.

Three facts the rest of the platform relies on:

1. **One source gives the whole ladder.** `ladder.effective_points` takes the
   source with the lowest rank, and no other source mixes in by quantity
   break. The ranks come from `ranks()` here: a price that names no supplier
   (the legacy "Manual" rows) first, then the component's own order (links
   with a `position`), then the library order (the register's `position`).
2. **The order is dated.** `ladder._effective_state` writes each point's rank
   into the price-history snapshot, so a production run is priced by the order
   that was in effect on its date. Every function here that changes an order
   therefore records price history for what it affects, in the same
   transaction. Skip that, and a reorder today reprices a closed run.
3. **A supplier's name is a key.** Price rows and snapshots name it, so it
   never changes once created (`models.Supplier`).
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from .. import models as M

log = logging.getLogger(__name__)

#: The register a fresh deployment starts with, in library order. JLCPCB and
#: LCSC are the two the platform refreshes; the other three are listed so a
#: price can name them before their connections exist (phase 2).
SEED = (
    ("JLCPCB", "jlcpcb", "https://jlcpcb.com/parts"),
    ("LCSC", "lcsc", "https://www.lcsc.com"),
    ("TME", "", "https://www.tme.eu"),
    ("Mouser", "", "https://www.mouser.com"),
    ("DigiKey", "", "https://www.digikey.com"),
)

#: The two suppliers whose links follow the component's `LCSC Part`.
LCSC_PART_SUPPLIERS = ("JLCPCB", "LCSC")

#: Spellings a `Supplier N` value may use for a supplier already registered.
_ALIASES = {"digi-key": "DigiKey", "digikey": "DigiKey", "mouser electronics": "Mouser",
            "tme.eu": "TME", "jlc": "JLCPCB"}

#: The rank of a price that names no supplier. It sorts before every supplier,
#: so a legacy hand-entered price keeps winning, as it did before the register.
LEGACY_RANK = -1

_SUPPLIER_KEY = re.compile(r"^Supplier( Part Number)? \d+$")

MIGRATION_ACTOR = "migration"
MIGRATION_COMMENT = "Supplier fields moved to the supplier register (decision 0055)"


class SupplierError(ValueError):
    """A request the register refuses. The message is shown to the user."""


def is_supplier_key(key: str) -> bool:
    """`Supplier N` and `Supplier Part Number N` — the retired properties.

    The component editor and the agent refuse them, the generator drops them,
    and the sign-off carry treats them as non-material."""
    return bool(_SUPPLIER_KEY.match(key or ""))


# ------------------------------------------------------------------ register
def ordered(db: Session) -> list[M.Supplier]:
    """The register in library order."""
    return db.query(M.Supplier).order_by(M.Supplier.position, M.Supplier.id).all()


def ensure_register(db: Session) -> int:
    """Seed an EMPTY register. Never adds to a register an admin has edited:
    a supplier an admin deleted must not come back on the next start."""
    if db.query(M.Supplier.id).first() is not None:
        return 0
    for i, (name, connector, website) in enumerate(SEED):
        db.add(M.Supplier(name=name, connector=connector, website=website, position=i,
                          created_by=MIGRATION_ACTOR))
    db.flush()
    return len(SEED)


def by_name(db: Session, name: str) -> M.Supplier | None:
    """Exact name first, then a case-insensitive match or a known alias."""
    name = (name or "").strip()
    if not name:
        return None
    s = db.query(M.Supplier).filter(M.Supplier.name == name).first()
    if s is not None:
        return s
    canonical = _ALIASES.get(name.lower(), name)
    return db.query(M.Supplier).filter(func.lower(M.Supplier.name) == canonical.lower()).first()


def create(db: Session, name: str, website: str = "", notes: str = "",
           actor: str = "user") -> M.Supplier:
    name = (name or "").strip()
    if not name:
        raise SupplierError("a supplier needs a name")
    if by_name(db, name) is not None:
        raise SupplierError(f"supplier {name!r} already exists")
    last = db.query(func.max(M.Supplier.position)).scalar()
    s = M.Supplier(name=name, website=website.strip(), notes=notes.strip(),
                   position=(last + 1) if last is not None else 0, created_by=actor)
    db.add(s)
    db.flush()
    return s


def delete(db: Session, supplier: M.Supplier) -> None:
    """Only a supplier nothing refers to. A price row or a snapshot that names
    it would be left pointing at nothing."""
    if supplier.connector:
        raise SupplierError(f"{supplier.name} is refreshed by the platform and cannot be removed")
    if db.query(M.ComponentSupplier.id).filter_by(supplier_id=supplier.id).first() is not None:
        raise SupplierError(f"{supplier.name} is linked to components — remove the links first")
    if db.query(M.ComponentPricePoint.id).filter_by(source=supplier.name).first() is not None:
        raise SupplierError(f"{supplier.name} has prices — remove them first")
    db.delete(supplier)
    db.flush()


def set_library_order(db: Session, supplier_ids: list[int]) -> int:
    """Reorder the register. Returns how many components got a new
    price-history snapshot — every priced component, because each snapshot
    records the order the component was priced by."""
    from . import ladder

    suppliers = {s.id: s for s in db.query(M.Supplier).all()}
    if sorted(supplier_ids) != sorted(suppliers):
        raise SupplierError("the order must name every supplier exactly once")
    for i, sid in enumerate(supplier_ids):
        suppliers[sid].position = i
    db.flush()
    priced = {cid for (cid,) in db.query(M.ComponentPricePoint.component_id).distinct()}
    priced |= {cid for (cid,) in db.query(M.ComponentPrice.component_id).distinct()}
    return sum(1 for cid in sorted(priced) if ladder.record_price_history(db, cid))


# ---------------------------------------------------------------- the order
def ranks(db: Session, component_ids) -> dict[int, dict[str, int]]:
    """Each component's supplier order as {source name: rank}, lowest first.

    The component's own order (links with a `position`) comes first, then
    every other supplier in library order. A source that is not a supplier
    has no entry here; `attach_ranks` gives it `LEGACY_RANK`."""
    ids = set(component_ids)
    library = [s.name for s in ordered(db)]
    own: dict[int, list[tuple[int, int, str]]] = {}
    if ids:
        q = (db.query(M.ComponentSupplier.component_id, M.ComponentSupplier.position,
                      M.ComponentSupplier.id, M.Supplier.name)
             .join(M.Supplier, M.Supplier.id == M.ComponentSupplier.supplier_id)
             .filter(M.ComponentSupplier.component_id.in_(ids),
                     M.ComponentSupplier.position.isnot(None)))
        for cid, pos, lid, name in q:
            own.setdefault(cid, []).append((pos, lid, name))
    out: dict[int, dict[str, int]] = {}
    for cid in ids:
        seq = [name for _, _, name in sorted(own.get(cid, []))]
        seq += [n for n in library if n not in seq]
        out[cid] = {n: i for i, n in enumerate(seq)}
    return out


def attach_ranks(db: Session, points_by_comp: dict[int, list]) -> None:
    """Give each LIVE price point a `rank` (a plain attribute, not a column),
    which `ladder.effective_points` resolves by."""
    r = ranks(db, points_by_comp.keys())
    for cid, pts in points_by_comp.items():
        m = r.get(cid, {})
        for p in pts:
            p.rank = m.get(p.source, LEGACY_RANK)


# -------------------------------------------------------------------- links
def links_for(db: Session, component_id: int) -> list[M.ComponentSupplier]:
    """The component's links in its effective order."""
    order = ranks(db, [component_id]).get(component_id, {})
    rows = (db.query(M.ComponentSupplier).options(selectinload(M.ComponentSupplier.supplier))
            .filter_by(component_id=component_id).all())
    return sorted(rows, key=lambda r: (order.get(r.supplier.name, 10**6), r.id))


def link(db: Session, component_id: int, supplier: M.Supplier, part_number: str | None = None,
         url: str | None = None, note: str | None = None, origin: str = "user",
         actor: str = "user") -> M.ComponentSupplier:
    """Create the component's link to `supplier`, or update the fields given.
    One link per component and supplier."""
    row = (db.query(M.ComponentSupplier)
           .filter_by(component_id=component_id, supplier_id=supplier.id).first())
    if row is None:
        row = M.ComponentSupplier(component_id=component_id, supplier_id=supplier.id,
                                  origin=origin, created_by=actor)
        row.supplier = supplier
        db.add(row)
    if part_number is not None:
        row.part_number = part_number.strip()
    if url is not None:
        row.url = url.strip()
    if note is not None:
        row.note = note.strip()
    db.flush()
    return row


def ensure_lcsc_links(db: Session, component_id: int, lcsc: str) -> int:
    """Keep the JLCPCB and LCSC links in step with `LCSC Part`. Returns how many
    links were created or corrected. A link a user typed is left alone."""
    lcsc = (lcsc or "").strip()
    if not lcsc:
        return 0
    n = 0
    for name in LCSC_PART_SUPPLIERS:
        s = db.query(M.Supplier).filter_by(name=name).first()
        if s is None:
            continue
        row = (db.query(M.ComponentSupplier)
               .filter_by(component_id=component_id, supplier_id=s.id).first())
        if row is None:
            link(db, component_id, s, part_number=lcsc, origin="lcsc_part", actor=MIGRATION_ACTOR)
            n += 1
        elif row.origin == "lcsc_part" and row.part_number != lcsc:
            row.part_number = lcsc
            n += 1
    return n


def remove_link(db: Session, row: M.ComponentSupplier) -> None:
    """Remove a link and the prices typed against it. A link that follows
    `LCSC Part` is removed by removing the property, not here."""
    from . import ladder

    if row.supplier.connector:
        raise SupplierError(f"the {row.supplier.name} link follows the LCSC Part property — "
                            "edit that instead")
    cid = row.component_id
    ladder.record_price_history(db, cid)
    db.query(M.ComponentPricePoint).filter_by(component_id=cid, source=row.supplier.name) \
        .delete(synchronize_session=False)
    db.delete(row)
    db.flush()
    ladder.record_price_history(db, cid)


def _renumber(rows: list[M.ComponentSupplier]) -> None:
    for i, r in enumerate(rows):
        r.position = i


def set_component_order(db: Session, component_id: int, link_ids: list[int] | None) -> None:
    """Set the component's own supplier order. `None` returns it to the library
    order. Links left out of `link_ids` follow the library order after it."""
    from . import ladder

    rows = db.query(M.ComponentSupplier).filter_by(component_id=component_id).all()
    by_id = {r.id: r for r in rows}
    if link_ids is None:
        for r in rows:
            r.position = None
    else:
        if len(set(link_ids)) != len(link_ids) or any(i not in by_id for i in link_ids):
            raise SupplierError("the order names a link this component does not have")
        for r in rows:
            r.position = None
        _renumber([by_id[i] for i in link_ids])
    db.flush()
    ladder.record_price_history(db, component_id)


def move_to_top(db: Session, row: M.ComponentSupplier) -> None:
    """Put one link first in its component's own order. Every link keeps its
    place relative to the others: the effective order is written out whole, so
    the links that followed the library order stay where they were."""
    rows = links_for(db, row.component_id)
    _renumber([row] + [r for r in rows if r.id != row.id])
    db.flush()


def _check_tiers(tiers: list[tuple[int, float, str]]) -> None:
    seen = set()
    for q, p, _cur in tiers:
        if q < 1 or p < 0:
            raise SupplierError("a quantity break must be 1 or more and a price 0 or more")
        if q in seen:
            raise SupplierError(f"quantity break {q} appears twice")
        seen.add(q)


def _write_link_points(db: Session, row: M.ComponentSupplier,
                       tiers: list[tuple[int, float, str]]) -> None:
    """Replace the link's points and apply the move-to-top rule. Records no
    history: the callers bracket it with one pair of snapshots."""
    cid, source = row.component_id, row.supplier.name
    had = db.query(M.ComponentPricePoint.id).filter_by(component_id=cid, source=source).first()
    db.query(M.ComponentPricePoint).filter_by(component_id=cid, source=source) \
        .delete(synchronize_session=False)
    now = M.utcnow()
    for q, p, cur in sorted(tiers):
        db.add(M.ComponentPricePoint(component_id=cid, source=source, qty_from=q, unit_price=p,
                                     currency=(cur or "USD").strip().upper() or "USD",
                                     updated_at=now))
    db.flush()
    if tiers and had is None:
        move_to_top(db, row)


def set_link_prices(db: Session, row: M.ComponentSupplier,
                    tiers: list[tuple[int, float, str]]) -> None:
    """Replace the prices typed against one link: [(qty_from, unit_price,
    currency)]. The FIRST hand-entered price a link gets moves it to the top
    of its component's order (user decision 2026-09-29) — somebody typed a
    quote because they mean to buy there. The user can move it down after."""
    from . import ladder

    if row.supplier.connector:
        raise SupplierError(f"{row.supplier.name} prices are refreshed by the platform")
    _check_tiers(tiers)
    ladder.record_price_history(db, row.component_id)
    _write_link_points(db, row, tiers)
    ladder.record_price_history(db, row.component_id)


def attribute_legacy(db: Session, row: M.ComponentSupplier, source: str) -> int:
    """Move the prices of a source that names no supplier ("Manual") onto a
    link, unchanged: same breaks, same prices, same currency. A part priced
    only by its legacy summary row takes the ladder the BOM already read from
    it (`ladder.summary_points`). Returns how many breaks moved."""
    from . import ladder

    if row.supplier.connector:
        raise SupplierError(f"{row.supplier.name} prices are refreshed by the platform")
    cid = row.component_id
    if db.query(M.Supplier.id).filter_by(name=source).first() is not None:
        raise SupplierError(f"{source!r} is a supplier already, not an unattributed price")
    if db.query(M.ComponentPricePoint.id).filter_by(component_id=cid, source=row.supplier.name).first():
        raise SupplierError(f"{row.supplier.name} already has prices on this component — "
                            "remove them first")
    pts = db.query(M.ComponentPricePoint).filter_by(component_id=cid, source=source).all()
    if pts:
        tiers = [(p.qty_from, p.unit_price, p.currency) for p in pts]
    else:
        any_point = db.query(M.ComponentPricePoint.id).filter_by(component_id=cid).first()
        pr = db.query(M.ComponentPrice).filter_by(component_id=cid).first()
        if any_point is not None or pr is None or (pr.source or "Manual") != source:
            raise SupplierError(f"this component has no {source!r} prices")
        tiers = [(p.qty_from, p.unit_price, p.currency) for p in ladder.summary_points(pr)]
    if not tiers:
        raise SupplierError(f"this component has no {source!r} prices")
    ladder.record_price_history(db, cid)
    db.query(M.ComponentPricePoint).filter_by(component_id=cid, source=source) \
        .delete(synchronize_session=False)
    _write_link_points(db, row, tiers)
    ladder.record_price_history(db, cid)
    return len(tiers)


# ---------------------------------------------------------------- migration
def _supplier_pairs(cv: M.ComponentVersion) -> list[tuple[str, str]]:
    """(supplier, part number) from the retired properties, in N order."""
    sup, pn = {}, {}
    for p in cv.properties:
        m = _SUPPLIER_KEY.match(p.key)
        if not m or p.is_null or p.value is None:
            continue
        n = int(p.key.rsplit(" ", 1)[1])
        (pn if m.group(1) else sup)[n] = p.value.strip()
    return [(sup[n], pn.get(n, "")) for n in sorted(sup) if sup[n]]


def _republish_without_supplier_keys(db: Session, comp: M.Component,
                                     cv: M.ComponentVersion) -> set[str]:
    """Publish the component again with every `Supplier` key removed.

    The new version pins the SAME datasheet versions as the old one. A publish
    would otherwise pin today's revision, and a datasheet revised since the
    last publish would then refuse the review carry — the migration would
    strip a verification for a reason it did not cause."""
    from .publish import publish_component_version

    last_no = db.query(func.max(M.ComponentVersion.version_no)) \
        .filter_by(component_id=comp.id).scalar() or 0
    new = M.ComponentVersion(
        component_id=comp.id, version_no=last_no + 1, base_component=cv.base_component,
        symbol_version_id=cv.symbol_version_id, footprint_version_id=cv.footprint_version_id,
        category_id=cv.category_id, removed_properties=cv.removed_properties,
        created_by=MIGRATION_ACTOR, comment=MIGRATION_COMMENT,
    )
    keep = [p for p in cv.properties if not is_supplier_key(p.key)]
    for i, p in enumerate(keep):
        new.properties.append(M.ComponentProperty(
            position=i, key=p.key, value=p.value, is_null=p.is_null, hide=p.hide,
            show_name=p.show_name, layout=p.layout))
    db.add(new)
    db.flush()
    for pin in db.query(M.ComponentVersionDatasheet).filter_by(component_version_id=cv.id):
        db.add(M.ComponentVersionDatasheet(component_version_id=new.id,
                                           datasheet_id=pin.datasheet_id,
                                           datasheet_version_id=pin.datasheet_version_id))
    db.flush()
    # BEFORE the publish: it warms the conformance cache for the new version,
    # and a cache computed without the re-pinned exception would read the
    # excused item as open until something re-evaluated it.
    _repin_exceptions(db, comp, cv, new)
    result = publish_component_version(db, comp, new, actor=MIGRATION_ACTOR)
    return result["tops"]


def _repin_exceptions(db: Session, comp: M.Component, old_cv: M.ComponentVersion,
                      new_cv: M.ComponentVersion) -> int:
    """Carry each standing exception pinned to the component's data across the
    migration.

    `$property_sha` digests EVERY property, so removing the `Supplier` keys
    changes it and every exception pinned to it would lapse — measured on the
    production copy: four parts fell from `checked` to `partial` or lost an
    excused finding. The decision was about data that did not change, so it is
    re-granted against the new digest. Exceptions are append-only: the old row
    is revoked with a reason naming this migration, and the new one keeps its
    key, variant, reason, note, evidence and actor type. An exception that had
    ALREADY lapsed stays lapsed."""
    from . import exceptions
    from .checklists import _property_sha

    old_sha, new_sha = _property_sha(old_cv), _property_sha(new_cv)
    if old_sha == new_sha:
        return 0
    n = 0
    for exc in exceptions.live_for(db, "component", comp.id).values():
        if (exc.depends_on or {}).get("$property_sha") != old_sha:
            continue
        exceptions.revoke(db, exc, MIGRATION_ACTOR,
                          f"Re-pinned: {MIGRATION_COMMENT}, which changed the component's data digest")
        exceptions.grant(db, "component", comp, exc.key, reason=exc.reason, note=exc.note,
                         actor=MIGRATION_ACTOR, actor_type=exc.actor_type, variant=exc.variant,
                         evidence=exc.evidence,
                         depends_on={**exc.depends_on, "$property_sha": new_sha})
        n += 1
    return n


def migrate(db: Session) -> dict:
    """Move `Supplier N` / `Supplier Part Number N` into links, and give every
    component with an `LCSC Part` its JLCPCB and LCSC links. Idempotent: a
    component that carries no `Supplier` key is not republished, and a link
    that exists is not duplicated. The caller commits and refreshes the mirror
    for the returned `tops`."""
    report = {"seeded": ensure_register(db), "republished": 0, "links": 0, "lcsc_links": 0,
              "created_suppliers": [], "lcsc_mismatch": [], "tops": set()}
    comps = db.query(M.Component).filter(M.Component.current_version_id.isnot(None)).all()
    cvs = {cv.id: cv for cv in db.query(M.ComponentVersion)
           .options(selectinload(M.ComponentVersion.properties))
           .filter(M.ComponentVersion.id.in_([c.current_version_id for c in comps]))}
    for comp in comps:
        cv = cvs.get(comp.current_version_id)
        if cv is None:
            continue
        lcsc = next((p.value.strip() for p in cv.properties
                     if p.key == "LCSC Part" and not p.is_null and p.value and p.value.strip()), "")
        for name, pn in _supplier_pairs(cv):
            s = by_name(db, name)
            if s is None:
                s = create(db, name, actor=MIGRATION_ACTOR)
                report["created_suppliers"].append(s.name)
            if s.name in LCSC_PART_SUPPLIERS:
                # `LCSC Part` is the authority for these two links.
                if pn and pn != lcsc:
                    report["lcsc_mismatch"].append((comp.name, pn, lcsc))
                continue
            existing = (db.query(M.ComponentSupplier)
                        .filter_by(component_id=comp.id, supplier_id=s.id).first())
            if existing is None:
                link(db, comp.id, s, part_number=pn, origin="migrated", actor=MIGRATION_ACTOR)
                report["links"] += 1
        report["lcsc_links"] += ensure_lcsc_links(db, comp.id, lcsc)
        if any(is_supplier_key(p.key) for p in cv.properties):
            report["tops"] |= _republish_without_supplier_keys(db, comp, cv)
            report["republished"] += 1
    return report


def run_startup_migration() -> dict | None:
    """The startup door for `migrate`, called from `main.startup`.

    Cheap when there is nothing to do: one query asks whether any LIVE
    component still carries a `Supplier` key, one whether the register is
    empty. Only the first start after the deploy does the work (about 13 s on
    the production copy, 424 components), and the mirror is rebuilt for the
    categories it republished — the KiCad libraries drop the fields."""
    from ..config import settings
    from ..db import SessionLocal
    from .mirror import update_mirror_symbols

    db = SessionLocal()
    try:
        pending = (db.query(M.ComponentProperty.id)
                   .join(M.Component, M.Component.current_version_id == M.ComponentProperty.component_version_id)
                   .filter(M.ComponentProperty.key.op("~")(_SUPPLIER_KEY.pattern))
                   .first())
        if pending is None and db.query(M.Supplier.id).first() is not None:
            return None
        report = migrate(db)
        db.commit()
        tops = report.pop("tops")
        if tops:
            db.expire_all()
            update_mirror_symbols(db, settings, tops)
        log.info(f"supplier register migration: {report}")
        return report
    finally:
        db.close()
