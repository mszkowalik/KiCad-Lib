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

## Conventions

- Component/library conventions live in the platform's **skill documents**
  (editable in the web UI, readable via the `get_skill` agent tool) — not in
  these files. `.claude/sync-skills.py` mirrors them from the database into
  `.claude/skills/kicad-<name>/SKILL.md` so Claude Code picks them up as real
  skills; two hooks in `.claude/settings.json` re-run it (session start, and
  `--quick` before every prompt), and the generated tree is gitignored. Each
  skill's unversioned `description` becomes the skill's frontmatter — edit it in
  the Skills view, not in the generated files, which are overwritten on sync.
- Backend and frontend conventions: see `api/CLAUDE.md` and `web/CLAUDE.md`.
  Record new non-obvious rules in the most specific of those files.
- Writes to library data go through **draft proposals** approved in the
  Proposals view — never publish directly (see the versioning section of
  `api/CLAUDE.md`).
