"""The printed invoice (decision 0066).

The layout follows 7Sigma's own template (`szablon/dokument.html`): seller and
title across the top, the two parties, the positions, payment beside the
totals, the amount to pay in words. PyMuPDF's HTML engine draws it, so the
layout is tables, not flex boxes, and nothing outside the api image is needed.

* A VAT document that KSeF has not accepted yet carries the PREVIEW banner:
  the invoice is the XML once KSeF accepts it.
* Once it has a KSeF number and the file's hash, the KSeF verification QR code
  (KOD I) is printed with the number under it. The Ministry requires it on an
  invoice handed over outside KSeF, a PDF in an e-mail included.
"""
from __future__ import annotations

import html
import io
from decimal import Decimal

from .amounts import d2, date_pl, in_words, money_pl, price_pl

QR_URL = "https://qr.ksef.mf.gov.pl/invoice"
SUBTITLE = {"proforma": "dokument informacyjny", "correction": "faktura korygująca",
            "advance": "faktura zaliczkowa", "settlement": "faktura rozliczeniowa"}

CSS = """
body { font-family: sans-serif; font-size: 9pt; color: #1d2330; }
td { vertical-align: top; }
.firma { font-size: 13pt; font-weight: bold; }
.szary { color: #6b7280; font-size: 8pt; }
.tytul { font-size: 16pt; font-weight: bold; text-align: right; }
.nr { font-size: 11pt; font-weight: bold; text-align: right; }
.prawo { text-align: right; }
.etyk { color: #6b7280; font-size: 7pt; text-transform: uppercase; }
.nazwa { font-weight: bold; }
table.poz { width: 100%; border-collapse: collapse; }
table.poz th { font-size: 7.5pt; font-weight: bold; border-top: 1px solid #1d2330;
               border-bottom: 1px solid #1d2330; padding: 4px 3px; text-align: center; }
table.poz td { padding: 5px 3px; border-bottom: 1px solid #d8dce3; }
.c { text-align: center; } .r { text-align: right; }
.razem td { font-weight: bold; border-bottom: none; }
.wzor { color: #b42318; border: 1px solid #b42318; font-weight: bold; text-align: center; padding: 4px; }
.zaplacono { color: #067647; font-weight: bold; }
.dozaplaty { font-size: 13pt; font-weight: bold; text-align: right; }
.sekcja { margin-top: 8px; }
.uwaga { color: #6b7280; font-size: 8pt; border-top: 1px solid #d8dce3; padding-top: 4px; margin-top: 14px; }
"""


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _rate_text(r: str) -> str:
    return f"{r}%" if r.isdigit() else r


def _qty(x) -> str:
    return f"{Decimal(str(x)).normalize():f}".replace(".", ",")


def _price(x) -> str:
    """The unit price with every decimal the net was computed from; an imported
    position that printed none stays blank."""
    if x in (None, ""):
        return ""
    try:
        return price_pl(x)
    except ArithmeticError:
        return _e(x)


def _party(p: dict) -> str:
    lines = [f'<span class="nazwa">{_e(p.get("name"))}</span>']
    lines += [_e(x) for x in (p.get("address_l1"), p.get("address_l2")) if x]
    if p.get("nip") and (p.get("country") or "PL").upper() == "PL":
        lines.append(f"NIP {_e(p['nip'])}")
    elif p.get("vat_eu"):
        from .fa3 import eu_prefix

        lines.append(f"VAT UE {_e(eu_prefix(p.get('country') or ''))}{_e(p['vat_eu'])}")
    elif p.get("nip"):
        lines.append(f"Tax ID {_e(p['nip'])}")
    return "<br/>".join(lines)


def _positions(rows: list[dict], totals: dict | None) -> str:
    head = ("<tr><th style='width:4%'>Lp.</th><th style='width:32%; text-align:left'>Nazwa towaru lub usługi</th>"
            "<th style='width:6%'>Ilość</th><th style='width:5%'>J.m.</th><th style='width:12%'>Cena netto</th>"
            "<th style='width:12%'>Wartość netto</th><th style='width:6%'>VAT</th>"
            "<th style='width:11%'>Kwota VAT</th><th style='width:12%'>Wartość brutto</th></tr>")
    body = "".join(
        f"<tr><td class='c'>{p.get('position', i)}</td><td>{_e(p.get('name'))}</td>"
        f"<td class='c'>{_qty(p.get('qty', 0))}</td><td class='c'>{_e(p.get('unit'))}</td>"
        f"<td class='r'>{_price(p.get('unit_net'))}</td><td class='r'>{money_pl(p.get('net'), '')}</td>"
        f"<td class='c'>{_e(_rate_text(str(p.get('vat_rate') or '')))}</td>"
        f"<td class='r'>{money_pl(p.get('vat'), '')}</td><td class='r'>{money_pl(p.get('gross'), '')}</td></tr>"
        for i, p in enumerate(rows, 1))
    total = ""
    if totals:
        rates = totals.get("rates") or {}
        one = _rate_text(next(iter(rates))) if len(rates) == 1 else ""
        total = (f"<tr class='razem'><td></td><td></td><td></td><td></td><td class='r'>Razem</td>"
                 f"<td class='r'>{money_pl(totals.get('net'), '')}</td><td class='c'>{_e(one)}</td>"
                 f"<td class='r'>{money_pl(totals.get('vat'), '')}</td>"
                 f"<td class='r'>{money_pl(totals.get('gross'), '')}</td></tr>")
    return f"<table class='poz'>{head}{body}{total}</table>"


def _advance_row(totals: dict, name: str, position: int = 1) -> dict:
    """An advance as one printed position: its net, VAT and gross."""
    return {"position": position, "name": name, "qty": 1, "unit": "", "unit_net": totals.get("net"),
            "net": totals.get("net"), "vat_rate": next(iter(totals.get("rates") or {"23": 0})),
            "vat": totals.get("vat"), "gross": totals.get("gross")}


def qr_png(url: str) -> bytes:
    import segno

    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=8, border=0)
    return buf.getvalue()


def qr_url(seller_nip: str, issue_date: str, ksef_hash: str) -> str:
    """KOD I: https://qr.ksef.mf.gov.pl/invoice/{NIP}/{DD-MM-YYYY}/{SHA-256, base64url}"""
    y, m, d = issue_date[:10].split("-")
    return f"{QR_URL}/{seller_nip}/{d}-{m}-{y}/{ksef_hash}"


def build_html(inv, preview: bool) -> tuple[str, dict[str, bytes]]:
    """The page as HTML, and the images it names."""
    b = inv.body or {}
    seller, buyer = b.get("seller") or {}, b.get("buyer") or {}
    pay, bank, totals = b.get("payment") or {}, b.get("bank") or {}, b.get("totals") or {}
    images: dict[str, bytes] = {}
    title = b.get("title") or {"proforma": "FAKTURA PROFORMA", "correction": "FAKTURA KORYGUJĄCA",
                               "advance": "FAKTURA ZALICZKOWA"}.get(inv.kind, "FAKTURA VAT")
    banner = ("<p class='wzor'>PODGLĄD – fakturą jest plik XML po przyjęciu przez KSeF.</p>"
              if preview else "")
    head = (
        "<table style='width:100%'><tr>"
        f"<td><span class='firma'>{_e(seller.get('name'))}</span><br/>"
        f"<span class='szary'>{_e(', '.join(x for x in (seller.get('address_l1'), seller.get('address_l2')) if x))}"
        f"<br/>NIP {_e(seller.get('nip'))}</span></td>"
        f"<td class='prawo'><span class='tytul'>{_e(title)}</span><br/>"
        f"<span class='nr'>Nr {_e(inv.number)}</span><br/>"
        f"<span class='szary'>{_e(SUBTITLE.get(inv.kind, ''))}</span><br/>"
        f"<span class='szary'>Data wystawienia:</span> <b>{_e(date_pl(inv.issue_date))}</b><br/>"
        f"<span class='szary'>Data sprzedaży:</span> <b>{_e(date_pl(inv.sale_date or inv.issue_date))}</b><br/>"
        f"<span class='szary'>Miejsce wystawienia:</span> <b>{_e(b.get('place'))}</b></td>"
        "</tr></table><hr/>")
    parties = ("<table style='width:100%'><tr>"
               f"<td style='width:50%'><span class='etyk'>Sprzedawca</span><br/>{_party(seller)}</td>"
               f"<td style='width:50%'><span class='etyk'>Nabywca</span><br/>{_party(buyer)}</td>"
               "</tr></table><p></p>")
    table = ""
    cor = b.get("correction") or {}
    if inv.kind == "correction" and cor.get("of_kind") == "advance":
        # KOR_ZAL: the order before and after, and the advance before and after.
        before_order = cor.get("before_order") or {}
        if before_order.get("lines"):
            table += ("<p class='nazwa'>Zamówienie przed korektą</p>"
                      + _positions(before_order["lines"], before_order.get("totals")))
        if (b.get("order") or {}).get("lines"):
            table += "<p class='nazwa'>Zamówienie po korekcie</p>" + _positions(b["order"]["lines"], b["order"].get("totals"))
        table += "<p class='nazwa'>Zaliczka</p>" + _positions(
            [_advance_row(cor.get("before_totals") or {}, "Zaliczka przed korektą"),
             _advance_row(totals, "Zaliczka po korekcie", 2)], None)
    elif inv.kind == "correction" and cor.get("before_lines"):
        table += "<p class='nazwa'>Przed korektą</p>" + _positions(cor["before_lines"], cor.get("before_totals"))
        table += "<p class='nazwa'>Po korekcie</p>"
    if inv.kind == "advance" and (b.get("order") or {}).get("lines"):
        table += "<p class='nazwa'>Zamówienie</p>" + _positions(b["order"]["lines"], b["order"].get("totals"))
        table += "<p class='nazwa'>Zaliczka</p>"
        table += _positions([_advance_row(totals, "Zaliczka na poczet zamówienia")], None)
    elif b.get("lines") and not (inv.kind == "correction" and cor.get("of_kind") == "advance"):
        table += _positions(b["lines"], totals)
    extras = ""
    if cor:
        parts = []
        if cor.get("of_number"):
            parts.append(f"Dotyczy faktury nr <b>{_e(cor['of_number'])}</b>"
                         + (f" z dnia {_e(date_pl(cor['of_date']))}" if cor.get("of_date") else "")
                         + (f", KSeF {_e(cor['of_ksef'])}" if cor.get("of_ksef") else ""))
        if cor.get("text_before"):
            parts.append("<b>Treść korygowana:</b><br/>" + "<br/>".join(_e(x) for x in cor["text_before"]))
        if cor.get("text_after"):
            parts.append("<b>Treść poprawna:</b><br/>" + "<br/>".join(_e(x) for x in cor["text_after"]))
        if cor.get("reason"):
            parts.append(f"Przyczyna korekty: {_e(cor['reason'])}")
        extras += "<p class='sekcja'>" + "<br/>".join(parts) + "</p>"
    for a in b.get("advances") or []:
        extras += (f"<p class='sekcja'>Wpłacona zaliczka {_e(a.get('number'))}: netto {money_pl(a.get('net'))}, "
                   f"VAT {money_pl(a.get('vat'))}, brutto {money_pl(a.get('gross'))}</p>")
    rows = []
    if pay.get("paid"):
        rows.append(("Status", "<span class='zaplacono'>ZAPŁACONO</span>"
                     + (f" {_e(date_pl(pay['paid_date']))}" if pay.get("paid_date") else "")
                     + (f"<br/>{_e(pay['note'])}" if pay.get("note") else "")))
    elif pay.get("due_date"):
        rows.append(("Termin płatności", f"<b>{_e(date_pl(pay['due_date']))}</b>"))
    for z in pay.get("partial") or []:
        rows.append(("Zapłata częściowa", money_pl(z.get("amount"))
                     + (f" – {_e(date_pl(z['date']))}" if z.get("date") else "")))
    if pay.get("method"):
        rows.append(("Forma płatności", _e(pay["method"])))
    if bank.get("account") and not pay.get("paid"):
        rows.append(("Numer rachunku", f"<b>{_e(bank['account'])}</b>"))
        if bank.get("name"):
            rows.append(("Bank", _e(bank["name"]) + (f"<br/>{_e(bank['address'])}" if bank.get("address") else "")))
    if b.get("split_payment"):
        rows.append(("", "<b>mechanizm podzielonej płatności</b>"))
    payment = "<table>" + "".join(f"<tr><td class='szary'>{a}</td><td>{v}</td></tr>" for a, v in rows) + "</table>"
    sums = ""
    if totals and inv.kind != "correction":
        rates = totals.get("rates") or {}
        sums += f"<tr><td>Wartość netto</td><td class='r'>{money_pl(totals.get('net'))}</td></tr>"
        if len(rates) > 1:
            for r, v in rates.items():
                sums += (f"<tr><td class='szary'>w tym {_e(_rate_text(r))}: netto {money_pl(v.get('net'))}</td>"
                         f"<td class='r szary'>VAT {money_pl(v.get('vat'))}</td></tr>")
        one = f" {_rate_text(next(iter(rates)))}" if len(rates) == 1 else ""
        sums += f"<tr><td>VAT{_e(one)}</td><td class='r'>{money_pl(totals.get('vat'))}</td></tr>"
        sums += f"<tr><td><b>Wartość brutto</b></td><td class='r'><b>{money_pl(totals.get('gross'))}</b></td></tr>"
    due = inv.amount_due if inv.amount_due is not None else d2(totals.get("gross") or 0)
    sums = (f"<table style='width:100%'>{sums}</table>"
            f"<p class='dozaplaty'>Do zapłaty: {money_pl(due)}</p>"
            f"<p class='szary prawo'>Słownie: {_e(in_words(due))}</p>")
    bottom = ("<table style='width:100%'><tr>"
              f"<td style='width:55%'>{payment}</td><td style='width:45%'>{sums}</td></tr></table>")
    qr = ""
    if inv.ksef_number and inv.ksef_hash:
        images["qr.png"] = qr_png(qr_url(seller.get("nip") or "", inv.issue_date, inv.ksef_hash))
        qr = ("<table><tr><td><img src='qr.png' width='80' height='80'/></td>"
              f"<td><b>{_e(inv.ksef_number)}</b><br/><span class='szary'>Numer KSeF. Kod QR prowadzi do "
              "weryfikacji faktury w KSeF.</span></td></tr></table>")
    elif inv.ksef_number:
        qr = f"<p class='sekcja'>Numer KSeF: <b>{_e(inv.ksef_number)}</b></p>"
    notes = "".join(f"<p class='uwaga'>{_e(t)}</p>" for t in b.get("extra_info") or []
                    if t != (pay.get("note") or ""))
    if inv.kind == "proforma":
        notes += ("<p class='uwaga'>Faktura proforma nie jest fakturą VAT i nie stanowi podstawy "
                  "do odliczenia podatku VAT.</p>")
    footer = f"<p class='szary'>Wystawił: {_e(b.get('issued_by') or seller.get('issuer') or '')}</p>"
    page = (f"<html><head><style>{CSS}</style></head><body>{banner}{head}{parties}{table}{extras}"
            f"<p></p>{bottom}{qr}{notes}{footer}</body></html>")
    return page, images


def render(inv, preview: bool | None = None) -> bytes:
    """The invoice as a PDF. `preview` defaults to "a VAT document KSeF has
    not accepted yet"."""
    import pymupdf

    if preview is None:
        preview = inv.kind != "proforma" and inv.status == "draft"
    page, images = build_html(inv, preview)
    archive = pymupdf.Archive()
    for name, data in images.items():
        archive.add(data, name)
    story = pymupdf.Story(page, archive=archive)
    out = io.BytesIO()
    writer = pymupdf.DocumentWriter(out)
    a4 = pymupdf.paper_rect("a4")
    where = a4 + (42, 40, -42, -44)
    more = True
    while more:
        dev = writer.begin_page(a4)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return out.getvalue()
