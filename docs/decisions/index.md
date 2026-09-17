# Decision records

This folder holds architecture and process decisions about the **7Sigma KiCad
Library Platform** itself — deployment, backend/frontend architecture, access
control, the agent workflow. It does not hold component or library
conventions: those live in the platform's **skill documents**, versioned in
Postgres and mirrored to `.claude/skills/` (see the root
[CLAUDE.md](../../CLAUDE.md), section "Skills").

The format is [MADR 4.0.0](https://adr.github.io/madr/). The file name pattern
is `NNNN-title-with-dashes.md`, four digits, no gaps skipped on purpose.

## Rules

1. Write a record when a change adds an external dependency, changes the
   deployment or access-control model, or would be expensive to reverse.
2. Put the record in the same commit as the change it describes.
3. **Never edit an accepted record.** To reverse a decision, write a new
   record and set the old one's `status` to `superseded by NNNN`. Move its row
   to the "Superseded" table below.
4. Copy [adr-template.md](adr-template.md) to start a new record. Before you
   do, check no file already claims the next number:
   `ls docs/decisions/NNNN-*`.
5. Set `status` to `accepted`, or to `proposed` if the decision still needs
   agreement.
6. Add a row to the matching table below in the same commit.

## Accepted

| # | Decision | Area |
|---|---|---|
| [0001](0001-generate-package-sim-wrappers-from-blocks.md) | Generate a package simulation wrapper from blocks, instead of writing it | Backend, simulation |
| [0002](0002-field-solver-in-the-platform.md) | The field solver lives in the platform, and its stackups are project data | Backend, frontend, projects |
| [0003](0003-orders-shipments-and-device-history.md) | Sales orders, shipments and a per-device history replace the sale fields on a run | Backend, frontend, production, flasher |
| [0004](0004-datasheet-identity-and-storage.md) | Store each datasheet once and version it by its text, not its bytes | Backend, datasheets, review |
| [0005](0005-off-board-parts.md) | Treat a part as off-board when its base symbol declares it and it has no land pattern | Backend, KiCad output, review |
| [0006](0006-sync-button-owns-library-updates.md) | Update installed KiCad libraries through the Sync button, and leave the PCM to the plugin | KiCad client, sync plugin, deployment |
| [0007](0007-built-means-finished-and-passed.md) | Count a batch by the devices that passed, not by the quantity typed on it (overrides item 8 of [0003](0003-orders-shipments-and-device-history.md)) | Backend, frontend, production, flasher |
| [0008](0008-a-stackup-is-electrical-only.md) | A stackup describes conduction only; appearance and impedance work are project data (extends [0002](0002-field-solver-in-the-platform.md)) | Backend, frontend, field solver, projects |
| [0009](0009-the-git-mirror-is-the-source-archive.md) | Keep project source in the git mirror only, and stop storing a tarball per snapshot | Backend, projects, storage, deployment |
| [0010](0010-a-git-token-belongs-to-an-account.md) | A git token belongs to an account, and projects point at it by name | Backend, frontend, projects, access control |
| [0011](0011-retire-the-skipped-verification-result.md) | Retire the `skipped` verification result; an unverifiable item is left unanswered and `na` carries a reason | Backend, frontend, review axis, agent tools |
| [0012](0012-rename-a-footprint-or-base-symbol-in-place.md) | Rename a footprint or a base symbol in place, and rewrite every reference with it | Backend, frontend, KiCad output, review axis, agent tools |
| [0013](0013-the-validator-owns-the-automatic-checks.md) | The validator owns the automatic checks, and a checklist switches them on or off per category | Backend, frontend, review axis, agent tools |
| [0014](0014-a-check-carries-its-own-configuration.md) | A check carries its own configuration, and the rules table is retired (completes [0013](0013-the-validator-owns-the-automatic-checks.md)) | Backend, frontend, review axis |
| [0015](0015-a-check-says-which-subjects-it-is-about.md) | A check says which subjects it is about — a `when` predicate that NARROWS, plus named variants on one discriminator (completes [0014](0014-a-check-carries-its-own-configuration.md)) | Backend, frontend, review axis, agent tools |
| [0016](0016-severity-and-standing-exceptions.md) | A check has a severity, and a subject can carry a standing exception — both copied from KiCad's DRC/ERC model | Backend, frontend, review axis, agent tools |
| [0017](0017-conformance-is-computed-not-recorded.md) | Conformance is computed on read and cached against a digest of its inputs, never recorded on publish | Backend, frontend, review axis |
| [0018](0018-does-not-apply-is-an-exception-not-an-answer.md) | "Does not apply" is a standing exception, not a per-version `na` answer — one control, and it works on an item nobody has answered | Backend, frontend, review axis, agent tools |
| [0019](0019-a-classification-carries-the-first-time-it-is-set.md) | A classification key carries the first time it is set — filling in `comp_type` costs no verification, changing one still does | Backend, review axis |
| [0020](0020-marking-goes-through-lightburn.md) | Drive the laser through LightBurn and a local agent, not a direct controller driver — the BSL board's protocol is not the open-source LMC one | Backend, frontend, production, external dependency |
| [0021](0021-a-device-is-judged-by-the-rule-it-was-made-under.md) | Judge a device by the rule its batch carried, and pin that rule on every programming run (refines [0007](0007-built-means-finished-and-passed.md)) | Backend, frontend, production, flasher |
| [0022](0022-labels-are-generated-by-the-bench-agent.md) | Print labels through CUPS and lay them out in the bench agent, with no template file and no vendor software (extends [0020](0020-marking-goes-through-lightburn.md)) | Backend, frontend, production, flasher |
| [0023](0023-the-agent-programs-the-device.md) | Do every byte of bench serial work in the agent, with esptool vendored inside it, and drop Web Serial entirely | Backend, frontend, production, flasher, external dependency |
| [0024](0024-a-version-declares-the-parameters-it-needs.md) | A version declares the parameters it needs, and a parameter set keeps an append-only revision log (supplies the half 2026-07-27 left out) | Backend, frontend, production, flasher |
| [0025](0025-a-device-fetches-from-its-own-address.md) | A device fetches from its own address, and on this deployment that address is plain HTTP — Tasmota completes no TLS against the edge and validates no certificate | Backend, production, flasher, deployment |
| [0026](0026-a-device-file-carries-its-kind-and-enters-by-upload.md) | A device file carries its kind (berryware or artwork), enters the pool by upload through the import endpoint, and is never deleted while a version or a bundle pins it | Backend, frontend, production, flasher |

## Proposed

| # | Decision | Area |
|---|---|---|

## Superseded

| # | Decision | Superseded by |
|---|---|---|
