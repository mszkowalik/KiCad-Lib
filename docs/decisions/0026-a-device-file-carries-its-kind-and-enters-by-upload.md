---
status: "accepted"
date: 2026-09-17
decision-makers: Mateusz Kowalik
---

# A device file carries its kind, enters the pool by upload, and is never deleted while pinned

## Context and Problem Statement

The device-file pool (`device_files` / `device_file_versions`) was built for
berryware — the `.be` and `.json` payload a device downloads during
programming. When laser marking arrived (decision
[0020](0020-marking-goes-through-lightburn.md)), the LightBurn `.lbrn2` a
mark version engraves went into the same pool, because it is the same shape
of thing: project-scoped, versioned, content-addressed, pinned by a
deployment version through `deployment_files`.

Nothing in the data said which was which. Measured on 2026-09-17: every screen
that showed pinned files — the version card, the diff, the timeline line, the
bench summary, the pool itself — called them "berryware", the only way into
the pool from the UI was a paste-the-text editor that made a DRAFT and needed
a second click to publish, the one artwork on the platform had been added over
the API because pasting 150 kB of XML is not a workflow, and nothing told the
reader whether a file was in use before they tried to delete it.

Three questions had to be answered together: how the platform tells the two
kinds apart, how a file gets in, and when a file may leave.

## Decision Drivers

* A label must come from data, not from a guess at a call site — four
  screens guessing is four rules.
* One way in. The folder import already content-addresses, reuses unchanged
  bytes and publishes; a second upload path would drift from it.
* What a device was given is history. A file version pinned by a published
  deployment version is the record of what those units got.
* The pool can no longer promise every upload is a UTF-8 source file.

## Considered Options

**Telling the kinds apart**

* A `kind` column on `device_files`, fixed at upload
* Sniff the extension at each place that prints a label
* A separate table or store for artwork

**Getting a file in**

* Upload through the existing import endpoint, single file allowed
* Keep the paste editor, add an upload beside it
* Put the artwork's content or id inside the `mark_laser` step

**Letting a file out**

* Usage-guarded delete per version, newest first, with usage shown up front
* Soft delete — hide a version, keep the row
* Cascade delete — remove the version and every pin that names it

## Decision Outcome

Chosen: **a `kind` column**, **upload through the import endpoint**, and
**usage-guarded delete per version**.

`device_files.kind` is `berryware` or `artwork`, set when the file is created:
by the extension (`.lbrn` / `.lbrn2` is artwork, everything else berryware),
or by the editor that asked for it — the marking step's upload asks for
`artwork` outright and is refused anything that is not a LightBurn file.
Backfilled from the extension; the one artwork on the platform was the only
match. The engine hands the device only berryware and the laser only artwork,
and `validate.check` reads the same split, so a template typed by hand that
names a script is caught at publish.

`POST /projects/{id}/device-files/import` takes one file as well as a folder.
`make_bundle=false` keeps a single upload from minting a one-file bundle, and
artwork never joins a bundle in any case. `replace_file_id` makes the upload a
new version of an existing row under that row's name. An upload publishes.
The paste editor is gone from the UI; its endpoint stays for API callers and
still makes a draft. A file that is not UTF-8 text is kept as bytes
(`content_bytes`, `is_binary`) and served as bytes; text is still
LF-normalised so the same source always hashes the same.

Delete acts on ONE version, and the pool's row-level button takes the newest.
The server refuses with a 409 naming the deployment versions and bundles that
pin it, exactly as before; what is new is that the list says "not used" or
"in use" before the click, from the same join. A version pinned by any
deployment version — draft or published, current or historical — or carried
by any bundle is in use. Nothing is ever hidden or cascaded.

### Consequences

* Good, because every label — version card, diff, timeline, bench, pool — now
  prints what the file is, from one column.
* Good, because a file enters the pool the way it exists: as a file. Upload
  from the pool, upload from the marking step, import a folder — one server
  path, one content-addressing rule, one publish.
* Good, because a binary upload no longer fails with "berryware files are
  sources, not binaries".
* Bad, because a `.lbrn2` that a fleet was marked under can never be deleted,
  even after a better one replaces it. That is the point, and the "in use"
  pill says so before anyone tries.
* Bad, because a file with several unused versions takes several clicks to
  remove. Accepted deliberately: history leaves one row at a time.
* Neutral: `binary` is a reserved word in SQL, so the column is `is_binary`
  while the JSON key stays `binary`.

### Confirmation

`GET /api/flasher/projects/{id}/device-files` returns `kind` and `used` per
file and `used_by` per version. `GET .../deployments` returns `files_kind` per
version and a change summary that says "artwork (1 changed)" on a mark
version. An upload of the same bytes answers `state: "unchanged"`; a `.be`
sent with `kind=artwork` answers 400; a 15-byte blob with a NUL round-trips
byte-for-byte through `/files/{id}/{name}`; a DELETE on a pinned version
answers 409. All four were run against the local platform on 2026-09-17.

## Pros and Cons of the Options

### Sniff the extension at each call site

* Good, because no migration.
* Bad, because the version card, the diff, the timeline, the bench and the
  pool each get their own copy of the rule, and the marking editor cannot
  filter a pool it cannot ask.

### A separate table or store for artwork

* Good, because the berryware rules (autoexec last, bundles) never see it.
* Bad, because the version pins it through the same `deployment_files` link,
  the bench fetches it through the same `/files/{id}/{name}` route, and the
  fingerprint covers it — a second table would need all three again.

### Keep the paste editor beside an upload

* Good, because a one-line fix to a script needs no file on disk.
* Bad, because it is the second way in, it makes a draft while the upload
  publishes, and the source of every file in the pool is a file on disk. The
  Bundles tab's folder import is the berryware update path.

### Artwork content or id inside the step

* Good, because the step is self-contained.
* Bad, because the bench fetches by file-version id, the delete guard and the
  fingerprint read the pins, and a new artwork revision would become a
  procedure edit instead of a pin change. The step names a FILENAME and the
  version pins the exact content — that indirection is what lets artwork move
  without touching the procedure.

### Soft delete

* Good, because nothing is ever lost.
* Bad, because a hidden version still has to be served to the device and the
  bench, so "hidden" would mean a flag every reader has to remember to ignore.

### Cascade delete

* Bad, because it rewrites what published deployment versions pinned, which
  is the record of what units were given. Rejected outright.

## More Information

* [0020](0020-marking-goes-through-lightburn.md) — why the artwork is a device
  file at all.
* `api/app/services/flasher/CLAUDE.md` — the load-bearing rules this record
  settles, stated as rules.
* `web/src/components/flasher/CLAUDE.md` — the pool and the procedure editor.
