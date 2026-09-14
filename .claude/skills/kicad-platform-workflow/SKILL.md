---
name: kicad-platform-workflow
description: "How changes become library: every write publishes immediately (no draft gate, no Proposals view), a publish regenerates the KiCad libraries and file mirror with no manual build, geometry publishes repoint the components on them, which changes carry a verification across a new version and which strip it, what mirror warnings mean, where the retired YAML pipeline went, and who handles platform setup. Use when asked how to publish, rebuild or regenerate."
---
<!-- platform-skill: platform-workflow v11 — source of truth is the platform; check with list_skills, refresh with get_skill -->
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

Every published version starts a verification trail.

1. **Machine** — the automatic checks. They are **worked out when something
   asks, not recorded on publish** (changed 2026-09-14). Edit a check and the
   whole library re-reads itself; nothing has to be re-run and there is no
   button to press. So do not try to refresh them, and do not answer them: they
   answer themselves, on every read, from the live checklist.
2. **Agent** — after publishing, verify against the documentation.
   `get_review_checklist` returns the resolved checklist with everything already
   answered, and marks each item so you can tell what is left for you.
   `record_verification` records your answers.
3. **Human** — the user works the **Reviews** queue and the per-component card,
   and separately signs off parts for production. The first human sign-off
   promotes a component's lifecycle to `released`.

### What you may answer, and what each answer means

| Result | Means |
|---|---|
| `checked` | You compared it against the documentation and it is correct. |
| `flagged` | You verified it and it is WRONG, and you are not fixing it. The note is required and IS the second-pass worklist entry. |
| `na` | This check is not about this part. **It is a standing exception, not an answer on this version.** |

**An item you could not verify is LEFT OUT entirely.** Do not send it. It keeps
the version at `partial`, which is the honest state. (`skipped` was retired on
2026-09-13: it meant "applies, but I could not verify it", everybody read it as
"does not apply", and agents used it to mean "I did not re-open the PDF on this
pass" — which parked 38 subjects at partial for no reason. Stored rows keep the
value and are read as unanswered.)

**`na` outlives the version.** Since 2026-09-14 it does not write an answer: it
records a standing exception on the PART, pinned to the drawing or to the
component's own data, so it survives the next publish and dies only when the
thing it was granted against changes. It needs a reason code —
`feature_absent`, `kind_exempt`, `waived`, `other` — **and a note**. An agent
can never grant one that holds for every future version; only a person can, from
the review card, where the scope is asked explicitly.

Never reach for `na` to get rid of a question you could not answer. It closes
the item for everybody who comes after you.

### Keep every note short

A note is capped at **400 characters** and a custom item's own text at 200; the
overall note on a pass is capped at 300 and is a CITATION of what you read, not
a summary of the findings. An over-long note is refused and comes back in
`blocked_items`, so the answer is lost.

Measured before the cap: a person writes 31 characters in a note, an agent's
median is 367 and the longest in the library was 3,316 — about 500 words on one
checklist item. Nobody reads that, so the finding inside it is lost anyway. Say
what you compared, what you found and where: *"pad pitch 0.5 mm, datasheet p4
table 2 says 0.65 mm"*.

### Not every check applies to every part

The resolved checklist reports three groups, and they mean different things:

- **items** — what this subject is measured against.
- **switched_off** — the owner decided this check does not apply here. Not your
  work; do not re-raise it.
- **inapplicable** — the check is not ABOUT parts like this one, because its
  `when` predicate does not match. Also not your work.

### A failure is not always a defect

Every check carries a severity. A **warning**-level failure is shown and counted
and never makes a part read as failed — that is what lets a new check ship at
all. An **error** does. `ignore` means the check does not run here.

### The state is three facts, not one word

`conforms` is what the code can see; `judged n of m` is what a person or an
agent has confirmed; sign-off is separate again. The single word — `unreviewed`
/ `partial` / `checked` / `failed` — is the aggregate a list sorts by, and a
component's is the WEAKEST of its own and those of the symbol and footprint it
pins. An item closed by a standing exception LEAVES the denominator: an
exception says the question is not about this part, never that somebody looked.

**Carry rules:** a new version that changes nothing reaching the board (equal
material fingerprint), or whose change was explicitly waived as minor
(`minor_change=true` on the geometry tools — ONLY for genuinely cosmetic
cleanups), inherits the previous verification and sign-off. Anything else starts
unreviewed again, on purpose.

**The fingerprint is computed for you, so do not reach for `minor_change`
first.** The platform hashes the subset of a drawing a fab or a netlist acts on
and compares it with the previous version. Redraw only decoration and the
verification carries by itself, with no waiver and nobody's name on one.

| | Included — changing it strips the review | Excluded — changing it carries |
|---|---|---|
| Footprint | every pad's number, type, shape, position, rotation, size, drill, layer set, margin overrides and custom primitives; the courtyard outline; the `attr` flags | `F.SilkS` / `B.SilkS`, `F.Fab` / `B.Fab`, `*.User` graphics and text; `descr`, `tags` and the footprint's `property` fields; the `model` line; every `uuid` |
| Symbol | the pin set — number, name, electrical type, graphic style (`line` vs `inverted`), position, rotation, length, hidden flag, alternates, unit | the body outline, field text and field positions; every `uuid` |

Two consequences worth holding on to. Removing a pin-1 circle, moving a
reference designator or swapping a 3D model carries the verification
automatically — observed on `LMR43620R5` v2, 2026-08-27, published with
`minor_change=False` and still `checked`. And a pin turning from `line` to
`inverted` does NOT carry, because it changes what the schematic claims about
the part.

`minor_change=true` exists for the case the fingerprint cannot judge — a
material change you are asserting is not worth a re-check. It is a waiver with
your name on it, not a shortcut.

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

### When a user's KiCad sees it

The platform side is done at the publish. The user's side has three clocks, and
none of them needs a KiCad restart (decision record 0006 in the repo,
2026-09-10):

- **The HTTP catalog** — part records, fields, `7S Version`, the footprint a
  part names — refreshes inside KiCad every 2 minutes. KiCad 10 re-fetches it
  in a background thread; no menu action, IPC command or plugin can force it,
  so "publish, then wait up to two minutes" is the honest answer.
- **Base symbols, footprints and 3D models** arrive when the user presses
  **Sync 7Sigma Library** in the PCB editor. The sync writes only what changed,
  fetches 3D models as a per-file delta, and records the two content packages
  in KiCad's Plugin and Content Manager as current and pinned — the PCM is for
  installing once and for updating the Sync plugin itself, never for library
  updates. KiCad re-reads a changed library file on its next use.
- **Parts already placed** on a board or schematic are copies. They change only
  through Tools → Update Footprints / Symbols from Library, and nothing on the
  platform can do that for the user.

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

**Use it sparingly, and look first.** Measured 2026-09-14: the library carries
**251 distinct custom keys**, most of them used exactly once, every one written
by an agent. They accumulated because there was nowhere durable to record a
finding — a waiver died with the version, so people invented a private key
instead. That is fixed: a decision goes in a standing exception and a defect
goes in `flagged`, both of which outlive the version and both of which somebody
can find again. A custom key is for a real check the checklist has no key for,
and when you write the third one of the same shape, say so in your report
instead: it is a check that should exist.

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
| **Deployed** | `https://disfunction.cc/lib` | The instance to use. Always on, **on the public internet**, served under the `/lib` path prefix by a shared nginx. |
| ↳ same box, LAN route | `http://192.168.200.28/lib` | The SAME deployment reached over the local network. Not a second instance. |
| Dev | `http://localhost:5173` (API on `:8020`) | A working copy on a developer's machine, sources live-mounted so edits hot-reload. |

**The two deployed addresses are one server, and only the first one counts.**
Verified 2026-08-27: both answer, both return the same seven skills at the same
versions and the same component rows. But `PUBLIC_BASE_URL` is
`https://disfunction.cc/lib`, and every URL the platform *generates* is built
from it no matter which route you arrived by — fetching
`/api/kicad/pcm/repository.json` over `192.168.200.28` still hands back a
packages URL on `disfunction.cc`. So a personal KiCad URL, a PCM link or a
datasheet link is always the internet one. Quote `https://disfunction.cc/lib`
to users; treat the LAN address as a convenience for browsing from that network,
never as the address to hand out.

**It is on the internet, so the access rules are not optional.** This document
said "reachable from the local network only" until 2026-08-27, which was wrong
and is the sort of wrong that changes how someone reasons about exposure. The
API is default-deny: a browser needs a session and every machine client needs a
personal API token. Accounts are created by an admin on the Setup page — there
is no sign-up and no password recovery.

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
