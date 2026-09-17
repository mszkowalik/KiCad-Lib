---
status: "accepted"
date: 2026-09-17
decision-makers: Mateusz Kowalik
---

# Do every byte of bench serial work in the agent, and drop Web Serial entirely

## Context and Problem Statement

The bench ran on Web Serial: esptool-js flashed in the tab, the device console
was a reader in the same tab, and the engine drove both over a WebSocket. It
worked, and it carried a list of traps that each cost a bench day
(`api/app/services/flasher/CLAUDE.md`):

* esptool-js changes baud by CLOSING and REOPENING the port, which toggles
  DTR/RTS and resets the chip out from under its own stub;
* the V2's CH340 reports no USB serial number, so Chrome discards the port
  permission on every replug — one picker per unit, forever;
* Web Serial tells a page only a vendor and product id, so three identical
  dongles are indistinguishable and a station could not be tied to a socket
  without the agent's help anyway
  ([bench-serial-ports.md](../reference/bench-serial-ports.md));
* a page on a public origin needs a Chrome policy for both serial and loopback;
* and a deploy replaces the hashed chip-module chunk, after which every bench
  tab already open fails its first connect — reported as the device refusing to
  enter download mode (prod run 6329, 2026-09-17).

The bench agent already ran on the bench machine for marking and labels
([0020](0020-marking-goes-through-lightburn.md),
[0022](0022-labels-are-generated-by-the-bench-agent.md)). The question was
whether programming belongs there too, and what it costs the agent's
no-install property.

## Decision Drivers

* The bench must not depend on Chrome's serial permission model at all (user
  decision 2026-09-17: "I would rather move away from Chrome, so we're browser
  independent").
* A deploy must not break a bench in the middle of a shift.
* Python's esptool is the reference implementation: `--flash_size detect`, baud
  changes on the open descriptor, years of board quirks.
* The agent had to stay one download that opens on a double-click.

## Considered Options

* **Keep Web Serial** and guard each trap as it appears.
* **Move the esptool phase only**, keeping the console in the browser.
* **Move EVERY byte** — esptool and the device console — into the agent, and
  delete the browser implementation.
* **A native agent** (Go or Rust) instead of Python.

## Decision Outcome

Chosen option: **move every byte, and delete the browser implementation.**

The install argument that chose the browser in 0020 turned out to survive:
esptool 4.8.1 and pyserial are pure Python, import without `cryptography`
(only secure-boot commands need it), and fit in a 634 KB `vendor.zip` that the
agent extracts once into the user's cache. The download is still "expand,
double-click", on the Python macOS already has.

**The esptool-phase-only option was tried first and rejected the same day.** It
left a per-station checkbox, two implementations of the connect ladder, and a
bench that still needed a Chrome policy for the console half — all of the cost
and half of the benefit. The user's answer was "we don't need the checkbox, we
are always going to use it", which is the right instinct: a fallback nobody
picks is a second implementation that drifts.

What that made possible, and is the real payoff: **`Assign socket…` is now a
list of the agent's own `/dev/cu.*` names**, not Chrome's port picker. The
station owns a socket by name, across replugs and reloads, with no permission
to grant and none to lose.

The split that stays: the PAGE fetches the firmware — the agent holds no
platform token and makes no outbound connection — and hands the bytes over on
loopback. The engine still owns the scenario, the step order and the run
record; only the implementation underneath the actions changed.

The native-binary option was not rejected on merit. It needs code signing and a
build per architecture before it can be a download at all, and nothing today
needs what it would add.

### Consequences

* Good, because a deploy no longer touches the flashing path: the agent's
  esptool is on disk, not a chunk the tab fetches. The stale-chunk guard added
  the same morning is now dead weight in a file that no longer lazily imports
  anything.
* Good, because the bench is browser-independent. No Web Serial, no port
  picker, no `SerialAllowUsbDevicesForUrls`, no secure-context requirement.
  The Chrome policy the agent installs is now only about reaching `127.0.0.1`.
* Good, because `station.ts` lost 948 lines — the claim machinery, the
  identify-by-opening trick, the read loop, the re-enumeration dance — all of
  which existed to work around Web Serial rather than to program a device.
* Good, because the connect ladder exists once, in Python, where a baud change
  does not reopen the port.
* Bad, because the agent is no longer one standard-library file. It is one file
  plus one zip, and `vendor.zip` is a binary in the repo that
  `scripts/build-agent-vendor.sh` rebuilds from pinned versions.
* Bad, because **a bench without the agent cannot program at all.** There is no
  fallback by design. Both benches say so plainly when the agent is not
  answering, and the flashing bench keeps a heartbeat so it can.
* Bad, because a station must own a socket before it can do anything. That was
  already true for marking and for socket-bound flashing; it is now true for
  every run.
* `esptool-js`, `js-md5` and the Web Serial type package left `web/package.json`
  once the runs above had passed. The one type that survived deletion —
  the DTR/RTS pair the console opens with — is now declared in `station.ts` as
  `OutputSignals`, keeping Web Serial's key names because they are the wire
  contract `POST /monitor/open` already reads.

### Confirmation

The agent's console was verified against real hardware before the browser code
was removed: `POST /monitor/open` on `/dev/cu.usbserial-10`, `monitor/write`
of `Status`, and the ESP32's own boot log read back through
`GET /monitor?since=`. `POST /esp` was verified to fail fast and readably on a
port that cannot be opened.

**Confirmed by three full runs on 2026-09-17**: programming runs 6383, 6384
and 6385, all `pass`, all on one V2 dongle
(`d4:e9:f4:f4:df:d4`, ESP32-D0WD-V3 rev 3.1), each recording
`connect_mode: "agent: 460800 baud"`.

The two open questions are answered:

* **The CH340 takes 460800 on the open descriptor.** Every one of the three
  connected on the first rung of the ladder — no fall back to 115200, and no
  reopen. The 115200 rung is kept anyway until a unit is seen needing it,
  because its cost is one failed attempt and its absence would cost a bench
  day.
* **The hand-off from esptool to the console is clean.** All three finished the
  Tasmota dialog, and 6385 recorded `wifi_rssi: 74` and 18 configuration files
  downloaded over WiFi — so the device joined the network with credentials the
  console had written and a reset had kept.

That last point is a second measurement worth naming, because the path was
wrong first. The agent's reset originally pulsed EN immediately, and the
credentials did not survive it (run 6382, `fail`): Tasmota holds a setting in
RAM for about a second before `SaveData` writes it. The browser's reset had a
500 ms settle the port code did not. `Monitor.reset()` now waits 500 ms before
it pulls EN low and 500 ms before it lets go, and DTR is held false throughout
so the chip boots normally instead of into download mode.
