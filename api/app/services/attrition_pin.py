"""Pin the unit cost of a CHARGED stock adjustment that never had one.

One-shot and idempotent, run at startup after the phase-1 DDL. Decision 0044,
item 6.

`ComponentStockAdjustment.unit_cost_usd` is nullable and NULL has always meant
"price it from the pool". The trouble is WHEN: `run_actuals._run_money` resolves
it against `pool_state(db, project_id)` with no `as_of`, which is the average
after every event in the database — including purchases made two years after the
write-off. So a 2024 attrition row charged to a 2024 batch was priced at a 2026
average, and moved again every time a later invoice was entered.

New rows pin at write time, from the average at the ADJUSTMENT'S OWN DATE, which
is what the figure should always have been.

These existing rows are pinned at what they resolve to **today** instead. That
is deliberate and it is the whole reason this file exists rather than an UPDATE
statement in the DDL list:

* Freezing the status quo moves NO number on deploy day. Every screen keeps
  reading what it read yesterday, and the only change is that it stops drifting.
* Re-deriving them at their own dates would silently restate historical batches
  in the very act of adding a rule against restating them — and one of them
  (decision 0043) already feeds a per-device cost that has been quoted.

An adjustment that is charged to nobody is left alone: nothing depends on the
moment it is read, so there is nothing to freeze.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import models as M
from . import run_actuals

log = logging.getLogger(__name__)


def migrate(db: Session) -> int:
    """Pin every charged, unpinned adjustment. Returns how many were written."""
    rows = (
        db.query(M.ComponentStockAdjustment)
        .filter(M.ComponentStockAdjustment.charge_run_id.isnot(None),
                M.ComponentStockAdjustment.unit_cost_usd.is_(None))
        .all()
    )
    if not rows:
        return 0
    # ONE replay for the whole batch: `pool_state` walks every purchase, draw and
    # adjustment in the database, so calling it per row turns a 30-row migration
    # into 30 full replays.
    pool = run_actuals.pool_state(db)
    pinned = 0
    for a in rows:
        unit = (pool.get(run_actuals._key(a), {}) or {}).get("avg_usd", 0.0)
        a.unit_cost_usd = float(unit or 0.0)
        pinned += 1
    db.commit()
    log.info(f"attrition_pin: pinned {pinned} charged stock adjustment(s)")
    return pinned
