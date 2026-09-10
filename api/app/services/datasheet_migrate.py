"""One-shot move of the datasheet bytes into the content-addressed
`documents` table (user decision 2026-09-10: "don't duplicate files, just
relink them").

Runs at startup, after `create_all` (which builds the empty `documents`
table) and after the phase-1 DDL. It is idempotent by construction: the whole
move keys off the presence of `datasheet_versions.data`, which the last step
drops, so a second boot finds nothing to do.

Everything happens in SQL, server-side. The stored corpus is close to a
gigabyte and single files pass 30 MB — pulling the rows through Python to
re-insert them would be exactly the mistake `datasheet_pages` warns about.

Why the pages move too: `datasheet_pages` was keyed on the version, so two
versions holding the same bytes carried two identical page sets. Re-keyed on
the document, duplicates are dropped (the lowest version id's set survives)
and a document shared by three components is indexed once.

The VACUUM at the end is what actually hands the disk back. `DROP COLUMN`
in Postgres only hides the column; the bytes stay in the dead tuples until
the table is rewritten. VACUUM FULL takes an exclusive lock on the two tables
for the duration of the rewrite — seconds for tables this size — and cannot
run inside a transaction, hence the autocommit connection.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

# name -> "ok" | "skipped" | "failed: ..."; merged into GET /api/health/schema.
RESULT: dict[str, str] = {}

_MOVE = """
ALTER TABLE datasheet_versions ADD COLUMN IF NOT EXISTS document_id integer
    REFERENCES documents(id);
ALTER TABLE datasheet_pages ADD COLUMN IF NOT EXISTS document_id integer
    REFERENCES documents(id);

-- One document per distinct byte content. The earliest version's copy wins;
-- they are byte-identical by definition, so it does not matter which.
--
-- `text_layer` is deliberately NOT carried over. The inherited tag was
-- decided by the OLD rules, which had no text hash and let a filename call an
-- HTML page a PDF, and the startup backfill only claims rows that are
-- unclassified or searchable-without-a-hash — so an inherited "scan" would
-- keep a verdict nothing would ever revisit. Empty means "not classified
-- yet", the backfill re-derives every row under the current rules, and the
-- one full pass costs about a minute on a corpus this size.
INSERT INTO documents (sha256, size_bytes, content_type, data, created_at,
                       text_layer, page_count, text_pages, pages_indexed_at)
SELECT DISTINCT ON (v.sha256)
       v.sha256, v.size_bytes, v.content_type, v.data, v.fetched_at,
       '', NULL, NULL, NULL
  FROM datasheet_versions v
 WHERE NOT EXISTS (SELECT 1 FROM documents d WHERE d.sha256 = v.sha256)
 ORDER BY v.sha256, v.id;

UPDATE datasheet_versions v SET document_id = d.id
  FROM documents d
 WHERE d.sha256 = v.sha256 AND v.document_id IS NULL;

-- Pages follow their version to its document, then duplicates go.
UPDATE datasheet_pages p SET document_id = v.document_id
  FROM datasheet_versions v
 WHERE p.datasheet_version_id = v.id AND p.document_id IS NULL;

DELETE FROM datasheet_pages p
 USING datasheet_pages q
 WHERE q.document_id = p.document_id
   AND q.page_no = p.page_no
   AND q.datasheet_version_id < p.datasheet_version_id;

-- A document counts as indexed when any of its versions was.
UPDATE documents d SET pages_indexed_at = s.m
  FROM (SELECT document_id, max(pages_indexed_at) AS m
          FROM datasheet_versions GROUP BY document_id) s
 WHERE s.document_id = d.id AND s.m IS NOT NULL;

ALTER TABLE datasheet_pages ALTER COLUMN document_id SET NOT NULL;
ALTER TABLE datasheet_pages DROP COLUMN datasheet_version_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_document_page
    ON datasheet_pages (document_id, page_no);
CREATE INDEX IF NOT EXISTS ix_datasheet_page_document
    ON datasheet_pages (document_id);

ALTER TABLE datasheet_versions ALTER COLUMN document_id SET NOT NULL;
ALTER TABLE datasheet_versions
    DROP COLUMN data,
    DROP COLUMN sha256,
    DROP COLUMN size_bytes,
    DROP COLUMN content_type,
    DROP COLUMN text_layer,
    DROP COLUMN page_count,
    DROP COLUMN text_pages,
    DROP COLUMN pages_indexed_at;
"""


VACUUM_STATE: dict = {"running": False, "started_at": None, "finished_at": None,
                      "before_bytes": None, "after_bytes": None, "last_error": None}


def _total_size(conn, tables: tuple[str, ...]) -> int:
    return sum(int(conn.execute(text("SELECT pg_total_relation_size(:t)"),
                                {"t": t}).scalar() or 0) for t in tables)


def reclaim_space(engine: Engine, tables: tuple[str, ...] = ("documents", "datasheet_pages"),
                  background: bool = True) -> bool:
    """Rewrite the datasheet tables so deleted blobs leave the disk.

    Postgres only marks a deleted row dead; the bytes stay in the table until
    it is rewritten, so dropping 68 documents changes `pg_total_relation_size`
    by nothing at all. VACUUM FULL is the rewrite. It takes an ACCESS
    EXCLUSIVE lock for its duration — reads of those tables block, which for
    a ~800 MB table is tens of seconds — and it cannot run inside a
    transaction, hence the autocommit connection and, by default, a thread:
    an HTTP request must not sit on a table rewrite.

    Returns False when a rewrite is already running."""
    import threading

    if VACUUM_STATE["running"]:
        return False
    VACUUM_STATE.update(running=True, last_error=None, after_bytes=None,
                        started_at=datetime.now(timezone.utc).isoformat(), finished_at=None)

    def run() -> None:
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                VACUUM_STATE["before_bytes"] = _total_size(conn, tables)
                for t in tables:
                    conn.execute(text(f"VACUUM FULL {t}"))  # noqa: S608 — fixed names
                VACUUM_STATE["after_bytes"] = _total_size(conn, tables)
            log.info("datasheet tables rewritten: "
                     f"{VACUUM_STATE['before_bytes'] / 1e6:.0f} MB -> "
                     f"{VACUUM_STATE['after_bytes'] / 1e6:.0f} MB")
        except Exception as e:  # noqa: BLE001 — the delete already landed
            VACUUM_STATE["last_error"] = str(e)
            log.warning(f"VACUUM FULL on the datasheet tables failed: {e}")
        finally:
            VACUUM_STATE["running"] = False
            VACUUM_STATE["finished_at"] = datetime.now(timezone.utc).isoformat()

    if not background:
        run()
        return True
    threading.Thread(target=run, daemon=True).start()
    return True


def _has_column(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"), {"t": table, "c": column}).scalar())


def _size(conn, table: str) -> int:
    return int(conn.execute(text("SELECT pg_total_relation_size(:t)"), {"t": table}).scalar() or 0)


def migrate_to_documents(engine: Engine) -> None:
    """Move the bytes, re-key the pages, drop the old columns, give the disk
    back. Logs what it did; never raises — startup must come up either way,
    and GET /api/health/schema shows the outcome."""
    try:
        with engine.begin() as conn:
            if not _has_column(conn, "datasheet_versions", "data"):
                RESULT["documents.move"] = "skipped"
                return
            before = _size(conn, "datasheet_versions") + _size(conn, "datasheet_pages")
            t0 = time.monotonic()
            n_versions = conn.execute(text("SELECT count(*) FROM datasheet_versions")).scalar()
            for stmt in [s.strip() for s in _MOVE.split(";") if s.strip()]:
                conn.execute(text(stmt))
            n_docs = conn.execute(text("SELECT count(*) FROM documents")).scalar()
            n_pages = conn.execute(text("SELECT count(*) FROM datasheet_pages")).scalar()
        RESULT["documents.move"] = "ok"
        log.info(
            f"datasheet bytes moved into documents: {n_versions} versions -> {n_docs} distinct "
            f"documents, {n_pages} page rows kept, {time.monotonic() - t0:.1f}s")
    except Exception as e:  # noqa: BLE001 — see the docstring
        RESULT["documents.move"] = f"failed: {e}"
        log.warning(f"datasheet document migration did not complete: {type(e).__name__}: {e}")
        return

    # Hand the disk back: the dropped `data` column's bytes live on in the
    # dead tuples until the table is rewritten. Synchronous on purpose — this
    # is startup, before the app serves anything.
    t0 = time.monotonic()
    reclaim_space(engine, ("datasheet_versions", "datasheet_pages", "documents"),
                  background=False)
    if VACUUM_STATE["last_error"]:
        RESULT["documents.vacuum"] = f"failed: {VACUUM_STATE['last_error']}"
        log.warning("The move is complete; run VACUUM FULL datasheet_versions by hand.")
    else:
        RESULT["documents.vacuum"] = "ok"
        log.info(f"reclaimed in {time.monotonic() - t0:.1f}s: {before / 1e6:.0f} MB before the "
                 f"move, {VACUUM_STATE['after_bytes'] / 1e6:.0f} MB after")
