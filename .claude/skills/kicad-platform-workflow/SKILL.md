---
name: kicad-platform-workflow
description: "How changes become library: every write is a draft proposal, approval automatically regenerates the KiCad libraries and file mirror (there is no manual build), what mirror warnings mean, where the retired YAML pipeline went, and who handles platform setup. Use when asked how to publish, rebuild or regenerate."
---
<!-- platform-skill: platform-workflow v7 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Platform workflow — how changes become library

Postgres is the source of truth. Every symbol, footprint, component and skill is
a row with an append-only version history; the KiCad files people actually use
are **generated output**, never the master copy.

## Writes publish immediately — review happens on its own axis

**Every write publishes at once** — components, symbols and footprints since
2026-08-23, skills since 2026-08-24. There is no approval gate left anywhere in
the platform and no Proposals view: the tool call is the publish, the mirror and
the KiCad catalog update in the same breath, and the accountability moved to the
**review axis** described below.

| Tool | Effect |
|---|---|
| `propose_new_component` / `propose_component_edit` | publishes a component version |
| `propose_symbol_edit` | publishes a base-symbol version (new name = creation) |
| `propose_footprint_edit` | publishes a footprint version (new name = creation) |
| `propose_skill_update` | publishes a skill version — live for every later agent run |

Versions stay immutable and append-only: publishing advances a pointer, and any
earlier version can be restored, so a bad publish is reversible — publish a new
version restoring the previous content.

Skills were the last exception, on the reasoning that a bad skill steers every
future agent run. That gate is gone too: a skill is prose, its versions are
immutable, and the undo is restoring the previous version from the Skills page.
So write a skill update only when you would defend it to the next reader — you
are changing what every later run is told, with nobody between you and it.

## The review axis: machine → agent → human

Every published version starts a verification trail:

1. **Machine** — the validator runs inside every publish and records the
   mechanical checklist items (courtyard/fab/silk widths, pad shapes, drill
   minimums, property rules — and a **required 3D model**: a footprint without
   one reads `failed` until a human or agent marks the item n/a with a reason).
2. **Agent** — after publishing, verify against the documentation:
   `get_review_checklist` returns the resolved checklist merged with what is
   already answered; `record_verification` records your answers. Be honest:
   `checked` only for what you actually compared against the datasheet,
   `na` (with a reason) for items that do not apply, `skipped` (with a reason)
   for items the documentation does not let you verify, and **`flagged`**
   (note required) for an item you verified and found WRONG without fixing
   it. A flag puts the part on the "issues" list and the second-pass
   worklist on the health panel — use it for review-only passes ("go over
   the library and list what needs fixing") and for defects whose fix needs
   the user's decision. Do not silently fix AND flag — one or the other.
   You can never overwrite an item a human answered.
3. **Human** — the user works the **Reviews** queue and the per-component
   verification card, and separately signs off parts for production. The first
   human sign-off promotes a component's lifecycle to `released`.

States are derived, never stored: `unreviewed` → `partial` (skipped or
unanswered items) → `checked`; `failed` when a machine check found a violation.
A component's effective state is the WEAKEST of its own record and its pinned
symbol and footprint records. Verifications are cumulative — a follow-up (the
datasheet turned up, the checklist grew) starts from everything already
answered.

**Carry rules:** a new version that changes nothing that reaches the board
(equal material fingerprint), or whose change was explicitly waived as minor
(`minor_change=true` on the geometry tools — use it ONLY for genuinely cosmetic
cleanups), inherits the previous verification and sign-off. Anything else
starts unreviewed again, on purpose.

**Lifecycle:** each component carries `in_design` / `released` / `deprecated` /
`obsolete`. Deprecated and obsolete parts stay fully visible on the platform
but are hidden from KiCad (chooser and generated libraries). Only the
in_design→released transition is automatic (first human sign-off).

## Publishing regenerates everything automatically

There is **no manual build step and no pipeline to run.** A publish regenerates
the affected KiCad symbol library and refreshes the file mirror in-process.
Every emitted symbol carries a hidden **`7S Version`** field ("c5 s3 f7" =
component / symbol / footprint version numbers), so a schematic committed to
git records exactly which library versions the board was drawn with.

Regeneration reports **mirror warnings** rather than failing. The usual one is
`unresolved template {Key}` — a `ki_description` referencing a property the
component doesn't carry. The publish still lands; the warning means the
generated description is wrong and the component needs a follow-up edit
([[add-component]]).

## Geometry publishes also repoint the components

A `ComponentVersion` **pins** the exact symbol and footprint version it was
drawn against. Publishing new geometry therefore also publishes a repoint
version for every part that uses it — properties untouched, pins moved — listed
under `repointed` in the response. The carry rules above decide whether each
part keeps its verification and sign-off (a silk tweak keeps them; a moved pad
strips them and the part shows up in the review queue). A component still
carrying an unfinished draft from before the gate was removed is skipped, and
named in `repointed.skipped`.

A part left pinned to a superseded drawing is visible on its component page:
the pinned version reads "library serves v5" beside it. That is what a repoint
prevents.

### A check the checklist never thought of

`record_verification` accepts a key the checklist does not define — use
`custom.<slug>` and include a `text` saying what you checked (without the text
the item is refused, because the record is the only place that wording lives).
It is recorded on that ONE part and does not change the checklist every other
part is measured against. People can add the same thing from the review card in
the web UI.

## Production runs warn, they never block

Creating a production run from a snapshot with unsigned, unreviewed or
deprecated components — or one whose design review was never completed in the
project's Review tab — answers 409 with the list; the user confirms explicitly
and the acknowledgement is audited. Nothing else is ever gated on review state.

## Where the old YAML pipeline went

The library used to be generated from `Sources/*.yaml` by a script at the repo
root. That pipeline is **retired** — it lives with its full history on the
`archive/yaml-library` branch. Postgres is the source of truth now. Don't tell
anyone to run `main.py`, edit YAML sources, or regenerate from files; those
instructions are stale.

One import endpoint still exists for a clean cutover: `POST /api/import` is
**destructive** (wipes and reloads everything from YAML, writing rows directly
as published). Treat it as off-limits unless the user explicitly asks for a full
reload. `POST /api/import/sync`, which used to file draft proposals, answers
**410**: with no approval path left, it would only write rows nobody could act
on.

## Running the platform itself

Setting up, configuring, or hosting the platform is a shell task, outside what
the library tools cover. Jaravis has no shell, no filesystem and no Python
environment — it acts only through its tools, so installation and deployment
questions belong with the platform README or an administrator, not in chat.

There are two places it runs, and they are not interchangeable:

| | Address | What it is |
|---|---|---|
| **Deployed** | `http://192.168.200.28/lib` | The instance to use. Always on, served under the `/lib` path prefix by a shared nginx, reachable from the local network only. |
| Dev | `http://localhost:5173` (API on `:8020`) | A working copy on a developer's machine, sources live-mounted so edits hot-reload. |

The deployed instance is **not** built from a checkout. Container images are
built by CI on every push and it pulls them, so `docker compose up --build` is
not how a change reaches it — the images have to be rebuilt and pulled first.
Note the `/lib` prefix: every URL it serves carries it, including the KiCad HTTP
catalog, the PCM repository and datasheet links.

**Configuration is editable in the web UI** — Setup → Configuration, the first
card on the page. A saved value is stored in the database and wins over the
environment; Revert drops it again. Values that are only read when the app
starts are labelled, because saving one needs a restart to take effect.
Infrastructure is deliberately absent: the database URL, the object-storage
credentials and `SECRET_KEY` cannot be changed under a running platform, the
last one because it decrypts stored git tokens and a new value would orphan
them. So "where do I change the public base URL, a token, or an API key" is
answered by the Setup page, not by a file on disk.

An agent that does have a shell and the repository runs the dev copy with
`docker compose up -d`; read the repo's `CLAUDE.md` files before changing
platform code.

## Related

[[add-component]] — the procedure that produces these publishes.
[[conventions-symbols]] / [[conventions-footprints]] — what a good version looks like.
