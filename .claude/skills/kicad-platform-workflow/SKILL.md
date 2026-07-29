---
name: kicad-platform-workflow
description: "How changes become library: every write is a draft proposal, approval automatically regenerates the KiCad libraries and file mirror (there is no manual build), what mirror warnings mean, where the retired YAML pipeline went, and who handles platform setup. Use when asked how to publish, rebuild or regenerate."
---
<!-- platform-skill: platform-workflow v1 — source of truth is the platform; check with list_skills, refresh with get_skill -->

# Platform workflow — how changes become library

Postgres is the source of truth. Every symbol, footprint, component and skill is
a row with an append-only version history; the KiCad files people actually use
are **generated output**, never the master copy.

## Nothing is published directly

All writes to library data go in as **drafts**:

| Tool | Creates |
|---|---|
| `propose_new_component` / `propose_component_edit` | draft component version |
| `propose_symbol_edit` | draft base-symbol version (new name = creation) |
| `propose_footprint_edit` | draft footprint version (new name = creation) |
| `propose_skill_update` | draft skill version |

A draft changes nothing. The user reviews it in the **Proposals** view — with a
visual before/after for symbol and footprint drafts — and approves or rejects
it. Versions are immutable: approving advances a pointer, and any earlier
version can be restored, which is why approval is a cheap, reversible decision.

Skills edited directly in the web UI are the exception: the person editing *is*
the approval, so a UI save creates a new version and makes it current
immediately. Jaravis-proposed skill changes still go through Proposals.

## Approval regenerates everything automatically

There is **no manual build step and no pipeline to run.** On approval the
platform regenerates the affected KiCad symbol library and refreshes the file
mirror in-process. If someone asks how to rebuild or regenerate the library, the
answer is: approve the pending proposal — that *is* the regeneration.

Regeneration reports **mirror warnings** rather than failing the approval. The
usual one is `unresolved template {Key}` — a `ki_description` referencing a
property the component doesn't carry. The approval still lands; the warning
means the generated description is wrong and the component needs a follow-up
edit ([[add-component]]).

Downstream consumers read the generated state: the KiCad HTTP library endpoint,
the PCM package, and the published file mirror. None of them need a separate
publish action.

## Where the old YAML pipeline went

The library used to be generated from `Sources/*.yaml` by a script at the repo
root. That pipeline is **retired** — it lives with its full history on the
`archive/yaml-library` branch. Postgres is the source of truth now. Don't tell
anyone to run `main.py`, edit YAML sources, or regenerate from files; those
instructions are stale.

The import station endpoints still exist for a clean cutover:
`POST /api/import` is **destructive** (wipes and reloads everything from YAML,
writing rows directly as published) and `POST /api/import/sync` is
non-destructive (diffs YAML against the DB and files draft proposals). Neither
is part of normal work — treat the destructive one as off-limits unless the user
explicitly asks for a full reload.

## Running the platform itself

Setting up, configuring, or hosting the platform is a shell task, outside what
the library tools cover. Jaravis has no shell, no filesystem and no Python
environment — it acts only through its tools, so installation and deployment
questions belong with the platform README or an administrator, not in chat.

An agent that *does* have a shell and the repository (e.g. Claude Code) runs it
with `docker compose up -d --build`; the web UI is on port 5173 and the API on
8020, and the api/web containers live-mount their sources so edits hot-reload.
Read the repo's `CLAUDE.md` files before changing platform code.

## Related

[[add-component]] — the procedure that produces these drafts.
[[conventions-symbols]] / [[conventions-footprints]] — what a good draft looks like.

