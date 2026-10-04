"""Which company a single record belongs to, and whether the caller may open it
(decision 0063, enforced by decision 0065).

A user sees the companies they belong to; an admin sees every company. The
lists already filter by the header scope. This module is the GATE for a route
that opens ONE record by its id: `require_company_access` runs on every request,
reads the matched route's path parameters, resolves each to the companies the
record belongs to, and answers 404 when the caller belongs to none of them. A
404 and not a 403: a record of another company does not exist for this caller.

Every path parameter in the API is classified in one of two tables, and
`tests/auth/test_company_access.py` fails when a route adds one that is in
neither:

* `RESOLVERS` — company data. `(prefix, param)` -> a function giving the
  companies of the record. A record that belongs to a project belongs to every
  company that ever owned the project, so a company's accountant can still
  open its own past batches after the project moved.
* `NOT_COMPANY_DATA` — shared by both companies on purpose: the library,
  users, suppliers, customers, the JLC account, the field solver's stackups,
  the file pool, the write log (admin-only), the simulator's uploads.

A record whose company cannot be found (a missing id) passes the gate: the
route answers its own 404.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from . import companies as C


def _project(db: Session, project_id) -> set[int]:
    return {r.company_id for r in C.ownership(db, int(project_id))}


def _run(db: Session, run_id) -> set[int]:
    run = db.get(M.ProductionRun, int(run_id))
    if run is None:
        return set()
    return {run.company_id} if run.company_id else _project(db, run.project_id)


def _order(db: Session, order_id) -> set[int]:
    o = db.get(M.SalesOrder, int(order_id))
    if o is None:
        return set()
    if o.company_id:
        return {o.company_id}
    out: set[int] = set()
    for ln in o.lines:
        out |= _project(db, ln.project_id)
    return out


def _doc(db: Session, doc_id) -> set[int]:
    d = db.get(M.RunCostDocument, int(doc_id))
    if d is None:
        return set()
    out = {c for c in (d.company_id, d.counterparty_company_id) if c}
    if not out and d.project_id:
        out = _project(db, d.project_id)
    if not out and d.run_id:
        out = _run(db, d.run_id)
    # A document no company is named on yet (a shared invoice before the
    # backfill) is visible to every company: hiding it would hide the money.
    return out or {c.id for c in C.all_companies(db)}


def _via(model, link: str, parent: Callable) -> Callable:
    def resolve(db: Session, ident) -> set[int]:
        row = db.get(model, int(ident))
        if row is None:
            return set()
        value = getattr(row, link, None)
        return parent(db, value) if value is not None else set()
    return resolve


def _device(db: Session, device_id) -> set[int]:
    d = db.get(M.DeviceUnit, int(device_id))
    if d is None:
        return set()
    if getattr(d, "production_run_id", None):
        got = _run(db, d.production_run_id)
        if got:
            return got
    return _project(db, d.project_id)


def _line(db: Session, line_id) -> set[int]:
    li = db.get(M.RunCostLine, int(line_id))
    return _doc(db, li.document_id) if li is not None else set()


def _attachment(db: Session, att_id) -> set[int]:
    a = db.get(M.RunAttachment, int(att_id))
    if a is None:
        return set()
    if a.document_id:
        return _doc(db, a.document_id)
    return _run(db, a.run_id) if a.run_id else set()


def _stock_row(model) -> Callable:
    def resolve(db: Session, ident) -> set[int]:
        row = db.get(model, int(ident))
        if row is None:
            return set()
        if row.company_id:
            return {row.company_id}
        run_id = getattr(row, "run_id", None) or getattr(row, "charge_run_id", None)
        if run_id:
            return _run(db, run_id)
        project_id = getattr(row, "project_id", None)
        return _project(db, project_id) if project_id else {c.id for c in C.all_companies(db)}
    return resolve


def _deployment_version(db: Session, version_id) -> set[int]:
    v = db.get(M.DeploymentVersion, int(version_id))
    if v is None:
        return set()
    dep = db.get(M.Deployment, v.deployment_id)
    return _project(db, dep.project_id) if dep is not None else set()


#: (path prefix, parameter) -> the companies the record belongs to.
RESOLVERS: dict[tuple[str, str], Callable[[Session, str], set[int]]] = {}


def _add(prefixes: list[str], param: str, fn: Callable) -> None:
    for p in prefixes:
        RESOLVERS[(p, param)] = fn


_add(["*"], "project_id", _project)
_add(["*"], "run_id", _run)
_add(["*"], "order_id", _order)
_add(["/api/flasher/production-runs/"], "production_run_id", _run)
_add(["/api/run-documents/", "/api/transfers/"], "doc_id", _doc)
_add(["/api/run-cost-lines/"], "line_id", _line)
_add(["/api/order-lines/"], "line_id", _via(M.SalesOrderLine, "order_id", _order))
_add(["/api/order-invoices/"], "invoice_id", _via(M.OrderInvoice, "order_id", _order))
_add(["/api/shipments/"], "shipment_id", _via(M.Shipment, "order_id", _order))
_add(["/api/devices/", "/api/flasher/devices/"], "device_id", _device)
_add(["/api/run-devices/"], "device_id", _via(M.RunDevice, "run_id", _run))
_add(["/api/snapshots/", "/api/sim/snapshot/"], "snapshot_id",
     _via(M.ProjectSnapshot, "project_id", _project))
_add(["/api/cost-items/"], "item_id", _via(M.ProjectCostItem, "project_id", _project))
_add(["/api/extra-items/"], "item_id", _via(M.ProjectExtraBomItem, "project_id", _project))
_add(["/api/project-notes/"], "note_id", _via(M.ProjectNote, "project_id", _project))
_add(["/api/substitutions/"], "sub_id", _via(M.RunSubstitution, "run_id", _run))
_add(["/api/production-sets/"], "set_id", _via(M.ProductionFileSet, "run_id", _run))
_add(["/api/production-files/"], "file_id",
     _via(M.ProductionFile, "set_id", _via(M.ProductionFileSet, "run_id", _run)))
_add(["/api/run-attachments/"], "attachment_id", _attachment)
_add(["/api/flasher/deployments/"], "deployment_id", _via(M.Deployment, "project_id", _project))
_add(["/api/flasher/deployment-versions/"], "version_id", _deployment_version)
_add(["/api/process-versions/"], "version_id", _via(M.ProcessVersion, "project_id", _project))
_add(["/api/process-transformations/"], "transformation_id",
     _via(M.ProcessTransformation, "project_id", _project))
_add(["/api/flasher/firmware/"], "asset_id", _via(M.FirmwareAsset, "project_id", _project))
_add(["/api/flasher/param-sets/"], "param_set_id", _via(M.ParamSet, "project_id", _project))
_add(["/api/consumption/"], "cons_id", _stock_row(M.ComponentConsumption))
_add(["/api/stock-adjustments/"], "adj_id", _stock_row(M.ComponentStockAdjustment))

#: Parameters that name data both companies share on purpose.
NOT_COMPANY_DATA: set[str] = {
    # the library, its reviews and the convention documents
    "comp_id", "sym_id", "fp_id", "version_no", "cat_id", "model_id", "skill_id", "ds_id",
    "page_no", "cl_id", "kind", "parent_id", "key", "exc_id", "req_id", "row_id", "link_id",
    "part_id", "comment_id", "filename", "name",
    # people and the companies themselves (admin routes guard their writes)
    "user_id", "token_id", "cred_id", "company_id", "request_id",
    # shared by both companies: the supplier register, the customers, the JLC
    # account and its shelf, the stackups, the file pool, the write log
    "supplier_id", "customer_id", "smt_order_code", "batch_num", "external_id", "pob",
    "order_batch_no", "lcsc", "item_id@/api/jlc/stock/item/", "set_id@/api/flasher/file-sets/",
    "set_id@/api/flasher/files/", "batch_id", "sid", "rid", "jid",
    # the simulator's own uploads and jobs, and a snapshot's board name
    "upload_id", "job", "board",
    # under a project route already resolved by its project_id
    "profile_id",
}


def classify(prefix: str, param: str) -> str:
    """"resolver", "shared" or "" (unclassified) for one route parameter."""
    if (prefix, param) in RESOLVERS or ("*", param) in RESOLVERS:
        return "resolver"
    if param in NOT_COMPANY_DATA or f"{param}@{prefix}" in NOT_COMPANY_DATA:
        return "shared"
    return ""


_PARAM = re.compile(r"\{(\w+)(?::[^}]*)?\}")


def route_params(path: str) -> list[tuple[str, str]]:
    """`(prefix, param)` for every parameter of a route path; the prefix is the
    path up to the parameter's own `{`."""
    out = []
    for m in _PARAM.finditer(path):
        out.append((path[:m.start()], m.group(1)))
    return out


def companies_of(db: Session, path: str, values: dict) -> list[set[int]]:
    """The companies of each company record a request names, one set per
    parameter. An empty list means the route names no company data, or names
    records that do not exist (the route answers its own 404)."""
    out = []
    for prefix, param in route_params(path):
        fn = RESOLVERS.get((prefix, param)) or RESOLVERS.get(("*", param))
        if fn is None or param not in values:
            continue
        try:
            got = fn(db, values[param])
        except (TypeError, ValueError):
            continue
        if got:
            out.append(got)
    return out


def may_open(db: Session, user, path: str, values: dict) -> bool:
    """Whether `user` belongs to a company of EVERY record the request names."""
    if user is None or getattr(user, "role", "") == "admin":
        return True
    mine = set(C.visible_ids(db, user))
    return all(owners & mine for owners in companies_of(db, path, values))


def require_company_access(request: Request, db: Session = Depends(get_db)) -> None:
    """The app-wide dependency. An admin passes, and so does a request with no
    signed-in user (the dev posture with auth off)."""
    user = getattr(request.state, "user", None)
    if user is None or getattr(user, "role", "") == "admin":
        return
    route = request.scope.get("route")
    path = getattr(route, "path", "") if route is not None else ""
    if "{" in path and not may_open(db, user, path, request.path_params):
        raise HTTPException(404, "not found")
