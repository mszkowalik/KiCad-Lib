"""A project's files at one commit: the list and the file itself, read from the
local git mirror.

Run from `api/`, with the dev database up:
    python -m pytest tests/projects -q
"""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import projects as router
from app.services import gitrepo


@pytest.fixture
def db():
    """One transaction, never committed: the dev database is left untouched."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def project(db: Session, tmp_path, monkeypatch):
    monkeypatch.setattr(gitrepo, "mirror_path", lambda project_id: tmp_path / f"{project_id}.git")
    p = M.Project(name="test-project-files", git_url="https://example.invalid/files.git")
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def sha(project, tmp_path):
    """A mirror with one commit: a PDF, text with no known type, a binary, an SVG
    and a name with a Polish letter, which git would quote without `-z`."""
    repo = tmp_path / f"{project.id}.git"
    (repo / "docs").mkdir(parents=True)
    files = {"docs/board.PDF": b"%PDF-1.7\n", "main.kicad_sch": b"(kicad_sch)\n", "logo.bin": b"\x00\x01\x02",
             "logo.svg": b"<svg/>", "docs/Płytka.txt": b"hello\n"}
    for name, data in files.items():
        (repo / name).write_bytes(data)

    def git(*args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=repo,
                              check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "one")
    return git("rev-parse", "HEAD")


def test_a_project_with_no_mirror_gets_a_sentence_and_not_a_500(db, project):
    for call in (lambda: router.project_files(project.id, "abc", db=db),
                 lambda: router.project_file(project.id, "abc", "a.txt", db=db)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 409 and "not fetched" in e.value.detail


def test_the_list_names_every_file_with_its_size_and_a_usable_path(db, project, sha):
    got = {f["path"]: f["size"] for f in router.project_files(project.id, sha, db=db)}
    assert got == {"docs/board.PDF": 9, "main.kicad_sch": 12, "logo.bin": 3, "logo.svg": 6, "docs/Płytka.txt": 6}
    # What the list prints is what the file route takes.
    assert router.project_file(project.id, sha, "docs/Płytka.txt", db=db).body == b"hello\n"


def test_a_file_is_served_inline_with_its_own_name_and_type(db, project, sha):
    def served(path):
        r = router.project_file(project.id, sha, path, db=db)
        return r.media_type, r.headers["content-disposition"]

    assert served("docs/board.PDF") == ("application/pdf", 'inline; filename="board.PDF"')
    assert served("main.kicad_sch") == ("text/plain; charset=utf-8", 'inline; filename="main.kicad_sch"')
    assert served("logo.bin") == ("application/octet-stream", 'inline; filename="logo.bin"')
    # Latin-1 cannot carry the Polish letter, so the header states it in `filename*`.
    media, disposition = served("docs/Płytka.txt")
    assert media.startswith("text/plain") and "filename*=UTF-8''P%C5%82ytka.txt" in disposition


def test_a_repository_svg_cannot_run_as_a_page_of_this_origin(db, project, sha):
    r = router.project_file(project.id, sha, "logo.svg", db=db)
    assert r.media_type == "image/svg+xml" and r.headers["content-security-policy"] == "sandbox"


def test_a_sha_that_reads_as_a_git_option_is_refused(db, project, sha):
    with pytest.raises(HTTPException) as e:
        router.project_file(project.id, "--output=/tmp/x", "a.txt", db=db)
    assert e.value.status_code == 422


def test_a_commit_the_mirror_does_not_hold_is_a_404(db, project, sha):
    with pytest.raises(HTTPException) as e:
        router.project_files(project.id, "0" * 40, db=db)
    assert e.value.status_code == 404
