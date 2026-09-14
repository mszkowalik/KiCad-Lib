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
  - **The WRITE path had the other half of that bug** (found 2026-08-25, fixed
    2026-09-14). `itemised_record` repaired reading, but `record_check` still
    built its new snapshot by carrying from `effective_record`. So when the
    newest record on a version was a one-click confirmation, writing ONE item
    carried from `items=None`, inherited nothing, and the new record became the
    only answer — silently discarding every per-item answer underneath it.
    Reproduced on `PESD1CAN,215`: a single `cmp.datasheet_text` answer took it
    from 12 answered items to 1. `carried_from_id` pointed at the one-click
    record, which was the tell.
    **`record_check` seeds from `itemised_record` now.** The STATE still comes
    from `effective_record` — `state_from_record` reads the `items=None`
    sentinel as a full check — and only the ITEMS come from the newest record
    that has a breakdown, which is the same split `_detail` makes for display.
    Verified: three answers, then Mark checked, then one more answer leaves four
    recorded, where it used to leave one.
  - **Adding an item to a base checklist un-answers it on every existing
    subject.** Publishing checklist v2 with `cmp.datasheet_text` (2026-08-25)
    moved all 418 components from checked to partial at once, because
    `machine_check_on_publish` ran only inside the publish transaction and
    nothing could re-run it. That one was backfilled by hand from the
    `text_layer` column the validator itself reads.
    **Since 2026-09-13 there is a re-run** (decision
    [0013](../decisions/0013-the-validator-owns-the-automatic-checks.md)):
    `POST /api/reviews/{kind}/{id}/recheck` for one subject and
    `POST /api/checklists/{id}/apply` for every subject a list governs, both
    through `review.recheck_machine_tier`. It answers the MACHINE items only, so
    it backfills a new automatic item and does nothing for a new judgment one —
    before adding a judgment item to a base checklist, still decide who answers
    it for the existing rows.
  - **Re-answering an item keeps what it replaced** (`superseded` on the entry).
    Accepting a flag used to mean deleting the only description of the defect,
    so the answer being overwritten is kept on the new entry, and `_notable`
    makes a real finding (`flagged`/`failed`) outlive any number of later
    routine re-checks. `_detail` must include `superseded` in the projection it
    builds for `answered` — a fixed key list there is exactly what hid it the
    first time.
  - **A machine item carrying a FINDING is answerable by hand** (2026-09-13).
    The card hides the Checked / N/A / Flag buttons on `machine: true` items,
    because the validator owns them — but a `failed` or `flagged` answer is a
    worklist entry addressed to a person, so those two open the buttons. The
    gate used to name `failed` only, which left an agent's `flagged` on a
    machine key read-only: `cmp.datasheet_text` reaches that state on any part
    whose archived PDF is partly image-only, and nothing in the UI could
    accept, waive or re-check it. The backend never forbade it — the tier rule
    lets a human answer over an agent on any key. A machine item nobody has
    answered YET is still read-only in the card; see the backfill trap above.
  - **A skip may carry a structured `reason`** (`html_datasheet`,
    `no_document`, …) — `record_check` stores it skip-only, capped at 40
    chars; the ReviewCard offers the presets. Free text stays in `note`.
  - **`validator._CHECK_SPECS` is the CATALOGUE of automatic checks, and the
    checklist says which of them run AND what they run against** (decisions
    [0013](../decisions/0013-the-validator-owns-the-automatic-checks.md) and
    [0014](../decisions/0014-a-check-carries-its-own-configuration.md)). A spec
    carries a key, a text, an optional hint and the check's `params` with their
    defaults; `MACHINE_KEYS` is derived from it and
    `validator.machine_checks(db, items, kind)` words each check with the
    parameters it will actually run with. `GET /api/checklists/meta` serves it
    and `_validate_items` REWRITES a machine item's text and hint from it on
    every save, from the item's OWN `params` — so an automatic item can no
    longer describe a rule the code does not apply, in either direction.
    `_validate_items` still refuses `machine: true` on a key the module does not
    answer: such an item can never be answered by anyone and would pin every
    subject of that kind at "partial" for ever.
  - **`params` on an item is that check's configuration, and it is the ONLY
    home for one** (2026-09-14). It used to be a `rules` table: one global JSON
    block holding the numbers for eleven different checks, plus fifteen
    per-category rows **nothing ever read**. Four things the move buys: a
    setting sits beside the switch of its own check; it versions with the
    checklist and carries the comment saying why it changed; it lands in
    `ReviewRecord.checklist_items`, so a past verification says what it was
    measured against; and a CATEGORY states its own by putting the item on a
    category-scoped component checklist, which `checklists.resolve` already
    merges — no second merge engine. `models.Rule` is dormant history and
    `checklists.migrate_rules_onto_items` folded it in, reporting the keys
    nothing consumes rather than dropping them.
    **The default's TYPE is the parameter's type**, and
    `routers/reviews._clean_params` validates against it: a positive number, a
    switch, a name, a list of property names, or property -> regular expression
    (compiled on save — a pattern that does not compile would fail every part
    carrying the property and name no cause anybody could act on). A threshold
    is checked there rather than where it is used, because a nonsense one would
    make its check PASS silently, which is the one failure mode a validator must
    not have.
  - **`when` on an item says which SUBJECTS the check is about** (2026-09-14,
    decision [0015](../decisions/0015-a-check-says-which-subjects-it-is-about.md)).
    `{field: pattern, …}`, every entry ANDed, each value a regular expression
    over one fact from `checklists.subject_facts` — a bare name is a component
    property, a `$` name is one of `checklists.FACTS` and is validated on save.
    It **NARROWS an already-resolved item; it never selects one.** That is the
    whole design: a selecting predicate would let two items claim one key, and
    predicates have no natural order to break the tie the way a category path
    does, so every resolution is bad — refusing overlap fails on regexes, an
    explicit precedence makes "why did this part get that rule" unreadable, and
    per-variant keys destroy the key as an identity. Narrowing keeps one item
    per key and only removes it.
    Three rules that are easy to get backwards: a fact that is ABSENT never
    matches (so `comp_type: ^TVS$` excludes a part carrying no `comp_type`);
    `facts=None` means every item applies, which is the editor describing a
    category rather than judging a part; and a pattern that does not compile
    matches NOTHING, because a check quietly not applying is recoverable and one
    quietly applying to the whole library is not.
    `resolve` returns it in a third bucket, **`inapplicable`**, which must never
    be folded into `disabled` — "not about parts like this one" and "the owner
    switched it off here" are different statements about different people's
    decisions, and `_detail` reports them separately for that reason.
    **A predicate over a PROPERTY is only as stable as that property.** A
    category is a row; `comp_type` is free text, and the library already carries
    the `ZENNER` spelling the skill flags. An edit there silently stops a check
    running, with no failure and no warning. `$` facts do not have this problem.
  - **The FACT VOCABULARY is the extension point; the assertion vocabulary is
    closed.** `checklists.FACTS` is one table of `{name, kinds, what, lazy}`,
    published by `GET /api/checklists/meta` so the editor offers exactly what
    the subject in hand carries — a footprint rule is never offered
    `$category`. A comparison BETWEEN two facts belongs in a derived fact, in
    Python (`$pins_without_pads`), never in a boolean assertion: the moment an
    assertion can name two facts it has become a rules language, which is what
    `models.Rule` was.
    A symbol and a footprint carry their own drawing facts as of 2026-09-14.
    Before that they carried `$kind`, `$name` and a fingerprint, so a footprint
    checklist could not say "this rule is about quad packages" and every
    geometry rule stayed prose in a skill.
    Three traps these facts cost a bug each:
    **`FootprintVersion.parsed` is not the material parse.** It carries no pad
    position and no drill, and it counts paste apertures as pads — a
    QFN-16-1EP reads as 26. Every geometry fact goes through
    `material.footprint_material(source_text)`; `$footprint_pad_count` is
    DISTINCT numbered pads, which is 17 for that part.
    **KiCad Y points DOWN, which inverts the shoelace sign.** The correct
    counter-clockwise quad trace sums NEGATIVE. Getting it backwards reports
    every correct QFN as mirrored.
    **A pad on an axis has no corner.** A two-pad chip sits at y = 0, so a
    `y < 0` test invents "bottom-left"; `_corner_of` reports `left`.
  - **Several items may share a key as named VARIANTS, and the constraint is
    what removes the ordering question.** `variant: "NMOS"` is the identity
    (stable under reordering, which an index is not) and the label — the editor
    reads `Transistors.NMOS` from it. A key with several variants must
    discriminate on ONE field with distinct literal values, plus at most one
    variant with no `when`, the fallback
    (`routers/reviews._check_variant_groups`). At most one literal can then
    match and the fallback is last by RULE, so `checklists.pick` never consults
    order. Get this backwards and two defects come with it: a table sorted by
    key would show variants in an order contradicting the effective one, and
    "is this variant reachable" would be undecidable instead of decidable.
    A compound predicate stays legal on a SINGLE-item key, where no ordering
    question exists.
    **A more specific list REPLACES a key's whole group** — a category states
    the complete set; to add a special case while keeping the general rule,
    switch the general one off and add a new KEY. **A disabled variant falls
    THROUGH to the next**; disabling every variant is what switches the check
    off. `inapplicable` names a key only when nothing in its group matched —
    listing the other variants would put an "n/a here" row on every card for
    every varied key.
    **`GET /api/checklists/coverage` is the mitigation for keying on free
    text**: it runs a key's discriminator over the live parts in scope and
    returns the split. A non-zero `no_match` on a settled category means the
    discriminator is not reliable, and that category wants a subcategory rather
    than a predicate.
  - **`severity` says what a FAILURE means, and `ignore` is also how a scope
    switches the check off** (2026-09-14, decision
    [0016](../decisions/0016-severity-and-standing-exceptions.md)). One control
    with three values — `error` / `warning` / `ignore` — not a switch beside a
    severity. `checklists.severity_of` still READS the retired `disabled: true`,
    because a checklist version is immutable and rewriting one would change what
    a past verification was measured against; `migrate_severities` converted the
    stored rows and turned the four seeded-OFF checks into warnings, which is
    what "off" was standing in for.
    **The severity is stamped on the ANSWER** when it is written, never read
    back from today's checklist — otherwise a checklist edit would silently
    rewrite what a past record means. `state_from_record` counts warning-level
    failures separately and they never make a subject `failed`, which is the
    only reason a new check can ship at all: `cmp.datasheet_text` moved 418
    components to partial in one publish.
  - **A STANDING EXCEPTION outlives the version** (`services/exceptions.py`,
    `review_exceptions`). `subject_id` is the PART, never a version — that is
    the whole change. The library held ZERO waivers while agents had invented
    188 `custom:` keys, because a waiver was an answer on one version and a pad
    move took it away.
    `depends_on` is KiCad's `drc_exclusions` idea: the exception names the facts
    it was granted against and is live while every one still holds. `{}` is
    "this part, always"; `{"$material_sha": …}` is "this drawing only". **The
    scope is asked, never inferred** — a blanket waiver silently covering a
    future edit is the failure it exists to prevent — and pinning a fact the
    subject has not got is refused rather than producing an exception that is
    stale the instant it is written. A fact that can no longer be READ counts as
    changed.
    It is applied in **one** place — `conformance.evaluate`, as an overlay, for
    machine and judgment items alike — so validator, agent and card are covered
    together, and the finding it replaces is kept in `superseded`. Nothing is
    written: granting and revoking both take effect on the next read. (0017 left
    judgment items on a write path inside `record_check`, and the result was
    that granting one on an item nobody had answered did NOTHING until some
    unrelated save ran — measured: `fp.model_fit` granted, item still open, 0/6
    answered. 0018 moved them here too.)
    **Grant one from the check itself**: every judgment row and every machine
    FINDING carries a `Does not apply…` button, outside verify mode, which asks
    the reason, the note and the scope in that order. It needs no verify mode
    because it stages nothing. The standing decisions on a subject list ABOVE
    the checklist fold, each with its own `Revoke exception`, because a decision
    you cannot find again is one nobody trusts.
  - **Thresholds are library-wide; property rules are per category.** That is a
    property of the SUBJECTS, not a limitation: a footprint and a symbol carry
    no category (`_category_of` returns None), one footprint is shared across
    categories, and a footprint nothing uses yet resolves to no category at all,
    so a per-category drill minimum could never be applied at the moment the
    check runs. A component has a category, so `cmp.*` parameters vary freely.
  - **`disabled: true` on an item means OFF at this level and below**, and it is
    the only thing that makes the merge subtractive. `checklists.resolve` returns
    `items` (what the subject is measured against) and `disabled` (what a list on
    the path switched off); a more specific list wins either way, so a category
    item WITHOUT the marker switches a base item back on. Three consumers, and
    all three are needed or "off" means nothing: `state_from_record` must not
    expect a disabled item (it is absent from the snapshot),
    `machine_check_on_publish` must not let the validator record one, and
    `record_check` DROPS a switched-off key from the merged answers — records are
    cumulative, so a `failed` recorded before the switch would be copied forward
    for ever with nothing able to clear it. That drop is destructive and
    deliberate: it takes an agent's or a human's answer on that key too, because
    "this check does not apply here" is exactly what was said. `_detail` and the
    agent's `get_review_checklist` report the switched-off keys rather than
    hiding them, so nobody re-raises one.
  - **A category-scoped switch only reaches COMPONENT checks**, for the same
    reason as the parameters above: symbols and footprints carry no category, so
    their automatic checks are switched on the base list, for every part of that
    kind at once.
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
- **The machine tier is COMPUTED, not recorded** (2026-09-14, decision
  [0017](../decisions/0017-conformance-is-computed-not-recorded.md)).
  `services/conformance.py` evaluates it on read and caches the result in
  `models.Conformance` against a **digest** of everything it depends on — the
  resolved checklist, the facts those checks actually read, and the live
  exception ids. Edit a check and every digest in the library changes, so the
  next read recomputes: nothing has to remember to invalidate anything, and a
  new check can never again move 418 subjects at once. Measured: `evaluate` is
  20 ms, a cached read is 0 ms, and the whole library is 857 rows warmed by a
  background thread at startup.
  The digest reads facts through their own KEYS, never by iterating the mapping:
  `subject_facts` is lazy, and iterating it would compute every derived fact on
  every digest.
  **A change has to WARM the cache, and a read has to PERSIST what it
  recomputed.** The digest makes the cache honest, but `cached` deliberately
  does not validate it, and until 2026-09-14 a detail read recomputed and never
  committed — so nothing outside the startup warm-up ever wrote a row. Editing a
  check on production changed no list at all until the API restarted, which is
  the opposite of what 0017 promises. A checklist save now fires
  `conformance.warm_in_background(kind)`, and the read paths commit the row they
  worked out. A GET that writes a cache row is cheap and cannot lose anything:
  the digest decides whether the row is used. Measured: revoke an exception and
  the failing-key list reports it on the next request.
  Three consequences to hold on to: `state_from_record` IGNORES machine answers
  stored in records (2,442 of them, kept as history, never deleted) and measures
  completeness over judgment items only; a one-click human confirmation can no
  longer hide a machine failure, because it vouches for the judgment and not for
  the code; and an exception is an OVERLAY applied during evaluation rather than
  a write, so revoking one takes effect on the next read.
  `machine_check_on_publish`, `recheck_machine_tier`, `POST …/recheck` and
  `POST /checklists/{id}/apply` were DELETED with it. If you find yourself
  re-adding one, ask first why a recomputable answer is being stored.
- **The checks themselves** (`services/validator.py`) once ran inside every publish
  (`machine_check_on_publish`, never raises) and on demand
  (`recheck_machine_tier`, which passes `close_requests=False` because a re-run
  verifies nothing and must not answer somebody's queued ask). Both resolve the
  checklist first and pass the enabled machine keys as
  `validator.validate(..., only=)` — an answer for a key the checklist does not
  carry would be stored as a CUSTOM item, where a `failed` still pins the subject
  at "issues", so without the filter a switched-off check would change nothing.
  Each check reads its parameters from its own resolved item
  (`validator.check_params`), falling back to the spec default. The checks
  themselves are the old YAML validator's
  footprint style/dimension checks, symbol basics, component property rules —
  plus **`fp.model3d`: a missing 3D
  model FAILS the check** and stays failed until somebody records that the part
  needs none. Machine items answer `checked|failed|na`; `failed` is
  machine-only. Agents/humans additionally have
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
- **`na` is a STANDING EXCEPTION, not an answer** (2026-09-14, decision
  [0018](../decisions/0018-does-not-apply-is-an-exception-not-an-answer.md)).
  The two said the same thing and only one of them lasted: 314 live `na`
  answers, 312 written by agents, not one with a reason recorded, every one due
  to expire at the next version bump — against ZERO rows in the table built to
  hold such decisions. The card sends no `na` at all; "Does not apply…" grants
  an exception, on ANY judgment item and on a machine finding, answered or not.
  The API still ACCEPTS `na` so no agent breaks, and `record_check` converts it:
  it needs a reason code AND a note (the answer outlives its version now), and
  it is always PINNED — `exceptions.DEFAULT_PIN`, the drawing for a symbol or
  footprint, the component's own fields for a component. Only a person can
  grant "always", in the card, where the scope is asked. The machine tier is
  untouched: `services/validator.py` answers `na` in a dozen places ("no SMD
  pads", "no vias") and those are computed, not recorded.
- **Every written explanation has a length limit, enforced at the WRITE.**
  `review.TEXT_LIMITS` (item note 400, custom item text 200, pass note 300,
  revoke reason 300), `exceptions.TEXT_LIMITS` (note 400, evidence 600, revoke
  reason 300) and `publish.CHANGE_COMMENT_LIMIT` (600). The numbers came from
  measuring what was already stored on 2026-09-14:

  | writer | notes | median | p90 | max |
  |---|---|---|---|---|
  | human | 13 | 31 | 115 | 115 |
  | machine | 1,304 | 17 | 27 | 93 |
  | agent | 19,747 | **367** | 1,055 | **3,316** |

  An agent writes twelve times what a person writes, and the tail is about 500
  words on ONE checklist item. Nobody reads that, so the finding inside it is
  lost as surely as if it had not been written — 45% of stored agent notes
  exceed the limit, which is the point of the number rather than an argument
  against it.
  **Over-long text is REFUSED, never truncated.** A truncation loses the end of
  a sentence and teaches nobody; a refusal names the actual length, the limit
  and what to write instead, and an item refused this way comes back in
  `blocked` with the rest of the save intact. The UI caps the input box
  (`PromptOptions.maxLength`, with a counter in the last quarter) so a person is
  stopped while typing rather than after saving — those mirrors live in
  `ReviewCard.LIMITS` and must move together with the server's.
- **The state is reported as THREE facts, not one word** (2026-09-14). The
  aggregate stays, because a list has to sort by something, but `conforms`
  (what the code can see), `judged n of m` (what a person confirmed) and
  `excused` are printed beside it. One word could not carry them: `partial`
  meant "nobody looked", "a question was added last week" and "one item is
  open" at once, and a subject read `unreviewed` straight after somebody decided
  every check on it. `ReviewPill` takes an optional `detail`; a DataTable row is
  one line tall and must not wrap (`web/src/components/CLAUDE.md`), so the queue
  carries the same sentence in its tooltip through `Ui.stateFacts` instead.
- **An excused item LEAVES the denominator.** `conformance.evaluate` computes
  them into `Conformance.excused` beside the machine answers, and
  `state_from_record` reports `excused` as its own number. It is never folded
  into `answered`: an exception says the question is not about this part, never
  that somebody looked, and a part whose whole checklist is excused must not
  read like a part that was judged.
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

