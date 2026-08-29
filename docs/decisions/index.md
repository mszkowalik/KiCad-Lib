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

## Proposed

| # | Decision | Area |
|---|---|---|

## Superseded

| # | Decision | Superseded by |
|---|---|---|
