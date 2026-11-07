// Keeps Henry's JLCPCB session alive from this browser. See README.md and
// docs/decisions/0102-a-browser-extension-carries-the-jlcpcb-login.md.
//
// Everything the worker must remember lives in chrome.storage: Chrome stops an
// idle worker at any time, and globals die with it.

const DEFAULT_HENRY_URL = "https://henry.disfunction.cc";
const JLC_URL = "https://jlcpcb.com/";
// An account page. Logged out, the site sends the tab to its login page. If its
// own login server still knows this browser, the site renews the session first.
const LOGIN_URL = "https://jlcpcb.com/user-center/orders/";
const SESSION_COOKIE = "JLCPCB_SESSION_ID";
// A change to any of these can mean a new login. The analytics cookies and
// XSRF-TOKEN change all the time and mean nothing.
const LOGIN_COOKIES = new Set([SESSION_COOKIE, "jlc_session_customer_code", "ONEKEYID"]);
const TICK_ALARM = "tick";
const WAIT_ALARM = "login-wait";
const TICK_MINUTES = 15;
const WAIT_MINUTES = 1;
const ASK_AGAIN_MS = 6 * 60 * 60 * 1000;
const NOTIFICATION_ID = "jlc-login";

const load = (...keys) => chrome.storage.local.get(keys);
const save = (values) => chrome.storage.local.set(values);

// One job at a time: a login fires several cookie changes and an alarm can land
// among them, and two jobs would open two tabs.
let queue = Promise.resolve();
function serial(job) {
  const run = queue.then(job);
  queue = run.catch(async (err) => {
    await save({ lastError: String(err.message || err) });
  });
  return queue;
}

async function henry(path, init = {}) {
  const { henryUrl = DEFAULT_HENRY_URL, token } = await load("henryUrl", "token");
  if (!token) throw new Error("no Henry token set");
  return fetch(henryUrl.replace(/\/+$/, "") + path, {
    ...init,
    // The Bearer token is the identity. A browser session on Henry must not add a second one.
    credentials: "omit",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  });
}

async function readJar() {
  // By URL, not by domain: this is exactly what the browser sends to jlcpcb.com,
  // the same set a person copies from DevTools. httpOnly cookies are included.
  const cookies = await chrome.cookies.getAll({ url: JLC_URL });
  if (!cookies.some((c) => c.name === SESSION_COOKIE)) return null;
  const login = cookies
    .filter((c) => LOGIN_COOKIES.has(c.name))
    .map((c) => `${c.name}=${c.value}`)
    .sort()
    .join(";");
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(login));
  return {
    header: cookies.map((c) => `${c.name}=${c.value}`).join("; "),
    digest: Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, "0")).join(""),
  };
}

// Send this browser's login to Henry if it has not seen it. Henry tests the
// cookies first and answers 409 if they cannot read the account, and then keeps
// what it has. A refusal is remembered so one logged-out jar costs one test.
async function sendIfNew() {
  const jar = await readJar();
  if (!jar) return false;
  const { sentDigest, refusedDigest } = await load("sentDigest", "refusedDigest");
  if (jar.digest === sentDigest || jar.digest === refusedDigest) return false;
  const today = new Date().toISOString().slice(0, 10);
  const res = await henry("/api/jlc/web/session", {
    method: "PUT",
    body: JSON.stringify({ cookies: jar.header, label: `chrome extension ${today}`, verify: true }),
  });
  if (res.status === 409) {
    await save({ refusedDigest: jar.digest });
    return false;
  }
  if (!res.ok) throw new Error(`Henry answered ${res.status} when it received the session`);
  await save({ sentDigest: jar.digest, refusedDigest: null, lastSentAt: Date.now() });
  await stopWaiting();
  return true;
}

async function openBackgroundTab(url) {
  try {
    return (await chrome.tabs.create({ url, active: false })).id;
  } catch {
    // Chrome is running with no window open.
    return (await chrome.windows.create({ url, focused: false })).tabs[0].id;
  }
}

async function closeOwnTab(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    // A tab somebody is looking at, or took for something else, is theirs now.
    const onJlc = tab.url && /(^|\.)jlcpcb\.com$/.test(new URL(tab.url).hostname);
    if (onJlc && !tab.active) await chrome.tabs.remove(tabId);
  } catch {
    // Already closed.
  }
}

async function stopWaiting() {
  const { loginTabId } = await load("loginTabId");
  await chrome.storage.local.remove(["loginTabId", "loginStartedAt"]);
  await chrome.alarms.clear(WAIT_ALARM);
  await chrome.notifications.clear(NOTIFICATION_ID);
  await chrome.action.setBadgeText({ text: "" });
  if (loginTabId != null) await closeOwnTab(loginTabId);
}

// First step of a recovery: open the site in the background, with no click. The
// site's own login server may renew the session, and then a cookie change sends it.
async function startLogin() {
  const { loginStartedAt = 0, loginTabId } = await load("loginStartedAt", "loginTabId");
  if (Date.now() - loginStartedAt < ASK_AGAIN_MS) return;
  if (loginTabId != null) await closeOwnTab(loginTabId);
  await save({ loginTabId: await openBackgroundTab(LOGIN_URL), loginStartedAt: Date.now() });
  await chrome.alarms.create(WAIT_ALARM, { delayInMinutes: WAIT_MINUTES });
}

// Second step: the site had its minute, so a person has to choose the Google
// account. This extension never touches Google's pages.
async function askPerson() {
  const { loginStartedAt } = await load("loginStartedAt");
  if (!loginStartedAt) return;
  await sendIfNew();
  if (!(await load("loginStartedAt")).loginStartedAt) return;
  await chrome.action.setBadgeText({ text: "!" });
  await chrome.notifications.create(NOTIFICATION_ID, {
    type: "basic",
    iconUrl: "icon.png",
    title: "JLCPCB login needed",
    message: "Henry lost its JLCPCB session. Click here, then log in with Google.",
    requireInteraction: true,
  });
}

async function showLoginTab() {
  const { loginTabId } = await load("loginTabId");
  try {
    const tab = await chrome.tabs.update(loginTabId, { active: true });
    await chrome.windows.update(tab.windowId, { focused: true });
  } catch {
    const tab = await chrome.tabs.create({ url: LOGIN_URL, active: true });
    await save({ loginTabId: tab.id });
  }
}

async function tick() {
  await save({ lastError: "", lastTickAt: Date.now() });
  await sendIfNew();
  const res = await henry("/api/jlc/web/session");
  if (!res.ok) throw new Error(`Henry answered ${res.status} to the status request`);
  const status = await res.json();
  // No session means somebody pressed Forget. A new login still arrives through
  // sendIfNew, but nothing here asks for one.
  if (!status.configured) return stopWaiting();
  if (status.alive) return stopWaiting();
  const check = await henry("/api/jlc/web/session/check", { method: "POST" });
  if (!check.ok) throw new Error(`Henry answered ${check.status} to the session check`);
  const result = await check.json();
  if (result.ok) return stopWaiting();
  if (!result.expired) throw new Error(result.error || "JLC did not answer");
  return startLogin();
}

let cookieTimer;
chrome.cookies.onChanged.addListener(({ removed, cookie }) => {
  if (removed || !LOGIN_COOKIES.has(cookie.name)) return;
  if (!/(^|\.)jlcpcb\.com$/.test(cookie.domain)) return;
  // A login sets several cookies. Wait for them all.
  clearTimeout(cookieTimer);
  cookieTimer = setTimeout(() => serial(sendIfNew), 2000);
});

chrome.alarms.onAlarm.addListener(({ name }) => serial(name === WAIT_ALARM ? askPerson : tick));
chrome.notifications.onClicked.addListener(() => serial(showLoginTab));

chrome.action.onClicked.addListener(async () => {
  const { loginStartedAt } = await load("loginStartedAt");
  if (loginStartedAt) serial(showLoginTab);
  else chrome.runtime.openOptionsPage();
});

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message !== "tick") return false;
  serial(tick).then(() => reply(true));
  return true;
});

// Chrome may drop alarms when it restarts.
function start() {
  chrome.alarms.create(TICK_ALARM, { periodInMinutes: TICK_MINUTES });
  serial(tick);
}
chrome.runtime.onInstalled.addListener(start);
chrome.runtime.onStartup.addListener(start);
