---
status: "accepted"
date: 2026-09-12
decision-makers: Mateusz Kowalik
---

# Keep project source in the git mirror only, and stop storing a tarball per snapshot

## Context and Problem Statement

Each project ingest wrote `projects/{id}/snapshots/{sha}/source.tar.gz` into
MinIO. Nothing ever read it back. Measured on the production server on
2026-09-12, those tarballs held **846.8 MiB**, which was 62% of the 1372.7 MiB
bucket, and the total grew by 60 to 103 MiB with every snapshot.

The platform already keeps a bare mirror clone of each project at
`DATA_DIR/git/<project_id>.git`. The mirrors hold every commit of every project
in **214 MB** — less space than two tarballs — because git stores an identical
blob once and packs the rest as deltas.

**Three of the four projects had such a mirror. One did not.** Project 3
(`CE_Aqua_V2`) had no `DATA_DIR/git/3.git`, an empty checkout directory, and a
remote that refuses an unauthenticated `git ls-remote` while the platform holds
no token for it — so its 102.9 MiB tarball was the only copy of that tree on
the server, and that snapshot is both the project's current one and pinned by a
production run. Nothing in the application can produce that state: `fetch_mirror`
is the only writer, `materialize` needs the mirror to make a snapshot at all,
and the only code that removes a mirror is project deletion, which removes the
row with it. It therefore arrived from outside the platform, and can again.

| Project 1, `CE_Dongle_V3` | Size |
|---|---|
| Git mirror, entire history | 117 MB |
| 8 stored snapshot tarballs | about 532 MiB |

## Decision Drivers

* The tarball was write-only. The key `source.tar.gz` appeared exactly twice in
  the codebase: the write in `project_ingest.py`, and a line in the
  `storage.py` key-layout docstring.
* Storage per snapshot was flat, so cost rose with every ingest, while the
  content between two commits of one board is nearly identical.
* `gitrepo.archive_tgz(project_id, sha)` already rebuilds the exact tree from
  the local mirror, with no network call.

## Considered Options

* Keep writing a tarball per snapshot
* Keep the mirror as the only source archive, and rebuild a tree on demand
* Store deltas between snapshots in MinIO
* Store a per-commit manifest plus content-addressed blobs in MinIO

## Decision Outcome

Chosen option: **keep the mirror as the only source archive**. Ingest no longer
writes the tarball, and a startup purge removes the ones already stored, behind
the marker object `maintenance/snapshot-archives-dropped.v1`.

**The purge verifies the premise per archive rather than assuming it.**
`gitrepo.can_rebuild(project_id, sha)` asks whether that commit is still an
object in that project's mirror — the directory existing is not enough, since a
re-clone of a rewritten remote can lose a commit. An archive that fails the
check is kept and logged by key, and the marker is NOT written, so fetching the
missing mirror and restarting finishes the job. Without that check the first
deploy would have destroyed project 3's only copy.

`archive_tgz` stays. It has no callers now, and it is the documented way back
to a byte-exact tree.

### Consequences

* Good, because it frees 743.9 MiB of the 846.8 MiB stored, verified by a dry
  run against production — the remaining 102.9 MiB is project 3's, kept until
  its mirror exists.
* Good, because snapshot storage stops growing with each ingest.
* Good, because the unit to back up becomes `DATA_DIR/git` at 214 MB, and that
  covers **every commit of every project**, not only the 16 that were
  snapshotted.
* Bad, because after the purge the mirror and the upstream remote are the only
  copies of project source. **`DATA_DIR/git` must be in the backup set.** If it
  is not, this change makes the recovery position worse, not better. Note that
  a project whose mirror is missing is not covered by backing up that directory
  at all — which is why the missing-mirror state must be visible, not silent.
* Neutral, because the ingest progress no longer reports an `archive` stage.
  The stage name is a free string with no frontend enum behind it.

### Confirmation

After the deploy that carries this change:

1. `maintenance/snapshot-archives-dropped.v1` exists in the bucket.
2. No key under `projects/*/snapshots/` ends in `source.tar.gz`.
3. The bucket falls from 1372.7 MiB to about 526 MiB (628 MiB while project 3's
   archive is still kept).
4. No project on the Projects page shows the red `no mirror` pill. One that does
   is a project whose tree nothing can rebuild — fetch it.

## Pros and Cons of the Options

### Keep writing a tarball per snapshot

* Good, because it is a copy that does not depend on the mirror surviving.
* Bad, because it protects only the commits that were snapshotted, while
  `DATA_DIR/git` protects all of them for a quarter of the space.
* Bad, because nothing read it, so a corrupt tarball would never be noticed.

### Keep the mirror as the only source archive

* Good, because git is a content-addressed delta store and it is already
  deployed, tested and in the read path.
* Good, because the rebuild path is one function that is already written.
* Bad, because it concentrates the recovery story on one directory.

### Store deltas between snapshots in MinIO

* Bad, because it re-implements what git does, with no history behind it.
* Bad, because a delta chain needs its own integrity check, which git has and a
  hand-rolled chain would not.

### Store a per-commit manifest plus content-addressed blobs in MinIO

* Neutral, because it would deduplicate correctly.
* Bad, because it is a second object database next to the one already on disk.

## More Information

* `services/gitrepo.py` — the mirror, `materialize`, and `archive_tgz`.
* `services/storage.py::drop_snapshot_archives` — the purge.
* Renders are a separate question and are NOT covered here. They hold about
  469.1 MiB, of which `board.glb` is 396.3 MiB in 16 objects. 302.3 MiB of
  that belongs to commits that are neither current nor pinned by a production
  run, and renders are a `cached_op` cache that re-renders on demand.
* Revisit this if a project is ever ingested from something other than a git
  remote. An uploaded tree has no mirror to rebuild from, and it would need its
  own stored copy. `can_rebuild` already answers false for one, so the purge
  would keep its archive rather than destroy it.
* Three supporting changes landed with this, all because the missing mirror was
  invisible until it was looked for:
  * `gitrepo.materialize` now names the missing mirror instead of dying on its
    `cwd` with a bare `FileNotFoundError`, and deletes a half-made checkout
    rather than leaving an EMPTY directory that later reads as a checkout on
    disk. Production had exactly one of those.
  * The Projects page shows a `no mirror` pill whenever the mirror is absent.
    It used to say so only for a project with no snapshot, so a project that
    was ingested and later lost its mirror looked healthy.
  * There is no scheduled fetch: a mirror is written only by
    `POST /api/projects/{id}/fetch`, so a lost one never heals by itself.
