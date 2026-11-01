"""A skill body must not carry the local SKILL.md header.

On 2026-11-01 five of the eight skills stored their own frontmatter and an old
`<!-- platform-skill: … -->` stamp inside the body, because an agent published
the whole local file. `publish.check_skill_body` now refuses that at both doors.

No database: the check runs before the publish touches the session.

Run from `api/`:
    python -m pytest tests/library/test_skill_body.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest

from app.services import publish

BODY = "# Footprint conventions\n\nPull the JLC land for the exact LCSC code.\n"
HEADER = ('---\nname: kicad-conventions-footprints\ndescription: "Choosing footprints."\n---\n'
          "<!-- platform-skill: conventions-footprints v56 — source of truth is the platform -->\n")


def test_a_plain_body_passes():
    publish.check_skill_body(BODY)


def test_a_body_that_starts_with_a_horizontal_rule_passes():
    publish.check_skill_body("---\n\n" + BODY)


def test_the_whole_local_file_is_refused():
    with pytest.raises(ValueError, match="frontmatter"):
        publish.check_skill_body(HEADER + BODY)


def test_frontmatter_alone_is_refused():
    with pytest.raises(ValueError, match="frontmatter"):
        publish.check_skill_body('---\nname: x\ndescription: "y"\n---\n' + BODY)


def test_a_stamp_alone_is_refused():
    stamp = "<!-- platform-skill: conventions-footprints v56 — source of truth is the platform -->\n"
    with pytest.raises(ValueError, match="stamp"):
        publish.check_skill_body(stamp + BODY)


def test_publish_refuses_before_it_writes():
    """db=None: the check must fail before the first query, so a refused
    publish leaves no version row and no audit row behind."""
    with pytest.raises(ValueError, match="frontmatter"):
        publish.publish_skill_version(None, None, HEADER + BODY, actor="test")
