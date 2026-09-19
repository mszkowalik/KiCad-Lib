"""Which routes are admin-only, asserted against the app itself.

Decision record: docs/decisions/0045-configuration-is-an-administrators-surface.md.

There was no test of the role gate at all until this file, which is why
`/api/settings` could sit ungated for months while `/api/users` beside it was
gated on every route. A dropped `require_admin` is a silent change: the route
keeps working, for everybody.

So this reads the mounted app and compares the gated set against `EXPECTED`
below. Adding an admin route means adding a line here. REMOVING a gate fails,
which is the direction that matters.

Two spellings of the same gate are both accepted, because both are in use:
`Depends(require_admin)` on the signature (settings, users, mqtt) and a bare
`require_admin(request)` in the body (the four field-solver routes, which were
written that way first). The test does not care which — only that the gate is
reachable from the endpoint.

Needs no database: nothing here calls a route, it inspects them.

Run from `api/`:
    python -m pytest tests/auth -q
"""
import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi.routing import APIRoute

from app.main import app
from app.routers.users import require_admin

# (method, path) for every route that must refuse a non-admin.
EXPECTED = {
    # The deployment's own configuration — decision 0045.
    ("GET", "/api/settings"),
    ("PUT", "/api/settings/{key}"),
    ("DELETE", "/api/settings/{key}"),
    # Other people's accounts.
    ("GET", "/api/users"),
    ("POST", "/api/users"),
    ("GET", "/api/users/{user_id}"),
    ("PATCH", "/api/users/{user_id}"),
    ("DELETE", "/api/users/{user_id}"),
    ("POST", "/api/users/{user_id}/sessions/revoke"),
    ("POST", "/api/users/{user_id}/tokens"),
    ("DELETE", "/api/users/{user_id}/tokens/{token_id}"),
    # A live fleet credential — decision 0033.
    ("GET", "/api/mqtt/config"),
    ("PUT", "/api/mqtt/config"),
    ("GET", "/api/mqtt/status"),
    ("GET", "/api/mqtt/mac-mismatches"),
    ("GET", "/api/mqtt/unlinked"),
    ("POST", "/api/mqtt/link"),
    # Exchange rates: every document in the register converts through them.
    # The two READS stay open on purpose and are not listed here.
    ("POST", "/api/fx/refresh"),
    ("PUT", "/api/fx"),
    # The archive-wide datasheet jobs. The PER-DATASHEET fetch and upload stay
    # open — that is ordinary library work, not maintenance of the archive.
    ("POST", "/api/datasheets/fetch-all"),
    ("POST", "/api/datasheets/classify"),
    ("POST", "/api/datasheets/index"),
    ("POST", "/api/datasheets/index/stop"),
    ("DELETE", "/api/datasheets/broken"),
    ("POST", "/api/datasheets/restamps/collapse"),
    ("POST", "/api/datasheets/storage/reclaim"),
    # The fab's shared facts: how boards are made, and what the fab can hold.
    ("POST", "/api/fieldsolver/stackups"),
    ("DELETE", "/api/fieldsolver/stackups/{sid}"),
    ("POST", "/api/fieldsolver/rules"),
    ("DELETE", "/api/fieldsolver/rules/{rid}"),
}


def _gated(route: APIRoute) -> bool:
    """True when `require_admin` runs for this route, either spelling."""
    for dep in route.dependant.dependencies:
        if dep.call is require_admin:
            return True
    try:
        body = inspect.getsource(route.endpoint)
    except (OSError, TypeError):
        return False
    return "require_admin(" in body


def _walk(routes):
    """Every APIRoute, however deeply included.

    `app.routes` is NOT flat on this FastAPI version: `include_router` leaves
    a `fastapi.routing._IncludedRouter` wrapper, and it has no `.routes` of its
    own — the real ones hang off `.original_router`. A pass that looked only at
    `app.routes` found `/openapi.json` and the docs and nothing else, which
    reads as "no admin route is mounted" rather than as a broken test. The
    router carries its own `prefix`, so the paths on those routes are already
    the full ones.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        inner = getattr(route, "original_router", None)
        yield from _walk(getattr(inner, "routes", None) or getattr(route, "routes", ()))


def _routes():
    for route in _walk(app.routes):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, route.path, route


def test_every_expected_route_exists():
    """A renamed or deleted route must not quietly drop out of the list."""
    live = {(m, p) for m, p, _ in _routes()}
    missing = sorted(EXPECTED - live)
    assert not missing, f"listed as admin-only but no longer mounted: {missing}"


@pytest.mark.parametrize("method,path", sorted(EXPECTED))
def test_expected_routes_are_admin_only(method, path):
    route = next(r for m, p, r in _routes() if (m, p) == (method, path))
    assert _gated(route), f"{method} {path} lost its require_admin gate"


def test_no_route_is_gated_without_being_listed():
    """The other direction: a gate nobody wrote down is as surprising as a
    missing one, and this is what keeps `EXPECTED` honest rather than stale."""
    gated = {(m, p) for m, p, r in _routes() if _gated(r)}
    unlisted = sorted(gated - EXPECTED)
    assert not unlisted, f"admin-only but not listed in EXPECTED: {unlisted}"
