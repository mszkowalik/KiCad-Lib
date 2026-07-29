# 7Sigma KiCad Library Platform

Web-hosted component library for KiCad: Postgres-backed catalog with versioned
components/symbols/footprints, draft-proposal workflow, KiCad HTTP library +
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

To *change* a convention, propose it: `propose_skill_update(name, content,
comment)` files a **draft** the user approves in the Proposals view. Writes to
skills are draft-gated exactly like components; approval is what makes the new
version the one `list_skills` reports. Then refresh the local file.

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
- **`render/` carries copies of two files from `api/app/services/`**
  (`project_ops.py`, `board_template.kicad_pcb`). The workflow's `guard` job
  fails the build when they are not byte-identical, so edit both together.

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

## Conventions

- Component/library conventions live in the platform's **skill documents** — not
  in these files. See "Skills" below for how the copies in `.claude/skills/`
  relate to the database.
- Backend and frontend conventions: see `api/CLAUDE.md` and `web/CLAUDE.md`.
  Record new non-obvious rules in the most specific of those files.
- Writes to library data go through **draft proposals** approved in the
  Proposals view — never publish directly (see the versioning section of
  `api/CLAUDE.md`).
