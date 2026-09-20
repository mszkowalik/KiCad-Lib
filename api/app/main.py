import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .authgate import AuthGate
from .config import settings
from .db import Base, engine
from .routers import (
    account,
    agent,
    auth as auth_router,
    categories,
    changes,
    comments,
    components,
    datasheets,
    field_solver,
    flasher,
    git_credentials,
    import_station,
    jaravis,
    jlc_import,
    jlc_stock,
    jlc_web,
    kicad_http,
    kicad_sync,
    ledger,
    libraries,
    models3d,
    mqtt,
    production_runs,
    projects,
    reviews,
    run_costs,
    settings as settings_router,
    sim_models,
    sim_runs,
    signoffs,
    skills,
    users,
    view,
    orders,
)

log = logging.getLogger(__name__)

settings.ensure_dirs()

app = FastAPI(title="Project Management Platform", version="0.1.0")

# ORDER MATTERS, and it is the reverse of the reading order: `add_middleware`
# prepends, so the LAST one added is the OUTERMOST and runs first. CORS must be
# outermost — otherwise the gate's own 401 leaves the stack without CORS
# headers and a cross-origin dev browser reports an opaque network failure
# instead of the 401 it can act on.
#
# Default-deny gate, inner. It covers the /files mount and the flasher
# WebSocket, neither of which a router dependency can reach. See authgate.py.
app.add_middleware(AuthGate)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
    # The session lives in a cookie, so a cross-origin dev server must be
    # allowed to send it. This is why cors_origins is an explicit list and
    # never "*" — the CORS spec forbids the two together, and a wildcard here
    # would silently stop the dev login from working.
    allow_credentials=True,
    # A cross-origin response hands JavaScript only the six CORS-safelisted
    # headers unless it says otherwise. `X-Unit-Count` is how a symbol preview
    # learns the drawing has ten units to page through (services/svg_units.py),
    # so without this line every multi-unit symbol loses its arrows in dev and
    # keeps them in production — the worst way for a bug to behave.
    expose_headers=["X-Unit-Count", "X-Version-Id"],
)

app.include_router(auth_router.router)
app.include_router(users.router)
app.include_router(categories.router)
app.include_router(components.router)
app.include_router(libraries.router)
app.include_router(sim_models.router)
app.include_router(sim_runs.router)
app.include_router(field_solver.router)
app.include_router(models3d.router)
app.include_router(datasheets.router)
app.include_router(jaravis.router)
app.include_router(agent.router)
app.include_router(comments.router)
app.include_router(signoffs.router)
app.include_router(reviews.router)
app.include_router(changes.router)
app.include_router(skills.router)
app.include_router(settings_router.router)
app.include_router(kicad_sync.router)
app.include_router(import_station.router)
app.include_router(kicad_http.router)
app.include_router(view.router)
app.include_router(projects.router)
app.include_router(git_credentials.router)
app.include_router(account.router)
app.include_router(production_runs.router)
app.include_router(jlc_stock.router)
app.include_router(jlc_web.router)
app.include_router(jlc_import.router)
app.include_router(ledger.router)
app.include_router(run_costs.router)
app.include_router(flasher.router)
app.include_router(mqtt.router)
app.include_router(orders.router)

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
    # A rule row scoped to a CATEGORY, not to a YAML library name. The 15 rows
    # the import seeded carried `library_name` only and nothing resolved them,
    # so every per-category property rule ("a Capacitor carries Value and
    # Voltage") had never been enforced. A name also cannot reach a
    # sub-category and breaks on a rename, which is the same reason
    # `services/rename.py` exists.
    ("rules.category_id",
     "ALTER TABLE rules ADD COLUMN IF NOT EXISTS category_id integer"),
    # Match each seeded row to the top-level category of the same name. A row
    # whose library has no category left simply stays unresolved and inert,
    # which is what it already was.
    ("rules.category_id backfill",
     "UPDATE rules SET category_id = c.id FROM categories c "
     "WHERE rules.scope = 'library' AND rules.category_id IS NULL "
     "AND c.parent_id IS NULL AND c.name = rules.library_name"),
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
    # A draw may now exist with no run: the stock left the shelf, and who pays
    # is a later, separate judgement. See `ComponentConsumption.run_id`.
    ("component_consumptions.run_id_nullable",
     "ALTER TABLE component_consumptions ALTER COLUMN run_id DROP NOT NULL"),
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
    # What a deployment IS, so the bench offers Program / Test from data rather
    # than from a name match. Backfilled from the names the retro import gave
    # them ("Dongle_V2 test", "Aqua_V2 test"); marking procedures come later.
    ("deployments.kind",
     "ALTER TABLE deployments ADD COLUMN IF NOT EXISTS "
     "kind varchar(20) NOT NULL DEFAULT 'flash'"),
    # The backfill that read a deployment's KIND out of its NAME has been
    # removed (user decision 2026-09-18). It ran on every boot, so a deployment
    # created tomorrow and called "… test" would be silently reclassified — a
    # guess from a text string, stored as a fact about what the bench does.
    # The historical rows it filled keep their value; new ones are set by hand.
    # The DEFAULT ticked on a new batch of this project. False on every test
    # deployment and true on everything else, so a deploy lands with NO test
    # required anywhere (user decision 2026-09-16): a fleet cannot go unverified
    # overnight, and turning a product's test on is one click in the Deployments
    # tab when its flow is ready for it.
    ("deployments.active",
     "ALTER TABLE deployments ADD COLUMN IF NOT EXISTS "
     "active boolean NOT NULL DEFAULT false"),
    # Removed with the backfill above, which it depended on: it turned every
    # deployment the name-guess had NOT called a test into an active one.
    # Whether a batch's units must pass the test, and the copy each programming
    # run keeps of that answer. Both default false: every run already recorded
    # required nothing, and a new rule must never re-judge a finished device.
    ("production_runs.requires_test",
     "ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS "
     "requires_test boolean NOT NULL DEFAULT false"),
    ("programming_runs.test_required",
     "ALTER TABLE programming_runs ADD COLUMN IF NOT EXISTS "
     "test_required boolean NOT NULL DEFAULT false"),
    # An erase runs no procedure, but it identifies a device and produces a log
    # the operator needs beside the programming runs (user decision 2026-09-16,
    # after a unit that could not be programmed left no trace).
    ("programming_runs.action",
     "ALTER TABLE programming_runs ADD COLUMN IF NOT EXISTS "
     "action varchar(20) NOT NULL DEFAULT 'program'"),
    ("programming_runs.version_nullable",
     "ALTER TABLE programming_runs ALTER COLUMN deployment_version_id DROP NOT NULL"),
    # JLC's per-(order, part) `componentSource`: who actually supplied the part.
    ("jlc_imports.bom_info",
     "ALTER TABLE jlc_imports ADD COLUMN IF NOT EXISTS bom_info jsonb"),
    # JLC's own batch status, so a cancelled order stops reading as work to do.
    ("jlc_imports.jlc_status",
     "ALTER TABLE jlc_imports ADD COLUMN IF NOT EXISTS "
     "jlc_status varchar(20) NOT NULL DEFAULT ''"),
    # WHO SUPPLIED a substituted part, which was being inferred from the
    # absence of a draw. `create_all` builds a missing TABLE and never a
    # missing COLUMN, so a field added to a table that already shipped needs
    # its own line here.
    ("run_substitutions.supplied_by",
     "ALTER TABLE run_substitutions ADD COLUMN IF NOT EXISTS "
     "supplied_by varchar(20) NOT NULL DEFAULT ''"),
    ("run_substitutions.supplier_source",
     "ALTER TABLE run_substitutions ADD COLUMN IF NOT EXISTS "
     "supplier_source varchar(40) NOT NULL DEFAULT ''"),
    # Per-order fee breakdown (orderCountTolls / smtPriceInfo) — what lets an
    # invoice line be split into vendor-neutral production steps.
    ("jlc_imports.fee_info",
     "ALTER TABLE jlc_imports ADD COLUMN IF NOT EXISTS fee_info jsonb"),
    # Reconnect staging to the documents it produced. The 2026-07 backfill wrote
    # documents with scripts that never stamped `status`/`document_id`, so all 37
    # rows read `staged` against 24 documents actually imported — and the table
    # designed to answer "what is left to import?" answered it wrongly, offering
    # to re-import money that was already in.
    ("jlc_imports.document_id backfill",
     "UPDATE jlc_imports i SET document_id = d.id, status = 'imported' "
     "FROM run_cost_documents d "
     "WHERE i.document_id IS NULL AND d.supplier = 'JLCPCB' "
     "  AND ((i.external_id <> '' AND d.external_id = i.external_id) "
     "       OR (i.invoice_no <> '' AND d.doc_number = i.invoice_no))"),
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
    # Production sign-off. `material_sha` caches services/material.py's
    # fingerprint of what a drawing puts on the board; `recheck_required` is
    # the approver's answer to "does this change need a new verification?".
    # NULL means nobody was ever asked, which is true of all existing rows —
    # `signoff.py` then falls back to comparing the fingerprints, so history
    # behaves sensibly without a backfilled opinion nobody actually held.
    ("symbol_versions.material_sha",
     "ALTER TABLE symbol_versions ADD COLUMN IF NOT EXISTS "
     "material_sha varchar(64) NOT NULL DEFAULT ''"),
    ("symbol_versions.recheck_required",
     "ALTER TABLE symbol_versions ADD COLUMN IF NOT EXISTS recheck_required boolean"),
    ("footprint_versions.material_sha",
     "ALTER TABLE footprint_versions ADD COLUMN IF NOT EXISTS "
     "material_sha varchar(64) NOT NULL DEFAULT ''"),
    ("footprint_versions.recheck_required",
     "ALTER TABLE footprint_versions ADD COLUMN IF NOT EXISTS recheck_required boolean"),
    # The resolved checklist a review record was measured against. Before it,
    # only the BASE checklist version was pinned, so an unanswered
    # category-scoped item read as partial when the check was saved and as
    # checked on the next load. Old rows stay NULL and keep the old behaviour
    # rather than being given an opinion nobody recorded.
    ("review_records.checklist_items",
     "ALTER TABLE review_records ADD COLUMN IF NOT EXISTS checklist_items jsonb"),
    # Judgment items closed by a standing exception, computed beside the machine
    # answers. Cache columns, so an empty default is correct and a NULL row just
    # recomputes on the next read — no backfill.
    ("conformance.excused",
     "ALTER TABLE conformance ADD COLUMN IF NOT EXISTS excused jsonb "
     "NOT NULL DEFAULT '[]'::jsonb"),
    # Which archived datasheets are searchable PDFs and which are pure scans.
    # The searchable-PDF classification (text_layer, page_count, text_pages)
    # and the page-index marker used to be columns here on datasheet_versions.
    # Since 2026-09-10 they live on `documents`, which create_all builds whole;
    # services/datasheet_migrate.py moved the data and dropped the old columns.
    # Never re-add them — the migration keys off `datasheet_versions.data`.
    # The search vector is a GENERATED column, so it can never disagree with
    # the content beside it — no trigger to forget and no app code to skip.
    # The config is `simple` and must stay identical to
    # datasheet_pages._TSCONFIG: a query parsed with a different config does
    # not match this index and Postgres silently falls back to a seq scan.
    # `english` was rejected on purpose — datasheet tokens are part numbers,
    # package codes and dimensions, which stemming damages.
    ("datasheet_pages.tsv",
     "ALTER TABLE datasheet_pages ADD COLUMN IF NOT EXISTS tsv tsvector "
     "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED"),
    ("ix_datasheet_pages_tsv",
     "CREATE INDEX IF NOT EXISTS ix_datasheet_pages_tsv "
     "ON datasheet_pages USING GIN (tsv)"),
    # Decision 0003: the device's current state and its batch, both caches of
    # `device_events`. "" = no event yet (a legacy unit whose batch was never
    # recorded); NULL run = the same.
    ("device_units.state",
     "ALTER TABLE device_units ADD COLUMN IF NOT EXISTS state varchar(20) NOT NULL DEFAULT ''"),
    ("device_units.production_run_id",
     "ALTER TABLE device_units ADD COLUMN IF NOT EXISTS production_run_id integer"),
    # A device's CONDITION, independent of its location. `state` says where the
    # unit is; this says what it is. Only `ok` may be shipped, so a faulty or
    # prototype unit can sit in stock, be counted, and never be picked.
    ("device_units.condition",
     "ALTER TABLE device_units ADD COLUMN IF NOT EXISTS "
     "condition varchar(20) NOT NULL DEFAULT 'ok'"),
    ("ix_device_units_condition",
     "CREATE INDEX IF NOT EXISTS ix_device_units_condition ON device_units (condition)"),
    ("ix_device_units_state",
     "CREATE INDEX IF NOT EXISTS ix_device_units_state ON device_units (state)"),
    ("ix_device_units_prod_run",
     "CREATE INDEX IF NOT EXISTS ix_device_units_prod_run ON device_units (production_run_id)"),
    # Decision 0010: a git token belongs to an ACCOUNT, not to each project
    # that happens to use it. `git_credentials` is a new table and arrives via
    # create_all; this is the pointer from the existing projects row. The
    # FK is added separately so a failure to add it cannot cost us the column.
    ("projects.git_credential_id",
     "ALTER TABLE projects ADD COLUMN IF NOT EXISTS git_credential_id integer"),
    ("ix_projects_git_credential",
     "CREATE INDEX IF NOT EXISTS ix_projects_git_credential ON projects (git_credential_id)"),
    ("projects.git_credential_id fk",
     "DO $$ BEGIN "
     "ALTER TABLE projects ADD CONSTRAINT fk_projects_git_credential "
     "FOREIGN KEY (git_credential_id) REFERENCES git_credentials (id); "
     "EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    # Decision 0024: a version DECLARES the parameters it needs, so editing a
    # project's values can refuse a change that breaks a published version
    # instead of failing at the bench. NULL means "never published under the
    # new rule" and the validator falls back to walking the steps, which is
    # what it always did — no backfill, nothing breaks.
    ("deployment_versions.param_schema",
     "ALTER TABLE deployment_versions ADD COLUMN IF NOT EXISTS param_schema jsonb"),
    # `param_set_revisions` is a new table and arrives via create_all. These
    # are the pointers from existing rows. Each FK is its own statement so a
    # failure to add one cannot cost us the column.
    ("programming_runs.param_set_revision_id",
     "ALTER TABLE programming_runs ADD COLUMN IF NOT EXISTS "
     "param_set_revision_id integer"),
    ("programming_runs.param_set_revision_id fk",
     "DO $$ BEGIN "
     "ALTER TABLE programming_runs ADD CONSTRAINT fk_programming_run_param_rev "
     "FOREIGN KEY (param_set_revision_id) REFERENCES param_set_revisions (id); "
     "EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    # `param_set_id` was a plain integer — a "soft pointer" — so deleting a set
    # left every version pointing at a dead id and the failure surfaced as
    # "no parameter defines {MqttHost}". Verified 0 dangling rows before this
    # was added (2026-09-17).
    # Revert needs the values, not just the names of what moved (user request
    # 2026-09-17). Encrypted exactly as the set itself is. A revision written
    # before this column is empty and reverting to it is refused, rather than
    # restoring an empty set over every parameter in the project.
    ("param_set_revisions.values_enc",
     "ALTER TABLE param_set_revisions ADD COLUMN IF NOT EXISTS "
     "values_enc text NOT NULL DEFAULT ''"),
    # A deployment's own parameter set: the default its next version inherits.
    # NULL means "not chosen", and version creation then falls back to the base
    # version's set exactly as it always did — no backfill, nothing breaks.
    ("deployments.param_set_id",
     "ALTER TABLE deployments ADD COLUMN IF NOT EXISTS param_set_id integer"),
    ("deployments.param_set_id fk",
     "DO $$ BEGIN "
     "ALTER TABLE deployments ADD CONSTRAINT fk_deployment_param_set "
     "FOREIGN KEY (param_set_id) REFERENCES param_sets (id); "
     "EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    # Backfill from what the deployment's versions already use: every one of
    # them points at the same set today, so the deployment's answer is simply
    # the one its newest version pinned.
    ("deployments.param_set_id backfill",
     "UPDATE deployments d SET param_set_id = v.param_set_id "
     "FROM deployment_versions v "
     "WHERE v.deployment_id = d.id AND v.param_set_id IS NOT NULL "
     "AND d.param_set_id IS NULL "
     "AND v.version_no = (SELECT MAX(version_no) FROM deployment_versions x "
     "                    WHERE x.deployment_id = d.id AND x.param_set_id IS NOT NULL)"),
    ("deployment_versions.param_set_id fk",
     "DO $$ BEGIN "
     "ALTER TABLE deployment_versions ADD CONSTRAINT fk_deployment_version_param_set "
     "FOREIGN KEY (param_set_id) REFERENCES param_sets (id); "
     "EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    # Light/dark is a property of the PERSON, not of the browser they happen to
    # be at. Everyone who existed before this column follows their OS, which is
    # what the app did for everybody until now, so the default is a no-op
    # migration.
    ("users.theme",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
     "theme varchar(10) NOT NULL DEFAULT 'system'"),
    # The device-file pool (`device_files`, `device_file_versions`) is gone:
    # services/flasher/fileset_migrate.py folded it into blobs and file sets
    # (decision 0029) and dropped the tables.
    #
    # ONE-OFF, and deliberately NOT a rule. A programming run naming a batch
    # its device was not built in is NORMAL — a unit reflashed while a later
    # batch was on the bench belongs to that session's history, and that is the
    # only place the fact is recorded (user decision 2026-09-19). What happened
    # on 2026-09-17 was different: the bench had Batch 8 selected, a batch that
    # is still `planned` and has built nothing, and 31 devices were corrected to
    # Batch 7 while their 50 attempts kept the mis-selection. Repair exactly
    # those rows, pinned by batch and date. A general "align the run to its
    # device" statement would erase every legitimate reflash, on every startup.
    ("programming_runs.production_run_id 2026-09-17 misselection",
     "UPDATE programming_runs r SET production_run_id = d.production_run_id "
     "FROM device_units d WHERE d.id = r.device_unit_id "
     "AND r.production_run_id = 19 AND d.production_run_id IS NOT NULL "
     "AND r.production_run_id <> d.production_run_id "
     "AND r.started_at < '2026-09-18'"),
    # Decision 0044: closing the books on a batch. NULL everywhere means "open",
    # which is every batch that exists today, so nothing changes on deploy day —
    # the lock only starts applying once somebody closes a batch by hand.
    ("production_runs.closed_at",
     "ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS closed_at timestamptz"),
    ("production_runs.closed_by",
     "ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS "
     "closed_by varchar(100) NOT NULL DEFAULT ''"),
    ("production_runs.closed_cost_usd",
     "ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS closed_cost_usd double precision"),
    ("production_runs.closed_units",
     "ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS closed_units integer"),
    ("ix_production_runs_closed",
     "CREATE INDEX IF NOT EXISTS ix_production_runs_closed "
     "ON production_runs (closed_at) WHERE closed_at IS NOT NULL"),
    # The pointer from a correction back to what it corrects. A soft pointer on
    # purpose (no FK): deleting the original must not take the correction with
    # it, because the correction is itself a financial record.
    ("run_cost_documents.corrects_document_id",
     "ALTER TABLE run_cost_documents ADD COLUMN IF NOT EXISTS "
     "corrects_document_id integer"),
    ("ix_run_cost_doc_corrects",
     "CREATE INDEX IF NOT EXISTS ix_run_cost_doc_corrects "
     "ON run_cost_documents (corrects_document_id) "
     "WHERE corrects_document_id IS NOT NULL"),
    # Decision 0044 item 6: a charged write-off with no pinned unit cost resolved
    # against the pool average AS IT STANDS ON EVERY READ, so a 2024 attrition
    # row was priced at a 2026 average and moved again with every later purchase.
    # New rows pin the average at their own date.
    #
    # These existing rows are pinned at what they resolve to TODAY — the figure
    # every screen has been showing — rather than at the average on their own
    # date. Freezing the status quo moves no number on deploy day; re-deriving
    # them would silently restate historical batches in the very act of adding a
    # rule against restating them. `services/attrition_pin.py` does it, because
    # the value comes from a replay and not from SQL.
    #
    # Decision 0045: say STOCK outright instead of inferring it from `kind`.
    # `allocate="none"` on a line naming no run and no project meant two
    # different things — "it goes to the shared pool" when the kind happened to
    # be `part`, and "nobody has decided yet" otherwise, which the register
    # reports as `unassigned`. Every line that ALREADY resolves to the pool is
    # marked `pooled`, so the stored value says what the computed one says and
    # the two states stop sharing a spelling.
    #
    # Mirrors `line_destination` exactly, including its ORDER: a line naming a
    # run or a project is charged there, and a document naming a run charges its
    # own lines to that run — neither is stock, so neither is touched. Anything
    # this does not match keeps resolving exactly as it did, which is the point:
    # no figure moves, only the reason becomes readable.
    ("run_cost_lines.allocate pooled backfill",
     "UPDATE run_cost_lines li SET allocate = 'pooled' "
     "FROM run_cost_documents d "
     "WHERE d.id = li.document_id "
     "AND li.kind = 'part' AND li.allocate = 'none' "
     "AND li.run_id IS NULL AND li.project_id IS NULL "
     "AND d.run_id IS NULL"),
    # ---- Decision 0047: the STEP says what a position is; `kind` is dropped.
    #
    # `kind` was a second field saying the same thing more coarsely, typed beside
    # `plan_key` and free to disagree with it — it did, on 12 rows. Every rule
    # below was measured against the real table before it was written, and the
    # counts are what it matched on 2026-09-19.
    #
    # ORDER IS LOAD-BEARING. Every leaf must have a step BEFORE the column that
    # currently classifies it is dropped, and these statements read `kind` to
    # decide. That is why this is SQL here rather than Python in `startup()`:
    # this list runs as one ordered sequence, so the fill cannot be separated
    # from the drop by a later edit. Each statement is idempotent — it only
    # touches rows that still have no step.
    #
    # A HEADER is skipped throughout: it is worth zero, its children carry the
    # money, and giving it a step would enter it into the plan-vs-actual
    # comparison a second time.
    #
    # By LABEL first, because the supplier prints the same wording every time and
    # nothing else distinguishes these (5 rows and 2 rows).
    ("run_cost_lines.plan_key cancelled",
     "UPDATE run_cost_lines SET plan_key = 'other:cancelled' "
     "WHERE plan_key = '' AND voided_at IS NULL AND label ILIKE 'cancelled:%' "
     "AND NOT EXISTS (SELECT 1 FROM run_cost_lines k "
     "                WHERE k.parent_line_id = run_cost_lines.id AND k.voided_at IS NULL)"),
    ("run_cost_lines.plan_key payment fee",
     "UPDATE run_cost_lines SET plan_key = 'other:payment_fee' "
     "WHERE plan_key = '' AND voided_at IS NULL AND label ILIKE '%payment service charge%' "
     "AND NOT EXISTS (SELECT 1 FROM run_cost_lines k "
     "                WHERE k.parent_line_id = run_cost_lines.id AND k.voided_at IS NULL)"),
    # Then by what the position IS. For a part, WHERE its money goes already
    # answers which kind of stock position it is (decision 0045): excluded means
    # prepaid components already in the pool, a named batch means the assembler
    # sourced it (0041), and the rest is ordinary stock. 0 / 20 / 232 rows.
    ("run_cost_lines.plan_key parts prepaid",
     "UPDATE run_cost_lines SET plan_key = 'parts:prepaid' "
     "WHERE plan_key = '' AND voided_at IS NULL AND kind = 'part' AND allocate = 'excluded' "
     "AND NOT EXISTS (SELECT 1 FROM run_cost_lines k "
     "                WHERE k.parent_line_id = run_cost_lines.id AND k.voided_at IS NULL)"),
    ("run_cost_lines.plan_key parts supplier",
     "UPDATE run_cost_lines SET plan_key = 'pcba:parts' "
     "WHERE plan_key = '' AND voided_at IS NULL AND kind = 'part' AND run_id IS NOT NULL "
     "AND NOT EXISTS (SELECT 1 FROM run_cost_lines k "
     "                WHERE k.parent_line_id = run_cost_lines.id AND k.voided_at IS NULL)"),
    ("run_cost_lines.plan_key parts pool",
     "UPDATE run_cost_lines SET plan_key = 'parts:pool' "
     "WHERE plan_key = '' AND voided_at IS NULL AND kind = 'part' "
     "AND NOT EXISTS (SELECT 1 FROM run_cost_lines k "
     "                WHERE k.parent_line_id = run_cost_lines.id AND k.voided_at IS NULL)"),
    ("run_cost_lines.plan_key logistics",
     "UPDATE run_cost_lines SET plan_key = "
     "  CASE kind WHEN 'freight' THEN 'logistics:inbound' ELSE 'logistics:duty' END "
     "WHERE plan_key = '' AND voided_at IS NULL AND kind IN ('freight','tax') "
     "AND NOT EXISTS (SELECT 1 FROM run_cost_lines k "
     "                WHERE k.parent_line_id = run_cost_lines.id AND k.voided_at IS NULL)"),
    # RE-STEP the two keys that were standing in for two different real things.
    # JLC bills a board ASSEMBLED, one price with the bare PCB inside it; the
    # other 38 rows on `pcba:general` are assembly billed as one figure with the
    # PCB charged separately, which is different money (user decision, after
    # reading the invoices). 9 rows.
    ("run_cost_lines.plan_key populated board",
     "UPDATE run_cost_lines SET plan_key = 'pcba:populated' "
     "WHERE plan_key = 'pcba:general' AND voided_at IS NULL "
     "AND label ILIKE '%fab + assembly%'"),
    # Italtronic's one-off print set-up is tooling; it shared a key with the
    # per-unit print, which is a service. 1 row.
    ("run_cost_lines.plan_key enclosure print setup",
     "UPDATE run_cost_lines SET plan_key = 'final:enclosure_print_setup' "
     "WHERE plan_key = 'final:enclosure_print' AND voided_at IS NULL "
     "AND label ILIKE '%tooling%'"),
    # A CANCELLED line has no destination (user decision 2026-09-19): the
    # supplier printed it, nothing was delivered, and nobody pays for it. Four of
    # the five `Cancelled: <mpn>` rows were already excluded and the fifth was
    # not — which was the whole of the register's standing `unassigned_usd
    # 19.78`. A payment fee is the same shape: real money, attributable to no
    # product.
    #
    # `exclude_reason` is `varchar(40)`, and `legacy_unstated` is the deploy-day
    # lint from the decision that added the column. Naming the real reason is
    # what clears it.
    ("run_cost_lines cancelled are excluded",
     "UPDATE run_cost_lines SET allocate = 'excluded', run_id = NULL, "
     "project_id = NULL, exclude_reason = 'cancelled_by_supplier' "
     "WHERE plan_key = 'other:cancelled' AND voided_at IS NULL "
     "AND (allocate <> 'excluded' OR exclude_reason IN ('', 'legacy_unstated'))"),
    ("run_cost_lines payment fees are excluded",
     "UPDATE run_cost_lines SET allocate = 'excluded', exclude_reason = 'payment_fee' "
     "WHERE plan_key = 'other:payment_fee' AND voided_at IS NULL "
     "AND (allocate <> 'excluded' OR exclude_reason IN ('', 'legacy_unstated'))"),
    # The direct cost-item link gets its own column (decision 0047). It used to
    # be written into `plan_key`, which is now what says what a position IS —
    # linking a part line to a cost item would have replaced its step with an
    # integer and dropped it out of the pool. Measured 0 live rows in the old
    # form, so there is nothing to move; the column exists so the UI has
    # somewhere to write that is not the step.
    ("run_cost_lines.plan_item_id",
     "ALTER TABLE run_cost_lines ADD COLUMN IF NOT EXISTS plan_item_id integer"),
    ("run_cost_lines.plan_item_id backfill",
     "UPDATE run_cost_lines SET plan_item_id = plan_key::integer, plan_key = '' "
     "WHERE plan_kind = 'cost' AND plan_key ~ '^[0-9]+$'"),
    # Decision 0049: a delivery names its devices, so `shipment_lines` — which
    # existed ONLY to carry a quantity with no device behind it — is dropped.
    # The three surviving rows were replaced by the 35 serials they stood for
    # before this ran, and the table was empty. Nothing else referenced it: a
    # shipment's content is the `shipped` events pointing at it.
    ("shipment_lines drop",
     "DROP TABLE IF EXISTS shipment_lines"),
    # LAST. Everything above reads `kind`; nothing below may.
    #
    # The index on it goes first and by name: `create_all` cannot drop an index
    # the model no longer declares, and `DROP COLUMN` would take it silently —
    # dropping it explicitly is what makes the change visible on
    # `GET /api/health/schema`.
    ("ix_run_cost_line_kind drop",
     "DROP INDEX IF EXISTS ix_run_cost_line_kind"),
    ("run_cost_lines.kind drop",
     "ALTER TABLE run_cost_lines DROP COLUMN IF EXISTS kind"),
)

# name -> "ok" | "failed: ..."; served by GET /api/health/schema.
_SCHEMA_RESULTS: dict[str, str] = {}


# A one-shot statement that READS a column another statement later drops. Once
# the drop has run, it can never apply again and would report `failed` on every
# boot for ever — which is how a health page people are meant to read becomes a
# page they learn to ignore. It is SKIPPED instead, which is a state
# `GET /api/health/schema` already understands (decision 0049).
#
# Keyed by the column it needs: (table, column) -> the statements that read it.
_NEEDS_COLUMN: dict[tuple[str, str], frozenset[str]] = {
    ("run_cost_lines", "kind"): frozenset({
        "run_cost_lines.allocate pooled backfill",
        "run_cost_lines.plan_key cancelled",
        "run_cost_lines.plan_key payment fee",
        "run_cost_lines.plan_key parts prepaid",
        "run_cost_lines.plan_key parts supplier",
        "run_cost_lines.plan_key parts pool",
        "run_cost_lines.plan_key logistics",
    }),
}


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"), {"t": table, "c": column}).first())


def _ensure_phase1_schema() -> None:
    gone: set[tuple[str, str]] = set()
    with engine.begin() as conn:
        for key in _NEEDS_COLUMN:
            if not _column_exists(conn, *key):
                gone.add(key)
    for name, ddl in _PHASE1_DDL:
        if any(name in names for key, names in _NEEDS_COLUMN.items() if key in gone):
            _SCHEMA_RESULTS[name] = "skipped"
            continue
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


def _has_table(conn, name: str) -> bool:
    return bool(conn.execute(text(
        "SELECT to_regclass(:n) IS NOT NULL"), {"n": f"public.{name}"}).scalar())


def _flasher_bundle_rename(conn) -> None:
    """Renames only — MUST run BEFORE `create_all`.

    `create_all` would otherwise build empty `deployments` tables beside the
    populated `deployment_scripts` ones and strand the imported history. This
    keeps every id, so the 6,321 V2 runs stay pointed at their own version.
    """
    if not _has_table(conn, "deployment_scripts") or _has_table(conn, "deployments"):
        return
    conn.execute(text("ALTER TABLE deployment_scripts RENAME TO deployments"))
    conn.execute(text("ALTER TABLE deployment_script_versions RENAME TO deployment_versions"))
    conn.execute(text("ALTER TABLE deployment_script_files RENAME TO deployment_files"))
    conn.execute(text(
        "ALTER TABLE deployment_versions RENAME COLUMN deployment_script_id TO deployment_id"))
    conn.execute(text(
        "ALTER TABLE deployment_files "
        "RENAME COLUMN deployment_script_version_id TO deployment_version_id"))
    for table in ("programming_runs", "production_runs"):
        if conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name = :t "
            "AND column_name = 'deployment_script_version_id'"), {"t": table}).first():
            conn.execute(text(
                f"ALTER TABLE {table} RENAME COLUMN deployment_script_version_id "
                "TO deployment_version_id"))
    log.info("flasher: renamed deployment_script* -> deployment* (ids preserved)")


def _flasher_bundle_migration(conn) -> None:
    """Fold releases into the deployment versions that pinned them.

    Runs AFTER `create_all` (it writes into `deployment_images`). Idempotent:
    every step checks the shape it is about to change, so a fresh database
    skips it and a half-applied run resumes.
    """
    def has_table(name: str) -> bool:
        return _has_table(conn, name)

    def has_col(table: str, col: str) -> bool:
        return bool(conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"), {"t": table, "c": col}).first())

    if not has_table("deployments"):
        return

    # 2. New columns on the version + the deployment.
    for table, col, typ in (
        ("deployments", "chip", "varchar(30) NOT NULL DEFAULT ''"),
        ("deployment_versions", "flash_config", "jsonb"),
        ("deployment_versions", "firmware_fingerprint", "varchar(64) NOT NULL DEFAULT ''"),
        ("programming_runs", "firmware_fingerprint", "varchar(64) NOT NULL DEFAULT ''"),
        ("programming_runs", "files_fingerprint", "varchar(64) NOT NULL DEFAULT ''"),
        ("programming_runs", "draft_run", "boolean NOT NULL DEFAULT false"),
        ("production_runs", "deployment_channel", "varchar(40) NOT NULL DEFAULT ''"),
    ):
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}"))

    # 3. Fold release images into the versions that pinned them, and carry the
    #    release's flash_config along — it belongs to the images.
    if has_table("release_images") and has_col("deployment_versions", "release_version_id"):
        conn.execute(text("""
            INSERT INTO deployment_images
                (deployment_version_id, firmware_asset_id, address, position)
            SELECT v.id, i.firmware_asset_id, i.address, i.position
            FROM deployment_versions v
            JOIN release_images i ON i.release_version_id = v.release_version_id
            WHERE v.release_version_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM deployment_images d
                              WHERE d.deployment_version_id = v.id)
        """))
        conn.execute(text("""
            UPDATE deployment_versions v SET flash_config = r.flash_config
            FROM release_versions r
            WHERE r.id = v.release_version_id AND v.flash_config IS NULL
        """))
        # The chip lived on the release; it belongs to the deployment now.
        conn.execute(text("""
            UPDATE deployments d SET chip = sub.chip
            FROM (SELECT DISTINCT ON (v.deployment_id) v.deployment_id, r.chip
                  FROM deployment_versions v
                  JOIN release_versions rv ON rv.id = v.release_version_id
                  JOIN releases r ON r.id = rv.release_id
                  WHERE r.chip <> '' ORDER BY v.deployment_id, v.version_no DESC) sub
            WHERE d.id = sub.deployment_id AND d.chip = ''
        """))
        log.info("flasher: folded release images into deployment versions")

    # 4. Drop what the fold replaced. Runs keep their evidence: the version
    #    they point at now owns the images directly.
    for table, col in (("programming_runs", "release_version_id"),
                       ("deployment_versions", "release_version_id")):
        if has_col(table, col):
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
    if has_col("production_runs", "release_version_id"):
        conn.execute(text("ALTER TABLE production_runs DROP COLUMN release_version_id"))
    for table in ("release_images", "release_versions", "releases"):
        if has_table(table):
            conn.execute(text(f"DROP TABLE {table} CASCADE"))
    # An earlier revision of this block re-added `deployment_script_version_id`
    # on every startup, so a stale empty column can exist beside the renamed
    # one. The pins live in `deployment_version_id`; drop the impostor.
    for table in ("programming_runs", "production_runs"):
        if has_col(table, "deployment_script_version_id") and has_col(table, "deployment_version_id"):
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN deployment_script_version_id"))
    log.info("flasher: release tables retired")


@app.on_event("startup")
def startup() -> None:
    try:
        # Renames first: create_all must not build empty bundle tables beside
        # the populated script ones (see _flasher_bundle_rename).
        with engine.begin() as conn:
            _flasher_bundle_rename(conn)
        Base.metadata.create_all(engine)
        # Idempotent column adds on pre-existing tables (create_all only
        # creates missing tables, it never alters existing ones).
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE components ADD COLUMN IF NOT EXISTS in_library boolean NOT NULL DEFAULT true"
            ))
            # Board appearance, which lives on the project's field revision and never
            # on the stackup (see models.ProjectFieldRevision).
            conn.execute(text(
                "ALTER TABLE project_field_revisions ADD COLUMN IF NOT EXISTS "
                "mask_color varchar(32) NOT NULL DEFAULT ''"
            ))
            conn.execute(text(
                "ALTER TABLE project_field_revisions ADD COLUMN IF NOT EXISTS "
                "silk_color varchar(32) NOT NULL DEFAULT ''"
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
            # ---- Deployment bundles (2026-07-29) ---------------------------
            # The first pass of this migration lived here and touched
            # `release_versions`; the bundle pass DROPS that table, so those
            # statements then failed with UndefinedTable and — because this
            # whole block is one transaction — silently rolled back every
            # column add after them. Superseded and removed; the two functions
            # below own the flasher schema end to end.
            # ONE revision binds firmware + berryware + procedure + params, so
            # "what does a device get" has a single answer. The Release entity
            # is folded in: its images become deployment_images and its
            # identity becomes a derived fingerprint. Renames keep the 6,321
            # imported runs and their evidence intact.
            _flasher_bundle_migration(conn)
            # Can this image be written to a device at all? (placeholders cannot)
            conn.execute(text(
                "ALTER TABLE firmware_assets ADD COLUMN IF NOT EXISTS "
                "flashable boolean NOT NULL DEFAULT true"
            ))
            # A step names the functionality it proves (2026-07-30), which is
            # what turns a run's timeline into the device view's green/red grid.
            conn.execute(text(
                "ALTER TABLE programming_steps ADD COLUMN IF NOT EXISTS "
                "check_name varchar(60) NOT NULL DEFAULT ''"
            ))
            # LTE module + SIM identity captured during programming.
            for col, typ in (("imei", "varchar(20)"), ("iccid", "varchar(24)"),
                             ("imsi", "varchar(18)"), ("modem_model", "varchar(60)"),
                             ("modem_fw", "varchar(60)")):
                conn.execute(text(
                    f"ALTER TABLE device_units ADD COLUMN IF NOT EXISTS {col} {typ} NOT NULL DEFAULT ''"
                ))
            # Retro imports (V2 production reports): the old reports know only
            # the topic suffix, not the full MAC, and the batch is deliberately
            # NOT guessed — so both become nullable.
            conn.execute(text("ALTER TABLE device_units ALTER COLUMN mac DROP NOT NULL"))
            conn.execute(text(
                "ALTER TABLE programming_runs ALTER COLUMN production_run_id DROP NOT NULL"
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
            # Composed simulation models (2026-08-29): a symbol's wrapper
            # subcircuit is built from library blocks instead of typed out, so
            # the link stores the block design and DERIVES the pin map. Every
            # pre-existing link is `model` mode with a NULL composition, which
            # is exactly what the default gives them.
            conn.execute(text(
                "ALTER TABLE symbol_sim_links ADD COLUMN IF NOT EXISTS "
                "mode varchar(20) NOT NULL DEFAULT 'model'"
            ))
            conn.execute(text(
                "ALTER TABLE symbol_sim_links ADD COLUMN IF NOT EXISTS composition jsonb"
            ))
            # Usage-fitness lifecycle (in_design | released | deprecated |
            # obsolete) — see models.Component.lifecycle_state.
            conn.execute(text(
                "ALTER TABLE components ADD COLUMN IF NOT EXISTS "
                "lifecycle_state varchar(20) NOT NULL DEFAULT 'in_design'"
            ))
            # The "7S Version" field as committed in the schematic (which
            # component version the board was drawn with).
            conn.execute(text(
                "ALTER TABLE snapshot_bom_lines ADD COLUMN IF NOT EXISTS "
                "lib_version varchar(60) NOT NULL DEFAULT ''"
            ))
            # The judgment items TODAY's checklist expects, cached beside the
            # machine answers so a LIST row measures completeness against the
            # same checklist the card does. NULL is "not computed yet" and the
            # caller falls back to the record's own snapshot; the startup
            # warm-up fills it.
            conn.execute(text(
                "ALTER TABLE conformance ADD COLUMN IF NOT EXISTS judgment jsonb"
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
    except Exception as e:  # noqa: BLE001 — startup must not die on migrations
        # This block is ONE transaction, so a single failing statement rolls
        # back every statement after it. Silently passing made a column add
        # vanish with no trace (2026-07-29) — always say which statement failed.
        log.warning(f"startup schema block did not complete: {type(e).__name__}: {e}")
    _ensure_phase1_schema()
    _ensure_dedup_indexes()
    # Datasheet bytes into the content-addressed `documents` table. Must run
    # AFTER create_all (which builds the empty table) and after the phase-1
    # DDL (the pages' generated tsv column). Idempotent — see the module.
    from .services.datasheet_migrate import migrate_to_documents

    migrate_to_documents(engine)
    # Decision 0010: one token per ACCOUNT, not one per project. Needs the
    # `git_credentials` table (create_all) and `projects.git_credential_id`
    # (phase-1 DDL), so it runs after both. Idempotent — see the module.
    try:
        from .db import SessionLocal as _Session
        from .services.git_credential_migrate import migrate as _fold_git_tokens

        _db = _Session()
        try:
            _fold_git_tokens(_db)
        finally:
            _db.close()
    except Exception as e:  # noqa: BLE001 — never block startup on a migration
        log.warning(f"git credential fold did not run: {type(e).__name__}: {e}")
    # Drop the surrogate key on `programming_logs` and rewrite the table. Runs
    # here, at startup, because the rewrite holds an ACCESS EXCLUSIVE lock and
    # must not sit under a request or under a live flasher run. Idempotent —
    # see the module.
    from .services.proglog_migrate import migrate as migrate_proglog_pk

    migrate_proglog_pk(engine)
    # Decision 0044: a charged write-off with no pinned unit cost was re-priced
    # by every later purchase. Freeze the ones that exist at today's figure.
    # Needs a full pool replay, so it is Python and not SQL. Idempotent — it
    # only ever looks at rows that are still NULL.
    try:
        from .db import SessionLocal as _PinSession
        from .services.attrition_pin import migrate as _pin_attrition

        _pdb = _PinSession()
        try:
            _pin_attrition(_pdb)
        finally:
            _pdb.close()
    except Exception as e:  # noqa: BLE001 — never block startup on a migration
        log.warning(f"attrition pin did not run: {type(e).__name__}: {e}")
    # The per-file version pool becomes blobs + file sets (decision 0029).
    # Runs after create_all built the three new tables; one transaction,
    # checked before the old tables are dropped, reported on /health/schema.
    from .services.flasher.fileset_migrate import migrate as migrate_file_sets
    migrate_file_sets(engine)
    try:
        from .db import SessionLocal
        from .services import appconfig

        db = SessionLocal()
        try:
            n = appconfig.apply_overrides(db)
            if n:
                print(f"appconfig: applied {n} stored setting override(s)")
        finally:
            db.close()
    except Exception:
        # A settings table that is not there yet must never stop startup.
        pass
    # The first admin, from ADMIN_USERNAME / ADMIN_PASSWORD, and ONLY when the
    # users table is empty. A deployment with auth on and no users can never be
    # signed into, so this must run — but it must also never be able to reset a
    # live account, which is why `bootstrap_admin` refuses once one exists.
    try:
        from .db import SessionLocal
        from .services import auth as auth_service

        db = SessionLocal()
        try:
            message = auth_service.bootstrap_admin(db)
            if message and message.startswith("auth: created"):
                log.info(message)
            elif message:
                # "nobody can sign in" is the one startup line an operator must
                # not scroll past — it means the deployment is locked out.
                log.warning(message)
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001 — never block startup
        log.warning(f"auth bootstrap did not run: {type(e).__name__}: {e}")
    # Objects the platform has stopped writing, removed once on the first start
    # after the deploy that stopped writing them. Object storage has no
    # invalidation path for something nobody asks for any more, so the deploy
    # that ends a write is the deploy that has to clean up after it. In the
    # background and behind a marker object each: on a big bucket the listing
    # is the slow part, and a deploy must not wait for it. Separate markers, so
    # one purge failing never blocks or re-runs the other.
    try:
        import threading

        from .services import storage

        def _purge(marker: str, fn, what: str) -> None:
            """`fn` returns (how many went, whether the job is finished).

            The marker is written only when the job IS finished. A purge that
            deliberately kept something — an archive with no mirror to rebuild
            it from — must be able to try again after the mirror is fetched,
            and a marker written too early would retire it forever.
            """
            try:
                if storage.exists(marker):
                    return
                gone, complete = fn()
                if complete:
                    storage.put_bytes(marker, b"", "text/plain")
                if gone:
                    log.info(f"storage: dropped {gone} {what}")
            except Exception as e:  # noqa: BLE001 — a purge must never block startup
                log.warning(f"{what} purge did not run: {type(e).__name__}: {e}")

        def _storage_purges() -> None:
            _purge("maintenance/schematic-renders-dropped.v1",
                   lambda: (storage.drop_schematic_renders(), True),
                   "cached schematic render object(s)")
            # Decision 0009: the git mirror IS the source archive. The stored
            # per-snapshot tarballs were a second copy that nothing read —
            # except where the mirror is missing, which the purge checks per
            # archive rather than assuming.
            _purge("maintenance/snapshot-archives-dropped.v1",
                   storage.drop_snapshot_archives,
                   "stored snapshot source archive(s)")

        threading.Thread(target=_storage_purges, daemon=True).start()
    except Exception as e:  # noqa: BLE001 — never block startup
        log.warning(f"storage purges did not start: {type(e).__name__}: {e}")
    # Fill `material_sha` on geometry versions published before the sign-off
    # feature existed. Runs in the background: an empty fingerprint blocks a
    # carry rather than granting one, so nothing is wrong while it works.
    try:
        from .services.signoff import start_material_backfill

        start_material_backfill()
    except Exception as e:  # noqa: BLE001 — a derived cache must never block startup
        log.warning(f"material backfill did not start: {type(e).__name__}: {e}")
    # Seed the review checklists on first start (idempotent — only kinds with
    # no base checklist yet get one).
    try:
        from .db import SessionLocal
        from .services.checklists import (
            migrate_rules_onto_items,
            migrate_severities,
            seed_checklists,
        )

        db = SessionLocal()
        try:
            seeded = seed_checklists(db)
            if seeded:
                log.info(f"checklists: seeded {seeded}")
            # Validation rules used to be JSON blocks in a `rules` table, and
            # the 15 per-category rows there were never read by anything. They
            # are now `params` on the check that uses them. Idempotent.
            moved = migrate_rules_onto_items(db)
            if moved["published"]:
                log.info(f"checklists: rules moved onto the items — {moved['published']}")
            if moved["unused"]:
                log.info(f"checklists: rule keys no check consumes — {moved['unused']}")
            # `disabled: true` -> `severity`. Idempotent; see the docstring for
            # why the four seeded-off checks become warnings rather than ignore.
            sev = migrate_severities(db)
            if sev:
                log.info(f"checklists: severities set — {sev}")
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001 — never block startup
        log.warning(f"checklist seed did not run: {type(e).__name__}: {e}")
    # Conformance is computed on read and cached against a digest of its
    # inputs. Warming it in the background is what keeps list surfaces fast on a
    # cold database; nothing depends on it finishing (decision 0017).
    try:
        import threading

        from .db import SessionLocal as _SL
        from .services.conformance import warm_all

        def _warm() -> None:
            db = _SL()
            try:
                log.info(f"conformance: warmed {warm_all(db)}")
            except Exception as e:  # noqa: BLE001 — never block startup
                log.warning(f"conformance warm-up did not finish: {type(e).__name__}: {e}")
            finally:
                db.close()

        threading.Thread(target=_warm, name="conformance-warm", daemon=True).start()
    except Exception as e:  # noqa: BLE001
        log.warning(f"conformance warm-up did not start: {type(e).__name__}: {e}")

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

    # Read-only subscriber on the fleet's MQTT broker, keeping
    # `device_presence` current. It subscribes to four LEAF topics and never
    # publishes — the traffic budget and the reasoning are in
    # services/mqtt_monitor.py and docs/reference/mqtt-presence.md.
    #
    # Unconditional here, because the switch is NOT an environment variable:
    # `start()` reads the admin-owned `mqtt_config` row and returns False when
    # the monitor is disabled or unconfigured, which is the normal case.
    try:
        from .db import SessionLocal
        from .services.mqtt_monitor import link_devices, start as start_mqtt

        db = SessionLocal()
        try:
            link_devices(db)
            start_mqtt(db)
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001 — a broker outage never blocks startup
        log.warning(f"MQTT monitor did not start: {type(e).__name__}: {e}")

    # Tag documents archived before the classifier existed as searchable or
    # scanned. Unconditional and self-limiting: it only touches rows with
    # text_layer = '', so on every boot after the first sweep it finds nothing
    # and exits. Delayed, because it competes with the startup fetch for I/O.
    try:
        import threading as _t

        from .services.datasheet_store import start_text_layer_classify

        _t.Timer(30.0, lambda: start_text_layer_classify("missing")).start()
    except Exception as e:  # noqa: BLE001 — a cosmetic tag must never block startup
        log.warning(f"could not arm the datasheet text-layer backfill: {e}")

    # Extract per-page text for every document stored before the page index
    # existed. Self-limiting in the same way: "missing" only claims versions
    # with pages_indexed_at IS NULL, so every boot after the backfill finds
    # nothing. Measured cost of the first full run on ~9400 pages is about 40
    # minutes of background CPU, hence the long delay — it must not compete
    # with the fetch and classify sweeps, which are the ones it reads from.
    if settings.datasheet_page_index_on_startup:
        try:
            import threading as _t2

            from .services.datasheet_pages import start_index

            _t2.Timer(120.0, lambda: start_index("missing")).start()
        except Exception as e:  # noqa: BLE001 — a derived cache must never block startup
            log.warning(f"could not arm the datasheet page-index backfill: {e}")
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
    from .services.datasheet_migrate import RESULT as _DOC_MIGRATION
    from .services.proglog_migrate import RESULT as _PROGLOG_MIGRATION
    from .services.flasher.fileset_migrate import RESULT as _FILESET_MIGRATION

    _SCHEMA_RESULTS.update(_DOC_MIGRATION)
    _SCHEMA_RESULTS.update(_PROGLOG_MIGRATION)
    _SCHEMA_RESULTS.update(_FILESET_MIGRATION)
    failed = {k: v for k, v in _SCHEMA_RESULTS.items() if v not in ("ok", "skipped")}
    return {
        "ok": not failed,
        "statements": _SCHEMA_RESULTS,
        "failed": failed,
        "note": ("every statement applied" if not failed else
                 "SOME STATEMENTS DID NOT APPLY — features depending on these "
                 "columns will misbehave until they do"),
    }
