"""Safe `{Property}` template resolution.

The legacy pipeline evaluated property templates as raw f-strings via eval()
(kicad_lib/yaml/parser.py) — every template in the sources is a plain
`{Key}` substitution, so this port replaces eval with regex substitution:
same behavior for all real data, no code execution, and unresolved keys are
reported instead of raising NameError.
"""
from __future__ import annotations

import re

# `(?<!\$)` — `${VAR}` is KiCad path-variable syntax (Sim.Library carries
# `${SEVENSIGMA_DIR}/...`), a different namespace resolved by KiCad, never a
# property template. Without the guard every such value warned "unresolved
# template {SEVENSIGMA_DIR}" on every mirror write.
TEMPLATE_RE = re.compile(r"(?<!\$)\{([^{}]+)\}")


def has_template(value: str | None) -> bool:
    return isinstance(value, str) and TEMPLATE_RE.search(value) is not None


def resolve_templates(
    value: str,
    props: dict[str, str | None],
    warnings: list[str] | None = None,
    context: str = "",
) -> str:
    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key in props and props[key] is not None:
            return str(props[key])
        if warnings is not None:
            warnings.append(f"{context}: unresolved template {{{key}}}")
        return match.group(0)

    return TEMPLATE_RE.sub(_sub, value)
