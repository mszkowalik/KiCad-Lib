"""What was FITTED on a batch, where it is not what the design specifies.

A substitution is a fact about a batch and a board position, not about a
component and not about a project. The snapshot records what was specified at
a moment and is never rewritten; this records what the factory actually put
there. Reasoning in
[0038](../../../docs/decisions/0038-a-substitution-belongs-to-the-batch.md).

The case that produced it (CE_Dongle_V2, 2026-09-19): JLC's own BOM for batches
7 and 8 carries `C7223` at designator `C1` with `matchType: "update"`, where
every earlier order carried `C110548` with `matchType: "auto"`. The change was
intended and was never copied into the schematic. Nothing in the platform knew,
so on 2026-08-06 a purchase of 476 more `C110548` went through at $1.23 against
a historic $0.34 — bought because the design was still asking for it.

**Detection compares JLC's BOM against JLC's OWN PREVIOUS BOM**, not against
our snapshot. JLC stores the board's original EasyEDA reference numbering — `C1`
where the schematic says `C2`, `USB2` for `J1`, `L1` for `L2` — so matching
their designators to ours fails on the very board this was found on. Comparing
their orders to each other needs no mapping at all, and the DESIGN designator is
then recovered by looking the superseded part up in the snapshot, which is
reliable because that part is the one the design still names.

Nothing here writes a substitution. Detection proposes; a person records.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import models as M

log = logging.getLogger(__name__)


def for_run(db: Session, run_id: int) -> list[M.RunSubstitution]:
    return (db.query(M.RunSubstitution).filter_by(run_id=run_id)
              .order_by(M.RunSubstitution.designator).all())


def by_designator(db: Session, run: M.ProductionRun) -> dict[str, M.RunSubstitution]:
    """`designator -> substitution` for one batch, for the BOM draw path.

    Matched on the run's own board and variant so a project with two boards
    cannot take the other board's substitution.
    """
    out: dict[str, M.RunSubstitution] = {}
    for s in for_run(db, run.id):
        if (s.board or "") not in ("", run.board or "") or (s.variant or "") not in ("", run.variant or ""):
            continue
        for ref in _refs(s.designator):
            out[ref] = s
    return out


def _refs(refs: str) -> list[str]:
    """A BOM line names several positions: "C14, C15, C16". Split on commas so a
    substitution can be keyed by any one of them."""
    return [r.strip() for r in (refs or "").replace(";", ",").split(",") if r.strip()]


# ------------------------------------------------------------------ detection

def _orders_by_run(db: Session) -> dict[str, int]:
    """`SMT order code -> run_id`, from the draws the invoice import wrote.

    `import_ref` is `jlc:<batch>:<SMT order>:<lcsc>`, so the order a draw came
    from is on the draw itself — no second source to keep in step.
    """
    out: dict[str, int] = {}
    for c in (db.query(M.ComponentConsumption)
                .filter(M.ComponentConsumption.import_ref.like("jlc:%"),
                        M.ComponentConsumption.run_id.isnot(None)).all()):
        bits = (c.import_ref or "").split(":")
        if len(bits) >= 3:
            out.setdefault(bits[2], c.run_id)
    return out


def _supplier_boms(db: Session) -> list[dict]:
    """Every cached JLC order BOM, oldest first, as
    `{order, batch, when, lines: {designator: line}}`."""
    out = []
    for row in db.query(M.JlcImport).filter(M.JlcImport.bom_info.isnot(None)).all():
        for code, bom in (row.bom_info or {}).items():
            lines = bom if isinstance(bom, list) else (bom.get("lines") or [])
            if not isinstance(lines, list):
                continue
            by_ref = {}
            for li in lines:
                if isinstance(li, dict) and li.get("designator"):
                    by_ref[str(li["designator"])] = li
            if by_ref:
                out.append({"order": code, "batch": row.external_id,
                            "when": row.doc_date or "", "lines": by_ref})
    # Order code carries the date (SMT0YYMMDD…), and the batch's own date is the
    # tiebreak when two orders share one batch.
    return sorted(out, key=lambda o: (o["when"] or "", o["order"]))


def _snapshot_index(db: Session, project_id: int) -> dict[str, dict]:
    """`lcsc -> {refs, qty, component_id, mpn}` from a project's latest ready
    snapshot — how the DESIGN names a part and where it sits."""
    snap = (db.query(M.ProjectSnapshot).filter_by(project_id=project_id, status="ready")
              .order_by(M.ProjectSnapshot.created_at.desc()).first())
    if snap is None:
        return {}
    out = {}
    for li in db.query(M.SnapshotBomLine).filter_by(snapshot_id=snap.id).all():
        if li.lcsc:
            out[li.lcsc.upper()] = {"refs": li.refs or "", "qty": li.qty or 0,
                                    "component_id": li.component_id, "mpn": li.mpn or "",
                                    "board": li.board or "", "variant": li.variant or ""}
    return out


def detect(db: Session) -> list[dict]:
    """Positions where a JLC order fitted a different part from the order before
    it, and no substitution has been recorded.

    A candidate, never a write. `matchType == "update"` is reported because it
    is JLC saying the line was changed BY HAND rather than auto-matched from the
    code we uploaded — the difference between an intended change and a
    mis-resolution.
    """
    boms = _supplier_boms(db)
    order_run = _orders_by_run(db)
    runs = {r.id: r for r in db.query(M.ProductionRun).all()}
    have = {(s.run_id, d)
            for s in db.query(M.RunSubstitution).all() for d in _refs(s.designator)}

    # One chain of BOMs per BOARD, never one global chain. A designator is only
    # meaningful within a board: keyed globally, `U3` on the dongle was compared
    # against `U3` on the Aqua and every board in the account reported a dozen
    # substitutions it never made. The board is reached through the order's run,
    # so an order no batch has been decided for is left out of the chain
    # entirely rather than joining the wrong one.
    chains: dict[tuple, list[dict]] = {}
    for bom in boms:
        run = runs.get(order_run.get(bom["order"], -1))
        if run is None:
            continue
        chains.setdefault((run.project_id, run.board or "", run.variant or ""), []).append(
            {**bom, "run": run})

    out: list[dict] = []
    for _key, chain in sorted(chains.items()):
      previous: dict[str, dict] = {}
      # What the DESIGN asks for at each of the supplier's designators, learned
      # from the chain itself. Once a position changes, every LATER batch is
      # still fitting the other part — and a substitution is per batch, so each
      # of those batches needs its own row. Without this, batch 7 was reported
      # and batch 8, built the same way, looked as though it followed the
      # design.
      specified_at: dict[str, dict] = {}
      for bom in chain:
        run = bom["run"]
        design = _snapshot_index(db, run.project_id)
        for ref, li in sorted(bom["lines"].items()):
            code = str(li.get("componentCode") or "")
            was = previous.get(ref)
            if code:
                previous[ref] = li
            if not code:
                continue
            if code.upper() in design:
                specified_at[ref] = li      # this batch followed the design here
                continue
            prev_code = str((was or {}).get("componentCode") or "")
            spec_line = specified_at.get(ref)
            spec_code = str((spec_line or {}).get("componentCode") or "")
            changed_here = bool(prev_code) and prev_code != code
            if not changed_here and not spec_code:
                continue      # never seen the design's part here; nothing to compare
            old = spec_code or prev_code
            if not old or old == code:
                continue
            if (run.id, ref) in have:
                continue
            # The SAME library component under two LCSC codes is not a
            # substitution. JLC lists one manufacturer part under several codes
            # — XL-1005SURC is both C25503345 and C965790 — and reporting the
            # switch between them as a part change puts three false rows at the
            # top of a list whose whole value is that every row is real.
            if _same_component(db, old, code):
                continue
            design = _snapshot_index(db, run.project_id)
            spec = design.get(old.upper())
            if any((run.id, r) in have for r in _refs((spec or {}).get("refs") or "")):
                continue
            out.append({
                "run_id": run.id, "run_label": run.label, "project_id": run.project_id,
                "order": bom["order"], "batch": bom["batch"], "when": bom["when"],
                "supplier_designator": ref,
                # the DESIGN's own designator, recovered through the part the
                # design still names — their numbering need not be ours
                "designator": (spec or {}).get("refs") or ref,
                "specified_lcsc": old,
                "specified_mpn": (spec or {}).get("mpn") or str(was.get("comment") or ""),
                "specified_component_id": (spec or {}).get("component_id"),
                "fitted_lcsc": code,
                "fitted_mpn": str(li.get("comment") or ""),
                "fitted_describe": str(li.get("describe") or "")[:200],
                "qty_per_device": float((spec or {}).get("qty") or 1),
                "board": (spec or {}).get("board") or run.board or "",
                "variant": (spec or {}).get("variant") or run.variant or "",
                "match_type": str(li.get("matchType") or ""),
                "supplier_source": str(li.get("componentSource") or ""),
                "supplied_by": supplied_by(str(li.get("componentSource") or "")),
                "still_in_design": old.upper() in design,
                "evidence": f"{bom['order']} line {ref}: matchType="
                            f"{li.get('matchType')!r}, source={li.get('componentSource')!r}",
            })
    # The rows that can still cost money first: the design has not moved on, and
    # JLC says the line was changed by hand rather than auto-matched.
    out.sort(key=lambda c: (not c["still_in_design"], c["match_type"] != "update",
                            c["when"] or ""))
    return out


def supplied_by(component_source: str) -> str:
    """JLC's `componentSource` -> who supplied the part.

    `preSale` is our own consigned stock, so a draw exists for it. `shop` is
    JLC's, billed inside the assembly fee, so no draw can ever exist — which is
    why a substituted line with no draw is explained rather than missing. Both
    together stays `both`: guessing which half is which would be inventing a
    split JLC did not report.
    """
    src = (component_source or "").strip()
    if src == "preSaleAndShop":
        return "both"
    if src == "preSale":
        return "pool"
    if src == "shop":
        return "supplier"
    return ""


def _component_of(db: Session, lcsc: str) -> int | None:
    """The library component an LCSC code belongs to.

    Two places know it and neither knows all of it: the JLC stock row for a code
    the library holds, and any purchase line already resolved to a component.
    `XL-1005SURC` is why both are needed — C965790 has a stock row, C25503345
    has only cost lines, and they are one part.
    """
    it = (db.query(M.JlcStockItem)
            .filter(M.JlcStockItem.lcsc == lcsc,
                    M.JlcStockItem.component_id.isnot(None)).first())
    if it is not None:
        return it.component_id
    line = (db.query(M.RunCostLine)
              .filter(M.RunCostLine.lcsc == lcsc,
                      M.RunCostLine.component_id.isnot(None)).first())
    return line.component_id if line is not None else None


def _same_component(db: Session, a: str, b: str) -> bool:
    """Do two LCSC codes resolve to ONE library component? Unknown is not the
    same — a code nothing has resolved must not silence a real change."""
    ca, cb = _component_of(db, a), _component_of(db, b)
    return ca is not None and ca == cb


def unused(db: Session, run: M.ProductionRun) -> dict:
    """Positions the design asks for that this batch shows no sign of fitting.

    Only answerable when the SUPPLIER'S BOM for the batch is cached: without it
    the absence of a part means nothing. With it, a design position whose part
    appears in neither JLC's BOM nor any draw is a part that did not go on the
    board — either replaced by something (record the substitution) or genuinely
    left off, which is a real thing: the early batches shipped without cartons.

    Matched on the LCSC CODE, never the designator. JLC's stored BOM keeps the
    board's older reference numbering, so designators do not line up; a code
    does.

    A position already covered by a substitution is not reported — that IS the
    answer to why it is absent.
    """
    orders = [code for code, rid in _orders_by_run(db).items() if rid == run.id]
    codes: set[str] = set()
    for bom in _supplier_boms(db):
        if bom["order"] not in orders:
            continue
        for li in bom["lines"].values():
            code = str(li.get("componentCode") or "")
            if code:
                codes.add(code.upper())
    if not codes:
        return {"has_supplier_bom": False, "unused": []}

    drawn = set()
    drawn_ids: set[int] = set()
    for c in db.query(M.ComponentConsumption).filter_by(run_id=run.id).all():
        if c.lcsc:
            drawn.add(c.lcsc.upper())
        if c.component_id:
            drawn_ids.add(c.component_id)
    # One part under two LCSC codes must not read as absent. Batch 8 drew
    # XL-1005SURC as C25503345 while the design names C965790, and matching on
    # the code alone reported the LEDs as never fitted.
    fitted_ids = {cid for cid in (_component_of(db, c) for c in codes) if cid}
    fitted_ids |= drawn_ids
    covered: set[str] = set()
    for sub in for_run(db, run.id):
        covered.add((sub.specified_lcsc or "").upper())
        covered.update(_refs(sub.designator))

    out = []
    if not run.snapshot_id:
        return {"has_supplier_bom": True, "unused": []}
    for li in (db.query(M.SnapshotBomLine)
                 .filter_by(snapshot_id=run.snapshot_id, board=run.board or "",
                            variant=run.variant or "").all()):
        code = (li.lcsc or "").upper()
        if not code or li.dnp or li.exclude_from_bom:
            continue
        if code in codes or code in drawn or code in covered:
            continue
        if li.component_id and li.component_id in fitted_ids:
            continue
        if _component_of(db, li.lcsc) in fitted_ids and li.lcsc:
            continue
        if any(r in covered for r in _refs(li.refs)):
            continue
        out.append({"lcsc": li.lcsc, "mpn": li.mpn or li.value or "",
                    "refs": li.refs or "", "qty_per_device": li.qty or 0})
    return {"has_supplier_bom": True, "unused": out}


def drift(db: Session) -> list[dict]:
    """Recorded substitutions whose design has not caught up.

    The standing finding. A substitution on its own is bookkeeping; THIS is what
    stops the superseded part being bought again, which is the failure that
    produced the whole idea.
    """
    out = []
    for s in db.query(M.RunSubstitution).filter_by(design_updated=False).all():
        run = db.get(M.ProductionRun, s.run_id)
        if run is None:
            continue
        design = _snapshot_index(db, run.project_id)
        if (s.specified_lcsc or "").upper() not in design:
            continue  # the design already moved on; nothing to warn about
        held = (db.query(M.JlcStockItem)
                  .filter(M.JlcStockItem.lcsc == s.specified_lcsc).first())
        out.append({
            "substitution_id": s.id, "run_id": run.id, "run_label": run.label,
            "project_id": run.project_id, "designator": s.designator,
            "specified_lcsc": s.specified_lcsc, "specified_mpn": s.specified_mpn,
            "fitted_lcsc": s.fitted_lcsc, "fitted_mpn": s.fitted_mpn,
            "specified_still_held": int(held.qty) if held else 0,
        })
    return out
