"""A new column on a journalled table must be registered (decision 0074).

Every write batch keeps a hash of the rows it left. A column added later
changes that hash for every older row, so every older batch reads as "edited
since" and can never be undone — unless the column is in
`journal.LATE_COLUMNS` with the value an older row reads back, or its table is
in `journal.HASH_ONLY`. Found 2026-10-05: ten columns the companies work added
to tables production already journalled.

`FROZEN` is each journalled table's columns when this test was written, minus
the late ones. Adding a column means adding it to `LATE_COLUMNS`, never to
`FROZEN`. A new JOURNALLED table gets its full column list here.

Run from `api/`:  python -m pytest tests/costs/test_journal_columns.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app import models as M  # noqa: F401  (registers the tables)
from app.db import Base
from app.services import journal as J

FROZEN: dict[str, set[str]] = {
    "component_consumption_lots": {
        "consumption_id", "created_at", "ext_ref", "id", "lot_adjustment_id", "lot_line_id", "note",
        "qty", "source", "unit_cost_usd"
    },
    "component_consumptions": {
        "basis", "component_id", "consumed_at", "created_at", "id", "import_ref", "lcsc", "mpn",
        "note", "qty", "run_id", "unit_cost_usd", "void_reason", "voided_at"
    },
    "component_stock_adjustments": {
        "actor", "adjusted_at", "charge_run_id", "component_id", "created_at", "id", "import_ref",
        "lcsc", "mpn", "note", "project_id", "qty_delta", "reason", "unit_cost_usd"
    },
    "cost_line_step_keys": {
        "created_at", "id", "line_id", "run_id", "step_key"
    },
    "cost_line_steps": {
        "created_at", "id", "line_id", "step_run_id"
    },
    "device_events": {
        "actor", "at", "auto", "created_at", "device_id", "id", "kind", "note", "order_line_id",
        "production_run_id", "reason", "replaces_device_id", "shipment_id"
    },
    "device_units": {
        "chip", "condition", "first_seen", "iccid", "id", "imei", "imsi", "last_seen", "last_status",
        "mac", "modem_fw", "modem_model", "notes", "production_run_id", "project_id", "serial",
        "state", "tasmota_id"
    },
    "jlc_imports": {
        "bom_info", "doc_date", "document_id", "external_id", "fee_info", "fetched_at", "id",
        "invoice_no", "jlc_status", "kind", "panel_info", "payload", "presale_amount", "status",
        "total_amount"
    },
    "jlc_order_decisions": {
        "applied_at", "batch_num", "confidence", "created_at", "decided_by", "id", "note", "outcome",
        "panel_factor", "run_id", "smt_order_code"
    },
    "process_transformations": {
        "actor", "created_at", "id", "input_value_usd", "made_at", "note", "output_adjustment_id",
        "output_component_id", "process_version_id", "production_run_id", "project_id", "qty",
        "recipe_key", "recipe_label", "scrap", "void_reason", "voided_at"
    },
    "programming_runs": {
        "action", "attempt_no", "chip_read", "client_info", "deployment_version_id", "device_unit_id",
        "draft_run", "duration_ms", "error", "files_fingerprint", "finished_at",
        "firmware_fingerprint", "id", "mac_read", "operator", "param_set_revision_id",
        "params_snapshot", "production_run_id", "release_override_reason", "results", "started_at",
        "station", "status", "test_required"
    },
    "run_attachments": {
        "content_type", "document_id", "filename", "id", "minio_key", "run_id", "size_bytes",
        "uploaded_at"
    },
    "run_cost_documents": {
        "attachment_id", "corrects_document_id", "created_at", "created_by", "currency",
        "display_amount", "doc_date", "doc_number", "doc_type", "external_id", "fx_rate_display",
        "fx_rate_usd", "id", "notes", "paid_at", "project_id", "run_id", "supplier", "tax_amount",
        "total_amount"
    },
    "run_cost_lines": {
        "allocate", "basis", "component_id", "created_at", "currency", "description", "document_id",
        "exclude_reason", "external_line_id", "id", "label", "lcsc", "lot_ref", "mpn", "notes",
        "ocr_confidence", "parent_line_id", "plan_item_id", "plan_key", "plan_kind", "plan_ref",
        "position", "project_id", "qty", "run_id", "superseded_by_id", "unit_price", "voided_at"
    },
    "run_substitutions": {
        "board", "decided_at", "decided_by", "design_updated", "designator", "evidence",
        "fitted_component_id", "fitted_lcsc", "fitted_mpn", "id", "note", "qty_per_device", "run_id",
        "source", "specified_component_id", "specified_lcsc", "specified_mpn", "supplied_by",
        "supplier_designator", "supplier_source", "variant"
    },
    "step_runs": {
        "actor", "chosen", "created_at", "id", "kind", "made_at", "note", "process_version_id",
        "project_id", "qty", "run_id", "step_key", "step_label"
    },
    "twin_steps": {
        "created_at", "id", "step_run_id", "twin_id"
    },
    "twins": {
        "created_at", "device_unit_id", "finished_at", "found", "id", "named_at", "note",
        "origin_run_id", "process_version_id", "project_id", "run_id", "scrapped_at", "stack_key",
        "status"
    },
}


def test_every_journalled_column_is_frozen_or_late():
    missing = {}
    for t in sorted(J.JOURNALLED):
        assert t in FROZEN, f"{t} is journalled: list its columns in FROZEN"
        cols = {c.name for c in Base.metadata.tables[t].columns}
        new = cols - FROZEN[t] - set(J.LATE_COLUMNS.get(t) or {}) - (J.HASH_ONLY.get(t) and cols or set())
        if new:
            missing[t] = sorted(new)
    assert not missing, ("add these to journal.LATE_COLUMNS with the value an older row reads back: "
                         f"{missing}")


def test_a_late_column_is_no_frozen_one():
    both = {t: sorted(set(c) & FROZEN.get(t, set())) for t, c in J.LATE_COLUMNS.items()}
    assert not any(both.values()), both
