"""3D model references inside a `.kicad_mod` — find them, resolve them on this
machine, and decide where they belong in the library.

A footprint drawn locally almost never points at the library: the user picks a
STEP out of ~/Downloads, out of KiCad's own `3dmodels/` tree, or out of a
project folder. The platform only accepts `${SEVENSIGMA_DIR}/3DModels/<rel>`
(services/geometry_proposals.py refuses anything else), so before this module a
push of such a footprint failed with a validation error and the user had to
upload the file by hand and retype the path.

Push now does that work: it reads every non-library model reference, finds the
file, uploads it to `/api/models3d/upload`, and rewrites the reference. This
module is the pure part of it — no I/O beyond `Path.is_file()`, so it is
testable on its own.

`suggest_rel_path` is duplicated in `mcp/server.py` (the `upload_model3d` tool)
because that script imports no app code. Change both together.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

MODEL_PREFIX = "${SEVENSIGMA_DIR}/3DModels/"

# Where a model with no better home goes. KiCad's own categories
# (`Package_SO.3dshapes`, `Capacitor_SMD.3dshapes`, …) are reused verbatim when
# the source file came from one; everything drawn or bought for a 7Sigma part
# lands here rather than loose at the root of 3DModels/, which is what the
# first 19 hand-uploaded files did.
HOUSE_DIR = "7Sigma.3dshapes"

SUFFIXES = (".step", ".stp", ".wrl")  # what /api/models3d/upload accepts

# KiCad always quotes the path. The bare form is accepted anyway — a
# hand-edited file is still a file we have to read.
_MODEL_RE = re.compile(r'\(\s*model\s+(?:"([^"]*)"|([^\s)]+))')
_VAR_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}|\$([A-Za-z0-9_]+)")


def model_paths(text: str) -> list[str]:
    """Every `(model …)` path in the footprint, in file order, with duplicates
    kept — one footprint may legitimately place the same solid twice."""
    return [q or bare for q, bare in _MODEL_RE.findall(text)]


def is_library_path(path: str) -> bool:
    return path.startswith(MODEL_PREFIX)


def rel_of(path: str) -> str:
    """The part after `${SEVENSIGMA_DIR}/3DModels/`, for a library path."""
    return path[len(MODEL_PREFIX):] if is_library_path(path) else ""


def var_names(path: str) -> list[str]:
    """Every `${VAR}` / `$VAR` name in the path. The caller decides what they
    mean — only it knows where KiCad installed things."""
    return [a or b for a, b in _VAR_RE.findall(path)]


def expand(path: str, variables: dict[str, str] | None = None,
           base_dir: Path | None = None) -> Path:
    """A path with `${VAR}`, `~` and relative segments resolved.

    `variables` wins over the process environment: KiCad's own path variables
    (`KICAD10_3DMODEL_DIR`, `KICAD10_3RD_PARTY`, …) are set inside KiCad's
    settings, not exported to the plugin's environment, so the caller passes
    what it can derive. An unknown variable is left in place, which makes the
    resulting path fail `is_file()` and surface as "cannot find" rather than
    silently resolving to something else.
    """
    variables = variables or {}

    def sub(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        return variables.get(name) or os.environ.get(name) or m.group(0)

    text = os.path.expanduser(_VAR_RE.sub(sub, path.strip()))
    p = Path(text)
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p
    return p


def resolve(path: str, variables: dict[str, str] | None = None,
            base_dir: Path | None = None) -> Path | None:
    """The file `path` names on this machine, or None when it is not there."""
    try:
        p = expand(path, variables, base_dir)
        return p if p.is_file() else None
    except OSError:
        return None


def suggest_rel_path(src: Path, existing: list[str] | None = None) -> str:
    """Where this file should live under `3DModels/`. Three rules, in order:

    1. The directory the footprint's CURRENT library model uses — replacing a
       model must not move it.
    2. The source file's own directory when it is a `*.3dshapes` folder — a
       model taken from KiCad's tree keeps KiCad's category, which is what
       every adopted Tier 0 footprint in the library already does.
    3. `HOUSE_DIR`.

    The basename is always the source file's own. Nothing here is enforced;
    the user edits the result in the push dialog.
    """
    for m in existing or []:
        rel = rel_of(m)
        if "/" in rel:
            return f"{rel.rsplit('/', 1)[0]}/{src.name}"
    if src.parent.name.endswith(".3dshapes"):
        return f"{src.parent.name}/{src.name}"
    return f"{HOUSE_DIR}/{src.name}"


def check_rel_path(rel: str) -> str | None:
    """The reason `rel` is not a usable library path, or None when it is."""
    rel = rel.strip().lstrip("/")
    if not rel:
        return "empty path"
    if ".." in rel.split("/"):
        return "must not contain '..'"
    if not rel.lower().endswith(SUFFIXES):
        return f"must end in one of {', '.join(SUFFIXES)}"
    return None


def rewrite_model_path(text: str, old: str, new: str) -> str:
    """Point every `(model "old" …)` at `new`, quoting the result.

    The quoted form is replaced whole, so a path that also appears in a comment
    or a property value is left alone.
    """
    out = text.replace(f'"{old}"', f'"{new}"')
    if out == text:  # unquoted in the source — put it back quoted
        out = re.sub(r'(\(\s*model\s+)' + re.escape(old) + r'(?=[\s)])',
                     lambda m: m.group(1) + f'"{new}"', text)
    return out
