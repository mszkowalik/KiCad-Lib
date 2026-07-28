import { Station } from "./station.js";
import { runScenario } from "./runner.js";
import { SCENARIOS, DEFAULT_SCENARIO } from "./scenario.js";

const MAX_STATIONS = 5;
const stationsEl = document.getElementById("stations");
const banner = document.getElementById("banner");
const stations = [];

function fail(msg) {
  banner.textContent = msg;
  banner.style.display = "block";
}

document.getElementById("cap").textContent =
  `secureContext=${window.isSecureContext} · navigator.serial=${"serial" in navigator}`;

if (!("serial" in navigator)) {
  fail("This browser has no Web Serial API. Use Chrome, Edge or another Chromium browser on desktop.");
}

function render(st) {
  const wrap = st.el;
  wrap.querySelector(".pill").className = `pill ${st.status}`;
  wrap.querySelector(".pill").textContent = st.status;
  wrap.querySelector(".st-port").textContent = st.portLabel;
  wrap.querySelector(".step").textContent = st.step || "";
  const bar = wrap.querySelector(".bar > i");
  bar.style.width = st.progress === null ? "0" : `${st.progress}%`;
  const res = Object.entries(st.results)
    .map(([k, v]) => `<b>${k}</b>=${typeof v === "object" ? JSON.stringify(v) : v}`)
    .join(" · ");
  wrap.querySelector(".kv").innerHTML = res;
  const log = wrap.querySelector(".log");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  // Only append what is new — the log can reach thousands of lines per run.
  for (let i = st.rendered ?? 0; i < st.log.length; i++) {
    const e = st.log[i];
    const span = document.createElement("span");
    span.className = e.dir;
    const arrow = e.dir === "tx" ? "»" : e.dir === "rx" ? "«" : e.dir === "err" ? "!" : "·";
    span.textContent = `${(e.t / 1000).toFixed(2).padStart(7)} ${arrow} ${e.text}\n`;
    log.appendChild(span);
  }
  st.rendered = st.log.length;
  if (atBottom) log.scrollTop = log.scrollHeight;
  document.getElementById("runall").disabled = stations.some((s) => s.status === "busy");
}

function addStation(port) {
  if (stations.length >= MAX_STATIONS) return;
  const st = new Station(stations.length + 1, () => render(st));
  const el = document.createElement("div");
  el.className = "station";
  const options = Object.entries(SCENARIOS)
    .map(([k, s]) => `<option value="${k}"${k === DEFAULT_SCENARIO ? " selected" : ""}>${s.name}</option>`)
    .join("");
  el.innerHTML = `
    <div class="st-head">
      <span class="st-title">Station ${st.id}</span>
      <span class="pill empty">empty</span>
    </div>
    <div class="st-body">
      <div class="kv st-port">—</div>
      <select class="scenario">${options}</select>
      <div style="display:flex; gap:6px;">
        <button class="connect">Connect port…</button>
        <button class="run primary">Run scenario</button>
      </div>
      <div style="display:flex; gap:6px;">
        <button class="monitor">Open console</button>
        <button class="hardreset">Hard reset</button>
      </div>
      <input class="cmd" placeholder="type a Tasmota command + Enter (e.g. Status 0)" />
      <div class="step"></div>
      <div class="bar"><i></i></div>
      <div class="kv"></div>
    </div>
    <pre class="log"></pre>`;
  stationsEl.appendChild(el);
  st.el = el;
  stations.push(st);

  el.querySelector(".connect").onclick = async () => {
    try {
      await st.requestPort();
    } catch (e) {
      st.emit("err", e.message);
    }
  };
  const chosen = () => SCENARIOS[el.querySelector(".scenario").value];
  st.chosenScenario = chosen;
  el.querySelector(".run").onclick = () => runScenario(st, chosen());

  // --- manual diagnosis: open the port, poke it, reset it -------------------
  el.querySelector(".monitor").onclick = async () => {
    try {
      if (st.reader) await st.serialClose();
      else await st.serialOpen(chosen().monitor_baud ?? 115200, chosen());
      el.querySelector(".monitor").textContent = st.reader ? "Close console" : "Open console";
    } catch (e) {
      st.emit("err", e.message);
    }
  };
  el.querySelector(".hardreset").onclick = async () => {
    try {
      const opened = !!st.reader;
      if (!opened) await st.serialOpen(chosen().monitor_baud ?? 115200, chosen());
      await st.hardResetPulse();
      if (st.profile(chosen()).reenumerates_on_reset) {
        await st.serialClose();
        await st.awaitReenumerate(25000);
        await st.serialOpen(chosen().monitor_baud ?? 115200, chosen());
      }
      el.querySelector(".monitor").textContent = "Close console";
    } catch (e) {
      st.emit("err", e.message);
    }
  };
  el.querySelector(".cmd").onkeydown = async (ev) => {
    if (ev.key !== "Enter") return;
    const text = ev.target.value.trim();
    if (!text) return;
    ev.target.value = "";
    try {
      if (!st.reader) await st.serialOpen(chosen().monitor_baud ?? 115200, chosen());
      el.querySelector(".monitor").textContent = "Close console";
      await st.write(`${text}\n`);
    } catch (e) {
      st.emit("err", e.message);
    }
  };

  if (port) st.attachPort(port);
  else render(st);
  return st;
}

document.getElementById("add").onclick = () => addStation();

// Debug/automation hook: lets an external driver (CDP) read station state.
window.__stations = stations;

document.getElementById("runall").onclick = () => {
  const ready = stations.filter((s) => s.port && s.status !== "busy");
  if (!ready.length) return fail("No station has a port yet — click “Connect port…” on a station first.");
  banner.style.display = "none";
  // Fire them all at once: this is the 5-devices-in-parallel measurement.
  const t0 = performance.now();
  Promise.all(ready.map((s) => runScenario(s, s.chosenScenario()))).then((oks) => {
    const secs = ((performance.now() - t0) / 1000).toFixed(1);
    console.log(`parallel run of ${ready.length} station(s): ${secs}s, results:`, oks);
    ready.forEach((s) => s.emit("app", `parallel batch of ${ready.length} finished in ${secs}s`));
  });
};

document.getElementById("dump").onclick = () => {
  const payload = {
    scenarios: SCENARIOS,
    userAgent: navigator.userAgent,
    stations: stations.map((s) => ({
      id: s.id,
      port: s.portLabel,
      status: s.status,
      results: s.results,
      vars: s.vars,
      timings: s.timings,
      log: s.log,
    })),
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `flasher-poc-run.json`;
  a.click();
};

// Re-attach ports the operator already granted (survives page reloads: this is
// what makes a 5-slot production bench usable without re-picking every port).
if ("serial" in navigator) {
  // Auto-attach only real USB adapters. macOS also exposes Bluetooth-Incoming-Port
  // and debug-console as serial ports; a production bench never programs through
  // those, and they would otherwise eat station slots. "Connect port…" still lets
  // an operator pick anything by hand.
  const granted = (await navigator.serial.getPorts()).filter((p) => p.getInfo().usbVendorId !== undefined);
  if (granted.length) granted.slice(0, MAX_STATIONS).forEach((p) => addStation(p));
  else addStation();
  navigator.serial.addEventListener("connect", (e) => {
    // A station mid-run whose device just re-enumerated (ESP32-C6 after reset)
    // claims the new handle; only a genuinely new device gets a new slot.
    const running = stations.find((s) => s.status === "busy" && s.lost && s.noteConnect(e.target));
    if (running) return;
    const free = stations.find((s) => !s.port);
    if (free) free.attachPort(e.target);
    else addStation(e.target);
  });
  navigator.serial.addEventListener("disconnect", (e) => {
    const st = stations.find((s) => s.port === e.target || (s.portIds && s.sameDevice(e.target)));
    if (!st) return;
    if (st.status === "busy") {
      // Expected during a reset on native USB — the scenario waits for it back.
      st.noteDisconnect(e.target);
      return;
    }
    st.emit("err", "adapter unplugged");
    st.port = null;
    st.setStatus("empty", "");
  });
}
