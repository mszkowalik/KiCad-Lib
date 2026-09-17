# The marking agent (`api/app/services/bench_agent`)

The local appliance that drives LightBurn for the marking bench, and the CLI
built on the same client. Full picture:
[docs/reference/laser-marking.md](../../../../docs/reference/laser-marking.md);
the reasoning is decision
[0020](../../../../docs/decisions/0020-marking-goes-through-lightburn.md).

## It ships as a .app inside a zip, and the zip is not avoidable

A `.app` is a DIRECTORY, and HTTP delivers files, so the bundle travels inside a
container. A `.dmg` would need `hdiutil`, which is macOS-only and this API runs
on Linux. So: zip, built per request by `routers/flasher.py`, containing the
bundle plus a terminal launcher. Chrome does not expand a zip on download the
way Safari does, so the operator double-clicks twice — once to expand, once to
open. That is the floor, not a shortcut.

**A DMG was considered and rejected** (2026-09-16). It needs `hdiutil` or
`libdmg-hfsplus` — the api image is Debian and has neither — and it would be
MORE clicks, not fewer: mount, drag or run from a read-only volume, eject. It
also cannot be built per request, so it could not carry the bench's own origin.
Do not reach for one without a reason the zip does not already cover.

## Why it lives here and not in `clients/`

**Because the platform SERVES it.** `routers/flasher.py` zips `agent.py` into
the download the marking bench offers, and `clients/` is not in the api image —
`/repo` is a dev-only mount. This is the same arrangement as
`services/pcm_plugin/`, which is packaged by `services/pcm.py` for exactly the
same reason.

## It is the bench's local appliance, and it will grow

It is named for marking because that is what it was built for, but what it
actually IS is "the part of the bench that has to run on the machine". It now
drives the label printer as well (`/printers`, `/print`, 2026-09-17), and
`GET /serial-ports` is here for binding stations to USB sockets
([reference/bench-serial-ports.md](../../../../docs/reference/bench-serial-ports.md)).

Adding a capability means adding a ROUTE, and keeping every rule below. In
particular it stays one standard-library file: the moment it needs a printing
library, it stops being something an operator can download and open, and that
property is worth more than any convenience inside it.

## The printer, and the three things that are expensive to get wrong

Full measurements in
[reference/label-printing.md](../../../../docs/reference/label-printing.md);
the reasoning is [0022](../../../../docs/decisions/0022-labels-are-generated-by-the-bench-agent.md).

- **The agent LAYS THE LABEL OUT, and that is deliberate.** The laser's artwork
  is a versioned file the platform serves, so the page owns it and this file
  never reads it. A label has no artwork: its geometry is in the printer's PPD,
  on this machine. There is one implementation that turns a serial into bars,
  and it is here.
- **The loaded roll cannot be read back.** CUPS carries no `media-ready` and no
  marker attributes for this driver, and the RFID stays between the printer and
  DYMO Connect. The roll is a bench SETTING, so `size` arrives in the request
  and a wrong one costs a label rather than raising an error.
- **"Printed" is not `job-state = completed`.** CUPS holds a finished job for
  about seven more seconds under `cups-waiting-for-job-completed` while the
  printer does nothing, so waiting for it reported a two-second step as nine. A
  label is printed when the printer said it printed a page, the backend has
  finished sending, and no fault stands — the last condition is what keeps it
  honest, because a missing roll leaves its fault standing.
- **A faulted job waits, and resumes by itself when the roll goes back in**, so
  `_print` CANCELS its own job when it gives up. Leaving it queued means the
  next roll change prints a stale serial onto whatever unit is in the fixture.
- **A bar must be a whole number of printer dots wide.** Three dots at 300 dpi
  is 0.254 mm, the standard minimum module, and a whole-dot edge rasterises
  with no grey pixel for the head to halftone into a ragged bar.

**macOS only, deliberately** (user decision 2026-09-16). The Python itself is
portable, but nothing Windows-specific is shipped or claimed: no launcher we
cannot test, and `install_chrome_policy` says plainly that only macOS is
automated rather than pretending.

## The rules

- **`agent.py` must stay standalone and standard-library only.** It is
  downloaded and run on a bench with nothing installed — verified against
  macOS's own Python 3.9.6, no venv, no pip. A dependency here is not a small
  change; it is the difference between "run this file" and "set up a machine".
  That is also why it speaks plain HTTP and the page polls, rather than a
  WebSocket: the library was the whole obstacle.
- **The LightBurn client lives in `agent.py`, and `mark.py` imports it back.**
  The direction looks backwards until you remember which file has to stand
  alone. One implementation of the UDP protocol and of the dialog guards, which
  were measured against a real LightBurn and are not guesses.
- **The window is tkinter, and the LAUNCHER has to pick a Python that has it.**
  `command -v python3` often lands on Homebrew's, which ships without tkinter
  (measured 2026-09-16: `No module named '_tkinter'`), while macOS's own
  `/usr/bin/python3` has it. The app's `run` script tries candidates and takes
  the first that can import it. When none can, the agent says so and serves
  without a window rather than dying — a bench that logs to a terminal still
  marks.
- **The window draws NO text of its own, and that is measured, not chosen.**
  macOS's Python carries Tk 8.5, and on macOS 26 every Tk-drawn widget —
  Label, Text, Canvas, Listbox, Message, all of ttk — paints nothing; only the
  native controls (Button, Checkbutton, Radiobutton, Menubutton) and the title
  bar show a label, one line each (screenshots, 2026-09-17). So the window is
  five flat buttons and a title, and the text lives on `GET /`, a
  server-rendered status page the buttons open. Do not "improve" the window
  with a Label or a Text widget: it was blank twice before this was found.
- **It opens LightBurn itself, but only when LightBurn is SILENT.** Opening an
  app that is already running pulls its window in front of whatever the operator
  is doing. And only when LightBurn is on this machine: with `--host-lightburn`
  elsewhere there is nothing here to start.
- **The Origin allow-list is a real boundary, not decoration.** Chrome asks the
  operator once for local-network access; after that any page they visit can
  reach this port. A browser cannot forge `Origin`. A request with no `Origin`
  is allowed, because it cannot have come from a page.
- **Never widen the bind address.** `127.0.0.1` only. A laser is not a thing to
  expose to a LAN.
- **It sets Chrome up itself, without root.** Chrome on macOS reads policy from
  the user's `com.google.Chrome` defaults domain as well as from
  `/Library/Managed Preferences`; only the second needs an administrator, and a
  profile installed there still WINS, so a managed machine is unaffected. The
  two grants are merged into whatever is already in those keys — replacing them
  would silently unbind another bench on the same machine. Verified end to end
  on 2026-09-16: downloaded, expanded, double-clicked, policy written, second
  run reported "already in place".
- **`GET /serial-ports` reports `held_by`, and that field is the point.** From
  `lsof`. A page can open one port and then ask which node Chrome took — the
  only way to tie a `SerialPort` object to a physical socket, because Web Serial
  exposes neither a path nor a location. Listing the names alone would be
  cosmetic.
- **The download bakes the bench's own origin into the launcher**, so the
  operator types no flags. It comes from the browser's `Origin` header, the
  same way `bench-policy.mobileconfig` does — a launcher written for the wrong
  address silently refuses every request from the page.
