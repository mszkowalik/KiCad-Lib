#!/usr/bin/env python3
"""Mirror the platform's database-hosted skills into `.claude/skills/`.

The skill documents are rows in Postgres, editable in the web UI and by Jaravis
(via approved proposals) — so they change under us. Claude Code only discovers
skills as files on disk, so this script pulls `GET /api/skills` and writes one
`.claude/skills/kicad-<name>/SKILL.md` per skill.

Wired to two hooks in `.claude/settings.json`:
  SessionStart      — full sync when a session starts/resumes/clears
  UserPromptSubmit  — `--quick` re-check before every prompt (one localhost GET)

Freshness: a skill's *body* is read from disk when the skill is invoked, so a
mid-session edit in the web UI is picked up on the next invocation. A changed
*description* only reaches the model's skill list at the next session start,
because Claude Code injects that list once per session.

Change detection is cheap: the list endpoint carries `current_version_no` and
`description`, and only skills whose pair differs from `.sync-manifest.json`
are re-fetched. If the API is unreachable the script exits 0 in silence and the
last-synced files stay in place — a stale skill beats no skill, and a dead API
must never block a prompt.

Run by hand:  python3 .claude/sync-skills.py [--quick] [--force]
Environment:  KICAD_API_URL (default http://localhost:8020)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_URL = os.environ.get("KICAD_API_URL", "http://localhost:8020").rstrip("/")
TOKEN = os.environ.get("KICAD_MCP_TOKEN", "").strip()

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
MANIFEST = SKILLS_DIR / ".sync-manifest.json"
# Written into every generated directory; only directories carrying it are ever
# deleted, so a hand-written skill can never be removed by this script.
MARKER = ".synced-from-db"
PREFIX = "kicad-"

QUICK = "--quick" in sys.argv
FORCE = "--force" in sys.argv
TIMEOUT = 2.0 if QUICK else 10.0


def fetch(path: str, timeout: float):
    req = urllib.request.Request(API_URL + path, headers={"accept": "application/json"})
    if TOKEN:
        req.add_header("authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def slug(name: str) -> str:
    """Claude Code skill names are lowercase alphanumerics and hyphens."""
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "unnamed"


def fallback_description(content: str) -> str:
    """First real paragraph, for a skill whose description is still empty."""
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", ">", "-", "*", "|", "`")):
            return line[:400]
    return "A 7Sigma KiCad library skill document."


def yaml_quote(text: str) -> str:
    flat = " ".join(text.split())
    return '"' + flat.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(skill: dict, content: str) -> str:
    name = skill["name"]
    desc = (skill.get("description") or "").strip() or fallback_description(content)
    version = skill.get("current_version_no")
    return (
        "---\n"
        f"name: {PREFIX}{slug(name)}\n"
        f"description: {yaml_quote(desc)}\n"
        "---\n\n"
        f"{content.strip()}\n\n"
        "---\n\n"
        f"*Generated from the 7Sigma platform database — skill `{name}` v{version}. "
        "Edit it in the web UI (Skills view) or propose a change with the "
        "`propose_skill_update` tool; edits to this file are overwritten on the next sync.*\n"
    )


def main() -> int:
    try:
        listing = fetch("/api/skills", TIMEOUT)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0  # API down — keep whatever was synced last.

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        manifest = json.loads(MANIFEST.read_text())
    except (OSError, ValueError):
        manifest = {}

    written, removed = [], []
    new_manifest: dict[str, dict] = {}

    for skill in listing:
        dirname = PREFIX + slug(skill["name"])
        stamp = {
            "version_no": skill.get("current_version_no"),
            "description": skill.get("description") or "",
        }
        new_manifest[dirname] = stamp
        target = SKILLS_DIR / dirname / "SKILL.md"
        if not FORCE and manifest.get(dirname) == stamp and target.exists():
            continue
        try:
            detail = fetch(f"/api/skills/{skill['id']}", TIMEOUT)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            # Leave this one's manifest entry as it was so the next run retries.
            new_manifest[dirname] = manifest.get(dirname, {})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        (target.parent / MARKER).write_text(skill["name"] + "\n")
        target.write_text(render(skill, detail.get("content") or ""))
        written.append(skill["name"])

    # Drop skills that no longer exist in the database (ours only — see MARKER).
    for child in SKILLS_DIR.iterdir():
        if child.is_dir() and child.name not in new_manifest and (child / MARKER).exists():
            shutil.rmtree(child)
            removed.append(child.name)

    MANIFEST.write_text(json.dumps(new_manifest, indent=2, sort_keys=True) + "\n")

    if written or removed:
        parts = []
        if written:
            parts.append(f"updated {', '.join(sorted(written))}")
        if removed:
            parts.append(f"removed {', '.join(sorted(removed))}")
        print(f"[skills] synced from {API_URL}: {'; '.join(parts)}")
    elif not QUICK:
        print(f"[skills] {len(new_manifest)} skills up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
