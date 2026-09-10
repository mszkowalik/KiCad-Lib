---
status: accepted
date: 2026-09-10
decision-makers: Mateusz Kowalik
consulted: Claude (measurements on the live library and on 20 vendor sites)
---

# Store each datasheet once and version it by its text, not its bytes

## Context and Problem Statement

The platform re-checks every datasheet URL each night and keeps an immutable
copy of every download. Two facts, both measured on 2026-09-10, made that
history wrong. First, TI re-signs every PDF about every two days (new
`ModDate`, new sha256, identical text) and generates the package addendum at
download time, so one TPS61023 datasheet had 37 stored copies, each of which
bumped the component to a new version and dropped its review record. Second,
three TPS7A20 variants each held the same 2.4 MB TI file, 14 copies each. The
user also wants to register a manufacturer page, not only a PDF, and be told
when a new revision appears. Which identity should a stored datasheet have,
and where should its bytes live?

## Decision Drivers

* The pin table must keep answering "which PDF was used in which component
  version".
* A re-signed or re-generated PDF must not create a version, bump a
  component, or drop a verification.
* A real revision must reach a human: the review record must not carry, and
  the change must appear on the worklist with the pages that changed.
* The same file linked by several components must be stored once.
* Vendors block plain HTTP inconsistently (measured: Infineon and Nexperia
  refuse `curl`, onsemi refuses a browser string, Microchip, ST and Analog
  Devices refuse both), so the fetcher needs a per-host strategy.

## Considered Options

* Keep the byte identity and suppress TI by hand (ignore `ModDate`).
* Hash the extracted text of every page, in order.
* Hash the text with per-page roles, so the pages a vendor generates at
  download time are compared by what is stable on them.
* Keep the bytes on the version row, or move them to a content-addressed
  table.

## Decision Outcome

Chosen: text identity with page roles, bytes in a content-addressed
`documents` table, versions as thin history rows that point at a document.

Hashing the text in order is not enough on its own. TI appends the tail of
every datasheet at download time, and measuring the 14 stored fetches of one
TPS7A20 Rev. H showed three separate kinds of noise: a date stamp in every
tail header, a "PACKAGE MATERIALS INFORMATION" logistics table whose reel
dimensions drift between fetches, a "PACKAGE OPTION ADDENDUM" catalog table
whose rows reorder and whose lead-finish cell flips back and forth between
consecutive downloads, and per-package drawing sections that come out in a
different order each time. So `page_identity` gives every page one of four
roles:

| Role | Pages | How it counts |
|---|---|---|
| body | everything before the first generated page | hashed in order |
| addendum | `PACKAGE OPTION ADDENDUM` | reduced to the document's set of (orderable part, lifecycle status) pairs |
| unordered | drawings, board layouts, the notice | hashed as a multiset |
| volatile | `PACKAGE MATERIALS INFORMATION` | excluded |

The part/status set was stable across all 14 fetches and caught the one real
event in them: TI adding `TPS7A20125PYCKR` and `TPS7A2029PYCKR`. That is also
the lifecycle signal the platform wants, arriving for free.

`Document.text_sha256` is the revision key. A scan has no text and compares by
bytes. `fetch_datasheet` decides in this order: 304, same bytes, same text
(`restamped`, nothing stored), bytes already held (`relinked`, a version that
points at the existing document), otherwise a new document and a new version.
A new version on a published component bumps it through the shared publish
path. `review.carry_component` refuses the carry when a pinned datasheet moved
to a document with a different text hash, and the bump opens a review request
whose note lists the revision labels, the pages that are new or edited, how
many drawings were removed, and whether the part table moved. `parse_revision`
produces a label for people and never decides anything.

Two smaller rules fall out of the same work. The leading bytes decide whether
a file is a PDF, ahead of its content type and its name: LCSC serves its
"document not available" page as `C10425.pdf` with `Content-Type: text/html`,
and 186 such pages were stored and filed as unsearchable scans. And the
fetcher tries the user agent remembered for the host, then the other one on a
refusal, recording what worked in `fetch_hosts`.

The migration runs once at startup, in SQL. `POST
/api/datasheets/restamps/collapse` folds the history the byte rule wrote: pins
move to the surviving version, orphaned documents are deleted, component
versions created by the old bumps stay as history. Both end in a `VACUUM FULL`
(`reclaim_space`, in a thread outside startup) because a dropped blob stays on
disk until the table is rewritten.

### Consequences

* Good, because a re-signed PDF costs one audit row and nothing else.
* Good, because a document shared by several parts is stored and indexed once,
  and the UI can show which parts share it.
* Good, because a real revision is a review event with a page list, and the
  verification that rested on the old revision does not survive it silently.
* Bad, because the page roles encode TI's tail layout. Another vendor that
  generates pages at download time will produce false versions until its
  pattern is added to `page_identity`. The review request's page list is what
  makes such a case visible, and the roles are one function to extend.
* Bad, because the revision label is a heuristic. It is shown, never trusted.
* Neutral: the manufacturer-page watch (candidate documents, lifecycle words,
  a headless browser for pages that need one) is not part of this record. It
  builds on this identity and is a separate decision.

### Confirmation

Measured 2026-09-10 on a local copy of the production library, before and
after:

| | Before | After |
|---|---|---|
| Stored versions | 704 | 616 |
| Distinct stored files | 557 | 484 |
| Page rows | 11685 | 8588 |
| Datasheet tables | 904 MB | 602 MB |
| Whole database | 1682 MB | 1394 MB |
| TPS61023 versions of one Rev. B | 37 | 1 |
| TPS7A20 versions of one Rev. H | 14 | 2 |

* `POST /api/datasheets/129/fetch` on TPS61023 answers `restamped` while TI
  serves new bytes with the same text.
* Every difference that survives is real: two TI parts added to a catalog
  table, three TSSOP drawing pages removed from TXS0104E and TXS0108E, one
  replaced drawing on LMR33630, and the genuine OPA354 F→G→H and ESP32
  revisions.
* `GET /api/datasheets/restamps` returns nothing after the collapse.
* A simulated revision on a verified component (test script, rolled back)
  publishes a system version carrying only the machine record, refuses the
  carry with "datasheet 'Datasheet' changed", and opens a review request
  naming the pages.
* Referential check after the collapse: no dangling `current_version_id`, no
  dangling pin, no version without a document, no orphaned document.
* `fetch_hosts` holds the browser string for Infineon and Nexperia and
  `curl/8.1` for TI and LCSC, learned by the retry.
