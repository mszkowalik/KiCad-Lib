"""Exact amounts for an invoice (decision 0066).

Every amount is a `Decimal` rounded half-up to the grosz, the way 7Sigma's
script and its spreadsheets computed them: a position's net is unit price x
quantity, its VAT is computed on the POSITION's net, and the totals per rate
are sums of the positions. Never floats: an invoice is a legal document and
0.1 + 0.2 is not 0.3.

A rate is a string: the percentages "23", "22", "8", "7", "5" and the FA(3)
codes "0 KR", "0 WDT", "0 EX", "zw", "oo", "np I", "np II". The script's "0"
and "np" are read as "0 KR" and "np I".
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")

#: Rates that carry a VAT percentage.
PERCENT_RATES = ("23", "22", "8", "7", "5")
#: Every rate an invoice may name, in the order FA(3) lists their totals.
RATES = ("23", "22", "8", "7", "5", "0 KR", "0 WDT", "0 EX", "zw", "oo", "np I", "np II")
_ALIASES = {"0": "0 KR", "np": "np I", "23.0": "23", "8.0": "8", "5.0": "5"}

MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
          "sierpnia", "września", "października", "listopada", "grudnia"]


def d2(x) -> Decimal:
    """A money amount, rounded half-up to the grosz."""
    return Decimal(str(x if x is not None else 0)).quantize(CENT, ROUND_HALF_UP)


def qty(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def rate(value) -> str:
    """The canonical rate string, or ValueError."""
    if value is None or value == "":
        return "23"
    s = str(value).strip().rstrip("%").replace(",", ".")
    s = _ALIASES.get(s, s)
    s = s.removesuffix(".0")
    if s not in RATES:
        raise ValueError(f"unknown VAT rate {value!r}; use one of {', '.join(RATES)}")
    return s


def line(position: int, name: str, unit: str, quantity, unit_net, vat_rate) -> dict:
    """One position, computed: net, VAT and gross."""
    r = rate(vat_rate)
    net = d2(qty(quantity) * Decimal(str(unit_net)))
    vat = d2(net * Decimal(r) / 100) if r in PERCENT_RATES else Decimal("0.00")
    return {"position": position, "name": (name or "").strip(), "unit": (unit or "szt.").strip(),
            "qty": str(qty(quantity).normalize()), "unit_net": str(d2(unit_net)),
            "net": str(net), "vat_rate": r, "vat": str(vat), "gross": str(net + vat)}


def lines(raw: list[dict]) -> list[dict]:
    """Positions as typed -> positions computed, numbered from 1."""
    out = []
    for i, p in enumerate(raw, 1):
        if not (p.get("name") or "").strip():
            raise ValueError(f"position {i} has no name")
        out.append(line(i, p["name"], p.get("unit") or "szt.", p.get("qty", 1),
                        p.get("unit_net", 0), p.get("vat_rate", "23")))
    return out


def totals(positions: list[dict]) -> dict:
    """Net, VAT and gross per rate and in all, as strings."""
    by: dict[str, dict] = {}
    for p in positions:
        s = by.setdefault(p["vat_rate"], {"net": Decimal(0), "vat": Decimal(0)})
        s["net"] += Decimal(p["net"])
        s["vat"] += Decimal(p["vat"])
    net = sum((s["net"] for s in by.values()), Decimal(0))
    vat = sum((s["vat"] for s in by.values()), Decimal(0))
    return {"net": str(d2(net)), "vat": str(d2(vat)), "gross": str(d2(net + vat)),
            "rates": {r: {"net": str(d2(by[r]["net"])), "vat": str(d2(by[r]["vat"]))}
                      for r in RATES if r in by}}


def money_pl(x, suffix: str = " zł") -> str:
    """3 690,00 zł"""
    return f"{d2(x):,.2f}".replace(",", " ").replace(".", ",") + suffix


def date_pl(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


# ---- the amount in words, as the spreadsheets printed it
_ONES = ["", "jeden", "dwa", "trzy", "cztery", "pięć", "sześć", "siedem", "osiem", "dziewięć",
         "dziesięć", "jedenaście", "dwanaście", "trzynaście", "czternaście", "piętnaście",
         "szesnaście", "siedemnaście", "osiemnaście", "dziewiętnaście"]
_TENS = ["", "", "dwadzieścia", "trzydzieści", "czterdzieści", "pięćdziesiąt", "sześćdziesiąt",
         "siedemdziesiąt", "osiemdziesiąt", "dziewięćdziesiąt"]
_HUNDREDS = ["", "sto", "dwieście", "trzysta", "czterysta", "pięćset", "sześćset", "siedemset",
             "osiemset", "dziewięćset"]


def _three(n: int) -> list[str]:
    r = n % 100
    words = [_HUNDREDS[n // 100]] + ([_ONES[r]] if r < 20 else [_TENS[r // 10], _ONES[r % 10]])
    return [w for w in words if w]


def _form(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    return few if n % 100 // 10 != 1 and 2 <= n % 10 <= 4 else many


def in_words(amount) -> str:
    """"trzy tysiące sześćset dziewięćdziesiąt złotych 0/100" """
    k = d2(abs(Decimal(str(amount))))
    zl, gr = int(k), int((k - int(k)) * 100)
    words: list[str] = []
    if zl == 0:
        words = ["zero"]
    else:
        mln, tys, ones = zl // 1_000_000, zl // 1000 % 1000, zl % 1000
        if mln:
            words += (["jeden"] if mln == 1 else _three(mln)) + [_form(mln, "milion", "miliony", "milionów")]
        if tys:
            words += ([] if tys == 1 else _three(tys)) + [_form(tys, "tysiąc", "tysiące", "tysięcy")]
        words += _three(ones)
    minus = "minus " if Decimal(str(amount)) < 0 else ""
    return f"{minus}{' '.join(words)} {_form(zl, 'złoty', 'złote', 'złotych')} {gr}/100"
