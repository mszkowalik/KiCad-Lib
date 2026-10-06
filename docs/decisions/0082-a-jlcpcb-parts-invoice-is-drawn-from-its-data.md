---
status: "accepted"
date: 2026-10-06  # accepted 2026-10-06 (user: "option 1, make sure it looks the same")
decision-makers: Mateusz Kowalik
consulted: Claude
---

# A JLCPCB parts invoice is drawn from JLCPCB's own invoice data

## Context and Problem Statement

Eleven JLCPCB parts orders (`POB…`) on the platform had no invoice file on
2026-10-06, among them seven 9SIGMA documents KSBR has to book. The user asked
whether the platform can download them.

JLCPCB keeps no file to download. Its invoice page fetches
`presaleOrder/getInvoiceInfo`, the call `jlc_web.get_parts_invoice` already
makes with the stored browser session, and its DOWNLOAD button runs
html2canvas over the page and saves the screenshot through jsPDF as
`componentInovice.pdf`. No request leaves the browser for it. Every JLCPCB
parts invoice in the user's folders was made that way.

The response sends the buyer's street, building number and e-mail encrypted:
SM2 (GB/T 32918), cipher mode C1C3C2, with the key pair of the session's
`secret/update` call. The page decrypts them in the browser.

## Decision Drivers

* The accountant needs a document for each order, and the user wants it to
  look like the ones JLCPCB's button made.
* No new dependency in the api image, and nothing that breaks when JLCPCB
  restyles its page.
* The figures must be JLCPCB's, never recomputed.

## Considered Options

* Draw the invoice from the API data with PyMuPDF.
* Run the button: a headless browser opens the page with the session and
  screenshots `#print`.
* The user downloads each one by hand.

## Decision Outcome

Chosen option: draw it from the API data, because it needs nothing new, the
text stays searchable, and it does not depend on the page's markup.

1. **`services/jlc_invoice_pdf.py` draws the page** with PyMuPDF, at the
   positions, sizes and colours measured on a PDF the button made
   (POB0202509301912457). The font is Helvetica with PyMuPDF's CJK font for
   ℃ and 、, sized to match widths. The labels are JLCPCB's English language
   pack; every value comes from the response.
2. **`services/sm2.py` decrypts the `{secret}` fields** in pure Python (SM3 is
   in `hashlib`). `jlc_web.WebClient` keeps the private key of the key pair it
   minted; `get_parts_invoice(..., reveal=True)` decrypts.
3. **It is filed as an ordinary attachment** (`services/document_files.py`).
   The import of a parts order attaches it at once, best effort. `POST
   /api/jlc/web/invoice-pdfs` draws it for documents that exist, and skips a
   document that already has a PDF unless `force`.
4. **A response that is not the order's invoice attaches nothing**: another
   batch number, no positions, or a field still encrypted. A different
   invoice number or total is a warning in the result and the audit row.
5. The PDF metadata says the platform drew it from `getInvoiceInfo`.

### Consequences

* Good, because every parts order can have its invoice with no manual step.
* Good, because the file shows today's data. JLCPCB's descriptions change
  over time, and so did its button's output.
* Bad, because it is not pixel-identical: the font differs, so a long
  description can break one character earlier or later than JLCPCB's.
* Bad, because the layout is a copy. If JLCPCB redesigns its invoice, this
  one stays as it is until somebody re-measures it.

### Confirmation

`api/tests/costs/test_jlc_invoice_pdf.py`: SM2 round trip and wrong-key
refusal; secrets decrypted in nested payloads and kept when unreadable; the
PDF text carries the seller, the buyer, every position and the totals; a
long order continues on a second page; an estimate prints "Proforma Invoice"
and JLCPCB's note; the file is filed once, `force` adds another, and each
kind of wrong response attaches nothing.

## Pros and Cons of the Options

### A headless browser runs the button

* Good, because the file would be the button's own output.
* Bad, because the api image has no Chromium, and the button's output depends
  on the browser window: the user's two 2025 files are drawn at different
  scales.
* Bad, because it breaks whenever JLCPCB changes the page.

### Download by hand

* Good, because no code.
* Bad, because every new order needs it, and the session that has the data is
  already on the server.

## More Information

Code: `api/app/services/jlc_invoice_pdf.py`, `api/app/services/sm2.py`,
`api/app/services/jlc_web.py` (`get_parts_invoice`, `reveal_secrets`),
`api/app/services/document_files.py`, `api/app/routers/jlc_web.py`
(`invoice_pdfs`), `api/app/routers/jlc_import.py` (`_attach_invoice_pdf`).
