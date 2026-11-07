"""JLC announces a dead session two ways, and both have to read as dead.

The second form arrived as HTTP 200 with `code: 460` in the body. It was reported as
a transport error, so `died_at` stayed empty and the status kept saying `alive`.
"""
import pathlib
import re
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.routers import jlc_web as jlc_web_router
from app.services import jlc_web


def _client(monkeypatch, status: int, body: dict) -> jlc_web.WebClient:
    monkeypatch.setattr(
        jlc_web.httpx, "request",
        lambda *a, **k: httpx.Response(status, json=body),
    )
    return jlc_web.WebClient({"JLCPCB_SESSION_ID": "x", "XSRF-TOKEN": "y"})


LOGGED_OUT = {
    "success": False,
    "code": 460,
    "message": "For security reasons, you were automatically logged out of your account.",
}


@pytest.mark.parametrize("status,body", [
    (460, {}),
    (200, LOGGED_OUT),
    (200, {**LOGGED_OUT, "code": "460"}),
    # The parts service: no `success` key, so the old check read it as an empty list.
    (200, {"code": 460, "msg": LOGGED_OUT["message"], "data": None}),
])
def test_both_forms_of_460_are_an_expired_session(monkeypatch, status, body):
    client = _client(monkeypatch, status, body)
    with pytest.raises(jlc_web.JlcSessionExpired):
        client._request("/any", method="POST", payload={})


def test_a_key_mint_recognises_the_session_is_gone(monkeypatch):
    client = _client(monkeypatch, 200, LOGGED_OUT)
    with pytest.raises(jlc_web.JlcSessionExpired):
        client._mint_secret_key()


def test_another_failure_is_not_a_death(monkeypatch):
    client = _client(monkeypatch, 200, {"success": False, "code": 500, "message": "System error"})
    with pytest.raises(jlc_web.JlcWebError) as err:
        client.post("/any", {})
    assert not isinstance(err.value, jlc_web.JlcSessionExpired)


def test_a_dead_jlc_session_never_answers_401():
    """The web client reads any 401 as "your Henry session is gone" and shows the
    sign-in form, so a dead JLC session would sign the user out of Henry."""
    def expired():
        raise jlc_web.JlcSessionExpired("gone")

    with pytest.raises(HTTPException) as err:
        jlc_web_router._run(expired)
    assert err.value.status_code == 409

    routers = pathlib.Path(jlc_web_router.__file__).parent
    for name in ("jlc_web.py", "jlc_stock.py", "jlc_import.py"):
        assert not re.search(r"HTTPException\(\s*401", (routers / name).read_text()), name


def test_cookies_that_cannot_read_the_account_are_refused(monkeypatch):
    monkeypatch.setattr(jlc_web.httpx, "request", lambda *a, **k: httpx.Response(200, json=LOGGED_OUT))
    with pytest.raises(jlc_web.JlcSessionExpired):
        jlc_web.verify_cookies("JLCPCB_SESSION_ID=x; XSRF-TOKEN=y")


def test_verifying_needs_the_session_cookie():
    with pytest.raises(jlc_web.JlcWebError):
        jlc_web.verify_cookies("XSRF-TOKEN=y")


class _OneRow:
    def __init__(self, row):
        self.row = row

    def get(self, *_):
        return self.row

    def add(self, *_):
        pass

    def commit(self):
        pass


def test_a_new_session_starts_clean_and_stores_only_cookies(monkeypatch):
    monkeypatch.setattr(jlc_web, "encrypt_token", lambda blob: f"enc:{blob}")
    row = SimpleNamespace(died_at="yesterday", last_error="code=460", keepalive_count=5859,
                          last_ok_at="yesterday", cookies_enc="old", label="", updated_at=None)
    jlc_web.set_session_cookies(_OneRow(row), CURL_B, "new")
    assert (row.died_at, row.last_error, row.keepalive_count) == (None, "", 0)
    assert row.last_ok_at == row.updated_at
    assert row.cookies_enc == "enc:a=1; JLCPCB_SESSION_ID=abc; c=3"


CURL_B = """curl 'https://jlcpcb.com/user-center/orders/' \\
  -H 'accept: text/html' \\
  -b 'a=1; JLCPCB_SESSION_ID=abc; c=3' \\
  -H 'user-agent: Mozilla/5.0; x=y' \\
  --data-raw 'q=1; z=2'"""


@pytest.mark.parametrize("blob,expected", [
    ("a=1; JLCPCB_SESSION_ID=abc; c=3", {"a": "1", "JLCPCB_SESSION_ID": "abc", "c": "3"}),
    ("Cookie: a=1; JLCPCB_SESSION_ID=abc", {"a": "1", "JLCPCB_SESSION_ID": "abc"}),
    ("accept: */*\ncookie: JLCPCB_SESSION_ID=abc; c=3\nuser-agent: x; y=z",
     {"JLCPCB_SESSION_ID": "abc", "c": "3"}),
    (CURL_B, {"a": "1", "JLCPCB_SESSION_ID": "abc", "c": "3"}),
    ("curl 'https://jlcpcb.com/' -H 'accept: */*' -H 'Cookie: JLCPCB_SESSION_ID=abc; c=3' -H 'x: y'",
     {"JLCPCB_SESSION_ID": "abc", "c": "3"}),
    ("curl 'https://jlcpcb.com/' --cookie \"JLCPCB_SESSION_ID=abc\"", {"JLCPCB_SESSION_ID": "abc"}),
    ("curl 'https://jlcpcb.com/' -b $'JLCPCB_SESSION_ID=abc'", {"JLCPCB_SESSION_ID": "abc"}),
    ("0d9f6c1e-1234-4abc-8def-000000000000", {"JLCPCB_SESSION_ID": "0d9f6c1e-1234-4abc-8def-000000000000"}),
    ('[{"name": "JLCPCB_SESSION_ID", "value": "abc"}]', {"JLCPCB_SESSION_ID": "abc"}),
    ("this is not a cookie", {}),
    ("curl 'https://jlcpcb.com/' -H 'accept: */*'", {}),
])
def test_a_paste_is_read_in_every_form_devtools_gives(blob, expected):
    assert jlc_web._parse_cookie_blob(blob) == expected


def test_a_paste_with_no_session_stores_nothing():
    with pytest.raises(HTTPException) as err:
        jlc_web_router.put_session(jlc_web_router.SessionBody(cookies="XSRF-TOKEN=y"), db=None)
    assert err.value.status_code == 400


def test_a_refused_paste_stores_nothing(monkeypatch):
    monkeypatch.setattr(jlc_web.httpx, "request", lambda *a, **k: httpx.Response(200, json=LOGGED_OUT))
    with pytest.raises(HTTPException) as err:
        # db=None: reaching the store would raise something other than this.
        jlc_web_router.put_session(jlc_web_router.SessionBody(cookies="JLCPCB_SESSION_ID=x; XSRF-TOKEN=y"), db=None)
    assert err.value.status_code == 409
    assert "kept" in err.value.detail
