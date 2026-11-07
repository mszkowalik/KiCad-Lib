# Henry JLCPCB session

A Chrome extension that keeps Henry's JLCPCB session working, so nobody copies
cookies. The reasons are in
[decision 0102](../../docs/decisions/0102-a-browser-extension-carries-the-jlcpcb-login.md).

## What it does

1. When this Chrome logs in to jlcpcb.com, it sends the cookies to Henry. Henry
   tests them and keeps its old session if they cannot read the account.
2. Every 15 minutes it asks Henry whether its session works.
3. If the session is dead, it opens a JLCPCB account page in a background tab.
   If the site renews the login by itself, the new cookies go to Henry and the
   tab closes. No click is needed.
4. If the login is still missing after 1 minute, it shows a notification and a
   `!` on its icon. Click either one and log in with Google in the tab. It asks
   again after 6 hours if nobody logs in.

The extension never touches Google's pages and never holds a password. It works
only while Chrome runs.

## Install

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Click **Load unpacked** and select this folder.
4. On the extension's options page, enter your Henry API token. The token is on
   the Account page in Henry. Chrome keeps it unencrypted in its profile folder.
5. Click **Save**.
6. Allow Chrome notifications in macOS System Settings.
7. On the JLCPCB login page, tick **Remember me** before you click Google.

## Test

The test runs the real extension in Chromium against a stub Henry and stub
JLCPCB pages. It sends nothing to JLCPCB.

```
.venv/bin/python clients/jlc-session-chrome/test_extension.py
```
