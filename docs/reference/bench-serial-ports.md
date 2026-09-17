# Binding a bench station to a USB socket

A bench station owns one USB socket and programs whatever unit is plugged into
it. This is how that works, and the two hardware facts that make it need a
process outside the browser.

Established 2026-09-16 on hardware; resolved 2026-09-17 by decision
[0023](../decisions/0023-the-agent-programs-the-device.md).

## The socket is in the device node's NAME, and nowhere else

**The serial port belongs to the DEVICE, not the socket.** The CH340 is on the
dongle, so an empty socket has no serial port at all, and every unit plugged in
is a new USB adapter. There is nothing at a socket to bind to between units —
except the name macOS gives the node, which the Apple CH34x driver builds from
the USB `locationID`, the physical port path (measured 2026-09-16):

| locationID | device node |
|---|---|
| `0x100000` | `/dev/cu.usbserial-10` |
| `0x1100000` | `/dev/cu.usbserial-110` |

Move the cable to another socket and the name changes. That is the identity the
bench uses.

**Nothing else identifies a unit.** Every V2 dongle is the same CH340
(`0x1A86:0x7523`) and reports **no USB serial number** — `ioreg` shows no
serial-number key. So vendor and product ids cannot tell two units apart, and
neither can anything a device says about itself before it is programmed.

## What the bench does now

**By socket, through the agent.** `Assign socket…` lists the agent's own
`/dev/cu.*` names and records `slot -> /dev/cu.usbserial-NNN` in the browser.
After that the station programs that node and no other, across replugs and
reloads. `Free socket` gives it up — which is how an operator moves a station to
a different cable, and why freeing forgets the socket rather than keeping it.

**The picker is a live watcher, not a list.** It opens with whatever is present,
polls while it is open, and marks anything that arrives afterwards NEW and sorts
it to the top. Four identical `/dev/cu.*` names are not something an operator can
choose between; the row that APPEARS when they plug the device in is. Nothing is
auto-assigned — appearing is a strong hint, and two cables can arrive at once.

**Nothing is adopted automatically.** An unassigned station stays empty however
many devices appear. Arrival order lived here until 2026-09-16 and was always a
guess: it handed station 1 whatever turned up, so moving a cable silently moved
the station, and the operator had no way to tell.

## Why the page could not do this alone

`SerialPort.getInfo()` returns only `usbVendorId`, `usbProductId` and a
Bluetooth service class id — no path, no location, no serial number. A device
path is identifying, so Web Serial withholds it by design. Combined with the two
facts above, that left a page with no name for a socket and no name for a unit.

Four ways around it were built and measured, and all four failed: holding the
`SerialPort` object per station (Chrome mints a new object on every replug);
matching by USB ids (every V2 answers the same pair); remembering the port's
INDEX in `getPorts()` (an index only means something against the list it came
from); and qualifying that index with the port count (move one dongle between
sockets and it is still "#1 of 1"). The bench runs 1 to 4 units at a time,
asynchronously, so the set of granted ports changes constantly and an index is
never a stable name for a socket.

They are recorded here only so nobody rebuilds one. The full text is in git
history (`docs/reference/bench-serial-ports.md` before 2026-09-17), and the
reasoning that replaced them is in
[0023](../decisions/0023-the-agent-programs-the-device.md).

## What would remove the software from the problem

1. **A USB-serial adapter that stays in the socket** — an FTDI or CP2102 wired
   to the unit's UART and EN/IO0 through a fixture. The adapter never leaves the
   bus, so the port belongs to the socket and swapping a unit does not touch USB
   at all. This is the real fix, and it is a fixture, not code.
2. **A bridge that reports a USB serial number.** CP2102N, a CH340B with its
   config EEPROM programmed, or a native-USB ESP32. **The ESP32-C6 already does
   this**: its built-in USB-Serial/JTAG reports a MAC-derived serial number,
   which is why a V3 bench never meets any of this.
