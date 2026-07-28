#!/usr/bin/env python3
"""Prototype parser for JLCPCB component invoices.

The PDFs are image-only (one JPEG per page, no text layer), so this OCRs each
page with tesseract in TSV mode and reconstructs the table from word
coordinates: money cells sit in two right-aligned columns, quantity in a third,
and rows are clustered by y. Every row is then checked arithmetically
(qty x unit_price == ext_price, within unit-price rounding) and the page's line
total is reconciled against the printed Subtotal / Grand Total — so an OCR
misread shows up as a number that does not add up, rather than as silently
wrong money.
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

TESSERACT = "/opt/homebrew/bin/tesseract"
MONEY = re.compile(r"\$[\d,]+\.\d+")
INT = re.compile(r"[\d,]{1,9}")
ROW_TOL = 40  # px: same-row y tolerance


def page_images(pdf: Path):
    """Yield each DISTINCT page image once. A tall JLC invoice is rendered as a
    single image that several PDF pages reference by the same xref — OCR-ing it
    per page would double every line and every total."""
    doc = pymupdf.open(pdf)
    seen: set[int] = set()
    for pno in range(doc.page_count):
        for im in doc[pno].get_images(full=True):
            if im[0] in seen:
                continue
            seen.add(im[0])
            x = doc.extract_image(im[0])
            yield pno + 1, x["ext"], x["image"]


def ocr_words(img_bytes: bytes, ext: str) -> list[dict]:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"page.{ext}"
        p.write_bytes(img_bytes)
        subprocess.run([TESSERACT, str(p), str(Path(td) / "out"), "tsv"],
                       check=True, capture_output=True)
        with open(Path(td) / "out.tsv") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
    return [
        {"t": r["text"], "x": int(r["left"]), "y": int(r["top"]),
         "w": int(r["width"]), "conf": float(r["conf"])}
        for r in rows if r["text"].strip()
    ]


def num(t: str) -> float:
    return float(t.replace("$", "").replace(",", ""))


def near(cands: list[dict], y: int, tol: int = ROW_TOL) -> dict | None:
    hit = [c for c in cands if abs(c["y"] - y) <= tol]
    return min(hit, key=lambda c: abs(c["y"] - y)) if hit else None


def header(words: list[dict]) -> dict:
    """Invoice No / Batch No / Invoice Date, wherever OCR put them."""
    joined = " ".join(w["t"] for w in words)
    out: dict = {}
    if m := re.search(r"Invoice\s*No:?\s*(\d{10,})", joined):
        out["invoice_no"] = m.group(1)
    if m := re.search(r"Batch\s*No:?\s*([A-Z0-9]{8,})", joined):
        out["batch_no"] = m.group(1)
    if m := re.search(r"Invoice\s*Date:?\s*(\d{2}/\d{2}/\d{4})", joined):
        d, mo, y = m.group(1).split("/")
        out["doc_date"] = f"{y}-{mo}-{d}"           # DD/MM/YYYY on the document
    # Loose numbers when the label and value were split across OCR blocks.
    if "invoice_no" not in out:
        cand = [w["t"] for w in words if re.fullmatch(r"\d{20,}", w["t"])]
        if cand:
            out["invoice_no"] = cand[0]
    if "batch_no" not in out:
        cand = [w["t"] for w in words if re.fullmatch(r"POB\d{10,}", w["t"])]
        if cand:
            out["batch_no"] = cand[0]
    # Totals block: Subtotal, optional extra charges ("Others", "Shipping",
    # "Handling", "Tax"), then Grand Total. The gap between subtotal and grand
    # total is a real cost that is NOT in the item table — it has to become a
    # document-level charge line, otherwise the invoice silently under-reports.
    charges: list[dict] = []
    for w in words:
        label = w["t"].rstrip(":")
        if label in ("Subtotal", "Grand", "Others", "Shipping", "Handling", "Tax", "Discount"):
            m2 = near([x for x in words if MONEY.fullmatch(x["t"])], w["y"], 25)
            if not m2:
                continue
            v = num(m2["t"])
            if label == "Subtotal":
                out["subtotal"] = v
            elif label == "Grand":
                out["grand"] = v
            else:
                charges.append({"label": label, "amount": v})
    if charges:
        out["charges"] = charges
    # BOTH the invoice number and the batch number embed the invoice date
    # (…<YYYYMMDD>…), so the OCR-read date can be checked against them for free.
    # Digits OCR far more reliably than a slashed date, so an embedded date wins.
    embedded = None
    for src in (out.get("invoice_no", ""), out.get("batch_no", "")):
        for m in re.finditer(r"(20[12]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", src):
            embedded = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            break
        if embedded:
            break
    if embedded:
        out["embedded_date"] = embedded
        out["date_agrees"] = (out.get("doc_date") == embedded)
        out["doc_date"] = embedded          # trust the digits over the slashed date
    if b := out.get("batch_no"):
        out["batch_no"] = re.sub(r"^POBO", "POB0", b)   # common OCR slip
    return out


def parse_page(words: list[dict]) -> tuple[list[dict], dict]:
    money = [w for w in words if MONEY.fullmatch(w["t"])]
    if not money:
        return [], header(words)
    ux = min(w["x"] for w in money)
    units = [w for w in money if abs(w["x"] - ux) < 60]
    exts = [w for w in money if abs(w["x"] - ux) >= 60]
    ints = [w for w in words if INT.fullmatch(w["t"]) and w["t"].replace(",", "").isdigit()]

    # Find the quantity column by ARITHMETIC VOTING: the x-bucket whose tokens
    # match round(ext/unit) on their row. Robust against description numbers
    # like "0805" that would otherwise look like quantities.
    votes: dict[int, int] = {}
    for u in units:
        e = near(exts, u["y"])
        if not e or num(u["t"]) == 0:
            continue
        want = round(num(e["t"]) / num(u["t"]))
        for i in ints:
            if abs(i["y"] - u["y"]) <= ROW_TOL and abs(int(i["t"].replace(",", "")) - want) <= max(2, want * 0.01):
                votes[i["x"] // 50 * 50] = votes.get(i["x"] // 50 * 50, 0) + 1
    qx = max(votes, key=votes.get) if votes else None
    qty_col = [w for w in ints if qx is not None and qx - 60 <= w["x"] <= qx + 110]

    # Text left of the quantity column is MPN (leftmost) + description.
    lines = []
    for u in sorted(units, key=lambda w: w["y"]):
        e = near(exts, u["y"])
        q = near(qty_col, u["y"])
        if not e:
            continue
        up, ext = num(u["t"]), num(e["t"])
        qty = int(q["t"].replace(",", "")) if q else None
        left = [w for w in words if w["x"] < (qx or ux) - 80 and abs(w["y"] - u["y"]) <= ROW_TOL]
        left.sort(key=lambda w: w["x"])
        mpn = left[0]["t"] if left else ""
        # Rounding-aware check: a 4dp unit price can only explain ext within
        # +-0.00005 per unit, so scale the tolerance with quantity.
        if qty:
            slack = 0.00005 * qty + 0.011
            good = abs(qty * up - ext) <= slack
        else:
            good = False
        lines.append({"mpn": mpn, "qty": qty, "unit_price": up, "ext_price": ext, "ok": good,
                      # The printed extended price is the money that was paid;
                      # the 4dp unit price is rounded for display. Importers
                      # should use this so qty x unit reproduces the invoice.
                      "unit_price_exact": round(ext / qty, 10) if qty else up,
                      "derived_qty": round(ext / up) if up else None,
                      "conf": min([u["conf"], e["conf"]] + ([q["conf"]] if q else []))})
    return lines, header(words)


def parse_invoice(pdf: Path) -> dict:
    all_lines: list[dict] = []
    head: dict = {}
    for _pno, ext, img in page_images(pdf):
        words = ocr_words(img, ext)
        lines, h = parse_page(words)
        all_lines += lines
        for k, v in h.items():
            head.setdefault(k, v)
    lines_total = round(sum(li["ext_price"] for li in all_lines), 2)
    charges = head.get("charges", [])
    charges_total = round(sum(c["amount"] for c in charges), 2)
    grand = head.get("grand")
    subtotal = head.get("subtotal")
    # Two independent reconciliations: item lines vs Subtotal, and
    # items + charges vs Grand Total.
    sub_ok = subtotal is not None and abs(lines_total - subtotal) <= 0.05
    grand_ok = grand is not None and abs(lines_total + charges_total - grand) <= 0.05
    return {"file": pdf.name, "header": head, "lines": all_lines, "charges": charges,
            "lines_total": lines_total, "charges_total": charges_total,
            "subtotal": subtotal, "grand": grand,
            "reconciled": (grand_ok if grand is not None else sub_ok),
            "subtotal_ok": sub_ok, "grand_ok": grand_ok,
            "bad_rows": [li for li in all_lines if not li["ok"]]}


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    grand_ok = grand_bad = 0
    for pdf in sorted(folder.glob("*.pdf")):
        r = parse_invoice(pdf)
        h = r["header"]
        flag = "RECONCILED" if r["reconciled"] else "!! TOTAL MISMATCH"
        datechk = "" if h.get("date_agrees") in (None, True) else "  !! date disagrees with batch no"
        print(f"\n{pdf.name}")
        print(f"  invoice={h.get('invoice_no','?')} batch={h.get('batch_no','?')} date={h.get('doc_date','?')}{datechk}")
        chg = f" + charges ${r['charges_total']} {[c['label'] for c in r['charges']]}" if r["charges"] else ""
        print(f"  lines={len(r['lines'])}  sum=${r['lines_total']}{chg}  "
              f"subtotal=${r['subtotal']} grand=${r['grand']}  {flag}")
        if r["bad_rows"]:
            print(f"  rows failing arithmetic: {len(r['bad_rows'])}")
            for li in r["bad_rows"][:4]:
                print(f"    {li['mpn'][:22]:22} qty={li['qty']} unit={li['unit_price']} "
                      f"ext={li['ext_price']} derived_qty={li['derived_qty']}")
        grand_ok += r["reconciled"]
        grand_bad += (not r["reconciled"])
    print(f"\n=== {grand_ok} invoices reconciled, {grand_bad} need review ===")
