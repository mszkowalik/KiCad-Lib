#!/usr/bin/env python3
"""Check the agent instruction files against the rules they state.

The rules live in docs/reference/writing-instruction-files.md. This script
enforces the three that a machine can decide:

  1. Every CLAUDE.md stays under the line budget (200 lines, warn above).
  2. Every relative markdown link resolves to a real file.
  3. No CLAUDE.md uses an @path import, which loads at launch and defeats
     the per-directory split.

It also refuses a CLAUDE.md over the size at which Claude Code warns about a
large memory file (~40,000 characters), and reports a heading that repeats its
own file title, which is what a careless move leaves behind.

Exit status 1 means something must be fixed. A line-budget overrun is a
warning and does not fail the run.
"""
from __future__ import annotations

import os
import re
import sys

LINE_BUDGET = 200
CHAR_LIMIT = 40_000
SKIP_DIRS = {".git", "node_modules", "dist", ".venv", "__pycache__", "easyeda_tmp"}

LINK = re.compile(r"\[[^\]]*\]\((?!https?:|mailto:|#)([^)\s#]+)")
IMPORT = re.compile(r"(?<![`\w])@[\w./~-]+")
FENCE = re.compile(r"```.*?```", re.S)
CODESPAN = re.compile(r"`[^`\n]*`")


def walk(root: str, name: str | None = None, suffix: str | None = None):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if (name and f == name) or (suffix and f.endswith(suffix)):
                yield os.path.join(base, f)


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    errors: list[str] = []
    warnings: list[str] = []

    claude_files = sorted(walk(".", name="CLAUDE.md"))
    reference = sorted(walk("docs/reference", suffix=".md"))

    for path in claude_files:
        text = open(path, encoding="utf-8").read()
        lines = text.count("\n") + 1
        chars = len(text)
        if chars > CHAR_LIMIT:
            errors.append(
                f"{path}: {chars} characters, over the {CHAR_LIMIT} limit at which "
                f"Claude Code warns about a large memory file. Split it."
            )
        elif lines > LINE_BUDGET:
            warnings.append(
                f"{path}: {lines} lines, over the {LINE_BUDGET}-line budget. "
                f"Split it by directory, or move the long form to docs/reference/."
            )
        stripped = CODESPAN.sub("", FENCE.sub("", text))
        for m in IMPORT.finditer(stripped):
            errors.append(
                f"{path}: '{m.group(0)}' reads as an @path import, which loads at "
                f"launch whatever the task is. Use an ordinary markdown link."
            )

    for path in claude_files + reference:
        base = os.path.dirname(path)
        text = open(path, encoding="utf-8").read()
        for m in LINK.finditer(text):
            target = os.path.normpath(os.path.join(base, m.group(1)))
            if not os.path.exists(target):
                errors.append(f"{path}: link to '{m.group(1)}' resolves to nothing.")
        head = text.split("\n", 1)[0].lstrip("# ").strip().lower()
        for line in text.split("\n")[1:12]:
            if line.startswith("#") and line.lstrip("# ").strip().lower() == head:
                errors.append(f"{path}: heading repeats the file title ('{head}').")

    for line in warnings:
        print(f"warning: {line}")
    for line in errors:
        print(f"error: {line}")

    print(
        f"\nchecked {len(claude_files)} CLAUDE.md and {len(reference)} reference pages: "
        f"{len(errors)} errors, {len(warnings)} warnings"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
