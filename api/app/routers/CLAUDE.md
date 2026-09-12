# Routers (`api/app/routers`)

One `APIRouter(prefix="/api/…")` per file. A router parses the request, calls a
service or a helper, and shapes the response. Non-trivial logic and anything
with a side effect belongs in `../services/`.

Read `api/CLAUDE.md` for the reuse table. `util.py` in this directory holds the
shared helpers, and you reuse them rather than write a second one.

## Never hand-write a per-tool agent route

`agent.py` dispatches `services/jaravis.py::TOOLS` by name. Add a tool there and
the HTTP surface and the MCP server both get it. See
[mcp/CLAUDE.md](../../../mcp/CLAUDE.md).

## `GET /api/{kind}/{id}/versions/{n}/preview.svg` SELECTS; `?v=` does not

Two preview endpoints per template, and the difference is load-bearing.
`/{kind}/{id}/preview.svg?v=` always renders the CURRENT drawing (`v` is a
cache key — see `_preview`). The version-addressed route renders THAT version,
which is what a before/after pane needs and what "history lives under
`/versions/...`" already promised. Version rows are immutable, so unlike
`_preview` it can always answer `immutable`. `preview.glb` follows the same
pair, so a footprint template page can show the 3D board view that previously
hung only off a component version.

## List surfaces — the two traps that cost a second each

Both were measured on 2026-08-24 against production data (421 components, 2296
version rows, 23509 property rows).

- **`routers/util.components_with_current(db)` is the list loader.**
  `selectinload(Component.versions).selectinload(ComponentVersion.properties)`
  is the obvious way to load a list and the wrong one: it pulls the entire
  HISTORY to print one version each. It also eager-loads `footprint_version`
  with `source_text`/`parsed`/`models` DEFERRED, because `props_dict` reads
  `Footprint_Name` through that relationship and otherwise lazy-loads a whole
  `.kicad_mod` per component — the same trap `kicad_http.library_versions`
  documents. Callers MUST use the returned `{component_id: version}` map:
  `current_version(comp)` reads `comp.versions`, which is unloaded here and
  would lazy-load the history back one component at a time. Pass the map to
  `review.states_for_components(..., cvs=live)` for the same reason.
  `GET /api/components` 1.22s -> 0.21s; `/api/reviews/queue` 1.36s -> 0.22s.
- **The identity map holds WEAK references.** `db.get(ChecklistVersion, id)`
  looked free — the repeat should come from the identity map — but
  `_checklist_items_of` keeps no reference to the object, so it is collected
  and every one of the 857 pre-snapshot review records re-queried. 299 of the
  review queue's 318 SQL round trips were the same three rows. Checklist
  VERSIONS are immutable, so `review._CHECKLIST_ITEMS` memoises them for the
  life of the process. Any other hot `db.get` on an immutable row is suspect
  for the same reason.
- **`GET /api/flasher/devices` pages in SQL** — 5502 rows are 1.98 MB and 2.5s,
  which no rendering trick improves. It returns `{items, total, offset, limit,
  has_more}`, and its filtering and sorting are SERVER-side (`_DEVICE_SORTS`,
  `_DEVICE_FILTERS`, both allow-lists because the column name arrives in a
  query string): a client holding one page cannot honestly answer "no rows
  match". 2.50s / 1.98 MB -> 0.11s / 38 kB.
- **`POST /api/components/{id}/versions` records the real actor.** It hardcoded
  `created_by="user"` (and `actor`/`approved_by`), so every component edit made
  in the browser was anonymous in its own history and in the change feed, while
  symbol and footprint publishes had always passed the signed-in name. Rows
  written before 2026-08-25 keep saying "user"; that history is not
  recoverable.

