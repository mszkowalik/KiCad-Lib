"""Run the real extension in Chromium against a stub Henry and stub JLCPCB pages.

Nothing here reaches jlcpcb.com: every request to it is answered by a route.
"""
import json
import pathlib
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
TOKEN = "test-token"


class Henry:
    """What the stub answers, and what it was asked."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.status = {"configured": True, "alive": True}
        self.check = {"ok": True, "expired": False}
        self.put_status = 200
        self.puts = []
        self.checks = 0
        self.bad_auth = 0


henry = Henry()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _answer(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            henry.bad_auth += 1
            return self._answer(401, {})
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if self.command == "PUT" and self.path == "/api/jlc/web/session":
            henry.puts.append(json.loads(body))
            return self._answer(henry.put_status, {})
        if self.command == "GET" and self.path == "/api/jlc/web/session":
            return self._answer(200, henry.status)
        if self.command == "POST" and self.path == "/api/jlc/web/session/check":
            henry.checks += 1
            return self._answer(200, henry.check)
        return self._answer(404, {})

    do_GET = do_PUT = do_POST = _handle


# The sync API answers a route only while a Playwright call runs, so a plain
# sleep leaves the tab's request hanging. Every wait makes a call.
pump = [lambda: None]


def settle(seconds):
    end = time.time() + seconds
    while time.time() < end:
        pump[0]()
        time.sleep(0.1)


def wait_for(what, condition, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        pump[0]()
        result = condition()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def cookie(name, value):
    return {"name": name, "value": value, "domain": ".jlcpcb.com", "path": "/",
            "secure": True, "httpOnly": True, "sameSite": "Lax"}


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    henry_url = f"http://127.0.0.1:{server.server_address[1]}"

    with sync_playwright() as p, tempfile.TemporaryDirectory() as profile:
        context = p.chromium.launch_persistent_context(
            profile, channel="chromium", headless=True,
            args=[f"--disable-extensions-except={HERE}", f"--load-extension={HERE}"],
        )

        page_hook = {"on_account_page": lambda: None}

        def jlc(route):
            page_hook["on_account_page"]()
            route.fulfill(status=200, content_type="text/html", body="<title>stub JLC</title>")

        context.route("https://jlcpcb.com/**", jlc)
        context.route("https://passport.jlcpcb.com/**", jlc)

        worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")

        def run(script):
            return worker.evaluate(script)

        pump[0] = lambda: run("1")

        def tick():
            run("serial(tick)")

        def jlc_tabs():
            return [pg for pg in context.pages if "jlcpcb.com" in pg.url]

        def fresh():
            henry.reset()
            page_hook["on_account_page"] = lambda: None
            run("""chrome.storage.local.get(['loginTabId']).then(async ({loginTabId}) => {
                await chrome.storage.local.remove(['loginStartedAt', 'loginTabId', 'refusedDigest', 'lastError']);
                await chrome.notifications.clear('jlc-login');
                await chrome.action.setBadgeText({text: ''});
                if (loginTabId != null) await chrome.tabs.remove(loginTabId).catch(() => {});
            })""")
            wait_for("tabs to close", lambda: not jlc_tabs())

        run(f"chrome.storage.local.set({{henryUrl: {json.dumps(henry_url)}, token: {json.dumps(TOKEN)}}})")

        # A login in this browser reaches Henry, httpOnly cookies included.
        fresh()
        context.add_cookies([cookie("JLCPCB_SESSION_ID", "first"), cookie("jlc_session_customer_code", "c1"),
                             cookie("XSRF-TOKEN", "x1")])
        wait_for("the first login to reach Henry", lambda: henry.puts)
        sent = henry.puts[-1]
        assert "JLCPCB_SESSION_ID=first" in sent["cookies"], sent
        assert "jlc_session_customer_code=c1" in sent["cookies"], sent
        assert sent["verify"] is True, sent
        assert sent["label"].startswith("chrome extension "), sent
        assert henry.bad_auth == 0
        print("ok  a login reaches Henry")

        # A cookie that says nothing about the login sends nothing.
        before = len(henry.puts)
        context.add_cookies([cookie("XSRF-TOKEN", "x2")])
        settle(3)
        tick()
        assert len(henry.puts) == before
        print("ok  a changed XSRF-TOKEN sends nothing")

        # Henry refuses a jar that cannot read the account, once.
        fresh()
        henry.put_status = 409
        context.add_cookies([cookie("JLCPCB_SESSION_ID", "anonymous")])
        wait_for("the refused jar", lambda: henry.puts)
        wait_for("the refusal to be stored", lambda: run(
            "chrome.storage.local.get('refusedDigest').then(s => !!s.refusedDigest)"))
        tick()
        assert len(henry.puts) == 1
        assert not jlc_tabs()
        print("ok  a refused jar is tested once")

        # A login on the same session cookie is a new jar, and it passes.
        henry.put_status = 200
        context.add_cookies([cookie("jlc_session_customer_code", "c2")])
        wait_for("the jar after a login", lambda: len(henry.puts) == 2)
        print("ok  a login after a refusal is tested again")

        # A working session opens nothing and spends no JLC call.
        fresh()
        tick()
        assert henry.checks == 0 and not jlc_tabs()
        print("ok  a live session is left alone")

        # Trouble that is not a dead session asks nobody to log in.
        fresh()
        henry.status = {"configured": True, "alive": False}
        henry.check = {"ok": False, "expired": False, "error": "JLC web HTTP 503"}
        tick()
        wait_for("the check", lambda: henry.checks == 1)
        assert not jlc_tabs()
        assert "503" in run("chrome.storage.local.get('lastError').then(s => s.lastError)")
        print("ok  a network problem opens no login")

        # A session somebody forgot stays forgotten.
        fresh()
        henry.status = {"configured": False, "alive": False}
        tick()
        assert henry.checks == 0 and not jlc_tabs()
        print("ok  Forget is respected")

        # Dead session, and the site renews it by itself: no click, no notification.
        fresh()
        henry.status = {"configured": True, "alive": False}
        henry.check = {"ok": False, "expired": True, "error": "gone"}
        page_hook["on_account_page"] = lambda: context.add_cookies([cookie("JLCPCB_SESSION_ID", "renewed")])
        tick()
        wait_for("the renewed session", lambda: any("JLCPCB_SESSION_ID=renewed" in x["cookies"] for x in henry.puts))
        wait_for("the background tab to close", lambda: not jlc_tabs())
        assert run("chrome.notifications.getAll().then(n => Object.keys(n).length)") == 0
        print("ok  a silent renewal needs no click and closes its tab")

        # Dead session, and the site asks for a login: one tab, a notification, a badge.
        fresh()
        henry.status = {"configured": True, "alive": False}
        henry.check = {"ok": False, "expired": True, "error": "gone"}
        tick()
        wait_for("the login tab", jlc_tabs)
        tick()
        settle(1)
        assert len(jlc_tabs()) == 1, "a second tick opened a second tab"
        assert run("chrome.alarms.get('login-wait').then(a => !!a)")
        run("serial(askPerson)")
        wait_for("the badge", lambda: run("chrome.action.getBadgeText({})") == "!")
        notes = run("chrome.notifications.getAll()")
        print(f"    notifications seen: {sorted(notes)}")
        assert "jlc-login" in notes, notes
        context.add_cookies([cookie("JLCPCB_SESSION_ID", "after-google")])
        wait_for("the login to reach Henry", lambda: any("after-google" in x["cookies"] for x in henry.puts))
        wait_for("the badge to clear", lambda: run("chrome.action.getBadgeText({})") == "")
        assert not run("chrome.alarms.get('login-wait').then(a => !!a)")
        wait_for("the tab to close", lambda: not jlc_tabs())
        print("ok  a login after the notification ends the wait")

        context.close()
    server.shutdown()
    print("all passed")


if __name__ == "__main__":
    sys.exit(main())
