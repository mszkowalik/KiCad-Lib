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

## Running

```bash
cp .env.example .env    # once; JLC/Anthropic keys optional
docker compose up -d --build
```

Web UI at http://localhost:5173, API at http://localhost:8020 (docs at
`/docs`). The api and web containers live-mount their sources (`api/app`,
`web/`) — host edits hot-reload without a rebuild.

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
