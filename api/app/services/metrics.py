"""Prometheus metrics of henry-api, for the server's Grafana (decision 0113).

Served on their OWN port (`METRICS_PORT`, 9100), by `prometheus_client`'s
small HTTP server in a thread, so `/metrics` never passes the auth gate and is
never reachable through nginx: only the scraper on the docker network sees it.
henry-api runs ONE uvicorn process, so no multiprocess mode is needed. A second
worker would make each scrape see only one of them.

Three kinds of series, all with low label cardinality on purpose (the box has
about 4 GB of memory free):

- `henry_http_requests_seconds`: every request, by method, ROUTE TEMPLATE
  (`/api/runs/{run_id}`, never the raw path), status code, whether a user was
  signed in, and the client (`mcp`, or `other`).
- `henry_db_query_seconds`: every SQL statement, by kind (select, insert, ...),
  timed on the engine's cursor. A statement of 1 s or more is counted and
  logged as `slow query`, with the request path in the log line.
- Gauges read from Postgres at scrape time: accounts, active users, sessions,
  sign-ins today, live OAuth tokens, open feedback reports.
"""

from __future__ import annotations

import contextvars
import logging
import re
import time
from datetime import timedelta

from prometheus_client import REGISTRY, Counter, Histogram, start_http_server
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import event, func, select, union

from .. import models as M

log = logging.getLogger("henry.metrics")

METRICS_PORT = 9100
SLOW_QUERY_S = 1.0

_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 120)
_DB_BUCKETS = (0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 10)

HTTP = Histogram("henry_http_requests_seconds", "Henry API requests, by route template",
                 ["method", "route", "status", "auth", "client"], buckets=_BUCKETS)
DB = Histogram("henry_db_query_seconds", "SQL statements of henry-api, by kind", ["kind"], buckets=_DB_BUCKETS)
# One series per agent tool (about 120), because `/api/agent/tools/{name}`
# hides which tool ran. Routes tagged as tools show under their own route.
TOOLS = Counter("henry_agent_tool_calls", "Agent tool calls through /api/agent/tools", ["tool", "result"])
SLOW = Counter("henry_db_slow_queries", f"SQL statements of {SLOW_QUERY_S:g} s or more")

# The path of the request in progress, for the slow-query log line.
_route: contextvars.ContextVar[str] = contextvars.ContextVar("henry_metrics_route", default="")

_KINDS = ("select", "insert", "update", "delete", "with")


_TEMPLATES: list[tuple[re.Pattern, str]] | None = None


def _templates(app) -> list[tuple[re.Pattern, str]]:
    """Every route template of the API, from its OpenAPI document, built once.
    FastAPI wraps included routers in objects whose `matches` reveals no route,
    so the document is the dependable list."""
    global _TEMPLATES
    if _TEMPLATES is None:
        out = []
        for path in (app.openapi().get("paths") or {}):
            rx = re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path))
            out.append((re.compile(f"^{rx}$"), path))
        # A literal segment beats a parameter: the longest template first.
        out.sort(key=lambda t: -len(t[1].replace("{", "").split("}")[0]))
        _TEMPLATES = out
    return _TEMPLATES


def _route_of(scope, app=None) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    p = scope.get("path", "")
    # The gate refuses a request before routing, so a 401 carries no route.
    # Match it against the templates, only then, so it still names one.
    if app is not None:
        try:
            for rx, template in _templates(app):
                if rx.match(p):
                    return template
        except Exception:  # noqa: BLE001 — never fail a request over a label
            pass
    # Paths with no route object: the file mirror and the static mount.
    for prefix in ("/files/", "/kicad/v1/"):
        if p.startswith(prefix):
            return prefix + "*"
    return "unmatched"


class MetricsMiddleware:
    """Pure ASGI, outermost: it times the whole request, the gate included."""

    def __init__(self, app, api=None):
        self.app = app
        self.api = api

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status: list[int] = []

        async def send_wrapped(message):
            if message["type"] == "http.response.start":
                status.append(message["status"])
            await send(message)

        token = _route.set(scope.get("path", ""))
        try:
            await self.app(scope, receive, send_wrapped)
        finally:
            _route.reset(token)
            headers = dict(scope.get("headers") or [])
            route = _route_of(scope, self.api)
            mcp = headers.get(b"x-kicad-client", b"").lower() == b"mcp" or route == "/mcp"
            client = "mcp" if mcp else "other"
            user = (scope.get("state") or {}).get("user")
            HTTP.labels(scope.get("method", ""), route, str(status[0] if status else 500),
                        "user" if user is not None else "anon", client).observe(time.perf_counter() - started)


def instrument_engine(engine) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("henry_t0", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _stop(conn, cursor, statement, parameters, context, executemany):
        stack = conn.info.get("henry_t0")
        if not stack:
            return
        took = time.perf_counter() - stack.pop()
        word = statement.lstrip().split(None, 1)[0].lower() if statement.strip() else ""
        DB.labels(word if word in _KINDS else "other").observe(took)
        if took >= SLOW_QUERY_S:
            # The raw path goes to the log only: as a label it would be one
            # series per record id.
            route = _route.get() or "background"
            SLOW.inc()
            log.warning("slow query %.2f s on %s: %s", took, route, " ".join(statement.split())[:300])


class DbGauges:
    """Figures read from Postgres on every scrape (15 s), a handful of COUNTs."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def collect(self):
        now = M.utcnow()
        db = self.session_factory()
        try:
            users = GaugeMetricFamily("henry_users", "Accounts", labels=["state"])
            for active, n in db.execute(select(M.User.active, func.count()).group_by(M.User.active)):
                users.add_metric(["active" if active else "inactive"], n)
            yield users

            act = GaugeMetricFamily("henry_active_users", "People who used Henry in the window, by any credential",
                                    labels=["window"])
            sess = GaugeMetricFamily("henry_sessions", "Browser sessions seen in the window", labels=["window"])
            for label, delta in (("15m", timedelta(minutes=15)), ("24h", timedelta(hours=24)),
                                 ("7d", timedelta(days=7))):
                since = now - delta
                who = union(
                    select(M.UserSession.user_id).where(M.UserSession.last_seen_at >= since),
                    select(M.ApiToken.user_id).where(M.ApiToken.last_used_at >= since),
                    select(M.OAuthToken.user_id).where(M.OAuthToken.last_used_at >= since),
                ).subquery()
                act.add_metric([label], db.execute(select(func.count()).select_from(who)).scalar_one())
                sess.add_metric([label], db.execute(select(func.count()).select_from(M.UserSession)
                                                    .where(M.UserSession.last_seen_at >= since)).scalar_one())
            yield act
            yield sess

            day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yield GaugeMetricFamily("henry_signins_today", "Accounts that signed in today (UTC)",
                                    value=db.execute(select(func.count()).select_from(M.User)
                                                     .where(M.User.last_login_at >= day)).scalar_one())
            yield GaugeMetricFamily("henry_oauth_tokens_live", "Unexpired, unrevoked remote-MCP access tokens",
                                    value=db.execute(select(func.count()).select_from(M.OAuthToken).where(
                                        M.OAuthToken.kind == "access", M.OAuthToken.revoked_at.is_(None),
                                        M.OAuthToken.expires_at > now)).scalar_one())
            fb = GaugeMetricFamily("henry_feedback_reports", "Bug reports and feature requests",
                                   labels=["kind", "status"])
            for kind, status, n in db.execute(select(M.FeedbackReport.kind, M.FeedbackReport.status, func.count())
                                              .group_by(M.FeedbackReport.kind, M.FeedbackReport.status)):
                fb.add_metric([kind, status], n)
            yield fb
        except Exception:  # noqa: BLE001 — a failed read must not fail the whole scrape
            log.exception("metrics: reading the database failed")
        finally:
            db.close()


_started = False


def start(engine, session_factory) -> None:
    """Instrument the engine, register the gauges and serve `/metrics`. Once."""
    global _started
    if _started:
        return
    _started = True
    instrument_engine(engine)
    REGISTRY.register(DbGauges(session_factory))
    try:
        start_http_server(METRICS_PORT)
    except OSError as e:  # the port is taken (a second app in one process, a test run)
        log.warning("metrics: not serving on port %d: %s", METRICS_PORT, e)
