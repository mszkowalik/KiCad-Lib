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
  the file pool, the activity log (admin-only), the simulator's uploads.
  The WRITE JOURNAL (`/api/ledger/batches/{batch_id}`) is not shared: a batch
  belongs to the companies of the rows it touched, and only a caller who sees
  every one of them may reverse it.

The gate reads three places, because a record can be named in any of them:

* the PATH parameters (`RESOLVERS`, by route prefix);
* the QUERY parameters and the keys of a JSON BODY, nested to two levels so a
  document's `lines[].run_id` is read (`FIELD_RESOLVERS`, by key, with a
  per-route meaning where one key means two things: `run_id` under
  `/api/flasher/runs/` is a PROGRAMMING run). The agent tools arrive as a JSON
  body at `/api/agent/tools/{name}`, so their id arguments pass the same gate.

An id is parsed the way FastAPI parses it (`"15371.0"` is 15371), and an id
that does not parse is refused, never skipped: a skipped parameter is an open
door. A record whose company cannot be found (a missing id) passes the gate:
the route answers its own 404.

A legacy shared token (`auth_via == "legacy"`) is nobody, so it sees no
company's records. A request with no signed-in user otherwise only happens
with auth off (the dev posture), and then nothing is limited.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable

from fastapi import Depends, HTTPException, WebSocketException
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection, Request

from .. import models as M
from ..db import get_db
from . import companies as C
from . import tracking

_INT = TypeAdapter(int)


def as_id(value) -> int:
    """The integer FastAPI itself would parse from `value` (lax pydantic:
    `"15371.0"`, `" 15371 "` and `"+15371"` are all 15371). ValueError when it
    is no integer at all."""
    try:
        return _INT.validate_python(value)
    except ValidationError as e:
        raise ValueError(f"not an id: {value!r}") from e


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


document_companies = _doc


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


def _company(db: Session, company_id) -> set[int]:
    return {int(company_id)}


def _raw(fn: Callable) -> Callable:
    """Mark a resolver that takes the value as TEXT (a serial, an order code),
    so it is not parsed as an id first."""
    fn.raw = True
    return fn


@_raw
def _serial(db: Session, code) -> set[int]:
    """A scanned device code — the serial as printed, normalised, or the MAC —
    the way the crafting screen and the shipments resolve it."""
    from sqlalchemy import func

    from .orders import find_device

    d = find_device(db, str(code))
    if d is None:
        d = db.query(M.DeviceUnit).filter(func.lower(M.DeviceUnit.mac) == str(code).strip().lower()).first()
    return _device(db, d.id) if d is not None else set()


@_raw
def _jlc_decision(db: Session, code) -> set[int]:
    """A JLC order's decision is the batch it links (decision 0070): voiding,
    applying or clearing it changes that batch's stock and cost."""
    dec = db.query(M.JlcOrderDecision).filter_by(smt_order_code=str(code)).first()
    return _run(db, dec.run_id) if dec is not None and dec.run_id else set()


def _programming_run(db: Session, run_id) -> set[int]:
    """A programming ATTEMPT (flasher): the batch it ran for, else the project
    of the version it executed, else the device it programmed."""
    r = db.get(M.ProgrammingRun, int(run_id))
    if r is None:
        return set()
    if r.production_run_id:
        got = _run(db, r.production_run_id)
        if got:
            return got
    if r.deployment_version_id:
        got = _deployment_version(db, r.deployment_version_id)
        if got:
            return got
    return _device(db, r.device_unit_id) if r.device_unit_id else set()


def _from_values(db: Session, values: dict) -> set[int]:
    """The companies a row's own columns name, read from a dict of them (a
    journal row's `before` image, when the row itself is gone)."""
    if values.get("company_id"):
        return {int(values["company_id"])}
    for key, fn in (("document_id", _doc), ("run_id", _run), ("charge_run_id", _run),
                    ("project_id", _project), ("consumption_id", _stock_row(M.ComponentConsumption)),
                    ("line_id", _line), ("step_run_id", _via(M.StepRun, "run_id", _run)),
                    ("origin_run_id", _run)):
        if values.get(key):
            got = fn(db, values[key])
            if got:
                return got
    return set()


_JOURNAL_TABLES: dict[str, Callable] = {}


def write_batch_companies(db: Session, batch_id) -> set[int]:
    """Every company whose rows a write-journal batch touched. A row that is
    gone is read from its `before` image. A batch that names no company's row
    (a JLC import of the shared account alone) belongs to every company."""
    wb = db.get(M.WriteBatch, int(batch_id))
    if wb is None:
        return set()
    if not _JOURNAL_TABLES:
        _JOURNAL_TABLES.update({
            "run_cost_documents": _doc, "run_cost_lines": _line,
            "component_consumptions": _stock_row(M.ComponentConsumption),
            "component_stock_adjustments": _stock_row(M.ComponentStockAdjustment),
            "component_consumption_lots": _via(M.ComponentConsumptionLot, "consumption_id",
                                               _stock_row(M.ComponentConsumption)),
            "run_substitutions": _via(M.RunSubstitution, "run_id", _run),
            "jlc_order_decisions": _via(M.JlcOrderDecision, "run_id", _run),
            # "Record assembly" (decision 0072): its click, links and twins
            "cost_line_steps": _via(M.CostLineStep, "line_id", _line),
            "cost_line_step_keys": _via(M.CostLineStepKey, "line_id", _line),
            "step_runs": _via(M.StepRun, "run_id", _run),
            "twin_steps": _via(M.TwinStep, "step_run_id", _via(M.StepRun, "run_id", _run)),
            "twins": _via(M.Twin, "origin_run_id", _run),
            # a scrap disposes of its named units (decision 0074)
            "device_units": _device,
            "device_events": _via(M.DeviceEvent, "device_id", _device),
            "programming_runs": _programming_run,
        })
    out: set[int] = set()
    for row in wb.rows:
        fn = _JOURNAL_TABLES.get(row.table_name)
        got = fn(db, row.row_id) if fn is not None else set()
        if not got and row.before:
            got = _from_values(db, row.before)
        out |= got
    if not out and (wb.source_ref or "").startswith("run:"):
        # A batch written for one production batch is that batch's company's.
        out = _run(db, int((wb.source_ref.split(":", 1)[1] or "0").split(":")[0] or 0))
    return out or {c.id for c in C.all_companies(db)}


#: (path prefix, parameter) -> the companies the record belongs to.
RESOLVERS: dict[tuple[str, str], Callable[[Session, str], set[int]]] = {}


def _add(prefixes: list[str], param: str, fn: Callable) -> None:
    for p in prefixes:
        RESOLVERS[(p, param)] = fn


_add(["*"], "project_id", _project)
# A company's own pages (its books, decision 0068) are that company's data.
_add(["/api/companies/"], "company_id", _company)
_add(["*"], "run_id", _run)
# The flasher's runs are programming ATTEMPTS, not batches.
_add(["/api/flasher/runs/", "/api/flasher/ws/"], "run_id", _programming_run)
_add(["/api/ledger/batches/"], "batch_id", write_batch_companies)
_add(["/api/jlc/import/decision/"], "smt_order_code", _jlc_decision)
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
_add(["/api/sales-invoices/"], "invoice_id", _via(M.SalesInvoice, "company_id", _company))
_add(["/api/sales-invoice-templates/"], "template_id", _via(M.SalesInvoiceTemplate, "company_id", _company))
_add(["/api/ksef/inbox/"], "ksef_id", _via(M.KsefInvoice, "company_id", _company))
# files kept with a sales invoice or a tax entry (decision 0077)
_add(["/api/sales-invoices/{invoice_id}/files/"], "file_id", _via(M.RecordFile, "company_id", _company))
_add(["/api/companies/{company_id}/tax-entries/"], "entry_id", _via(M.CompanyTaxEntry, "company_id", _company))
_add(["/api/companies/{company_id}/tax-periods/"], "period_id", _via(M.CompanyTaxPeriod, "company_id", _company))
_add(["/api/companies/{company_id}/tax-entries/{entry_id}/files/"], "file_id", _via(M.RecordFile, "company_id", _company))
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
    "set_id@/api/flasher/files/", "sid", "rid", "jid",
    # the simulator's own uploads and jobs, and a snapshot's board name
    "upload_id", "job", "board",
    # under a project route already resolved by its project_id
    "profile_id",
}


#: Query parameters and JSON body keys that name company data: key -> the
#: companies of the record. `(route path, key)` overrides `("*", key)` where a
#: key means something else on one route.
FIELD_RESOLVERS: dict[tuple[str, str], Callable[[Session, str], set[int]]] = {
    ("*", "project_id"): _project,
    ("*", "run_id"): _run,
    ("*", "charge_run_id"): _run,
    ("*", "production_run_id"): _run,
    ("*", "order_id"): _order,
    ("*", "company_id"): _company,
    ("*", "document_id"): _doc,
    ("*", "corrects_document_id"): _doc,
    ("*", "transformation_id"): _via(M.ProcessTransformation, "project_id", _project),
    ("*", "lot_line_id"): _line,
    ("*", "lot_adjustment_id"): _stock_row(M.ComponentStockAdjustment),
    ("*", "adjustment_id"): _stock_row(M.ComponentStockAdjustment),
    ("*", "snapshot_id"): _via(M.ProjectSnapshot, "project_id", _project),
    ("*", "origin_run_id"): _run,
    ("*", "order_line_id"): _via(M.SalesOrderLine, "order_id", _order),
    ("*", "shipment_id"): _via(M.Shipment, "order_id", _order),
    ("*", "replaces_device_id"): _device,
    ("*", "device_ids"): _device,
    # documents marked as sent to the accountant (decision 0079)
    ("*", "document_ids"): _doc,
    ("*", "sales_invoice_ids"): _via(M.SalesInvoice, "company_id", _company),
    ("*", "serials"): _serial,
    ("*", "codes"): _serial,
    ("/api/runs/{run_id}/craft/costs", "line_ids"): _line,
    ("/api/runs/{run_id}/craft/costs", "step_run_ids"): _via(M.StepRun, "run_id", _run),
    ("/api/run-documents/{doc_id}/lines", "deletes"): _line,
    ("/api/runs/{run_id}/craft/assembly", "line_ids"): _line,
    ("/api/runs/{run_id}/craft/assembly", "parent_line_id"): _line,
    ("/api/runs/{run_id}/craft/assembly", "draw_ids"): _stock_row(M.ComponentConsumption),
    ("*", "attachment_id"): _attachment,
    ("*", "plan_item_id"): _via(M.ProjectCostItem, "project_id", _project),
    ("*", "firmware_asset_id"): _via(M.FirmwareAsset, "project_id", _project),
    ("*", "param_set_id"): _via(M.ParamSet, "project_id", _project),
    ("*", "deployment_version_id"): _deployment_version,
    ("*", "programming_run_id"): _programming_run,
    # an in-house transfer names both companies, so its author must see both
    ("/api/transfers", "sender_id"): _company,
    ("/api/transfers", "receiver_id"): _company,
    ("/api/flasher/checks/recompute", "run_id"): _programming_run,
    ("/api/flasher/deployments/{deployment_id}/versions", "from_version_id"): _deployment_version,
    ("/api/projects/{project_id}/process", "version_id"): _via(M.ProcessVersion, "project_id", _project),
    ("/api/projects/{project_id}/process/transform", "version_id"):
        _via(M.ProcessVersion, "project_id", _project),
    ("/api/projects/{project_id}/process/versions", "from_version_id"):
        _via(M.ProcessVersion, "project_id", _project),
    ("/api/runs/{run_id}/rebuild", "version_id"): _via(M.ProcessVersion, "project_id", _project),
    # the batch whose boards a rebuilt batch's devices were built on (decision 0060)
    ("/api/runs/{run_id}/rebuild", "from_run_id"): _run,
    ("/api/runs/{run_id}/process-version", "version_id"): _via(M.ProcessVersion, "project_id", _project),
    ("/api/agent/tools/{name}", "line_id"): _line,
}

#: Query parameters and body keys ending in `_id` that name shared data.
#: `tests/auth/test_company_access.py` fails on one in neither table.
NOT_COMPANY_FIELDS: set[str] = {
    # the library, the supplier register, the customers (a NIP is `tax_id`)
    "category_id", "parent_id", "component_id", "fitted_component_id", "specified_component_id",
    "link_id", "lcsc_id", "supplier_id", "customer_id", "tax_id", "external_id",
    # the activity log (admin-only), the caller's own git credential, the broker login
    "before_id", "entity_id", "request_id", "user_id", "git_credential_id", "client_id",
    # the flasher's shared file pool, the simulator's uploads, a field-solver profile
    # (read under its project's id)
    "file_set_id", "artwork_set_id", "upload_id", "profile_id",
}


#: List-valued body keys that name shared data (checked by the inventory test
#: like the `*_id` keys): user memberships (admin), JLC ledger rows, library
#: parts.
NOT_COMPANY_LISTS: set[str] = {
    "company_ids", "change_key_ids", "component_ids", "category_ids", "comp_ids", "fp_ids", "sym_ids",
    # the library's supplier links and the supplier register's order rows
    "link_ids", "ids",
    # not ids at all: property keys, layer names, file paths, step keys, text
    "removed_properties", "reference_layers", "paths", "sides", "pin", "extra_info", "unmodelled",
    "assume", "costs", "done", "draw", "step_keys",
    # a printed invoice's own text lines (decision 0085)
    "notes",
    # the advance invoices a recorded settlement names, by NUMBER (decision 0077)
    "advance_numbers",
}


def classify(prefix: str, param: str) -> str:
    """"resolver", "shared" or "" (unclassified) for one route parameter."""
    if (prefix, param) in RESOLVERS or ("*", param) in RESOLVERS:
        return "resolver"
    if param in NOT_COMPANY_DATA or f"{param}@{prefix}" in NOT_COMPANY_DATA:
        return "shared"
    return ""


def classify_field(route_path: str, key: str) -> str:
    """"resolver", "shared" or "" for a query parameter or body key."""
    if (route_path, key) in FIELD_RESOLVERS or ("*", key) in FIELD_RESOLVERS:
        return "resolver"
    if key in NOT_COMPANY_FIELDS or key in NOT_COMPANY_LISTS:
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


def _resolve(db: Session, fn: Callable, value) -> set[int] | None:
    """The companies of one named record. None for a value that is no id at
    all, which the caller refuses."""
    if value is None or value == "":
        return set()
    if getattr(fn, "raw", False):
        return fn(db, value)
    try:
        # A JSON `true` is the id 1 to FastAPI's lax parsing, so it is to the
        # gate too: never skipped.
        ident = as_id(value)
    except ValueError:
        return None
    return fn(db, ident)


def companies_of(db: Session, path: str, values: dict) -> list[set[int]]:
    """The companies of each company record a route's PATH names, one set per
    parameter. An empty list means the route names no company data, or names
    records that do not exist (the route answers its own 404). A value that is
    no id gives an empty set, which no caller passes."""
    out = []
    for prefix, param in route_params(path):
        fn = RESOLVERS.get((prefix, param)) or RESOLVERS.get(("*", param))
        if fn is None or param not in values:
            continue
        got = _resolve(db, fn, values[param])
        if got is None:
            out.append(set())
        elif got:
            out.append(got)
    return out


def _fields(value, depth: int = 0):
    """(key, scalar) pairs of a JSON body: the top object and the objects in
    its lists or nested objects, three levels down. A list of scalars under a
    key yields one pair per item (`device_ids: [1, 2]`)."""
    if depth > 3:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, list) and not any(isinstance(x, (dict, list)) for x in v):
                for x in v:
                    yield k, x
            elif isinstance(v, (dict, list)):
                yield from _fields(v, depth + 1)
            else:
                yield k, v
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, (dict, list)):
                yield from _fields(v, depth + 1)


def field_companies(db: Session, route_path: str, fields) -> list[set[int]]:
    """Like `companies_of`, for query parameters and body keys."""
    out, seen = [], {}
    for key, value in fields:
        fn = FIELD_RESOLVERS.get((route_path, key)) or FIELD_RESOLVERS.get(("*", key))
        if fn is None:
            continue
        cache_key = (key, str(value))
        if cache_key not in seen:
            seen[cache_key] = _resolve(db, fn, value)
        got = seen[cache_key]
        if got is None:
            out.append(set())
        elif got:
            out.append(got)
    return out


def allowed_companies(db: Session, ctx=None, user=None) -> set[int] | None:
    """The companies the current caller may see, or None for no limit: an
    admin, auth off (the dev posture), or an internal call with no request (a
    job, a test). A legacy shared token is nobody and sees no company."""
    ctx = ctx if ctx is not None else tracking.current()
    if ctx is None:
        return None
    if ctx.auth_via == "legacy":
        return set()
    if user is None and ctx.user_id:
        user = db.get(M.User, ctx.user_id)
    if user is None or getattr(user, "role", "") == "admin":
        return None
    return set(C.memberships(db, user))


def hides_project(db: Session, project_id) -> bool:
    """Whether a project is another company's for the current caller — for a
    route that meets a project where the gate cannot read it (a WebSocket
    message)."""
    mine = allowed_companies(db)
    if mine is None or project_id is None:
        return False
    owners = _project(db, project_id)
    return bool(owners) and not owners & mine


def visible_device_ids(db: Session, mine: set[int]) -> set[int]:
    """Every device the gate's device rule gives one of `mine`: its batch's
    company, else its project's companies. A device no company is named for
    is in none."""
    by_run: dict[int, set[int]] = {}
    by_project: dict[int, set[int]] = {}
    keep: set[int] = set()
    for uid, run_id, pid in db.query(M.DeviceUnit.id, M.DeviceUnit.production_run_id, M.DeviceUnit.project_id):
        owners: set[int] = set()
        if run_id:
            if run_id not in by_run:
                by_run[run_id] = _run(db, run_id)
            owners = by_run[run_id]
        if not owners:
            if pid not in by_project:
                by_project[pid] = _project(db, pid)
            owners = by_project[pid]
        if owners & mine:
            keep.add(uid)
    return keep


def may_open(db: Session, user, path: str, values: dict) -> bool:
    """Whether `user` belongs to a company of EVERY record the path names."""
    if user is None or getattr(user, "role", "") == "admin":
        return True
    mine = set(C.visible_ids(db, user))
    return all(owners & mine for owners in companies_of(db, path, values))


def require(db: Session, *owner_sets: set[int]) -> None:
    """404 unless the current caller sees a company of every set."""
    mine = allowed_companies(db)
    if mine is not None and not all(owners & mine for owners in owner_sets):
        raise HTTPException(404, "not found")


def require_every(db: Session, owners: set[int]) -> None:
    """404 unless the current caller sees EVERY company in `owners` — for a
    write that changes the records of each of them at once."""
    mine = allowed_companies(db)
    if mine is not None and not owners <= mine:
        raise HTTPException(404, "not found")


def _check(db: Session, ctx, user, route_path: str, path_params: dict, fields: list) -> bool:
    mine = allowed_companies(db, ctx, user)
    if mine is None:
        return True
    named = companies_of(db, route_path, path_params) if "{" in route_path else []
    named += field_companies(db, route_path, fields)
    return all(owners & mine for owners in named)


def _names_company_data(route_path: str, path_params: dict, fields: list) -> bool:
    for prefix, param in route_params(route_path):
        if param in path_params and ((prefix, param) in RESOLVERS or ("*", param) in RESOLVERS):
            return True
    return any((route_path, k) in FIELD_RESOLVERS or ("*", k) in FIELD_RESOLVERS for k, _ in fields)


_FORM_TYPES = ("multipart/form-data", "application/x-www-form-urlencoded")


async def require_company_access(conn: HTTPConnection, db: Session = Depends(get_db)) -> None:
    """The app-wide dependency, for HTTP requests and WebSockets alike. It
    touches the database only when the request names company data and the
    caller is limited to some companies."""
    ctx = tracking.current()
    if ctx is None:
        return
    user = getattr(conn.state, "user", None)
    if ctx.auth_via != "legacy" and (user is None or getattr(user, "role", "") == "admin"):
        return
    route = conn.scope.get("route")
    route_path = getattr(route, "path", "") if route is not None else ""
    path_params = dict(conn.path_params)
    fields = list(conn.query_params.multi_items())
    if isinstance(conn, Request) and conn.method in ("POST", "PUT", "PATCH", "DELETE"):
        ctype = conn.headers.get("content-type", "").lower()
        if ctype.startswith(_FORM_TYPES):
            # A form's fields, never its files (FastAPI parses the same form).
            form = await conn.form()
            fields += [(k, v) for k, v in form.multi_items() if isinstance(v, str)]
        else:
            # Whatever the Content-Type says: a route that reads the raw body
            # (the agent tools) parses it as JSON regardless.
            raw = await conn.body()
            if raw:
                try:
                    fields += list(_fields(json.loads(raw)))
                except (ValueError, UnicodeDecodeError):
                    pass  # not JSON: the route refuses it on its own
    if not _names_company_data(route_path, path_params, fields):
        return
    try:
        ok = await run_in_threadpool(_check, db, ctx, user, route_path, path_params, fields)
    finally:
        if conn.scope.get("type") == "websocket":
            # A socket lives for minutes: give the connection back now, not
            # when the handler returns.
            db.close()
    if not ok:
        if conn.scope.get("type") == "websocket":
            raise WebSocketException(code=1008, reason="not found")
        raise HTTPException(404, "not found")
