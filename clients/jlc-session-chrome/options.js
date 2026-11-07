const urlBox = document.getElementById("henryUrl");
const tokenBox = document.getElementById("token");
const statusBox = document.getElementById("status");

const when = (ms) => (ms ? new Date(ms).toLocaleString() : "never");

async function show() {
  const s = await chrome.storage.local.get([
    "henryUrl", "token", "lastSentAt", "lastTickAt", "lastError", "loginStartedAt",
  ]);
  urlBox.value = s.henryUrl || "";
  tokenBox.value = s.token || "";
  statusBox.textContent = [
    `Last session sent: ${when(s.lastSentAt)}`,
    `Last check: ${when(s.lastTickAt)}`,
    s.loginStartedAt ? "Waiting for a JLCPCB login." : "Not waiting for a login.",
    s.lastError ? `Last error: ${s.lastError}` : "",
  ].join("\n");
}

async function sync() {
  statusBox.textContent = "Checking…";
  await chrome.runtime.sendMessage("tick");
  await show();
}

document.getElementById("save").addEventListener("click", async () => {
  await chrome.storage.local.set({ henryUrl: urlBox.value.trim(), token: tokenBox.value.trim() });
  await sync();
});
document.getElementById("sync").addEventListener("click", sync);
show();
