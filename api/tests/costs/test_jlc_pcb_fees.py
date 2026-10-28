"""A JLC PCB order's fee list maps to the words JLC's own order page prints:
`stencilMoney` is the board price, not a stencil.

Order W2026092300301215, PCB order P50, as the platform imported it and as
JLC's "Detail" popup shows it (read 2026-10-28): Engineering fee 25.00,
Surface Finish 29.50, Testing 4.70, Film 2.70, Color 5.00, Board 55.70,
Confirm Production file 1.05, ENIG Area Surcharge 1.88.

Run from `api/`:
    python -m pytest tests/costs/test_jlc_pcb_fees.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.services import jlc_import

P50 = {
    "kind": "pcb",
    "dummy": 125.53,
    "extra": 0,
    "tolls": {
        "projectMoney": 25.00,
        "adornPutMoney": 29.50,
        "testsMoney": 4.70,
        "fillMoney": 2.70,
        "charFontColor": 5.00,
        "stencilMoney": 55.70,
    },
}


def _by_slug(entry):
    return {c["slug"]: c for c in jlc_import.order_fee_components(entry)}


def test_stencil_money_is_the_board_price():
    c = _by_slug(P50)
    assert c["stencilMoney"]["step"] == "fab:pcb"
    assert c["stencilMoney"]["label"] == "Board"
    assert not any(x["step"] == "pcba:stencil" for x in c.values())


def test_jlc_wording_for_surface_finish_and_film():
    c = _by_slug(P50)
    assert c["adornPutMoney"]["label"] == "Surface finish"
    assert c["fillMoney"]["label"] == "Film"


def test_remainder_is_the_surcharges_when_the_board_is_itemized():
    c = _by_slug(P50)
    assert round(c["board"]["amount"], 2) == 2.93  # 1.05 + 1.88
    assert c["board"]["step"] == "fab:pcb"
    assert c["board"]["label"].startswith("Board surcharges")


def test_components_still_sum_to_the_order():
    total = sum(x["amount"] for x in jlc_import.order_fee_components(P50))
    assert round(total, 4) == 125.53


def test_remainder_is_the_bare_board_when_nothing_names_the_board():
    entry = {"kind": "pcb", "dummy": 40.0, "extra": 0, "tolls": {"projectMoney": 25.0}}
    c = _by_slug(entry)
    assert c["board"]["label"] == "Bare board price (incl. spec surcharges)"
    assert round(c["board"]["amount"], 2) == 15.0
