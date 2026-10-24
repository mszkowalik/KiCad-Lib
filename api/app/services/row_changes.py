"""Every row change kept, and any request put back (decision 0089).

**Capture is in the database.** A trigger on every table writes `row_changes`.
The ORM hooks of `tracking.py` and `journal.py` cannot be the record: they miss
the cascades Postgres runs itself (a step click's `twin_steps`), every bulk
`UPDATE`/`DELETE`, raw SQL and scripts. A trigger sees all of them.

What a row keeps: a DELETE the whole old row, an UPDATE the old and the new
values of the columns it changed, an INSERT the new row. A long value in a NEW
image is kept as {"$md5": ...} (`rc_shrink`): it is only compared, never put
back. An OLD image is kept whole, because an undo writes it back. Secret columns
(the `tracking._is_secret` names) are never stored, so a revoked token or a
reset password is never brought back.

**Each transaction is tagged** (`_tag`, on every session's `after_begin`) with
the request's id, the person and the client, so the trigger can group rows by
request. Work no request started groups by its transaction.

**Undo puts back one request.** `plan` reconstructs, per row the request
touched, the state before it and the state it left, and refuses when the row no
longer reads as the request left it — naming the later request to undo first.
`undo` writes the before-states back in an order the foreign keys accept, as
one new request, so a redo is the undo of the undo. The stock rule of the Write
log (`journal.stock_blockers`) and the closed-batch rule apply.
"""
from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from .. import models as M
from . import tracking

log = logging.getLogger("uvicorn.error")

# Tables with no trigger. The record itself and the logs that already hold what
# they describe; machine state rewritten all day (95.8 million presence updates,
# 2.8 million bench log lines, a price cache replaced on every refresh, the
# datasheet fetcher's host table, a computed conformance cache); the tables the
# material ledger replaced, kept read only as `legacy_<name>` (decision 0098);
# and the tables whose rows ARE credentials.
SKIP = frozenset({
    "row_changes", "change_undos", "audit_log", "write_batches", "write_batch_rows",
    "device_presence", "programming_logs", "component_price_points", "fetch_hosts", "conformance",
    "legacy_component_consumptions", "legacy_component_consumption_lots", "legacy_component_stock_adjustments",
    "legacy_process_transformations", "legacy_cost_line_steps", "legacy_cost_line_step_keys",
    "legacy_step_runs", "legacy_twin_steps", "legacy_twins",
    "user_sessions", "login_attempts", "jlc_web_sessions", "api_tokens",
})

SHRINK_AT = 2000  # characters of a value's JSON text; keep `rc_shrink` in step

FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION rc_shrink(j jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $f$
  SELECT coalesce(jsonb_object_agg(key, CASE WHEN length(value::text) > 2000
                                             THEN jsonb_build_object('$md5', md5(value::text))
                                             ELSE value END), '{}'::jsonb)
  FROM jsonb_each(j)
$f$;

CREATE OR REPLACE FUNCTION row_change_capture() RETURNS trigger LANGUAGE plpgsql AS $f$
DECLARE
  pk_cols text[] := string_to_array(TG_ARGV[0], ',');
  secret text[] := coalesce(string_to_array(nullif(TG_ARGV[1], ''), ','), '{}');
  ctx jsonb := nullif(current_setting('app.row_ctx', true), '')::jsonb;
  o jsonb;
  n jsonb;
  ch jsonb;
  src jsonb;
  k text;
  key jsonb := '{}'::jsonb;
BEGIN
  IF TG_OP <> 'INSERT' THEN o := to_jsonb(OLD); END IF;
  IF TG_OP <> 'DELETE' THEN n := to_jsonb(NEW); END IF;
  src := coalesce(n, o);
  FOREACH k IN ARRAY pk_cols LOOP
    key := key || jsonb_build_object(k, src -> k);
  END LOOP;
  -- a value that is secret only on some rows
  IF TG_TABLE_NAME = 'device_config_values' THEN
    IF coalesce((o ->> 'is_secret')::boolean, false) OR coalesce((n ->> 'is_secret')::boolean, false) THEN
      secret := secret || 'value'::text;
    END IF;
  ELSIF TG_TABLE_NAME = 'app_settings' AND coalesce(TG_ARGV[2], '') <> '' THEN
    IF (src ->> 'key') = ANY (string_to_array(TG_ARGV[2], ',')) THEN
      secret := secret || 'value'::text;
    END IF;
  END IF;
  IF coalesce(array_length(secret, 1), 0) > 0 THEN
    o := o - secret;
    n := n - secret;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    SELECT jsonb_object_agg(e.key, e.value) INTO ch FROM jsonb_each(n) e WHERE (o -> e.key) IS DISTINCT FROM e.value;
    IF ch IS NULL THEN
      RETURN NULL;  -- nothing changed, or only a secret did
    END IF;
    SELECT jsonb_object_agg(e.key, o -> e.key) INTO o FROM jsonb_each(ch) e;
    n := rc_shrink(ch);
  ELSIF TG_OP = 'INSERT' THEN
    n := rc_shrink(n);
  END IF;
  INSERT INTO row_changes (at, group_key, request_id, user_id, actor, client, table_name, op, pk, old, new)
  VALUES (clock_timestamp(), coalesce(ctx ->> 'request_id', 'tx:' || txid_current()), ctx ->> 'request_id',
          (ctx ->> 'user_id')::int, coalesce(ctx ->> 'actor', ''), coalesce(ctx ->> 'client', 'job'),
          TG_TABLE_NAME, left(TG_OP, 1), key, o, n);
  RETURN NULL;
END
$f$;
"""

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _q(name: str) -> str:
    if not _IDENT.match(name):
        raise HTTPException(422, f"not a table or column name: {name!r}")
    return f'"{name}"'


def _secret_columns(table: str, columns: list[str]) -> list[str]:
    return [c for c in columns if tracking._is_secret(table, c, None)]


def install(engine) -> dict:
    """Create the functions and put the trigger on every table not in SKIP.
    Idempotent; runs at startup after every table exists."""
    out = {"tables": 0, "skipped": 0}
    knobs = ",".join(sorted(tracking._secret_knobs()))
    with engine.begin() as conn:
        conn.execute(text(FUNCTIONS))
        tables = [r[0] for r in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"))]
        for t in tables:
            if t in SKIP:
                conn.execute(text(f"DROP TRIGGER IF EXISTS row_change_capture ON {_q(t)}"))
                out["skipped"] += 1
                continue
            pk = [r[0] for r in conn.execute(text(
                "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
                "AND a.attnum = ANY(i.indkey) WHERE i.indrelid = CAST(:t AS regclass) AND i.indisprimary "
                "ORDER BY a.attnum"), {"t": t})]
            cols = [r[0] for r in conn.execute(text(
                "SELECT attname FROM pg_attribute WHERE attrelid = CAST(:t AS regclass) AND attnum > 0 "
                "AND NOT attisdropped"), {"t": t})]
            if not pk:
                log.warning(f"row changes: {t} has no primary key, so it has no trigger")
                continue
            args = [",".join(pk), ",".join(_secret_columns(t, cols)), knobs if t == "app_settings" else ""]
            quoted = ", ".join("'" + a.replace("'", "''") + "'" for a in args)
            conn.execute(text(
                f"CREATE OR REPLACE TRIGGER row_change_capture AFTER INSERT OR UPDATE OR DELETE ON {_q(t)} "
                f"FOR EACH ROW EXECUTE FUNCTION row_change_capture({quoted})"))
            out["tables"] += 1
    return out


def missing_triggers(conn) -> list[str]:
    """The tables that should carry the trigger and do not."""
    have = {r[0] for r in conn.execute(text(
        "SELECT c.relname FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid "
        "WHERE g.tgname = 'row_change_capture' AND NOT g.tgisinternal"))}
    tables = [r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))]
    return sorted(t for t in tables if t not in SKIP and t not in have)


# ------------------------------------------------------------------ tagging

def context() -> dict:
    ctx = tracking.current()
    if ctx is None:
        return {"client": "job"}
    return {"request_id": ctx.request_id, "user_id": ctx.user_id, "actor": tracking.actor_label(ctx),
            "client": getattr(ctx, "client", "") or ctx.auth_via}


def _tag(session: Session, transaction, connection) -> None:
    connection.execute(text("SELECT set_config('app.row_ctx', :v, true)"), {"v": json.dumps(context())})


_installed = False


def install_tagging() -> None:
    """Tag every ORM transaction with its request (once per process)."""
    global _installed
    if not _installed:
        event.listen(Session, "after_begin", _tag)
        _installed = True


def current_group(db: Session) -> str:
    return db.execute(text(
        "SELECT coalesce(nullif(current_setting('app.row_ctx', true), '')::jsonb ->> 'request_id', "
        "'tx:' || txid_current())")).scalar()


# ------------------------------------------------------------------ reading

def _caller(db: Session) -> tuple[int | None, bool]:
    """The caller's user id, and whether they may act on anybody's changes. With
    auth off (dev) there is nobody, and everything is allowed."""
    ctx = tracking.current()
    if ctx is None or ctx.user_id is None:
        return None, ctx is None or ctx.auth_via == "none"
    u = db.get(M.User, ctx.user_id)
    return ctx.user_id, bool(u is not None and getattr(u, "role", "") == "admin")


def _requests(db: Session, keys: list[str]) -> dict[str, dict]:
    rows = db.query(M.AuditLog).filter(M.AuditLog.action == tracking.REQUEST_ACTION,
                                       M.AuditLog.request_id.in_(keys or ["-"])).all()
    return {r.request_id: {"method": (r.details or {}).get("method"), "path": (r.details or {}).get("path"),
                           "status": (r.details or {}).get("status")} for r in rows}


def list_groups(db: Session, *, everyone: bool = False, user_id: int | None = None, client: str = "",
                table: str = "", before: int | None = None, limit: int = 30) -> list[dict]:
    """Requests that changed rows, newest first: who, when, from which client,
    the route, and how many rows of each table they inserted, updated and
    deleted. A non-admin sees only their own."""
    me, admin = _caller(db)
    if not admin and me is None:
        return []                        # a token that names nobody owns no change
    q = db.query(M.RowChange.group_key, sa.func.max(M.RowChange.id).label("last"))
    if not admin or (not everyone and me is not None):
        q = q.filter(M.RowChange.user_id == me)
    if user_id is not None and admin:
        q = q.filter(M.RowChange.user_id == user_id)
    if client:
        q = q.filter(M.RowChange.client == client)
    if table:
        q = q.filter(M.RowChange.table_name == table)
    q = q.group_by(M.RowChange.group_key)
    if before:
        q = q.having(sa.func.max(M.RowChange.id) < before)
    keys = [k for k, _last in q.order_by(sa.desc("last")).limit(max(1, min(limit, 200))).all()]
    return [summary(db, k) for k in keys]


def summary(db: Session, key: str) -> dict:
    rows = db.query(M.RowChange).filter_by(group_key=key).order_by(M.RowChange.id).all()
    if not rows:
        raise HTTPException(404, f"no change {key}")
    counts: dict[str, dict[str, int]] = OrderedDict()
    for r in rows:
        c = counts.setdefault(r.table_name, {"inserted": 0, "updated": 0, "deleted": 0})
        c[{"I": "inserted", "U": "updated", "D": "deleted"}[r.op]] += 1
    undone = db.query(M.ChangeUndo).filter_by(group_key=key).order_by(M.ChangeUndo.id.desc()).first()
    undoes = db.query(M.ChangeUndo).filter_by(undo_group_key=key).first()
    first = rows[0]
    return {"key": key, "at": first.at, "until": rows[-1].at, "user_id": first.user_id, "actor": first.actor,
            "client": first.client, "request": _requests(db, [key]).get(key), "rows": len(rows),
            "tables": counts, "last_id": rows[-1].id,
            "undone_by": undone.undo_group_key if undone else None,
            "undoes": undoes.group_key if undoes else None}


def _owner(db: Session, key: str) -> int | None:
    return db.query(M.RowChange.user_id).filter_by(group_key=key).limit(1).scalar()


def detail(db: Session, key: str, limit: int = 200) -> dict:
    """One request's rows: what each one was and what it became. Another
    person's request does not exist for a non-administrator."""
    me, admin = _caller(db)
    if not admin and (me is None or _owner(db, key) != me):
        raise HTTPException(404, f"no change {key}")
    out = summary(db, key)
    rows = db.query(M.RowChange).filter_by(group_key=key).order_by(M.RowChange.id).limit(limit).all()
    out["changes"] = [{"id": r.id, "table": r.table_name, "op": r.op, "pk": r.pk, "old": r.old, "new": r.new}
                      for r in rows]
    return out


def row_history(db: Session, table: str, pk: dict, limit: int = 50) -> list[dict]:
    """Every recorded change of one row, newest first — how to find what a
    deleted record held, and which request deleted it. A non-administrator
    sees the changes their own requests made."""
    me, admin = _caller(db)
    if not admin and me is None:
        return []
    q = db.query(M.RowChange).filter(M.RowChange.table_name == table, M.RowChange.pk == pk)
    if not admin:
        q = q.filter(M.RowChange.user_id == me)
    rows = q.order_by(M.RowChange.id.desc()).limit(limit).all()
    return [{"id": r.id, "at": r.at, "key": r.group_key, "actor": r.actor, "client": r.client, "op": r.op,
             "old": r.old, "new": r.new} for r in rows]


# ------------------------------------------------------------------ undo

def _where(table: str, pk: dict) -> tuple[str, dict]:
    cond = " AND ".join(f"{_q(c)} = (SELECT {_q(c)} FROM jsonb_populate_record(NULL::{_q(table)}, "
                        f"CAST(:pk AS jsonb)))" for c in pk)
    return cond, {"pk": json.dumps(pk)}


def _current(db: Session, table: str, pk: dict) -> dict | None:
    cond, params = _where(table, pk)
    return db.execute(text(f"SELECT rc_shrink(to_jsonb(t)) FROM {_q(table)} t WHERE {cond}"), params).scalar()


def _writable(db: Session, table: str) -> set[str]:
    """Columns an undo may write: not generated."""
    return {r[0] for r in db.execute(text(
        "SELECT attname FROM pg_attribute WHERE attrelid = CAST(:t AS regclass) AND attnum > 0 "
        "AND NOT attisdropped AND attgenerated = ''"), {"t": table})}


def _not_null_without_default(db: Session, table: str) -> set[str]:
    return {r[0] for r in db.execute(text(
        "SELECT a.attname FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid "
        "AND d.adnum = a.attnum WHERE a.attrelid = CAST(:t AS regclass) AND a.attnum > 0 "
        "AND NOT a.attisdropped AND a.attnotnull AND d.adbin IS NULL"), {"t": table})}


def plan(db: Session, key: str) -> dict:
    """What undoing request `key` would write, and why it cannot, if it cannot."""
    rows = db.query(M.RowChange).filter_by(group_key=key).order_by(M.RowChange.id).all()
    if not rows:
        raise HTTPException(404, f"no change {key}")
    me, admin = _caller(db)
    owner = rows[0].user_id
    if not admin and (owner is None or owner != me):
        raise HTTPException(403, "you can undo only your own changes; an administrator can undo anybody's")
    by_row: dict[tuple[str, str], list[M.RowChange]] = OrderedDict()
    for r in rows:
        by_row.setdefault((r.table_name, json.dumps(r.pk, sort_keys=True)), []).append(r)
    last_id = rows[-1].id
    actions, refused = [], []
    from .journal import LEGACY_TABLES

    for (table, pkj), changes in by_row.items():
        pk = changes[0].pk
        if table in LEGACY_TABLES:
            refused.append({"table": table, "pk": pk,
                            "why": "it was made before the switch to the material ledger (decision 0098); "
                                   "that table is kept read only"})
            continue
        first, last = changes[0], changes[-1]
        # What the request left: absent after a final delete, else the new images.
        expect: dict | None = None
        if last.op != "D":
            start = max((i for i, c in enumerate(changes) if c.op == "I"), default=0)
            expect = {}
            for c in changes[start:]:
                expect.update(c.new or {})
        now = _current(db, table, pk)
        drifted = (now is not None) if expect is None else (
            now is None or any(now.get(k) != v for k, v in expect.items()))
        if drifted:
            later = sorted({k for (k,) in db.query(M.RowChange.group_key).filter(
                M.RowChange.table_name == table, M.RowChange.pk == pk, M.RowChange.id > last_id).all()})
            refused.append({"table": table, "pk": pk,
                            "why": ("it was changed again since by " + ", ".join(later) + " — undo that first")
                            if later else "it no longer reads as this request left it"})
            continue
        if first.op == "I":
            # An item the material ledger made because a move named a part for
            # the first time is reference data, not part of the request: later
            # moves name it too (decision 0098).
            if last.op != "D" and table != "material_items":
                actions.append({"do": "delete", "table": table, "pk": pk})
            continue
        before: dict = {}
        for c in reversed(changes):          # the earliest prior value of each column wins
            before.update(c.old or {})
        if last.op == "D":
            missing = _not_null_without_default(db, table) - set(before)
            if missing:
                refused.append({"table": table, "pk": pk,
                                "why": f"it holds a credential that is never kept ({', '.join(sorted(missing))})"})
                continue
            actions.append({"do": "insert", "table": table, "pk": pk, "values": before})
        else:
            actions.append({"do": "update", "table": table, "pk": pk, "values": before})
    refused += _closed_batches(db, actions)
    return {"key": key, "owner": owner, "actions": actions, "refused": refused}


def _closed_batches(db: Session, actions: list[dict]) -> list[dict]:
    runs: set[int] = set()
    for a in actions:
        vals = {**(a.get("values") or {}), **a["pk"]}
        if a["table"] == "production_runs":
            runs.add(int(a["pk"].get("id")))
        for k in ("run_id", "production_run_id", "charge_run_id"):
            if isinstance(vals.get(k), int):
                runs.add(vals[k])
    out = []
    for rid in sorted(runs):
        r = db.get(M.ProductionRun, rid)
        if r is not None and r.closed_at is not None:
            out.append({"table": "production_runs", "pk": {"id": rid},
                        "why": f"batch {r.label} is closed — a correction of a closed batch is a new document"})
    return out


def _order() -> dict[str, int]:
    return {t.name: i for i, t in enumerate(M.Base.metadata.sorted_tables)}


def _apply(db: Session, actions: list[dict]) -> None:
    """Write the actions: deletes children first, then updates, then inserts
    parents first. A step the foreign keys refuse is tried again after the
    others, so an order the metadata cannot see still settles."""
    rank = _order()
    deletes = sorted((a for a in actions if a["do"] == "delete"),
                     key=lambda a: (-rank.get(a["table"], 0), json.dumps(a["pk"], sort_keys=True)), reverse=False)
    updates = [a for a in actions if a["do"] == "update"]
    inserts = sorted((a for a in actions if a["do"] == "insert"),
                     key=lambda a: (rank.get(a["table"], 0), json.dumps(a["pk"], sort_keys=True)))
    cols_of: dict[str, set[str]] = {}

    def run(a: dict) -> None:
        t = a["table"]
        cond, params = _where(t, a["pk"])
        if a["do"] == "delete":
            db.execute(text(f"DELETE FROM {_q(t)} WHERE {cond}"), params)
            return
        cols = cols_of.setdefault(t, _writable(db, t))
        vals = {k: v for k, v in a["values"].items() if k in cols}
        if not vals:
            return
        names = ", ".join(_q(k) for k in vals)
        params["v"] = json.dumps(vals)
        if a["do"] == "insert":
            db.execute(text(f"INSERT INTO {_q(t)} ({names}) SELECT {names} "
                            f"FROM jsonb_populate_record(NULL::{_q(t)}, CAST(:v AS jsonb))"), params)
        else:
            db.execute(text(f"UPDATE {_q(t)} SET ({names}) = (SELECT {names} FROM "
                            f"jsonb_populate_record(NULL::{_q(t)}, CAST(:v AS jsonb))) WHERE {cond}"), params)

    for group in (deletes, updates, inserts):
        pending = list(group)
        while pending:
            failed, last_error = [], None
            for a in pending:
                try:
                    with db.begin_nested():
                        run(a)
                except sa.exc.IntegrityError as e:
                    failed.append(a)
                    last_error = e
            if len(failed) == len(pending):
                why = str(last_error.orig).splitlines()[0] if last_error is not None and last_error.orig else ""
                raise HTTPException(409, f"the undo cannot be written: {why}")
            pending = failed


class _StockRow:
    def __init__(self, table: str, op: str, before: dict | None, row_id):
        self.table_name, self.op, self.before, self.row_id = table, op, before, row_id


def _stock_blockers(db: Session, p: dict) -> list[str]:
    from . import journal

    rows = []
    for a in p["actions"]:
        if a["table"] not in journal.STOCK_TABLES or "id" not in a["pk"]:
            continue
        now = _current(db, a["table"], a["pk"])
        op = {"delete": "insert", "insert": "delete", "update": "update"}[a["do"]]
        before = None if op == "insert" else {**(now or {}), **(a.get("values") or {})}
        rows.append(_StockRow(a["table"], op, before, a["pk"]["id"]))
    if not rows:
        return []
    return journal.stock_blockers(db, type("Batch", (), {"rows": rows})(), reverse=lambda: _apply(db, p["actions"]))


def undo(db: Session, key: str, *, dry_run: bool = True) -> dict:
    """Undo request `key`: a plan with dry_run, else the writes, committed."""
    p = plan(db, key)
    if not p["refused"]:
        p["refused"] += [{"why": w} for w in _stock_blockers(db, p)]
    out = {"key": key, "dry_run": dry_run, "rows": len(p["actions"]),
           "actions": [{k: v for k, v in a.items() if k != "values"} for a in p["actions"]][:200],
           "refused": p["refused"]}
    if dry_run:
        return out
    if p["refused"]:
        raise HTTPException(409, {"error": "this change cannot be undone — see `refused`", **out})
    _apply(db, p["actions"])
    me, _admin = _caller(db)
    ctx = tracking.current()
    db.add(M.ChangeUndo(group_key=key, undo_group_key=current_group(db), user_id=me,
                        actor=tracking.actor_label(ctx) if ctx else "job"))
    db.commit()
    out["undo_key"] = db.query(M.ChangeUndo.undo_group_key).filter_by(group_key=key).order_by(
        M.ChangeUndo.id.desc()).limit(1).scalar()
    return out
