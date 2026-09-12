# Datasheets — identity, fetch ladder, storage and the page index

## Three rules that are expensive to get wrong

- **A new version means the TEXT changed, never the bytes.** Vendors re-sign
  and re-generate PDFs constantly — Texas Instruments does it about every two
  days — so a byte comparison called a fresh download a new revision. One
  TPS61023 datasheet reached 37 stored copies of a single Rev. B that way, and
  every one of them bumped the component and dropped its verification. The
  identity is a hash of the page text with a role per page.
- **A real revision is a review event.** The bump goes through the shared
  publish path: the sign-off carries because the part did not change, the
  review record does not because the document it was checked against did, and
  a review request opens naming the pages that moved.
- **A file is stored once and shared.** Bytes live in `documents`, addressed by
  sha256; a datasheet version points at one. Three variants of a part that link
  the same PDF hold one copy and one page index between them.

Deleting a stored file does not free the disk until the table is rewritten, so
the clean-up endpoints end in a `VACUUM FULL`.

Backend rules. The service is `api/app/services/datasheet_store.py`, with
`datasheet_pages.py` for the page index and `datasheet_migrate.py` for the
one-time move to shared documents. Decision
[0004](../decisions/0004-datasheet-identity-and-storage.md) holds the reasoning.

The short version is in the root `CLAUDE.md`. This page holds the rules you need
before you change a fetch, a hash, a classification or an endpoint.

- **The injected datasheet link prefers the LOCAL copy.** `injected_props`
  emits `{public_base_url}/api/datasheets/{id}/file` whenever the current
  `DatasheetVersion` is a real PDF (content-type or `.pdf` filename), or is an
  uploaded file with no `source_url` at all; otherwise it falls back to the
  internet URL. Stored HTML product pages (LCSC etc.) deliberately keep the
  live link — a saved product page is worse than the real one. Applies to both
  emission paths (generated mirror symbols and the KiCad HTTP catalog), so
  `public_base_url` must be the API address as KiCad clients see it, not
  `localhost`, on any non-local deployment.
- **A new component archives its datasheet AT PUBLISH TIME, before the version
  lands.** `jaravis.propose_new_component` adds the `Datasheet` row, flushes,
  then calls `_archive_datasheet` (a best-effort wrapper on `fetch_datasheet`)
  BEFORE `_publish_component`. Order matters both ways: `pin_datasheets` then
  records which PDF version this component version used, and the
  `cmp.datasheet_text` machine item sees a real document instead of answering
  `na — no archived PDF`, which reads as "question does not apply" rather than
  "the file is missing". Before 2026-08-27 the row held only a URL and the PDF
  was fetched lazily on the first `read_datasheet`, so every freshly published
  part was invisible to `search_datasheets`.

  Two things to keep in mind if you touch this. `fetch_datasheet` **commits**,
  so the draft `ComponentVersion` is persisted before the publish — harmless
  only because every row it needs is already built by then. And the wrapper
  never raises: a supplier that is down must not cost the caller a component
  write. It returns `{"archived": ..., "text_layer": ...}` into the tool's
  response, and `text_layer` is the field that matters — an HTML page is
  **stored, not refused**, as `archived: true` with `text_layer: "none"`.
- **Datasheets are re-checked nightly** (`datasheet_store.start_nightly_recheck`,
  armed from `main.py` startup at `settings.datasheet_recheck_hour`, server
  local time — containers are UTC unless `TZ` is set). It runs the existing
  `start_fetch_all("all")` worker, so a changed document flows through the
  normal path: new `DatasheetVersion` → auto-bumped component version → mirror
  rebuild. The re-check is cheap because `fetch_datasheet(..., conditional=True)`
  replays the stored `etag` / `last_modified` (columns added by startup
  migration, learned on any fetch) as `If-None-Match` / `If-Modified-Since`;
  an unchanged document costs one 304 with no body. A 304 NEVER falls through
  to the store path. Manual re-fetch (`POST /api/datasheets/{id}/fetch`)
  deliberately passes `conditional=False` — a supplier can swap file content
  without touching its validators, and clicking re-fetch means "actually look".
- **Bytes are stored once, in `documents`, and versions point at them**
  (2026-09-10, [decision 0004](../decisions/0004-datasheet-identity-and-storage.md)).
  `DatasheetVersion` is a history entry — `datasheet_id`, `version_no`,
  `filename`, `fetched_at`, the HTTP validators — plus `document_id`. Every
  column that describes the bytes (`sha256`, `size_bytes`, `content_type`,
  `data`, `text_layer`, `page_count`, `text_pages`, `pages_indexed_at`) lives
  on `Document`, and `DatasheetVersion` proxies them as read-only properties
  for the readers that predate the split. Two versions of two components that
  fetched the same PDF share one document; `datasheet_pages` is keyed on the
  document, so a shared file is indexed once. `Document.data` is a deferred
  column — load the document row freely, the PDF comes only when `.data` is
  read. `services/datasheet_migrate.py` did the move at startup (SQL only,
  server-side, then `VACUUM FULL`) and keys off the presence of
  `datasheet_versions.data`, so it is a no-op on every later boot. Never
  re-add the old columns to `datasheet_versions` in `_PHASE1_DDL`.
- **A new version means the TEXT changed, not the bytes.** TI re-signs every
  PDF about every two days (new `ModDate`, new sha, same document) and
  generates the package addendum at download time (date stamp in the header,
  live tape-and-reel tables, package sections in a different order). Under
  the old byte rule one TPS61023 datasheet reached 32 versions and 31 automatic
  component bumps. `inspect_document` now computes `Document.text_sha256`
  from the per-page text through `page_identity`: body pages hashed in order,
  TI addendum pages (`PACKAGE OPTION ADDENDUM`, outline drawings, the notice)
  hashed as an unordered set, `PACKAGE MATERIALS INFORMATION` pages excluded,
  the `www.ti.com D-Mon-YYYY` stamp stripped everywhere. `fetch_datasheet`'s
  ladder: 304 → unchanged; same sha → unchanged; same text hash →
  **`restamped`** (validators refreshed, audit row, nothing stored); bytes
  already held as another document → **`relinked`** (new version, no new
  blob); else a new document and a new version. A scan has no text hash and
  compares by bytes. `doc_revision` (`parse_revision`: PDF Title "(Rev. B)",
  TI Keywords "SLVSF14B", "Rev. X" / "Revised March 2023" on page 1 or the
  last page) is informational — it goes in the note and the UI, it never
  decides. `GET /api/datasheets/restamps` lists the history the byte rule
  wrote, `POST /api/datasheets/restamps/collapse` folds it (pins move to the
  survivor, orphaned documents are deleted); it refuses while the
  classification backfill runs, because a document without a text hash yet
  never matches.
- **A datasheet revision does not carry the review record.** The automatic
  bump goes through `publish.publish_component_version` like every other
  publish, and `review.carry_component` asks `datasheet_store.datasheet_carries`
  after `signoff.data_carries`: a pin that moved to a document with a
  different text hash refuses the carry ("datasheet 'X' changed (Rev. G to
  Rev. H)"). The sign-off still carries — the part is the same part. The bump
  also opens a `ReviewRequest` on the component whose note names the revision
  labels and the pages whose text changed (`changed_pages`, from the stored
  `page_hashes`), so the change reaches the worklist instead of being a silent
  system version.
- **No single request shape works at every supplier.** Measured 2026-09-10 on
  the direct PDF URLs: Infineon answers an AWS WAF challenge with 0 bytes and
  Nexperia a 403 to `curl/8.1`, both serve a browser string; onsemi serves
  curl and 403s the browser; Microchip, ST and Analog Devices refuse both from
  here. `datasheet_store._get` tries the user agent remembered for the host
  (`FetchHost`, learned, never configured) and the other one on a refusal
  (401/403/406/429/503, a WAF header, an empty 200), then records what worked.
  The 11 "empty file" rejections from Infineon in the audit log were this.
- **A publish that touched the datasheet rows fetches them immediately.**
  `routers/components.py` calls `start_fetch_component(comp.id)` after the
  commit when `body.datasheets` was sent: a scoped, stateless run of the
  fetch worker over that component's rows without a local copy, so a new URL
  has its PDF within seconds instead of at 03:00. The agent path already
  archived at publish time (`_archive_datasheet`, above).
- **Every stored document is classified searchable or not, ONCE, at store
  time** (`datasheet_store.classify_text_layer` → the `text_layer`,
  `page_count`, `text_pages` columns on `Document`). It opens the PDF
  with PyMuPDF and counts pages whose extracted text clears
  `_TEXT_MIN_CHARS` (24, above a scanner's stamped page number); ≥
  `_TEXT_RATIO_OK` (0.9) of pages is `text`, none is `scan`, between is
  `mixed`, a non-PDF is `none` and an unopenable file is `error`. Three rules:
  - **Never classify on read.** The corpus is ~900 MB of PDF bytes and single
    documents pass 30 MB. Walking one on every list render is not an option,
    which is the whole reason these are columns and not a computed property.
  - **The classifier never raises.** It runs inside the download path, and a
    document that stores fine must still store when the classifier chokes on
    it. Failures land as `text_layer = "error"`, which is itself a useful
    signal — it caught a 0-byte "PDF" Infineon served as `text/html`.
  - **`""` means "not classified yet"**, and is what
    `start_text_layer_classify("missing")` claims — together with searchable
    documents that have no `text_sha256` yet, which the revision ladder needs.
    It is armed unconditionally 30 s after startup, so it costs nothing on
    every boot after the first sweep. `_classify_worker` loads ONE row at a
    time and expunges it — a `query(Document).all()` here pulls the whole
    library into memory. `POST /api/datasheets/classify` re-runs it (`mode: "all"` after a
    threshold change); `GET /api/datasheets/classify-status` and
    `/fetch-status` both report the per-class counts.

  `mixed` is not noise: a TI datasheet whose last six pages are image plates
  reads 24/30, and those plates are the package-drawing pages a footprint
  check goes looking for. Note the consequence for the agent — `scan` means
  `read_datasheet` returns EMPTY text for every page, so a verification that
  looks like it read the datasheet actually rested on the rendered images.
- **A file nothing can open is refused at the door, on every path.**
  `inspect_document` returns the classification AND the reason to refuse, from
  the same single PDF open; `store_or_raise` turns the reason into
  `BadDocument`. The gate sits in the SERVICE functions (`fetch_datasheet`,
  `store_upload`, `add_component_file`), not in the routers, so the UI upload,
  `POST /api/datasheets/{id}/upload`, the component file-add and the nightly
  fetch are all covered by one rule. Refused: empty files, files that do not
  open as a PDF, password-locked PDFs, and PDFs with zero pages.
  - **A `scan` is NOT refused.** It opens and it is a real document — it is
    only unsearchable. Refusing it would leave the part with nothing at all;
    the tag and `cmp.datasheet_text` exist to get it replaced instead.
  - **`fetch_datasheet` returns `{"result": "rejected", "reason": ...}` rather
    than raising**, so the nightly sweep counts it (`FETCH_STATE["rejected"]`)
    instead of dying. Any copy already held survives untouched — and the gate
    runs BEFORE the sha comparison, so a supplier that starts serving an error
    page reads as "rejected", not as "unchanged".
- **Fixing a component's datasheet: three doors, and only one of them is free.**
  The MCP tool surface has no way to attach a datasheet to an EXISTING
  component, and successive agent passes concluded from that the platform
  cannot do it and recorded `cmp.datasheet` as `skipped` on
  `LC76GPAMD`, `LE310X1-EU/-LA`, `LE910R1-EU` and `MP34DT05TR-A`. That
  conclusion is wrong — it is a gap in the tool surface, not in the API:
  - `POST /api/datasheets/{ds_id}/fetch` — server re-downloads `source_url`.
    No version bump. Use first; the server reaches some hosts the agent cannot.
  - `POST /api/datasheets/{ds_id}/upload` — push a PDF fetched by hand. The
    response says `component_bumped_to: null`, and that is the point: **the
    component version does NOT move, so its verification answers survive.**
    This is the door for a host that 403s the server (verified 2026-08-25 on
    `PESD1CAN,215`, whose Nexperia URL the server cannot reach).
  - `POST /api/components/{id}/versions` with `datasheets: [{label,
    source_url}]` — the only way to create, replace or reorder the ROWS, and
    hence to fix a wrong `source_url`. It **bumps the component version and
    drops every agent answer**, so do it first and re-record afterwards. Pass
    an existing row's `id` to keep its stored PDF; omit a row to archive it.

  Reachability is asymmetric and worth testing rather than assuming: on
  2026-08-25 `ti.com`, `assets.nexperia.com`, `hammfg.com`, `quectel.com`,
  `infineon.com`, `italtronic.com`, `degson.com`, `china-fenghua.com`,
  `samwha.com` and `telit.com` all served real PDFs to the agent's machine,
  while `phoenixcontact.com` (403), `st.com` (timeout) and `renata.com` (500)
  refused both it and the server. A 403 or a login wall arrives as a
  200-status HTML page, so check `file` says `PDF document` before uploading.
- **Datasheets are indexed PER PAGE, and the index is a finding aid — never an
  authority** (`services/datasheet_pages.py`, 2026-08-25). `DatasheetPage`
  holds one row per page of layout-aware markdown from `pymupdf4llm` (same
  MuPDF engine and Artifex licence as the `pymupdf` already used; it pulls
  onnxruntime, MIT). Keyed on the IMMUTABLE `datasheet_version_id`, so a row
  never goes stale — new PDF content is a new version with its own pages.
  Measured on the live corpus: 0.18–0.27 s per page, ~9400 pages on the
  current copies, 16.4 MB of text.
  - **Why it exists**: `read_datasheet` returns at most 6 pages chosen by
    GUESSING a page number, and RP2040 is 642 pages with its absolute maximum
    ratings on page 615. Nothing could search datasheet text at all.
  - **What it may not be trusted for.** The extractor keeps a table's grid and
    recovers the text drawn inside a mechanical figure, both of which plain
    extraction destroys — the TPS61023 land-pattern drawing yields
    `6X (0.67)`, `4X (0.5)`, `(1.48)`, and the STM32H725 LQFP100 pinout figure
    yields a correct pin-number-to-name map for all 100 pins. It ALSO shreds
    text that wraps inside a merged cell ("voltage must be supplied from" →
    "voage mus e suppe rom", STM32H725 p117) and reorders multi-line pin labels
    ("PC15-OSC32_OUT" → "OSC32_OUTPC15-", UFBGA169 ballout), and a unit in a
    merged column lands on one row of the group. So the index FINDS a page and
    the page image settles the value. Do not build a check that reads a
    dimension out of `content`.
  - **`extract_kind` is never blank on a written row.** `text` |
    `picture_text` (all of it came from inside a drawing) | `fallback_text`
    (layout extraction failed, plain extraction used) | `empty_scan` |
    `failed`. The extractor returns zero characters on a scanned page in
    0.08 s and raises NOTHING, so an unmarked empty row would make search
    return nothing and let a reader conclude the page is blank. This is the
    page-level twin of `DatasheetVersion.text_layer`.
  - **`pages_indexed_at` on the version is the coverage marker, not "has any
    page rows"** — a non-PDF legitimately yields zero pages and would
    otherwise be retried on every sweep for ever.
  - **The `tsv` column is GENERATED and the config is `simple`.** It cannot
    disagree with the content beside it, and `datasheet_pages._TSCONFIG` must
    stay identical to the DDL in `main.py` — a query parsed with a different
    config does not match the GIN index and silently falls back to a seq scan.
    `english` was rejected on purpose: datasheet tokens are part numbers,
    package codes and dimensions, which stemming damages.
  - **Search excludes superseded versions by default** (`d.current_version_id
    = dv.id`). Including them returns the same hit several times and points at
    a page the library no longer serves.
  - Sweeps mirror the fetch/classify pair: `POST /api/datasheets/index`
    (`missing` = the retroactive backfill, `current`, `all`),
    `POST /api/datasheets/index/stop` (stops BETWEEN versions — a
    half-extracted document would read as complete, because
    `extract_version` stamps `pages_indexed_at` itself),
    `GET /api/datasheets/index-status`. Startup arms `missing` after 120 s
    unless `DATASHEET_PAGE_INDEX_ON_STARTUP=false`. A store path fires
    `_index_pages` in a daemon thread — a 642-page document is three minutes
    of work and must never sit in the upload request. **In dev, a source edit
    reloads uvicorn and KILLS a running sweep**; the version's NULL
    `pages_indexed_at` is what makes that recoverable.
  - Read surfaces: `GET /api/datasheets/search`, `/{id}/outline`,
    `/{id}/pages/{n}`, and the agent tools `search_datasheets` /
    `datasheet_outline` (34 client tools now — the count in
    [jaravis.md](jaravis.md) has been stale since before this).
- **`GET`/`DELETE /api/datasheets/broken`** list and remove documents that were
  archived before the gate existed. `purge_broken` does three things in order,
  and all three are load-bearing: NULL the `ComponentVersionDatasheet` pins (a
  real FK — the delete raises otherwise, and NULL already means "no local copy
  existed"), repoint `Datasheet.current_version_id` to the newest survivor or
  NULL (a dangling pointer makes `has_file` true and every download 404), then
  refresh the mirror for the affected categories (`injected_props` emits the
  LOCAL url whenever a current version exists, so a row falling back to NULL
  must go back to emitting the supplier URL). Run 2026-08-25: removed 2 — a
  truncated 300 kB LCSC PDF whose xref cannot resolve object 1
  (`FPC-05F-24PH20`, still served broken today, so that part now has no local
  copy at all) and a 0-byte `text/html` file Infineon served under a `.pdf`
  name (`BTT60501ERAXUMA1`, history only).
- **`cmp.datasheet_text` is a machine checklist item** answered by
  `validate_component` from the `text_layer` column, so it costs a column read.
  `scan` and `error` fail it; `mixed` passes with the page counts in the note;
  a non-PDF or an unclassified row is `na`. Two things to know before touching
  the machine tier:
  - **Adding a machine key does NOT re-open settled reviews.**
    `state_from_record` measures against the record's OWN pinned checklist
    snapshot (`_checklist_items_of`), so a checklist edit never flips history.
    Verified after publishing component checklist v2: 128 components stayed
    `checked` with zero records carrying the new key.
  - **There is deliberately no bulk re-validate**, and do not add one casually.
    `effective_record` is "newest non-revoked record on this version",
    regardless of actor — so writing a fresh machine record across the library
    would SUPERSEDE every human confirmation it lands on. A new rule therefore
    applies from each component's next publish onward.
