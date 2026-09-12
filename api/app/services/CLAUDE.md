# Services (`api/app/services`)

Business logic and everything with a side effect. A router parses a request and
calls into here. Read `api/CLAUDE.md` first for the reuse table and the backend
conventions.

## Where each topic is written down

This directory is flat and holds about 70 modules. The rules for one topic live
in one document. Open the document before you change the module.

| Topic | Modules | Document |
|---|---|---|
| Datasheet identity, fetch, classification, page index | `datasheet_store.py`, `datasheet_pages.py`, `datasheet_migrate.py` | [docs/reference/datasheets.md](../../../docs/reference/datasheets.md) |
| Cost plans, invoices, stock, orders, sales | `cost_state.py`, `material.py`, `stock.py`, `orders.py` | [docs/reference/production-economics.md](../../../docs/reference/production-economics.md) |
| Sign-off, verification, the review record | `signoff.py`, `review.py`, `material.py` | [docs/reference/review-axis.md](../../../docs/reference/review-axis.md) |
| Projects, git mirrors, snapshots, exports | `gitrepo.py`, `project_ops.py`, `git_credential_migrate.py` | [docs/reference/projects-module.md](../../../docs/reference/projects-module.md) |
| Simulation models and composition | `simmodel.py`, `sim_store.py`, `simcompose.py` | [docs/reference/simulation-models.md](../../../docs/reference/simulation-models.md) |
| SPICE runs, netlists, harnesses, the live sketch | `sim_spice.py`, `project_ops.py`, `sch_lib.py`, `sim_scenario.py` | [docs/reference/spice-runs.md](../../../docs/reference/spice-runs.md) |
| The agent tool surface | `jaravis.py` | [docs/reference/jaravis.md](../../../docs/reference/jaravis.md) |
| PCM package retention and the personal repository | `pcm.py` | [docs/reference/pcm-packaging.md](../../../docs/reference/pcm-packaging.md) |
| The HTTP catalog and KiCad field visibility | `generator.py`, `mirror.py` | [docs/reference/kicad-integration.md](../../../docs/reference/kicad-integration.md) |
| The 2D field solver | `fieldsolver/` | `fieldsolver/CLAUDE.md` |
| Production programming | `flasher/` | `flasher/CLAUDE.md` |
| The KiCad sync plugin this packages | `pcm_plugin/` | `pcm_plugin/CLAUDE.md` |

## The versioning + publish model (core invariant)

Read this before touching components, symbols, footprints, or skills.

**AUTO-PUBLISH, EVERYWHERE.** Components, symbols and footprints since
2026-08-23; **skills since 2026-08-24**, which removed the last draft gate in
the platform. What replaced the gate is the **review axis**
(`services/review.py`, [docs/reference/review-axis.md](../../../docs/reference/review-axis.md)):
every publish records a machine
validation, and verification/sign-off happen afterwards, asynchronously. All
publish doors go through `services/publish.py` —
`publish_component_version` / `publish_geometry_version` /
`publish_skill_version` — which own the datasheet pins, the sign-off carry,
the review-record carry and the machine check. A new publish path that
bypasses them silently loses all four. Mirror refreshes are the
`refresh_mirror_for_*` twins, AFTER the commit.

**Nothing files drafts any more, and there is nowhere to approve one.**
`routers/proposals.py` is DELETED, with the Proposals view, the nav badge and
`RecheckDialog`; `/proposals` redirects to `/reviews`. `POST
/api/import/sync` (the retired YAML diff, the one remaining draft producer)
answers **410** rather than writing rows nothing can act on — the destructive
full import still works, because it writes published rows. Draft and rejected
version rows from before all this stay readable as history: never write a new
one, and never re-introduce an approval queue without reading the review-axis
section first.

- **Immutable version rows.** `ComponentVersion`, `SymbolVersion`,
  `FootprintVersion`, `SkillVersion` are append-only. You never mutate a live
  version in place — you create a new one.
- **`current_version_id`** on the parent (`Component`, `Symbol`, …) is a plain
  `Integer` (deliberately **not** a FK) pointing at the live version. `None`
  means "no published version yet" — now only a leftover from the draft era (a
  creation that was filed and never approved). `current_version(comp)` resolves it.
- **`status` is a `String(20)`**, default `"published"`. Live values:
  - `"published"` — the only status anything writes now.
  - `"draft"` / `"rejected"` — HISTORY. Nothing produces either; both stay
    readable, and the UI labels them as never-published.
  There is **no `"approved"` status**; `approved_by` records who published when
  a person did it through a UI save.
- **`services/publish.py` is the single choke point**: it sets
  `status="published"`, moves `current_version_id`, pins datasheets, carries
  the sign-off and the review record, and runs the machine validation. Call it
  — never hand-roll a publish, and never move `current_version_id` yourself.
- **Prices and datasheets are NOT properties.** They live in `component_prices`
  and `datasheets` (component-scoped, auto-managed). Keep them out of
  `ComponentProperty`; the price keys (`PRICE_KEY_TO_COL`) and `Datasheet*` keys
  are stripped on import and rejected by Jaravis's `_parse_properties`.
  **Prices are never emitted to KiCad** (user decision 2026-07): neither the
  generated mirror symbols nor the HTTP catalog carry `Price *` fields —
  `injected_props(datasheets)` injects datasheet links only. Pricing lives on
  the platform (BOMs, ladders, run economics).

## Creating a version (the one true pattern)

Mirror `services/jaravis.py`. New component: `Component(name=…)` with
`current_version_id` left `None`; `ComponentVersion(version_no=1,
created_by=<actor>, comment=…)`; `ComponentProperty` rows with `position`; then
**`publish.publish_component_version(db, comp, cv, actor=…)`** and, after the
commit, `refresh_mirror_for_component`. Edit: same, but `version_no =
max(existing)+1` and carry `removed_properties` forward. Geometry: build the
version row and call `publish_geometry_version` + `refresh_mirror_for_geometry`
— or better, go through `services/geometry_proposals.py`, which owns the
parsing, the model-path rules and the repoint. Skills:
`publish.publish_skill_version`.

Never set `status` or move `current_version_id` by hand: those two lines are
what the publish functions exist to own, and a path that writes them itself
skips the datasheet pins, the sign-off carry, the review carry and the machine
validation. Audit actions in use: `publish`, `review.check`, `review.revoke`,
`signoff.*`, `import`. (`proposal.create` / `proposal.approve` /
`proposal.reject` appear in history only.)


## Importing from YAML — two modes

`services/importer.py` runs as a background daemon thread (`IMPORT_STATE` +
`threading.Lock`; progress via `_stage(name)`; status polled at
`GET /api/import/status`). There are **two** ways to load `Sources/*.yaml`:

1. **Full import (`run_import`, `POST /api/import`)** — DESTRUCTIVE: wipes and
   reloads everything (categories, rules, base symbols, footprints, 3D models,
   components) writing rows directly as `published`. Skills and component notes
   survive. Use for first-time load / clean cutover / refreshing geometry.
   **Do not casually edit or "test" this — it drops the DB and cannot be run
   safely against real data.**
2. **Sync (`run_sync`, `POST /api/import/sync`)** — NON-DESTRUCTIVE: diffs each
   YAML component against the DB and creates **draft proposals** for new and
   changed components (reusing the proposal pattern in
   [docs/reference/jaravis.md](../../../docs/reference/jaravis.md)). It never wipes,
   never deletes, and touches nothing but the drafts it creates + audit rows.
   Scope and guarantees:
   - Diffs on versioned component data only: `base_component`, footprint
     **name**, `category_id`, `removed_properties`, and the ordered plain
     properties `(key, value, is_null)`. Prices, datasheets, and property
     visibility/layout are intentionally **not** part of the diff.
   - Resolves base symbols, footprints, and categories from what is **already
     in the DB**. A component that references a base symbol / footprint /
     category not present is **skipped and reported**, never invented — run a
     full import first to add geometry.
   - **Idempotent**: components equal to their live version are `unchanged`; if
     a matching draft already exists it is not duplicated. Re-running a sync
     over unchanged YAML must create zero proposals.
   - Components in the DB but absent from YAML are **reported** (`only_in_db`),
     never auto-deleted.

`_build_desired(...)` builds one component's desired state and mirrors
`run_import`'s per-component logic; if you change how a component is built from
YAML, keep both paths consistent.


## The change feed (`services/changes.py`, `routers/changes.py`)

"What moved in the library lately, and who moved it" — one time-ordered stream
over six sources: component, symbol, footprint and skill versions, 3D model
uploads, and the lifecycle/review lane of the audit log.

- **The list is cheap; the diff is not.** A feed row carries only what one
  printed line needs. Every diff — the property table, the before/after
  renders, the text diff — is a SECOND call to `GET /api/changes/{kind}/{id}`,
  made when a row is expanded. There are ~18k events in this database and
  rendering a symbol costs a kicad-cli invocation, so a feed that computed
  diffs eagerly is not a slower feed, it is an unusable one.
- **Pagination is KEYSET, never offset.** The cursor is the last row's
  `(ts, src, row_id)` triple, which is exactly the sort key. The feed is
  append-mostly and is read while new versions land, so `OFFSET 100` silently
  repeats rows. An unparseable cursor means "start at the top", never a 500.
- **`EVENT_PREFIXES` deliberately excludes `publish` / `proposal.*`.** Those
  audit rows describe the very version rows the other five lanes already
  report, and report them WITH a diff. Including both doubles every publish.
- **3D models join the audit log for their actor.** `models3d` has no
  `created_by`; the uploader is only in the `model3d.create` row. The ~4.7k
  rows the retired YAML import created legitimately have nobody and read as
  "import". Never select `Model3D.data` in the feed — it is a `LargeBinary`
  and would drag every mesh through Postgres to print a filename.


## The mirror refresh

- **The mirror refresh is incrementally cached — keep the guards.**
  `update_mirror_symbols` runs after *every* approval, so `services/mirror.py`
  memoises the two parts that almost never change. (1) `write_manifest` keys
  SHA-256 digests on `(mtime_ns, size)` in `_MANIFEST_HASHES`: the tree carries
  ~1.4 GB of 3D models that a property edit cannot touch, and re-hashing them
  cost ~1.3s per approval. (2) `write_symbol_libs` rebuilds
  `7Sigma_Base.kicad_sym` only when `_base_symbol_fingerprint(db)` (every
  `Symbol.current_version_id`) moves or the file is missing — it ignored
  `only_tops` and re-parsed all ~140 base symbols every time, ~0.7s. Both
  caches are **in-process and advisory**: each is validated against real
  filesystem/DB state on every call, so a restart or a `rebuild_mirror` wipe
  costs one full rebuild and never a stale artifact. If you add a mirror
  artifact with its own rebuild cost, follow the same shape — cache keyed on
  observable state, never on "we think nothing changed". The manifest's JSON
  format is public (PCM builder, sync clients); don't add cache fields to it.
- **`db.expire_all()` before any post-commit mirror refresh.** The session uses
  `expire_on_commit=False`, and services create new versions via `db.add()`
  without appending to already-loaded relationships — so after calling a
  service that commits (e.g. `add_component_file`), a preloaded `comp.versions`
  is stale and `current_version(comp)` returns None, silently skipping
  `update_mirror_symbols`. Precedents: `create_version`, `proposals.approve`,
  `components.add_file`.
