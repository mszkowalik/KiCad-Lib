"""JLCPCB's OWN inventory ledger for the private parts library, and what it
says about ours.

JLC keeps a per-part ledger behind the private-library page:
`myLibrary/selectComponentChanges`, one row per movement with the balance
before and after and the document that caused it. It is the only JLC surface
that states a movement no document reports, and the only one where a purchase
that never arrived is visible by ABSENCE.

Two findings that justify syncing it rather than reading it by hand
(2026-09-18, C965790 / XL-1005SURC):

* Lot 754166 settled 3,470 pieces on a parts order and was then cancelled
  (`orderStatus=40`, refunded). The importer booked 3,470 pieces of stock. The
  ledger records no receipt for them — JLC never held them.
* On 2024-10-22 JLC moved 8 pieces under code `T241022013`, remark "pick 3 pcs
  of C778132 & 8 pcs of C965790 up to complete SMT order". It appears on no
  invoice and in no BOM, because no order consumed it: a warehouse action.

Neither is reachable from invoices, so neither could have been found by the
importer. Both are one row here.

**This module never writes a movement.** It records what JLC says and names
every row on either side that the other cannot explain. Booking one is an
explicit action elsewhere, with JLC's own row as its source.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models as M
from ..models import utcnow
from . import jlc_web
from .run_actuals import JLC_TZ

log = logging.getLogger(__name__)

# `bussinessType` as observed across the whole account (2026-09-18). A value
# not listed here is kept on the row and reported as `other` — never guessed at.
BT_SMT_ORDER = 4
BT_PARTS_ORDER = 5
BT_WAREHOUSE = 10

# `changeStatus` 3 is a movement that DID NOT TAKE EFFECT — a ship-out request
# JLC cancelled. It still states a quantity and a before/after pair, so a naive
# replay of the newest row's `realOccupyCount` reports the wrong balance for
# exactly the parts that have one. Measured 2026-09-18: excluding status 3, all
# 67 parts in the account replay to the balance JLC reports; including it, two
# do not (C157472, C62102 — five such rows in total).
STATUS_VOID = 3

_PAGE = 100


def _ts(ms) -> datetime:
    """JLC stamps in epoch milliseconds. Kept in China time, the calendar every
    other JLC figure is dated in (see `run_actuals._jlc_date`)."""
    return datetime.fromtimestamp(int(ms) / 1000, JLC_TZ).astimezone(timezone.utc)


def stock_keys(db: Session) -> dict[str, dict]:
    """`lcsc -> {stock_key_id, mpn, qty}` for every part in the private library.

    From the WEB stock list, not the official OpenAPI one: only this response
    carries `customerPresaleStockKeyId`, and the ledger accepts no other key.
    Parts at zero are included — 36 of the account's 67 sit at zero and are
    exactly the ones whose history matters.
    """
    out: dict[str, dict] = {}
    page = 1
    while True:
        data = jlc_web.get_customer_component_stock(db, page=page, page_size=_PAGE)
        rows = data.get("list") or []
        for r in rows:
            code = str(r.get("componentCode") or "")
            key = r.get("customerPresaleStockKeyId")
            if not code or not key:
                continue
            out[code] = {"stock_key_id": int(key),
                         "mpn": str(r.get("componentModel") or "")[:200],
                         "qty": int(r.get("privateStockCount") or 0)}
        if page >= int(data.get("pages") or 1):
            break
        page += 1
    return out


def fetch_changes(db: Session, stock_key_id: int) -> list[dict]:
    """Every ledger row for one part, oldest first."""
    rows: list[dict] = []
    page = 1
    while True:
        data = jlc_web.get_component_changes(db, stock_key_id=stock_key_id,
                                             page=page, page_size=_PAGE)
        batch = data.get("list") or []
        rows.extend(batch)
        if page >= int(data.get("pages") or 1) or not batch:
            break
        page += 1
    return sorted(rows, key=lambda r: int(r.get("createTime") or 0))


def sync(db: Session, only: list[str] | None = None) -> dict:
    """Upsert JLC's ledger for every private-library part.

    UPSERT, not replace: a ledger row is immutable at JLC and keyed by
    `customerPresaleStockChangeKeyId`, so re-syncing adds the new movements and
    touches nothing else. `JlcStockItem` is replaced wholesale instead because
    it is a balance, not a history.
    """
    keys = stock_keys(db)
    if only:
        want = {c.upper() for c in only}
        keys = {k: v for k, v in keys.items() if k.upper() in want}
    held = {int(r.change_key_id) for r in db.query(M.JlcStockChange.change_key_id).all()}
    now = utcnow()
    added = parts = replays = 0
    broken: list[str] = []
    for lcsc, meta in sorted(keys.items()):
        rows = fetch_changes(db, meta["stock_key_id"])
        parts += 1
        for r in rows:
            key = int(r.get("customerPresaleStockChangeKeyId") or 0)
            if not key or key in held:
                continue
            db.add(M.JlcStockChange(
                change_key_id=key,
                stock_key_id=int(r.get("customerPresaleStockKeyId") or meta["stock_key_id"]),
                lcsc=lcsc,
                mpn=meta["mpn"],
                changed_at=_ts(r.get("createTime") or 0),
                qty_before=int(r.get("oldOccupyCount") or 0),
                change_qty=int(r.get("changeCount") or 0),
                qty_after=int(r.get("realOccupyCount") or 0),
                paid_usd=float(r.get("paidMoney") or 0.0),
                business_code=str(r.get("bussinessCode") or "")[:60],
                business_type=int(r.get("bussinessType") or 0),
                change_type=int(r.get("changeType") or 0),
                change_status=int(r.get("changeStatus") or 0),
                remark=str(r.get("remarkEn") or r.get("remark") or "")[:500],
                raw=r, synced_at=now))
            held.add(key)
            added += 1
        # The ledger must replay to the balance JLC itself reports. A part that
        # does not is a FETCH problem — a page missed, a row filtered — and must
        # not be read as a disagreement about stock.
        if rows:
            effective = sum(int(r.get("changeCount") or 0) for r in rows
                            if int(r.get("changeStatus") or 0) != STATUS_VOID)
            if effective == meta["qty"]:
                replays += 1
            else:
                broken.append(lcsc)
    db.commit()
    report = {"parts": parts, "rows_added": added, "replays_to_balance": replays,
              "does_not_replay": broken, "synced_at": now.isoformat()}
    log.info(f"JLC stock ledger sync: {report}")
    return report


# ------------------------------------------------------------- reconciliation

def _local_index(db: Session) -> tuple[dict, dict]:
    """`(draws, purchases)` keyed by `(lcsc, JLC document code)`.

    A draw carries its order in `import_ref` as `jlc:<batch>:<SMT code>:<lcsc>`.
    A purchase line carries no order reference of its own — the POB is the
    DOCUMENT's `external_id`, one document per parts order.

    Only a line that feeds the POOL is a purchase into JLC's warehouse. A part
    line with a `run_id` was bought FOR one batch and never entered the consigned
    stock — the parts the factory sourced itself are exactly that, and counting
    them here reported 17,647 pieces as "booked as bought that JLC never
    received" the moment a supplier-parts position was itemised (2026-09-19).
    Same test as `run_actuals.pooled_part_lines`; an `excluded` line is not a
    purchase either, it is money recorded so a document reconciles.
    """
    draws: dict[tuple[str, str], list] = {}
    for c in db.query(M.ComponentConsumption).filter(
            M.ComponentConsumption.import_ref.like("jlc:%")).all():
        bits = (c.import_ref or "").split(":")
        if len(bits) >= 3:
            draws.setdefault(((c.lcsc or "").upper(), bits[2]), []).append(c)
    purchases: dict[tuple[str, str], list] = {}
    rows = (db.query(M.RunCostLine, M.RunCostDocument.external_id)
              .join(M.RunCostDocument, M.RunCostLine.document_id == M.RunCostDocument.id)
              .filter(M.RunCostLine.kind == "part",
                      M.RunCostLine.voided_at.is_(None),
                      M.RunCostLine.run_id.is_(None),
                      M.RunCostLine.allocate != "excluded").all())
    for line, external_id in rows:
        ref = external_id or ""
        if ref:
            purchases.setdefault(((line.lcsc or "").upper(), ref), []).append(line)
    return draws, purchases


def _booked_keys(db: Session) -> set[str]:
    """`changeKeyId`s already written as draws, from `import_ref`."""
    return {
        (c.import_ref or "").split(":", 1)[1]
        for c in db.query(M.ComponentConsumption)
        .filter(M.ComponentConsumption.import_ref.like("jlcledger:%")).all()
    }


def unexplained(db: Session, lcsc: str = "") -> dict:
    """Every ledger row the platform cannot account for, and every part line
    JLC's ledger never confirms.

    Returns both directions because they are different defects. A JLC row we
    have no event for is stock that moved and we did not record. A part line
    with no receipt in the ledger is stock we recorded and JLC never held —
    which is what a cancelled lot looks like.
    """
    q = db.query(M.JlcStockChange)
    if lcsc:
        q = q.filter(M.JlcStockChange.lcsc == lcsc.upper())
    rows = q.order_by(M.JlcStockChange.lcsc, M.JlcStockChange.changed_at).all()
    draws, purchases = _local_index(db)
    booked = _booked_keys(db)

    receipts: dict[tuple[str, str], int] = {}
    theirs: list[dict] = []
    for r in rows:
        if r.change_status == STATUS_VOID:
            continue  # JLC cancelled it; nothing moved
        if str(r.change_key_id) in booked:
            continue  # written as a draw straight from this row
        code = r.business_code
        key = (r.lcsc.upper(), code)
        if r.business_type == BT_PARTS_ORDER and r.change_qty > 0:
            receipts[key] = receipts.get(key, 0) + r.change_qty
        matched = bool(draws.get(key)) if r.business_type == BT_SMT_ORDER else bool(purchases.get(key))
        if matched:
            continue
        theirs.append({
            "lcsc": r.lcsc, "mpn": r.mpn,
            "changed_at": r.changed_at.astimezone(JLC_TZ).strftime("%Y-%m-%d %H:%M"),
            "change_qty": r.change_qty, "qty_after": r.qty_after,
            "business_code": code, "business_type": r.business_type,
            "kind": ("smt_order" if r.business_type == BT_SMT_ORDER else
                     "parts_order" if r.business_type == BT_PARTS_ORDER else
                     "warehouse" if r.business_type == BT_WAREHOUSE else "other"),
            "paid_usd": r.paid_usd, "remark": r.remark,
        })

    # A draw JLC later gave back is not a disagreement: SMT026061460600 took 20
    # parts on 2026-06-14 and returned every one on 2026-06-15 (40 rows, net
    # zero), and a ship-out request that came back does the same under its SIP
    # code. Netting by document keeps those out of the report — what is left is
    # stock that really moved.
    net: dict[tuple[str, str], int] = {}
    for t in theirs:
        if t["business_code"]:
            key = (t["lcsc"], t["business_code"])
            net[key] = net.get(key, 0) + t["change_qty"]
    cancelled_out = [t for t in theirs
                     if t["business_code"] and net.get((t["lcsc"], t["business_code"])) == 0]
    theirs = [t for t in theirs if t not in cancelled_out]

    ours: list[dict] = []
    seen_parts = {r.lcsc.upper() for r in rows}
    for (code_lcsc, ref), lines in sorted(purchases.items()):
        if code_lcsc not in seen_parts:
            continue  # not a JLC-held part; its ledger says nothing about it
        if lcsc and code_lcsc != lcsc.upper():
            continue
        got = receipts.get((code_lcsc, ref), 0)
        booked = sum(int(line.qty or 0) for line in lines)
        if got >= booked:
            continue
        ours.append({
            "lcsc": code_lcsc, "parts_order": ref,
            "line_ids": [line.id for line in lines],
            "booked_qty": booked, "ledger_receipt_qty": got,
            "missing_qty": booked - got,
            "usd": round(sum(float(line.qty or 0) * float(line.unit_price or 0)
                             for line in lines), 4),
        })

    return {
        "jlc_rows_we_cannot_explain": theirs,
        "our_lines_jlc_never_received": ours,
        "totals": {
            "parts": len({r.lcsc for r in rows}),
            "ledger_rows": len(rows),
            "unexplained_rows": len(theirs),
            "netted_out_rows": len(cancelled_out),
            "unconfirmed_lines": len(ours),
            "unconfirmed_qty": sum(x["missing_qty"] for x in ours),
        },
    }


# ------------------------------------------------------------------- booking

def bookable(db: Session) -> list[dict]:
    """Ledger rows that took stock out and that NO document can ever report.

    Two shapes, both observed:

    * `bussinessType=10`, code `T…` — a warehouse pick. "pick 3 pcs of C778132 &
      8 pcs of C965790 up to complete SMT order" (2024-10-22). JLC topped an
      order up by hand, so the quantity is on no invoice and in no BOM.
    * a row with NO `bussinessCode` at all, carrying a free-text remark:
      "2014632A-SMT02306271294260-W202306271941724-Y20 used 20pcs in 2nd
      Process" (2023-08-15) — 20 pieces of C157472 consumed in a second process,
      which is the whole of that part's disagreement.

    A row that names a document is NOT bookable here even when we have not
    imported that document: importing it is the right fix, and writing the draw
    from the ledger as well would take the same stock out twice.
    """
    seen = _booked_keys(db)
    out = []
    for r in (db.query(M.JlcStockChange)
                .filter(M.JlcStockChange.change_status != STATUS_VOID,
                        M.JlcStockChange.change_qty < 0)
                .order_by(M.JlcStockChange.changed_at).all()):
        if r.business_type != BT_WAREHOUSE and r.business_code:
            continue
        if str(r.change_key_id) in seen:
            continue
        out.append({"change_key_id": r.change_key_id, "lcsc": r.lcsc, "mpn": r.mpn,
                    "qty": -r.change_qty,
                    "date": r.changed_at.astimezone(JLC_TZ).date().isoformat(),
                    "business_code": r.business_code, "remark": r.remark})
    return out


def book(db: Session, change_key_ids: list[int] | None = None,
         actor: str = "user", dry_run: bool = True) -> dict:
    """Write the chosen ledger rows as UNCHARGED DRAWS.

    An uncharged draw, not an adjustment, for the reason decision
    [0034](../../../docs/decisions/0034-stock-moves-when-the-supplier-says-so.md)
    gives: the stock left, and who pays is a separate question this row does not
    answer. A warehouse pick belongs to whichever order it completed, and JLC's
    remark names that order in prose only — so it is charged to nobody until a
    human says otherwise, exactly like an external order's draws.

    `basis='measured'`, because JLC measured it. That also stops the end-of-
    production screen retyping it (`run_costs.set_used_qty` refuses a measured
    part).

    Idempotent: `import_ref='jlcledger:<changeKeyId>'` under
    `uq_consumption_import`, so re-booking the same row is a no-op rather than a
    second draw.

    NOTHING here decides on its own what should move. The caller names the rows.
    """
    from .run_actuals import check_shortages, resolve_pool_identity

    want = set(change_key_ids or [])
    rows = [r for r in bookable(db) if not want or r["change_key_id"] in want]
    missing = sorted(want - {r["change_key_id"] for r in rows})
    written, refused = [], []
    for r in rows:
        pool = resolve_pool_identity(db, None, r["mpn"], r["lcsc"], as_of=r["date"])
        if pool is None:
            refused.append({**r, "why": "no pool entry for that part — the purchase "
                                        "it came from is not in the platform"})
            continue
        short = check_shortages(db, [{"component_id": pool.get("component_id"),
                                      "mpn": pool.get("mpn") or r["mpn"],
                                      "lcsc": pool.get("lcsc") or r["lcsc"],
                                      "qty": r["qty"], "date": r["date"]}])
        if short:
            refused.append({**r, "why": "the pool does not hold that much on that date",
                            "shortages": short})
            continue
        unit = pool["avg_usd"]
        entry = {**r, "unit_cost_usd": unit, "usd": round(r["qty"] * unit, 4)}
        if not dry_run:
            row = M.ComponentConsumption(
                run_id=None, component_id=pool.get("component_id"),
                mpn=pool.get("mpn") or r["mpn"], lcsc=pool.get("lcsc") or r["lcsc"],
                qty=r["qty"], unit_cost_usd=unit, basis="measured",
                import_ref=f"jlcledger:{r['change_key_id']}",
                consumed_at=r["date"],
                note=(f"JLC inventory ledger {r['date']}"
                      + (f" ({r['business_code']})" if r["business_code"] else "")
                      + f": {r['remark']}")[:500])
            db.add(row)
            db.flush()
            entry["consumption_id"] = row.id
        written.append(entry)
    return {"dry_run": dry_run, "written": written, "refused": refused,
            "not_bookable": missing,
            "totals": {"rows": len(written), "qty": sum(w["qty"] for w in written),
                       "usd": round(sum(w["usd"] for w in written), 4)}}
