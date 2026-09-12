# Jaravis — implementation notes (`api/app/services/jaravis.py`)

The capability policy that governs what Jaravis may do is in
[mcp/CLAUDE.md](../../mcp/CLAUDE.md). This page holds the implementation.

- **Simulation and the field solver are on the tool surface too** (2026-08-31).
  Running: `sim_projects`, `sim_scenarios`, `sim_netlist`, `sim_run_scenario` —
  the last one returns the harness's PASS/FAIL verdicts, per-vector min/max/final
  and the ngspice log tail, never the 7SIM binary (a transient is tens of
  thousands of points per vector). Impedance: `fieldsolver_stackups`,
  `fieldsolver_rules`, `fieldsolver_geometry`, `fieldsolver_solve`,
  `fieldsolver_find_solutions`, `fieldsolver_board`,
  `fieldsolver_assign_stackup`, `fieldsolver_save_profile`. Two deliberate
  omissions: **no stackup create/edit tool** — a stackup is admin-only and a tool
  call carries no signed-in administrator — and **no profile delete**, because
  overwriting by name is enough and a delete would be the one destructive act on
  somebody else's board. `fieldsolver_solve` and `fieldsolver_find_solutions` run
  the FEM inline (seconds to a minute), so they take small sweeps by default; the
  browser's job queue exists for the long ones.
- 26 client tools + 2 Anthropic **server tools** (`web_search_20260209`,
  `web_fetch_20260209` — plain dicts appended to the runner's tools list; they
  execute on Anthropic's side, no beta header, `max_uses` caps cost).
- **pause_turn**: the Python tool runner does NOT auto-resume a
  `stop_reason="pause_turn"` from a long server-tool turn — it silently
  truncates. The loop mirrors the conversation while iterating and restarts
  the runner with the paused turn appended (bounded). Keep that loop when
  touching the runner code.
- **The agent loop is a generator** (`run_chat_events`): it yields
  `note`/`tool` progress events per iteration plus a final `done`; long runs
  show live activity and a Stop button (client disconnect closes the generator
  → run ends at the next event). `run_chat` is the blocking drain kept for
  scripts. `MAX_ITERATIONS` (80) bounds model calls per turn — the runner
  stops silently when hit, so `run_chat_events` synthesizes a "stopped, say
  continue" reply.
- **Persisted chat is server-authoritative** (`JaravisSession` +
  `JaravisMessage`; the `messages` relationship cascades on delete). The DB —
  not the browser — holds the conversation, so it survives reloads and the user
  can keep several chats in parallel. Session titles auto-derive from the first
  user message. The stateless `POST /chat` + `POST /chat/stream` (full message
  array, store nothing) stay for scripts.
- **A turn runs in a BACKGROUND THREAD, decoupled from the HTTP client**, so a
  refresh / closed tab does NOT cancel it — this is the whole point of the
  persistence (a request-scoped run is cancelled on disconnect and its answer,
  and tokens, are lost). `start_session_run(sid, content)` spawns
  `_run_worker` (persists the user message BEFORE the long turn, replays only
  role+text to `run_chat_events`, persists the assistant reply — text+trace+
  proposals — the instant `done` is produced) and appends every event to an
  in-process `_Run.events` buffer under a `Condition`. `POST
  /sessions/{id}/chat/stream` starts the run then tails the buffer via
  `stream_run_events` (409 if one is already running); `GET
  /sessions/{id}/run/stream` re-attaches after a reload and replays the buffer
  from the start (204 when nothing is running — stored messages are then
  authoritative); `POST /sessions/{id}/run/cancel` sets `_Run.cancelled` so the
  worker breaks the loop at the next event boundary (the server-side Stop
  button; no assistant message is persisted for a cancelled turn). At most one
  active run per session; `_run_worker` removes itself from `_RUNS` on finish
  (subscribers keep their local ref and drain). The registry is **in-process
  and does NOT survive a restart** — a run in flight when uvicorn restarts
  (including a `--reload` from a code edit) is lost; the reloaded page then sees
  a dangling trailing user message and reconciles. Never yield while holding
  `_Run.cond`.
- **Per-turn proposals use a `ContextVar` (`_turn_proposals`), not a module
  global** — set to a fresh list at the start of each `run_chat_events` turn and
  read into the `done` event; `_record_proposal` appends. This isolates
  overlapping turns (background threads; two sessions at once) so drafts are
  never cross-attributed. Do not reintroduce a shared module-level list.
- `read_datasheet` returns a LIST of content blocks (text + base64 PNG page
  images rendered with **pymupdf**) — tool results may be
  `Iterable[BetaContent]`, not just str. pymupdf is a pyproject dependency.
- **Geometry proposals live in `services/geometry_proposals.py`, not in the
  tool.** `propose_symbol_version` / `propose_footprint_version` own the
  validation (kiutils/sexpr parse, footprint header must equal the name with NO
  prefix, 3D paths must start `${SEVENSIGMA_DIR}/3DModels/`; note the footprint
  node IS the sexpr tree root — reuse parse_cache's fallback), the draft row and
  the audit entry. New names create the parent row with `current_version_id=None`,
  same as components. **Two callers must never diverge**: the
  `propose_symbol_edit`/`propose_footprint_edit` agent tools (which only add
  `_record_proposal` + `json.dumps`) and `POST /api/{symbols,footprints}/{id}/propose`,
  the web paste box. The route takes the name from the ROW, never the request,
  so a paste can never rename a template.
- **Pasted geometry is normalised before it is parsed.** KiCad's editors put an
  s-expression on the clipboard, but not necessarily the file body: a footprint
  can arrive wrapped in an outer node and a symbol as a bare `(symbol …)` with no
  library. `normalize_footprint_text` / `normalize_symbol_text` reduce both to
  what the parsers expect, via `slice_node` — a hand-rolled balanced scan rather
  than parse-and-serialise, because the result is STORED as the version source
  and must keep the author's formatting byte-for-byte. A payload with no
  footprint/symbol node at all is refused by name ("this is not a whole
  footprint"), because a canvas-only selection otherwise parses fine and then
  fails the header check with a confusing message.
- **The same drawing, spelled differently, is NOT a new version**
  (`geometry_proposals._unchanged`, 2026-08-27). KiCad rewrites the WHOLE
  library file it saves: opening `7Sigma_Base.kicad_sym` in KiCad 10 and
  saving added `(show_name no)` 1284 times and `(do_not_autoplace no)` 1274
  times, re-sorted the pins of 21 symbols and moved custom properties ahead of
  the `ki_*` ones — across 197 symbols, 183 of which nobody had touched. Every
  call to `propose_*_version` bumps `version_no` and `_publish_geometry`
  repoints every component onto the new row, so pushing that file once would
  have written 197 symbol versions, published a component version for each of
  ~420 components, and buried the 14 real edits among them. Both propose
  functions therefore compare the incoming payload against the LIVE version
  first and return `{"ok": true, "unchanged": true, …}` without writing
  anything when they are the same drawing.
  - **It reuses `services/pcm_plugin/kicad_canon.py`, and must keep doing so.**
    That module already answers this exact question for the sync and push
    plugins, which meet the same wall from the client side; a second dialect
    that disagreed with them about what "edited" means would be worse than no
    guard. Measured on the real library: `kicad_canon` absorbs 169 of 197
    entries, and the 28 it still reports are real — 14 edits made on purpose
    and 14 where KiCad genuinely moved a hidden property field to `(at 0 0 0)`.
  - **Do NOT use `material.material_sha` for this.** It answers "does the
    production sign-off still hold" and deliberately ignores the symbol body
    outline, field text and field positions, so it reads a full redraw as no
    change. The two hashes measure different things on purpose.
  - **Never write the canonical form into a library file.** It sorts the
    children of `(symbol …)`, which reorders graphics and so decides which
    fill sits on top. It is a comparison key, exactly as its own docstring
    says. The stored `source_text` stays the author's bytes.
  - `cli/symdiff.py` is the client-side half: it reports which entries of a
    `.kicad_sym` really changed and `--extract`s them as single-symbol
    libraries ready to push. Run it before pushing a file KiCad has re-saved.
- **A clipboard copy has NO name, and the name is rewritten, not enforced.**
  KiCad names a copied item after the pseudo-library it invents for the
  clipboard — `(footprint "clipboard:11d1f418-7567-4c54-…")`. Refusing on a
  header mismatch therefore rejected the primary way text arrives, and deriving
  a name from it would have created a footprint literally called
  `clipboard:<uuid>`. So: `set_footprint_header` / `set_symbol_entry_name`
  rewrite the pasted name to the authoritative one (the row being edited, or
  what the user typed), and `is_placeholder_name` makes `derive_*_name` return
  None for a placeholder so the create form asks instead. A mismatch that is a
  REAL name still lands, with a warning naming both — silence there would let a
  wrong paste overwrite the wrong template unnoticed. Renaming a symbol must
  rewrite its unit entries (`<entry>_<unit>_<style>`) too, or the symbol renders
  empty.
- **Rendering needs the name INSIDE the text to match the name passed to
  kicad-cli.** `_render_source` therefore rewrites both to a safe label when the
  payload is a clipboard copy: the colon in `clipboard:<uuid>` reads as a
  library separator and the symbol lookup fails (502). Pass
  `allow_placeholder=True` to `derive_*_name` when you only need a label.
- **Creation reads the name OUT of the pasted text** (`derive_footprint_name` /
  `derive_symbol_name`), so `POST /api/{symbols,footprints}/propose` has no name
  field: a footprint header must equal the row name anyway, so a second field
  could only ever disagree. That route also REFUSES a name that already exists.
  The agent tool's "new name = create, known name = edit" overload is right for a
  call that states the name, but on a form labelled *new* it would file a version
  against a template the user never opened.
- **Rejecting the only draft of a never-published template deletes the row**
  (`proposals._drop_if_stillborn`). A creation proposal makes the parent up front
  with `current_version_id=None`, so a rejected creation used to leave a
  permanent versionless entry in the Templates browser that no UI could remove.
  Guarded twice: the parent must have no `current_version_id` AND no non-rejected
  version, so rejecting one draft of a published template never touches it.
- **`POST /api/{symbols,footprints}/preview.svg` renders UNSAVED source.** It is
  what the paste box previews before filing. It writes nothing and touches no
  table; `render_svg` is content-addressed, so re-previewing identical text is
  free. It normalises first — the point is to show what WOULD be filed.
- **A structured refusal puts its whole message in `error`.** These return
  `{"error": …, …context}` and the router raises it as the HTTPException detail;
  the web client renders `detail.error` verbatim. Context keys (`offending`,
  `symbols_found`, `header`) are extra for non-browser callers — never the only
  place a fact appears, or the browser shows a bare "400 Bad Request".
- Publishing geometry rebuilds the mirror through
  `publish.refresh_mirror_for_geometry`: a symbol publish rebuilds the base lib
  + the affected top-level libs (`update_mirror_symbols`), a footprint publish
  writes its own `.kicad_mod` AND those symbol libs (the injected "7S Version"
  field moves when a repoint bumps a component version). The PCM packages pick the change up
  lazily via the manifest hash. Components keep their pinned
  `symbol_version_id`/`footprint_version_id`; the KiCad-facing base lib,
  footprint mirror, and HTTP catalog always follow the newest published
  geometry.
- **Publishing geometry AUTO-PUBLISHES the component repoints**
  (`services/repoint.py`, user decision 2026-08-04, publishing since
  2026-08-23). The two facts above pull apart: the mirror and the HTTP catalog
  jump to the new geometry while every linked `ComponentVersion` still names the
  previous `footprint_version_id`, so the library and the components silently
  disagree about which land pattern is current. Measured on 2026-08-03: a pin-1
  sweep published 105 footprint versions and left 185 of 327 components pinned to
  the superseded drawing. So a geometry publish calls `repoint_for` in the SAME
  transaction and returns the result as `repointed`; each affected component
  gets a published version through `publish_component_version`, so the sign-off
  carry, the review carry and the machine check all run.
  `AUTO_REPOINT_COMPONENTS=false` turns it off. What a stale pin looks like to
  a user is `PinnedRef.is_current === false` on the component page ("library
  serves v5") — the state this exists to prevent. Invariants in that module:
  - **A leftover human/agent draft is skipped, not rewritten**, and reported in
    `repointed.skipped`. Nothing files drafts any more, so this only fires on
    rows from before the gate was removed — but rewriting one would still be
    rewriting somebody's unfinished edit.
  - **A leftover auto-draft is refreshed and published** rather than left beside
    a new parallel version.
  - **Properties are cloned in FULL fidelity** — `hide`, `show_name` and `layout`
    included. `propose_component_edit` writes only key/value/is_null and lets the
    rest default, which is fine when a caller is restating properties on purpose,
    but here the component is not being edited and `hide` drives KiCad field
    visibility.
  - **Never read `comp.versions` inside this module.** The session is
    `expire_on_commit=False` and rows added here are not appended to a loaded
    relationship, so it goes stale the moment a version is added — that made the
    coalescing miss its own draft and open a second one. Use `_versions(db, comp)`.
    `publish.publish_skill_version` avoids the same trap by querying the version
    numbers instead of reading `skill.versions`.

