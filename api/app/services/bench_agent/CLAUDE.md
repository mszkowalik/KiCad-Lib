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
actually IS is "the part of the bench that has to run on the machine". It drives
the label printer (`/printers`, `/print`) and, since
[0023](../../../../docs/decisions/0023-the-agent-programs-the-device.md),
**every byte of serial the bench sends**: `POST /esp` (connect, erase, flash,
reset, through the vendored esptool) and `/monitor/*` plus `GET /monitor?since=`
(the device console). `GET /serial-ports` names the sockets a station can be
bound to
([reference/bench-serial-ports.md](../../../../docs/reference/bench-serial-ports.md)).

Three things that follow, and are easy to break:

- **Everything is addressed by NODE**, so nothing here works for a station with
  no socket assigned. That is the contract, not a limitation to route around.
- **The connect ladder lives HERE and nowhere else** (`EspRun`). The browser
  copy is deleted; do not reintroduce one.
- **One console session at a time**, and `/monitor/open` closes any previous
  one. The page's identity probe relies on that, and so does the hand-off
  between the esptool phase and the dialog phase.
- **A failed esptool call keeps the port open for as long as its exception
  lives** (bench, 2026-09-17: "held by Python" — the agent refusing its own
  handle, unfixable without a restart). The loader that opened the port hangs
  off the exception's traceback. So `EspRun` keeps MESSAGES, never exception
  objects, raises `from None`, and calls `release_own_port` AFTER the `except`
  block — inside it the exception is still alive and `gc.collect()` frees
  nothing. And an own-process hold is released, never refused.
- **The device console reads ONE byte and then drains `in_waiting`.**
  `ser.read(4096)` with a 200 ms timeout waits for the full count or the
  timeout — a latency floor on every reply, which paced every Tasmota command
  at about a second (run 6377). `GET /monitor` long-polls on a condition for
  the same reason: the engine drains its queue before each command, so a
  console delivered in clumps loses a reply that lands 3 ms after the write.

Adding a capability means adding a ROUTE, and keeping every rule below — in
particular the one about `vendor.zip`: it stays standard library plus that one
vetted, pure-Python archive. The moment it needs a package with a compiled
part, it stops being something an operator can download and open, and that
property is worth more than any convenience inside it.

## Setting a printer up, and the trap that makes it worth doing

The agent does the whole setup except installing the driver, which needs root.
`printer_plan()` decides what stands between each printer and a working queue,
and `bench_actions()` turns each state into a button on the status page.

- **The driver is matched on the device's make-and-model EXACTLY**, never as a
  substring, and an existing queue's PPD NickName is checked the same way. CUPS
  offers `DYMO Label Printer`, `SE450`, `550 Connect`, `550 Turbo` and
  `550 Twin Turbo` beside the right one. A queue on any of them looks healthy —
  `lpadmin` accepts it, it lists label sizes, jobs complete — and prints
  NOTHING, measured on a powered 550. The printer advertises no page language
  (`CMD:` empty), so it cannot complain.
- **`lpinfo -v` lists BACKENDS as well as devices.** Only a uri containing
  `://` is a printer; `network ipp` is a backend. Matching the scheme alone
  would find a driverless printer on every Mac.
- **Creating a queue needs no password** for an account in `_lpadmin`, which an
  admin account has. `remove_queue` only removes what this run created: a bench
  is not the place to delete somebody else's print queue.
- **Actions are derived FROM the facts**, not from a second look at the world.
  Re-reading the health raced the probe `bench_facts` starts, and the page
  offered "Open LightBurn" beside a LightBurn that was answering.
- **`bench_facts` spawns NOTHING. Every slow probe runs on a watcher, and the
  facts read its last answer.** `lpinfo -l -v` walks every CUPS backend, the
  network ones included, and takes 5.5 s on a laptop with nothing plugged in.
  Until 2026-09-17 the window tick (on Tk's main thread, every second), the
  status page (every 2 s), `/ready` and the printer watcher each ran it on
  their own, on top of one another: `/ready` answered in 25 s, the status page
  in 31 s, and the window hung for most of every cycle — "the agent is laggy
  and unresponsive", on an 8 GB Mac unusable. Now `printer_snapshot` is the one
  caller, `watch_printers` keeps `agent.printers` fresh every 10 s, and the
  same routes answer in 0.05 s. A button that CHANGES a queue refreshes the
  snapshot before it answers, so the redirect shows the truth. If a new fact
  needs a subprocess that is not measured to be instant, put it on a watcher.
- **A printer with a driver and no queue gets one, on a watcher, without being
  asked** (`watch_printers`). Only a queue that is ABSENT: repointing one that
  exists stays a button, because creating something missing and changing
  something present are different acts, and the second may undo a choice. One
  attempt per printer per run, so deleting a queue on purpose is not argued
  with ten seconds later.
- **A console nobody is using is closed and its port given back**
  (`watch_monitor`, 120 s). Nothing tells the agent that a tab was closed,
  reloaded or crashed, so until this the port stayed held until the agent was
  quit and every other program asking for it was refused. Never while a mark, a
  print or a flash is running: those own the bench even when the console is
  quiet. The touch is taken BEFORE the long poll waits, or a slow device would
  look like an abandoned tab.
- **The status page is where actions live**, because this Tk draws no text and
  the window is a launcher for that page. A link opens, a command is shown to
  copy, and anything that CHANGES the machine is a form POST — never a link,
  which a page load could follow.

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

## The version number, and why the page does not trust it

`PROTOCOL_VERSION` stayed at **3** through the whole of decision 0023, which
added `POST /esp`, `/monitor/*` and the vendored esptool. So an agent from
BEFORE the bench could program reported exactly what one that could reported,
the page saw nothing wrong, and a run failed part-way with the agent's own 404
— `no such path` — after a device was already in the socket (bench,
2026-09-17). The operator's agent was five weeks old and nothing had said so.

- **Bump `PROTOCOL_VERSION` in the same change that adds a route a page
  depends on.** It is 4 now. Forgetting it is the whole defect above.
- **But the flashing bench tests the CAPABILITY, not the number**
  (`canProgram` in `web/src/flasher/benchAgent.ts`): `/hello` reports the
  esptool it carries, and that IS the question. Raising `NEEDS_PROTOCOL`
  instead would have been tidy and wrong — it would also condemn every agent
  that programs perfectly well, for a download nobody needs. A version number
  is a proxy; ask the real question when `/hello` can answer it.
- **Anything a page must know before it commits an operator to something goes
  in `/hello`.** It is the one call made before work starts.

## The rules

- **`agent.py` is standard-library only, and `vendor.zip` is the ONE
  exception.** The agent is downloaded and run on a bench with nothing
  installed — verified against macOS's own Python 3.9.6, no venv, no pip.
  Since [0023](../../../../docs/decisions/0023-the-agent-programs-the-device.md)
  it programs devices too, and esptool is not standard library: it ships as
  `vendor.zip` beside `agent.py` (esptool 4.8.1, pyserial, and their
  pure-Python dependencies — no compiled code, ~640 KB), which `import_vendor()`
  extracts once into `~/Library/Caches/7Sigma Agent/vendor-<hash>/`. Extracted,
  not zipimported: esptool opens its stub-flasher JSON files by path. Rebuild
  it with `scripts/build-agent-vendor.sh`, never by hand, and never add a
  package with a compiled part — `cryptography` is left out on purpose, and
  esptool imports without it. Anything else the agent needs stays stdlib, and
  the page still polls plain HTTP: the library was the obstacle, and one
  vetted zip is the whole allowance.
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
