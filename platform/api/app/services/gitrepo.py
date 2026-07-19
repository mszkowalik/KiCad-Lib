"""Git operations for project repos — plain `git` CLI over HTTPS, provider
agnostic (GitHub / GitLab / Gitea / any smart-HTTP remote).

Each project keeps a bare mirror clone at DATA_DIR/git/<project_id>.git.
Credentials are NEVER written to disk: the stored (encrypted) token is
injected per invocation as a Basic auth header ("oauth2:<token>", accepted
by GitHub, GitLab and Gitea alike). All reads (log, tags, archive, show)
run against the local mirror and need no network.
"""
from __future__ import annotations

import base64
import os
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from ..config import settings


class GitError(RuntimeError):
    pass


def mirror_path(project_id: int) -> Path:
    return settings.git_dir / f"{project_id}.git"


def _auth_args(git_url: str, token: str | None) -> list[str]:
    if not token:
        return []
    basic = base64.b64encode(f"oauth2:{token}".encode()).decode()
    return ["-c", f"http.extraheader=AUTHORIZATION: basic {basic}"]


def _run(args: list[str], cwd: Path | None = None, timeout: int = 300) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or proc.stdout.strip() or f"git {args[0]} failed")
    return proc.stdout


def fetch_mirror(project_id: int, git_url: str, token: str | None) -> None:
    """Clone the mirror if missing, else fetch (prune deleted refs)."""
    path = mirror_path(project_id)
    settings.git_dir.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _run([*_auth_args(git_url, token), "clone", "--mirror", git_url, str(path)], timeout=1800)
    else:
        # keep origin URL current in case it was edited on the project
        _run(["remote", "set-url", "origin", git_url], cwd=path)
        _run([*_auth_args(git_url, token), "fetch", "--prune", "origin"], cwd=path, timeout=1800)


def has_mirror(project_id: int) -> bool:
    return mirror_path(project_id).exists()


def rev_parse(project_id: int, ref: str) -> str:
    return _run(["rev-parse", f"{ref}^{{commit}}"], cwd=mirror_path(project_id)).strip()


def log(project_id: int, ref: str = "HEAD", limit: int = 100) -> list[dict]:
    """[{sha, author, date, message, refs}] — newest first."""
    sep = "\x1f"  # NUL is illegal inside an argv string
    out = _run(
        ["log", f"--format=%H{sep}%an{sep}%aI{sep}%s{sep}%D", "-n", str(limit), ref, "--"],
        cwd=mirror_path(project_id),
    )
    commits = []
    for line in out.splitlines():
        parts = line.split(sep)
        if len(parts) != 5:
            continue
        sha, author, date, message, refs = parts
        commits.append(
            {
                "sha": sha,
                "author": author,
                "date": date,
                "message": message,
                "refs": [r.strip() for r in refs.split(",") if r.strip()],
            }
        )
    return commits


def tags(project_id: int) -> list[dict]:
    """[{name, sha, date}] — sha is the dereferenced commit, newest first."""
    out = _run(
        [
            "for-each-ref",
            "refs/tags",
            "--sort=-creatordate",
            "--format=%(refname:short)\x1f%(if)%(*objectname)%(then)%(*objectname)%(else)%(objectname)%(end)\x1f%(creatordate:iso-strict)",
        ],
        cwd=mirror_path(project_id),
    )
    result = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            result.append({"name": parts[0], "sha": parts[1], "date": parts[2]})
    return result


def branches(project_id: int) -> list[dict]:
    out = _run(
        ["for-each-ref", "refs/heads", "--format=%(refname:short)\x1f%(objectname)"],
        cwd=mirror_path(project_id),
    )
    result = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 2:
            result.append({"name": parts[0], "sha": parts[1]})
    return result


def checkout_path(project_id: int, sha: str) -> Path:
    return settings.checkouts_dir / str(project_id) / sha


def materialize(project_id: int, sha: str) -> Path:
    """Extract the tree at `sha` into the shared checkouts dir (idempotent —
    reused by render-on-demand; safe to delete anytime)."""
    dest = checkout_path(project_id, sha)
    marker = dest / ".complete"
    if marker.exists():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar") as tf:
        proc = subprocess.run(
            ["git", "archive", "--format=tar", sha],
            cwd=mirror_path(project_id),
            stdout=tf,
            stderr=subprocess.PIPE,
            timeout=600,
        )
        if proc.returncode != 0:
            raise GitError(proc.stderr.decode().strip())
        tf.seek(0)
        with tarfile.open(fileobj=tf) as tar:
            tar.extractall(dest, filter="data")
    marker.touch()
    return dest


def archive_tgz(project_id: int, sha: str) -> bytes:
    """tar.gz of the tree at sha — stored in MinIO as the snapshot backup."""
    proc = subprocess.run(
        ["git", "archive", "--format=tar.gz", sha],
        cwd=mirror_path(project_id),
        capture_output=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise GitError(proc.stderr.decode().strip())
    return proc.stdout


def list_files(project_id: int, sha: str) -> list[dict]:
    out = _run(["ls-tree", "-r", "--long", sha], cwd=mirror_path(project_id))
    files = []
    for line in out.splitlines():
        # <mode> <type> <object> <size>\t<path>
        try:
            meta, path = line.split("\t", 1)
            size = meta.split()[3]
            files.append({"path": path, "size": None if size == "-" else int(size)})
        except (ValueError, IndexError):
            continue
    return files


def show_file(project_id: int, sha: str, path: str) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        cwd=mirror_path(project_id),
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise GitError(proc.stderr.decode().strip())
    return proc.stdout


def commit_info(project_id: int, sha: str) -> dict:
    out = _run(
        ["show", "-s", "--format=%H\x1f%an\x1f%aI\x1f%s", sha],
        cwd=mirror_path(project_id),
    ).strip()
    parts = out.split("\x1f")
    return {
        "sha": parts[0],
        "author": parts[1] if len(parts) > 1 else "",
        "date": parts[2] if len(parts) > 2 else "",
        "message": parts[3] if len(parts) > 3 else "",
    }


def parse_iso(date_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None
