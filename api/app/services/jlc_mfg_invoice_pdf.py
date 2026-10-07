"""JLCPCB's assembly (manufacturing) invoice, drawn from its data (decision 0086).

JLCPCB keeps no invoice FILE for an assembly order (`W…`) either: the PDFs its
DOWNLOAD button saved for this account are jsPDF 2.5.1 files holding one JPEG of
the page (checked on the platform's own copies, 2026-10-07), the same
html2canvas screenshot decision 0082 found for a parts order. So the platform
draws the invoice from `orderCenter/invoiceOrder` (`jlc_web.
get_manufacturing_invoice(..., reveal=True)`), the call the JLC import already
makes, in the layout of JLCPCB's page as measured on W202404272006430
(positions in points below).

**The rows are JLCPCB's data, one per order, not the page's split.** The page
prints the board fabrication inside an assembly order as a row of its own and
merges it with a bare-board order of the same design; that split comes from
data `invoiceOrder` does not carry. The amounts and every total are the same:
`productMoney` is the sum of the order totals (the import verified the invoice
arithmetic on all 35 invoices, `jlc_import.plan_manufacturing_document`). A
footer line on the page says the invoice was drawn from the data.

Nothing here computes an amount: every figure is JLCPCB's.
"""
from __future__ import annotations

import fitz
from sqlalchemy.orm import Session

from .. import models as M
from ..routers.util import audit
from . import document_files, jlc_web
from .jlc_invoice_pdf import (
    BLUE,
    HEADER_BG,
    LOGO,
    NOTE_GREY,
    PAGE_H,
    PAGE_W,
    ROW_LINE,
    SELLER,
    STRIPE,
    WHITE,
    InvoicePdfError,
    _pdfs,
    _Pen,
    _rgb,
    _s,
    break_all,
    money,
    width,
    wrap_words,
)

X0, X1 = 21.5, 574.5                      # the page's content edges
LOGO_RECT = fitz.Rect(21.0, 13.0, 122.0, 33.0)
SELLER_NAME_BASE = 45.5
SELLER_NAME_SIZE = 5.6
SELLER_LINES = ["Unit 21, 28/F, Metropole Square", "No.2 On Yiu Street, Shatin, New Territories", "HONG KONG, China",
                "support@jlcpcb.com", "+86 755 23919769", "JLCPCB.COM"]
SELLER_BASE, SELLER_PITCH = 65.6, 11.9
BODY = 7.0

BOX = fitz.Rect(404.5, 46.5, 573.5, 171.5)
BOX_BORDER = _rgb("e4e7ed")
BOX_LABEL_X, BOX_VALUE_X = 421.5, 477.0
BOX_FIRST, BOX_PITCH = 67.8, 16.1
BOX_VALUE_W = BOX.x1 - BOX_VALUE_X - 8.0

DIVIDER_Y = 184.5
DIVIDER = _rgb("dddddd")
PARTY_TITLE_BASE, PARTY_TITLE_SIZE = 206.5, 7.4
PARTY_FIRST, PARTY_PITCH = 221.0, 12.7
SHIP_X, BILL_X = 21.5, 404.5
PARTY_W = 360.0

HEADER_TOP, HEADER_H = 330.0, 16.0
HEADER_SIZE = 6.2
CELL, CELL_LINE = 6.2, 7.6
ROW_MIN, ROW_PAD = 21.5, 6.0
COLUMNS = (                                # header, text x, wrap width
    ("", 26.8, 14.0),
    ("Product", 47.0, 128.0),
    ("File Name", 181.0, 70.0),
    ("Order Number", 253.5, 102.0),
    ("QTY", 362.0, 66.0),
    ("Unit Price", 434.5, 66.0),
    ("Ext.Price", 506.5, 66.0),
)
TOTALS_LABEL_X, TOTALS_RIGHT = 421.5, 549.8
TOTALS_GAP, TOTALS_PITCH = 22.0, 15.7
TOP, BOTTOM = 24.0, PAGE_H - 34.0
FOOTER = ("Drawn by the 7Sigma platform from JLCPCB's invoice data (orderCenter/invoiceOrder), one row per order. "
          "JLCPCB's own page prints the board fabrication of an assembly order as a row of its own; the amounts "
          "and the totals are the same.")


def _rows(data: dict) -> list[list[str]]:
    out = []
    for n, it in enumerate(data.get("invoiceListResponseList") or [], 1):
        out.append([str(n), _s(it.get("specifications") or it.get("orderType")), _s(it.get("orderFileName")),
                    _s(it.get("orderCode")), _s(it.get("number")),
                    money(it.get("unitMoney"), "USD", "$", 4), money(it.get("totalMoney"), "USD", "$", 4)])
    return out


def totals(data: dict) -> list[tuple[str, object]]:
    """The totals JLCPCB prints, in its order, each only when it is there."""
    out = [("Merchandise Total:", data.get("productMoney")), ("Shipping:", data.get("carriageMoney"))]
    if data.get("discount"):
        out.append(("Discount:", -float(data["discount"])))
    out.append(("Subtotal:", data.get("subTotalMoney")))
    if data.get("tariffChargesMoney"):
        rate = data.get("tariffRate")
        out.append((f"Import Taxes({rate:g}%):" if rate else "Import Taxes:", data["tariffChargesMoney"]))
    if data.get("serviceCharges"):
        out.append(("Service Charge:", data["serviceCharges"]))
    out.append(("Grand Total:", data.get("totalMoney")))
    return out


def _party(data: dict, billing: bool) -> list[str]:
    sfx = "Billing" if billing else ""
    vat = _s(data.get(f"brazilCpnj{sfx}")) or _s(data.get(f"taxVat{sfx}"))
    place = " ".join(x for x in (_s(data.get(f"province{sfx}")), _s(data.get(f"city{sfx}")),
                                 _s(data.get(f"postCode{sfx}"))) if x)
    return [_s(data.get(f"companyName{sfx}")), _s(data.get(f"man{sfx}")), _s(data.get(f"address{sfx}")), place,
            _s(data.get(f"country{sfx}")), "Email:" + _s(data.get("email")), "Tel:" + _s(data.get(f"tel{sfx}")),
            "VAT No:" + vat]


def render(data: dict) -> bytes:
    """The invoice PDF for one `invoiceOrder` response, its `{secret}` fields
    already decrypted."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    pen = _Pen(page)

    # -- seller
    page.insert_image(LOGO_RECT, filename=str(LOGO), keep_proportion=True)
    pen.text(X0, SELLER_NAME_BASE, SELLER, SELLER_NAME_SIZE, BLUE)
    for i, line in enumerate(SELLER_LINES):
        pen.text(X0, SELLER_BASE + i * SELLER_PITCH, line, BODY)

    # -- the box: invoice number, date, reference, batch, shipping
    page.draw_rect(BOX, color=BOX_BORDER, width=0.6)
    y = BOX_FIRST
    for label, value in (("Invoice No.:", data.get("invoiceNo")), ("Invoice Date:", data.get("invoiceDate")),
                         ("Reference:", data.get("expressNo")), ("Batch No.:", data.get("batchNum")),
                         ("Ship Via:", data.get("freightModeName")), ("Type of Trade:", data.get("typeOfTrade"))):
        if not _s(value):
            continue
        pen.text(BOX_LABEL_X, y, label, BODY)
        lines = wrap_words(_s(value), BODY, BOX_VALUE_W)
        for k, line in enumerate(lines):
            pen.text(BOX_VALUE_X, y + k * (BODY + 2.2), line, BODY)
        y += BOX_PITCH + (len(lines) - 1) * (BODY + 2.2)

    page.draw_line((X0, DIVIDER_Y), (X1, DIVIDER_Y), color=DIVIDER, width=0.6)

    # -- ship to, billing to
    for x, title, billing in ((SHIP_X, "Ship To:", False), (BILL_X, "Billing To:", True)):
        pen.text(x, PARTY_TITLE_BASE, title, PARTY_TITLE_SIZE, bold=True)
        limit = PARTY_W if not billing else X1 - BILL_X
        y = PARTY_FIRST
        for t in _party(data, billing):
            for line in wrap_words(t, BODY, limit):
                pen.text(x, y, line, BODY)
                y += PARTY_PITCH

    # -- the table
    top = HEADER_TOP
    page.draw_rect(fitz.Rect(X0, top, X1, top + HEADER_H), color=None, fill=HEADER_BG, width=0)
    for head, x, _ in COLUMNS:
        pen.text(x, top + HEADER_H / 2 + 2.2, head, HEADER_SIZE, WHITE, bold=True)
    y = top + HEADER_H
    for n, cells in enumerate(_rows(data)):
        wrapped = [break_all(c, CELL, w) for c, (_, _, w) in zip(cells, COLUMNS)]
        h = max(ROW_MIN, ROW_PAD + CELL_LINE * max(len(w) for w in wrapped))
        if y + h > BOTTOM:
            pen.flush()
            page = doc.new_page(width=PAGE_W, height=PAGE_H)
            pen = _Pen(page)
            y = TOP
        if n % 2:
            page.draw_rect(fitz.Rect(X0, y, X1, y + h), color=None, fill=STRIPE, width=0)
        page.draw_line((X0, y + h - 0.17), (X1, y + h - 0.17), color=ROW_LINE, width=0.35)
        for lines, (_, x, _) in zip(wrapped, COLUMNS):
            block_top = y + (h - CELL_LINE * len(lines)) / 2
            for i, line in enumerate(lines):
                pen.text(x, block_top + CELL_LINE * i + CELL_LINE / 2 + 2.2, line, CELL)
        y += h

    # -- totals, then the footer that says where the invoice came from
    rows = totals(data)
    footer = wrap_words(FOOTER, 5.6, X1 - X0)
    base = y + TOTALS_GAP
    if base + TOTALS_PITCH * len(rows) + 8.0 * (len(footer) + 1) > PAGE_H - 20.0:
        pen.flush()
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        pen = _Pen(page)
        base = TOP + TOTALS_GAP
    for label, value in rows:
        text = money(value, "USD", "$", 2)
        pen.text(TOTALS_LABEL_X, base, label, BODY)
        pen.text(TOTALS_RIGHT - width(text, BODY), base, text, BODY)
        base += TOTALS_PITCH
    fy = max(base + 8.0, PAGE_H - 20.0 - 8.0 * len(footer))
    for i, line in enumerate(footer):
        pen.text(X0, fy + 8.0 * i, line, 5.6, NOTE_GREY)
    pen.flush()

    doc.set_metadata({
        "title": f"JLCPCB invoice {data.get('invoiceNo') or data.get('batchNum')}",
        "subject": f"Assembly order {data.get('batchNum')}",
        "creator": "7Sigma platform, drawn from JLCPCB invoiceOrder",
        "producer": f"PyMuPDF {fitz.VersionBind}",
    })
    doc.subset_fonts()
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out


# ----------------------------------------------------------- the attachment
def filename(doc: M.RunCostDocument, batch: str) -> str:
    """Dated and keyed like the other JLCPCB files."""
    return f"{doc.doc_date or 'undated'}-JLCPCB-invoice-{batch}.pdf"


def _check(doc: M.RunCostDocument, data: dict) -> list[str]:
    """Refuse a response that is not this order's invoice; return what
    disagrees with the document as warnings."""
    want = (doc.external_id or "").upper()
    if _s(data.get("batchNum")).upper() != want:
        raise InvoicePdfError(f"JLCPCB answered for {data.get('batchNum')!r}, not {doc.external_id}")
    if not data.get("invoiceListResponseList"):
        raise InvoicePdfError(f"JLCPCB's invoice for {doc.external_id} has no positions")
    secret = [k for k, v in data.items() if isinstance(v, str) and v.startswith("{secret}")]
    if secret:
        raise InvoicePdfError(f"could not decrypt {', '.join(secret)} of {doc.external_id}; nothing attached")
    warnings = []
    if doc.doc_number and _s(data.get("invoiceNo")) != doc.doc_number:
        warnings.append(f"invoice number: the document says {doc.doc_number}, JLCPCB {data.get('invoiceNo')}")
    total = data.get("totalMoney")
    if doc.total_amount is not None and total not in (None, "") and abs(float(total) - float(doc.total_amount)) > 0.005:
        warnings.append(f"total: the document says {doc.total_amount}, JLCPCB {total}")
    return warnings


def attach(db: Session, doc: M.RunCostDocument, *, force: bool = False, actor: str = "user") -> dict:
    """Fetch the invoice data of one JLCPCB assembly order, draw it, and file
    the PDF with its document. The new file is added, never put in place of
    one, and becomes the headline file. A document that already has a PDF is
    left alone unless `force`. The caller commits."""
    batch = (doc.external_id or "").upper()
    if not batch.startswith("W"):
        raise InvoicePdfError(f"document {doc.id} is not a JLCPCB assembly order (external id {doc.external_id!r})")
    if not force and _pdfs(db, doc.id):
        return {"document_id": doc.id, "status": "skipped", "reason": "the document already has a PDF"}
    data = jlc_web.get_manufacturing_invoice(db, batch, reveal=True)
    warnings = _check(doc, data)
    a = document_files.add(db, doc, filename(doc, batch), "application/pdf", render(data))
    audit(db, "jlc.manufacturing.invoice_pdf", "run_attachment", a.id,
          {"document_id": doc.id, "batch": batch, "filename": a.filename, "size_bytes": a.size_bytes,
           "warnings": warnings}, actor=actor)
    return {"document_id": doc.id, "status": "attached", "attachment_id": a.id, "filename": a.filename,
            "proforma": False, "warnings": warnings}
