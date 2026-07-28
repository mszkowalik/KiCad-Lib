// Capability probe: what does THIS browser actually give us for Web Serial?
// Every line below is measured at runtime, nothing is assumed.

const out = document.getElementById("out");
const rows = [];

function row(name, value, tone) {
  rows.push({ name, value, tone });
  const tr = document.createElement("tr");
  const t = tone ?? (value === true ? "y" : value === false ? "n" : "q");
  tr.innerHTML = `<td>${name}</td><td class="${t}">${String(value)}</td>`;
  out.appendChild(tr);
}

row("userAgent", navigator.userAgent);
row("isSecureContext", window.isSecureContext);
row("navigator.serial present (window)", "serial" in navigator);
row("serial.requestPort is fn", typeof navigator.serial?.requestPort === "function");
row("serial.getPorts is fn", typeof navigator.serial?.getPorts === "function");
row("SerialPort.prototype.setSignals", typeof SerialPort?.prototype?.setSignals === "function");
row("SerialPort.prototype.getSignals", typeof SerialPort?.prototype?.getSignals === "function");
row("SerialPort.prototype.forget", typeof SerialPort?.prototype?.forget === "function");

// Already-granted ports (no user gesture needed): this is what lets a production
// station auto-reconnect its 5 adapters after a page reload.
try {
  const ports = await navigator.serial.getPorts();
  row("getPorts() granted count", ports.length, ports.length ? "y" : "q");
  ports.forEach((p, i) => {
    const info = p.getInfo();
    row(`  port[${i}].getInfo()`, JSON.stringify(info));
  });
} catch (e) {
  row("getPorts() error", e.message, "n");
}

// Is Web Serial usable from a dedicated worker? Decides whether 5 parallel
// flashes can each get their own thread instead of sharing the main one.
const workerSrc = `
  self.onmessage = async () => {
    const res = { hasSerial: "serial" in self.navigator };
    if (res.hasSerial) {
      res.hasGetPorts = typeof self.navigator.serial.getPorts === "function";
      res.hasRequestPort = typeof self.navigator.serial.requestPort === "function";
      try { res.grantedPorts = (await self.navigator.serial.getPorts()).length; }
      catch (e) { res.getPortsError = String(e && e.message || e); }
    }
    self.postMessage(res);
  };
`;
try {
  const w = new Worker(URL.createObjectURL(new Blob([workerSrc], { type: "text/javascript" })), {
    type: "module",
  });
  const res = await new Promise((resolve, reject) => {
    w.onmessage = (e) => resolve(e.data);
    w.onerror = (e) => reject(new Error(e.message));
    setTimeout(() => reject(new Error("worker timeout")), 3000);
    w.postMessage("go");
  });
  row("navigator.serial in DedicatedWorker", res.hasSerial);
  if (res.hasSerial) {
    row("  worker getPorts is fn", res.hasGetPorts);
    row("  worker requestPort is fn", res.hasRequestPort);
    row("  worker getPorts() count", res.grantedPorts ?? res.getPortsError ?? "-");
  }
  w.terminate();
} catch (e) {
  row("worker probe error", e.message, "n");
}

// Can a SerialPort be handed to a worker at all (structured clone / transfer)?
try {
  const ports = await navigator.serial.getPorts();
  if (!ports.length) {
    row("SerialPort structured-clone", "no granted port to test", "q");
  } else {
    try {
      structuredClone(ports[0]);
      row("SerialPort structured-clone", true);
    } catch (e) {
      row("SerialPort structured-clone", `${e.name} (not cloneable)`, "n");
    }
  }
} catch (e) {
  row("clone probe error", e.message, "n");
}

document.title = "probe done";
const pre = document.createElement("pre");
pre.id = "json";
pre.textContent = JSON.stringify(rows, null, 1);
document.body.appendChild(pre);
