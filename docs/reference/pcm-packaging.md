# PCM packages — retention, versioning and the personal repository

How the Plugin and Content Manager gets the library, why a superseded artifact
stays downloadable, and how a user token reaches KiCad. The service is
`api/app/services/pcm.py`. The plugin source it packages is in
`api/app/services/pcm_plugin/`, which has its own rules.

## A superseded PCM artifact stays downloadable (the "hash does not match" trap)

`ZIP_EPOCH` already handles half of this failure: the same content must always
produce the same bytes. The other half is retention. PCM caches `packages.json`
and refreshes the repository only when asked, so a user can hold a record
naming a build tag the mirror has already moved past — and **every component
publish moves the mirror**. Deleting the superseded zip immediately turned that
stale record into a 404, and KiCad hashes the 80-byte JSON error body like any
other download and reports:

    Downloaded archive hash for package 7Sigma Library does not match
    repository entry.

which reads as corruption and is nothing of the kind (reported 2026-08-25 on
`library-fb1c4c239d2fr10.zip`; the chain served at that moment was perfectly
self-consistent). `ensure_built`'s prune therefore keeps, besides the current
build and this revision's personal plugin zips, any artifact that is
`_within_grace` — under `_GRACE_DAYS` old AND inside its package's
`_GRACE_BYTES` budget, where newer siblings claim the budget first.

**The budget is in bytes, not generations, and the difference matters.** A
generation cap looks equivalent and is not: the library package rebuilds on
every component publish, so "keep the last two" is minutes of cover on a busy
day, while the retention has to span however long a user leaves a pending
update sitting in PCM. Sized per package, the same 14 days buys ~400 library
zips (0.5 MB each) or one extra 3D models zip (260 MB).

**A pending update is pinned in the CLIENT, and no server retention reaches
back past it.** `installed_packages.json` records the download URL and sha of
each version PCM has seen, and an update uses that record rather than
re-reading `packages.json` — so refreshing the repository does not rewrite it.
A user whose recorded version has aged out of the grace window has to uninstall
and reinstall the package.

**A stale `packages-<tag>.json` is served from the build ITS OWN TAG names**,
not from the current one — `pcm.meta_for_packages_file` loads `meta-<tag>.json`
and `pcm_artifact` personalises that. Answering from the current build fails the
hash the client's cached repository record published, and falling through to the
shared file on disk hands KiCad download URLs with no `?t=` on them, so every
zip fetch after it is unauthenticated. Retention is what makes this work: the
grace window keeps the zips an old index names, its personal plugin zip
included.

**Diagnosing this class of report**: fetch `repository.json`, then
`packages.json`, then the zip, and compare the advertised `download_sha256`
against the served bytes. A 404 body, not a hash difference, is the usual
answer — and it means the client is stale, not that the package is broken.

## Each PCM package is versioned from ITS OWN content

A package's version string is what PCM compares to decide "update available",
and the three packages differ in where it comes from: `library` and `models3d`
derive it from the mirror manifest's `generated_at`, `sync` carries the manual
`PLUGIN_VERSION`. **A content package keeps its previous version while its own
subtree hash is unchanged** — `_resolve_package` reuses the whole cached entry,
version included. Only the plugin (`pinned_version=True`) takes the passed-in
version on a cache hit, because that one is authored by hand and a bump with
untouched sources still has to reach the repository.

Getting this wrong is expensive in both directions, and the module has now been
wrong in both:

- Reuse the zip but keep the old version, and a `PLUGIN_VERSION` bump becomes a
  silent no-op — nobody is offered the new plugin.
- Put the version IN the reuse test, and the 260 MB models zip is re-encoded on
  **every mirror regeneration**, because a content package's version follows the
  mirror timestamp and that moves on every component publish. Same content, same
  URL, same bytes (`ZIP_EPOCH`), minutes of CPU — and PCM offered every user a
  260 MB update for an unchanged 3D model tree. Measured 2026-08-25: seven
  rebuilds of `models3d-68a2993fcf88r10.zip` in one morning of footprint edits.

The module docstring has promised per-content versioning since it was written;
until 2026-08-25 the code did not do it. When the reuse rule changes again,
check both failure modes before believing the fix.

## The personal PCM repository (how a token reaches KiCad)

One URL per user — `…/api/kicad/pcm/repository.json?t=<token>` — installs the
library, the 3D models AND a sync plugin with that token already inside it. The
user pastes once and never types a credential.

- **The three documents are chained by hash, so all three are per-token.**
  Personalising a `download_url` changes `packages.json`, which changes the
  sha256 that `repository.json` publishes. `pcm.personal_repository` /
  `personal_packages` generate them per request (they are small and
  deterministic for a given (meta, token), so the hash a client verifies always
  matches the bytes it later fetches). Never cache one without the other.
- **`_plugin_files(token="")` must stay the default for the repository tag.**
  `ensure_built` hashes the plugin files to decide whether to rebuild, so if
  personalisation moved that hash, every user's first install would look like a
  library change and rebuild the 1.4 GB models package.
- **A personalised plugin zip needs its sha256 RECOMPUTED** — PCM verifies the
  download against `packages.json`, and a zip with a different token is a
  different file. `pcm.personal_plugin` builds it lazily under a
  `psync-<hash>.zip` name keyed on the plugin content hash AND the token, writes
  it via a `.part` rename (a half-written zip would fail PCM's check and read as
  a server fault), and lets `ensure_built`'s prune treat it as the cache it is.
- **The plugin sends its token as a HEADER, never `?t=`.** Only PCM itself is
  forced into the query string. Both templates fall back to `token.json` beside
  the plugin, which is the recovery path after a rotation, and turn a 401 into
  an instruction rather than a stack trace.
- **`BUILDER_REV` and `PLUGIN_VERSION` both had to move for this.** See the
  rule above about them: `pcm.py` changing what a package advertises needs
  `BUILDER_REV`, and plugin source changes need `PLUGIN_VERSION`.
- **Every client through the tunnel MUST send its own `User-Agent`.**
  Cloudflare's browser-integrity check answers the bare `Python-urllib/3.x`
  signature with **403 and error code 1010** before the request ever reaches
  nginx — it is not an API refusal, and the body is Cloudflare's HTML, so it
  surfaces as an unexplained failure. Verified 2026-07-31: `Python-urllib/3.11`
  403s while `sevensigma-sync/1.0`, `curl/8.7.1` and `KiCad/9.0` all pass. Both
  plugin templates and `cli/kicadlib.py` already set one on every request
  (`_headers()`), so keep it that way — a new request path that forgets the
  header works on the LAN and fails only from the internet.

