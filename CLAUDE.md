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

## Layout

| Path | Role | Docs |
|---|---|---|
| `api/` | FastAPI backend (DB, importer, generator, Jaravis, JLC/LCSC clients) | `api/CLAUDE.md` |
| `web/` | React + Vite frontend | `web/CLAUDE.md` |
| `mcp/` | Stdio MCP server proxying the agent tools to Claude Code | `api/CLAUDE.md` (agent section) |
| `render/` | kicad-cli render container (previews, project exports) | — |
| `clients/` | Client-side helpers (KiCad sync plugin etc.) | — |
| `compose.yaml` | Full dev deployment (db, minio, api, render, web) | `README.md` |
| `compose.prod.yaml` | Server deployment from the published GHCR images | `README.md` |
| `.github/workflows/images.yml` | Builds + pushes the api/web/render images | `README.md` |

## Running

```bash
cp .env.example .env    # once; JLC/Anthropic keys optional
docker compose up -d --build
```

Web UI at http://localhost:5173, API at http://localhost:8020 (docs at
`/docs`). The api and web containers live-mount their sources (`api/app`,
`web/`) — host edits hot-reload without a rebuild.

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
every push to `main` (pull requests build without pushing);
`compose.prod.yaml` runs them on the server. Three rules follow from that:

- **The deployed UI is same-origin.** The `web` image is a `prod` Dockerfile
  target: the built SPA served by nginx, which reverse-proxies `/api`,
  `/kicad`, `/files`, `/docs` and `/openapi.json` to the api container. Vite
  inlines env vars at build time, so a baked-in API URL would tie an image to
  one hostname — `src/api.ts` therefore defaults `API_URL` to `""`. Never
  reintroduce an absolute default (see `web/CLAUDE.md`).
- **`compose.yaml` must ask for `target: dev`** on the web service, or dev
  gets the nginx image instead of the Vite server.
- **`render/` carries copies of three files from `api/app/services/`**
  (`project_ops.py`, `sim_spice.py`, `board_template.kicad_pcb`). The
  workflow's `guard` job fails the build when they are not byte-identical, so
  edit both together.

`linux/amd64` only, on purpose: the render image's `kicad/kicad` base is
published amd64-only, and the api image compiles LibreDWG from source, which
is very slow under emulation.

- **A pruned machine self-recovers.** The workflow also pushes a full
  (`mode=max`) registry build cache to `ghcr.io/.../<name>:buildcache`, and the
  `build.cache_from` lists in `compose.yaml` point at it — after a
  `docker system prune`, `docker compose up -d` pulls the layers (LibreDWG
  included) instead of recompiling. Unreachable cache refs only warn, so
  offline builds still work. Keep both halves in sync: dropping either the
  `cache-to` line in `images.yml` or a `cache_from` list silently brings the
  ~10-minute cold rebuild back.

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

## Conventions

- Component/library conventions live in the platform's **skill documents** — not
  in these files. See "Skills" below for how the copies in `.claude/skills/`
  relate to the database.
- Backend and frontend conventions: see `api/CLAUDE.md` and `web/CLAUDE.md`.
  Record new non-obvious rules in the most specific of those files.
- **Every write AUTO-PUBLISHES** — components, symbols and footprints since
  2026-08-23, skills since 2026-08-24. There is no draft gate and no approval
  queue left in the platform: the Proposals view and `routers/proposals.py`
  were removed, `/proposals` redirects to Reviews, and the YAML sync
  (`POST /api/import/sync`), whose drafts nothing could approve any more,
  answers 410. Accountability lives on the **review axis** — machine
  validation on every publish, checklist verifications, the Reviews queue,
  human sign-off, and the per-component lifecycle (`released` on first
  sign-off; `deprecated`/`obsolete` hidden from KiCad). See "The review axis"
  in `api/CLAUDE.md`.

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
