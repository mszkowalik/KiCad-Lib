#!/usr/bin/env python3
"""Every API route has a caller in the web UI, or a written reason why not.

The rule is in docs/reference/ui-map.md: a function of the platform is reachable
from the UI. A route with no caller is a function nobody can find, and this is how
they pile up, so the check reads the routers and the client and compares them. It
needs no running server and imports nothing from the app.

A route with no UI on purpose is listed in scripts/routes-without-ui.txt with its
reason: a machine client (KiCad, the bench agent, an agent over MCP), or a server
job. The check fails on a new route with no caller, and on a stale line in that
list, so the list cannot rot.

    python3 scripts/check-ui-routes.py          fail on anything unexplained
    python3 scripts/check-ui-routes.py --all    print every route with no caller
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROUTERS = ROOT / "api/app/routers"
WEB = ROOT / "web/src"
ALLOW = ROOT / "scripts/routes-without-ui.txt"

DECORATOR = re.compile(r'@(\w+)\.(get|post|put|patch|delete)\(\s*\n?\s*(f?)"([^"]*)"')
ROUTER = re.compile(r'(\w+)\s*=\s*APIRouter\(([^)]*)\)', re.S)
PREFIX = re.compile(r'prefix\s*=\s*"([^"]*)"')


def routes() -> list[tuple[str, str, str]]:
    out = []
    for path in sorted(ROUTERS.glob("*.py")):
        text = path.read_text()
        prefixes = {m.group(1): (PREFIX.search(m.group(2)).group(1) if PREFIX.search(m.group(2)) else "")
                    for m in ROUTER.finditer(text)}
        for m in DECORATOR.finditer(text):
            name, method, _f, route = m.groups()
            if name not in prefixes:
                continue
            full = prefixes[name] + route
            if full.startswith("/api"):
                out.append((method.upper(), full, path.name))
    return out


# A helper that builds the start of a path, and the paths it can build.
PATH_HELPERS = {"simBase": ["/api/sim/snapshot/{}/{}", "/api/sim/upload/{}"]}
# `/api/${kind}/...` in the client: `kind` is one of these.
KINDS = ["components", "symbols", "footprints"]


def strings_with_paths(text: str) -> set[tuple[str, str]]:
    """Each string or template literal that starts with an API path, as (method,
    path), with every `${...}` written as `{}`. A scanner and not a regex, because
    an interpolation may hold a nested template: `/api/x${q ? `?${q}` : ""}`. The
    method is the `method:` that follows in the same statement. GET when there is
    none, ANY when it is not a literal."""
    found: set[tuple[str, str]] = set()
    starts = [(m.start(), m.end() - len("/api/"), "") for m in re.finditer(r'(?:\$\{API_URL\})?/api/', text)]
    for name, bases in PATH_HELPERS.items():
        for m in re.finditer(r'\$\{(?:API_URL\}\$\{)?%s\([^)]*\)\}' % name, text):
            for base in bases:
                starts.append((m.start(), m.end(), base))
    for start, body, prefix in starts:
        before = text[start - 1] if start else ""
        if before not in "`\"'":
            continue
        out, i, depth = [prefix], body, 0
        while i < len(text):
            c = text[i]
            if depth:
                depth += {"{": 1, "}": -1}.get(c, 0)
                if depth == 0:
                    out.append("{}")
            elif text.startswith("${", i):
                depth, i = 1, i + 1
            elif c == before or c == "?" or c in " \n":
                break
            else:
                out.append(c)
            i += 1
        rest = text[i:i + 400]
        stmt = rest.split(";", 1)[0]
        m = re.search(r'method:\s*("(\w+)"|\S)', stmt) or re.search(r'jsonBody\(("(\w+)"|\S)', stmt)
        method = (m.group(2) or "ANY") if m else "POST" if "fsJson(" in stmt else "GET"
        found.add((method, "".join(out)))
    return found


def callers() -> list[tuple[str, re.Pattern]]:
    """`{}` matches one path segment. At the end of a string it may also be a query
    string or nothing."""
    found: set[tuple[str, str]] = set()
    for path in WEB.rglob("*.ts*"):
        found |= strings_with_paths(path.read_text())
    pats = []
    for method, s in found:
        s = s.rstrip("/")
        trailing = s.endswith("{}")
        if trailing:
            s = s[:-2]
        for kind in KINDS if s.startswith("/api/{}") else [None]:
            t = s.replace("/api/{}", f"/api/{kind}", 1) if kind else s
            body = "[^/]+".join(re.escape(p) for p in t.split("{}"))
            pats.append((method, re.compile("^" + body + ("[^/]*" if trailing else "") + "/?$")))
    return pats


def allowed() -> dict[str, str]:
    out = {}
    if ALLOW.exists():
        for line in ALLOW.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, why = line.partition("  ")
            out[key.strip()] = why.strip()
    return out


def main() -> int:
    pats = callers()
    probe = lambda route: re.sub(r"\{[^}]*\}", "x", route)
    missing = []
    for method, route, source in routes():
        if not any(m in (method, "ANY") and p.match(probe(route)) for m, p in pats):
            missing.append((f"{method} {route}", source))
    if "--all" in sys.argv:
        for key, source in missing:
            print(f"{key}  [{source}]")
        print(f"{len(missing)} route(s) with no caller in web/src")
        return 0
    allow = allowed()
    names = {k for k, _ in missing}
    new = [(k, s) for k, s in missing if k not in allow]
    stale = sorted(k for k in allow if k not in names)
    for key, source in new:
        print(f"no UI: {key} ({source}). Give it a screen, remove it, or give the reason in {ALLOW.name}.")
    for key in stale:
        print(f"stale: {key} is in {ALLOW.name}, and it has a caller or no longer exists.")
    print(f"checked the routes: {len(new)} with no UI and no reason, {len(stale)} stale, {len(allow)} with a reason")
    return 1 if new or stale else 0


if __name__ == "__main__":
    sys.exit(main())
