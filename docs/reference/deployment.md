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

- **A 502 on `/lib/` after a deploy means the shared nginx, not the platform.**
  The front container `webserver` serves `/lib/` for every stack on that host
  and resolves `kicadlib-web` ONCE, when its configuration loads. Recreating
  `kicadlib-web` can give it a new address on the shared network, and nginx
  keeps proxying to the old one. The api is healthy and the page is a 502.
  The fix is one command and it touches no other stack:

  ```
  ssh ubuntu "docker exec webserver nginx -s reload"
  ```

  Check the api first, so the reload is a diagnosis rather than a reflex:
  `docker logs --tail 20 kicadlib-api` says `Application startup complete`
  when the platform itself is fine. (Seen 2026-09-17.)

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


## Bringing production data down to local

```
scripts/sync-prod-to-local.sh --check      # compare, change nothing
scripts/sync-prod-to-local.sh              # database only
scripts/sync-prod-to-local.sh --files      # database + the MinIO objects
scripts/sync-prod-to-local.sh --lean       # skip the 2.5M-row flash logs
```

The script exists because **a partial restore is worse than no restore.** A
local copy that was missing `jlc_order_decisions` showed 45 undecided JLC
orders that production had decided months earlier, and read as a regression in
code that was fine (2026-09-21). Four more tables — `run_checks`,
`device_config_values`, `programming_steps`, `run_production_files` — were empty
for the same reason and nobody had noticed.

Four facts it encodes, each of which cost a failed run to learn:

- **It only goes one way, and it only READS production.** Every prod command is
  a `pg_dump`, a `tar -c` or a `select`. There is no flag that reverses the
  direction, on purpose.
- **`pg_restore --jobs` refuses a dump on standard input.** The dump is copied
  into the db container first, then restored from a file.
- **The MinIO image ships no `tar`.** It does not need one: MinIO's data on the
  server is a host BIND mount (`docker inspect kicadlib-minio` says where), so
  the files are ordinary files and `tar` runs on the server itself. Locally it
  is a named volume, written through a throwaway container while the service is
  stopped.
- **The comparison uses EXACT counts, never `n_live_tup`.** The estimate cannot
  tell a real gap from collector drift, and it reported `run_cost_documents 86
  vs 87` as noise when production had genuinely gained an invoice mid-dump.

A run while somebody is using the platform will show a few tables one row
apart. That is real — the dump has a timestamp — and `--check` says so.
