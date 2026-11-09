"""The line batch edit refuses a body it does not understand.

`PATCH /api/run-documents/{id}/lines` with `lines` instead of `updates`
answered 200 and wrote nothing (2026-11-07). FastAPI answers a body that fails
its model with 422 and the error's `loc`, so the model is what is tested here.
Needs no database:
    python -m pytest tests/costs/test_lines_batch_body.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from pydantic import ValidationError

from app.routers.run_costs import LinesBatchIn


def test_an_unknown_key_is_refused_and_named():
    with pytest.raises(ValidationError) as e:
        LinesBatchIn.model_validate({"lines": [{"id": 1, "qty": 2}]})
    errs = e.value.errors()
    assert [(err["type"], err["loc"]) for err in errs] == [("extra_forbidden", ("lines",))]


def test_the_keys_the_browser_sends_are_accepted():
    body = LinesBatchIn.model_validate({
        "document": {"notes": "x"}, "updates": [{"id": 1, "qty": 2}], "creates": [], "deletes": [3]})
    assert body.deletes == [3]


def test_a_line_row_may_carry_fields_the_edit_does_not_read():
    """Only the top level is strict: the browser sends whole line rows."""
    body = LinesBatchIn.model_validate({"updates": [{"id": 1, "qty": 2, "kind": "part", "usd": 1.5}]})
    assert body.updates[0].id == 1
