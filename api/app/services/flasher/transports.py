"""How a board is talked to: the transport profiles, and the one place they live.

**These are PLATFORM settings, not frontend constants** (user decision
2026-09-17). The whole table used to sit in `web/src/flasher/station.ts` as a
TypeScript literal while the backend knew only the two NAMES — so the baud a
device is flashed at, whether a reset re-enumerates USB, and whether the monitor
may touch DTR/RTS were all decided by a file that ships in a browser bundle.
Changing the flash baud meant a web build and a deploy, and it moved every
deployment using that profile at once, whether or not anyone had tested the
others.

Now the table is here, `GET /api/flasher/meta` serves it, and the engine resolves
it into each run's spec. The browser holds no copy.

**A profile is the DEFAULT, and a STEP overrides it.** `baud` is a field on the
esptool steps — `esp_connect`, `erase`, `flash` — because it is a property of
that erase or that write, not of the board in general and certainly not of the
browser (user decision 2026-09-17: "put it into the flash step where it
logically belongs"). The engine forwards every step field to the bench, so the
step carries it with no plumbing of its own, and it is versioned in `steps` like
the rest of the procedure.

WHY A VERSION MAY WANT ITS OWN BAUD, measured on a Dongle V2 (CH340) with the
2.27 MB factory image, 2026-09-17:

    460800   45.4 s   the profile default
    576000   fails    "serial data stream stopped"
    750000   32.5 s   3/3 clean, hash verified
    921600   fails    "invalid head of packet"

The pattern is the bridge's 12 MHz clock: 750000 is an exact divisor (12e6/16),
576000 and 921600 are not, so they alias into corruption. That is a property of
one board, which is exactly why it belongs on the version and not in a shared
profile — the Aqua uses the same profile and nobody has flashed one at 750000.
"""
from __future__ import annotations

from typing import Any

# The bauds esptool and a USB bridge can actually agree on. A value outside this
# is not a preference to honour — it is a run that corrupts halfway through,
# after the erase has already wiped the device.
FLASH_BAUDS = (115200, 230400, 460800, 750000, 921600, 1500000)

PROFILES: dict[str, dict[str, Any]] = {
    "uart_bridge": {
        "label": "external USB-UART bridge",
        "before": "default_reset",
        "flash_baud": 460800,
        # The line states the console opens with. The peripheral resets the chip
        # on DTR=0 while RTS=1, so both are held false.
        "monitor_signals": {"dataTerminalReady": False, "requestToSend": False},
        "reenumerates_on_reset": False,
    },
    "usb_serial_jtag": {
        "label": "built-in USB-Serial/JTAG",
        "before": "usb_reset",
        # CDC ignores baud entirely; changing it only forces a pointless re-open.
        "flash_baud": 115200,
        # NEVER call setSignals() on this one — a measured requirement, not a
        # preference. See docs/flasher/design.md §7.
        "monitor_signals": None,
        "reenumerates_on_reset": True,
    },
}

NAMES = tuple(PROFILES)
DEFAULT = "uart_bridge"


def resolve(profile_name: str | None) -> dict[str, Any]:
    """The transport a run starts from. A step may override the baud.

    An unknown name falls back to the bridge rather than failing, because that
    is what every board without a native USB peripheral is, and a run that
    cannot name its transport is still better served by the common case than by
    an exception eleven steps in.
    """
    return dict(PROFILES.get(profile_name or "", PROFILES[DEFAULT]))
