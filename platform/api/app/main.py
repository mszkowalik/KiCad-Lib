from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import settings
from .db import Base, engine
from .routers import (
    categories,
    comments,
    components,
    datasheets,
    import_station,
    jaravis,
    jlc_stock,
    kicad_http,
    kicad_sync,
    libraries,
    production_runs,
    projects,
    proposals,
    skills,
    view,
)

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

# Published-state file mirror, served read-only (sync + downloads).
app.mount("/files", StaticFiles(directory=settings.mirror_dir), name="files")


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
            conn.execute(text(
                "ALTER TABLE component_supply ADD COLUMN IF NOT EXISTS jlc_stock integer"
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
    if settings.datasheet_autofetch:
        # Fetch missing datasheet PDFs in the background (idempotent —
        # only datasheets without a local copy are downloaded).
        import threading

        from .services.datasheet_store import start_fetch_all

        threading.Timer(10.0, lambda: start_fetch_all("missing")).start()
    if settings.fx_autofetch:
        from .services.fx import start_auto_refresh

        start_auto_refresh()
    if settings.price_ladder_autofetch:
        from .services.ladder import start_background_refresh

        start_background_refresh()
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
