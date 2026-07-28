"""Post-factum production costs: what a run ACTUALLY cost, from supplier
documents entered after the fact.

The planned side already exists (`project_bom.run_effective` prices a run's BOM
from historical pricing at the run's date). This module is the other half: real
invoice lines, and the split of component purchases across runs.

Model (user decisions, 2026-07-27):

- Purchases go into a **cost pool**, not onto a run: JLC invoices are stockpile
  replenishment, so a purchase can never be booked straight to a batch. A
  `RunCostLine` with ``kind="part"`` and no ``run_id`` IS the pool; every other
  kind is a direct cost of its run.
- A run pays for what it **drew** from the pool (`ComponentConsumption`), valued
  at a **moving weighted average** — not FIFO, because JLC merges reels and never
  reports which lot went into a build, so lot-picking would be fiction.
- The goal is **splitting invoice cost, not matching JLC's stock counts**.
  Attrition is expected and first-class (`ComponentStockAdjustment`), optionally
  charged to a run so its per-device figure carries the real loss. A residual
  pool balance is normal.
- Everything is computed ON READ from append-only rows, like `run_effective`.
  Nothing here is stored.

Replay order is the EVENT date (`doc_date` / `consumed_at` / `adjusted_at`),
never insertion order — backfilling 2024 invoices in 2026 must not change the
average a 2024 run already paid.
"""
from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models as M
from . import cost_steps, fx
from .project_bom import display_currency, run_pricing_date

# Kinds that are component purchases feeding the pool; everything else is a
# direct run cost (fab, assembly, tooling, freight, …).
PART_KIND = "part"
# `allocate` values that spread a non-part line over the same document's parts.
# Deliberately NOT gated on `kind`: freight and duty are the common cases, but a
# per-unit surcharge printed as its own position is the same thing — ITALTRONIC
# bills the digital print on an enclosure and its one-off print tooling as
# separate lines, and the MRP (correctly) carries both inside the enclosure's unit
# cost, because neither is stock in its own right. The operator's explicit
# `allocate` choice is the signal; the kind is only a description.
SPREAD = ("by_value", "by_qty")
# `allocate` value meaning "recorded so the document reconciles, charged to nobody
# on purpose". Reclaimable VAT and already-pooled prepaid components.
EXCLUDED = "excluded"


def live_consumption(db: Session, **filters):
    """Every draw that still counts — the ONE place the void filter is written.

    A draw is retired by VOIDING it, never by deleting it, so an import that
    superseded a BOM forecast can be reversed and put the forecast back. That
    only works if every reader agrees on what "live" means: a single missed
    `voided_at IS NULL` produces a run charged for a draw the lot layer has
    already released, and both conservation identities still pass — the exact
    failure class that let $14,443 sit in `excluded` unnoticed.

    So readers call this, not `db.query(M.ComponentConsumption)`. Grepping the
    raw query is then a reliable audit: the only legitimate uses left are writes
    and the void/unvoid paths themselves.
    """
    q = db.query(M.ComponentConsumption).filter(M.ComponentConsumption.voided_at.is_(None))
    return q.filter_by(**filters) if filters else q


def _round(v: float | None) -> float | None:
    return None if v is None else round(v + 0.0, 4)


def _key(row) -> str:
    """Pool identity for a part: component_id when known, else MPN, else LCSC.

    The MPN is normalised to alphanumerics (`_strip`) because distributors punctuate
    the same part differently — Mouser prints Molex `146153-0050`, DigiKey and the
    MRP print `1461530050`. Keying on the raw string would split one antenna into
    two pool entries with two averages, and neither would match a BOM draw.
    """
    if getattr(row, "component_id", None):
        return f"c{row.component_id}"
    if getattr(row, "mpn", ""):
        return f"m{_strip(row.mpn)}"
    if getattr(row, "lcsc", ""):
        return f"l{_strip(row.lcsc)}"
    return "?"


# ------------------------------------------------------------------ payloads

def effective_qty(li: M.RunCostLine, doc: M.RunCostDocument | None = None,
                  db: Session | None = None) -> float:
    """Quantity the money is actually charged on.

    A `per_device` line states a rate per board ("5 PLN/board"), so its real
    quantity is `qty x the run's units`. Without this, a document whose printed
    total is the batch total looks unreconciled — the reconciliation would
    compare 1750 PLN against a bare 5.0.
    """
    qty = li.qty or 0.0
    if li.basis != "per_device":
        return qty
    run_id = li.run_id or (doc.run_id if doc else None)
    if run_id is None or db is None:
        return qty
    run = db.get(M.ProductionRun, run_id)
    if run is None:
        return qty
    return qty * max(run.qty_good or run.plan_qty or run.qty or 1, 1)


def header_ids(db: Session, document_id: int | None = None) -> set[int]:
    """Ids of lines that have at least one LIVE child.

    Such a line is a header: the children carry its money, so counting the
    header too would double it. Every money path in this module filters on this
    one set — the invariant is not re-derived per call site.
    """
    q = db.query(M.RunCostLine.parent_line_id).filter(
        M.RunCostLine.parent_line_id.isnot(None),
        M.RunCostLine.voided_at.is_(None),
    )
    if document_id is not None:
        # Children always live on their parent's document (enforced when they
        # are created), so a per-document filter is exact.
        q = q.filter(M.RunCostLine.document_id == document_id)
    return {pid for (pid,) in q.all() if pid}


def line_json(li: M.RunCostLine, doc: M.RunCostDocument | None = None,
              db: Session | None = None, kids: dict[int, float] | None = None) -> dict:
    """`kids` maps a header line id -> the summed amount of its live children, in
    the SAME currency (children inherit the parent's). Absent and with a session
    available, it is looked up for this one line."""
    cur = li.currency or (doc.currency if doc else "USD")
    eff = effective_qty(li, doc, db)
    total = _round(eff * (li.unit_price or 0)) or 0.0
    if kids is None and db is not None:
        children = (
            db.query(M.RunCostLine)
            .filter(M.RunCostLine.parent_line_id == li.id, M.RunCostLine.voided_at.is_(None))
            .all()
        )
        kids = ({li.id: sum(effective_qty(c, doc, db) * (c.unit_price or 0) for c in children)}
                if children else {})
    child_total = (kids or {}).get(li.id)
    return {
        "id": li.id,
        "document_id": li.document_id,
        "run_id": li.run_id,
        "project_id": li.project_id,
        "parent_line_id": li.parent_line_id,
        # A header's own amount is NOT counted anywhere; its children are.
        "is_header": child_total is not None,
        "children_total": _round(child_total),
        # What is still unallocated on a header. The Aqua share of a shared
        # freight line used to live in a `notes` string — i.e. it was invisible.
        "residual": _round(total - child_total) if child_total is not None else None,
        "position": li.position,
        "kind": li.kind,
        "basis": li.basis,
        "label": li.label,
        "qty": li.qty,
        "qty_effective": eff,
        "unit_price": li.unit_price,
        "line_total": total,
        "currency": cur,
        "allocate": li.allocate,
        "component_id": li.component_id,
        "mpn": li.mpn,
        "lcsc": li.lcsc,
        "description": li.description,
        "plan_key": li.plan_key,
        "plan_kind": li.plan_kind,
        "plan_ref": li.plan_ref,
        "notes": li.notes,
        "ocr_confidence": li.ocr_confidence,
        "voided": li.voided_at is not None,
        "superseded_by_id": li.superseded_by_id,
    }


def line_destination(li: M.RunCostLine, doc: M.RunCostDocument | None) -> tuple[str, int | None]:
    """Where a LEAF line's money ends up, most specific first.

    `"unassigned"` is the money-disappearing detector: a non-part line on a
    shared document that names neither a run nor a project belongs to nobody, and
    silently vanishes from every per-run figure.

    `"excluded"` is its deliberate opposite — money entered so the document
    reconciles against its printed total, but knowingly charged to nobody:
    reclaimable import VAT, and the prepaid-component portion of a populated-board
    price whose components are already in the pool (user decisions 2026-07-27).
    Being explicit is the point: an excluded line is auditable, whereas simply not
    entering it would make the document fail to add up.
    """
    if li.allocate == EXCLUDED:
        return "excluded", None
    if li.run_id:
        return "run", li.run_id
    if li.project_id:
        return "project", li.project_id
    if doc is not None and doc.run_id:
        return "run", doc.run_id
    if li.kind == PART_KIND:
        return "pool", None  # stockpile: runs reach it through consumption
    if li.allocate in SPREAD:
        # Spread over the same document's parts: landed cost, so the money follows
        # the parts into the pool instead of belonging to nobody.
        # Only when there ARE parts to carry it — `pool_state` cannot spread a
        # surcharge over nothing, and claiming the bucket anyway would lose it.
        if doc is not None and any(
            c.kind == PART_KIND and c.run_id is None and c.voided_at is None for c in doc.lines
        ):
            return "pool", None
    if doc is not None and doc.project_id:
        return "project", doc.project_id
    return "unassigned", None


def document_json(doc: M.RunCostDocument, with_lines: bool = True,
                  db: Session | None = None) -> dict:
    live = [li for li in doc.lines if li.voided_at is None]
    kids: dict[int, float] = defaultdict(float)
    for li in live:
        if li.parent_line_id:
            kids[li.parent_line_id] += effective_qty(li, doc, db) * (li.unit_price or 0)
    # Reconciliation compares the printed total against the TOP-LEVEL lines, the
    # ones the invoice actually prints. Splitting a position into children must
    # never disturb it — otherwise every split invoice would read unreconciled.
    lines_total = sum(effective_qty(li, doc, db) * (li.unit_price or 0)
                      for li in live if not li.parent_line_id)
    leaves = [li for li in live if li.id not in kids]
    by_dest: dict[str, float] = defaultdict(float)
    by_run: dict[int, float] = defaultdict(float)
    by_project: dict[int, float] = defaultdict(float)
    for li in leaves:
        amount = effective_qty(li, doc, db) * (li.unit_price or 0)
        dest, ref = line_destination(li, doc)
        by_dest[dest] += amount
        if dest == "run" and ref:
            by_run[ref] += amount
        elif dest == "project" and ref:
            by_project[ref] += amount
    residual = sum(
        max(effective_qty(li, doc, db) * (li.unit_price or 0) - kids[li.id], 0.0)
        for li in live if li.id in kids
    )
    out = {
        "id": doc.id,
        "project_id": doc.project_id,
        "run_id": doc.run_id,
        "doc_type": doc.doc_type,
        "supplier": doc.supplier,
        "doc_number": doc.doc_number,
        "external_id": doc.external_id,
        "doc_date": doc.doc_date,
        "paid_at": doc.paid_at,
        "currency": doc.currency,
        "fx_rate_usd": doc.fx_rate_usd,
        "display_amount": doc.display_amount,
        "total_amount": doc.total_amount,
        "tax_amount": doc.tax_amount,
        "notes": doc.notes,
        "attachment_id": doc.attachment_id,
        # The supplier's original, filed with the money it evidences.
        "attachment_count": (
            db.query(M.RunAttachment).filter(M.RunAttachment.document_id == doc.id).count()
            if db is not None else 0
        ),
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "line_count": len(live),
        "lines_total": _round(lines_total),
        # Entered total vs the sum of its lines: the reconciliation an importer
        # (or a human) can get wrong, surfaced instead of hidden.
        # Compares the printed total against the sum of EFFECTIVE line amounts,
        # so a "5 PLN per board" line reconciles against a batch total.
        "reconciled": doc.total_amount is None or abs(lines_total - doc.total_amount) <= 0.05,
        # Where this document's money actually went, leaves only. `unassigned`
        # plus `residual` is what no run and no project is paying for — the
        # "money is not disappearing anywhere" check, per document.
        "assignment": {
            "run": _round(by_dest.get("run", 0.0)),
            "project": _round(by_dest.get("project", 0.0)),
            "pool": _round(by_dest.get("pool", 0.0)),
            "excluded": _round(by_dest.get("excluded", 0.0)),
            "unassigned": _round(by_dest.get("unassigned", 0.0)),
            "residual": _round(residual),
            "by_run": {str(k): _round(v) for k, v in sorted(by_run.items())},
            "by_project": {str(k): _round(v) for k, v in sorted(by_project.items())},
            "fully_assigned": by_dest.get("unassigned", 0.0) <= 0.005 and residual <= 0.005,
        },
    }
    if with_lines:
        out["lines"] = [line_json(li, doc, db, kids=kids)
                        for li in sorted(doc.lines, key=lambda x: (x.position, x.id))]
    return out


# OCR-tolerant MPN keys. `jlc._norm_mpn` only drops dashes/underscores/spaces;
# an invoice can also carry stray punctuation ("S$S34") and character
# confusions, so matching needs both a strict and a folded form.
_CONFUSABLE = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})


def _strip(s: str) -> str:
    """Upper-case, alphanumerics only — kills OCR punctuation noise."""
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def _fold(s: str) -> str:
    """Additionally fold the character pairs OCR mixes up, for a fallback pass."""
    return _strip(s).translate(_CONFUSABLE)


# ------------------------------------------------- resolving parts to the library

def resolve_part_lines(db: Session, document_id: int | None = None) -> dict:
    """Attach `component_id` (and LCSC) to invoice part lines by matching the MPN.

    JLC component invoices identify parts by **manufacturer part number only** —
    there is no LCSC column on them — while the platform's BOM lines carry LCSC
    codes and component ids. Without this bridge a purchase and a BOM draw key
    on different things (`m<MPN>` vs `c<id>`), the pool never matches the BOM,
    and every component is costed at zero.

    Two sources, best first:
      1. `jlc_stock_items` — the synced private JLC library already pairs
         mpn + lcsc + component_id (matched 21/30 MPNs on real data).
      2. the library's own `Manufacturer Part Number 1` property (16/30).

    Comparison is OCR-tolerant (see `_strip` / `_fold`) and every non-exact
    match is written into the line's notes so a human can audit it.
    """
    q = db.query(M.RunCostLine).filter(
        M.RunCostLine.kind == PART_KIND,
        M.RunCostLine.voided_at.is_(None),
        M.RunCostLine.component_id.is_(None),
        M.RunCostLine.mpn != "",
    )
    if document_id is not None:
        q = q.filter(M.RunCostLine.document_id == document_id)
    lines = q.all()
    if not lines:
        return {"resolved": 0, "unresolved": [], "checked": 0}

    # index 1: JLC private stock (mpn -> component_id, lcsc)
    by_mpn: dict[str, tuple[int | None, str]] = {}

    def offer(key: str, cid: int | None, lcsc: str) -> None:
        """Index an MPN, PREFERRING an entry that carries a component_id.

        JLC routinely lists the same manufacturer part under several LCSC codes —
        `XL-1005SURC` exists as both C25503345 (unlinked) and C965790 (linked to
        library component 218). A blind `setdefault` let the unlinked one win, so
        the purchase keyed on its MPN while the BOM draw keyed on the component id:
        the two never met and 16,800 LEDs costed at zero while their money sat
        unconsumed in the pool. First-write-wins is wrong here; component_id wins.
        """
        if not key:
            return
        have = by_mpn.get(key)
        if have is None or (have[0] is None and cid is not None):
            by_mpn[key] = (cid, lcsc or (have[1] if have else ""))

    for it in db.query(M.JlcStockItem).filter(M.JlcStockItem.mpn != "").all():
        offer(_strip(it.mpn), it.component_id, it.lcsc or "")
    # index 2: the library's MPN property, with its LCSC alongside
    rows = (
        db.query(M.ComponentProperty.value, M.ComponentVersion.component_id)
        .join(M.ComponentVersion, M.ComponentVersion.id == M.ComponentProperty.component_version_id)
        .filter(M.ComponentProperty.key == "Manufacturer Part Number 1",
                M.ComponentProperty.value != "")
        .all()
    )
    lib_lcsc: dict[int, str] = {
        cid: val for val, cid in (
            db.query(M.ComponentProperty.value, M.ComponentVersion.component_id)
            .join(M.ComponentVersion, M.ComponentVersion.id == M.ComponentProperty.component_version_id)
            .filter(M.ComponentProperty.key == "LCSC Part", M.ComponentProperty.value != "")
            .all()
        )
    }
    for value, cid in rows:
        # the library is authoritative for component_id, so it may upgrade an
        # entry that JLC stock left unlinked
        offer(_strip(value), cid, lib_lcsc.get(cid, ""))

    # OCR of a printed invoice confuses characters and truncates wrapped cells,
    # so matching runs in three tiers, each requiring a UNIQUE hit:
    #   exact  — normalised MPN is identical
    #   folded — 0/O, 1/I, 5/S confusions folded ("O805W8F1200TSE" -> 0805W8F1200T5E)
    #   prefix — the invoice value is a prefix of exactly one library MPN
    #            ("ESP32-WROOM-32UE-" truncated from "…-32UE-N4")
    # A tier that produces several candidates is rejected rather than guessed.
    folded: dict[str, list[str]] = defaultdict(list)
    for key in by_mpn:
        folded[_fold(key)].append(key)

    resolved, unresolved, unlinked = 0, [], []
    tiers: dict[str, int] = defaultdict(int)
    for li in lines:
        norm = _strip(li.mpn)
        hit_key = norm if norm in by_mpn else None
        tier = "exact"
        if hit_key is None:
            cands = folded.get(_fold(norm), [])
            if len(cands) == 1:
                hit_key, tier = cands[0], "folded"
        if hit_key is None and len(norm) >= 6:
            pref = [k for k in by_mpn if k.startswith(norm)]
            if len(pref) == 1:
                hit_key, tier = pref[0], "prefix"
        if hit_key is None:
            unresolved.append(li.mpn)
            continue
        cid, lcsc = by_mpn[hit_key]
        if cid:
            li.component_id = cid
            resolved += 1
            tiers[tier] += 1
            if tier != "exact":
                note = f"MPN matched by {tier} ({li.mpn!r} → {hit_key})"
                li.notes = f"{li.notes}; {note}" if li.notes else note
        else:
            # The MPN was recognised, but the thing it matched has no library
            # component — so this purchase still cannot meet a BOM draw. Reporting
            # it as neither resolved nor unresolved hid real money (1750 DIP
            # switches), so it gets its own bucket.
            unlinked.append(li.mpn)
        if lcsc and not li.lcsc:
            li.lcsc = lcsc
    return {"resolved": resolved, "unresolved": sorted(set(unresolved)),
            # recognised but with no library component behind them: priced in the
            # pool, yet unreachable by any BOM draw until the part is modelled
            "unlinked": sorted(set(unlinked)),
            "checked": len(lines), "by_tier": dict(tiers)}


# --------------------------------------------------------------- the pool

def _to_usd(amount: float, currency: str, rates: dict[str, float]) -> tuple[float, bool]:
    return fx.convert(amount, currency or "USD", "USD", rates)


def _pool_events(db: Session) -> tuple[list[tuple[str, str, object]], dict, dict]:
    """Everything that moves part stock, sorted by event date: leaf part
    purchases (non-proforma, unallocated, not excluded), run draws, and stock
    adjustments — plus the document map and the landed-cost surcharge per
    purchase line. ONE source of events for `pool_state`, `component_ledger`
    and `check_shortages`, so the three can never disagree about what happened.
    """
    doc_by_id = {d.id: d for d in db.query(M.RunCostDocument).all()}
    headers = header_ids(db)
    carriers: list[M.RunCostLine] = []
    if not doc_by_id:
        purchases: list[M.RunCostLine] = []
    else:
        pool_doc_ids = [d.id for d in doc_by_id.values() if (d.doc_type or "invoice") != "proforma"]
        purchases = (
            db.query(M.RunCostLine)
            .filter(
                M.RunCostLine.kind == PART_KIND,
                # run_id set = bought FOR that run and charged to it directly
                # (see run_actuals); only unallocated purchases are pool stock,
                # otherwise the same money is counted twice.
                M.RunCostLine.run_id.is_(None),
                M.RunCostLine.voided_at.is_(None),
                M.RunCostLine.document_id.in_(pool_doc_ids or [0]),
                # Prepaid components on a populated-board invoice are the SAME
                # money as the component invoice that already fed the pool.
                M.RunCostLine.allocate != EXCLUDED,
            )
            .all()
        )
        # A split position is carried by its children; the header is worth zero.
        purchases = [li for li in purchases if li.id not in headers]
        carriers = [
            li for li in (
                db.query(M.RunCostLine)
                .filter(
                    M.RunCostLine.kind != PART_KIND,
                    M.RunCostLine.allocate.in_(SPREAD),
                    M.RunCostLine.run_id.is_(None),
                    M.RunCostLine.voided_at.is_(None),
                    M.RunCostLine.document_id.in_(pool_doc_ids or [0]),
                )
                .all()
            )
            if li.id not in headers
        ]
    # Landed cost: a freight/duty line marked `allocate` is spread over the part
    # lines of the SAME document, in that document's currency. It adds value
    # without adding quantity, so the moving average rises to what the stock
    # really cost to get here. Carrier rows are never consumed themselves.
    surcharge: dict[int, float] = defaultdict(float)
    if carriers:
        parts_by_doc: dict[int, list[M.RunCostLine]] = defaultdict(list)
        for li in purchases:
            parts_by_doc[li.document_id].append(li)
        for c in carriers:
            targets = parts_by_doc.get(c.document_id) or []
            weights = [
                (li, (li.qty or 0.0) if c.allocate == "by_qty" else (li.qty or 0.0) * (li.unit_price or 0.0))
                for li in targets
            ]
            total_w = sum(w for _, w in weights)
            if total_w <= 0:
                # Nothing to spread it over. Leave it alone rather than lose it —
                # `line_destination` keeps such a line out of the pool bucket too,
                # so the register reports it instead of silently absorbing it.
                continue
            amount = (c.qty or 0.0) * (c.unit_price or 0.0)
            for li, w in weights:
                surcharge[li.id] += amount * w / total_w

    events: list[tuple[str, str, object]] = []
    for li in purchases:
        doc = doc_by_id[li.document_id]
        events.append((doc.doc_date or "", "buy", li))
    for c in live_consumption(db).all():
        events.append((c.consumed_at or "", "use", c))
    for a in db.query(M.ComponentStockAdjustment).all():
        events.append((a.adjusted_at or "", "adj", a))
    # Same-date ties resolve adj < buy < use, so an invoice dated the day of a
    # run counts as available to it.
    events.sort(key=lambda e: (e[0] or "9999", e[1]))
    return events, doc_by_id, surcharge


def _buy_usd(row: M.RunCostLine, doc: M.RunCostDocument, extra: float,
             rates: dict[str, float]) -> tuple[float, float, bool]:
    """A purchase line's unit price and its landed-cost surcharge share, in USD.
    The document's pinned rate wins; else the historical table for the date."""
    cur = row.currency or doc.currency or "USD"
    unit = row.unit_price or 0.0
    if doc.fx_rate_usd and cur.upper() != "USD":
        return unit * doc.fx_rate_usd, extra * doc.fx_rate_usd, True
    unit_usd, known = _to_usd(unit, cur, rates)
    extra_usd, _ = _to_usd(extra, cur, rates)
    return unit_usd, extra_usd, known


def pool_state(db: Session, project_id: int | None = None, as_of: str | None = None) -> dict:
    """Replay purchases, consumptions and adjustments in EVENT DATE order and
    return the per-part COMPANY-WIDE pool: quantity on hand, moving average
    unit cost, value.

    Quantities here exist to apportion money — they are not an inventory record
    and are not expected to match JLCPCB's stock (see the module docstring).
    """
    # `project_id` is accepted for call-site clarity but does NOT scope the
    # balance: stock bought once serves every product, so purchases, draws and
    # write-offs are all company-wide. Scoping purchases while counting all
    # consumption would silently under-report what is on hand.
    events, doc_by_id, surcharge = _pool_events(db)
    if as_of:
        # Historical accuracy: a run dated 2024 must be priced from the pool as
        # it stood THEN. Without this cutoff a purchase made in 2026 would
        # retro-price a 2024 batch, because the replay would run to the end.
        events = [e for e in events if (e[0] or "9999") <= as_of]

    # One rate table per distinct event date keeps the replay honest without a
    # query per row. A document's own pinned rate wins when present.
    rate_cache: dict[str, dict[str, float]] = {}

    def rates_for(date_iso: str) -> dict[str, float]:
        if date_iso not in rate_cache:
            rate_cache[date_iso] = fx.rates_at(db, _as_dt(date_iso))
        return rate_cache[date_iso]

    # `value_*` are the money legs of the same events the quantities track, so
    # `value_bought + value_adj - value_used == value_usd` holds exactly per part.
    # The invoice register asserts that identity company-wide.
    pool: dict[str, dict] = defaultdict(
        lambda: {"qty": 0.0, "value_usd": 0.0, "avg_usd": 0.0, "mpn": "", "lcsc": "",
                 "component_id": None, "bought": 0.0, "used": 0.0, "lost": 0.0,
                 "value_bought": 0.0, "value_used": 0.0, "value_adj": 0.0,
                 # Basis for the moving average, kept SEPARATE from the reported
                 # figures and never allowed below zero. `qty`/`value_usd` are the
                 # pure algebraic sums the register's identity depends on, so they
                 # must be able to go negative when more was drawn than bought.
                 # Deriving the average from those directly is what let a run draw
                 # stock the pool never had, strip the quantity without the value,
                 # and make the NEXT purchase average $44 for a $3.73 enclosure.
                 "_avg_qty": 0.0, "_avg_value": 0.0,
                 # Shortage bookkeeping: the lowest the balance ever went and the
                 # date it first dipped below zero — the register's negative-stock
                 # issues read these instead of re-deriving the replay.
                 "min_qty": 0.0, "first_short": None,
                 "unknown_rate": False}
    )
    for date_iso, kind, row in events:
        k = _key(row)
        p = pool[k]
        p["mpn"] = p["mpn"] or getattr(row, "mpn", "") or ""
        p["lcsc"] = p["lcsc"] or getattr(row, "lcsc", "") or ""
        p["component_id"] = p["component_id"] or getattr(row, "component_id", None)
        if kind == "buy":
            doc = doc_by_id[row.document_id]
            extra = surcharge.get(row.id, 0.0)  # freight share, document currency
            unit_usd, extra_usd, known = _buy_usd(row, doc, extra, rates_for(date_iso))
            p["unknown_rate"] = p["unknown_rate"] or not known
            p["qty"] += row.qty or 0.0
            value = (row.qty or 0.0) * unit_usd + extra_usd
            p["value_usd"] += value
            p["value_bought"] += value
            p["bought"] += row.qty or 0.0
            p["_avg_qty"] += row.qty or 0.0
            p["_avg_value"] += value
        elif kind == "use":
            q = row.qty or 0.0
            unit = row.unit_cost_usd or p["avg_usd"]
            p["qty"] -= q
            p["value_usd"] -= q * unit
            p["value_used"] += q * unit
            p["used"] += q
            # a draw can only take value that is actually there — and it takes it
            # at the BASIS's own average, never the draw's snapshotted price. The
            # snap belongs to run costing; using it here leaks the difference into
            # the basis, and a long sequence of below-average snaps once drained
            # the quantity but not the value, leaving 1 phantom piece "worth"
            # $125.66 that repriced every CH340B on the next plan.
            taken = min(q, max(p["_avg_qty"], 0.0))
            basis_avg = p["_avg_value"] / p["_avg_qty"] if p["_avg_qty"] > 0.0001 else 0.0
            p["_avg_qty"] -= taken
            p["_avg_value"] = max(p["_avg_value"] - taken * basis_avg, 0.0)
        else:  # adjustment: negative delta = attrition / write-off
            q = row.qty_delta or 0.0
            p["qty"] += q
            delta = q * (row.unit_cost_usd if row.unit_cost_usd is not None else p["avg_usd"])
            p["value_usd"] += delta
            p["value_adj"] += delta
            if q >= 0:
                p["_avg_qty"] += q
                p["_avg_value"] += delta
            else:
                # same rule as draws: the basis loses value at its own average
                taken = min(-q, max(p["_avg_qty"], 0.0))
                basis_avg = p["_avg_value"] / p["_avg_qty"] if p["_avg_qty"] > 0.0001 else 0.0
                p["_avg_qty"] -= taken
                p["_avg_value"] = max(p["_avg_value"] - taken * basis_avg, 0.0)
            if q < 0:
                p["lost"] += -q
        # average of what is genuinely on hand; when nothing is, the last known
        # average is retained so a later purchase blends against a sane figure
        if p["_avg_qty"] > 0.0001:
            p["avg_usd"] = p["_avg_value"] / p["_avg_qty"]
        if p["qty"] < p["min_qty"]:
            p["min_qty"] = p["qty"]
            if p["qty"] < -0.0001 and p["first_short"] is None:
                p["first_short"] = date_iso
    return dict(pool)


def component_ledger(db: Session, component_id: int | None = None,
                     mpn: str = "", lcsc: str = "") -> dict:
    """One part's complete event history with the running balance after every
    event — the audit trail behind a Parts-stock row, and the answer to "what
    was our stock of this on any given date".

    Events match on ANY identity the part is known under (component id, MPN,
    LCSC), so an unlinked purchase and a linked draw appear in one timeline
    instead of two half-stories.
    """
    want = set(_identity_keys(component_id, mpn or "", lcsc or ""))
    events, doc_by_id, surcharge = _pool_events(db)
    runs = {r.id: r for r in db.query(M.ProductionRun).all()}

    rate_cache: dict[str, dict[str, float]] = {}

    def rates_for(date_iso: str) -> dict[str, float]:
        if date_iso not in rate_cache:
            rate_cache[date_iso] = fx.rates_at(db, _as_dt(date_iso))
        return rate_cache[date_iso]

    rows: list[dict] = []
    bal = val = avg = 0.0
    aq = av = 0.0  # the clamped moving-average basis, same rules as pool_state
    for date_iso, kind, row in events:
        keys = set(_identity_keys(getattr(row, "component_id", None),
                                  getattr(row, "mpn", "") or "",
                                  getattr(row, "lcsc", "") or ""))
        if not (keys & want):
            continue
        if kind == "buy":
            doc = doc_by_id[row.document_id]
            unit_usd, extra_usd, _known = _buy_usd(
                row, doc, surcharge.get(row.id, 0.0), rates_for(date_iso))
            qty_d = row.qty or 0.0
            value_d = qty_d * unit_usd + extra_usd
            aq += qty_d
            av += value_d
            ref = f"{doc.supplier or '?'} {doc.doc_number or ''}".strip()
            detail = row.label or ""
        elif kind == "use":
            qty_d = -(row.qty or 0.0)
            unit = row.unit_cost_usd if row.unit_cost_usd is not None else avg
            value_d = qty_d * unit
            # basis loses value at its OWN average, never the snapped price
            # (same rule as pool_state — see the comment there)
            taken = min(-qty_d, max(aq, 0.0))
            basis_avg = av / aq if aq > 0.0001 else 0.0
            aq -= taken
            av = max(av - taken * basis_avg, 0.0)
            run = runs.get(row.run_id)
            ref = f"run {row.run_id}" + (f" — {run.label}" if run else "")
            detail = row.note or ""
        else:  # adjustment
            qty_d = row.qty_delta or 0.0
            unit = row.unit_cost_usd if row.unit_cost_usd is not None else avg
            value_d = qty_d * unit
            if qty_d >= 0:
                aq += qty_d
                av += value_d
            else:
                taken = min(-qty_d, max(aq, 0.0))
                basis_avg = av / aq if aq > 0.0001 else 0.0
                aq -= taken
                av = max(av - taken * basis_avg, 0.0)
            ref = f"adjustment — {row.reason or ''}".strip()
            detail = row.note or ""
        bal += qty_d
        val += value_d
        if aq > 0.0001:
            avg = av / aq
        rows.append({
            "date": date_iso, "kind": kind, "ref": ref, "detail": detail,
            "qty_delta": _round(qty_d), "unit_usd": _round(value_d / qty_d) if qty_d else None,
            "value_delta_usd": _round(value_d),
            "balance_after": _round(bal), "avg_usd_after": _round(avg),
            "run_id": getattr(row, "run_id", None) if kind == "use" else None,
            "document_id": getattr(row, "document_id", None) if kind == "buy" else None,
            "short": bal < -0.0001,
        })
    return {
        "component_id": component_id, "mpn": mpn, "lcsc": lcsc,
        "events": rows, "balance": _round(bal), "value_usd": _round(val),
        "avg_usd": _round(avg),
        "first_short": next((r["date"] for r in rows if r["short"]), None),
    }


def check_shortages(db: Session, candidates: list[dict]) -> list[dict]:
    """Would these draws take stock below zero at ANY point from their date on?

    A full-timeline check, not a point check: inserting a draw at a historical
    date must not push a LATER event's balance negative either. Quantities only
    — no FX — so it is cheap enough to run on every write. Each candidate is
    `{component_id?, mpn?, lcsc?, qty, date, label?}`; the return value is one
    entry per short part, empty when everything is covered.
    """
    events, _docs, _sur = _pool_events(db)
    out: list[dict] = []
    # candidates already accepted in THIS batch count against the same stock —
    # two BOM lines drawing one part must not each see the full balance
    accepted: list[tuple[set, str, float]] = []
    for cand in candidates:
        want = set(_identity_keys(cand.get("component_id"),
                                  cand.get("mpn") or "", cand.get("lcsc") or ""))
        cdate = cand.get("date") or "9999"
        need = float(cand.get("qty") or 0.0)
        if not want or need <= 0:
            continue
        # this part's timeline, reduced to signed quantities; the candidate is a
        # "use", so on its own date it sorts after adj/buy rows (adj < buy < use)
        # and a same-day invoice covers it. Stable sort keeps it after equal keys.
        entries: list[tuple[tuple[str, str], float, bool]] = []
        for date_iso, kind, row in events:
            keys = set(_identity_keys(getattr(row, "component_id", None),
                                      getattr(row, "mpn", "") or "",
                                      getattr(row, "lcsc", "") or ""))
            if not (keys & want):
                continue
            q = (row.qty or 0.0) if kind == "buy" else \
                (-(row.qty or 0.0) if kind == "use" else (row.qty_delta or 0.0))
            entries.append((((date_iso or "9999"), kind), q, False))
        for pw, pd, pq in accepted:
            if pw & want:
                entries.append((((pd or "9999"), "use"), -pq, False))
        entries.append(((cdate, "use"), -need, True))
        entries.sort(key=lambda e: e[0])

        bal, on_hand, min_after = 0.0, 0.0, None
        for _k, q, is_cand in entries:
            if is_cand:
                on_hand = bal
            bal += q
            if is_cand:
                min_after = bal
            elif min_after is not None and bal < min_after:
                min_after = bal
        if min_after is not None and min_after < -0.0001:
            out.append({
                "component_id": cand.get("component_id"), "mpn": cand.get("mpn") or "",
                "lcsc": cand.get("lcsc") or "", "label": cand.get("label") or "",
                "date": cand.get("date") or "", "needed": _round(need),
                "on_hand": _round(on_hand), "short": _round(-min_after),
            })
        else:
            accepted.append((want, cdate, need))
    return out


def average_cost(db: Session, project_id: int | None, key: str) -> float:
    return pool_state(db, project_id).get(key, {}).get("avg_usd", 0.0)


def _as_dt(date_iso: str):
    """ISO date -> aware datetime for fx.rates_at; falls back to 'now'."""
    from datetime import datetime, timezone
    if not date_iso:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(date_iso).replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


# ------------------------------------------------------------ run actuals

def run_actuals(db: Session, run: M.ProductionRun) -> dict:
    """What this run really cost: components drawn from the pool + direct lines
    + attrition charged to it, in the project's display currency, next to the
    planned figure so the delta is visible."""
    project = db.get(M.Project, run.project_id)
    cur = display_currency(project)
    rates = fx.rates_at(db, run_pricing_date(run))
    unknown: set[str] = set()

    def to_display(amount_usd: float) -> float:
        v, known = fx.convert(amount_usd, "USD", cur, rates)
        if not known:
            unknown.add(cur)
        return v

    # 1. components drawn from the pool
    cons = live_consumption(db, run_id=run.id).all()
    comp_usd = sum((c.qty or 0) * (c.unit_cost_usd or 0) for c in cons)
    by_basis: dict[str, float] = defaultdict(float)
    for c in cons:
        by_basis[c.basis or "manual"] += (c.qty or 0) * (c.unit_cost_usd or 0)

    # 2. direct lines on documents pointing at this run (or lines carrying run_id)
    candidates = (
        db.query(M.RunCostLine)
        .join(M.RunCostDocument, M.RunCostLine.document_id == M.RunCostDocument.id)
        .filter(
            M.RunCostLine.voided_at.is_(None),
            or_(M.RunCostLine.run_id == run.id, M.RunCostDocument.run_id == run.id),
        )
        .all()
    )
    headers = header_ids(db)
    lines = []
    for li in candidates:
        if li.id in headers:
            continue  # split position: its children carry the money
        if li.allocate == EXCLUDED:
            continue  # recorded for reconciliation, charged to nobody on purpose
        if li.run_id == run.id:
            lines.append(li)
            continue
        # Document-level ownership only claims lines that name no destination of
        # their own. Without this, an invoice assigned to run A with a line
        # allocated to run B is charged to BOTH.
        if li.run_id is None and li.project_id is None:
            lines.append(li)
    by_kind: dict[str, float] = defaultdict(float)
    # actuals per production step ("pcba:setup", ...); lines without a step key
    # bucket under "~<kind>" so coarse invoices still show up in the comparison
    actual_by_step: dict[str, float] = defaultdict(float)
    step_sources: dict[str, dict[int, dict]] = {}
    direct_usd = 0.0
    for li in lines:
        doc = db.get(M.RunCostDocument, li.document_id)
        if li.kind == PART_KIND and li.run_id is None:
            continue  # that purchase belongs to the pool, not to this run
        cur_l = li.currency or (doc.currency if doc else "USD")
        # One rule for per_device everywhere (`effective_qty`): charging at
        # plan_qty here while reconciling at qty_good would disagree by the yield.
        amount = effective_qty(li, doc, db) * (li.unit_price or 0)
        if doc and doc.fx_rate_usd and cur_l.upper() != "USD":
            usd = amount * doc.fx_rate_usd
        else:
            usd, known = _to_usd(amount, cur_l, rates)
            if not known:
                unknown.add(cur_l)
        direct_usd += usd
        by_kind[li.kind] += usd
        # Production-step identity (services/cost_steps.py): a line billed
        # under "pcba:setup" is the actual of the planned cost item carrying
        # the same step_key, whatever the vendor called it on paper.
        step = li.plan_key if cost_steps.stage_of(li.plan_key) else ""
        skey = step or f"~{li.kind}"
        actual_by_step[skey] += usd
        # remember WHICH document the money came from, so the run view can
        # answer "who billed this step" without a second sweep
        src = step_sources.setdefault(skey, {}).setdefault(li.document_id, {
            "document_id": li.document_id,
            "doc_number": (doc.doc_number if doc else "") or "",
            "supplier": (doc.supplier if doc else "") or "",
            "doc_date": (doc.doc_date if doc else "") or "",
            "amount_usd": 0.0,
        })
        src["amount_usd"] += usd

    # 3. attrition explicitly charged to this run
    adjs = db.query(M.ComponentStockAdjustment).filter_by(charge_run_id=run.id).all()
    pool = pool_state(db, run.project_id)
    attrition_usd = 0.0
    for a in adjs:
        unit = a.unit_cost_usd
        if unit is None:
            unit = pool.get(_key(a), {}).get("avg_usd", 0.0)
        attrition_usd += abs(a.qty_delta or 0) * (unit or 0)

    total_usd = comp_usd + direct_usd + attrition_usd
    qty_plan = max(run.plan_qty or run.qty or 1, 1)
    good = max(run.qty_good or run.plan_qty or run.qty or 1, 1)

    planned = None
    eff_totals: dict = {}
    try:
        from .project_bom import run_effective
        eff_totals = run_effective(db, run).get("totals") or {}
        planned = eff_totals.get("run_total")
    except Exception:  # noqa: BLE001 — a missing snapshot must not break actuals
        planned = None

    # --- plan-vs-actual per production step (user design 2026-07-28): planned
    # cost items carry `step_key`, invoice lines carry the same key in
    # `plan_key`; matching is on the KEY, so it survives vendors wording the
    # same step differently and works for every cost added to a run or project.
    steps_cmp: list[dict] = []
    try:
        from . import cost_state
        from .project_bom import _cost_price_at
        snap = db.get(M.ProjectSnapshot, run.snapshot_id) if run.snapshot_id else None
        _x, cost_items, _rev = cost_state.items_for(db, run.project_id, snap)
        planned_by_step: dict[str, float] = defaultdict(float)
        for c in cost_items:
            if not c.step_key:
                continue
            price = _cost_price_at(c, good)
            per_run = price * good if c.basis == "per_device" else price
            usd_v, _known = _to_usd(per_run, c.currency or "USD", rates)
            planned_by_step[c.step_key] += usd_v
        for key in sorted(set(planned_by_step) | {k for k in actual_by_step if not k.startswith("~")}):
            info = cost_steps.STEPS.get(key)
            steps_cmp.append({
                "key": key,
                "label": info[0] if info else key,
                "stage": key.split(":", 1)[0],
                "planned_usd": _round(planned_by_step.get(key)),
                "actual_usd": _round(actual_by_step.get(key)),
                "delta_usd": _round((actual_by_step.get(key) or 0)
                                    - (planned_by_step.get(key) or 0)),
                "sources": sorted((dict(v, amount_usd=_round(v["amount_usd"]))
                                   for v in (step_sources.get(key) or {}).values()),
                                  key=lambda x: -(x["amount_usd"] or 0)),
            })
        # STAGE ROLLUP (user design 2026-07-28): a coarse `<stage>:general` bill
        # cannot be compared step-by-step, so its row compares against the SUM of
        # the stage's planned steps instead — minus any steps billed in detail,
        # whose own rows stay. Planned-only step rows inside such a stage are
        # folded into the rollup (their plan is inside the general figure), so
        # the table never double-signals the same money.
        for stage in cost_steps.STAGES:
            gkey = f"{stage}:general"
            gact = actual_by_step.get(gkey)
            if not gact:
                continue
            detailed_billed = {k for k in actual_by_step
                               if k.startswith(stage + ":") and k != gkey}
            remainder_plan = sum(v for k, v in planned_by_step.items()
                                 if k.startswith(stage + ":") and k not in detailed_billed)
            folded = [r for r in steps_cmp
                      if r["stage"] == stage and r["key"] != gkey
                      and r["key"] not in detailed_billed]
            for r in folded:
                steps_cmp.remove(r)
            grow = next((r for r in steps_cmp if r["key"] == gkey), None)
            if grow is None:
                continue
            grow["planned_usd"] = _round(remainder_plan) if remainder_plan else None
            grow["delta_usd"] = (_round(gact - remainder_plan)
                                 if remainder_plan else None)
            grow["rollup"] = True
            grow["label"] = (cost_steps.STEPS[gkey][0] +
                             " — compared against the stage's planned steps summed"
                             + (f" ({len(folded)} folded in)" if folded else ""))

        # Materials rows, so the table covers ALL of a run's money, not just fees:
        # planned = the effective BOM's parts total, actual = the pool draws.
        parts_planned = eff_totals.get("parts_total")
        if parts_planned is not None and cur.upper() != "USD":
            parts_planned, _pk = fx.convert(parts_planned, cur, "USD", rates)
        if (parts_planned is not None) or comp_usd:
            steps_cmp.insert(0, {
                "key": "parts:pool", "label": cost_steps.STEPS["parts:pool"][0],
                "stage": "parts", "planned_usd": _round(parts_planned),
                "actual_usd": _round(comp_usd),
                "delta_usd": _round(comp_usd - parts_planned) if parts_planned is not None else None,
                "sources": [],  # pool draws — the purchase documents live in Parts stock
            })
        if attrition_usd:
            steps_cmp.append({
                "key": "parts:attrition", "label": cost_steps.STEPS["parts:attrition"][0],
                "stage": "parts", "planned_usd": None,
                "actual_usd": _round(attrition_usd), "delta_usd": None,
                "sources": [],
            })
        for key, v in sorted(actual_by_step.items()):
            if key.startswith("~") and v:
                steps_cmp.append({"key": key, "label": f"unclassified ({key[1:]})",
                                  "stage": None, "planned_usd": None,
                                  "actual_usd": _round(v), "delta_usd": None,
                                  "sources": sorted((dict(v, amount_usd=_round(v["amount_usd"]))
                                   for v in (step_sources.get(key) or {}).values()),
                                  key=lambda x: -(x["amount_usd"] or 0)),})
    except Exception:  # noqa: BLE001 — the comparison must never break actuals
        steps_cmp = []

    actual_total = _round(to_display(total_usd))

    # --- the sale side. Revenue is price-per-device x units BILLED (`qty_sold`),
    # falling back to good units then planned: a customer is invoiced for what
    # shipped, which is not always what passed test. Converted into the same
    # display currency as the cost, at the run's date, so margin is comparable.
    revenue = None
    if run.sale_unit_price:
        sold = run.qty_sold or run.qty_good or run.plan_qty or run.qty or 0
        sale_cur = (run.sale_currency or cur).upper()
        gross = (run.sale_unit_price or 0) * sold
        if sale_cur == cur.upper():
            revenue = gross
        else:
            revenue, known = fx.convert(gross, sale_cur, cur, rates)
            if not known:
                unknown.add(sale_cur)
    margin = None if revenue is None else revenue - (actual_total or 0)

    return {
        "currency": cur,
        "qty_planned": qty_plan,
        "qty_good": run.qty_good,
        "qty_sold": run.qty_sold,
        "sale_unit_price": run.sale_unit_price,
        "sale_currency": run.sale_currency or cur,
        "customer": run.customer,
        "order_ref": run.order_ref,
        "order_date": run.order_date,
        "revenue": _round(revenue),
        "margin": _round(margin),
        # Margin over REVENUE (gross margin), not over cost — the figure a price
        # decision is made against. Null when nothing has been priced.
        "margin_pct": (_round(margin / revenue * 100) if revenue not in (None, 0) else None),
        "margin_per_device": (
            _round(margin / max(run.qty_sold or run.qty_good or run.plan_qty or run.qty or 1, 1))
            if margin is not None else None
        ),
        "components": _round(to_display(comp_usd)),
        "components_by_basis": {k: _round(to_display(v)) for k, v in sorted(by_basis.items())},
        "direct": _round(to_display(direct_usd)),
        "by_kind": {k: _round(to_display(v)) for k, v in sorted(by_kind.items())},
        # planned-vs-billed per production step, USD (see services/cost_steps.py)
        "steps": steps_cmp,
        "attrition": _round(to_display(attrition_usd)),
        "total": actual_total,
        "per_device": _round((actual_total or 0) / good) if actual_total is not None else None,
        "planned_total": _round(planned),
        # delta_pct is deliberately null when nothing was planned — a late
        # position has no percentage, only an absolute figure.
        "delta": _round((actual_total or 0) - planned) if planned is not None else None,
        "delta_pct": (
            _round(((actual_total or 0) - planned) / planned * 100)
            if planned not in (None, 0) else None
        ),
        "document_count": len({li.document_id for li in lines}),
        "consumption_count": len(cons),
        "unknown_rates": sorted(unknown),
    }


# ------------------------------------------------------------- parts stock

def _identity_keys(component_id: int | None, mpn: str, lcsc: str) -> list[str]:
    """Every key a part could be known by, so the two sides of `parts_stock` meet
    even when one of them has not been resolved to a library component yet."""
    keys = []
    if component_id:
        keys.append(f"c{component_id}")
    if mpn:
        keys.append(f"m{_strip(mpn)}")
    if lcsc:
        keys.append(f"l{_strip(lcsc)}")
    return keys


def parts_stock(db: Session) -> dict:
    """Every part the company has money in, or that JLCPCB physically holds — with
    both measurements side by side.

    These answer different questions about the same parts and are routinely
    different, which is the point of showing them together:

    - **physical** (`JlcStockItem`): how many pieces JLC holds on consignment,
      valued at the cached MARKET unit price;
    - **money** (the cost pool): how much was actually PAID for parts, how much of
      that has been drawn by runs, and what the unconsumed remainder cost.

    The two derived gaps are the useful part:

    - `delta_qty` = held - remaining. Positive means JLC holds more than the
      platform has paid for; negative means the pool still counts parts JLC no
      longer has — boards were built without recording the draw, or stock was lost
      (record it with `ComponentStockAdjustment`).
    - `delta_value_usd` = `(market_unit - paid_unit) x remaining_qty`, i.e. what
      the unconsumed remainder would be worth at today's price versus what it cost.
      Deliberately valued on the SAME quantity — comparing "held at market" against
      "remaining at cost" would just restate the quantity gap as money.

    `state` classifies each row, and `jlc_only` is a **missing-invoice detector**:
    JLC is holding stock the platform has no purchase for. `pool_only` is normal
    for parts bought elsewhere (enclosures, antennas) or fully consumed.
    """
    pool = pool_state(db)
    items = db.query(M.JlcStockItem).all()

    # index JLC stock under every identity it carries, so an unresolved pool line
    # keyed m<MPN> still meets the JLC row keyed c<component_id>. A key maps to a
    # LIST, not one item: JLC lists the same manufacturer part under several LCSC
    # codes (XL-1005SURC is both C25503345 and C965790), so first-match-wins showed
    # the SAME LED twice — once with the pool's money and no stock, once with 18,488
    # pieces and a bogus "no invoice" flag.
    by_key: dict[str, list[M.JlcStockItem]] = defaultdict(list)
    for it in items:
        for k in _identity_keys(it.component_id, it.mpn or "", it.lcsc or ""):
            by_key[k].append(it)

    comp_names: dict[int, str] = {}
    ids = {it.component_id for it in items if it.component_id}
    ids |= {p["component_id"] for p in pool.values() if p.get("component_id")}
    if ids:
        for c in db.query(M.Component).filter(M.Component.id.in_(ids)).all():
            comp_names[c.id] = c.name

    rows: list[dict] = []
    matched: set[int] = set()
    for key, p in pool.items():
        # every stock item sharing ANY identity with this pool entry, deduplicated
        found: dict[int, M.JlcStockItem] = {}
        for k in _identity_keys(p.get("component_id"), p.get("mpn", ""), p.get("lcsc", "")):
            for cand in by_key.get(k, []):
                found[cand.id] = cand
        matched.update(found)
        it = next(iter(found.values()), None)
        remaining = round(p["qty"], 4)
        paid_value = round(p["value_usd"], 4)
        # quantities ADD across codes — two LCSC codes are two reels of one part
        held = sum(c.qty or 0 for c in found.values())
        market_unit = next((c.unit_price_usd for c in found.values()
                            if c.unit_price_usd is not None), None)
        market_value = round(market_unit * held, 4) if market_unit is not None else None
        # the remainder priced at today's market, so the money delta is like-for-like
        remaining_market = round(market_unit * remaining, 4) if market_unit is not None else None
        rows.append({
            "key": key,
            "component_id": p.get("component_id"),
            "component_name": comp_names.get(p.get("component_id") or -1),
            "mpn": p.get("mpn") or (it.mpn if it is not None else ""),
            "lcsc": p.get("lcsc") or (it.lcsc if it is not None else ""),
            "description": next((c.description for c in found.values() if c.description), ""),
            # when JLC carries the part under more than one code, say so
            "jlc_codes": sorted({c.lcsc for c in found.values() if c.lcsc}),
            "bought": round(p["bought"], 4),
            "drawn": round(p["used"], 4),
            "lost": round(p["lost"], 4),
            "remaining_qty": remaining,
            "paid_unit_usd": _round(p["avg_usd"]),
            "paid_value_usd": paid_value,
            "held_qty": held,
            "market_unit_usd": market_unit,
            "market_value_usd": market_value,
            "remaining_at_market_usd": remaining_market,
            "delta_qty": round(held - remaining, 4) if it is not None else None,
            "delta_value_usd": (round(remaining_market - paid_value, 4)
                                if remaining_market is not None else None),
            "state": "both" if it is not None else "pool_only",
            "unknown_rate": p.get("unknown_rate", False),
        })

    # JLC holds it, the platform has never paid for it -> the invoice is missing
    for it in items:
        if it.id in matched:
            continue
        market_value = (round((it.unit_price_usd or 0) * it.qty, 4)
                        if it.unit_price_usd is not None else None)
        rows.append({
            "key": f"jlc{it.id}",
            "component_id": it.component_id,
            "component_name": comp_names.get(it.component_id or -1),
            "mpn": it.mpn or "", "lcsc": it.lcsc or "", "description": it.description or "",
            "bought": 0.0, "drawn": 0.0, "lost": 0.0, "remaining_qty": 0.0,
            "paid_unit_usd": None, "paid_value_usd": 0.0,
            "held_qty": it.qty, "market_unit_usd": it.unit_price_usd,
            "market_value_usd": market_value, "remaining_at_market_usd": 0.0,
            "delta_qty": float(it.qty), "delta_value_usd": None,
            "state": "jlc_only", "unknown_rate": False,
        })

    rows.sort(key=lambda r: -(r["paid_value_usd"] or 0.0))
    both = [r for r in rows if r["state"] == "both"]
    jlc_only = [r for r in rows if r["state"] == "jlc_only"]
    return {
        "parts": rows,
        "totals": {
            "parts": len(rows),
            "spent_usd": _round(sum(p["value_bought"] for p in pool.values())),
            "drawn_usd": _round(sum(p["value_used"] for p in pool.values())),
            "adjusted_usd": _round(sum(p["value_adj"] for p in pool.values())),
            "remaining_at_cost_usd": _round(sum(p["value_usd"] for p in pool.values())),
            # The SAME remainder priced two ways, over the parts that have both a
            # paid average and a market price — the only honest value comparison.
            "comparable_cost_usd": _round(sum(r["paid_value_usd"] for r in both
                                              if r["remaining_at_market_usd"] is not None)),
            "comparable_market_usd": _round(sum(r["remaining_at_market_usd"] for r in both
                                                if r["remaining_at_market_usd"] is not None)),
            "jlc_held_value_usd": _round(sum(r["market_value_usd"] or 0.0 for r in rows)),
            "jlc_held_qty": sum(r["held_qty"] for r in rows),
            # Pool says unconsumed, JLC no longer holds: unrecorded draws or losses.
            "over_pool_parts": sum(1 for r in both if (r["delta_qty"] or 0) < -0.5),
            "missing_invoice_parts": len(jlc_only),
            "missing_invoice_value_usd": _round(sum(r["market_value_usd"] or 0.0
                                                    for r in jlc_only)),
            "pool_only_parts": sum(1 for r in rows if r["state"] == "pool_only"),
            "unvalued_parts": sum(1 for r in rows if r["market_value_usd"] is None
                                  and r["held_qty"]),
        },
        "last_sync": (last.isoformat()
                      if (last := max((i.updated_at for i in items), default=None)) else None),
    }


# -------------------------------------------------------- the invoice register


def _run_money(db: Session, rid: int, direct_usd: float, components_usd: float,
               rate_cache: dict, run: M.ProductionRun | None) -> dict:
    """Cost and income for one run, both in USD so the register compares runs
    across projects and sale currencies on one scale."""
    cost = direct_usd + components_usd
    revenue = None
    if run is not None and run.sale_unit_price:
        sold = run.qty_sold or run.qty_good or run.plan_qty or run.qty or 0
        gross = run.sale_unit_price * sold
        cur = (run.sale_currency or "USD").upper()
        if cur == "USD":
            revenue = gross
        else:
            # priced at the ORDER date when known, else the run date: a sale is
            # struck on a day, and its FX should not drift with today's rate
            key = run.order_date or run.run_date or ""
            if key not in rate_cache:
                rate_cache[key] = fx.rates_at(db, _as_dt(key))
            revenue, _known = fx.convert(gross, cur, "USD", rate_cache[key])
    margin = None if revenue is None else revenue - cost
    return {
        "direct_usd": _round(direct_usd),
        "components_usd": _round(components_usd),
        "total_usd": _round(cost),
        "revenue_usd": _round(revenue),
        "margin_usd": _round(margin),
        "margin_pct": (_round(margin / revenue * 100) if revenue not in (None, 0) else None),
    }


def invoice_register(db: Session) -> dict:
    """Every supplier document, where its money went, and whether any of it is
    unaccounted for.

    This is the "money is not disappearing anywhere" check (user requirement,
    2026-07-27). Three independent questions, answered side by side:

    1. Does each document's own arithmetic hold (`reconciled`)?
    2. Does every position have a destination — a run, a project, or the pool
       (`unassigned` + `residual`)?
    3. Does the pool balance: bought +/- adjustments - drawn == still on hand?

    Amounts roll up in USD, at the document's pinned rate when it has one (see
    `RunCostDocument`), else the rate history at its date.
    """
    docs = (
        db.query(M.RunCostDocument)
        .order_by(M.RunCostDocument.doc_date.desc(), M.RunCostDocument.id.desc())
        .all()
    )
    rate_cache: dict[str, dict[str, float]] = {}
    unknown: set[str] = set()

    def to_usd(amount: float, doc: M.RunCostDocument) -> float:
        cur = (doc.currency or "USD").upper()
        if cur == "USD" or not amount:
            return amount
        if doc.fx_rate_usd:
            return amount * doc.fx_rate_usd
        key = doc.doc_date or ""
        if key not in rate_cache:
            rate_cache[key] = fx.rates_at(db, _as_dt(key))
        value, known = fx.convert(amount, cur, "USD", rate_cache[key])
        if not known:
            unknown.add(cur)
        return value

    projects = {p.id: p.name for p in db.query(M.Project).all()}
    runs = {
        r.id: {"label": r.label or f"run {r.id}", "project_id": r.project_id,
               "run_date": r.run_date or "", "qty": r.qty_good or r.plan_qty or r.qty,
               # sale side, so income sits beside cost in the register
               "qty_sold": r.qty_sold, "sale_unit_price": r.sale_unit_price,
               "sale_currency": r.sale_currency or "", "customer": r.customer,
               "order_ref": r.order_ref, "order_date": r.order_date}
        for r in db.query(M.ProductionRun).all()
    }

    rows: list[dict] = []
    tot = defaultdict(float)
    by_project: dict[int, float] = defaultdict(float)
    by_run: dict[int, float] = defaultdict(float)
    by_supplier: dict[str, float] = defaultdict(float)
    for doc in docs:
        j = document_json(doc, with_lines=False, db=db)
        a = j["assignment"]
        # The printed total is the truth about how much money left the company;
        # `lines_total` is our transcription of it. Show both, trust the printed.
        printed = doc.total_amount if doc.total_amount is not None else (j["lines_total"] or 0.0)
        j["total_usd"] = _round(to_usd(printed, doc))
        j["lines_total_usd"] = _round(to_usd(j["lines_total"] or 0.0, doc))
        j["assignment_usd"] = {k: _round(to_usd(a[k] or 0.0, doc))
                               for k in ("run", "project", "pool", "excluded",
                                         "unassigned", "residual")}
        j["project_name"] = projects.get(doc.project_id or 0, "")
        j["run_label"] = (runs.get(doc.run_id or 0) or {}).get("label", "")
        rows.append(j)
        if (doc.doc_type or "invoice") == "proforma":
            continue  # not money: a quote that the real invoice supersedes
        tot["total"] += j["total_usd"] or 0.0
        for k in ("run", "project", "pool", "excluded", "unassigned", "residual"):
            tot[k] += j["assignment_usd"][k] or 0.0
        by_supplier[doc.supplier or "(unnamed)"] += j["total_usd"] or 0.0
        for rid, amount in a["by_run"].items():
            by_run[int(rid)] += to_usd(amount or 0.0, doc)
        for pid, amount in a["by_project"].items():
            by_project[int(pid)] += to_usd(amount or 0.0, doc)

    # Components reach a run through the pool, so add the drawn value to each
    # run's figure — otherwise a batch whose only cost is components looks unpaid.
    priced_runs = {r.id for r in db.query(M.ProductionRun)
                   .filter(M.ProductionRun.sale_unit_price.isnot(None)).all()}
    pool = pool_state(db)
    drawn_by_run: dict[int, float] = defaultdict(float)
    for c in live_consumption(db).all():
        drawn_by_run[c.run_id] += (c.qty or 0) * (c.unit_cost_usd or 0)
    purchased = sum(p["value_bought"] for p in pool.values())
    used = sum(p["value_used"] for p in pool.values())
    adjusted = sum(p["value_adj"] for p in pool.values())
    on_hand = sum(p["value_usd"] for p in pool.values())

    # Stock that went below zero at some point in the replay: every one of these
    # is a missing purchase document (real or placeholder), an unrecorded loss,
    # or a batch that genuinely shipped without the part and should say so via a
    # run override. New draws hard-refuse; these are the grandfathered ones.
    neg_names: dict[int, str] = {}
    neg_ids = {p["component_id"] for p in pool.values()
               if p["min_qty"] < -0.0001 and p.get("component_id")}
    if neg_ids:
        for c in db.query(M.Component).filter(M.Component.id.in_(neg_ids)).all():
            neg_names[c.id] = c.name
    negative_stock = sorted(
        ({"key": k, "component_id": p["component_id"],
          "component_name": neg_names.get(p["component_id"] or -1, ""),
          "mpn": p["mpn"], "lcsc": p["lcsc"],
          "first_short": p["first_short"], "min_qty": _round(p["min_qty"]),
          "remaining_qty": _round(p["qty"])}
         for k, p in pool.items() if p["min_qty"] < -0.0001),
        key=lambda r: r["min_qty"])

    # Transport on a parts document must land in the part prices (user rule
    # 2026-07-28): a freight/duty leaf naming no destination of its own, on a
    # document whose part lines feed the pool, is money that should be spread.
    hdrs = header_ids(db)
    live_doc_ids = [d.id for d in docs if (d.doc_type or "invoice") != "proforma"]
    pool_doc_ids = {
        li.document_id
        for li in db.query(M.RunCostLine).filter(
            M.RunCostLine.kind == PART_KIND, M.RunCostLine.run_id.is_(None),
            M.RunCostLine.voided_at.is_(None), M.RunCostLine.allocate != EXCLUDED,
            M.RunCostLine.document_id.in_(live_doc_ids or [0])).all()
        if li.id not in hdrs
    }
    doc_map = {d.id: d for d in docs}
    unspread_transport = [
        {"document_id": li.document_id, "line_id": li.id, "label": li.label,
         "supplier": doc_map[li.document_id].supplier,
         "doc_number": doc_map[li.document_id].doc_number,
         "doc_date": doc_map[li.document_id].doc_date,
         "amount": _round((li.qty or 0) * (li.unit_price or 0)),
         "currency": li.currency or doc_map[li.document_id].currency}
        for li in db.query(M.RunCostLine).filter(
            M.RunCostLine.kind.in_(("freight", "duty")),
            M.RunCostLine.voided_at.is_(None),
            M.RunCostLine.run_id.is_(None), M.RunCostLine.project_id.is_(None),
            M.RunCostLine.allocate.notin_((*SPREAD, EXCLUDED)),
            M.RunCostLine.document_id.in_(sorted(pool_doc_ids) or [0])).all()
        if li.id not in hdrs
    ]

    return {
        "documents": rows,
        "projects": {str(k): v for k, v in sorted(projects.items())},
        "runs": {str(k): v for k, v in sorted(runs.items())},
        "summary": {
            "document_count": len(rows),
            "total_usd": _round(tot["total"]),
            "to_runs_usd": _round(tot["run"]),
            "to_projects_usd": _round(tot["project"]),
            "to_pool_usd": _round(tot["pool"]),
            # Recorded so documents reconcile, charged to nobody on purpose:
            # reclaimable import VAT, and prepaid components already in the pool.
            "excluded_usd": _round(tot["excluded"]),
            "unassigned_usd": _round(tot["unassigned"]),
            "residual_usd": _round(tot["residual"]),
            # Everything above is one identity: total == runs + projects + pool
            # + unassigned + residual. A non-zero gap means a bug here, not bad data.
            "gap_usd": _round(tot["total"] - tot["run"] - tot["project"] - tot["pool"]
                              - tot["excluded"] - tot["unassigned"] - tot["residual"]),
            "unknown_rates": sorted(unknown),
            "by_supplier_usd": {k: _round(v) for k, v in sorted(by_supplier.items(),
                                                                key=lambda kv: -kv[1])},
        },
        "by_project_usd": {str(k): _round(v) for k, v in sorted(by_project.items())},
        "by_run_usd": {
            str(rid): _run_money(db, rid, by_run.get(rid, 0.0), drawn_by_run.get(rid, 0.0),
                                 rate_cache, db.get(M.ProductionRun, rid))
            for rid in sorted(set(by_run) | set(drawn_by_run) | set(priced_runs))
        },
        "pool": {
            "purchased_usd": _round(purchased),
            "adjustments_usd": _round(adjusted),
            "drawn_usd": _round(used),
            "on_hand_usd": _round(on_hand),
            "balanced": abs(purchased + adjusted - used - on_hand) <= 0.5,
            "part_count": len(pool),
        },
        "issues": {
            "unreconciled": [
                {"id": r["id"], "supplier": r["supplier"], "doc_number": r["doc_number"],
                 "doc_date": r["doc_date"], "total_amount": r["total_amount"],
                 "lines_total": r["lines_total"], "currency": r["currency"]}
                for r in rows if not r["reconciled"]
            ],
            "unassigned": [
                {"id": r["id"], "supplier": r["supplier"], "doc_number": r["doc_number"],
                 "doc_date": r["doc_date"], "amount_usd": r["assignment_usd"]["unassigned"],
                 "residual_usd": r["assignment_usd"]["residual"]}
                for r in rows
                if (r["doc_type"] or "invoice") != "proforma" and not r["assignment"]["fully_assigned"]
            ],
            "negative_stock": negative_stock,
            "unspread_transport": unspread_transport,
        },
    }


def consume_from_bom(db: Session, run: M.ProductionRun, basis: str = "bom",
                     consumed_at: str = "") -> dict:
    """Draw this run's components from the pool using its BOM x built units.

    Priced at the pool's moving average per part, snapshotted onto each row.
    Parts with nothing in the pool are reported as `unpriced` rather than
    silently costed at zero.
    """
    if not run.snapshot_id:
        return {"created": 0, "unpriced": [], "error": "run has no snapshot — no BOM to draw from"}
    snap = db.get(M.ProjectSnapshot, run.snapshot_id)
    if snap is None:
        return {"created": 0, "unpriced": [], "error": "snapshot not found"}
    volume = max(run.qty_good or run.plan_qty or run.qty or 1, 1)
    # Price the draw from the pool AS IT STOOD at the run's date.
    pool = pool_state(db, run.project_id, as_of=(consumed_at or run.run_date or None))
    bom = (
        db.query(M.SnapshotBomLine)
        .filter_by(snapshot_id=snap.id, board=run.board, variant=run.variant)
        .all()
    )
    created, unpriced, skipped = 0, [], []
    date_iso = consumed_at or (run.run_date or "")
    # Per-run corrections, sharing the SAME key scheme and the SAME `drop` flag the
    # planned side already uses (`project_bom.run_effective`): `b<bom line id>` and
    # `x<extra item id>`. A batch that predates a part, or shipped without it, is a
    # real thing — the early batches went out with no carton — and so is a
    # substitution. Without this the only way to correct a run was to hand-delete
    # draw rows, which leaves no record of the decision.
    #   overrides = {"b12": {"drop": true},                      not used
    #                "b12": {"component_id": 319},               replaced by another part
    #                "b12": {"qty_total": 900}}                   different quantity
    overrides = run.overrides or {}

    planned: list[dict] = []

    def draw(key: str, component_id: int | None, lcsc: str, mpn: str,
             qty: float, label: str) -> None:
        ov = overrides.get(key) or {}
        if ov.get("drop"):
            skipped.append({"key": key, "label": label, "reason": ov.get("note") or "not used"})
            return
        if ov.get("component_id"):
            component_id, lcsc, mpn = int(ov["component_id"]), "", ""
        if ov.get("qty_total") is not None:
            qty = float(ov["qty_total"])
        if not qty:
            return
        note = f"BOM x {volume}"
        if ov:
            note += f" (override {json.dumps(ov)})"
        planned.append({"component_id": component_id, "lcsc": lcsc, "mpn": mpn,
                        "qty": qty, "label": label, "date": date_iso, "note": note})

    for li in bom:
        if li.dnp or li.exclude_from_bom:
            continue
        draw(f"b{li.id}", li.component_id, li.lcsc or "", "", (li.qty or 0) * volume,
             li.lcsc or li.refs or str(li.component_id))

    # EXTRA BOM items too. `project_bom` already counts them in the PLANNED
    # per-device figure, so leaving them out here made plan and actual asymmetric:
    # an enclosure or antenna would show as expected cost and never be drawn from
    # the pool, so its money sat unconsumed and every run read too cheap. These are
    # exactly the parts that cannot come from the schematic — an ESP32-WROOM-32U
    # takes its antenna on the module's own connector, so nothing is placed on the
    # PCB and no SnapshotBomLine can ever exist for it.
    from . import cost_state

    extras, _costs, _rev = cost_state.items_for(db, run.project_id, snap)
    for x in extras:
        draw(f"x{x.id}", x.component_id, "", x.mpn or "", (x.qty or 0) * volume,
             x.mpn or x.label or f"extra {x.id}")

    # A run cannot draw what was never bought (user decision 2026-07-28): the
    # WHOLE batch is checked first and refused atomically, so a failed draw never
    # leaves half a run consumed. The fix is the missing invoice — real or
    # placeholder — or a signed stock adjustment, or an override marking the part
    # as genuinely not used ("shipped without cartons" is history, not an error).
    shortages = check_shortages(db, planned)
    if shortages:
        return {"created": 0, "unpriced": [], "volume": volume, "skipped": skipped,
                "shortages": shortages,
                "error": f"{len(shortages)} part(s) short — enter the missing invoice "
                         "(or a placeholder), record a stock adjustment, or mark the "
                         "part not-used via the run's overrides"}

    for d in planned:
        probe = type("P", (), {"component_id": d["component_id"], "mpn": d["mpn"],
                               "lcsc": d["lcsc"]})()
        avg = pool.get(_key(probe), {}).get("avg_usd", 0.0)
        if avg <= 0:
            unpriced.append(d["label"])
        db.add(M.ComponentConsumption(
            run_id=run.id, component_id=d["component_id"], lcsc=d["lcsc"], mpn=d["mpn"],
            qty=d["qty"], unit_cost_usd=avg, basis=basis, consumed_at=d["date"],
            note=d["note"],
        ))
        created += 1
    return {"created": created, "unpriced": unpriced, "volume": volume,
            "extras_drawn": len([x for x in extras if (x.qty or 0)]),
            # what the run's overrides deliberately left out, so a missing line is
            # never mistaken for an oversight
            "skipped": skipped}
