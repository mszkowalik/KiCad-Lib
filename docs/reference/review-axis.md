# The review axis — sign-off, verification and the review record

Every write auto-publishes, so accountability lives here instead of in an
approval queue. Two services own it: `api/app/services/signoff.py` (production
sign-off and material) and `api/app/services/review.py` (the review record).

## Production sign-off (`services/signoff.py`, `services/material.py`)

A **sign-off** records that a human checked a component's symbol, land pattern
and part number before boards were built (user design, 2026-08-17). It is a
different act from library approval and uses a different word everywhere: a
version's `approved_by` means "this edit was let into the library", and a
published component may never have been checked by anybody. Never merge the two
concepts, and never let a UI print one where it means the other.

- **The row names a `component_version_id`, never just a component.** A
  component version pins its exact `symbol_version_id` and
  `footprint_version_id`, and version rows are immutable, so naming the version
  names the three drawings that were checked and can never come to mean
  something else. Every state is DERIVED from one question — is there a live
  sign-off on `components.current_version_id`? — so nothing is ever swept or
  invalidated. `signed` | `stale` | `revoked` | `unsigned`; `revoked` must never
  render as `unsigned`, because "somebody took this back" is a stronger
  statement than "nobody looked yet".
- **`component_signoffs` is append-only, with no unique constraint.** Revoking
  stamps `revoked_at`; signing again adds a row. The live sign-off of a version
  is the newest row for it with `revoked_at IS NULL` (`live_signoff`).
- **Two publish paths must BOTH carry.** `proposals.approve` and
  `components.create_version` (the in-place save, where the user saving IS the
  approval) each call `signoff.carry_on_publish` in the same transaction as the
  publish. Miss one and editing a description silently unsigns the part. Any
  future third publish path has to call it too.
- **`NON_MATERIAL_KEYS` is an ALLOW-LIST, and the direction is the point.** A
  property key is material — it can make the checked part the wrong part —
  unless it is explicitly listed (`ki_description`, `ki_keywords`,
  `ki_fp_filters`, `ki_locked`, `Datasheet*`, `Footprint_Name`). A new key
  nobody has classified blocks the carry, which is the safe way to be wrong.
- **The material fingerprint is what makes the carry provable.**
  `services/material.py` hashes only what reaches the board: pads (number, type,
  shape, position, rotation, size, drill, layers, margins, primitives), the
  courtyard and the `attr` flags; on symbols, the pin set (number, name,
  electrical type, graphic style, position, length, hidden, alternates, unit).
  Silkscreen, fab, `descr`/`tags`, uuids, 3D models, symbol body graphics and
  field positions are excluded on purpose. Parse with `util/sexpr.py`, never
  kiutils, and never reuse `parse_cache` here — it drops pad and pin POSITIONS,
  which is the single most important thing being compared. **An empty
  `material_sha` means "could not tell" and must NEVER compare equal to another
  empty one.**
- **Precedence in `geometry_carries` is deliberate**: `recheck_required is True`
  wins over everything (an approver who asks for another look has a reason the
  fingerprint cannot see); then an identical fingerprint yields `auto-carried`;
  only then does `recheck_required is False` yield `carried`. A waiver on an
  unchanged drawing is not a waiver — reporting it as one would put a human's
  name on a decision they never made and would make "somebody took
  responsibility for a change" indistinguishable from "nothing changed".
- **Geometry approval asks the question and stores the answer.**
  `POST /api/proposals/{symbols,footprints}/{id}/approve` takes
  `{recheck_required, note}`; `GET …/material-diff` supplies the pre-answer the
  dialog shows. A body-less approval (older client, bulk path) leaves
  `recheck_required` NULL, and the fingerprint comparison then decides — the
  same answer the dialog would have suggested.
- **Nothing is blocked.** No export refuses and no run is gated; the state is a
  badge (user decision). If that ever changes, change it at a call site —
  `services/signoff.py` stays a pure record.
- **`material_sha` is a derived cache**, stamped at version creation
  (`geometry_proposals`, `importer`) and backfilled in a background thread from
  `main.py` startup. It is safe for it to be missing: an un-fingerprinted
  version blocks a carry rather than granting one.
- Jaravis gets READ access only (`list_signoffs`, plus `production_signoff` on
  `get_component`). A production check is a human act and there is no draft to
  gate a robot's version of it.
- **First human sign-off promotes `in_design` -> `released`**
  (`signoffs._promote_on_first_sign`) — the ONE automatic lifecycle
  transition. Deprecated/obsolete are never touched by it.

## The review record (`services/review.py`, user design 2026-08-23)

Publishing and reviewing are separate axes. Versions publish immediately; the
review axis records who verified each version against its documentation.

- **`review_records`** — append-only, CUMULATIVE, polymorphic
  (`subject_kind` + `subject_version_id`, like `Comment`). Each record stores
  the FULL merged item snapshot; the effective record of a version is simply
  the newest non-revoked one. Items carry per-item provenance
  `{actor, actor_type, at}` with the tier rule machine < agent < human
  enforced at write time (`record_check`) — a lower tier never overwrites a
  higher tier's answer. `items=None` = a one-click human confirmation.
- **States are DERIVED, never stored** (`state_from_record`): `unreviewed` |
  `failed` (a machine item failed) | `partial` (items still unanswered) |
  `checked`. A component's effective state is the WEAKEST of its own record
  and its pinned symbol/footprint records (`component_effective` /
  `states_for_components` — always the bulk variant on list surfaces).
- **Checklists** (`checklists` + `checklist_versions`,
  `services/checklists.py`): seeded from code on first start, resolved per
  subject (base for the kind + category-scoped merges), items keyed stably.
  A human UI save publishes a version directly; the agent never edits
  checklists. The editor is `web/src/pages/Checklists.tsx`
  (`/reviews/checklists`), and four rules hold it up:
  - **`GET /api/{kind}/{id}/preview.svg?v=<version_id>`**: `v` is a CACHE KEY,
    never a selector — it always renders the CURRENT drawing. It exists so the
    URL changes when the drawing does; a matching `v` gets
    `immutable, max-age=1y`, a missing or stale one gets `no-cache`, and
    `X-Version-Id` always reports what was rendered. Before this the URL was
    version-agnostic and a pushed footprint kept showing its old picture.
  - **The agent worklist** (`review_requests`, endpoints under
    `/api/reviews/requests`): the user queues subjects from the Reviews page,
    the agent reads them with the `get_review_worklist` tool, and
    `record_check` marks a subject's open requests done the moment ANY
    verification lands on it — whoever wrote it. Requests gate nothing and
    carry no content; done rows are kept, never pruned ("when did I ask" is
    cheap to answer). `POST /api/reviews/confirm-agent` is the other half:
    one human gesture writing the same one-click confirmation "Mark checked"
    writes, over every subject whose effective state is checked with agent
    provenance — for a component that is its OWN record's provenance, not the
    aggregate, so confirming a part never silently vouches for an unchecked
    footprint.
  - **The queue ranks by leverage.** `GET /api/reviews/queue` returns
    `used_by` per template (live components pinning it) because 18 failed
    symbols were dragging 159 components (measured 2026-08-24) and a
    state-sorted list hid it; `?snapshot_id=` scopes the whole queue to one
    snapshot's BOM and the drawings it pins (review-before-build). Health adds
    `failing_keys` (machine failures + flags grouped by checklist key — the
    work-plan view), `na_reasons` and `legacy_skipped_items`, all counted over
    EFFECTIVE records only, so the numbers cannot drift from the queue.
  - **A one-click confirmation stores `items=None`, and the card must not read
    its answers off it.** That sentinel is what makes `state_from_record`
    return a full check without measuring completeness, so it cannot be
    repopulated — a subject the person vouched for while an item was still
    unanswered would flip back to partial. But `_detail` read the per-item answers from the effective record
    alone, so pressing **Mark checked** blanked the whole checklist and threw
    away the visible evidence of what the machine and the agent had verified
    (user report 2026-08-25). The state still comes from `effective_record`;
    the ITEMS come from `review.itemised_record`, the newest non-revoked record
    that has a breakdown, and `items_carried` tells the card to say so rather
    than crediting those answers to whoever pressed the button.
  - **The WRITE path still has the other half of that bug** (found 2026-08-25,
    not yet fixed). `itemised_record` repaired reading; `record_check` still
    builds its new snapshot by carrying from `effective_record`. So when the
    newest record on a version is a one-click confirmation, writing ONE item
    carries from `items=None`, inherits nothing, and the new record becomes the
    only answer — silently discarding every per-item answer underneath it.
    Reproduced on `PESD1CAN,215`: a single `cmp.datasheet_text` answer took it
    from 12 answered items to 1, with the 12 recoverable only from a snapshot
    taken earlier in the session. `carried_from_id` pointed at the one-click
    record, which is the tell. The fix is for `record_check` to seed from
    `itemised_record` rather than `effective_record`; until then, never record a
    partial item set on a subject whose latest record is a one-click human
    confirm — read the checklist first and re-send every answer it already has.
  - **Adding an item to a base checklist un-answers it on every existing
    subject, and nothing backfills it.** `machine_check_on_publish` is the only
    caller of `validator.validate`, and it runs inside the publish transaction —
    there is no endpoint that re-runs the validator on an already-published
    version. So publishing checklist v2 with `cmp.datasheet_text` (2026-08-25)
    moved all 418 components from checked to partial at once, and the only ways
    out are a mass republish, which would drop every agent answer, or answering
    the item by hand. It was backfilled by hand from the `text_layer` column the
    validator itself reads. Before adding a machine item to a base checklist,
    decide who answers it for the existing rows.
  - **Re-answering an item keeps what it replaced** (`superseded` on the entry).
    Accepting a flag used to mean deleting the only description of the defect,
    so the answer being overwritten is kept on the new entry, and `_notable`
    makes a real finding (`flagged`/`failed`) outlive any number of later
    routine re-checks. `_detail` must include `superseded` in the projection it
    builds for `answered` — a fixed key list there is exactly what hid it the
    first time.
  - **A skip may carry a structured `reason`** (`html_datasheet`,
    `no_document`, …) — `record_check` stores it skip-only, capped at 40
    chars; the ReviewCard offers the presets. Free text stays in `note`.
  - **`machine: true` is a claim about `services/validator.py`, not a wish.**
    `validator.MACHINE_KEYS` is the registry of keys that module answers, per
    kind; `GET /api/checklists/meta` serves it, the editor greys the flag out
    for anything else, and `_validate_items` refuses it. An item flagged
    machine that nothing answers can never be answered by anyone — it pins
    every subject of that kind at "partial" for ever.
  - **A review record snapshots the RESOLVED list it was measured against**
    (`ReviewRecord.checklist_items`, startup-migrated). Before it,
    `checklist_version_id` named the base version alone, so a category-scoped
    item was expected while a check was being written and forgotten on the next
    read — an unanswered one silently upgraded the state from partial to
    checked. `_checklist_items_of` prefers the snapshot and falls back to the
    pinned base version for older rows; the carries copy it. Never re-resolve
    from the current checklists on read, or editing a checklist would rewrite
    the state of every past check.
  - **`GET /api/checklists/resolve?kind=&category_id=`** returns the merged list
    with a `from` per item, which is the only honest way to look at a
    category-scoped list — it MERGES on top of the base one rather than
    replacing it.
  - **Only ONE base list per kind is ever read**, and symbols and footprints
    carry no category — so `create_checklist` accepts a CATEGORY-SCOPED
    COMPONENT list and nothing else, and refuses a second list for a category
    that already has one. Anything else would be created, listed, edited and
    never reach a verification. Deleting is category-scoped for the mirror
    reason: a base checklist would leave its kind with nothing to answer. Past
    verifications are safe either way because of the snapshot above.
  - `save_checklist` / `create_checklist` call `db.expire_all()` before
    re-reading. Without it the response described the checklist as it was
    BEFORE the save (`version_no: null`, zero items, the new row missing from
    the history) while the save itself had landed — the same
    `expire_on_commit=False` trap as `services/repoint.py`.
- **The machine tier** (`services/validator.py`) runs inside every publish
  (`machine_check_on_publish`, never raises): the old YAML validator's
  footprint style/dimension checks, symbol basics, component property rules
  (consuming `M.Rule` global defaults) — plus **`fp.model3d`: a missing 3D
  model FAILS the check** and stays failed until a human/agent marks the item
  `na` in a follow-up. Machine items answer `checked|failed|na`, never
  `na`; `failed` is machine-only, and the machine is exempt from the `na`
  reason rule below. Agents/humans additionally have
  **`flagged`** (verified and found WRONG, deliberately not fixed — note
  required, enforced in `record_check`): it ranks like `failed` (state
  "issues") and feeds the second-pass worklist
  (`reviews.flagged_worklist`, surfaced on the health panel). Review-only
  passes use it instead of editing.
- **There is no `skipped`, since 2026-09-13** (decision
  [0011](../decisions/0011-retire-the-skipped-verification-result.md)). It meant
  "applies, but I could not verify it" and read to everybody as "does not
  apply", which is `na`'s job. An item nobody can verify is now LEFT UNANSWERED,
  producing the same `partial` state `skipped` always did. The measurement that
  settled it: 138 stored skips, every one with reason `unstated`, holding 45
  subjects at `partial` — 38 of them with nothing else open, and most notes
  saying only that a datasheet was out of scope for that pass. Stored rows keep
  the value, are read as unanswered, and are reported as `legacy_skipped_items`
  so the open work stays visible; nothing was migrated.
- **`na` requires a reason code above the machine tier** — `feature_absent`,
  `kind_exempt`, `waived` or `other` (`review.NA_REASONS`). `na` is the answer
  that CLOSES an item, so it is the one that has to justify itself, and a code
  aggregates where 84 free-text notes do not. The machine tier is exempt:
  `services/validator.py` answers `na` in a dozen places ("no SMD pads", "no
  vias") with a note and no code, and requiring one would fail every publish.
- **A check may answer a key the checklist does not define** — a custom item,
  recorded on that ONE subject. The agent could always do it (any key reaches
  `record_check`); the review card can now too, and both must send the item's
  `text`, because the record is the only place that wording will ever live —
  `record_check` blocks a textless unknown key rather than storing a bare key
  nobody can read. Custom items count in the state exactly like checklist items
  (`state_from_record` measures `total` as `max(expected, answered)`), and
  `_detail` returns them as `extra_items`. Adding one does NOT touch the
  checklist document, which is the point: it says "this part needed this
  check", not "every part does".
- **Carries mirror the sign-off carry**: equal `material_sha` or
  `recheck_required=False` (the minor-change waiver, settable at publish time
  via `minor_change` on the geometry tools/paste box) clones the record onto
  the new version as kind `carry`; component data changes are judged by
  `signoff.data_carries`. Repoints therefore keep verifications on
  silk-only edits and strip them on pad moves.
- **`Component.lifecycle_state`** (`in_design|released|deprecated|obsolete`):
  usage fitness, separate from review state. `deprecated`/`obsolete`
  (`mirror.HIDDEN_LIFECYCLE`) are excluded from the generated symbol libs AND
  both `kicad_http` part endpoints — platform-only. Changed via
  `PATCH /api/components/{id}/lifecycle`, which rebuilds the mirror when
  visibility flips.
- **The `7S Version` field** (`generator.version_prop`, "c5 s3 f7") is
  injected into every emitted symbol (mirror + HTTP catalog), lands on placed
  schematic symbols, and is read back at ingest into
  `SnapshotBomLine.lib_version` (BOM export field `7S Version` → label
  `LibVersion` — `project_ops.BOM_FIELDS`, BOTH copies). It answers "which
  library versions was this board drawn with" from the committed source.
- **`snapshot_reviews`** — the end-of-design record
  (`POST /api/projects/{id}/review/complete`), storing per-component states
  at completion so a later run can say "3 components changed since the
  review". `routers/reviews.py::snapshot_review_issues` is the ONE
  implementation both the project Review tab and the run-creation gate use.
- **The run-creation gate WARNS, it never blocks**: `create_run` answers 409
  `{review_warning: true, …}` for a snapshot with unsigned/unreviewed/
  deprecated parts, changes since the last review, or no completed review;
  re-posting with `ack_review=true` proceeds and audits
  `production.review_ack`. Everything else stays reporting-only.

