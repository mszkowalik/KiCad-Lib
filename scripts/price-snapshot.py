"""Capture every price the platform derives, so a change to price resolution
can be proven to move nothing it should not.

Written for the supplier register (decision 0055), which replaced the
"JLCPCB hides LCSC" rule with a supplier order. Run it once on the old code and
once on the new code, against the SAME database copy, then diff the two:

    docker compose exec -T api python - capture < scripts/price-snapshot.py > before.json
    ... change the code, migrate ...
    docker compose exec -T api python - capture < scripts/price-snapshot.py > after.json
    python3 scripts/price-snapshot.py diff before.json after.json

Pipe it through stdin, never run it as a file inside the container: a file puts
its own directory on sys.path and imports the stale `app` baked into the image
(see api/CLAUDE.md). Background refreshes must be OFF for both captures
(PRICE_LADDER_AUTOFETCH / FX_AUTOFETCH / DATASHEET_AUTOFETCH=false), or a live
supplier fetch moves prices between the two runs and the diff reports the
market instead of the change.

What it captures, and why each one:

- runs      Every production run's planned side (`run_effective`) — the
            financial figure a rule change could move retroactively.
- boms      Every project BOM, for every snapshot a run uses plus each
            project's newest, at four volumes — the live market estimate.
- prices    Each component's resolved unit price at five quantities, through
            the same `_component_data` + `price_at` path the BOM uses.
- summary   The browse-list price (`component_prices`).
- review    Sign-off, review record and machine-tier result per component —
            the migration removes properties and must cost no verification.
- jlc_stock The consigned-stock valuation `jlc.sync` would write.

It writes nothing: the session is rolled back at the end, which also discards
the conformance cache rows `conformance.get` adds as a side effect.
"""
import json
import sys


def _r(x):
    return None if x is None else round(float(x), 6)


def capture() -> dict:
    from app import models as M
    from app.db import SessionLocal
    from app.routers.util import components_with_current
    from app.services import conformance, ladder, project_bom, review, signoff

    assert M.__file__ == "/srv/app/models.py", M.__file__
    db = SessionLocal()
    out: dict = {"runs": {}, "boms": {}, "prices": {}, "summary": {}, "review": {}, "jlc_stock": {}}
    try:
        for run in db.query(M.ProductionRun).order_by(M.ProductionRun.id).all():
            try:
                eff = project_bom.run_effective(db, run)
            except Exception as e:  # noqa: BLE001 — record, do not stop
                out["runs"][str(run.id)] = {"error": f"{type(e).__name__}: {e}"}
                continue
            out["runs"][str(run.id)] = {
                "label": run.label,
                "totals": {k: _r(v) for k, v in (eff.get("totals") or {}).items()},
                "lines": {
                    l["key"]: {"unit": _r(l.get("unit_price")), "src": l.get("price_source"),
                               "qty": l.get("qty_total"), "total": _r(l.get("line_total"))}
                    for l in eff.get("lines", []) + eff.get("added", [])
                },
            }

        snaps: set[int] = {r.snapshot_id for r in db.query(M.ProductionRun).all() if r.snapshot_id}
        for p in db.query(M.Project).all():
            last = (db.query(M.ProjectSnapshot).filter_by(project_id=p.id)
                    .order_by(M.ProjectSnapshot.id.desc()).first())
            if last is not None:
                snaps.add(last.id)
        for sid in sorted(snaps):
            snap = db.get(M.ProjectSnapshot, sid)
            if snap is None:
                continue
            project = db.get(M.Project, snap.project_id)
            pairs = {(b, v) for b, v in db.query(M.SnapshotBomLine.board, M.SnapshotBomLine.variant)
                     .filter_by(snapshot_id=sid).distinct().all()}
            for board, variant in sorted(pairs):
                for vol in (1, 10, 100, 1000):
                    bom = project_bom.priced_bom(db, project, snap, board, variant, vol)
                    key = f"{sid}|{board}|{variant}|{vol}"
                    lines = {}
                    for i, l in enumerate(bom["lines"]):
                        lk = l["key"]
                        lines[lk] = {"unit": _r(l.get("unit_price")), "src": l.get("price_source"),
                                     "tier": l.get("price_qty_from"), "order_qty": l.get("order_qty"),
                                     "order_total": _r(l.get("order_total")),
                                     "stock_ok": l.get("stock_ok")}
                    for l in bom["extra"]:
                        lines[l["key"]] = {"unit": _r(l.get("unit_price")), "src": l.get("price_source"),
                                           "tier": l.get("price_qty_from")}
                    out["boms"][key] = {
                        "totals": {k: (_r(v) if isinstance(v, (int, float)) else v)
                                   for k, v in bom["totals"].items()},
                        "lines": lines,
                    }

        comps, live = components_with_current(db)
        ids = {c.id for c in comps}
        points, _supply, _names, _virtual = project_bom._component_data(db, ids)
        for c in comps:
            pts = points.get(c.id) or []
            row = {}
            for q in (1, 10, 100, 1000, 5000):
                pt = ladder.price_at(pts, q)
                row[str(q)] = None if pt is None else [pt.source, _r(pt.unit_price), pt.currency, pt.qty_from]
            out["prices"][c.name] = row
        for pr in db.query(M.ComponentPrice).all():
            out["summary"][str(pr.component_id)] = [pr.price_1, pr.price_100, pr.price_bulk,
                                                    pr.bulk_qty, pr.source]

        so = signoff.states_for(db, comps, detail=False)
        rv = review.states_for_components(db, comps, cvs=live)
        for c in comps:
            cv = live.get(c.id)
            items, _exc, _judg = conformance.get(db, "component", c, cv)
            out["review"][c.name] = {
                "signoff": so.get(c.id, {}).get("state"),
                "review": rv.get(c.id, {}).get("state"),
                "machine": {i["key"]: i.get("result") for i in items},
            }

        for it in db.query(M.JlcStockItem).filter(M.JlcStockItem.component_id.isnot(None)).all():
            pts = points.get(it.component_id) or []
            pt = ladder.price_at(pts, max(it.qty or 0, 1))
            out["jlc_stock"][it.lcsc] = None if pt is None else [pt.source, _r(pt.unit_price)]
    finally:
        db.rollback()
        db.close()
    return out


def diff(a_path: str, b_path: str) -> int:
    a, b = json.load(open(a_path)), json.load(open(b_path))
    changed = 0
    for section in a:
        sa, sb = a[section], b.get(section, {})
        n = 0
        for key in sorted(set(sa) | set(sb)):
            if sa.get(key) == sb.get(key):
                continue
            va, vb = sa.get(key), sb.get(key)
            if isinstance(va, dict) and isinstance(vb, dict) and "lines" in va:
                for k in ("totals",):
                    if va.get(k) != vb.get(k):
                        print(f"[{section}] {key} {k}: {va.get(k)} -> {vb.get(k)}")
                la, lb = va.get("lines", {}), vb.get("lines", {})
                for lk in sorted(set(la) | set(lb)):
                    if la.get(lk) != lb.get(lk):
                        print(f"[{section}] {key} line {lk}: {la.get(lk)} -> {lb.get(lk)}")
            else:
                print(f"[{section}] {key}: {va} -> {vb}")
            n += 1
        print(f"== {section}: {len(sa)} before, {len(sb)} after, {n} differ")
        changed += n
    return 1 if changed else 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "capture"
    if mode == "capture":
        json.dump(capture(), sys.stdout, indent=1, sort_keys=True, default=str)
    elif mode == "diff":
        sys.exit(diff(sys.argv[2], sys.argv[3]))
    else:
        sys.exit(f"unknown mode {mode!r}: capture | diff A B")
