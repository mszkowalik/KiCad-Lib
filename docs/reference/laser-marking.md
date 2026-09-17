# Laser marking

How a device serial gets engraved, what the hardware actually is, and why the
platform drives LightBurn instead of the controller. The decision is
[0020](../decisions/0020-marking-goes-through-lightburn.md); this page holds the
measurements behind it and the things you need to run a marking bench.

## The chain

```
browser  ──Web Serial──▶  device            (reads the Tasmota device name)
browser  ──HTTP───────▶  platform           (fetches the pinned .lbrn2)
browser  ──patches XML                      (one Text shape, one attribute)
browser  ──http://127.0.0.1:19842─▶ agent   (sends the FINISHED job, polls its log)
agent    ──UDP 19840──▶  LightBurn          (FORCELOAD, START, STATUS)
LightBurn ──USB──────▶   BSL controller     (closed protocol, see below)
```

Only the agent step is new software. Everything to the left of it is the same
engine, the same run record and the same publish gate as flashing.

## Setting up a marking bench

1. LightBurn runs on the laser machine, **licensed as Pro**, with no modal
   dialog open. There is no UDP setting to switch on — the listener is always
   there — but two things silence it:

   * **Core cannot drive a galvo at all.** EZCad2 and BSL controllers are a Pro
     feature. On 2026-09-16 an upgrade left this bench on *LightBurn Core
     2.1.03*, and the symptom was not an error message: LightBurn held
     `UDP *:19840` open and ignored `PING`, `STATUS`, `HELLO` and everything
     else, on every address family. Activating Pro fixed it in one step. If the
     agent reports "LightBurn is not answering", **check the title bar for the
     tier before anything else**.
   * A modal dialog freezes the interface completely. The agent's first `PING`
     gets no answer and the run fails saying so.
2. Start the agent on that machine. **Download it from the marking bench**,
   expand the zip, double-click **7Sigma Agent**, and leave its window
   open. The first time, macOS refuses an unsigned downloaded app: right-click
   it and choose Open, once. **It opens LightBurn itself** if LightBurn is not
   already answering, so the operator starts one thing rather than two. It needs nothing installed — every import is standard library, so
   whatever Python 3 is already there runs it (verified on macOS's own 3.9.6,
   with no venv and no pip) — and the launcher already carries the bench's own
   address, so there are no flags to type.

   The archive is built per request by `GET /api/flasher/agent.zip`
   from `api/app/services/bench_agent/`. It is a ZIP rather than a bare file for
   one reason: **a download loses the execute bit and an archive keeps it**, so
   what comes out of it is something that runs on a double-click. macOS asks
   once whether to open a file from the internet.

   By hand, for a dev bench:

   ```
   python3 agent.py --origin http://localhost:5173
   ```

   It listens on `127.0.0.1:19842` only, prints every request it accepts or
   refuses, and keeps running until the window is closed.

   Its API, should you need to poke it by hand:

   | | |
   |---|---|
   | `GET /hello` | what it is, and where it thinks LightBurn is |
   | `GET /health` | `PING` + `STATUS`, and `laser_usb`: whether the controller board is on the bench machine's USB bus — the one thing LightBurn cannot say, since `STATUS` answers `OK` on a "Disconnected" profile |
   | `POST /mark` | `{name, lbrn2, start, job_timeout}` → `{job}` |
   | `GET /job/<id>?since=<n>` | the lines after `n`, and the result once done |
   | `GET /printers` | the print queues, their state, and one queue's rolls |
   | `POST /print` | `{value, printer, size, dots, rotate, copies}` -> `{job}` |

   The last two are the label half of the same bench:
   [label-printing.md](label-printing.md).

   **Plain HTTP rather than a WebSocket, on purpose**: the dependency was the
   only thing standing between an operator and a working bench. A mark's log is
   polled instead of pushed, which for a job measured in seconds costs nothing.
3. **The agent sets Chrome up on first start**, and needs no administrator
   rights to do it: Chrome reads policy from the user's own `com.google.Chrome`
   defaults domain as well as from `/Library/Managed Preferences`, and only the
   second needs root. It grants the bench's origin `SerialAllowUsbDevicesForUrls`
   for the two bench bridges and `LoopbackNetworkAccessAllowedForUrls` for
   itself, then says so and asks for Chrome to be restarted once. Existing
   entries are merged, never replaced, so another bench in the list keeps
   working, and `--no-browser-setup` turns it off.

   A profile installed in `/Library/Managed Preferences` still outranks this, so
   a managed machine can keep using `bench-policy.mobileconfig` instead. Only
   macOS is automated; elsewhere, answer Chrome's local-network prompt.
4. The Laser panel reports the two hops separately. "Agent down" is fixed on the
   bench machine; "LightBurn is not answering" is fixed in LightBurn.

## Authoring a marking procedure

A marking procedure is an ordinary deployment version. Nothing about it is
special except its kind:

1. Create a deployment with **kind `mark`**. The marking bench lists these and
   only these — read from `kind`, never from the name.
2. Add the `.lbrn2` as a **device file** and pin it to the version. The artwork
   is versioned exactly like berryware, so the run record answers "which drawing
   did this unit get".
3. Steps: open the port, read the device's identity, engrave.

   | op | what it does |
   |---|---|
   | `serial_open` | the device's own USB port |
   | `command` `Status 0`, `capture: {device_name: "Status.DeviceName"}` | Tasmota's name |
   | `mark_laser` | `value: "{device_name}"`, `take_after: "_"`, `device:` the LightBurn profile (see "The machine") |

   `take_after` exists for one shape: Tasmota names a device
   `<something>_<MAC without separators>`, and the MAC is what goes on the part.
   The old tool did the same split in `lightburn.py`.

**A marker can carry more than one laser SOURCE**, and this one does — but a
LightBurn device profile is NOT a source, and `LASER:<name>` does NOT pick one.
It picks a profile; the source is picked inside the artwork. The whole mechanism,
measured on 2026-09-17, is in "The machine" below. What the step's `device`
field therefore means: **the profile whose galvo calibration matches the source
the artwork's layers use.** The name must match LightBurn's exactly; a wrong one
answers `!` rather than being ignored, and `GET /lasers` on the agent lists what
that machine has.

`LASER:` needs **LightBurn 2.0 or newer**. It answered `!` on 1.7.03, which is
why the old tool never switched profiles.

## The machine

An **AtomStack M4**, dual source: **1064 nm / 2 W IR** and **450 nm / 10 W
diode** (from the Class 4 label — the M4 manual describes only the IR). One BSL
board drives both. It took an evening to make it mark from a clean LightBurn
install, and every fact below was measured on the machine, so nobody has to
measure it again:

| | |
|---|---|
| Laser Type | **CO2** in LightBurn's list. Fiber makes LightBurn report the board *disconnected*; UV connects but was not tested. CO2 here means PWM plus an analog power level and no fibre handshake, which is what this board's drivers take. |
| **Enable Analog Output** | **On.** The vendor config has `OPC_ENPOWERANALOGOUT=1`. With it off the source runs at a fixed idle level: a beam you can see, that changes with nothing, that marks nothing at 10 % or 100 %. |
| Tickle | off (a CO2-tube feature). Frequency 20–200 kHz (`OPC_MINPWMFREQ` / `OPC_MAXPWMFREQ`). |
| Output port 1, high | **red pointer.** The vendor file says 0; the machine says 1. |
| Output port 2, high | **Select 2nd Laser Source** — the 450 nm diode. Set it in Device Settings AND turn on *Enable Analog Output (Laser 2)*, which is greyed until a port is chosen. |
| Which source fires | **Per layer**: *Use Laser 2* at the top of the Cut Settings Editor. Off = the IR, on = the diode. The port alone does nothing. |
| Input port 1, low, full pulse | start-mark input (`STARTMARKPORT=1`, `STARTSIGNALPULSEMODE=1`). |
| Require framing before start | **Off.** On, LightBurn's Start button — and the agent's UDP `START` — opens the Live Framing window instead of marking, with the pointer tracing the outline and `STATUS` answering "not busy". That is the "galvo traces, nothing marks" symptom, and it was on by default. |
| Focus | the two red focus-assist spots overlap into one (M4 manual part 9). The pointer during a job is a separate thing. 450 nm and 1064 nm focus at different heights through the one lens. |

Two profiles, one per source, because a profile carries ONE galvo calibration
and the two sources need different ones (about 3 % apart in scale — chromatic):

| Profile | Calibration from | Layers |
|---|---|---|
| `M4 IR 1064nm` | `LmcPar_Fiber.cfg` | *Use Laser 2* off |
| `M4 Diode 450nm` | `LmcPar_Blue.cfg` | *Use Laser 2* on |

Everything else in the two profiles is identical. Verify a pairing with a 50 mm
square: the wrong calibration comes out about 51.6 mm.

**Both profiles are kept in the repo**, so a fresh laser machine is one script
away rather than another evening: [laser-marking/](laser-marking/) holds
`lightburn-devices.json` (the two `DeviceList` entries exactly as LightBurn
2.1.04 stores them), the two vendor `LmcPar_*.cfg` files the calibrations came
from, and `apply-lightburn-devices.py`, which writes the profiles into
`prefs.ini` with LightBurn closed and makes the IR one the default. The
template's `DeviceName` is `M4 IR 1064nm` too (v3), so the file opens on the
right profile when someone loads it by hand.

Three traps that cost hours, in order of cost:

- **The visible beam proves nothing about the working beam.** The pointer on
  this machine is blue-ish and follows the galvo, so "I can see the dot
  moving" was the pointer every time. The IR is invisible. Only material tells
  you which source fired: **bare aluminium marks under 1064 nm and not under
  450 nm; cardboard chars under 450 nm and is untouched by 2 W of 1064 nm.**
  White ABS marks under the IR (TiO2 darkens), 600 mm/s at 100 %.
- **A vendor `config` folder found on disk is not evidence about THIS machine**
  unless it came from its own U disk. The one used here had the red light on
  the wrong port, a 100 mm field for a 70 mm machine, and a part counter of
  1223. Its port map was still the right STARTING point — every other key
  matched — but "the config says so" settled nothing that the machine
  contradicted.
- **Only the profile LightBurn STARTED with can connect.** Switching to the
  other — in the Devices window or over UDP with `LASER:` — leaves it
  "Disconnected", and replugging the USB does not recover it; only relaunching
  LightBurn with that profile selected does. It is not a profile setting: the
  two were byte-identical apart from calibration, and a fresh clone of the
  working one failed the same way. And `STATUS` still answers `OK` on a
  disconnected profile, so a job sent to it "succeeds" and marks nothing. Hence
  the rule: **one profile per LightBurn session**, and the agent refuses a
  `device` that differs from the first one it selected in that session.

Reference numbers from AtomStack's own manual, for the IR: 500 mm/s, 100 %,
30 kHz baseline; plastic 1000–1500 mm/s at 100 %, line spacing 0.05 mm; and
every material in its table at 100 %.

The publish gate refuses a marking step that names a template the version does
not pin, or that names none when the version pins several, and warns when the
step loads the job without starting it — a run that never fires cannot prove the
part was marked.

## The artwork

`patchTemplate` replaces the `Str` attribute of one `Shape Type="Text"`. Nothing
else in the file is touched: the layers, speeds, power and passes are the
artwork author's, and LightBurn applies its own galvo correction on top. That is
the whole reason the platform patches a drawing rather than generating one.

The placeholder defaults to `123456789011`, then `123456` — the strings the CE
templates have always used, first hit wins — and a step can name its own.

Measured from `AQUA_DONGLE_Side_Info.lbrn2` v2 (2026-09-17), as an example of
what a template carries: the serial is Arial at 1.73 mm on layer 2 "Logo", a
Scan layer at 600 mm/s, 50 kHz, 2 passes, power 10–100 %, cross-hatched at 27°.
v1 ran 800 mm/s at 80 %; v2 is what white ABS was measured to want under the
M4's 1064 nm source.

## What the laser actually is, and why we do not drive it

**USB `04b4:1004`, "SEATHINKING / SEA-LASER"** — a BSL galvo controller on a
Cypress FX2LP. One vendor-specific interface, four bulk endpoints (`0x02` and
`0x06` OUT, `0x84` and `0x88` IN, 512 B, high speed), **no USB serial number**.

Four findings, all measured on 2026-09-16, so nobody has to measure them again:

- **WebUSB could claim it.** No kernel driver holds interface 0, and the
  interface was claimed from userspace with libusb. The transport is not the
  obstacle.
- **It is not an LMC board.** The endpoint layout matches the EZCAD2 boards
  [galvoplotter](https://github.com/meerk40t/galvoplotter) drives (write `0x02`,
  read `0x88`), but every LMC opcode returns the same 20-byte idle frame
  `fe ff 00 14 00 03 fa 01 00×11 fb` — `GetVersion`, `GetSerialNo`,
  `GetListStatus`, `GetPositionXY` and `ReadPort` are indistinguishable.
  Replies arrive on `0x84`, not `0x88`. Reproducible across a device reset.
- **The FX2 firmware cannot be usefully dumped.** Vendor request `0xA0` answers,
  but ignores the address: 16 KB came back with 19 distinct byte values. The
  running firmware has taken that request over. Even a clean dump would likely
  show USB plumbing rather than mark semantics, because the FX2 is a bridge to
  an FPGA.
- **The bench machine cannot capture USB.** Apple Silicon on macOS 26 exposes no
  `XHC` interface and `dumpcap -D` lists network interfaces only. Decoding the
  protocol needs a Windows host with USBPcap or a Linux host with `usbmon`.

If a capture host ever appears, vary one thing at a time: an empty job, one
line, one square at two speeds, then the real artwork. The pairs are what make
the bytes readable.

## Two things LightBurn's interface will not tell you

Both were measured against LightBurn 1.7.03 on 2026-07-26 and both are guarded
in `api/app/services/bench_agent/agent.py`:

- **`STATUS` answered `OK` with no laser connected**, so it means "not busy",
  never "a laser is there". `START` likewise answered `OK`. Neither confirms
  that anything was engraved — **a mark is operator-confirmed, not
  machine-proven**, until `STATUS` is seen reporting busy during a real job.
- **`RequireFrameBeforeStart` is on in both device profiles**, and a frame pass
  is the red pointer tracing the outline — the galvo moving with nothing
  marked. If a job traces and leaves no mark, look there before suspecting the
  source or the artwork (2026-09-17).
- **`LOADFILE` with a missing path gets no reply at all** and raises a modal
  dialog, which freezes the interface until a human dismisses it. The agent
  writes the file and verifies it exists before the command is ever sent, and
  probes `PING` before and after every command.
