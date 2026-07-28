"""Parse a JLCPCB manufacturing invoice into a vendor-neutral intermediate form.

PURE TRANSFORMATION — no DB access, no writes. The importer decides what to do
with the result; this module only says what the invoice *means*. That split is
deliberate: an invoice fetch must never move money as a side effect, and a
parser with no side effects can be tested against saved payloads forever.

What a JLC manufacturing invoice actually contains (verified against seven real
invoices, 2026-07-28):

  invoiceListResponseList[]   the MONEY: one row per ordered item — bare PCBs
                              ("Printed Circuit Board...") and assembled boards
                              ("Circuit Board Assembly Module"), each with its
                              own freight and tariff.
  presaleDetailResultVOList[] the PHYSICAL: one row per component LOT consumed
                              out of the private library, keyed to the assembly
                              order by `smtOrderCode`.

Two structural facts drive the design here:

1. **One invoice covers several assembly orders.** `orderCode` on an assembly
   line looks like `SMT026070663866-Y88` — the SMT order code AND the board
   code, joined by a hyphen — while a consumption row's `smtOrderCode` is the
   bare `SMT026070663866`. So attribution is per assembly order, never per
   invoice, and the join needs that prefix split.

2. **Consumption is reported per PURCHASE LOT, not per component.** The same
   part appears once per lot at that lot's own settle price (real example:
   C2904795 at $0.4553 and at $0.3470 in one invoice — a 31% spread), each row
   carrying `orderBatchNo` / `presaleOrderNo` / `presaleGoodsKeyId` to identify
   which purchase it came from. Aggregating these away would destroy exactly
   the information that makes lot costing possible, so rows are kept intact and
   `component_totals()` is offered separately for callers that want the blend.

Three arithmetic identities hold exactly on real data and are returned as
`checks` so an import can refuse a payload it does not fully understand rather
than silently booking a wrong number:

  A. total_money - presale_money == the batch's charged total (the prepaid
     component portion was already paid via the parts order — this is the
     codebase's `excluded` allocate semantics, with exact figures).
  B. sum(consumption[].money) == presale_money
  C. per assembly order: sum(its consumption rows' money) == that order line's
     presale_money

Money is USD: `settleCurrency` is USD and `settleExchangeRate` is 1.0 on every
observed invoice. The rate is still carried through rather than assumed, so
switching the account to another billing currency surfaces as a visible change
instead of silently mispricing everything. Note the sibling fields are traps:
`exchangeRate` is CNY-per-USD (JLC's internal RMB conversion, irrelevant here)
and `euroExchangeRate` was frozen at 0.9595 across invoices eight months apart,
i.e. dead data. Neither is used.
"""
from __future__ import annotations

import re
from datetime import date, datetime

# Assembly lines are the ones that can consume private-library stock. JLC's
# wording is matched loosely because it is display text, not an enum.
_ASSEMBLY_HINT = re.compile(r"assembl|populated", re.IGNORECASE)
_PCB_HINT = re.compile(r"printed circuit board|bare", re.IGNORECASE)
_STENCIL_HINT = re.compile(r"stencil|steel", re.IGNORECASE)

# Tolerance for the money identities. JLC rounds per line to 2dp, so a sum of
# ~70 lines can drift a cent or two; anything larger means we misread the
# structure and must not be booked.
MONEY_EPS = 0.05

# Keys whose ABSENCE must fail the import outright, even though `_f` would
# coerce a missing value to 0.0 and every money identity would still pass.
# This is not paranoia — it is the specific way this parser could silently
# destroy data. If JLC renamed `componentNum`, all three identities would still
# balance (they are money-only) while every draw was written at qty 0 and the
# run's forecast draws were deleted in favour of them. If it renamed
# `presaleMoney`, the excluded portion would read 0.00 and the full invoice
# total would be charged to the run ($9,216.42 instead of $3,320.00) with the
# document reconciling perfectly. So presence is checked separately from value.
REQUIRED_HEADER_KEYS = ("totalMoney", "presaleMoney")
REQUIRED_CONSUMPTION_KEYS = ("componentCode", "componentNum", "componentMoney", "smtOrderCode")
REQUIRED_LINE_KEYS = ("orderCode", "totalMoney", "presaleMoney")

# A consumption row must be internally consistent: money == qty x unit. Catches
# a renamed/rescaled quantity or price field that presence alone cannot.
ROW_REL_TOL = 0.005   # 0.5%
ROW_ABS_TOL = 0.01


def _f(v) -> float:
    """Money/quantity coercion. JLC sends nulls freely for 'not applicable'."""
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def parse_invoice_date(raw: str | None) -> date | None:
    """JLC prints DD/MM/YYYY (verified: '23/07/2026' on an invoice dated July
    2026). Tried before the ISO form because 03/06/2026 is ambiguous and the
    day-first reading is the correct one for this vendor."""
    s = _s(raw)
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            # An invoice date is a printed calendar date with no time and no
            # zone. Attaching a tzinfo would invent precision the document does
            # not have, and only the .date() is kept anyway.
            return datetime.strptime(s, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    return None


def split_assembly_order_code(order_code: str) -> tuple[str, str]:
    """`SMT026070663866-Y88` -> ('SMT026070663866', 'Y88').

    The consumption rows carry the bare SMT code, so this is what lets money
    lines and physical rows be joined. Only splits when the code actually looks
    like an SMT order, so a board code containing a hyphen cannot be mangled.
    """
    code = _s(order_code)
    if code.upper().startswith("SMT") and "-" in code:
        smt, board = code.rsplit("-", 1)
        return smt.strip(), board.strip()
    return code, ""


def classify_line(order_type: str) -> str:
    """Map JLC's display wording onto the codebase's vendor-neutral stages.

    Returns 'pcba' | 'fab' | 'stencil' | 'other'. Deliberately coarse: the
    fine-grained step key (`pcba:setup`, `fab:panel`, ...) is the importer's
    business, and `cost_steps.py` already owns that vocabulary.
    """
    t = _s(order_type)
    if _ASSEMBLY_HINT.search(t):
        return "pcba"
    if _STENCIL_HINT.search(t):
        return "stencil"
    if _PCB_HINT.search(t):
        return "fab"
    return "other"


def parse(raw: dict) -> dict:
    """Turn a raw `orderCenter/invoiceOrder` payload into the intermediate form.

    Never raises on odd data — unknown or missing pieces surface in `checks`
    and `warnings` so the caller can refuse the import with a reason. Raising
    here would make a single unfamiliar invoice un-inspectable.
    """
    cur = raw.get("settleCurrencyInfoVO") or {}
    currency = _s(cur.get("settleCurrency")) or "USD"
    settle_rate = _f(cur.get("settleExchangeRate")) or 1.0

    total_money = _f(raw.get("totalMoney"))
    presale_money = _f(raw.get("presaleMoney"))

    lines = [_parse_money_line(r) for r in (raw.get("invoiceListResponseList") or [])]
    consumption = [_parse_consumption(r) for r in (raw.get("presaleDetailResultVOList") or [])]

    warnings: list[str] = []
    if currency != "USD" or abs(settle_rate - 1.0) > 1e-9:
        # Not an error — but every verified invoice was USD @ 1.0, so anything
        # else is unexercised territory and must be looked at by a human.
        warnings.append(
            f"invoice settles in {currency} at rate {settle_rate} — the USD assumption "
            "no longer holds; verify how amounts are denominated before importing"
        )
    for c in consumption:
        if not c["lcsc"]:
            warnings.append(f"consumption row for {c['mpn'] or '?'} has no componentCode")

    schema = schema_check(raw)
    money_checks = checks(total_money, presale_money, lines, consumption)
    warnings.extend(schema["problems"])

    return {
        "invoice_no": _s(raw.get("invoiceNo")),
        "invoice_date": parse_invoice_date(raw.get("invoiceDate")),
        "batch_num": _s(raw.get("batchNum")),
        "currency": currency,
        "settle_rate": settle_rate,
        "totals": {
            "product": _f(raw.get("productMoney")),
            "freight": _f(raw.get("carriageMoney")),
            "tariff": _f(raw.get("tariffChargesMoney")),
            "tariff_service": _f(raw.get("tariffServiceMoney")),
            # A payment-processor fee (PayPal). Small but load-bearing: it is the
            # ONLY term that explained the last two invoices whose totals did not
            # otherwise close (deltas of exactly 1.00 and 6.49).
            "service_charge": _f(raw.get("serviceCharges")),
            "discount": _f(raw.get("discount")),
            "presale": presale_money,
            "sub_total": _f(raw.get("subTotalMoney")),
            "total": total_money,
            # What the batch was actually CHARGED: the prepaid component portion
            # was already settled on the parts order (identity A).
            "charged": round(total_money - presale_money, 4),
        },
        "tracking": _s(raw.get("expressNo")),
        "shipping_method": _s(raw.get("freightModeName")),
        "lines": lines,
        "consumption": consumption,
        "assembly_orders": assembly_orders(lines, consumption),
        # Schema FIRST: the money identities cannot detect a renamed field,
        # because they are money-only and a missing key coerces to 0.0.
        "schema": schema,
        "checks": {**money_checks, "ok": money_checks["ok"] and schema["ok"],
                   "schema_ok": schema["ok"]},
        "warnings": warnings,
    }


def _parse_money_line(r: dict) -> dict:
    order_code = _s(r.get("orderCode"))
    smt_code, board = split_assembly_order_code(order_code)
    return {
        "order_code": order_code,
        "smt_order_code": smt_code,
        "board_code": board,
        "order_type_raw": _s(r.get("orderType")),
        "stage": classify_line(r.get("orderType")),
        "specifications": _s(r.get("specifications")),
        "file_name": _s(r.get("orderFileName")),
        "qty": _f(r.get("number")),
        "unit_price": _f(r.get("unitMoney")),
        "total": _f(r.get("totalMoney")),
        "freight": _f(r.get("carriageMoney")),
        "tariff": _f(r.get("tariffChargesMoney")),
        # The prepaid-component share of this line — becomes an `excluded` line.
        "presale": _f(r.get("presaleMoney")),
        "total_with_fees": _f(r.get("paiclMoney")),
    }


def _parse_consumption(r: dict) -> dict:
    """One consumed LOT. The lot identity is the (orderBatchNo, presaleOrderNo,
    presaleGoodsKeyId) triple — `presaleGoodsKeyId` alone is the tightest key
    JLC gives, so it is kept as the primary lot reference."""
    return {
        "smt_order_code": _s(r.get("smtOrderCode")),
        "lcsc": _s(r.get("componentCode")),
        "mpn": _s(r.get("componentModel")),
        "jlc_component_id": r.get("componentId"),
        "qty": _f(r.get("componentNum")),
        "unit_price": _f(r.get("settleGoodsPrice")),
        "money": _f(r.get("componentMoney")),
        "other_money": _f(r.get("otherMoney")),
        "tariff": _f(r.get("tariffMoney")),
        "vat": _f(r.get("vatMoney")),
        "operate": _f(r.get("operateMoney")),
        # --- lot identity, the whole point of keeping rows unaggregated
        "lot_key": _s(r.get("presaleGoodsKeyId")),
        "purchase_batch_no": _s(r.get("orderBatchNo")),
        "purchase_order_no": _s(r.get("presaleOrderNo")),
        "stock_type": r.get("stockType"),
        "remain_after": r.get("remainNumber"),
    }


def assembly_orders(lines: list[dict], consumption: list[dict]) -> list[dict]:
    """Group the invoice by ASSEMBLY ORDER — the unit that maps to a production
    run. Each entry pairs the money line with the lots it consumed.

    Consumption rows whose `smtOrderCode` matches no money line are surfaced
    under `orphan_consumption` by `checks` rather than being silently attached
    to the first order, which would misattribute real money.
    """
    by_code: dict[str, dict] = {}
    for li in lines:
        if li["stage"] != "pcba":
            continue
        code = li["smt_order_code"] or li["order_code"]
        entry = by_code.setdefault(code, {
            "smt_order_code": code,
            "board_codes": [],
            "qty": 0.0,
            "money": 0.0,
            "presale": 0.0,
            "freight": 0.0,
            "tariff": 0.0,
            "consumption": [],
        })
        if li["board_code"] and li["board_code"] not in entry["board_codes"]:
            entry["board_codes"].append(li["board_code"])
        entry["qty"] += li["qty"]
        entry["money"] += li["total"]
        entry["presale"] += li["presale"]
        entry["freight"] += li["freight"]
        entry["tariff"] += li["tariff"]

    for c in consumption:
        entry = by_code.get(c["smt_order_code"])
        if entry is not None:
            entry["consumption"].append(c)

    for entry in by_code.values():
        entry["qty"] = round(entry["qty"], 4)
        for k in ("money", "presale", "freight", "tariff"):
            entry[k] = round(entry[k], 4)
        entry["consumed_value"] = round(sum(c["money"] for c in entry["consumption"]), 4)
        entry["lot_count"] = len(entry["consumption"])
        entry["component_count"] = len({c["lcsc"] for c in entry["consumption"] if c["lcsc"]})
    return sorted(by_code.values(), key=lambda e: e["smt_order_code"])


def component_totals(consumption: list[dict]) -> list[dict]:
    """Blend lots per component — the DEFAULT (non-advanced) UI row.

    The weighted average is computed from money and quantity actually consumed,
    so it is exact for this invoice rather than an approximation. `lots` is kept
    alongside so the advanced view can emit one flat row per lot without
    re-querying anything.
    """
    by_part: dict[str, dict] = {}
    for c in consumption:
        key = c["lcsc"] or f"mpn:{c['mpn']}"
        e = by_part.setdefault(key, {
            "lcsc": c["lcsc"], "mpn": c["mpn"], "qty": 0.0, "money": 0.0, "lots": [],
        })
        e["qty"] += c["qty"]
        e["money"] += c["money"]
        e["lots"].append(c)
    out = []
    for e in by_part.values():
        e["qty"] = round(e["qty"], 4)
        e["money"] = round(e["money"], 6)
        e["unit_price_avg"] = round(e["money"] / e["qty"], 8) if e["qty"] else None
        e["lot_count"] = len(e["lots"])
        e["price_spread"] = _spread(e["lots"])
        out.append(e)
    return sorted(out, key=lambda e: -e["money"])


def _spread(lots: list[dict]) -> float | None:
    """Relative gap between the cheapest and dearest lot of one part. This is
    the number that justifies lot accounting at all — a real invoice showed
    0.31 (C2904795 at $0.4553 vs $0.3470)."""
    prices = [c["unit_price"] for c in lots if c["unit_price"]]
    if len(prices) < 2:
        return None
    lo, hi = min(prices), max(prices)
    return round((hi - lo) / hi, 4) if hi else None


def schema_check(raw: dict) -> dict:
    """Assert the keys we depend on are PRESENT, before any value is read.

    The money identities are necessary but not sufficient: they are all
    money-only, and `_f` turns a missing key into 0.0, so a renamed quantity or
    presale field passes every one of them while writing catastrophically wrong
    rows (see REQUIRED_* above for the two concrete scenarios). Absence is
    therefore a hard failure, distinct from a zero value — `presaleMoney: 0` is
    a legitimate invoice (two of the seven verified ones), a *missing*
    `presaleMoney` is an unrecognised payload.

    Also verifies each consumption row is internally consistent
    (money == qty x unit) and has a positive quantity, which catches a rescaled
    or swapped field that presence alone cannot.
    """
    missing_header = [k for k in REQUIRED_HEADER_KEYS if k not in raw]

    # ABSENCE of the container is the dangerous case (renamed or removed).
    # Present-but-null is normal and must NOT be rejected: JLC sends
    # `"presaleDetailResultVOList": null` on any invoice with no private-library
    # consumption — bare-PCB and stencil-only orders. Eight of the 37 real
    # batches are exactly this, worth $785, and an over-strict check refused
    # every one of them.
    missing_containers = [
        name for name in ("presaleDetailResultVOList", "invoiceListResponseList")
        if name not in raw
    ]
    cons_rows = raw.get("presaleDetailResultVOList") or []
    line_rows = raw.get("invoiceListResponseList") or []

    # The real invariant: consumption rows must exist IFF prepaid money exists.
    # This is what actually catches a renamed quantity/rows field, without
    # tripping over a legitimately empty invoice.
    presale = _f(raw.get("presaleMoney"))
    presale_without_rows = presale > MONEY_EPS and not cons_rows
    rows_without_presale = bool(cons_rows) and presale <= 0

    missing_cons: set[str] = set()
    missing_line: set[str] = set()
    bad_rows: list[dict] = []
    for i, r in enumerate(cons_rows or []):
        missing_cons |= {k for k in REQUIRED_CONSUMPTION_KEYS if k not in r}
        qty, unit, money = _f(r.get("componentNum")), _f(r.get("settleGoodsPrice")), _f(r.get("componentMoney"))
        if qty <= 0:
            bad_rows.append({"row": i, "reason": "quantity is not positive",
                             "qty": qty, "money": money})
            continue
        expected = qty * unit
        tol = max(ROW_ABS_TOL, abs(money) * ROW_REL_TOL)
        if abs(money - expected) > tol:
            bad_rows.append({"row": i, "reason": "money != qty x unit price",
                             "qty": qty, "unit": unit, "money": money,
                             "expected": round(expected, 6)})
    for r in line_rows or []:
        missing_line |= {k for k in REQUIRED_LINE_KEYS if k not in r}

    problems = []
    if missing_header:
        problems.append(f"header is missing {', '.join(missing_header)}")
    if missing_containers:
        problems.append(f"payload is missing the key {', '.join(missing_containers)} entirely")
    if presale_without_rows:
        problems.append(
            f"presaleMoney is {presale} but no consumption rows were returned — "
            "the prepaid components cannot be attributed to any lot"
        )
    if rows_without_presale:
        problems.append(
            "consumption rows exist but presaleMoney is zero — the quantity and money "
            "fields disagree about whether anything was drawn"
        )
    if missing_cons:
        problems.append(f"consumption rows are missing {', '.join(sorted(missing_cons))}")
    if missing_line:
        problems.append(f"invoice lines are missing {', '.join(sorted(missing_line))}")
    if bad_rows:
        problems.append(f"{len(bad_rows)} consumption row(s) are internally inconsistent")

    return {
        "ok": not problems,
        "problems": problems,
        "missing_header_keys": missing_header,
        "missing_containers": missing_containers,
        "missing_consumption_keys": sorted(missing_cons),
        "missing_line_keys": sorted(missing_line),
        "inconsistent_rows": bad_rows[:20],
        "consumption_row_count": len(cons_rows or []),
    }


def checks(total_money: float, presale_money: float,
           lines: list[dict], consumption: list[dict]) -> dict:
    """The three identities, evaluated. `ok` false means DO NOT IMPORT — the
    payload was not fully understood, and booking it would put a wrong number
    in the register."""
    consumed = round(sum(c["money"] for c in consumption), 4)
    line_presale = round(sum(li["presale"] for li in lines), 4)

    codes = {li["smt_order_code"] for li in lines if li["stage"] == "pcba"}
    orphans = sorted({c["smt_order_code"] for c in consumption
                      if c["smt_order_code"] and c["smt_order_code"] not in codes})

    per_order_ok = True
    per_order_detail = []
    for code in sorted(codes):
        want = round(sum(li["presale"] for li in lines if li["smt_order_code"] == code), 4)
        got = round(sum(c["money"] for c in consumption if c["smt_order_code"] == code), 4)
        ok = abs(want - got) <= MONEY_EPS
        per_order_ok = per_order_ok and ok
        per_order_detail.append({"smt_order_code": code, "line_presale": want,
                                 "consumed_value": got, "ok": ok})

    identity_b = abs(consumed - presale_money) <= MONEY_EPS
    identity_c = per_order_ok and not orphans
    # Identity A is definitional here (charged is derived), so what is worth
    # asserting is that the per-LINE presale figures add up to the header's.
    identity_a = abs(line_presale - presale_money) <= MONEY_EPS

    return {
        "ok": identity_a and identity_b and identity_c,
        "charged": round(total_money - presale_money, 4),
        "identity_a_line_presale_sums_to_header": {
            "ok": identity_a, "lines": line_presale, "header": presale_money,
            "delta": round(line_presale - presale_money, 4),
        },
        "identity_b_consumption_sums_to_presale": {
            "ok": identity_b, "consumed": consumed, "presale": presale_money,
            "delta": round(consumed - presale_money, 4),
        },
        "identity_c_per_assembly_order": {
            "ok": identity_c, "orders": per_order_detail,
            "orphan_consumption": orphans,
        },
    }
