"""What a supplier document IS in Polish law, and what that means for its VAT
(decision 0087).

`RunCostDocument.doc_type` says how the platform counts the money (a proforma
is not stock, a transfer moves between companies). `kind` says what the paper
is in law, and it decides whether the VAT on it can be deducted at all. The two
are kept apart on purpose: a debit note and an invoice count their money the
same way and differ only in what they mean for VAT.

The rules, checked against the statute texts on 2026-10-07 (research and
sources in decision 0087):

* Input VAT comes from invoices (art. 86 ust. 2 pkt 1 VAT act) — a VAT
  invoice, its correction, an advance or a settlement invoice, a receipt with
  the buyer's NIP up to 450 PLN (a simplified invoice, art. 106e ust. 5 pkt 3
  and ust. 6), a single ticket (§ 3 pkt 4 of the invoicing regulation) — and,
  for an import, from the customs document (art. 86 ust. 2 pkt 2).
* A receipt without the NIP or above 450 PLN, a debit, credit or interest
  note, an insurance policy, a bill (rachunek), a bank statement, an internal
  voucher and a proforma give no input VAT.
* A passenger car used for business and private purposes gives 50 % of the
  VAT on its costs (art. 86a ust. 1); accommodation and catering give none
  (art. 88 ust. 1 pkt 4). These are document flags (`vat_rule`), because
  they depend on what was bought, not on the paper.
"""
from __future__ import annotations

from decimal import Decimal

#: slug -> (Polish name, the VAT on it can be deducted)
KINDS: dict[str, tuple[str, bool]] = {
    "invoice": ("Faktura VAT", True),
    "invoice_correction": ("Faktura korygująca", True),
    "advance_invoice": ("Faktura zaliczkowa", True),
    "settlement_invoice": ("Faktura rozliczeniowa", True),
    "simplified_invoice": ("Paragon z NIP do 450 zł (faktura uproszczona)", True),
    "ticket": ("Bilet jednorazowy (faktura)", True),
    "customs_document": ("Dokument celny (PZC / ZC299 / SAD)", True),
    "receipt": ("Paragon (bez NIP lub ponad 450 zł)", False),
    "bill": ("Rachunek", False),
    "debit_note": ("Nota obciążeniowa", False),
    "credit_note": ("Nota uznaniowa", False),
    "interest_note": ("Nota odsetkowa", False),
    "note_correction": ("Korekta noty", False),
    "policy": ("Polisa ubezpieczeniowa", False),
    "bank_statement": ("Wyciąg bankowy (opłaty)", False),
    "internal": ("Dowód wewnętrzny", False),
    "proforma": ("Faktura proforma", False),
    "placeholder": ("Zapis bez dokumentu", False),
    "transfer": ("Przesunięcie między spółkami", False),
}

#: slug -> (description, the share of the VAT that can be deducted)
VAT_RULES: dict[str, tuple[str, Decimal]] = {
    "car_mixed": ("Samochód osobowy, użytek mieszany: 50 % VAT (art. 86a ust. 1)", Decimal("0.5")),
    "accommodation_catering": ("Usługi noclegowe lub gastronomiczne: bez odliczenia (art. 88 ust. 1 pkt 4)", Decimal(0)),
}

#: KSeF's invoice type -> kind
KSEF_KIND = {"Vat": "invoice", "Kor": "invoice_correction", "KorZal": "invoice_correction",
             "KorRoz": "invoice_correction", "Zal": "advance_invoice", "Roz": "settlement_invoice",
             "Upr": "simplified_invoice", "VatPef": "invoice", "VatRr": "invoice"}


def check(kind: str | None, vat_rule: str | None) -> None:
    """Refuse a value outside the two vocabularies ("" is "not decided")."""
    if kind and kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)} (or empty)")
    if vat_rule and vat_rule not in VAT_RULES:
        raise ValueError(f"vat_rule is one of {', '.join(VAT_RULES)} (or empty)")


def deductible_share(kind: str | None, vat_rule: str | None) -> Decimal:
    """The share of a document's VAT that can be deducted. A document whose
    kind nobody decided yet counts in full, as before decision 0087, so a
    missing classification never hides VAT; the classification job leaves
    none undecided."""
    share = Decimal(1) if not kind or KINDS.get(kind, ("", True))[1] else Decimal(0)
    if vat_rule in VAT_RULES:
        share *= VAT_RULES[vat_rule][1]
    return share


def as_json() -> dict:
    """The two vocabularies, for a form."""
    return {"kinds": [{"value": k, "label": v[0], "deductible": v[1]} for k, v in KINDS.items()],
            "vat_rules": [{"value": k, "label": v[0], "share": str(v[1])} for k, v in VAT_RULES.items()]}
