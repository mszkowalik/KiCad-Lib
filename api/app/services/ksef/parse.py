"""An FA(3) invoice from KSeF, read into the platform's invoice document
(decision 0067). Ported from `z_fa3` in 7Sigma's script.

The totals are the invoice's own P_13_x / P_14_x / P_15, never re-added from
the positions: the invoice in KSeF is the legally binding one. Each position's
VAT is computed from its net (FA(3) states it only optionally), and a
difference from the printed totals is noted, not corrected.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal

from ..invoicing.amounts import d2

KIND = {"VAT": "vat", "KOR": "correction", "ZAL": "advance", "ROZ": "settlement", "UPR": "vat",
        "KOR_ZAL": "correction", "KOR_ROZ": "correction"}
#: total field -> rate, the inverse of `invoicing.fa3.RATE_FIELDS`
NET_FIELDS = {"P_13_1": "23", "P_13_2": "8", "P_13_3": "5", "P_13_4": "4", "P_13_5": "oss",
              "P_13_6_1": "0 KR", "P_13_6_2": "0 WDT", "P_13_6_3": "0 EX", "P_13_7": "zw",
              "P_13_8": "np I", "P_13_9": "np II", "P_13_10": "oo", "P_13_11": "marża"}
VAT_FIELDS = {"P_13_1": "P_14_1", "P_13_2": "P_14_2", "P_13_3": "P_14_3", "P_13_4": "P_14_4", "P_13_5": "P_14_5"}
FORMS = {"1": "gotówka", "2": "karta", "3": "bon", "4": "czek", "5": "kredyt", "6": "przelew",
         "7": "płatność mobilna"}
PERCENT = {"23", "22", "8", "7", "5", "4", "3"}


def _strip(root) -> None:
    for e in root.iter():
        e.tag = e.tag.split("}")[-1]


def _t(node, path: str) -> str | None:
    if node is None:
        return None
    e = node.find(path)
    return e.text if e is not None else None


def _party(root, tag: str) -> dict:
    p = root.find(tag)
    lines = [x.text for x in (p.find("Adres/AdresL1"), p.find("Adres/AdresL2")) if x is not None] if p is not None else []
    nip = _t(p, "DaneIdentyfikacyjne/NIP") or _t(p, "DaneIdentyfikacyjne/NrVatUE") or _t(p, "DaneIdentyfikacyjne/NrID") or ""
    return {"name": _t(p, "DaneIdentyfikacyjne/Nazwa") or "", "address_l1": lines[0] if lines else "",
            "address_l2": lines[1] if len(lines) > 1 else "", "nip": nip,
            "country": _t(p, "Adres/KodKraju") or "PL"}


def _position(w, n: int) -> dict:
    rate = (_t(w, "P_12") or "").strip()
    qty = Decimal(_t(w, "P_8B") or "1")
    net = Decimal(_t(w, "P_11") or "0")
    unit = _t(w, "P_9A")
    unit_net = Decimal(unit) if unit else (net / qty if qty else net)
    vat = d2(net * Decimal(rate) / 100) if rate in PERCENT else Decimal("0.00")
    return {"position": int(_t(w, "NrWierszaFa") or n), "name": _t(w, "P_7") or "", "unit": _t(w, "P_8A") or "szt.",
            "qty": f"{qty.normalize():f}", "unit_net": str(d2(unit_net)), "net": str(d2(net)),
            "vat_rate": rate, "vat": str(vat), "gross": str(d2(net) + vat),
            "before": _t(w, "StanPrzed") == "1"}


def parse(xml: bytes) -> dict:
    """The invoice: kind, number, dates, currency, parties, positions, totals,
    payment, bank account, extra lines, the corrected invoice."""
    root = ET.fromstring(xml)
    _strip(root)
    fa = root.find("Fa")
    if fa is None:
        raise ValueError("not an FA invoice: no Fa element")
    rates: dict[str, dict] = {}
    for f, r in NET_FIELDS.items():
        v = _t(fa, f)
        if v is not None:
            vat = _t(fa, VAT_FIELDS[f]) if f in VAT_FIELDS else None
            rates[r] = {"net": str(d2(v)), "vat": str(d2(vat or 0))}
    net = sum((Decimal(v["net"]) for v in rates.values()), Decimal(0))
    vat = sum((Decimal(v["vat"]) for v in rates.values()), Decimal(0))
    gross = Decimal(_t(fa, "P_15") or "0")
    rows = [_position(w, i) for i, w in enumerate(fa.findall("FaWiersz"), 1)]
    pl = fa.find("Platnosc")
    paid = _t(pl, "Zaplacono") == "1"
    terms = [t.text for t in pl.findall("TerminPlatnosci/Termin")] if pl is not None else []
    rb = pl.find("RachunekBankowy") if pl is not None else None
    notes = []
    line_gross = sum((Decimal(p["gross"]) for p in rows if not p["before"]), Decimal(0))
    if rows and fa.find("RodzajFaktury") is not None and _t(fa, "RodzajFaktury") == "VAT" \
            and abs(line_gross - gross) > Decimal("0.01"):
        notes.append(f"the positions add up to {d2(line_gross)}, the invoice states P_15 {d2(gross)}")
    cor = None
    dk = fa.find("DaneFaKorygowanej")
    if dk is not None:
        cor = {"of_number": _t(dk, "NrFaKorygowanej") or "", "of_date": _t(dk, "DataWystFaKorygowanej") or "",
               "of_ksef": _t(dk, "NrKSeFFaKorygowanej") or "", "reason": _t(fa, "PrzyczynaKorekty") or "",
               "before_lines": [p for p in rows if p["before"]]}
    return {
        "kind": KIND.get(_t(fa, "RodzajFaktury") or "VAT", "vat"),
        "number": _t(fa, "P_2") or "", "issue_date": _t(fa, "P_1") or "",
        "sale_date": _t(fa, "P_6") or _t(fa, "OkresFa/P_6_Do") or _t(fa, "P_1") or "",
        "currency": _t(fa, "KodWaluty") or "PLN",
        "body": {
            "title": "", "place": _t(fa, "P_1M") or "",
            "seller": _party(root, "Podmiot1"), "buyer": _party(root, "Podmiot2"),
            "lines": [p for p in rows if not p["before"]],
            "totals": {"net": str(d2(net)), "vat": str(d2(vat)), "gross": str(d2(gross)), "rates": rates},
            "payment": {"due_date": terms[0] if terms and not paid else None,
                        "method": FORMS.get(_t(pl, "FormaPlatnosci") or "", "") if pl is not None else "",
                        "paid": paid, "paid_date": _t(pl, "DataZaplaty") if paid else None, "note": ""},
            "bank": {"name": _t(rb, "NazwaBanku") or "", "address": "", "account": _t(rb, "NrRB") or ""},
            "extra_info": [x.find("Wartosc").text for x in fa.findall("DodatkowyOpis")
                           if x.find("Wartosc") is not None],
            "issued_by": "", "notes": notes,
            **({"correction": cor} if cor else {}),
        },
    }
