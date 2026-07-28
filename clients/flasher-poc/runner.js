// The step interpreter. Same op vocabulary that will move into the API
// (services/flasher/engine.py) once the browser becomes the serial pipe only.
import { Station } from "./station.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function subst(value, vars) {
  if (typeof value !== "string") return value;
  return value.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
}

function dig(obj, path) {
  return path.split(".").reduce((o, k) => {
    if (o === null || o === undefined) return undefined;
    if (typeof o !== "object") return undefined;
    const hit = Object.keys(o).find((x) => x.toLowerCase() === k.toLowerCase());
    return hit === undefined ? undefined : o[hit];
  }, obj);
}

export async function runScenario(station, scenario) {
  station.vars = { ...scenario.vars, ...station.vars };
  station.results = { ...station.results };
  station.timings = [];
  const t0 = performance.now();
  station.setStatus("busy", "starting");
  station.emit("app", `=== scenario "${scenario.name}" start ===`);

  try {
    for (const [i, step] of scenario.steps.entries()) {
      const label = step.label ?? step.op;
      station.setStatus("busy", `${i + 1}/${scenario.steps.length} ${label}`);
      station.emit("app", `--- step ${i + 1}: ${label} (${step.op})`);
      const ts = performance.now();
      await runStep(station, scenario, step);
      const dur = performance.now() - ts;
      station.timings.push({ step: label, op: step.op, ms: Math.round(dur) });
      station.emit("app", `--- step ${i + 1} ok in ${(dur / 1000).toFixed(2)}s`);
    }
    station.results.total_ms = Math.round(performance.now() - t0);
    station.setStatus("pass", "done");
    station.emit("app", `=== scenario PASS in ${(station.results.total_ms / 1000).toFixed(1)}s ===`);
    return true;
  } catch (e) {
    station.results.error = e.message;
    station.results.total_ms = Math.round(performance.now() - t0);
    station.emit("err", `FAIL: ${e.message}`);
    station.setStatus("fail", station.step);
    return false;
  } finally {
    try {
      if (station.reader) await station.serialClose();
      if (station.transport) await station.transport.disconnect();
    } catch (e) {
      station.emit("err", `cleanup: ${e.message}`);
    }
  }
}

async function runStep(st, scenario, step) {
  const V = (v) => subst(v, st.vars);
  const timeout = (step.timeout ?? 10) * 1000;

  switch (step.op) {
    case "esp_connect":
      await st.espOpen(scenario);
      return;

    case "erase":
      await st.espErase();
      return;

    case "flash":
      await st.espFlash(step, scenario);
      return;

    case "esp_reset":
      await st.espReset(scenario);
      return;

    case "serial_open":
      await st.serialOpen(step.baud ?? scenario.monitor_baud, scenario);
      return;

    case "await_reenumerate":
      await st.awaitReenumerate(timeout);
      return;

    case "serial_close":
      await st.serialClose();
      return;

    case "sleep":
      await sleep((step.seconds ?? 1) * 1000);
      return;

    case "reset": {
      const profile = st.profile(scenario);
      if (profile.reenumerates_on_reset) {
        // Native USB: driving RTS alone is the "assert reset" combination for
        // the USB-Serial/JTAG peripheral, and the CDC device then drops off the
        // bus. Use the full USB-JTAG sequence and re-acquire the port.
        await st.port.setSignals({ dataTerminalReady: false, requestToSend: false });
        await sleep(100);
        await st.port.setSignals({ dataTerminalReady: false, requestToSend: true });
        await sleep(100);
        await st.port.setSignals({ dataTerminalReady: false, requestToSend: false });
        st.emit("app", "USB-Serial/JTAG reset sequence sent");
        await st.serialClose();
        await st.awaitReenumerate(20000);
        await st.serialOpen(scenario.monitor_baud, scenario);
      } else {
        // Bridge: pulse RTS (wired to EN) exactly like SerialDevice.reset_device().
        await st.port.setSignals({ requestToSend: false });
        await sleep(500);
        await st.port.setSignals({ requestToSend: true });
        await sleep(500);
        await st.port.setSignals({ requestToSend: false });
        st.emit("app", "RTS reset pulse sent");
      }
      return;
    }

    case "wait_boot": {
      // Do NOT rely on catching the boot banner: on a native-USB chip everything
      // printed before the host opens the CDC port is simply lost (the port only
      // exists once the firmware is running), and on any transport an idle
      // Tasmota prints nothing at all. So poll it instead — a reply to a command
      // is the only definitive proof the firmware is up and listening.
      const probe = step.probe ?? { cmd: "Status", payload: "0", expect_key: "Status" };
      const every = (step.probe_every ?? 2) * 1000;
      const pattern = step.pattern ? new RegExp(step.pattern, "i") : null;
      const deadline = performance.now() + timeout;
      let attempt = 0;
      while (performance.now() < deadline) {
        attempt++;
        st.drainRx();
        await st.write(probe.payload ? `${probe.cmd} ${probe.payload}\n` : `${probe.cmd}\n`);
        const slice = Math.min(every, deadline - performance.now());
        const hit = await st.waitForAny(probe.expect_key, pattern, slice);
        if (hit) {
          st.emit("app", `device answered on probe ${attempt} — firmware is up`);
          await sleep(300);
          st.drainRx();
          return;
        }
        st.emit("app", `probe ${attempt}: no answer yet`);
      }
      throw new Error(
        `device never answered "${probe.cmd}" within ${step.timeout ?? 10}s ` +
          `(is it running the app, or still in the ROM/stub loader?)`,
      );
    }

    case "expect": {
      const pattern = new RegExp(V(step.pattern), "i");
      const deadline = performance.now() + timeout;
      while (performance.now() < deadline) {
        const line = await st.nextLine(deadline - performance.now());
        if (line === null) break;
        if (pattern.test(line)) return;
      }
      throw new Error(`expected /${step.pattern}/ not seen`);
    }

    case "command": {
      const resp = await st.sendCommand(V(step.cmd), V(step.payload), step.expect_key, timeout);
      if (resp === null) throw new Error(`no response to "${step.cmd}" within ${step.timeout ?? 10}s`);
      capture(st, step, resp);
      return;
    }

    case "set_and_check": {
      // Port of Tasmota.set_and_check(): send, then confirm the echoed value.
      const value = V(step.value);
      const confirm = step.confirm === undefined ? value : V(step.confirm);
      const key = step.response_key ?? step.cmd;
      const resp = await st.sendCommand(V(step.cmd), value, key, timeout);
      if (resp === null) throw new Error(`no response for ${step.cmd}`);
      if (typeof resp !== "object") throw new Error(`unexpected response type for ${step.cmd}`);
      const hit = Object.keys(resp).find((k) => k.toLowerCase().includes(key.toLowerCase()));
      if (hit === undefined) throw new Error(`response for ${step.cmd} has no ${key}: ${JSON.stringify(resp)}`);
      if (String(resp[hit]) !== String(confirm))
        throw new Error(`${step.cmd}: got "${resp[hit]}", expected "${confirm}"`);
      st.emit("app", `${step.cmd} confirmed = ${confirm}`);
      capture(st, step, resp);
      return;
    }

    case "assert_equals": {
      const got = step.var ? st.vars[step.var] : dig(st.lastResponse, step.path);
      const want = V(step.equals);
      if (String(got) !== String(want)) throw new Error(`assert_equals: got "${got}", expected "${want}"`);
      st.emit("app", `assert ok: ${step.var ?? step.path} == ${want}`);
      return;
    }

    case "assert_range": {
      const got = Number(step.var ? st.vars[step.var] : dig(st.lastResponse, step.path));
      if (!(got >= step.min && got <= step.max))
        throw new Error(`assert_range: ${got} outside [${step.min}, ${step.max}]`);
      st.emit("app", `assert ok: ${got} in [${step.min}, ${step.max}]`);
      return;
    }

    default:
      throw new Error(`unknown op "${step.op}"`);
  }
}

function capture(st, step, resp) {
  for (const [name, path] of Object.entries(step.capture ?? {})) {
    const value = dig(resp, path);
    st.vars[name] = value;
    st.results[name] = value;
    st.emit("app", `captured ${name} = ${JSON.stringify(value)}`);
  }
}
