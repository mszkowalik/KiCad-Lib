# The KiCad sync plugin (`api/app/services/pcm_plugin`)

The source of the Sync 7Sigma Library plugin. `api/app/services/pcm.py` packages
it. Decision
[0006](../../../../docs/decisions/0006-sync-button-owns-library-updates.md) says
why the Sync button owns library updates, not the Plugin and Content Manager.

- **IPC plugin buttons appear in the PCB EDITOR ONLY.** `api.v1.schema.json`
  accepts five scopes (`pcb`, `schematic`, `footprint`, `symbol`,
  `project_manager`), but KiCad implements the IPC plugin system in the PCB
  editor alone — the other editors are "planned" (dev-docs, *For Add-on
  Developers*). The enum being permissive is not a capability; do not read it
  as one, and do not promise a button in the footprint or symbol editor.
  Verified against KiCad 10 on 2026-07-31: both actions declare all four
  scopes, and both render in the PCB editor only. The extra scopes are
  harmless — the plugin still loads — so they stay as forward compatibility.
  This costs the push plugin nothing: it reads the SAVED library files off
  disk, so the focused editor is irrelevant. Edit in the footprint editor,
  save, push from the PCB editor.
- **"Did I edit this?" is a CANONICAL comparison, never a byte hash**
  (`services/pcm_plugin/kicad_canon.py`, shared by both entrypoints). KiCad
  rewrites the WHOLE file it saves and writes tokens the platform's generator
  omits — every `(property …)` gains `(show_name no)` and
  `(do_not_autoplace no)`, every symbol gains
  `(duplicate_pin_numbers_are_jumpers no)` and `(in_pos_files yes)`, pins come
  back sorted, and every footprint pad and graphic gets a fresh `(uuid …)`.
  Measured 2026-08-20: editing ONE symbol changed the text of all 183 entries
  in `7Sigma_Base.kicad_sym`, Push offered to propose every one of them, and
  Sync froze the whole library. The canonical form drops default-valued tokens
  and uuids, normalises numbers and sorts the unordered children of
  `(symbol …)` / `(footprint …)`. It is a COMPARISON KEY: it is never written
  to a library file. Extend `DEFAULTS` when a KiCad release starts printing
  another default — the symptom is "everything is suddenly edited" right after
  a KiCad upgrade.
- **The unit of protection is the drawing, not the file.** Every base symbol
  lives in one generated `.kicad_sym`, so "never overwrite a file edited here"
  meant one edited symbol blocked updates to the other 182.
  `_conflicting_entries` finds the edited ENTRIES and `_merge_symbols` keeps
  only the ones the user chose; the entries it keeps must NOT be re-recorded
  (`_record_written(..., skip=…)`), or the next sync overwrites the unsent edit
  and Push forgets it exists.
- **A conflict row is ONE ITEM in EVERY path, including the orphan path.** The
  rule above covered the normal case and missed the other one: a library file
  the upstream package no longer carries (a rename upstream, a stale duplicate)
  was emitted as a single row, hardcoded `"kind": "footprint"` — so a
  `.kicad_sym` appeared as one line under the "Footprints" header whose "server"
  answer deleted all 196 symbols at once. Reported 2026-08-24. `_scan_conflicts`
  now splits it per entry, and the matching prune in `_apply_package` rewrites
  the file with `kicad_canon.drop_symbols` instead of unlinking it, removing it
  only when every entry was released. Two things follow: the prune must clear
  `_LOCAL` for the entries it drops and the file-level record when it rewrites
  (the kept entries keep their own records, which is what Push reads), and it
  must name only the entries that HAD a row in `kept_local` — the unedited rest
  are stale copies of upstream drawings, and reporting them made one notify list
  195 symbols.
- **3D models carry per-file records too, since plugin 1.3.0, and their check is
  stat-first.** Models used to bypass the conflict window entirely, and not
  merely coarsely: `_sync_models_delta` compared the upstream sha against the
  RECORDED sha in `models_state.json`, never against the bytes on disk, so a
  model edited here read as current, was never re-fetched, was never asked
  about, and was overwritten in silence by the next full-zip fallback.
  `local_state.json` held zero model keys. What blocked the fix was cost — 4745
  models, about 1.4 GB, is not hashable on every sync. So each record is now
  `{"s": sha, "m": mtime, "z": size}` and `_model_edits` stats the tree and
  hashes ONLY the files whose size or mtime moved (measured: 3 reads for 3 edits
  out of 50 files). A bare-string record is pre-1.3.0 and adopts the current
  stat at the sha it already asserted, so the upgrade reports no edits rather
  than a wave of false ones. Consequences to keep: `_sync_models_delta` is split
  into `_scan_models_delta` (read-only, returns a plan plus rows) and
  `_apply_models_delta`, because the single-dialog rule below forbids asking
  mid-write; a model the user KEEPS must not be re-recorded, so the record
  cleanup keys on what is still ON DISK rather than on `upstream`; and the
  full-zip path must WRITE the records it builds — it used to delete
  `models_state.json`, which would now leave the next sync unable to tell an
  edit from a write.
- **A two-way clash is a QUESTION, not a policy.** When a drawing changed here
  AND on the platform, the old rule kept the local copy silently and for ever,
  so an approved fix could never come back down — the only escape was deleting
  the file by hand (reported 2026-08-23, the mirrored KSZ8864 footprint).
  Sync now runs in two passes: `_fetch_package` + `_scan_conflicts` gather every
  clash across EVERY package without writing anything, `conflict_ui.resolve`
  asks once in one window, then `_apply_package` writes. Keep the passes
  separate — asking per package would put three dialogs in front of one sync,
  and asking mid-write would leave a half-applied package if the user cancels.
  `_members()` is deliberately shared by both passes: if the scan and the write
  disagreed on which zip entries are in play, the dialog would ask about a file
  that never gets touched.
- **Every failure path in the conflict UI resolves to "mine".** Cancel, a closed
  window, no wx, no osascript, an absurd conflict count — all keep the local
  copy, which is what the plugin did before the dialog existed. Refusing an
  update is recoverable; destroying an unsent drawing is not. `resolve()` always
  returns a decision for every key so no caller has to handle a gap. wxPython
  ships inside KiCad (4.2.2 on the 3.9 runtime), with the AppleScript list Push
  already uses as the fallback.
- **Reconcile, or an approved edit stays pending for ever.** A sync that
  refuses to clobber a local edit must still notice when that edit IS the
  platform's copy now — pushed, approved and come back. Without it the baseline
  keeps the pre-edit hash, the file is "edited" for ever, and Push keeps
  offering to propose it again (reported 2026-08-20, five footprints). Push
  carries the same belt-and-braces check: it verifies the FLAGGED items against
  the live mirror and corrects the baseline, so a wrong state file self-heals.
  A failed fetch leaves the item flagged — offering an edit twice is annoying,
  losing one is not recoverable.
- **The prune must never delete a library file the plugin did not write** —
  unless the user asked for it in the window. It is either a local edit or a
  footprint drawn here and not yet pushed; the old rule deleted anything absent
  from the package, which destroyed new work before Push could send it. **Models
  are no longer exempt** (they were, while they carried no record): a model with
  no record was placed here by hand and a model whose record is dirty was edited
  here, and both now survive a prune unless the dialog released them. A model the
  plugin wrote and nothing touched still prunes silently — that is a genuine
  upstream deletion, not work.
- **Every local change is offered back, not just the two-way clashes.** A
  drawing edited here while the platform's copy stayed put is not a conflict,
  but "throw my edit away and take the platform's copy" is still something only
  this window can do — otherwise the answer is "delete the file by hand". So
  `_scan_conflicts` emits three kinds of row, each labelled with its `note`:
  changed on both sides, changed only here, and exists only here (where the
  server side means DELETE). The cost is that a package with no upstream change
  is fetched anyway while any local edit is outstanding (`_has_local_edits`
  forces it) — 0.5 MB for the library package, and the only way the window can
  show what the platform would give back. Every failure path still resolves to
  "mine".
- **Push carries the 3D model, or the footprint cannot be pushed at all.** A
  footprint drawn here points its `(model …)` wherever the file actually sits —
  ~/Downloads, KiCad's own `3dmodels/` tree, a project folder — and
  `geometry_proposals` refuses any path outside `${SEVENSIGMA_DIR}/3DModels/`.
  So `push.py` resolves each off-library reference on disk
  (`model_paths.resolve`, expanding `${KICAD*_3RD_PARTY}` and
  `${KICAD*_3DMODEL_DIR}` from the install layout — KiCad does not export its
  path variables to a plugin), asks where each one goes (`model_ui`, suggested
  path editable), uploads them to `/api/models3d/upload` FIRST, then rewrites
  the reference and sends the footprint. A reference whose file is missing
  blocks that footprint with a named error rather than letting the platform
  answer with a validation refusal.
  - **The local file is repointed at the installed copy afterwards, and its
    baseline is deliberately NOT re-recorded.** Repointing stops the model
    vanishing when ~/Downloads is cleared and stops the next push re-uploading
    it; leaving the baseline alone means the next sync settles the file by
    comparing drawings, which is the one path that cannot lose an edit if the
    mirror is still rebuilding. The rewritten path uses `THIRD_PARTY_VAR`,
    baked into the template by `_plugin_files` as `__THIRD_PARTY_VAR__` — the
    same constant the library zip's rewrite uses, so `to_platform_text` undoes
    exactly what was written and the round trip is byte-stable.
  - **The suggested folder follows what the library already does**: the
    footprint's current model folder, else the source file's own `*.3dshapes`
    folder (a model adopted from KiCad keeps KiCad's category), else
    `7Sigma.3dshapes/`. Nineteen hand-uploaded files sit loose at the root of
    `3DModels/` from before that rule existed.
- **A missing baseline means "unknown", and Push must FLAG an unknown item.**
  The two rules above combine into a trap: Sync withholds a record for an entry
  it kept back, so a drawing edited before the first sync that protected it
  never gets a baseline, and no later sync writes one. Push treated "no record"
  as "cannot judge", listed the item in a footnote and offered it to nobody —
  a moved pin on BTS723GW was unpushable and Push reported "no local changes"
  (2026-08-21). `_changed` now flags an unrecorded item and lets `_drop_settled`
  settle it against the live mirror, which is the only test that can tell an
  unrecorded edit from an unrecorded untouched file. Never re-introduce a
  branch that answers "unknown" with silence.
- **`local_state.json` records both hashes** (`{"r": raw, "c": canonical}`) and
  still reads a bare string as a pre-1.1.0 raw-only record. Dropping that
  fallback would make every installed file read as edited on the first run
  after an upgrade. `models_state.json` follows the same shape for the same
  reason — `{"s","m","z"}` now, a bare sha before 1.3.0 — and it is PRIVATE to
  `sync.py`: nothing else reads it, which is what made the format change safe.
- **The dialog has two row ceilings, not one.** Answers are per item now, so a
  single sync can legitimately raise hundreds of rows and collapsing them all to
  "kept everything" is the worse answer. `conflict_ui._WX_MAX_ROWS` (600) is the
  give-up point; `_SANE_ROWS` (200) now gates only the AppleScript backend,
  whose `choose from list` cannot be scrolled sensibly. Notifications that list
  names go through `_names()`, which caps at 8 plus a count — a macOS
  notification truncates anyway.
- **Two constants gate whether a plugin change reaches anyone, and both are
  manual.** `PLUGIN_VERSION` is what PCM compares to decide "update
  available", so shipping plugin source without bumping it is a silent no-op.
  And `ensure_built()` short-circuits on `meta-<tag>.json`, where `tag` hashes
  the mirror digest plus the plugin FILE contents — NOT `pcm.py` — so a
  `PLUGIN_VERSION` bump on its own never rebuilds the repository either. Any
  `pcm.py` edit that changes what a package advertises needs `BUILDER_REV`
  bumped too. Both were missed in sequence on 2026-07-31 and the repository
  kept advertising 1.0.4 through four deploys.
- **KiCad PCM/plugin gotchas** (`services/pcm.py`, `services/pcm_plugin/`):
  package identifiers allow NO underscores (dots/dashes only) but KiCad
  replaces dots with underscores for install directories; `license` must be
  a value from the schema enum (`unrestricted` for in-house); python-runtime
  IPC plugins REQUIRE a `requirements.txt` or env setup silently aborts and
  the toolbar button never appears; **KiCad's bundled Python has NO usable CA
  store on macOS** (its compiled-in cafile path does not exist inside the app
  bundle), so every `urlopen` of an https URL fails with
  CERTIFICATE_VERIFY_FAILED — first hit when the platform moved to
  `https://disfunction.cc` (2026-08-03, plugin 1.0.8). Both templates build an
  SSL context from certifi (in the plugin venv via `requirements.txt`) with
  `/etc/ssl/cert.pem` as the stdlib-only fallback; never disable verification
  — the push plugin carries a write credential; validate generated metadata against
  `go.kicad.org/pcm/schemas/v1` and the plugin manifest against KiCad's
  shipped `api.v1.schema.json` before shipping. The library package ships
  ONLY the deduplicated `7Sigma_Base.kicad_sym` (written by
  `mirror.write_symbol_libs`) + footprints — HTTP-catalog parts reference
  base drawings (`symbolIdStr = HTTPLIB_SYMBOL_LIB:<base_component>`), so
  adding components must never bump the library package. 3D model updates
  flow as LZMA deltas (`POST /api/kicad/pcm/models-delta`).
- **The sync plugin sweeps the install directory on EVERY run, before it
  fetches anything** (`_sweep_strays` + `_repair_lib_tables` in
  `pcm_plugin/sync.py.tmpl`). The KiCad user directory usually sits in iCloud
  Drive (`~/Documents/KiCad/<ver>`), and the file provider uniquifies a
  colliding name: the PCM extracts `7Sigma.pretty` over a copy iCloud still
  holds and an EMPTY `7Sigma 2.pretty` appears beside it — or it extracts
  `7Sigma_Base.kicad_sym` and a `7Sigma_Base 2.kicad_sym` holding the OLD
  library appears (2026-09-06). KiCad's PCM registers every `*.pretty` and
  `*.kicad_sym` in a package, so the user gets a second, broken footprint
  library row, or a second, stale symbol library — and the stale one is worse:
  no entry in it has a baseline in `local_state.json`, so the conflict window
  lists all of them as "only here — never sent" (153 rows). Three rules
  follow. The sweep cannot live in the apply path — the install that creates a
  stray also records the package as current, so apply is the one path that
  never runs again (seen 2026-08-25: the prune at the end of `_apply_package`
  had been there all along and the stray survived it). A duplicate with
  content is MOVED to `strays/<stamp>/` inside the plugin folder, never
  deleted (plugin 1.4.1) — the plugin cannot know whether the content is the
  user's, and a move takes it out of KiCad's and the scan's sight while
  keeping it. And removing the stray is only half the repair: the row the PCM
  already wrote into the global `fp-lib-table` / `sym-lib-table` must go too,
  or KiCad reports a missing library forever. The table edit is deliberately
  narrow — a row goes only when its URI resolves inside a `com_sevensigma*`
  install directory AND that path is gone — and it asks for a KiCad restart,
  because KiCad holds the tables in memory and can write them back on exit.
  The sweep commit of 2026-08-27 bumped only `BUILDER_REV`, so 1.4.0 with the
  sweep never reached anyone who had 1.4.0 without it — the second time the
  rule two bullets up bit.
- **The sync plugin writes KiCad's PCM record, and pins the content
  packages** (`_record_pcm_installed` in `pcm_plugin/sync.py.tmpl`, plugin
  1.5.0). `installed_packages.json` in the KiCad settings folder is what the
  PCM compares against the repository; verified in the 10.0 source, it is
  read ONCE (`PLUGIN_CONTENT_MANAGER` constructor) and written ONLY when
  `DIALOG_PCM` closes, and the badge check (`RunBackgroundUpdate`) runs at
  start-up and after that dialog. So an in-place sync left the PCM offering
  the 259 MB models zip as an "update" forever. After a sync, every content
  package whose `sync_state.json` sha matches the served one is recorded at
  the served version with the served package body (KiCad asserts the recorded
  version exists in the recorded version list) and `pinned: true` — pinned
  packages are excluded from the badge count and from Update All, and
  `MarkInstalled` keeps the pin across a PCM-driven update. The plugin's own
  entry is never touched: the plugin cannot update itself, so PCM must keep
  offering it. The file is found through `_kicad_config_dir(PCM_RECORD)`, the
  same resolver the lib-table repair uses; any read or write problem is
  swallowed. A PCM dialog closed later in the same KiCad session writes the
  stale in-memory record back; the next sync re-corrects it. No IPC API
  command reloads libraries or updates placed footprints, so the closing
  notification tells the user about Tools → Update … from Library.
