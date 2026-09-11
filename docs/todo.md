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

## More information

* [decisions/index.md](decisions/index.md) — decisions still `proposed`.
* [CLAUDE.md](../CLAUDE.md) — how a finding routes to a decision, a skill, a
  checklist item or this file.
