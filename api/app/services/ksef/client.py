"""KSeF API 2.0, read only (decision 0067). Ported from `class KSeF` in
7Sigma's script, which read 7Sigma's invoices with it from 2026-02.

Authentication with a KSeF token: the token and a challenge timestamp are
encrypted with the Ministry's `KsefTokenEncryption` public key (RSA-OAEP,
SHA-256), exchanged for an authentication token, polled until accepted, and
redeemed for an access token.

Limits, as the script met them: about 8 requests per second (a short 429 that
is worth waiting out), 20 metadata queries an hour and a per-minute limit on
XML downloads. A long wait is never slept through: `RateLimited` says how long,
and the next sync carries on.
"""
from __future__ import annotations

import base64
import time
from datetime import UTC, date, datetime, timedelta

import httpx

BASE_URL = "https://api.ksef.mf.gov.pl/v2"
#: KSeF 2.0 went live in February 2026; the first sync reads from here.
KSEF2_START = date(2026, 2, 1)


class KsefError(RuntimeError):
    pass


class RateLimited(KsefError):
    def __init__(self, path: str, seconds: int):
        super().__init__(f"KSeF limit reached on {path}; try again in {seconds // 60} min {seconds % 60} s")
        self.seconds = seconds


class Client:
    """One company's session. `token` is the decrypted KSeF token; hold the
    client only for one sync."""

    def __init__(self, token: str, nip: str, base_url: str = BASE_URL,
                 transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self._token = token
        self.nip = nip
        self._http = httpx.Client(base_url=base_url, timeout=60, transport=transport)
        self._access: str | None = None
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, *, body: dict | None = None, token: str | None = None,
              accept: str = "application/json", params: dict | None = None):
        headers = {"Accept": accept, "X-Error-Format": "problem-details"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        for attempt in range(5):
            try:
                r = self._http.request(method, path, json=body, headers=headers, params=params)
            except httpx.HTTPError as e:
                # Unreachable, timed out, reset: a KSeF error, so the sync keeps
                # what it already read and records why it stopped.
                raise KsefError(f"KSeF unreachable on {method} {path}: {e}") from e
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After") or 2)
                short = 10 if "/query/" in path else 120
                if wait <= short and attempt < 4:
                    self._sleep(wait)
                    continue
                raise RateLimited(path, wait)
            if r.status_code >= 400:
                raise KsefError(f"KSeF HTTP {r.status_code} {method} {path}: {r.text[:300]}")
            if accept == "application/json":
                return r.json() if r.content else {}
            return r.content
        raise KsefError(f"KSeF: {path} kept answering 429")

    def authenticate(self) -> str:
        if self._access:
            return self._access
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        now = datetime.now(UTC)
        certs = self._call("GET", "/security/public-key-certificates")
        cert = next((c for c in certs if "KsefTokenEncryption" in c.get("usage", [])
                     and datetime.fromisoformat(c["validFrom"]) <= now <= datetime.fromisoformat(c["validTo"])),
                    None)
        if cert is None:
            raise KsefError("KSeF published no valid KsefTokenEncryption certificate")
        key = x509.load_der_x509_certificate(base64.b64decode(cert["certificate"])).public_key()
        ch = self._call("POST", "/auth/challenge")
        secret = key.encrypt(f"{self._token}|{ch['timestampMs']}".encode(),
                             padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        init = self._call("POST", "/auth/ksef-token", body={
            "challenge": ch["challenge"], "contextIdentifier": {"type": "Nip", "value": self.nip},
            "encryptedToken": base64.b64encode(secret).decode()})
        auth, ref = init["authenticationToken"]["token"], init["referenceNumber"]
        for _ in range(30):
            st = self._call("GET", f"/auth/{ref}", token=auth)["status"]
            if st["code"] == 200:
                break
            if st["code"] >= 400:
                raise KsefError(f"KSeF refused the token: {st}")
            self._sleep(1)
        else:
            raise KsefError("KSeF did not finish the authentication")
        self._access = self._call("POST", "/auth/token/redeem", token=auth)["accessToken"]["token"]
        return self._access

    def metadata(self, subject: str, start: date, end: date) -> list[dict]:
        """Invoice metadata by issue date. `subject`: "sales" (the company is the
        seller, Subject1) or "purchase" (the buyer, Subject2). One query covers
        at most 90 days, as the API allows."""
        subj = {"sales": "Subject1", "purchase": "Subject2"}[subject]
        out: list[dict] = []
        cur = start
        while cur <= end:
            stop = min(cur + timedelta(days=89), end)
            body = {"subjectType": subj, "dateRange": {"dateType": "Issue",
                                                       "from": f"{cur}T00:00:00+02:00",
                                                       "to": f"{stop}T23:59:59+02:00"}}
            page = 0
            while True:
                r = self._call("POST", "/invoices/query/metadata", body=body, token=self.authenticate(),
                               params={"sortOrder": "Asc", "pageOffset": page, "pageSize": 250})
                out += r.get("invoices") or []
                if not r.get("hasMore"):
                    break
                if r.get("isTruncated"):
                    raise KsefError("KSeF truncated the result at 10 000 invoices; narrow the dates")
                page += 1
            cur = stop + timedelta(days=1)
        return out

    def xml(self, ksef_number: str) -> bytes:
        return self._call("GET", f"/invoices/ksef/{ksef_number}", token=self.authenticate(),
                          accept="application/xml")
