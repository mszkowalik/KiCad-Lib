# Deployment — images, the server and the build cache

`.github/workflows/images.yml` publishes the images, `compose.prod.yaml` runs
them. The short version is in the root `CLAUDE.md`; this page holds the rules
and the reasons.

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
- **`render/` carries copies of five files from `api/app/services/`**
  (`project_ops.py`, `sim_spice.py`, `svg_units.py`,
  `board_template.kicad_pcb`, `themes/Skyline-7S.json`). The workflow's `guard`
  job fails the build when they are not byte-identical, so edit both together.
  The theme is on that list because kicad-cli renders with it and the browser's
  own schematic renderer reads the same file through `GET /api/sim/theme`.
  `svg_units.py` is there because BOTH renderers have to pick a symbol's unit
  out of the per-unit files kicad-cli writes, and it imports nothing, which is
  what lets one file be a package module here and a flat module there.

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

- **The server is a Proxmox guest, and the field solver feels its size.** The
  server runs as VM 104 (`ubuntu`) on the Proxmox node `pve`
  (`ssh proxmox`), an AMD Ryzen 7 8745H with 8 cores and 16 threads. On
  2026-08-31 the VM went from 2 cores to 8, from 8 GB to 16 GB (ballooned, with
  an 8 GB floor, because the node has only ~29 GB for all its guests), and from
  `cpu: x86-64-v2-AES` to `cpu: host`. The CPU model matters: `x86-64-v2` has no
  AVX at all, so numpy and scipy fell back to OpenBLAS kernels from before 2011.
  The geometry search went from 21.1 s to 8.2 s. If solving is slow again, check
  `qm config 104` for the core count and the CPU model FIRST — the solver fans
  out over `FIELDSOLVER_WORKERS` processes, capped by `os.cpu_count()`.

