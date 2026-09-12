# KiCad integration — installing the library and serving the catalog

Rules that bind the platform to what KiCad itself does: how the library
reaches a user's KiCad, and what the backend must not do to the catalog.

## Getting the library into KiCad

Full reasoning in [docs/decisions/0006](../decisions/0006-sync-button-owns-library-updates.md).

- **The Plugin and Content Manager installs once and updates only the plugin.**
  It installs the base symbols and footprints, the 3D models and the Sync
  plugin from the user's personal repository URL. After that, library updates
  come from the **Sync 7Sigma Library** button, which KiCad 10 shows in the PCB
  editor. A sync records the two content packages in the PCM as current and
  pinned, so the PCM offers no library update and Update All skips them. The
  plugin cannot update itself, so its own PCM entry is left alone.
- **KiCad re-reads a changed library on its next use, no restart.** The
  footprint, symbol and 3D caches check file modification times (verified in
  the 10.0 source). Parts already placed are copies: Tools → Update Footprints
  / Symbols from Library. A restart is needed only after the plugin edits a
  library table.
- **The HTTP catalog refreshes itself every 2 minutes, and nothing can force
  it.** KiCad 10 re-fetches in a background thread every `max` of the two
  timeouts in the `.kicad_httplib`; both are 120 s since 2026-09-10 and are
  baked into the downloaded file, so a change means a re-download. One refresh
  is about 44 kB on the wire.

## The catalog and field visibility, in the backend

- **The KiCad HTTP catalog is on the symbol chooser's critical path — never
  load the whole library per request.** `EnumerateSymbolLib` walks every
  category and calls `parts/category/{id}.json` once each, so one slow handler
  is multiplied by the category count. Both part endpoints therefore go through
  `kicad_http.library_versions(db)`, which expresses `current_version(comp)` +
  `in_library` as a SQL filter (`ComponentVersion.id == Component.current_version_id`)
  instead of loading every component with every version and filtering in Python
  — that cost ~0.3s per category, ~4s per chooser open on 327 components.
  Two traps it also closes: `props_dict` reads `Footprint_Name` through
  `cv.footprint_version`, which lazy-loads a whole `.kicad_mod` body per
  component unless `source_text`/`parsed`/`models` are deferred; and the
  `Component` join needs `contains_eager` or the parent row is re-fetched per
  row. Verified 2026-07-30: 4.14s -> 0.38s wall clock for 15 categories,
  payloads byte-identical.
- **KiCad 10 refreshes the HTTP catalog in a background thread, and nothing
  else refreshes it.** `source.timeout_categories_seconds` and
  `source.timeout_parts_seconds` live in the `.kicad_httplib`; KiCad 10 fills
  its copy once, then `backgroundRefreshWorker` (`sch_io_http_lib.cpp`) sleeps
  `max(categories, parts)` seconds between full re-fetches, so the two values
  act as ONE interval and a low value no longer slows an "Add Symbol" click
  (in KiCad 9 the category timeout expired every part list at once, on the
  click). There is no menu action, no IPC API command and no plugin hook that
  forces a refresh — verified in the 10.0 source 2026-09-10 — the only manual
  way is a real edit to the global symbol library table (Manage Symbol
  Libraries → change the row's description → OK), which clears and reloads
  every symbol library. `routers/kicad_sync.py::httplib_file` emits both from
  `httplib_timeout_categories_s` / `httplib_timeout_parts_s` (120 / 120 since
  2026-09-10, editable in Settings). One refresh is 17 requests, ~44 kB gzip on
  the wire (16 categories, 439 parts). The copy is per KiCad session and cold
  on startup, so the server-side cost still matters. **The values are baked
  into the downloaded file** — changing the knob needs a re-download, exactly
  like `httplib_token`.
- **KiCad field visibility is curated ON THE BASE SYMBOL — never per
  component** (user decision 2026-08-04). The component only holds values; a
  key the base symbol draws visible (R's Value, C's Voltage/Dielectric, LED's
  Color) is visible on every component using it, any other key is hidden, and
  the dormant per-row `layout` effects are the only override. That is the rule
  `apply_properties` bakes into the mirror symbols, and the HTTP catalog must
  emit the SAME answer — `generator.schematic_field_visibility` (cached per
  base-symbol version id) is the one implementation; never consult
  `ComponentProperty.hide`, which the generator has never read and which is
  True on almost every imported row. Both wrong answers shipped once: forcing
  Value visible showed it on every testpoint; obeying the `hide` column hid it
  on every resistor. The column stays only as a dormant import artifact, and
  the web editor no longer shows it. To make a category display a parameter,
  edit the base symbol's property effects — one symbol proposal.
