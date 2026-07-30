"""JLCPCB **web** API client — browser-session auth, for the data the official
OpenAPI does not expose.

Why this exists alongside `jlc.py`: the official JOP-signed partner API
(`open.jlcpcb.com`) has NO PCBA surface at all. Its complete published surface
is 20 endpoints — 4 `component/`, 9 `pcb/`, 7 `tdp/` — and every "SMT" token in
it means *SMD stencil*, not assembly (`pcb/calculate` accepts orderType 1/2/3 =
PCB / PCB+stencil / stencil only, so an assembly order cannot even be placed
through it). There is likewise no stock-movement endpoint at any permission
level: `getPrivateComponentLibrary` returns point-in-time balances, never a
ledger. Verified 2026-07-28 against three independent reconstructions of the
official docs.

So per-SMT-order component consumption is reachable only through the same web
API the user-center SPA calls, authenticated with browser session cookies. The
key endpoint is the manufacturing invoice:

    POST /api/overseas-core-platform/orderCenter/invoiceOrder
         {"batchNum": "W...", "orderPay": "yes"}
    -> presaleDetailResultVOList[]:
         {componentCode, smtOrderCode, orderBatchNo,
          componentNum, settleGoodsPrice, componentMoney}

That single list IS the component -> assembly-order -> invoice join: which LCSC
part, how many, for which SMT order, at what price. It is billed consumption,
which is what the cost pool wants — the platform otherwise has to infer draws
from the BOM.

**Auth is three-legged** and all three legs are required on every call:
  1. session cookies from a real browser login (`JLCPCB_SESSION_ID` is
     httpOnly, so `document.cookie` cannot produce them — they must come from
     DevTools / a cookie export),
  2. `x-xsrf-token`: the URL-DECODED value of the `XSRF-TOKEN` cookie,
  3. `secretkey`: minted from `/api/overseas-core-platform/secret/update` with
     a random uuid4 hex `keyId`, **30-minute TTL**.

Failure modes are distinct and must not be conflated: HTTP **460** = the
session cookies are dead (a human must log in again); `success:false` with
code 401/403 = only the secret key went stale, so re-mint and retry once. The
retry is automatic; the re-login is not, and is surfaced to the user.

This is an UNDOCUMENTED, UNVERSIONED API that can change without notice — treat
every response as untrusted shape and keep the raw payload. The endpoint map
was taken from the MIT-licensed https://github.com/hatlabs/jlcpcb-cli, adapted
to this codebase's httpx + settings + encrypted-credential conventions.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from .. import models as M
from .crypto import decrypt_token, encrypt_token

log = logging.getLogger(__name__)

BASE_URL = "https://jlcpcb.com"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Secret key TTL is 30 min server-side; refresh early so a slow call can't
# straddle the boundary.
_SECRET_TTL_SEC = 25 * 60

# Any path under the overseas-pcb-order service issues an XSRF-TOKEN via its
# CSRF filter; a non-existent one is chosen so the bootstrap cannot have side
# effects (the filter runs before routing, so the 404 still sets the cookie).
_XSRF_BOOTSTRAP_URL = "/api/overseas-pcb-order/v1/csrf-bootstrap"

# --- endpoints -------------------------------------------------------------
SECRET_UPDATE_PATH = "/overseas-core-platform/secret/update"
ORDER_BATCH_LIST_PATH = "/overseas-core-platform/orderCenter/selectPersonBatch"
ORDER_DETAIL_PATH = "/overseas-core-platform/orderCenter/selectPersonOrderDetail"
# The order-centre view — the only source of panelisation (panelX x panelY).
ORDER_PERSON_URI = "/overseas-core-platform/orderCenter/selectPersonOrder"
# JLC's OWN BOM for an assembly order — the only source of `componentSource`,
# i.e. who supplied each part. Keyed by the order's UUID, not its SMT code.
SMT_ORDER_DETAIL_PATH = "/overseas-pcb-order/v1/smtOrder/getSmtOrderDetail"
MFG_INVOICE_PATH = "/overseas-core-platform/orderCenter/invoiceOrder"
BILLING_LIST_PATH = "/overseas-pcb-order/v1/billing/queryBillingBatchNumList"
BILLING_DETAIL_PATH = "/overseas-pcb-order/v1/billing/queryBillingDetail"
_SMT_BASE = "/overseas-smt-component-order-platform/v1/overseasSmtComponentOrder"
PARTS_ORDER_LIST_PATH = f"{_SMT_BASE}/presaleOrder/selectPresaleOrderList"
PARTS_INVOICE_PATH = f"{_SMT_BASE}/presaleOrder/getInvoiceInfo"
CUSTOMER_STOCK_PATH = f"{_SMT_BASE}/myLibrary/getCustomerComponentStock"


class JlcWebError(RuntimeError):
    """Any failure talking to the JLCPCB web API."""


class JlcSessionExpired(JlcWebError):
    """Session cookies are dead — a human must log in again (HTTP 460)."""


class _StaleSecretKey(JlcWebError):
    """Secret key aged out mid-flight; re-mint and retry (internal only)."""


# --------------------------------------------------------------- credentials
def _parse_cookie_blob(blob: str) -> dict[str, str]:
    """Accept either a raw `Cookie:` header string or a Playwright/DevTools
    cookie-JSON array, so the user can paste whatever their browser gives them.

    A cURL copy yields `a=1; b=2`; a cookie-export extension yields
    `[{"name": "a", "value": "1"}, ...]`. Both are common; neither is
    obviously "the" format, so support both rather than making the user
    convert by hand.
    """
    blob = (blob or "").strip()
    if not blob:
        return {}
    if blob.startswith("["):
        try:
            rows = json.loads(blob)
        except json.JSONDecodeError as e:
            raise JlcWebError(f"cookie JSON is not valid JSON: {e}") from e
        out = {}
        for row in rows:
            name = str(row.get("name") or "").strip()
            if name:
                out[name] = str(row.get("value") or "")
        return out
    # Raw header form. Strip a leading "Cookie:" if the user pasted the header
    # line verbatim.
    if blob.lower().startswith("cookie:"):
        blob = blob.split(":", 1)[1].strip()
    out = {}
    for part in blob.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def get_session_cookies(db: Session) -> dict[str, str]:
    """Decrypted cookie jar from the stored session row, or {} if unset."""
    row = db.get(M.JlcWebSession, 1)
    if row is None or not row.cookies_enc:
        return {}
    return _parse_cookie_blob(decrypt_token(row.cookies_enc))


def set_session_cookies(db: Session, blob: str, label: str = "") -> dict:
    """Store (encrypted) a pasted cookie blob. Returns a summary that NEVER
    contains cookie values — the caller shapes an HTTP response from it."""
    jar = _parse_cookie_blob(blob)
    # Only the session cookie is genuinely required. XSRF-TOKEN carries
    # Max-Age=1800, so a copied session very often arrives without one — the
    # client re-bootstraps it on demand (see WebClient._xsrf_token).
    if "JLCPCB_SESSION_ID" not in jar:
        raise JlcWebError(
            "cookie blob is missing JLCPCB_SESSION_ID — copy the full Cookie header from an "
            "authenticated jlcpcb.com request (DevTools > Network > Copy as cURL); "
            "it is httpOnly so document.cookie will not include it"
        )
    row = db.get(M.JlcWebSession, 1)
    if row is None:
        row = M.JlcWebSession(id=1)
        db.add(row)
    row.cookies_enc = encrypt_token(blob)
    row.label = label[:200]
    row.updated_at = M.utcnow()
    row.last_ok_at = None
    db.commit()
    _invalidate_client()
    return {"cookie_names": sorted(jar.keys()), "updated_at": row.updated_at.isoformat()}


def clear_session(db: Session) -> None:
    row = db.get(M.JlcWebSession, 1)
    if row is not None:
        row.cookies_enc = None
        row.last_ok_at = None
        db.commit()
    _invalidate_client()


def session_status(db: Session) -> dict:
    """Whether a session is configured — never exposes the cookies."""
    row = db.get(M.JlcWebSession, 1)
    if row is None:
        return {"configured": False, "label": "", "updated_at": None,
                "last_ok_at": None, "died_at": None, "last_error": "",
                "keepalive_count": 0, "age_hours": None, "alive": False}
    now = datetime.now(timezone.utc)
    # Presence, liveness and death are three separate facts. Collapsing them is
    # how "Sync from JLCPCB" came to fail with a bare error banner: the UI knew a
    # session was configured and had no way to know it had stopped working.
    return {
        "configured": bool(row.cookies_enc),
        "label": row.label or "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "last_ok_at": row.last_ok_at.isoformat() if row.last_ok_at else None,
        "died_at": row.died_at.isoformat() if row.died_at else None,
        "last_error": row.last_error or "",
        "keepalive_count": row.keepalive_count or 0,
        "age_hours": (round((now - row.updated_at).total_seconds() / 3600, 2)
                      if row.updated_at else None),
        # Best guess without spending a round trip: it worked and has not been
        # seen dead since. `check_session` is the authority.
        "alive": bool(row.cookies_enc and row.last_ok_at
                      and (row.died_at is None or row.died_at < row.last_ok_at)),
    }


# ----------------------------------------------------------------- keep-alive
_keepalive_timer = None


def keepalive_tick(interval_s: float) -> None:
    """Touch the session so an IDLE timeout cannot kill it, and record the moment
    it dies if it does.

    Worth doing for two independent reasons, and the second holds even if the
    first turns out to be false:

    1. **It may remove the problem entirely.** If JLC expires a session on
       inactivity, a request every 20 minutes keeps it alive indefinitely and the
       cookies never need re-pasting.
    2. **It measures what nothing else can.** The session's true lifetime is
       unknown — `secretkey` (25 min) and `XSRF-TOKEN` (`Max-Age=1800`) are the
       short-lived things, and this client already renews both by itself. With a
       tick running, `died_at - updated_at` is the actual answer, so the choice
       between a browser extension and a headless login stops being a guess.

    It also means a dead session is discovered BEFORE an import is attempted
    rather than halfway through one.
    """
    from ..db import SessionLocal

    global _keepalive_timer
    try:
        db = SessionLocal()
        try:
            row = db.get(M.JlcWebSession, 1)
            if row is not None and row.cookies_enc:
                res = check_session(db)
                row = db.get(M.JlcWebSession, 1)
                if res.get("ok"):
                    row.keepalive_count = (row.keepalive_count or 0) + 1
                    row.died_at = None
                    row.last_error = ""
                elif res.get("expired"):
                    # First observation only: overwriting it on every later tick
                    # would lose the lifetime this exists to measure.
                    if row.died_at is None:
                        row.died_at = datetime.now(timezone.utc)
                        age = ((row.died_at - row.updated_at).total_seconds() / 3600
                               if row.updated_at else None)
                        log.warning(
                            f"JLCPCB session died after "
                            f"{round(age, 2) if age else '?'}h and "
                            f"{row.keepalive_count or 0} keep-alive touches — "
                            "a human must paste fresh cookies")
                    row.last_error = (res.get("error") or "expired")[:300]
                else:
                    # A transport error is not a death. Recording it as one would
                    # tell the user to re-log-in over a blip of network trouble.
                    row.last_error = (res.get("error") or "")[:300]
                db.commit()
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001 — a keep-alive must never take the app down
        log.warning(f"JLCPCB session keep-alive failed: {e}")
    finally:
        _keepalive_timer = threading.Timer(interval_s, lambda: keepalive_tick(interval_s))
        _keepalive_timer.daemon = True
        _keepalive_timer.start()


def start_keepalive(interval_min: float) -> None:
    """Begin touching the stored session every `interval_min` minutes. 0 = off."""
    if interval_min <= 0:
        return

    global _keepalive_timer
    if _keepalive_timer is not None:
        return
    interval_s = interval_min * 60
    # First touch shortly after boot, not immediately: startup is already busy
    # building PCM packages and refreshing ladders.
    _keepalive_timer = threading.Timer(45.0, lambda: keepalive_tick(interval_s))
    _keepalive_timer.daemon = True
    _keepalive_timer.start()
    log.info(f"JLCPCB session keep-alive every {interval_min} min")


# ------------------------------------------------------------------- client
class WebClient:
    """One authenticated conversation with jlcpcb.com.

    Holds the minted secret key so a batch of calls costs one mint, not one
    per call. Not thread-safe by itself; `_get_client` hands out a process
    singleton guarded by `_CLIENT_LOCK`.
    """

    def __init__(self, cookies: dict[str, str]):
        self._cookies = cookies
        self._secret_key: str | None = None
        self._secret_minted_at = 0.0

    # -- auth legs
    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    def _bootstrap_xsrf(self) -> str:
        """Mint an XSRF-TOKEN by asking jlcpcb.com for one.

        This is the standard double-submit-cookie pattern: the server issues a
        token as a cookie and expects it echoed back in a header, comparing the
        two. So any token the server itself just issued is valid — we do not
        need the one the browser happened to hold. That matters because the
        cookie carries `Max-Age=1800`, meaning a session pasted from a tab that
        has been open a while almost never includes a live one.

        The session cookie is sent along so the token is minted in the context
        of the logged-in session rather than an anonymous one.

        Which URL matters: only the `overseas-pcb-order` service runs the CSRF
        filter that issues the cookie. The site root, `overseas-core-platform`
        and the SMT service all return 200 without one (verified 2026-07-28).
        A deliberately non-existent path under that prefix is used because the
        filter runs BEFORE routing — the 404 still sets the cookie — which
        makes this side-effect-free: no real endpoint is invoked.
        """
        try:
            resp = httpx.get(
                f"{BASE_URL}{_XSRF_BOOTSTRAP_URL}",
                headers={"Cookie": self._cookie_header(), "User-Agent": _USER_AGENT},
                timeout=30,
            )
        except httpx.HTTPError as e:
            raise JlcWebError(f"could not bootstrap XSRF token: {e}") from e
        token = resp.cookies.get("XSRF-TOKEN")
        if not token:
            raise JlcWebError(
                f"jlcpcb.com issued no XSRF-TOKEN from {_XSRF_BOOTSTRAP_URL} "
                f"(HTTP {resp.status_code}) — their CSRF filter may have moved"
            )
        self._cookies["XSRF-TOKEN"] = token
        return urllib.parse.unquote(token)

    def _xsrf_token(self) -> str:
        raw = self._cookies.get("XSRF-TOKEN")
        if not raw:
            return self._bootstrap_xsrf()
        # The cookie is URL-encoded; the header wants it decoded.
        return urllib.parse.unquote(raw)

    def _mint_secret_key(self) -> str:
        body = self._request(
            SECRET_UPDATE_PATH,
            method="POST",
            payload={"keyId": uuid.uuid4().hex},
            headers={"x-xsrf-token": self._xsrf_token()},
        )
        key = (body.get("data") or {}).get("keyId")
        if not key:
            raise JlcWebError(f"could not mint secret key: {json.dumps(body)[:200]}")
        self._secret_key = key
        self._secret_minted_at = time.time()
        return key

    def _ensure_secret_key(self) -> None:
        if self._secret_key is None or (time.time() - self._secret_minted_at) > _SECRET_TTL_SEC:
            self._mint_secret_key()

    def _auth_headers(self) -> dict[str, str]:
        return {"x-xsrf-token": self._xsrf_token(), "secretkey": self._secret_key or ""}

    # -- transport
    def _request(self, path: str, *, method: str, payload: dict | None = None,
                 params: dict | None = None, headers: dict[str, str] | None = None) -> dict:
        url = f"{BASE_URL}/api{path}"
        hdrs = {"Cookie": self._cookie_header(), "User-Agent": _USER_AGENT}
        if payload is not None:
            hdrs["Content-Type"] = "application/json"
        if headers:
            hdrs.update(headers)
        try:
            resp = httpx.request(
                method,
                url,
                content=json.dumps(payload).encode() if payload is not None else None,
                params=params,
                headers=hdrs,
                timeout=45,
            )
        except httpx.HTTPError as e:
            raise JlcWebError(f"JLC web request failed: {e}") from e
        # 460 is JLCPCB's own "your login is gone" code, not a standard status.
        if resp.status_code == 460:
            raise JlcSessionExpired("JLCPCB session expired (HTTP 460) — re-paste browser cookies")
        if resp.status_code != 200:
            raise JlcWebError(f"JLC web HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as e:
            raise JlcWebError(f"JLC web returned non-JSON: {resp.text[:200]}") from e

    def _check_stale(self, result: dict) -> None:
        if not result.get("success") and result.get("code") in (401, 403, "401", "403"):
            raise _StaleSecretKey(f"secret key rejected (code={result.get('code')})")

    @staticmethod
    def _check_success(result: dict) -> None:
        if "success" in result and not result["success"]:
            code = result.get("code", "?")
            msg = result.get("message") or result.get("msg") or "unknown error"
            raise JlcWebError(f"JLC web API error (code={code}): {msg}")

    def _call(self, path: str, *, method: str, payload: dict | None = None,
              params: dict | None = None) -> dict:
        self._ensure_secret_key()
        try:
            result = self._request(path, method=method, payload=payload, params=params,
                                   headers=self._auth_headers())
            self._check_stale(result)
        except _StaleSecretKey:
            # One re-mint + retry. A second failure is a real error, not a TTL race.
            self._mint_secret_key()
            result = self._request(path, method=method, payload=payload, params=params,
                                   headers=self._auth_headers())
        self._check_success(result)
        return result

    def post(self, path: str, payload: dict) -> dict:
        return self._call(path, method="POST", payload=payload)

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._call(path, method="GET", params=params)


_CLIENT: WebClient | None = None
_CLIENT_COOKIES: dict[str, str] | None = None
_CLIENT_LOCK = threading.Lock()


def _invalidate_client() -> None:
    global _CLIENT, _CLIENT_COOKIES
    with _CLIENT_LOCK:
        _CLIENT = None
        _CLIENT_COOKIES = None


def _get_client(db: Session) -> WebClient:
    """Process-wide client, rebuilt whenever the stored cookies change.

    In-process and advisory only, like the mirror caches: the cookie jar is
    re-read from the DB on every call and compared, so another worker updating
    the session is picked up without a restart.
    """
    global _CLIENT, _CLIENT_COOKIES
    jar = get_session_cookies(db)
    if not jar:
        raise JlcSessionExpired(
            "no JLCPCB browser session stored — paste cookies in Settings before syncing"
        )
    with _CLIENT_LOCK:
        if _CLIENT is None or _CLIENT_COOKIES != jar:
            _CLIENT = WebClient(jar)
            _CLIENT_COOKIES = dict(jar)
        return _CLIENT


def available(db: Session) -> bool:
    return bool(get_session_cookies(db))


def _mark_ok(db: Session) -> None:
    row = db.get(M.JlcWebSession, 1)
    if row is not None:
        row.last_ok_at = M.utcnow()
        db.commit()


# ---------------------------------------------------------------- endpoints
def list_order_batches(db: Session, *, page: int = 1, page_size: int = 25,
                       status: str = "", search: str = "") -> dict:
    """Order batches (W...) from the order centre. `status` is JLC's own
    vocabulary: shipped | inProduction | cancelled | waitPay | waitReview."""
    client = _get_client(db)
    payload = {
        "businessType": None,
        "orderStatisticsType": None,
        "searchKey": search or None,
        "batchStatus": status or None,
        "fromType": 3,
        "orderBusinessSystemType": "0",
        "timeStamp": int(time.time() * 1000),
        "currentPage": page,
        "pageRows": page_size,
    }
    data = client.post(ORDER_BATCH_LIST_PATH, payload).get("data") or {}
    _mark_ok(db)
    return data


def get_order_detail(db: Session, batch_num: str) -> dict:
    """Per-order detail for a batch. SMT assembly orders are `orderType == 4`
    and carry `detail.smtDetail.smtOrderCode` — the id the invoice's
    consumption rows are keyed by. NOTE: this endpoint names the BOM FILE but
    never its contents; quantities come from the invoice, not here."""
    client = _get_client(db)
    data = client.get(ORDER_DETAIL_PATH, {"batchNum": batch_num}).get("data") or {}
    _mark_ok(db)
    return data


def get_person_order(db: Session, batch_num: str) -> dict:
    """Order-centre view of a batch — the ONLY place JLC states panelisation.

    `unionOrderInfoVOList[].myOrdersRecord.detail`:
      * SMT orders (`orderType == 4`) carry `smtDetail.pasteNumber` (the count JLC
        assembled, in PANELS when panelised) and `smtDetail.produceOrderCode`,
        which names the PCB order they were built from.
      * PCB orders (`orderType == 0`) carry `pcbDetail.panelX` and `panelY`.

    So devices = `pasteNumber x panelX x panelY` of the referenced PCB order —
    authoritative, and available even for orders whose parts are not in the
    library, unlike the BOM-vote derivation. Verified on W2025101700561735: P29
    is 2x2 so SMT025101662104 built 250 x 4 = 1000 devices, while P30 is 1x1 so
    SMT025101662116 built 250. Both agree exactly with the BOM votes.
    """
    client = _get_client(db)
    data = client.post(ORDER_PERSON_URI, {"batchNum": batch_num, "paySuccess": True})
    _mark_ok(db)
    return data.get("data") or {}


def panel_factors(person_order: dict) -> dict[str, dict]:
    """`smtOrderCode` -> {panel_factor, panels, devices, pcb_order}."""
    pcb: dict[str, int] = {}
    smt: dict[str, dict] = {}
    for o in (person_order.get("unionOrderInfoVOList") or []):
        rec = o.get("myOrdersRecord") or {}
        detail = rec.get("detail") or {}
        code = str(o.get("orderCode") or "")
        d_pcb = detail.get("pcbDetail") or {}
        if d_pcb:
            x = int(d_pcb.get("panelX") or 1) or 1
            y = int(d_pcb.get("panelY") or 1) or 1
            pcb[code] = x * y
        d_smt = detail.get("smtDetail") or {}
        if d_smt:
            smt[str(d_smt.get("smtOrderCode") or code)] = {
                "panels": d_smt.get("pasteNumber"),
                "pcb_order": str(d_smt.get("produceOrderCode") or ""),
            }
    out: dict[str, dict] = {}
    for code, info in smt.items():
        k = pcb.get(info["pcb_order"])
        panels = info["panels"]
        out[code] = {
            "panel_factor": k,
            "panels": panels,
            "devices": (panels * k) if (panels and k) else None,
            "pcb_order": info["pcb_order"],
            # `None` means the PCB order was not in this batch — a re-order
            # assembles boards fabricated earlier, so the factor is genuinely
            # unknown here rather than 1.
            "source": "jlc_panelisation" if k else "unknown",
        }
    return out


def order_fee_info(order_detail: dict) -> dict:
    """Per-order fee breakdown from a `selectPersonOrderDetail` payload.

    This endpoint is the ONLY place JLC itemizes what an order's price is made
    of: `recordsDetail.orderCountTolls` on a PCB order (engineering fee,
    panelization, stencil, test, board-spec surcharges), `recordsDetail
    .smtPriceInfo` on an assembly order (setup, stencil, components, extended
    fee, placement, hand soldering, fixture, packaging, services). The invoice
    endpoint prints ONE figure per line and even reallocates money between the
    PCB and assembly lines of one project, so per-fee truth must come from
    here (verified to the cent across all 37 staged batches, 2026-07-30).

    Facts the extractor relies on, all verified on real payloads:
      * `dummyMoney` is the order's own product money; `paiclMoney` =
        dummyMoney + carriageMoney + tariffChargesMoney + an UNITEMIZED extra
        that is real invoiced money on some assembly orders (up to $382.74).
      * An assembly entry names its board via `pcbOrderId`, which equals the
        PCB entry's `produceOrderId`.
      * The raw tolls dicts are kept verbatim — undocumented API, keep the
        evidence (same policy as `JlcImport.payload`).

    Returns {"orders": {<orderCode or SMT code>: {kind: pcb|smt, board,
    dummy, paicl, carriage, tariff, extra, tolls|spi}}}.
    """
    orders: dict[str, dict] = {}
    board_by_produce_id: dict[int, str] = {}
    entries = order_detail.get("unionOrderDetailVOList") or []

    def _money(rd: dict) -> dict:
        dummy = rd.get("dummyMoney") or 0.0
        paicl = rd.get("paiclMoney") or 0.0
        carriage = rd.get("carriageMoney") or 0.0
        tariff = rd.get("tariffChargesMoney") or 0.0
        return {
            "dummy": dummy, "paicl": paicl, "carriage": carriage, "tariff": tariff,
            # The slice of the billed order total no toll key explains. Real
            # money — the invoice's product total only closes with it included.
            "extra": round(paicl - dummy - carriage - tariff, 4),
        }

    for o in entries:
        rd = o.get("recordsDetail") or {}
        dd = rd.get("detail") or {}
        tolls = rd.get("orderCountTolls") or dd.get("orderCountTolls") or {}
        code = str(o.get("orderCode") or rd.get("orderCode") or "").strip()
        if not tolls:
            continue
        pid = rd.get("produceOrderId") or tolls.get("produceOrderId")
        if not code:
            code = f"produce:{pid}"
        if pid:
            board_by_produce_id[int(pid)] = code
        orders[code] = {"kind": "pcb", "board": code, "produce_order_id": pid,
                        **_money(rd), "tolls": tolls}

    for o in entries:
        rd = o.get("recordsDetail") or {}
        dd = rd.get("detail") or {}
        spi = rd.get("smtPriceInfo") or {}
        smt = dd.get("smtDetail") or {}
        if not spi:
            continue
        code = str(smt.get("smtOrderCode") or "").strip()
        if not code:
            continue
        pcb_id = rd.get("pcbOrderId")
        board = (board_by_produce_id.get(int(pcb_id)) if pcb_id else None) or str(
            smt.get("produceOrderCode") or "")
        orders[code] = {"kind": "smt", "board": board,
                        "produce_order_id": rd.get("produceOrderId"),
                        **_money(rd), "spi": spi}
    return {"orders": orders}


def smt_order_nums(person_order: dict) -> dict[str, str]:
    """`smtOrderCode` -> the order's UUID (`myOrdersRecord.orderNum`).

    `getSmtOrderDetail` is keyed by that UUID and returns `code 500` for the
    human-readable SMT code, so this lookup is mandatory.
    """
    out: dict[str, str] = {}
    for o in (person_order.get("unionOrderInfoVOList") or []):
        rec = o.get("myOrdersRecord") or {}
        smt = ((rec.get("detail") or {}).get("smtDetail") or {})
        code = str(smt.get("smtOrderCode") or "")
        num = str(rec.get("orderNum") or rec.get("orderDetailNum") or "")
        if code and num:
            out[code] = num
    return out


def get_smt_order_detail(db: Session, smt_order_num: str) -> dict:
    """JLC's own BOM + fee breakdown for one assembly order.

    `smtBomResult[].componentSource` is the authoritative answer to who supplied
    each part: `preSale` (the customer's consigned library, unitPrice 0 because it
    was paid on the parts order), `shop` (JLC's own stock, and charged), or
    `preSaleAndShop`. Drawing a `shop` part from the pool creates a phantom
    shortage — it never entered the pool.
    """
    client = _get_client(db)
    data = client.get(SMT_ORDER_DETAIL_PATH,
                      {"smtOrderNum": smt_order_num, "_t": int(time.time() * 1000)})
    _mark_ok(db)
    return data.get("data") or {}


def get_manufacturing_invoice(db: Session, batch_num: str) -> dict:
    """THE consumption source. Returns the raw payload; `presaleDetailResultVOList`
    is the per-component / per-SMT-order billed consumption."""
    client = _get_client(db)
    data = client.post(MFG_INVOICE_PATH, {"batchNum": batch_num, "orderPay": "yes"}).get("data") or {}
    _mark_ok(db)
    return data


def list_parts_orders(db: Session, *, page: int = 1, page_size: int = 25,
                      status: str = "", search: str = "") -> dict:
    """Parts PURCHASE orders (POB...) — what was bought into the private
    library, not what assembly consumed. Sub-orders are split across four
    parallel lists by fulfilment type (stockList / buyList / overseasShopList /
    idleOrderList) which must all be read."""
    client = _get_client(db)
    payload = {
        "pageNum": page,
        "pageSize": page_size,
        "orderType": None,
        "keyword": search or "",
        "orderStatus": status or "",
    }
    data = client.post(PARTS_ORDER_LIST_PATH, payload).get("data") or {}
    _mark_ok(db)
    return data


def get_parts_invoice(db: Session, order_batch_no: str) -> dict:
    """Invoice for a parts purchase batch (POB...) — `componentGoodsVOList`."""
    client = _get_client(db)
    payload = {"addressType": "billing", "orderBatchAccessId": "null", "orderBatchNo": order_batch_no}
    data = client.post(PARTS_INVOICE_PATH, payload).get("data") or {}
    _mark_ok(db)
    return data


def get_customer_component_stock(db: Session, *, page: int = 1, page_size: int = 100,
                                 keyword: str = "") -> dict:
    """Private-library stock via the WEB API. Richer than the official
    `getPrivateComponentLibrary` (adds brand / type / description) but still a
    BALANCE, not a ledger — `jlc.sync()` remains the canonical stock path."""
    client = _get_client(db)
    params = {"pageNum": page, "pageSize": page_size, "keyWord": keyword,
              "_t": int(time.time() * 1000)}
    data = client.get(CUSTOMER_STOCK_PATH, params).get("data") or {}
    _mark_ok(db)
    return data


def check_session(db: Session) -> dict:
    """Cheap liveness probe: mint a secret key and read page 1 of the order
    list. Used by the Settings UI to tell 'cookies present' from
    'cookies still work'."""
    try:
        data = list_order_batches(db, page=1, page_size=1)
    except JlcSessionExpired as e:
        return {"ok": False, "expired": True, "error": str(e)}
    except JlcWebError as e:
        return {"ok": False, "expired": False, "error": str(e)}
    return {"ok": True, "expired": False, "batches_visible": int(data.get("total") or 0)}
