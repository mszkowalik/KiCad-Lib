---
status: accepted
date: 2026-11-01
decision-makers: Mateusz Kowalik
---

# Name the platform Henry, serve it at the root of henry.disfunction.cc, and redirect the old /lib address

## Context and Problem Statement

The platform started as a KiCad component library and kept that name:
"7Sigma KiCad Library Platform" in the docs, `kicadlib` on the server,
`kicad-library` for the MCP server. It now also holds projects and BOMs,
production runs and their costs, invoices and KSeF, stock, shipments, device
programming, the bench and the fleet watch, for two companies (7Sigma and
9SIGMA). The name describes one part of it.

It was served at `https://disfunction.cc/lib`, under a path prefix in the
shared nginx, because `/api/` at that root belongs to another stack. What
name does the platform get, where does it live, and what happens to the old
address that thousands of stored links point at?

## Decision Drivers

* The name must not depend on KiCad, on electronics or on one company.
* Old links must keep resolving. Every datasheet link in a schematic made
  from the library points at `https://disfunction.cc/lib/api/datasheets/…`,
  and those files are outside the platform's reach.
* No data migration. The data stays where it is.
* The bench agent trusts browser origins. `https://disfunction.cc` also
  serves unrelated apps, so any page there could call a bench agent. An own
  hostname gives the platform an origin of its own.

## Considered Options

Name: Keel, Spine, Truss, Kelvin, letter names (ORB, HOP, P2D), **Henry**.

Old address:

* Proxy the machine paths (`/lib/api`, `/lib/kicad`, `/lib/files`) for
  ever, and redirect the browser pages.
* Keep the whole old UI too, with a second web container built for
  `APP_BASE=/lib`.
* **Redirect everything to the same path on henry.**

Internal names (Postgres role and database, MinIO bucket, the env vars
`KICAD_API_URL` and `KICAD_MCP_TOKEN`): **keep them**, or rename them.

## Decision Outcome

Chosen: **Henry**, at the root of **`henry.disfunction.cc`**, with the old
address redirected, because the user chose that name and that redirect. Henry
is the SI unit of inductance and a common first name, so it has a link to
electronics without depending on KiCad.

1. **The display name is Henry**: the web header, the login page, the page
   title, the API title, the KSeF `SystemInfo`, the KiCad HTTP-library
   description and the PCM repository name ("Henry (7Sigma library)").
2. **The address is `https://henry.disfunction.cc`**, with the app at the
   root: `PUBLIC_BASE_URL=https://henry.disfunction.cc`,
   `DEVICE_BASE_URL=http://henry.disfunction.cc` (the http twin, for the
   reason in [0025](0025-a-device-fetches-from-its-own-address.md)),
   `APP_BASE=""`. The pieces on the server are a Cloudflare DNS CNAME to the
   tunnel, a tunnel ingress rule, an nginx server block and `henry.env`.
   The wildcard certificate and dnsmasq already covered every subdomain.
3. **`disfunction.cc/lib/<path>` answers a 307 to
   `https://henry.disfunction.cc/<path>`, permanently.** It is a 307 and not
   a 301 or a 308 on purpose: the sync plugin runs on KiCad's bundled Python
   3.9.13, whose `urllib` has no 308 handler, and a 301 turns a POST into a
   GET with no body. A 307 is followed on GET and refused with an error on
   POST.
4. **The server stack is `henry`**: compose project, container names
   (`henry-db`, `henry-minio`, `henry-api`, `henry-render`, `henry-web`),
   data directory and env file.
5. **The MCP server is `henry`**, so its tools are `mcp__henry__*`. The token
   file is `~/.config/henry/token`, and `server.py` falls back to
   `~/.config/kicad-library/token` when the new file is missing.
6. **The bench agent's default origin is `https://henry.disfunction.cc`
   only.** The old origin is dropped, not kept beside it: it is shared with
   other apps.
7. **The sync plugin goes to 1.5.1**, so the PCM offers every user a plugin
   with the new base URL in it.

Kept unchanged on purpose:

* The Postgres role and database `kicadlib` and the MinIO bucket `kicadlib`.
  Nobody sees them, and a rename is a data migration.
* The env var names `KICAD_API_URL` and `KICAD_MCP_TOKEN`. Every agent
  config carries them.
* The KiCad library nicknames `PCM_7Sigma` and `PCM_7Sigma_Base`, and the PCM
  identifiers `com.sevensigma.*`. Every schematic stores its symbol links
  with those nicknames, so a rename breaks every board.
* The GitHub repo and the image path `ghcr.io/mszkowalik/kicad-lib/*`. The
  workflow derives the image path from the repo name. Rename both together,
  or not at all.
* `BUILDER_REV`. A bump re-versions every PCM package, and the PCM then
  offers each user the 260 MB models package again for an unchanged tree.
  The new base URL changes the plugin files, which rebuilds the repository
  without it.
* The local dev compose project `kicadlib-platform`. Its named volumes take
  the project name as a prefix.

### Consequences

* Good: the name fits the whole platform, and the platform has its own origin.
* Good: every stored link still resolves, through one redirect.
* Bad: every user must sign in again. The session cookie belongs to one host.
* Bad: an MCP server registered before the move stops working. `httpx`
  follows no redirect by default. The user runs the Account page prompt again.
* Bad: a bench launcher downloaded before the move refuses the new origin.
  Each bench Mac must download the agent again and install the new macOS
  profile, which grants Chrome local-network access per origin.
* Bad: a push from a sync plugin below 1.5.1 fails with HTTP 307 until the
  user updates the plugin in the PCM.
* Unverified: whether KiCad's own HTTP client (PCM and HTTP library) follows a
  307. If it does not, a user must paste the new personal repository URL from
  the Account page.

### Confirmation

* `https://henry.disfunction.cc/api/health` answers 200 on the LAN and
  through the tunnel.
* `http://henry.disfunction.cc/…` answers without an HTTPS redirect, which a
  device needs.
* `https://disfunction.cc/lib/api/health` answers 307 with
  `Location: https://henry.disfunction.cc/api/health`.
* A bench launcher downloaded from henry carries
  `--origin 'https://henry.disfunction.cc'`.

## Pros and Cons of the Options

### Proxy the machine paths, redirect the browser pages

* Good, because every client keeps working with no redirect to follow.
* Bad, because two addresses answer the API, for ever.

### Keep the whole old UI too

* Good, because old bench launchers keep working until each bench is updated.
* Bad, because a second web container must be built, deployed and retired.

### Redirect everything

* Good, because one address serves the platform and the nginx rule is short.
* Bad, because clients that do not follow a redirect break: `httpx`, and
  Python 3.9 `urllib` on a 308 (hence the 307).

### Rename the internal names too

* Bad, because renaming the database and the bucket is a migration with
  longer downtime, for names no user sees.

## More Information

* [docs/reference/deployment.md](../reference/deployment.md) — the hostname,
  the redirect and the stack names.
* [0025](0025-a-device-fetches-from-its-own-address.md) — why a device gets
  the http twin.
* The server's `~/aws-deployment/HOMELAB.md` §3 — the tunnel, DNS and nginx
  side.
