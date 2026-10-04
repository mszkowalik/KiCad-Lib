"""Sales invoices of a company that issues them (decision 0066).

Ported from 7Sigma's own invoicing script (`7sigma.py`), which kept every
sales document of 7Sigma in `rejestr.json` from 2021 to 2026-10-04. The
platform is the numbering authority from that day on.

* `amounts` — exact decimal arithmetic for positions and totals, the amount in
  Polish words, Polish dates.
* `numbering` — the four series and their monthly numbers.
* `fa3` — the FA(3) XML a VAT, correction, advance or settlement invoice is
  uploaded to KSeF as, checked against the Ministry's schema in `schema/`.
* `pdf` — the printed document, with the KSeF verification QR code once the
  invoice has a KSeF number.
* `service` — creating, issuing, correcting and importing.
"""
