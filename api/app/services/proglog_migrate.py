"""Drop the surrogate key on `programming_logs` and make `(run_id, seq)` the key.

`programming_logs` is the largest row count in the database — 2,444,307 rows
across 6321 runs — and it only grows, because every line of every run is kept
on purpose (user decision 2026-07-27). It carried a surrogate `id` primary key
beside a UNIQUE constraint on `(run_id, seq)`, so it paid for TWO indexes of
52 MB each. `pg_stat_user_indexes` reported `idx_scan = 0` on the `id` one:
not a single scan, ever. Nothing addresses a log line by anything but its run
and its sequence — the only reader filters `run_id` and `seq` and orders by
`seq` (`routers/flasher.py`), and the only writer is a `bulk_insert_mappings`
that never supplies an id (`services/flasher/engine.py`). No foreign key
pointed at it either.

Measured on the 2.44 M-row copy: 375 MB -> 304 MB, of which 53 MB is the index
and 18 MB the row overhead. The DDL took 0.54 s and the rewrite 1.7 s.

**The rewrite is the point of the second step.** `DROP COLUMN` only marks a
column dead in Postgres; its bytes stay in every existing row until the table
is rewritten, so the DDL alone moves `pg_relation_size` by nothing. VACUUM FULL
is the rewrite. It cannot run inside a transaction, hence the autocommit
connection, and it holds an ACCESS EXCLUSIVE lock for its duration — which is
why it runs at startup, before the flasher can open a run, and not from a
request.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger("uvicorn.error")

# name -> "ok: …" | "skipped" | "failed: …"; merged into GET /api/health/schema.
RESULT: dict[str, str] = {}


def _has_column(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"), {"t": table, "c": column}).scalar())


def _size(conn, table: str) -> int:
    return int(conn.execute(text("SELECT pg_total_relation_size(:t)"), {"t": table}).scalar() or 0)


def migrate(engine: Engine) -> None:
    """Idempotent: the presence of the `id` column is the whole guard.

    Never raises. A failure here must not stop the API coming up — the old
    shape works, it is only bigger — so the outcome goes to the log and to
    `RESULT`, the way every other schema step here reports itself.
    """
    try:
        with engine.begin() as conn:
            if not _has_column(conn, "programming_logs", "id"):
                RESULT["programming_logs.pk"] = "skipped"
                return
            before = _size(conn, "programming_logs")
            # Order matters: the old PK constraint owns the index on `id`, so it
            # has to go before the column can. The unique constraint on
            # (run_id, seq) cannot be promoted in place — Postgres refuses
            # `ADD PRIMARY KEY USING INDEX` on an index that already backs a
            # constraint ("is already associated with a constraint") — so it is
            # dropped and rebuilt as the primary key. That build is the only
            # slow statement, and it measured 0.45 s on 2.44 M rows.
            conn.execute(text(
                "ALTER TABLE programming_logs DROP CONSTRAINT IF EXISTS programming_logs_pkey"))
            conn.execute(text("ALTER TABLE programming_logs DROP COLUMN id"))
            conn.execute(text(
                "ALTER TABLE programming_logs DROP CONSTRAINT IF EXISTS uq_programming_log_seq"))
            conn.execute(text(
                "ALTER TABLE programming_logs ADD CONSTRAINT programming_logs_pkey "
                "PRIMARY KEY (run_id, seq)"))
    except Exception as e:  # noqa: BLE001 — a bigger table is not a reason to stay down
        RESULT["programming_logs.pk"] = f"failed: {e}"
        log.warning(f"programming_logs primary key migration failed: {e}")
        return

    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM FULL programming_logs"))
            after = _size(conn, "programming_logs")
        # Plain "ok": `GET /api/health/schema` counts anything that is not
        # exactly "ok" or "skipped" as a failure, and the sizes belong in the
        # log anyway — they are a one-time fact, not a health signal.
        RESULT["programming_logs.pk"] = "ok"
        log.info("programming_logs: dropped the unused surrogate key, "
                 f"{before / 1e6:.0f} MB -> {after / 1e6:.0f} MB")
    except Exception as e:  # noqa: BLE001 — the DDL landed; only the space is outstanding
        RESULT["programming_logs.pk"] = f"ok, not yet rewritten: {e}"
        log.warning(f"programming_logs rewritten failed (the key change landed): {e}")
