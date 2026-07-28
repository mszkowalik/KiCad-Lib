import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import settings
from .db import Base, engine
from .routers import (
    agent,
    categories,
    comments,
    components,
    datasheets,
    import_station,
    jaravis,
    jlc_import,
    jlc_stock,
    jlc_web,
    kicad_http,
    kicad_sync,
    ledger,
    libraries,
    production_runs,
    projects,
    proposals,
    run_costs,
    skills,
    view,
)

log = logging.getLogger(__name__)

settings.ensure_dirs()

app = FastAPI(title="Project Management Platform", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(categories.router)
app.include_router(components.router)
app.include_router(libraries.router)
app.include_router(datasheets.router)
app.include_router(jaravis.router)
app.include_router(agent.router)
app.include_router(proposals.router)
app.include_router(comments.router)
app.include_router(skills.router)
app.include_router(kicad_sync.router)
app.include_router(import_station.router)
app.include_router(kicad_http.router)
app.include_router(view.router)
app.include_router(projects.router)
app.include_router(production_runs.router)
app.include_router(jlc_stock.router)
app.include_router(jlc_web.router)
app.include_router(jlc_import.router)
app.include_router(ledger.router)
app.include_router(run_costs.router)

# Published-state file mirror, served read-only (sync + downloads).
app.mount("/files", StaticFiles(directory=settings.mirror_dir), name="files")


# Partial UNIQUE indexes that make a re-run of a supplier import idempotent
# rather than additive. Each is created in its OWN transaction, and a failure is
# LOGGED WITH THE OFFENDING ROWS rather than swallowed — unlike the column adds
# above, which share one transaction where a bare `except: pass` would silently
# skip everything after the first error. A duplicate here means real data needs
# a human decision, so startup must say so plainly and still come up.
_DEDUP_INDEXES = (
    (
        "uq_run_cost_doc_external",
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_run_cost_doc_external "
            "ON run_cost_documents (supplier, external_id) WHERE external_id <> ''"
        ),
        (
            "SELECT supplier, external_id, COUNT(*) n, STRING_AGG(id::text, ',') ids "
            "FROM run_cost_documents WHERE external_id <> '' "
            "GROUP BY supplier, external_id HAVING COUNT(*) > 1"
        ),
    ),
    (
        "uq_consumption_import",
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_consumption_import "
            "ON component_consumptions (import_ref) WHERE import_ref <> ''"
        ),
        (
            "SELECT import_ref, COUNT(*) n, STRING_AGG(id::text, ',') ids "
            "FROM component_consumptions WHERE import_ref <> '' "
            "GROUP BY import_ref HAVING COUNT(*) > 1"
        ),
    ),
)


# Additive schema for the UI-driven import workflow. Kept SEPARATE from the big
# shared-transaction block in `startup()`: that one runs under a bare
# `except: pass`, so one failing statement silently skips every statement after
# it and the app comes up looking healthy with half a schema. These run one
# transaction each, and `GET /api/health/schema` reports which landed — a
# migration that half-applies must be visible, not inferred from a later crash.
_PHASE1_DDL = (
    # WHY a line is charged to nobody. `excluded` is a legal bucket in the
    # conservation identity, so the $14,443 incident passed every check.
    ("run_cost_lines.exclude_reason",
     "ALTER TABLE run_cost_lines ADD COLUMN IF NOT EXISTS "
     "exclude_reason varchar(40) NOT NULL DEFAULT ''"),
    # Make the historical exclusions LINT on deploy day rather than be inherited
    # as green. Anything already excluded has, by definition, no stated reason.
    ("run_cost_lines.exclude_reason backfill",
     "UPDATE run_cost_lines SET exclude_reason = 'legacy_unstated' "
     "WHERE allocate = 'excluded' AND exclude_reason = ''"),
    # The supplier's own line identity — computed by the planner since the first
    # import and stored nowhere, which is why the line -> order join had to be
    # recovered from `label` text by two repair scripts.
    ("run_cost_lines.external_line_id",
     "ALTER TABLE run_cost_lines ADD COLUMN IF NOT EXISTS "
     "external_line_id varchar(120) NOT NULL DEFAULT ''"),
    ("ix_run_cost_line_extline",
     "CREATE INDEX IF NOT EXISTS ix_run_cost_line_extline "
     "ON run_cost_lines (external_line_id) WHERE external_line_id <> ''"),
    # Recover the key on lines imported before the column existed. The planner has
    # always built the label as "<order type> - <order code>", with the two carved
    # children as "Prepaid components - …" and "Assembly work - …", so the join is
    # derivable from the text it was hiding in. Without this, every line written
    # during the 2026-07 backfill is invisible to `reclassify_order_lines` and a
    # decision could never revisit its own charges.
    # The suffixes are spelled `':' || 'prepaid'` rather than `':prepaid'` because
    # SQLAlchemy's `text()` regex-scans for `:name` bind parameters without parsing
    # SQL, so a literal colon inside a quoted string is claimed as a parameter and
    # the statement fails at execute time. Caught by GET /api/health/schema.
    ("run_cost_lines.external_line_id backfill",
     r"""UPDATE run_cost_lines SET external_line_id = CASE
             WHEN label LIKE 'Prepaid components - %'
                  THEN (regexp_match(label, '(SMT[A-Za-z0-9-]+)'))[1] || ':' || 'prepaid'
             WHEN label LIKE 'Assembly work - %'
                  THEN (regexp_match(label, '(SMT[A-Za-z0-9-]+)'))[1] || ':' || 'work'
             ELSE (regexp_match(label, '(SMT[A-Za-z0-9-]+)'))[1]
         END
         WHERE external_line_id = '' AND label ~ 'SMT[A-Za-z0-9-]+'"""),
    # Draws become voidable instead of deletable, so an import that superseded a
    # forecast can be reversed. Every read filters `voided_at IS NULL`.
    ("component_consumptions.voided_at",
     "ALTER TABLE component_consumptions ADD COLUMN IF NOT EXISTS voided_at timestamptz"),
    ("component_consumptions.void_reason",
     "ALTER TABLE component_consumptions ADD COLUMN IF NOT EXISTS "
     "void_reason varchar(40) NOT NULL DEFAULT ''"),
    # A constraint replacing the `note LIKE '%code%'` text scan that stood in for
    # idempotency in `apply_external_movements`.
    ("component_stock_adjustments.import_ref",
     "ALTER TABLE component_stock_adjustments ADD COLUMN IF NOT EXISTS "
     "import_ref varchar(120) NOT NULL DEFAULT ''"),
    ("uq_stock_adj_import",
     "CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_adj_import "
     "ON component_stock_adjustments (import_ref) WHERE import_ref <> ''"),
    # JLC's per-(order, part) `componentSource`: who actually supplied the part.
    ("jlc_imports.bom_info",
     "ALTER TABLE jlc_imports ADD COLUMN IF NOT EXISTS bom_info jsonb"),
    # Session liveness, so a dead login is discovered before an import starts —
    # and so the session's real lifetime gets measured instead of assumed.
    ("jlc_web_sessions.died_at",
     "ALTER TABLE jlc_web_sessions ADD COLUMN IF NOT EXISTS died_at timestamptz"),
    ("jlc_web_sessions.last_error",
     "ALTER TABLE jlc_web_sessions ADD COLUMN IF NOT EXISTS "
     "last_error varchar(300) NOT NULL DEFAULT ''"),
    ("jlc_web_sessions.keepalive_count",
     "ALTER TABLE jlc_web_sessions ADD COLUMN IF NOT EXISTS "
     "keepalive_count integer NOT NULL DEFAULT 0"),
)

# name -> "ok" | "failed: ..."; served by GET /api/health/schema.
_SCHEMA_RESULTS: dict[str, str] = {}


def _ensure_phase1_schema() -> None:
    for name, ddl in _PHASE1_DDL:
        try:
            with engine.begin() as conn:
                conn.execute(text(ddl))
            _SCHEMA_RESULTS[name] = "ok"
        except Exception as e:  # noqa: BLE001 — never block startup on a column add
            _SCHEMA_RESULTS[name] = f"failed: {e}"
            log.warning(
                f"schema statement {name!r} failed: {e}. "
                "The features depending on it will misbehave; see GET /api/health/schema."
            )


def _find_duplicates(dupe_sql: str) -> list[tuple]:
    """Best-effort: why did the index fail? Returns [] if even this cannot run."""
    try:
        with engine.begin() as conn:
            return [tuple(r) for r in conn.execute(text(dupe_sql)).fetchall()]
    except Exception as e:  # noqa: BLE001 — diagnostics must never raise
        log.warning(f"could not query for duplicates: {e}")
        return []


def _ensure_dedup_indexes() -> None:
    for name, ddl, dupe_sql in _DEDUP_INDEXES:
        try:
            with engine.begin() as conn:
                conn.execute(text(ddl))
        except Exception as e:  # noqa: BLE001 — never block startup on this
            dupes = _find_duplicates(dupe_sql)
            log.warning(
                f"could not create {name}: {e}. "
                f"Duplicate groups blocking it: {dupes or 'none found (different cause)'}. "
                "Imports are NOT protected against duplication until this is resolved."
            )


@app.on_event("startup")
def startup() -> None:
    try:
        Base.metadata.create_all(engine)
        # Idempotent column adds on pre-existing tables (create_all only
        # creates missing tables, it never alters existing ones).
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE components ADD COLUMN IF NOT EXISTS in_library boolean NOT NULL DEFAULT true"
            ))
            conn.execute(text(
                "ALTER TABLE components ADD COLUMN IF NOT EXISTS purchasable boolean NOT NULL DEFAULT true"
            ))
            conn.execute(text(
                "ALTER TABLE datasheet_versions ADD COLUMN IF NOT EXISTS etag varchar(300)"
            ))
            conn.execute(text(
                "ALTER TABLE datasheet_versions ADD COLUMN IF NOT EXISTS last_modified varchar(100)"
            ))
            conn.execute(text(
                "ALTER TABLE project_notes ADD COLUMN IF NOT EXISTS sha varchar(40) NOT NULL DEFAULT ''"
            ))
            conn.execute(text(
                "ALTER TABLE project_notes ADD COLUMN IF NOT EXISTS ref_name varchar(200) NOT NULL DEFAULT ''"
            ))
            # Commit-anchored cost revisions: adopt pre-versioning rows into a
            # "since forever" revision per project (idempotent backfill).
            conn.execute(text(
                "ALTER TABLE project_extra_bom_items ADD COLUMN IF NOT EXISTS revision_id integer"
            ))
            conn.execute(text(
                "ALTER TABLE project_cost_items ADD COLUMN IF NOT EXISTS revision_id integer"
            ))
            conn.execute(text(
                "ALTER TABLE project_cost_items ADD COLUMN IF NOT EXISTS steps jsonb"
            ))
            # Production-step identity (services/cost_steps.py) — the key that
            # matches a planned cost item to the invoice lines billed under it.
            conn.execute(text(
                "ALTER TABLE project_cost_items ADD COLUMN IF NOT EXISTS "
                "step_key varchar(40) NOT NULL DEFAULT ''"
            ))
            conn.execute(text(
                "ALTER TABLE component_supply ADD COLUMN IF NOT EXISTS jlc_stock integer"
            ))
            # The firmware+steps bundle a production batch is programmed with.
            conn.execute(text(
                "ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS release_version_id integer"
            ))
            # Cost baseline pinning + real yield, so a historical run's expected
            # figure cannot drift and its per-device actual divides by good units.
            for col, typ in (("plan_revision_id", "integer"), ("plan_frozen_at", "timestamptz"),
                             ("plan_qty", "integer"), ("qty_good", "integer"),
                             # the sale side: price per device + the customer order it
                             # belongs to, so income and margin compute against cost
                             ("sale_unit_price", "double precision"),
                             ("sale_currency", "varchar(10) NOT NULL DEFAULT ''"),
                             ("qty_sold", "integer"),
                             ("customer", "varchar(200) NOT NULL DEFAULT ''"),
                             ("order_ref", "varchar(200) NOT NULL DEFAULT ''"),
                             ("order_date", "varchar(20) NOT NULL DEFAULT ''")):
                conn.execute(text(
                    f"ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS {col} {typ}"
                ))
            # A supplier document may be SHARED across projects (one parts
            # invoice covering several products), so it needs no project.
            conn.execute(text(
                "ALTER TABLE run_cost_documents ALTER COLUMN project_id DROP NOT NULL"
            ))
            # Invoice positions split into a tree: shares charged to different
            # runs, and a supplier's own sub-breakdown of one printed figure.
            conn.execute(text(
                "ALTER TABLE run_cost_lines ADD COLUMN IF NOT EXISTS parent_line_id integer"
            ))
            conn.execute(text(
                "ALTER TABLE run_cost_lines ADD COLUMN IF NOT EXISTS project_id integer"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_run_cost_line_parent "
                "ON run_cost_lines (parent_line_id)"
            ))
            # An attachment may belong to a supplier DOCUMENT instead of a run, so
            # a scanned invoice can be filed with the money it evidences — including
            # on a shared document, which has no run at all.
            conn.execute(text(
                "ALTER TABLE run_attachments ALTER COLUMN run_id DROP NOT NULL"
            ))
            conn.execute(text(
                "ALTER TABLE run_attachments ADD COLUMN IF NOT EXISTS document_id integer"
            ))
            # Provenance of an IMPORTED draw. Empty for every hand-made row, so
            # the unique index below constrains only what an importer wrote and
            # can never reject existing data. This is the column that makes a
            # re-run of a supplier import idempotent instead of additive —
            # `component_consumptions` has had no uniqueness of any kind, which
            # is how components 324/325 were drawn twice across five runs.
            conn.execute(text(
                "ALTER TABLE component_consumptions ADD COLUMN IF NOT EXISTS "
                "import_ref varchar(120) NOT NULL DEFAULT ''"
            ))
            # Lot identity on a purchase line. A LOT IS ALREADY A ROW — a leaf
            # part line with no run — so lots are made first-class by naming
            # them, not by copying them into a parallel table that could drift
            # from the money rows. `lot_ref` holds the supplier's own per-lot key
            # (JLC `presaleGoodsKeyId`), which is what lets a draw record WHICH
            # purchase it consumed as reported fact rather than inferred FIFO.
            conn.execute(text(
                "ALTER TABLE run_cost_lines ADD COLUMN IF NOT EXISTS "
                "lot_ref varchar(120) NOT NULL DEFAULT ''"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_run_cost_line_lot "
                "ON run_cost_lines (lot_ref) WHERE lot_ref <> ''"
            ))
            # Panelisation per smtOrderCode, cached from the order-centre view.
            # It lives on a different endpoint from the invoice and is the ONLY
            # authoritative device count, so the decision queue caches it rather
            # than making an extra round trip per batch on every page load.
            conn.execute(text(
                "ALTER TABLE jlc_imports ADD COLUMN IF NOT EXISTS panel_info jsonb"
            ))
            conn.execute(text(
                "ALTER TABLE skills ADD COLUMN IF NOT EXISTS description varchar(500) NOT NULL DEFAULT ''"
            ))
            conn.execute(text(
                "ALTER TABLE footprints ADD COLUMN IF NOT EXISTS display_name varchar(200) NOT NULL DEFAULT ''"
            ))
            conn.execute(text(
                """
                INSERT INTO project_cost_revisions
                    (project_id, effective_sha, effective_ref, created_at)
                SELECT t.project_id, '', '', now() FROM (
                    SELECT project_id FROM project_extra_bom_items WHERE revision_id IS NULL
                    UNION
                    SELECT project_id FROM project_cost_items WHERE revision_id IS NULL
                ) t
                WHERE NOT EXISTS (
                    SELECT 1 FROM project_cost_revisions r
                    WHERE r.project_id = t.project_id AND r.effective_sha = ''
                )
                """
            ))
            conn.execute(text(
                """
                UPDATE project_extra_bom_items x SET revision_id = r.id
                FROM project_cost_revisions r
                WHERE x.revision_id IS NULL
                  AND r.project_id = x.project_id AND r.effective_sha = ''
                """
            ))
            conn.execute(text(
                """
                UPDATE project_cost_items c SET revision_id = r.id
                FROM project_cost_revisions r
                WHERE c.revision_id IS NULL
                  AND r.project_id = c.project_id AND r.effective_sha = ''
                """
            ))
            # Seed price history from the current point sets (idempotent —
            # only components with no history yet). recorded_at = the set's
            # last refresh, so pre-existing runs resolve to it as the
            # closest snapshot.
            conn.execute(text(
                """
                INSERT INTO component_price_history (component_id, points, recorded_at)
                SELECT p.component_id,
                       jsonb_agg(jsonb_build_object(
                           'source', p.source, 'qty_from', p.qty_from,
                           'unit_price', p.unit_price, 'currency', p.currency
                       ) ORDER BY p.source, p.qty_from),
                       max(p.updated_at)
                FROM component_price_points p
                WHERE NOT EXISTS (
                    SELECT 1 FROM component_price_history h
                    WHERE h.component_id = p.component_id
                )
                GROUP BY p.component_id
                """
            ))
            conn.execute(text(
                """
                INSERT INTO exchange_rate_history (currency, rate_usd, recorded_at)
                SELECT r.currency, r.rate_usd, r.updated_at FROM exchange_rates r
                WHERE NOT EXISTS (
                    SELECT 1 FROM exchange_rate_history h WHERE h.currency = r.currency
                )
                """
            ))
            # Fold the legacy component_comments table into the generic
            # `comments` table (target_type='component'), then DRAIN the source
            # so this is idempotent — a second startup copies zero rows and can
            # never resurrect comments deleted through the new path.
            conn.execute(text(
                """
                INSERT INTO comments (target_type, target_id, author, body, created_at)
                SELECT 'component', component_id, author, body, created_at
                FROM component_comments
                """
            ))
            conn.execute(text("DELETE FROM component_comments"))
    except Exception:
        # DB may still be starting; the import endpoint will create tables anyway.
        pass
    _ensure_phase1_schema()
    _ensure_dedup_indexes()
    if settings.datasheet_autofetch:
        # Fetch missing datasheet PDFs in the background (idempotent —
        # only datasheets without a local copy are downloaded).
        import threading

        from .services.datasheet_store import start_fetch_all

        threading.Timer(10.0, lambda: start_fetch_all("missing", trigger="startup")).start()
    if settings.datasheet_recheck_nightly:
        # Nightly conditional re-check of every source URL: changed documents
        # become new versions and bump their component version.
        from .services.datasheet_store import start_nightly_recheck

        start_nightly_recheck(settings.datasheet_recheck_hour)
    if settings.fx_autofetch:
        from .services.fx import start_auto_refresh

        start_auto_refresh()
    if settings.price_ladder_autofetch:
        from .services.ladder import start_background_refresh

        start_background_refresh()
    if settings.jlc_session_keepalive_min:
        # Touch the jlcpcb.com session periodically. Two payoffs: if JLC expires
        # sessions on inactivity this removes the re-paste chore entirely, and
        # either way `died_at - updated_at` finally measures the real lifetime.
        from .services.jlc_web import start_keepalive

        start_keepalive(settings.jlc_session_keepalive_min)
    # warm the KiCad PCM packages so the first PCM request doesn't wait for
    # the 1.4 GB models zip to build
    from .services import pcm

    pcm.start_background_build()


@app.get("/api/health")
def health():
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    return {"ok": True, "db": db_ok}


@app.get("/api/health/schema")
def health_schema():
    """Which additive schema statements landed on this database.

    The startup DDL is best-effort by design — the app must come up even against
    a database that is still starting. That makes a half-applied schema silent,
    and a feature that depends on a column which was never added fails somewhere
    far away from the cause. This is where to look first.
    """
    failed = {k: v for k, v in _SCHEMA_RESULTS.items() if v != "ok"}
    return {
        "ok": not failed,
        "statements": _SCHEMA_RESULTS,
        "failed": failed,
        "note": ("every statement applied" if not failed else
                 "SOME STATEMENTS DID NOT APPLY — features depending on these "
                 "columns will misbehave until they do"),
    }
