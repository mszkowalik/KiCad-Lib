"""The FA(3) XML of a sales invoice, checked against the Ministry's schema
(decision 0066).

Ported from `fa3_xml` in 7Sigma's script, which uploaded every 2026 invoice
this way. What it writes, and only that:

* `vat` — RodzajFaktury VAT;
* `correction` — RodzajFaktury KOR: the totals are the DIFFERENCE after minus
  before (the schema's own definition of P_13_x and P_15 for a correction),
  the positions before the correction carry `StanPrzed`, and the corrected
  invoice is named with its KSeF number when it has one;
* `advance` — RodzajFaktury ZAL: the totals are the advance received, its VAT
  computed from the gross as art. 106f ust. 1 pkt 3 requires, and the order it
  is paid against goes in `Zamowienie`.

A settlement invoice after advances (ROZ), a currency other than PLN and the
taxi rates 4 and 3 are refused here: their figures need checking before the
platform writes them. Every rate code is mapped as the schema documents it.

The schema files in `schema/` are the Ministry's FA(3) 1-0E, with the imports
pointing at the local copies.
"""
from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache

from .amounts import PERCENT_RATES, d2

NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"
SCHEMA = pathlib.Path(__file__).parent / "schema" / "schemat_FA3.xsd"

#: rate -> (net field, VAT field), as the schema documents them.
RATE_FIELDS = {"23": ("P_13_1", "P_14_1"), "22": ("P_13_1", "P_14_1"),
               "8": ("P_13_2", "P_14_2"), "7": ("P_13_2", "P_14_2"),
               "5": ("P_13_3", "P_14_3"),
               "0 KR": ("P_13_6_1", None), "0 WDT": ("P_13_6_2", None), "0 EX": ("P_13_6_3", None),
               "zw": ("P_13_7", None), "np I": ("P_13_8", None), "np II": ("P_13_9", None),
               "oo": ("P_13_10", None)}
#: the order of the totals in `Fa`
FIELD_ORDER = ["P_13_1", "P_14_1", "P_13_2", "P_14_2", "P_13_3", "P_14_3", "P_13_6_1",
               "P_13_6_2", "P_13_6_3", "P_13_7", "P_13_8", "P_13_9", "P_13_10"]
EU = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE",
      "IT", "LT", "LU", "LV", "MT", "NL", "PT", "RO", "SE", "SI", "SK", "XI"}
PAYMENT_FORMS = {"gotówka": 1, "karta": 2, "bon": 3, "czek": 4, "kredyt": 5, "przelew": 6,
                 "płatność mobilna": 7}


class Refused(ValueError):
    """This invoice cannot be written as FA(3) by the platform yet."""


@lru_cache(maxsize=1)
def _schema():
    import xmlschema

    return xmlschema.XMLSchema(str(SCHEMA))


def validate(xml: bytes) -> list[str]:
    """Every schema error in the XML; an empty list means it is valid."""
    return [str(e.reason or e)[:300] for e in _schema().iter_errors(xml)]


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _sub(parent, tag: str, text=None, **attrs):
    e = ET.SubElement(parent, _q(tag), attrs)
    if text is not None:
        e.text = str(text)
    return e


def _amount(x) -> str:
    return f"{d2(x):f}"


def _qty(x) -> str:
    return f"{Decimal(str(x)).normalize():f}"


def _party(root, tag: str, party: dict) -> None:
    p = _sub(root, tag)
    country = (party.get("country") or "PL").upper()
    if tag == "Podmiot1":
        _sub(p, "PrefiksPodatnika", "PL")
    di = _sub(p, "DaneIdentyfikacyjne")
    nip = (party.get("nip") or "").replace("-", "").replace(" ", "")
    if tag == "Podmiot1" or (country == "PL" and nip):
        _sub(di, "NIP", nip)
    elif country in EU and party.get("vat_eu"):
        _sub(di, "KodUE", country)
        _sub(di, "NrVatUE", party["vat_eu"])
    elif nip:
        _sub(di, "KodKraju", country)
        _sub(di, "NrID", nip)
    else:
        _sub(di, "BrakID", 1)
    _sub(di, "Nazwa", party.get("name") or "")
    ad = _sub(p, "Adres")
    _sub(ad, "KodKraju", country)
    # Both lines in AdresL1, as the Taxpayer Application writes them; 7Sigma's
    # script did the same for every invoice KSeF accepted.
    _sub(ad, "AdresL1", " ".join(x for x in (party.get("address_l1"), party.get("address_l2")) if x))
    if tag == "Podmiot2":
        _sub(p, "JST", 2)
        _sub(p, "GV", 2)


def _rate_totals(fa, rates: dict) -> None:
    fields: dict[str, Decimal] = {}
    for r, t in rates.items():
        if r not in RATE_FIELDS:
            raise Refused(f"the platform does not write rate {r!r} to FA(3) yet")
        net_f, vat_f = RATE_FIELDS[r]
        fields[net_f] = fields.get(net_f, Decimal(0)) + Decimal(str(t["net"]))
        if vat_f:
            fields[vat_f] = fields.get(vat_f, Decimal(0)) + Decimal(str(t["vat"]))
    for f in FIELD_ORDER:
        if f in fields:
            _sub(fa, f, _amount(fields[f]))


def _annotations(fa, body: dict) -> None:
    ad = _sub(fa, "Adnotacje")
    _sub(ad, "P_16", 2)
    _sub(ad, "P_17", 2)
    _sub(ad, "P_18", 2)
    _sub(ad, "P_18A", 1 if body.get("split_payment") else 2)
    _sub(_sub(ad, "Zwolnienie"), "P_19N", 1)
    _sub(_sub(ad, "NoweSrodkiTransportu"), "P_22N", 1)
    _sub(ad, "P_23", 2)
    _sub(_sub(ad, "PMarzy"), "P_PMarzyN", 1)


def _row(fa, n: int, p: dict, before: bool = False) -> None:
    w = _sub(fa, "FaWiersz")
    _sub(w, "NrWierszaFa", n)
    _sub(w, "P_7", p["name"])
    _sub(w, "P_8A", p.get("unit") or "szt.")
    _sub(w, "P_8B", _qty(p["qty"]))
    _sub(w, "P_9A", _amount(p["unit_net"]))
    _sub(w, "P_11", _amount(p["net"]))
    _sub(w, "P_12", p["vat_rate"])
    if p.get("gtu"):
        _sub(w, "GTU", p["gtu"])
    if before:
        _sub(w, "StanPrzed", 1)


def _payment(fa, body: dict) -> None:
    pay = body.get("payment") or {}
    pl = _sub(fa, "Platnosc")
    if pay.get("paid") and pay.get("paid_date"):
        _sub(pl, "Zaplacono", 1)
        _sub(pl, "DataZaplaty", pay["paid_date"])
    elif pay.get("due_date"):
        _sub(_sub(pl, "TerminPlatnosci"), "Termin", pay["due_date"])
    _sub(pl, "FormaPlatnosci", PAYMENT_FORMS.get((pay.get("method") or "przelew").lower(), 6))
    bank = body.get("bank") or {}
    if not pay.get("paid") and bank.get("account"):
        rb = _sub(pl, "RachunekBankowy")
        _sub(rb, "NrRB", bank["account"].replace(" ", ""))
        if bank.get("swift"):
            _sub(rb, "SWIFT", bank["swift"])
        if bank.get("name"):
            _sub(rb, "NazwaBanku", bank["name"])


def _diff(after: dict, before: dict) -> dict:
    """Per-rate totals after minus before."""
    rates = {}
    for r in list(before.get("rates", {})) + [r for r in after.get("rates", {}) if r not in before.get("rates", {})]:
        a = after.get("rates", {}).get(r, {"net": "0", "vat": "0"})
        b = before.get("rates", {}).get(r, {"net": "0", "vat": "0"})
        rates[r] = {"net": str(d2(Decimal(a["net"]) - Decimal(b["net"]))),
                    "vat": str(d2(Decimal(a["vat"]) - Decimal(b["vat"])))}
    gross = d2(Decimal(after["gross"]) - Decimal(before["gross"]))
    return {"rates": rates, "gross": str(gross)}


def advance_totals(order_totals: dict, advance_gross) -> dict:
    """The net and VAT of an advance, per rate, from its gross: the gross is
    split over the order's rates in proportion to their gross, and each share's
    VAT is gross x rate / (100 + rate) (art. 106f ust. 1 pkt 3)."""
    paid = d2(advance_gross)
    order_gross = Decimal(order_totals["gross"])
    if order_gross <= 0:
        raise ValueError("the order has no value to take an advance against")
    rates, left = {}, paid
    items = list(order_totals["rates"].items())
    for i, (r, t) in enumerate(items):
        share_gross = Decimal(t["net"]) + Decimal(t["vat"])
        part = left if i == len(items) - 1 else d2(paid * share_gross / order_gross)
        left -= part
        vat = d2(part * Decimal(r) / (100 + Decimal(r))) if r in PERCENT_RATES else Decimal("0.00")
        rates[r] = {"net": str(d2(part - vat)), "vat": str(vat)}
    net = sum((Decimal(v["net"]) for v in rates.values()), Decimal(0))
    vat = sum((Decimal(v["vat"]) for v in rates.values()), Decimal(0))
    return {"net": str(d2(net)), "vat": str(d2(vat)), "gross": str(paid), "rates": rates}


def build(inv) -> bytes:
    """The FA(3) XML of `inv` (a `SalesInvoice`). Raises `Refused` for what the
    platform does not write yet."""
    body = inv.body or {}
    if inv.kind not in ("vat", "correction", "advance"):
        raise Refused(f"a {inv.kind} invoice is not written to FA(3) by the platform")
    if (inv.currency or "PLN") != "PLN":
        raise Refused("only PLN invoices are written to FA(3) yet")
    ET.register_namespace("", NS)
    root = ET.Element(_q("Faktura"))
    n = _sub(root, "Naglowek")
    _sub(n, "KodFormularza", "FA", kodSystemowy="FA (3)", wersjaSchemy="1-0E")
    _sub(n, "WariantFormularza", 3)
    _sub(n, "DataWytworzeniaFa", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _sub(n, "SystemInfo", "Project Management Platform")
    _party(root, "Podmiot1", body.get("seller") or {})
    _party(root, "Podmiot2", body.get("buyer") or {})
    fa = _sub(root, "Fa")
    _sub(fa, "KodWaluty", "PLN")
    _sub(fa, "P_1", inv.issue_date)
    if body.get("place"):
        _sub(fa, "P_1M", body["place"])
    _sub(fa, "P_2", inv.number)
    _sub(fa, "P_6", inv.sale_date or inv.issue_date)
    totals = body.get("totals") or {}
    if inv.kind == "correction":
        cor = body.get("correction") or {}
        before = cor.get("before_totals") or {"rates": {}, "gross": "0"}
        diff = _diff(totals, before)
        _rate_totals(fa, diff["rates"])
        _sub(fa, "P_15", _amount(diff["gross"]))
    else:
        _rate_totals(fa, totals.get("rates") or {})
        _sub(fa, "P_15", _amount(totals.get("gross") or 0))
    _annotations(fa, body)
    _sub(fa, "RodzajFaktury", {"vat": "VAT", "correction": "KOR", "advance": "ZAL"}[inv.kind])
    if inv.kind == "correction":
        cor = body.get("correction") or {}
        if cor.get("reason"):
            _sub(fa, "PrzyczynaKorekty", cor["reason"])
        dk = _sub(fa, "DaneFaKorygowanej")
        _sub(dk, "DataWystFaKorygowanej", cor.get("of_date") or "")
        _sub(dk, "NrFaKorygowanej", cor.get("of_number") or "")
        if cor.get("of_ksef"):
            _sub(dk, "NrKSeF", 1)
            _sub(dk, "NrKSeFFaKorygowanej", cor["of_ksef"])
        else:
            _sub(dk, "NrKSeFN", 1)
    for i, text in enumerate(body.get("extra_info") or [], 1):
        do = _sub(fa, "DodatkowyOpis")
        _sub(do, "Klucz", "Informacja" if i == 1 else f"Informacja {i}")
        _sub(do, "Wartosc", text)
    if inv.kind == "correction":
        rows = 0
        for p in (body.get("correction") or {}).get("before_lines") or []:
            rows += 1
            _row(fa, rows, p, before=True)
        for p in body.get("lines") or []:
            rows += 1
            _row(fa, rows, p)
    elif inv.kind == "vat":
        for i, p in enumerate(body.get("lines") or [], 1):
            _row(fa, i, p)
    _payment(fa, body)
    if inv.kind == "advance":
        order = body.get("order") or {}
        z = _sub(fa, "Zamowienie")
        _sub(z, "WartoscZamowienia", _amount((order.get("totals") or {}).get("gross") or 0))
        for i, p in enumerate(order.get("lines") or [], 1):
            w = _sub(z, "ZamowienieWiersz")
            _sub(w, "NrWierszaZam", i)
            _sub(w, "P_7Z", p["name"])
            _sub(w, "P_8AZ", p.get("unit") or "szt.")
            _sub(w, "P_8BZ", _qty(p["qty"]))
            _sub(w, "P_9AZ", _amount(p["unit_net"]))
            _sub(w, "P_11NettoZ", _amount(p["net"]))
            _sub(w, "P_11VatZ", _amount(p["vat"]))
            _sub(w, "P_12Z", p["vat_rate"])
    ET.indent(root)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
