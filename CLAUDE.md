# 7Sigma KiCad Library Platform

Web-hosted component library for KiCad: Postgres-backed catalog with versioned
components/symbols/footprints, publish-then-review workflow, KiCad HTTP library +
PCM packages, project BOMs and production-run economics, and the Jaravis agent
(also exposed to Claude Code over MCP).

**Postgres is the source of truth.** The old YAML pipeline that seeded it
(`Sources/*.yaml`, `kicad_lib/`, `main.py`, generated `Symbols/` +
`Footprints/` + `3DModels/`) is retired: it lives, with full history and its
final generated state, on the **`archive/yaml-library`** branch. To re-run a
full YAML import, check out that branch in this working tree — `compose.yaml`
mounts the repo at `/repo` for exactly that.

## Layout, and where the rules live

**This file holds what applies everywhere. Every other rule sits next to the
code it governs.** A `CLAUDE.md` in a subdirectory is read when you open a file
in that directory, so a backend rule costs nothing on a frontend task. Put a new
rule in the most specific file that covers it, and never copy a rule into two
files — write it once and link to it.

| Path | Role | Read before you change it |
|---|---|---|
| `api/` | FastAPI backend (DB, importer, generator, Jaravis, JLC/LCSC clients) | `api/CLAUDE.md` |
| `api/app/services/` | Business logic | `api/app/services/CLAUDE.md` — it routes every backend topic to its document |
| `api/app/routers/` | HTTP endpoints | `api/app/routers/CLAUDE.md` |
| `api/app/services/fieldsolver\|flasher\|pcm_plugin/` | Field solver, production programming, the KiCad sync plugin | the `CLAUDE.md` in that directory |
| `web/` | React + Vite frontend | `web/CLAUDE.md` — the style system and the shared-input rule |
| `web/src/components\|pages\|sim/` | Shared components, routes, the simulator | the `CLAUDE.md` in that directory |
| `mcp/` | Stdio MCP server proxying the agent tools to Claude Code | `mcp/CLAUDE.md` |
| `render/` | kicad-cli render container (previews, project exports) | — |
| `clients/` | A sample `.kicad_httplib` and unrelated client projects (flasher, invoice import). The KiCad sync plugin is NOT here: its source is `api/app/services/pcm_plugin/`, packaged by `api/app/services/pcm.py` | `api/CLAUDE.md` |
| `docs/reference/` | Long-form topic documents the `CLAUDE.md` files link to | [docs/reference/index.md](docs/reference/index.md) |
| `docs/decisions/` | Architecture decisions, MADR format | [docs/decisions/index.md](docs/decisions/index.md) |
| `compose.yaml`, `compose.prod.yaml`, `.github/workflows/images.yml` | Dev and server deployment, image builds | [docs/reference/deployment.md](docs/reference/deployment.md) |

## Running

`README.md` holds the commands and the port table. One fact it does not state:
the api and web containers live-mount their sources (`api/app`, `web/`), so host
edits hot-reload and need no rebuild.

## Skills — the platform is the source of truth, the files are a working copy

The component and library conventions are **skill documents in Postgres**,
edited in the Skills view and versioned like everything else here. Copies live
in `.claude/skills/kicad-<name>/SKILL.md`, tracked in git, because that is the
only way Claude Code discovers a skill and auto-triggers it on the right task.
Each file carries a stamp under its frontmatter:

```
<!-- platform-skill: conventions-symbols v3 — ... -->
```

There is **no sync script and no hook** — an earlier version mirrored the
database into these files on every prompt. Keeping them current is now the
agent's job, and it costs one tool call:

1. **Before library work, call `list_skills`** (MCP: `kicad-library`). It
   returns every skill with its `version_no` and no bodies.
2. **If a local stamp is behind, refresh that file**: `get_skill(name)` and
   rewrite `SKILL.md` — keep the frontmatter, update the stamp to the new
   version. Editing these files is expected, not a workaround.
3. **Never treat the local copy as authoritative** when it disagrees with the
   platform, and never record a new convention only in the file — it would be
   lost on the next refresh.

To *change* a convention, write it: `propose_skill_update(skill_name, content,
comment)` — the first argument is `skill_name`, not `name`; `name` is rejected
with `bad arguments for 'propose_skill_update'` — and it **publishes a new
version immediately** (2026-08-24 — skills were the last thing behind the
draft gate, and it is gone, along with the Proposals view). The version it
writes is what `list_skills` reports and what every later agent run reads, so
get it right rather than filing it and walking away. Then refresh the local
file. To undo one, `get_skill` the previous version's text
and write it back — or restore it on the Skills page.

A skill's `description` is unversioned and lives on `Skill` — edit it in the
Skills view; it becomes the frontmatter `description`, which is what an agent
reads to decide whether to open the document.

## Images and deployment

`.github/workflows/images.yml` publishes `api`, `web` and `render` to GHCR on
every push to `main`; `compose.prod.yaml` runs them on the server. Read
[docs/reference/deployment.md](docs/reference/deployment.md) before you change a
Dockerfile, a compose file or the workflow. Four traps it explains:

- **The deployed UI is same-origin**, so `src/api.ts` must keep defaulting
  `API_URL` to `""`.
- **`compose.yaml` must ask for `target: dev`** on the web service.
- **`render/` carries byte-identical copies of five files** from
  `api/app/services/` — edit both, or the `guard` job fails the build.
- **The build cache has two halves** (`cache-to` in the workflow, `cache_from`
  in `compose.yaml`). Dropping either brings the 10-minute cold rebuild back.

`linux/amd64` only, on purpose.

## Controlled impedance

The 2D field solver lives at **Simulator → Field solver** (`/sim?tab=field`) and
its stackups are project data, not scratch data. The three rules that are
expensive to get wrong are in `api/app/services/fieldsolver/CLAUDE.md`, with the
reasoning in
[docs/decisions/0002](docs/decisions/0002-field-solver-in-the-platform.md).

## Getting the library into KiCad

The Plugin and Content Manager installs once; after that the **Sync 7Sigma
Library** button owns library updates, and each user has one personal URL that
carries their token. Full rules in
[docs/reference/kicad-integration.md](docs/reference/kicad-integration.md), full
reasoning in
[docs/decisions/0006](docs/decisions/0006-sync-button-owns-library-updates.md).

## Datasheets

Every datasheet URL is re-fetched once a night, and the archive is the document
KiCad itself is pointed at. Three rules are expensive to get wrong — a version
means the TEXT changed, a real revision is a review event, and a file is stored
once and shared. They are stated in
[docs/reference/datasheets.md](docs/reference/datasheets.md), with the reasoning
in [docs/decisions/0004](docs/decisions/0004-datasheet-identity-and-storage.md).

## Access control

The platform is on the internet at `https://disfunction.cc/lib` and the API is
**default-deny**: a browser needs a session, every machine client needs a
personal API token. Full rules in `api/CLAUDE.md` (backend) and `web/CLAUDE.md`
(the sign-in gate). Three facts that belong at this level:

- **Accounts are made by an admin, on the Setup page.** No sign-up, no password
  recovery, no endpoint for either.
- **Each user gets one URL for KiCad**:
  `…/api/kicad/pcm/repository.json?t=<their token>`. Pasting it into the Plugin
  and Content Manager installs the library, the models, and a sync plugin with
  their token already inside it.
- **`PUBLIC_BASE_URL`, `APP_BASE` and the shared nginx `/lib/` route still move
  together** — the personal URLs are built from `PUBLIC_BASE_URL`, so a mismatch
  hands users a link that resolves nowhere.

## Decisions and open work

Two registers track the platform itself — not component data, which stays in
the skill documents (see "Skills" above).

| Register | Holds |
|---|---|
| [docs/decisions/](docs/decisions/) | Architecture and process decisions that are expensive to reverse: deployment, access control, backend/frontend architecture. MADR format, `NNNN-title.md`. Never edit an accepted record — write a new one and mark the old `superseded by NNNN`. |
| [docs/todo.md](docs/todo.md) | Work found but not done. Ask before adding a row, unless the user asked for that item first. Delete a row when it lands and record the result in its real home — a decision record, a skill update, or `CHANGELOG.md`. |

Route a new fact the same way "Leave the library better than you found it"
(below) routes a component finding: a decision that is expensive to reverse
goes to `docs/decisions/`; a release or a correction goes to `CHANGELOG.md`;
work found but not agreed yet goes to `docs/todo.md`, after the user agrees.

A register holds open rows only. When a `docs/todo.md` row is answered, write
the answer into its home, then delete the row — do not strike it through.

### The documentation is part of the change, not a follow-up

**A change is not done until its documentation lands in the SAME commit.** Do
not report work as finished, and do not push or deploy it, until you have gone
through this list and said in your report which entries you wrote and which you
decided did not apply:

| Write | When |
|---|---|
| `docs/decisions/NNNN-*.md` + a row in `docs/decisions/index.md` | The change adds an external dependency, alters deployment or access control, or **would be expensive to reverse**. Reversing it changes other people's boards, data or credentials. Follow the rules in [docs/decisions/index.md](docs/decisions/index.md). |
| `CHANGELOG.md` | Anything a user of the platform would notice: a new capability, a behaviour change, a correction. Add a dated section at the top. |
| `docs/todo.md` | You found real work and are not doing it now. **Ask first**, unless the user already asked for that item. |
| The nearest `CLAUDE.md`, or the `docs/reference/` page it links to | A non-obvious fact about how the repo, platform or process works. Put it in the most specific file that covers it — see "Layout, and where the rules live". **When a change makes an existing statement wrong, correcting it is part of the change** — a stale rule in these files is worse than a missing one, because the next agent believes it. |
| A `CLAUDE.md` or a `docs/reference/` page | Before you write one, read [docs/reference/writing-instruction-files.md](docs/reference/writing-instruction-files.md) — the six rules that keep these files working, and why a file that grows past its usefulness makes an agent follow LESS of it. Run `python3 scripts/check-docs.py` before you report the work as done. |
| A platform skill, via `propose_skill_update` | A component or library convention, a decision rule, or a trap. Never record a convention only in `.claude/skills/` — the next refresh overwrites it. |

Two failure modes to avoid, both seen in this repo:

- **Writing the code and calling it done.** The decision record for
  [0005](docs/decisions/0005-off-board-parts.md) was written after the change
  had already been committed, pushed and deployed, which is exactly what rule 2
  of the decisions index forbids. The record is the only place the REJECTED
  options survive, and those are what stop the next person re-proposing them.
- **Leaving a register to grow stale.** A decision record is never edited once
  accepted — supersede it. A `docs/todo.md` row is deleted when it lands, never
  struck through.

## Conventions

- Component/library conventions live in the platform's **skill documents** — not
  in these files. See "Skills" above for how the copies in `.claude/skills/`
  relate to the database.
- Backend and frontend conventions live beside the code — see the table above. Record a new non-obvious rule in the most specific file that
  covers it, and write it once. Two copies of a rule become two different rules.
- **Every input in the web UI is a SHARED component, never a page-local one.**
  One rule draws every text control, `components/Field.tsx` labels it, and a
  value that carries a unit goes through `components/SiInput.tsx` whatever page
  it is on. Four competing form styles and three different control appearances
  existed at once before this was written down (2026-09-12). The full rules —
  the two sizes, the SI quantities, where the ⓘ goes — are in `web/CLAUDE.md`
  under "Reuse the existing style system"; this line is here because the rule is a PROJECT rule, not
  a frontend detail: a new screen that invents its own input is wrong even when
  it looks fine on its own page.
- **Every write AUTO-PUBLISHES** — components, symbols and footprints since
  2026-08-23, skills since 2026-08-24. There is no draft gate and no approval
  queue left in the platform: the Proposals view and `routers/proposals.py`
  were removed, `/proposals` redirects to Reviews, and the YAML sync
  (`POST /api/import/sync`), whose drafts nothing could approve any more,
  answers 410. Accountability lives on the **review axis** — machine
  validation on every publish, checklist verifications, the Reviews queue,
  human sign-off, and the per-component lifecycle (`released` on first
  sign-off; `deprecated`/`obsolete` hidden from KiCad). See
  [docs/reference/review-axis.md](docs/reference/review-axis.md).

## Leave the library better than you found it

Verification work is not only about the part in front of you. **Every pass is
also a survey of what keeps going wrong**, and noticing that is part of the job,
not a distraction from it.

**When the same finding shows up on a third part, stop and generalise it.** One
occurrence is a defect, two is a coincidence, three is a missing default. Ask
whether it belongs in one of these places, and say so in your report:

| Where it belongs | What goes there |
|---|---|
| A **checklist item** (component / symbol / footprint) | A check a human or agent should run on EVERY part of that kind, that the current checklist has no key for. Until then, record it as `custom:<slug>` with a `text` — those accumulate on the parts you touch and are the evidence for promoting it. |
| A **validator rule** | A check that is purely mechanical and could be machine-decided on publish, so no one has to remember it. |
| A **skill document** | A convention, a decision rule, or a trap that changed how you worked. Publish it with `propose_skill_update` — it is live for every later run. |
| **These CLAUDE.md files** | A fact about how the repo, platform or process works, rather than about component data. |

Recurring findings already established this way, so you do not have to rediscover
them: symbol field defaults carrying `easyeda2kicad:` footprint references and
HTML datasheet URLs; pins left electrical type `unspecified` after an EasyEDA
import; exposed pads named `GND` and typed `power_in` where the datasheet says
the pad is not a ground pin; empty symbol `Description` / missing `ki_keywords` /
missing `ki_fp_filters`; `ki_fp_filters` naming a package the part is not made
in; and a rating copied from a sibling variant's table into `ki_description`
(single-channel where the part is dual, peak where the part is continuous).

**Also flag process friction, not just data defects.** If the validator silently
skipped its machine items, if a version bump dropped verification that should
have carried, if a tool's argument names differ from its documentation — that is
worth a line in your report even though it is nobody's component. The platform is
ours to fix too.

Do not let this become scope creep: finish the task you were given first, then
report the generalisation. Proposing a checklist item is a suggestion to the
user, not something to implement mid-task.
