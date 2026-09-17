# Binding a bench station to a USB socket

**It cannot be done for a Dongle V2 from a web page.** This records what was
tried, what was measured, and what would have to change — so a later attempt,
most likely for the C6, starts from evidence instead of from the beginning.

Decided 2026-09-16, after the bench was built and the behaviour tested on
hardware.

## What we wanted

Four stations, each owning one USB socket. Plug a unit into the second socket
and station 2 programs it, whichever unit it is. The operator never chooses a
port; the bench knows the sockets.

## Why it cannot work

**The serial port belongs to the DEVICE, not the socket.** The CH340 is on the
dongle, so an empty socket has no serial port at all. Every unit plugged in is a
new USB adapter. There is nothing at a socket to bind to between units.

**macOS does encode the socket — and the page never sees it.** The Apple CH34x
driver builds the device node from the USB `locationID`, which is the physical
port path (measured 2026-09-16):

| locationID | device node |
|---|---|
| `0x100000` | `/dev/cu.usbserial-10` |
| `0x1100000` | `/dev/cu.usbserial-110` |

Chrome knows this name too and shows it in its port picker. But
`SerialPort.getInfo()` returns only `usbVendorId`, `usbProductId` and a
Bluetooth service class id — no path, no location, no serial number. A device
path is identifying, so the API withholds it by design.

**Every V2 dongle is the same CH340** (`0x1A86:0x7523`) and reports **no USB
serial number** (`ioreg` shows no serial-number key). So the ids cannot tell two
units apart either.

## What was tried, and how each attempt failed

| Attempt | Why it failed |
|---|---|
| Hold the `SerialPort` object per station, assuming one object per socket | Chrome mints a NEW object on every replug. Measured: `held=yes live=false states=[live] claims: #1=free` — the station holding a dead object while its live replacement sat unclaimed. |
| Match a returning port by USB ids | Every V2 answers with the same pair, so a station could take a cable that was never its own. |
| Remember the port's INDEX in `getPorts()`, per slot, in `localStorage` | An index only means something against the list it came from. "#1 of 1" written with one adapter points at a different physical port once a second is present — a station silently re-bound to the wrong cable, then refused the operator's assignment of it to another station. |
| Qualify the index with the port COUNT it was written under | Fixes the cross-count case and nothing else: move one dongle between sockets and it is still "#1 of 1", so the station takes it. |

The killing constraint is the last one combined with real use: the bench runs
**1 to 4 units at a time, asynchronously**, so the set of granted ports changes
constantly and an index is never a stable name for a socket.

## What would make it work

1. **A USB-serial adapter that stays in the socket** — an FTDI or CP2102 wired
   to the unit's UART and EN/IO0 through a fixture. The adapter never leaves the
   bus, so the port is stable and belongs to the socket, and swapping a unit
   does not touch USB at all. This is the real fix, and it is a fixture, not
   code.
2. **A bridge that reports a USB serial number.** CP2102N, a CH340B with its
   config EEPROM programmed, or a native-USB ESP32. Chrome then persists the
   permission per device, so the picker stops appearing as well — see
   `api/app/services/flasher/CLAUDE.md`. **The ESP32-C6 already does this**: its
   built-in USB-Serial/JTAG reports a MAC-derived serial number, which is why V3
   benches never hit any of this. A C6 attempt should start by checking whether
   `getInfo()` plus the persisted grant is enough on its own.
3. **A local helper process** that enumerates the real `/dev/cu.usbserial-*`
   paths and tells the page which port is which. The only page-side route, and
   it costs an install on every bench.

## Route 3 is now open — the marking agent exists (2026-09-16)

The helper that route 3 wanted was built for something else. The marking bench
runs `api/app/services/bench_agent/agent.py` on the laser machine, and it already
answers `GET /serial-ports`:

```json
{"ports": [{"device": "/dev/cu.usbserial-110", "held_by": "Google Chrome"}]}
```

Both fields matter, and the second is the one that closes the gap:

* **`device`** is the socket. macOS derives the name from the USB location, so
  the name changes when the cable moves — which is exactly the identity Web
  Serial refuses to give a page.
* **`held_by`** comes from `lsof`, and says which process has the node open.
  That is the correlation neither side can make alone: **the page opens ONE
  port, then asks the agent which node Chrome just took**. The answer binds that
  `SerialPort` object — otherwise indistinguishable from three identical CH340s
  — to a physical socket. Measured 2026-09-16: `held_by` flipped from `""` to
  the holding process the instant another process opened the node.

**The bench now works this way** (2026-09-16). Assigning a port identifies it
and stores `slot -> node`; from then on a station takes the port that IS its
socket and no other. The cost is real and stated plainly: **the flashing bench
now wants the agent running too.** Without it a station still works by hand —
assign a port, use it — it simply cannot remember which socket that was.
Route 1, a fixed adapter in the socket, remains the answer that needs no
software at all.

Nothing in "Why it cannot work" below is wrong: from the PAGE ALONE it still
cannot work, and that is why the answer changed only when a process outside the
page arrived.

## What the bench does now

**By socket.** `Assign socket…` opens the picker once, identifies what was
picked, and records `slot -> /dev/cu.usbserial-NNN` in the browser. After that
the station takes that node and nothing else, across replugs and reloads, and
the port row shows the real name. `Free socket` gives it up — which is how an
operator moves a station to a different cable, and why freeing forgets the
socket rather than keeping it.

**Nothing is adopted automatically any more.** An unassigned station stays
empty however many devices appear. Arrival order lived here until 2026-09-16
and was always a guess: it handed station 1 whatever turned up, so moving a
cable silently moved the station, and the operator had no way to tell.
