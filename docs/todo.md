# Work list

What the platform still needs: built, fixed or decided. One row per item, with
the reason it matters and what proves it done.

**This file holds open work only.** Ask before you add a row, unless the user
asked for that item first. Delete a row when it is done — record the result in
its proper home: a [decision record](decisions/index.md), a
`.claude/skills/` update via `propose_skill_update`, or
[CHANGELOG.md](../CHANGELOG.md). Git and the changelog hold what a deleted row
said. Never strike a row through and leave it.

**This file holds work, not facts.** A choice still to make goes to a proposed
[decision record](decisions/index.md) instead. A row here can point at one.

## Open

| # | Item | Why | Done when |
|---|---|---|---|
| 1 | Draw mechanical footprints for the three Italtronic enclosures — `Italtronic_05.0502530`, `Italtronic_35.0207000.BL`, `Italtronic_P05050201P.BL` | Every other `Mechanical_7S` enclosure has its own land (`Enclosure_Hammond_1551RFLGY`, `_1551TFLGY`, `_1551XFLGY`, `_1556CGY`, `Enclosure_TAKACHI_SIM6-12-3W`); these three are the only members of the family without one, so their outline and keepout are invisible on a layout. Raised by a review pass on 2026-08-25 and still flagged on all three parts. [Decision 0005](decisions/0005-off-board-parts.md) stopped the machine tier failing them but deliberately did not settle this — assigning a footprint puts each part back on the board automatically, so the two are compatible in either order | A footprint exists for each of the three, is assigned, and the `custom:footprint-missing-enclosure` flag on each part is answered rather than left open |
| 2 | Run the datasheet clean-up on production: deploy, let the startup migration move the bytes, then `POST /api/datasheets/restamps/collapse` | The code is committed but production still carries the old schema and the history the byte rule wrote — 704 versions over 557 distinct files, 1079 MB in `datasheet_versions`, 1981 MB of database. The local rehearsal on a copy of that data gave 616 versions over 484 files and 602 MB, and the server has 75 GB free, so the table rewrite has room. The migration is idempotent and the collapse refuses to run while the classification backfill is still going ([decision 0004](decisions/0004-datasheet-identity-and-storage.md)) | `GET /api/datasheets/restamps` on production returns nothing, `GET /api/datasheets/storage` reports fewer documents than versions, and the referential check finds no dangling pin, current version or orphan |
| 3 | Watch a manufacturer's product page, not only its PDF: register a page URL per component, re-open it on a schedule, and report new documents and lifecycle changes as findings | The original request behind [decision 0004](decisions/0004-datasheet-identity-and-storage.md), which built only the identity it needs. Measured 2026-09-10 over 20 vendor sites: a plain HTTP scrape finds the datasheet link on 3 of 17 pages, headless Chromium raises that to about 7, and Microchip, Analog Devices and ST refuse both from this network — so resolving a page must be a one-off step with a human or the agent confirming the document, while the nightly job stays a conditional GET on the resolved PDF. Chromium is in no image today. The orderable-part and lifecycle table the identity hash already extracts from a TI datasheet is the same signal, arriving for free | A component can carry a watched page URL, a scheduled pass reports a new document or a status change as a review finding rather than attaching it automatically, and a page the fetcher cannot reach is reported as unreachable instead of unchanged |
## More information

* [decisions/index.md](decisions/index.md) — decisions still `proposed`.
* [CLAUDE.md](../CLAUDE.md) — how a finding routes to a decision, a skill, a
  checklist item or this file.
