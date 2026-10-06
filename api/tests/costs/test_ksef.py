"""KSeF read-out (decision 0067), against a fake KSeF: the token is encrypted
for the Ministry's key, the inbox fills without touching money, a sales draft is
issued by its KSeF twin, an invoice written in KSeF takes its number out of the
series, and a purchase becomes a supplier document only when asked.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_ksef.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import base64
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import companies as C
from app.services import crypto
from app.services.invoicing import amounts as A
from app.services.invoicing import fa3, numbering
from app.services.invoicing import service as S
from app.services.ksef import client as K
from app.services.ksef import sync as Y
from app.services.ksef.parse import parse


@pytest.fixture
def db():
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def _cert():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return key, base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()


def test_the_token_is_encrypted_for_the_ministry_key():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    key, der = _cert()
    seen = {}
    now = datetime.now(UTC)

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p.endswith("/security/public-key-certificates"):
            return httpx.Response(200, json=[{"usage": ["KsefTokenEncryption"], "certificate": der,
                                              "validFrom": (now - timedelta(days=1)).isoformat(),
                                              "validTo": (now + timedelta(days=1)).isoformat()}])
        if p.endswith("/auth/challenge"):
            return httpx.Response(200, json={"challenge": "CH", "timestampMs": 1234})
        if p.endswith("/auth/ksef-token"):
            body = json.loads(req.content)
            seen["plain"] = key.decrypt(base64.b64decode(body["encryptedToken"]),
                                        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                     algorithm=hashes.SHA256(), label=None)).decode()
            seen["nip"] = body["contextIdentifier"]["value"]
            return httpx.Response(200, json={"authenticationToken": {"token": "AT"}, "referenceNumber": "R"})
        if p.endswith("/auth/R"):
            return httpx.Response(200, json={"status": {"code": 200}})
        if p.endswith("/auth/token/redeem"):
            return httpx.Response(200, json={"accessToken": {"token": "ACCESS"}})
        if p.endswith("/invoices/query/metadata"):
            seen["auth"] = req.headers["Authorization"]
            return httpx.Response(200, json={"invoices": [{"ksefNumber": "X"}], "hasMore": False})
        return httpx.Response(404)

    cl = K.Client("SECRET-TOKEN", "8513262910", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    rows = cl.metadata("sales", date(2026, 9, 1), date(2026, 9, 2))
    assert rows == [{"ksefNumber": "X"}]
    assert seen == {"plain": "SECRET-TOKEN|1234", "nip": "8513262910", "auth": "Bearer ACCESS"}


def test_a_long_rate_limit_is_never_slept_through():
    def handler(req):
        return httpx.Response(429, headers={"Retry-After": "1800"})

    cl = K.Client("t", "1", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(K.RateLimited) as e:
        cl._call("POST", "/invoices/query/metadata")
    assert e.value.seconds == 1800


@pytest.fixture
def seven(db):
    c = C.by_key(db, "7sigma")
    c.issues_invoices = True
    cust = M.Customer(name="TEST-KSEF-BUYER", legal_name="KSEF BUYER", tax_id="5213545223",
                      address_l1="a", address_l2="b")
    db.add(cust)
    db.flush()
    cred = Y.credential(db, c.id, create=True)
    cred.token_enc = crypto.encrypt_token("t")
    cred.rate_limited_until = None
    cred.sales_read_to = cred.purchases_read_to = ""
    db.flush()
    return SimpleNamespace(c=c, cust=cust)


class FakeKsef:
    """What KSeF answers: metadata per side and the XML per number."""

    def __init__(self, sales, purchases, xmls):
        self.sales, self.purchases, self.xmls = sales, purchases, xmls

    def __call__(self, token, nip):
        return self

    def metadata(self, side, start, end):
        return self.sales if side == "sales" else self.purchases

    def xml(self, number):
        return self.xmls[number]

    def close(self):
        pass


def _meta(number, inv_number, xml, seller, buyer, typ="Vat", day="2049-03-10"):
    return {"ksefNumber": number, "invoiceNumber": inv_number, "invoiceType": typ, "issueDate": day,
            "seller": {"nip": seller}, "buyer": {"identifier": {"value": buyer}, "name": "B"},
            "netAmount": 100, "vatAmount": 23, "grossAmount": 123, "currency": "PLN",
            "invoiceHash": base64.b64encode(hashlib.sha256(xml).digest()).decode(),
            "acquisitionDate": f"{day}T10:00:00Z"}


def test_a_sync_issues_the_draft_and_records_what_ksef_alone_holds(db, seven, monkeypatch):
    store = {}
    monkeypatch.setattr("app.services.storage.put_bytes", lambda k, d, ct="": store.__setitem__(k, d))
    monkeypatch.setattr("app.services.storage.get_bytes", lambda k: store.get(k))
    lines = [{"name": "Usługa", "qty": 1, "unit_net": "100", "vat_rate": "23"}]
    draft = S.create(db, company_id=seven.c.id, kind="vat", customer_id=seven.cust.id,
                     issue_date="2049-03-10", lines=lines)
    xml_draft = fa3.build(draft)
    direct = SimpleNamespace(kind="vat", currency="PLN", issue_date="2049-03-11", sale_date="2049-03-11",
                             number="02/03/2049", body={**draft.body})
    xml_direct = fa3.build(direct)
    n1, n2 = "8513262910-20490310-0123456789AB-01", "8513262910-20490311-0123456789AB-02"
    pur_xml = fa3.build(SimpleNamespace(kind="vat", currency="PLN", issue_date="2049-03-12",
                                        sale_date="2049-03-12", number="FV 7/2049",
                                        body={**draft.body, "seller": {"name": "DOSTAWCA SP. Z O.O.",
                                                                       "address_l1": "x", "nip": "5213545223"},
                                              "buyer": draft.body["seller"]}))
    n3 = "5213545223-20490312-0123456789AB-03"
    fake = FakeKsef(sales=[_meta(n1, draft.number, xml_draft, "8513262910", "5213545223"),
                           _meta(n2, "02/03/2049", xml_direct, "8513262910", "5213545223", day="2049-03-11")],
                    purchases=[_meta(n3, "FV 7/2049", pur_xml, "5213545223", "8513262910", day="2049-03-12")],
                    xmls={n1: xml_draft, n2: xml_direct, n3: pur_xml})
    res = Y.sync(db, seven.c.id, since="2049-03-01", client_factory=fake)
    assert res["linked"] == 1 and res["recorded"] == 1 and res["downloaded"] == 3
    db.refresh(draft)
    assert draft.status == "issued" and draft.ksef_number == n1
    assert draft.ksef_hash == S.ksef_hash(xml_draft)          # from the metadata's hash
    # the number written directly in KSeF is taken
    assert numbering.next_number(db, seven.c.id, "vat", date(2049, 3, 20)) == "03/03/2049"
    pur = db.query(M.KsefInvoice).filter_by(ksef_number=n3).one()
    assert pur.status == "new"                               # fetching writes no money
    assert db.query(M.RunCostDocument).filter_by(external_id=n3).first() is None
    monkeypatch.setattr("app.services.nbp.resolve_for_document", lambda db, cur, day: {"rate_usd": 0.25})
    doc = Y.import_purchase(db, pur, actor="test")
    assert (doc.company_id, doc.seller_tax_id, doc.doc_number) == (seven.c.id, "5213545223", "FV 7/2049")
    assert doc.total_amount == pytest.approx(100.0) and len(doc.lines) == 1
    with pytest.raises(HTTPException):
        Y.import_purchase(db, pur)


def test_a_draft_whose_number_ksef_gave_another_buyer_is_not_linked(db, seven, monkeypatch):
    monkeypatch.setattr("app.services.storage.put_bytes", lambda k, d, ct="": None)
    monkeypatch.setattr("app.services.storage.get_bytes", lambda k: None)
    draft = S.create(db, company_id=seven.c.id, kind="vat", customer_id=seven.cust.id, issue_date="2049-04-10",
                     lines=[{"name": "U", "qty": 1, "unit_net": "1", "vat_rate": "23"}])
    xml = fa3.build(draft)
    fake = FakeKsef(sales=[_meta("8513262910-20490410-0123456789AB-04", draft.number, xml, "8513262910",
                                 "1111111111", day="2049-04-10")], purchases=[], xmls={})
    fake.xml = lambda n: (_ for _ in ()).throw(K.RateLimited("/x", 60))
    res = Y.sync(db, seven.c.id, sides=("sales",), since="2049-04-01", client_factory=fake)
    assert res["refused"] and draft.status == "draft"


def test_an_ksef_invoice_reads_back_to_the_same_document(db, seven):
    lines = A.lines([{"name": "Usługa", "qty": 2, "unit_net": "12.50", "vat_rate": "8"}])
    inv = SimpleNamespace(kind="vat", currency="PLN", issue_date="2049-05-01", sale_date="2049-05-01",
                          number="05/05/2049",
                          body={"seller": S.seller_of(seven.c), "buyer": S.buyer_of(seven.cust), "place": "Kraków",
                                "lines": lines, "totals": A.totals(lines),
                                "payment": {"due_date": "2049-05-15", "method": "przelew"}, "bank": {}})
    p = parse(fa3.build(inv))
    assert (p["kind"], p["number"], p["issue_date"]) == ("vat", "05/05/2049", "2049-05-01")
    assert p["body"]["totals"]["gross"] == "27.00" and p["body"]["lines"][0]["net"] == "25.00"
    assert p["body"]["buyer"]["nip"] == "5213545223"


# --- review fixes of 2026-10-04 -------------------------------------------------

@pytest.fixture
def store(monkeypatch):
    files = {}
    monkeypatch.setattr("app.services.storage.put_bytes", lambda k, d, ct="": files.__setitem__(k, d))
    monkeypatch.setattr("app.services.storage.get_bytes", lambda k: files.get(k))
    monkeypatch.setattr("app.services.nbp.resolve_for_document", lambda db, cur, day: {"rate_usd": 0.25})
    return files


def _purchase_xml(seven, number, day, seller_name="DOSTAWCA SP. Z O.O.", seller_nip="5213545223"):
    lines = A.lines([{"name": "Usługa", "qty": 1, "unit_net": "100", "vat_rate": "23"}])
    return fa3.build(SimpleNamespace(kind="vat", currency="PLN", issue_date=day, sale_date=day, number=number,
                                     body={"seller": {"name": seller_name, "address_l1": "x", "nip": seller_nip},
                                           "buyer": S.seller_of(seven.c), "lines": lines,
                                           "totals": A.totals(lines), "payment": {"due_date": day}}))


def test_a_linked_correction_keeps_one_difference(db, seven, store):
    """KSeF states a correction's DIFFERENCE. The linked record keeps its state
    before, so its totals after are before + difference, and the books count
    the difference once."""
    from app.services import company_books as B

    inv = S.create(db, company_id=seven.c.id, kind="vat", customer_id=seven.cust.id, issue_date="2049-03-01",
                   lines=[{"name": "U", "qty": 1, "unit_net": "1000", "vat_rate": "23"}])
    inv.status = "issued"
    kor = S.correct(db, inv, issue_date="2049-03-05", reason="cena")
    S.update(db, kor, {"lines": [{"name": "U", "qty": 1, "unit_net": "800", "vat_rate": "23"}]})
    xml = fa3.build(kor)
    n = "8513262910-20490305-0123456789AB-31"
    meta = {**_meta(n, kor.number, xml, "8513262910", "5213545223", typ="Kor", day="2049-03-05")}
    Y.sync(db, seven.c.id, sides=("sales",), since="2049-03-01",
           client_factory=FakeKsef(sales=[meta], purchases=[], xmls={n: xml}))
    db.refresh(kor)
    assert kor.status == "issued" and kor.ksef_number == n
    assert kor.amount_due == A.d2("-246.00") and kor.body["totals"]["gross"] == "984.00"
    mar = B.year(db, seven.c.id, 2049)["months"][2]
    assert (mar["revenue_net"], mar["sales_vat"]) == ("800.00", "184.00")


def test_an_invoice_between_our_companies_is_in_both_inboxes(db, seven, store):
    nine = C.by_key(db, "9sigma")
    cred = Y.credential(db, nine.id, create=True)
    cred.token_enc, cred.rate_limited_until = crypto.encrypt_token("t"), None
    cred.sales_read_to = cred.purchases_read_to = ""
    db.flush()
    lines = A.lines([{"name": "Usługa", "qty": 1, "unit_net": "100", "vat_rate": "23"}])
    xml = fa3.build(SimpleNamespace(kind="vat", currency="PLN", issue_date="2049-06-01", sale_date="2049-06-01",
                                    number="01/06/2049", body={"seller": S.seller_of(seven.c),
                                                               "buyer": {**S.seller_of(nine), "nip": nine.nip},
                                                               "lines": lines, "totals": A.totals(lines),
                                                               "payment": {"due_date": "2049-06-15"}}))
    n = "8513262910-20490601-0123456789AB-11"
    meta = _meta(n, "01/06/2049", xml, seven.c.nip, nine.nip, day="2049-06-01")
    Y.sync(db, seven.c.id, sides=("sales",), since="2049-06-01",
           client_factory=FakeKsef(sales=[meta], purchases=[], xmls={n: xml}))
    Y.sync(db, nine.id, sides=("purchase",), since="2049-06-01",
           client_factory=FakeKsef(sales=[], purchases=[meta], xmls={n: xml}))
    rows = db.query(M.KsefInvoice).filter_by(ksef_number=n).all()
    assert sorted((r.company_id, r.side) for r in rows) == sorted([(seven.c.id, "sales"), (nine.id, "purchase")])


def test_a_gross_priced_row_and_a_fine_unit_price_read_back():
    xml = (b'<?xml version="1.0" encoding="UTF-8"?><Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">'
           b'<Podmiot1><DaneIdentyfikacyjne><NIP>5213545223</NIP><Nazwa>S</Nazwa></DaneIdentyfikacyjne></Podmiot1>'
           b'<Podmiot2><DaneIdentyfikacyjne><NIP>8513262910</NIP><Nazwa>B</Nazwa></DaneIdentyfikacyjne></Podmiot2>'
           b'<Fa><KodWaluty>PLN</KodWaluty><P_1>2049-06-02</P_1><P_2>FV 1</P_2><P_13_1>112.50</P_13_1>'
           b'<P_14_1>25.88</P_14_1><P_15>138.38</P_15><RodzajFaktury>VAT</RodzajFaktury>'
           b'<FaWiersz><NrWierszaFa>1</NrWierszaFa><P_7>Brutto</P_7><P_8B>2</P_8B><P_9B>61.50</P_9B>'
           b'<P_11A>123.00</P_11A><P_12>23</P_12></FaWiersz>'
           b'<FaWiersz><NrWierszaFa>2</NrWierszaFa><P_7>Drobne</P_7><P_8B>1000</P_8B><P_9A>0.0125</P_9A>'
           b'<P_11>12.50</P_11><P_12>23</P_12></FaWiersz></Fa></Faktura>')
    a, b = parse(xml)["body"]["lines"]
    assert (a["net"], a["vat"], a["gross"], a["unit_net"]) == ("100.00", "23.00", "123.00", "50.00")
    assert (b["net"], b["unit_net"]) == ("12.50", "0.0125")


def test_a_purchase_entered_by_hand_is_not_doubled(db, seven, store):
    hand = M.RunCostDocument(doc_type="invoice", supplier="Dostawca", doc_number="FV 07/2049", doc_date="2049-03-12",
                             currency="PLN", company_id=seven.c.id, total_amount=100.0)
    db.add(hand)
    db.flush()
    xml = _purchase_xml(seven, "FV 7/2049", "2049-03-12")
    n = "5213545223-20490312-0123456789AB-07"
    Y.sync(db, seven.c.id, sides=("purchase",), since="2049-03-01",
           client_factory=FakeKsef(sales=[], purchases=[_meta(n, "FV 7/2049", xml, "5213545223", "8513262910",
                                                              day="2049-03-12")], xmls={n: xml}))
    row = db.query(M.KsefInvoice).filter_by(company_id=seven.c.id, ksef_number=n).one()
    with pytest.raises(HTTPException) as e:
        Y.import_purchase(db, row, actor="test")
    assert e.value.status_code == 409 and e.value.detail["candidates"][0]["id"] == hand.id
    assert row.status == "new"
    Y.import_purchase(db, row, actor="test", link_to=hand.id)
    assert (row.status, row.document_id, hand.seller_tax_id) == ("imported", hand.id, "5213545223")


def test_the_link_is_kept_when_the_import_answers_409(db, seven, monkeypatch):
    from app.routers import ksef as R

    n = "5213545223-20490313-0123456789AB-09"
    doc = M.RunCostDocument(doc_type="invoice", supplier="X", doc_number="FV 9/2049", external_id=n,
                            doc_date="2049-03-13", currency="PLN", company_id=seven.c.id)
    row = M.KsefInvoice(company_id=seven.c.id, side="purchase", ksef_number=n, invoice_number="FV 9/2049",
                        seller_nip="5213545223", issue_date="2049-03-13", status="new")
    db.add_all([doc, row])
    db.flush()
    commits = []
    monkeypatch.setattr(db, "commit", lambda: commits.append(1))
    with pytest.raises(HTTPException) as e:
        R.import_purchase(row.id, db=db)
    assert e.value.status_code == 409 and commits      # the link is committed, not rolled back
    assert (row.status, row.document_id) == ("imported", doc.id)


def test_a_ksef_error_keeps_what_was_fetched_and_the_error(db, seven, store, monkeypatch):
    from app.routers import ksef as R

    xml = _purchase_xml(seven, "FV 11/2049", "2049-07-02")
    n = "8513262910-20490702-0123456789AB-41"

    class Broken(FakeKsef):
        def metadata(self, side, start, end):
            if side == "purchase":
                raise K.KsefError("KSeF HTTP 500")
            return self.sales

    fake = Broken(sales=[_meta(n, "05/07/2049", xml, "8513262910", "5213545223", day="2049-07-02")],
                  purchases=[], xmls={n: xml})
    real = Y.sync
    monkeypatch.setattr(R.svc, "sync", lambda db_, cid, **kw: real(db_, cid, client_factory=fake, **kw))
    commits = []
    monkeypatch.setattr(db, "commit", lambda: commits.append(1))
    with pytest.raises(HTTPException) as e:
        R.run_sync(R.SyncIn(company_id=seven.c.id, since="2049-07-01"), db=db, admin=None)
    assert e.value.status_code == 502 and commits
    assert Y.credential(db, seven.c.id).last_error == "KSeF HTTP 500"
    assert db.query(M.KsefInvoice).filter_by(company_id=seven.c.id, ksef_number=n).one()


def test_a_sales_invoice_is_never_skipped(db, seven):
    from app.routers import ksef as R

    row = M.KsefInvoice(company_id=seven.c.id, side="sales", ksef_number="8513262910-20490801-0123456789AB-21",
                        invoice_number="01/08/2049", invoice_type="Vat", status="new")
    db.add(row)
    db.flush()
    with pytest.raises(HTTPException) as e:
        R.skip(row.id, R.SkipIn(reason="nie nasza"), db=db)
    assert e.value.status_code == 422 and row.status == "new"


def test_a_purchase_whose_document_was_deleted_imports_again(db, seven, store):
    from app.routers import run_costs as RC

    xml = _purchase_xml(seven, "FV 12/2049", "2049-08-02")
    n = "5213545223-20490802-0123456789AB-51"
    Y.sync(db, seven.c.id, sides=("purchase",), since="2049-08-01",
           client_factory=FakeKsef(sales=[], purchases=[_meta(n, "FV 12/2049", xml, "5213545223", "8513262910",
                                                              day="2049-08-02")], xmls={n: xml}))
    row = db.query(M.KsefInvoice).filter_by(company_id=seven.c.id, ksef_number=n).one()
    doc = Y.import_purchase(db, row, actor="test")
    RC.delete_document(doc.id, force=True, db=db)
    db.refresh(row)
    assert (row.status, row.document_id) == ("new", None)
    again = Y.import_purchase(db, row, actor="test")
    # A row an older delete left behind heals on the next import too.
    db.delete(again)
    db.flush()
    assert Y.import_purchase(db, row, actor="test").id not in (doc.id, again.id)


def test_the_sync_reads_back_long_enough_for_late_invoices(db, seven):
    seen = {}

    class Spy(FakeKsef):
        def metadata(self, side, start, end):
            seen[side] = start
            return []

    Y.credential(db, seven.c.id).sales_read_to = "2049-05-31"
    Y.sync(db, seven.c.id, sides=("sales",), client_factory=Spy([], [], {}))
    assert seen["sales"] <= date(2049, 5, 1)


def test_a_zero_quantity_stays_zero():
    """P_8B=0 is a real zero (a correction's after-row that removes a position),
    never the quantity one that a MISSING P_8B means."""
    def doc(kind, rows):
        return (b'<?xml version="1.0" encoding="UTF-8"?><Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">'
                b'<Podmiot1><DaneIdentyfikacyjne><NIP>5213545223</NIP><Nazwa>S</Nazwa></DaneIdentyfikacyjne>'
                b'</Podmiot1><Podmiot2><DaneIdentyfikacyjne><NIP>8513262910</NIP><Nazwa>B</Nazwa>'
                b'</DaneIdentyfikacyjne></Podmiot2><Fa><KodWaluty>PLN</KodWaluty><P_1>2049-06-02</P_1>'
                b'<P_2>FV 2</P_2><P_13_1>0</P_13_1><P_14_1>0</P_14_1><P_15>0</P_15><RodzajFaktury>'
                + kind + b'</RodzajFaktury>' + rows + b'</Fa></Faktura>')

    vat = parse(doc(b"VAT", b'<FaWiersz><NrWierszaFa>1</NrWierszaFa><P_7>A</P_7><P_8B>0</P_8B>'
                            b'<P_9A>100</P_9A><P_12>23</P_12></FaWiersz>'))
    (a,) = vat["body"]["lines"]
    assert (a["qty"], a["net"]) == ("0", "0.00")
    kor = parse(doc(b"KOR", b'<FaWiersz><NrWierszaFa>1</NrWierszaFa><P_7>A</P_7><P_8B>5</P_8B><P_9A>100</P_9A>'
                            b'<P_11>500.00</P_11><P_12>23</P_12><StanPrzed>1</StanPrzed></FaWiersz>'
                            b'<FaWiersz><NrWierszaFa>2</NrWierszaFa><P_7>A</P_7><P_8B>0.000</P_8B>'
                            b'<P_9A>100</P_9A><P_12>23</P_12></FaWiersz>'))
    (after,) = kor["body"]["lines"]
    assert (after["qty"], after["net"]) == ("0", "0.00")
    missing = parse(doc(b"VAT", b'<FaWiersz><NrWierszaFa>1</NrWierszaFa><P_7>A</P_7><P_9A>100</P_9A>'
                                b'<P_12>23</P_12></FaWiersz>'))
    assert missing["body"]["lines"][0]["qty"] == "1"


# --- decision 0084: a supplier document keeps the invoice's tax data -----------

def test_a_foreign_currency_invoice_keeps_its_vat_in_pln():
    xml = (b'<?xml version="1.0" encoding="UTF-8"?><Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">'
           b'<Podmiot1><DaneIdentyfikacyjne><NIP>5213545223</NIP><Nazwa>S</Nazwa></DaneIdentyfikacyjne></Podmiot1>'
           b'<Podmiot2><DaneIdentyfikacyjne><NIP>8513262910</NIP><Nazwa>B</Nazwa></DaneIdentyfikacyjne></Podmiot2>'
           b'<Fa><KodWaluty>EUR</KodWaluty><P_1>2049-06-02</P_1><P_2>FV 3</P_2><P_13_1>100.00</P_13_1>'
           b'<P_14_1>23.00</P_14_1><P_14_1W>98.21</P_14_1W><P_15>123.00</P_15><RodzajFaktury>VAT</RodzajFaktury>'
           b'<FaWiersz><NrWierszaFa>1</NrWierszaFa><P_7>U</P_7><P_8B>1</P_8B><P_9A>100</P_9A>'
           b'<P_11>100.00</P_11><P_12>23</P_12></FaWiersz></Fa></Faktura>')
    t = parse(xml)["body"]["totals"]
    assert (t["vat"], t["vat_pln"], t["rates"]["23"]["vat_pln"]) == ("23.00", "98.21", "98.21")
    # A PLN invoice states no P_14_xW and gets no vat_pln.
    assert "vat_pln" not in parse(xml.replace(b"<P_14_1W>98.21</P_14_1W>", b""))["body"]["totals"]


def test_the_receipt_day_is_the_polish_day_ksef_numbered_it():
    assert Y.received_day("2049-03-31T23:30:00Z") == "2049-04-01"          # CEST, UTC+2
    assert Y.received_day("2049-03-10T10:00:00.1234567+00:00") == "2049-03-10"
    assert Y.received_day("2049-03-10") == "2049-03-10" and Y.received_day("") == ""


def test_an_import_keeps_the_invoice_s_tax_data(db, seven, store):
    xml = _purchase_xml(seven, "FV 21/2049", "2049-09-02")
    n = "5213545223-20490902-0123456789AB-61"
    meta = {**_meta(n, "FV 21/2049", xml, "5213545223", "8513262910", day="2049-09-02"),
            "acquisitionDate": "2049-09-04T22:15:00Z"}
    Y.sync(db, seven.c.id, sides=("purchase",), since="2049-09-01",
           client_factory=FakeKsef(sales=[], purchases=[meta], xmls={n: xml}))
    row = db.query(M.KsefInvoice).filter_by(company_id=seven.c.id, ksef_number=n).one()
    doc = Y.import_purchase(db, row, actor="test")
    assert (doc.sale_date, doc.due_date, doc.received_date) == ("2049-09-02", "2049-09-02", "2049-09-05")
    assert doc.tax_amount == pytest.approx(23.0) and doc.tax_amount_pln is None    # a PLN invoice
    assert doc.body["seller"]["nip"] == "5213545223" and doc.body["lines"][0]["vat_rate"] == "23"
    # The documents imported before the change are filled by the job, once.
    doc.sale_date, doc.received_date, doc.body = "", "", None
    db.flush()
    res = Y.fill_documents(db)
    assert {"document_id": doc.id, "ksef_number": n, "fields": ["body", "sale_date", "received_date"]} \
        in res["filled"]
    assert doc.received_date == "2049-09-05"
    assert not any(f["document_id"] == doc.id for f in Y.fill_documents(db)["filled"])


def test_a_hand_typed_document_learns_the_tax_data_when_it_is_linked(db, seven, store):
    hand = M.RunCostDocument(doc_type="invoice", supplier="Dostawca", doc_number="FV 22/2049", doc_date="2049-09-12",
                             currency="PLN", company_id=seven.c.id, total_amount=100.0)
    db.add(hand)
    db.flush()
    xml = _purchase_xml(seven, "FV 22/2049", "2049-09-12")
    n = "5213545223-20490912-0123456789AB-62"
    Y.sync(db, seven.c.id, sides=("purchase",), since="2049-09-01",
           client_factory=FakeKsef(sales=[], purchases=[_meta(n, "FV 22/2049", xml, "5213545223", "8513262910",
                                                              day="2049-09-12")], xmls={n: xml}))
    row = db.query(M.KsefInvoice).filter_by(company_id=seven.c.id, ksef_number=n).one()
    Y.import_purchase(db, row, actor="test", link_to=hand.id)
    assert hand.tax_amount == pytest.approx(23.0) and hand.received_date == "2049-09-12"
    assert hand.total_amount == pytest.approx(100.0) and hand.body["totals"]["gross"] == "123.00"
