"""JLCPCB's parts invoice, drawn from the data its own page draws (decision 0082).

JLCPCB keeps no invoice FILE for a parts order (`POB…`). Its invoice page
fetches `presaleOrder/getInvoiceInfo` (`jlc_web.get_parts_invoice`) and the
DOWNLOAD button screenshots that page in the browser: html2canvas, then one
JPEG on A4 pages through jsPDF. This module draws the same page from the same
response, as text and rectangles, so the result can be searched and stays
sharp.

Every position, size and colour below was measured on a PDF that button
produced (POB0202509301912457, 2025-09-30), at 600 dpi. Two differences are
deliberate:

* **The font is Helvetica**, with PyMuPDF's CJK font for the glyphs Helvetica
  lacks (℃, 、). The browser font is a system font of whoever pressed the
  button, and nothing here may depend on that. The sizes are matched on WIDTH,
  so the columns break their text at nearly the same character; the font
  metrics differ, so one break in a long description can land a character
  earlier or later than JLCPCB's.
* **A row never splits across pages.** JLCPCB slices one tall image into A4
  pages and cuts through whatever row the edge lands on.

The text is JLCPCB's: the labels from its English language pack, everything
else from the response. Nothing here computes an amount.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import fitz
from sqlalchemy.orm import Session

from .. import models as M
from ..routers.util import audit
from . import document_files, jlc_web

PAGE_W, PAGE_H = 595.28, 841.89
LOGO = Path(__file__).parent / "assets" / "jlcpcb_invoice_logo.png"


def _rgb(hex6: str) -> tuple[float, float, float]:
    return tuple(int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))


INK = _rgb("222222")
BLUE = _rgb("2385fc")
TITLE_GREY = _rgb("999999")
NOTE_GREY = _rgb("666666")
DIVIDER = _rgb("dddddd")
HEADER_BG = _rgb("666666")
STRIPE = _rgb("f7faff")
ROW_LINE = _rgb("ebeef5")
NOTE_BG = _rgb("f5f6f9")
WHITE = (1.0, 1.0, 1.0)

# Left column: the seller, as JLCPCB prints it.
SELLER = "JiaLiChuang (HongKong) Co., Limited"
SELLER_LINES = ["Unit 21, 28/F, Metropole Square", "No.2 On Yiu Street, Shatin", "New Territories", "HONG KONG"]
CONTACT_LINES = ["support@jlcpcb.com", "+86 755 23919769", "JLCPCB.COM"]
LEFT_X = 113.28
LOGO_RECT = fitz.Rect(113.04, 17.35, 168.54, 29.42)
SELLER_BASE = 40.0
SELLER_SIZE = 5.1
BODY = 5.77                 # the 16 px body text
LEAD = 9.72                 # its 28 px line height
SELLER_LINES_BASE = 55.44
CONTACT_BASE = 108.36

# Right column: anchored on its RIGHT edge and as wide as its widest line, the
# way the page's flex box lays it out, so the divider is as long as that line.
RIGHT_EDGE = 464.9
RIGHT_MAX_W = 250.0
TITLE_SIZE = 18.0
TITLE_BASE = 36.72
LABEL_SIZE = 5.5
LABEL_BASES = (55.3, 67.8, 80.3)
VALUE_GAP = 5.0
DIVIDER_Y, DIVIDER_W = 86.52, 0.48
BUYER_BASE = 100.8
CONTACT_GAP = 16.56         # postal block to "Email:", baseline to baseline beyond one line

# The positions table.
TABLE_X0, TABLE_X1 = 113.28, 482.16
HEADER_GAP = 20.16          # last right-column baseline to the header band
HEADER_H = 17.88
HEADER_SIZE = 5.6
HEADER_TEXT_DY = 11.4       # band top to header baseline
CELL = 4.85                 # the 14 px cell text
CELL_LINE = 7.97            # the cell's 23 px line height
ROW_MIN = 13.87             # h-40
ROW_PAD = 4.1               # 12 px of cell padding
CAP_MID = 1.75              # half Helvetica's cap height at CELL
COLUMNS = (                 # header, text x, wrap width
    ("Mfr. Part #", 123.7, 46.5),
    ("Description", 182.95, 161.5),
    ("QTY", 367.35, 27.0),
    ("Unit Price", 398.65, 43.0),
    ("Ext. Price", 447.4, 30.5),
)

# Totals: each line right-aligned, a 130 px label then a value at least 80 px wide.
TOTALS_RIGHT = 482.2
TOTALS_LABEL_W = 47.4
TOTALS_VALUE_MIN = 27.9
TOTALS_SIZE = 5.6           # the label
TOTALS_VALUE_SIZE = 6.05    # the amount: its digits run wider than Helvetica's
TOTALS_GAP = 21.05          # table bottom to the first totals baseline
TOTALS_PITCH = 12.6

TOP = 20.0                  # where a continued page starts
BOTTOM = PAGE_H - 20.0

ESTIMATE_NOTE = ("Proforma Invoice is for reference only prior to payment. "
                 "The actual payment amount is subject to the final procurement results.")

_FONTS: dict[str, fitz.Font] = {}


def _font(name: str) -> fitz.Font:
    if name not in _FONTS:
        _FONTS[name] = fitz.Font(name)
    return _FONTS[name]


def _runs(text: str, bold: bool):
    """Split `text` into runs of one font: Helvetica, or the CJK font for a
    glyph Helvetica does not have."""
    main, other = _font("hebo" if bold else "helv"), _font("cjk")
    run, cur = "", None
    for ch in text:
        f = main if main.has_glyph(ord(ch)) else other
        if run and f is not cur:
            yield cur, run
            run = ""
        cur, run = f, run + ch
    if run:
        yield cur, run


def width(text: str, size: float, bold: bool = False) -> float:
    return sum(f.text_length(r, size) for f, r in _runs(text, bold))


class _Pen:
    """The text of one page, one TextWriter per colour."""

    def __init__(self, page: fitz.Page):
        self.page = page
        self.writers: dict[tuple, fitz.TextWriter] = {}

    def text(self, x: float, y: float, text: str, size: float, colour=INK, bold: bool = False) -> float:
        tw = self.writers.setdefault(colour, fitz.TextWriter(self.page.rect))
        for f, r in _runs(text, bold):
            _, end = tw.append((x, y), r, font=f, fontsize=size)
            x = end.x
        return x

    def flush(self) -> None:
        for colour, tw in self.writers.items():
            tw.write_text(self.page, color=colour)
        self.writers = {}


def break_all(text: str, size: float, limit: float) -> list[str]:
    """CSS `word-break: break-all`, which JLCPCB's table cells use: a line ends
    at whichever character no longer fits. A space at the break is dropped."""
    lines, line, w = [], "", 0.0
    for ch in " ".join(str(text or "").split()):
        cw = width(ch, size)
        if line and w + cw > limit:
            lines.append(line.rstrip())
            line, w = "", 0.0
        if not line and ch == " ":
            continue
        line, w = line + ch, w + cw
    if line:
        lines.append(line.rstrip())
    return lines or [""]


def wrap_words(text: str, size: float, limit: float) -> list[str]:
    """Ordinary wrapping, at spaces. A word longer than the line overflows it."""
    lines, line = [], ""
    for word in str(text or "").split(" "):
        trial = f"{line} {word}" if line else word
        if line and width(trial, size) > limit:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    return lines


def money(value, currency: str, symbol: str, digits: int = 2) -> str:
    """JLCPCB's `MCS`: `USD $0.3360` — currency, a space, symbol, fixed decimals."""
    q = Decimal(str(value if value not in (None, "") else 0)).quantize(Decimal(1).scaleb(-digits), ROUND_HALF_UP)
    return f"{currency} {symbol}{q}".strip()


def _s(v) -> str:
    return "" if v is None else str(v)


def render(data: dict) -> bytes:
    """The invoice PDF for one `getInvoiceInfo` response, its `{secret}`
    fields already decrypted (`jlc_web.get_parts_invoice(..., reveal=True)`)."""
    cur = data.get("settleCurrencyInfoVO") or {}
    currency = _s(cur.get("settleCurrency")) or "USD"
    symbol = _s(cur.get("settleCurrencySymbol")) or "$"
    batch = _s(data.get("orderBatchNo"))

    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    pen = _Pen(page)

    # -- left column
    page.insert_image(LOGO_RECT, filename=str(LOGO))
    pen.text(LEFT_X, SELLER_BASE, SELLER, SELLER_SIZE, BLUE)
    for i, line in enumerate(SELLER_LINES):
        pen.text(LEFT_X, SELLER_LINES_BASE + i * LEAD, line, BODY)
    for i, line in enumerate(CONTACT_LINES):
        pen.text(LEFT_X, CONTACT_BASE + i * LEAD, line, BODY)

    # -- right column
    title = "Proforma Invoice" if data.get("estimateInvoiceFlag") else "INVOICE"
    labels = [("Invoice No.:", _s(data.get("invoiceNo"))), ("Invoice Date:", _s(data.get("invoiceDate"))),
              ("Batch No.:", batch)]
    address = ",".join(_s(data.get(k)) for k in ("countryName", "stateName", "cityName", "streetAddress", "buildingNo"))
    buyer = [_s(data.get("companyName")), _s(data.get("firstName")) + _s(data.get("lastName")), address,
             _s(data.get("postalCode")), _s(data.get("countryName"))]
    contact = ["Email:" + _s(data.get("email")), "Tel:" + _s(data.get("mobileNumber")),
               "VAT No:" + _s(data.get("eoriNumber"))]
    natural = [width(title, TITLE_SIZE, True)]
    natural += [width(lab, LABEL_SIZE, True) + VALUE_GAP + width(val, BODY) for lab, val in labels]
    natural += [width(t, BODY) for t in buyer + contact]
    col_w = min(max(natural), RIGHT_MAX_W)
    x0 = RIGHT_EDGE - col_w

    pen.text(x0, TITLE_BASE, title, TITLE_SIZE, TITLE_GREY, bold=True)
    for (lab, val), y in zip(labels, LABEL_BASES):
        end = pen.text(x0, y, lab, LABEL_SIZE, bold=True)
        pen.text(end + VALUE_GAP, y, val, BODY)
    page.draw_line((x0, DIVIDER_Y + DIVIDER_W / 2), (x0 + col_w, DIVIDER_Y + DIVIDER_W / 2),
                   color=DIVIDER, width=DIVIDER_W)
    y = BUYER_BASE
    for t in buyer:
        for line in wrap_words(t, BODY, col_w):
            pen.text(x0, y, line, BODY)
            y += LEAD
    y += CONTACT_GAP - LEAD
    for t in contact:
        for line in wrap_words(t, BODY, col_w):
            pen.text(x0, y, line, BODY)
            y += LEAD
    last_base = y - LEAD

    # -- the table header
    top = last_base + HEADER_GAP
    page.draw_rect(fitz.Rect(TABLE_X0, top, TABLE_X1, top + HEADER_H), color=None, fill=HEADER_BG, width=0)
    for head, x, _ in COLUMNS:
        pen.text(x, top + HEADER_TEXT_DY, head, HEADER_SIZE, WHITE, bold=True)
    y = top + HEADER_H

    # -- the rows
    for n, item in enumerate(data.get("componentGoodsVOList") or []):
        cells = [_s(item.get("componentModel")), _s(item.get("description")), _s(item.get("settlePresaleNumber")),
                 money(item.get("settleGoodsPrice"), currency, symbol, 4),
                 money(item.get("settleGoodsPaidMoney"), currency, symbol, 2)]
        wrapped = [break_all(c, CELL, w) for c, (_, _, w) in zip(cells, COLUMNS)]
        h = max(ROW_MIN, ROW_PAD + CELL_LINE * max(len(w) for w in wrapped))
        if y + h > BOTTOM:
            pen.flush()
            page = doc.new_page(width=PAGE_W, height=PAGE_H)
            pen = _Pen(page)
            y = TOP
        if n % 2:
            page.draw_rect(fitz.Rect(TABLE_X0, y, TABLE_X1, y + h), color=None, fill=STRIPE, width=0)
        page.draw_line((TABLE_X0, y + h - 0.17), (TABLE_X1, y + h - 0.17), color=ROW_LINE, width=0.35)
        for lines, (_, x, _) in zip(wrapped, COLUMNS):
            block_top = y + (h - CELL_LINE * len(lines)) / 2
            for i, line in enumerate(lines):
                pen.text(x, block_top + CELL_LINE * i + CELL_LINE / 2 + CAP_MID, line, CELL)
        y += h

    # -- totals: only the figures JLCPCB prints, in its order
    totals = []
    if data.get("totalPayment"):
        totals.append(("Subtotal", data["totalPayment"]))
    if data.get("totalOtherFee"):
        totals.append(("Others", data["totalOtherFee"]))
    if data.get("totalDiscountProductFee"):
        totals.append(("Discount", data["totalDiscountProductFee"]))
    totals.append(("Grand Total:", data.get("paidMoney")))
    base = y + TOTALS_GAP
    note_lines = wrap_words(ESTIMATE_NOTE, BODY, TABLE_X1 - TABLE_X0 - 14.0) if data.get("estimateInvoiceFlag") else []
    need = TOTALS_PITCH * (len(totals) - 1) + (7.0 + 7.0 + LEAD * len(note_lines) if note_lines else 0)
    if base + need > BOTTOM:
        pen.flush()
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        pen = _Pen(page)
        base = TOP + TOTALS_GAP
    for label, value in totals:
        text = money(value, currency, symbol, 2)
        vx = TOTALS_RIGHT - max(width(text, TOTALS_VALUE_SIZE, True), TOTALS_VALUE_MIN)
        pen.text(vx - TOTALS_LABEL_W, base, label, TOTALS_SIZE, bold=True)
        pen.text(vx, base, text, TOTALS_VALUE_SIZE, bold=True)
        base += TOTALS_PITCH
    if note_lines:
        box_top = base - TOTALS_PITCH + 7.0 + 2.0
        box = fitz.Rect(TABLE_X0, box_top, TABLE_X1, box_top + 7.0 + LEAD * len(note_lines))
        page.draw_rect(box, color=None, fill=NOTE_BG, width=0)
        for i, line in enumerate(note_lines):
            pen.text(TABLE_X0 + 7.0, box_top + 3.5 + LEAD * i + LEAD / 2 + 2.07, line, BODY, NOTE_GREY)
    pen.flush()

    doc.set_metadata({
        "title": f"JLCPCB invoice {data.get('invoiceNo') or batch}",
        "subject": f"Parts order {batch}",
        "creator": "7Sigma platform, drawn from JLCPCB getInvoiceInfo",
        "producer": f"PyMuPDF {fitz.VersionBind}",
    })
    doc.subset_fonts()
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out


# ----------------------------------------------------------- the attachment
class InvoicePdfError(ValueError):
    """The response cannot become this document's invoice: nothing is attached."""


def filename(doc: M.RunCostDocument) -> str:
    """What JLCPCB's button would save, dated and keyed like the other files."""
    return f"{doc.doc_date or 'undated'}-JLCPCB-componentInovice-{doc.external_id}.pdf"


def _check(doc: M.RunCostDocument, data: dict) -> list[str]:
    """Refuse a response that is not this order's invoice; return what disagrees
    with the document as warnings, for the person to look at."""
    pob = doc.external_id
    if _s(data.get("orderBatchNo")) != pob:
        raise InvoicePdfError(f"JLCPCB answered for {data.get('orderBatchNo')!r}, not {pob}")
    if not data.get("componentGoodsVOList"):
        raise InvoicePdfError(f"JLCPCB's invoice for {pob} has no positions")
    secret = [k for k, v in data.items() if isinstance(v, str) and v.startswith("{secret}")]
    if secret:
        raise InvoicePdfError(f"could not decrypt {', '.join(secret)} of {pob}; nothing attached")
    warnings = []
    if doc.doc_number and _s(data.get("invoiceNo")) != doc.doc_number:
        warnings.append(f"invoice number: the document says {doc.doc_number}, JLCPCB {data.get('invoiceNo')}")
    paid = data.get("paidMoney")
    if doc.total_amount is not None and paid is not None and abs(float(paid) - float(doc.total_amount)) > 0.005:
        warnings.append(f"total: the document says {doc.total_amount}, JLCPCB {paid}")
    return warnings


def attach(db: Session, doc: M.RunCostDocument, *, force: bool = False, actor: str = "user") -> dict:
    """Fetch the invoice data of one JLCPCB parts order, draw it, and file the
    PDF with its document. A document that already has a PDF is left alone
    unless `force`; the new file is added, never put in place of one. The
    caller commits."""
    if not (doc.external_id or "").startswith("POB"):
        raise InvoicePdfError(f"document {doc.id} is not a JLCPCB parts order (external id {doc.external_id!r})")
    if not force and document_files.has_pdf(db, doc.id):
        return {"document_id": doc.id, "status": "skipped", "reason": "the document already has a PDF"}
    data = jlc_web.get_parts_invoice(db, doc.external_id, reveal=True)
    warnings = _check(doc, data)
    a = document_files.add(db, doc, filename(doc), "application/pdf", render(data))
    audit(db, "jlc.parts.invoice_pdf", "run_attachment", a.id,
          {"document_id": doc.id, "pob": doc.external_id, "filename": a.filename, "size_bytes": a.size_bytes,
           "warnings": warnings}, actor=actor)
    return {"document_id": doc.id, "status": "attached", "attachment_id": a.id, "filename": a.filename,
            "buyer": _s(data.get("companyName")), "buyer_vat": _s(data.get("eoriNumber")),
            "warnings": warnings}
