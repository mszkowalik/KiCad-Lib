---
status: "accepted"
date: 2026-09-18
decision-makers: Mateusz Kowalik
---

# A release is a content-addressed file set, and a deployment version pins the set

## Context and Problem Statement

One berryware release was stored three times. `device_file_versions` gave
every file its own version number; `berry_bundles` listed those versions as a
named set; `deployment_files` pinned the same versions again under each
deployment version, with `files_fingerprint`, `files_label` and
`berry_bundle_id` cached on the version and re-derived by fingerprint
matching after every edit. Measured on 2026-09-18: 56 files, 111 file
versions, 9 bundles and 293 pin rows to describe 9 releases across 25
versions, and the same driver JSON stored as three unrelated files with three
histories because the pool was project-scoped. The user's verdict: the
per-file version numbers mean nothing to them, and the way files are stored
in connection with where they are used is too complicated.

The user had already said on 2026-07-29 that files come in bundles and the
bundle is the thing they care about. The bundle was built on top of the
per-file versions rather than replacing them, which is where the three
copies came from.

## Decision Drivers

* The user thinks in releases ("release-1.3.11"), never in "autoexec.be v6".
* One place for "which files does this version give a device", with no
  cache to re-derive.
* Content that is the same in two projects is the same content.
* A programming run must still answer "what did this unit get" after any
  tidy-up, which the pin history has always guaranteed.

## Considered Options

* **A** — blobs and file sets: content-addressed bytes, an immutable manifest
  as the unit, the version pins the set.
* **B** — keep the schema, hide the per-file pool and show only bundles.
* **C** — keep per-file versions but pin the bundle instead of each file.

## Decision Outcome

Chosen option: **A**.

* `file_blobs` holds bytes keyed by sha256, platform wide. Text is
  LF-normalised, a non-UTF-8 upload is kept as bytes.
* `file_sets` is an immutable, ordered manifest of `(filename, blob)` with a
  `kind` (`berryware` or `artwork`), a label and a fingerprint that is its
  identity, unique on the platform. A set is never project-scoped: the same
  release imported by two projects is one row (user decision 2026-09-18).
* `deployment_versions.file_set_id` pins the berryware release and
  `artwork_set_id` the drawing. `deployment_files`, `files_fingerprint`,
  `files_label`, `berry_bundle_id`, `device_files`, `device_file_versions`,
  `berry_bundles` and `berry_bundle_files` are gone.
* A set enters by import (a folder or files) or by **derive**: copy an
  existing manifest, replace or add files by upload, borrow files from any
  other set, leave some out, name the result. There is no hand-picked
  composition of individual file versions and no paste editor.
* The device URL is `/api/flasher/files/{set_id}/{filename}`; the engine's
  local names for a download step are `file_set_id` and `filename`.
* Delete is per set and refuses while any deployment version pins it, draft
  or published. Blobs no set names are pruned with the set.

The fold (`services/flasher/fileset_migrate.py`) runs once at startup in one
transaction, keeps bundle ids, collapses twins with equal fingerprints,
checks every version's new set against its old cached fingerprint, and drops
the old tables only after that check passes. Local result on 2026-09-18:
76 blobs, 10 sets from 9 bundles plus 3 artwork versions, 25 versions
repointed, 20 fingerprints checked, 6 unreachable blobs pruned.

### Consequences

* Good, because a version's files are one pointer, and "same berryware as
  v5" is one integer comparison with no cache to go stale.
* Good, because the Files page lists releases, not file rows with version
  counts, and a file's history is read off the releases that carried it.
* Good, because the same driver JSON in three projects is stored once.
* Bad, because a one-line fix to one script now mints a whole new release.
  That is the point: the device receives a set, so the set is what changed.
* Bad, because "vs previous" on the Files page compares against the newest
  older set of the same kind on the whole platform, and the lineages of two
  projects interleave. The exact answer between two versions is the diff view.
* Neutral: the per-file version numbers are gone from history too. The
  migration labelled each artwork set from its old number
  (`…lbrn2 v3`) so the marking versions still read the same.

### Confirmation

`GET /api/health/schema` reports `file_sets.fold` as `ok: …` on the first
start and `skipped` after. Run against the local platform on 2026-09-18:
importing the exact bytes of an existing release answered `created: false`;
deriving from `release-1.3.11` with one replaced and one removed file made a
17-file set whose changed file read "changed since release-1.3.11"; a set of
scripts plus an `.lbrn2` answered 400; pinning a berryware set on a mark
version answered 400; a PATCH pinning the derived set on a flash draft
validated and the timeline read "berryware (1 changed, 1 removed)"; DELETE on
the pinned set answered 409, and after unpinning it answered 200 and pruned
the one blob nothing else carried.

## Pros and Cons of the Options

### A — blobs and file sets

* Good, because storage matches the unit the user reasons in.
* Good, because the delete guard, the fingerprint and the pin are one join.
* Bad, because it is a schema migration with a table drop, and a partial
  application would be worse than either shape — which is why the fold is
  one checked transaction.

### B — keep the schema, change the screen

* Good, because no migration.
* Bad, because the three copies and the fingerprint re-linking stay, and
  the next feature that touches files meets all three again.

### C — pin the bundle, keep per-file versions

* Good, because the pin becomes one pointer.
* Bad, because "autoexec.be v6" stays the primary object underneath, and a
  bundle still has to be composed from versions nobody thinks in.

## More Information

* Supersedes [0026](0026-a-device-file-carries-its-kind-and-enters-by-upload.md):
  the kind now lives on the set and is decided from the extensions of the
  whole manifest; the upload path is the set import; the delete guard is per
  set. What 0026 rejected stays rejected — sniffing the extension at each call
  site, content inside the step, soft delete, cascade delete.
* [0020](0020-marking-goes-through-lightburn.md) still holds: the step names
  a filename, the version pins the content — now as a one-file artwork set.
* `api/app/services/flasher/CLAUDE.md` and
  `web/src/components/flasher/CLAUDE.md` state the rules this record settles.
