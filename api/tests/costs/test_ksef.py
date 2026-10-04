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
