# Label printing

How a device serial becomes a barcode label, what was measured to make it
print correctly, and what to do when the printer refuses. The decision is
[0022](../decisions/0022-labels-are-generated-by-the-bench-agent.md); the laser
half of the same bench is [laser-marking.md](laser-marking.md).

## The chain

```
browser  ──Web Serial──▶  device                 (reads the Tasmota device name)
browser  ──http://127.0.0.1:19842─▶ agent        (sends {value, printer, size, …})
agent    ──builds the Code 128 symbol and a PDF
agent    ──lp ──▶ CUPS ──▶ usb:// ──▶ LabelWriter 550
agent    ──lpstat ──▶ watches the job to its end
```

Nothing is pinned to the deployment version for a label: **the `print_label`
step IS the label definition.** A Code 128 label has no artwork, and its
geometry comes from the printer's PPD on the bench, which is why the agent lays
it out instead of the page. That is the one place this differs from marking.

## Setting up the printer on a new bench

Measured end to end on 2026-09-17, on a Mac put deliberately into the state a
new one arrives in.

1. Plug it in and give it its own power adapter. USB alone does not bring it up.
2. **Install DYMO's driver once.** `brew install --cask dymo-connect` fetches
   DYMO's own `DCDMac…pkg`, or download DYMO Connect for Desktop from
   dymo.com/support. The application can be deleted afterwards and none of its
   background jobs need to run: the bench printed all evening with no DYMO app
   installed and nothing of DYMO's loaded in `launchctl`. What the bench uses is
   the CUPS driver the installer leaves behind.
3. **Open the agent's status page and press Set up.** The agent finds the
   printer, matches the driver and builds the queue. Nothing else is needed,
   and no administrator password: `lpadmin` is authorised through the
   `_lpadmin` group, which an admin account already has.
4. Load a **DYMO Authentic** roll. The 550 series reads an RFID chip on the roll
   and refuses anything else, including older DYMO rolls without a chip.

**macOS does not reliably do step 3 for you.** It built the queue by itself the
first time on one bench, and on a freshly installed driver with the printer
plugged in it did not. Whether the first one was macOS or DYMO's `pnpd` could
never be established, so the bench does not depend on either.

### Why the driver is not optional, and why the match must be exact

The printer's own device-id ends `CMD: ` — **empty**. It advertises no page
language at all, no PCL, no PostScript, no PWG raster, and its USB interface is
class 7 protocol 2, a plain bidirectional printer rather than IPP-over-USB
(which is protocol 4). So nothing generic can drive it and there is no
driverless path.

That matters more than it sounds, because CUPS offers drivers that LOOK right:

```
drv:///sample.drv/dymo.ppd              DYMO Label Printer          <- CUPS's own
Library/.../se450.ppd.gz                DYMO LabelWriter SE450
Library/.../lw550c.ppd.gz               DYMO LabelWriter 550 Connect
Library/.../lw550t.ppd.gz               DYMO LabelWriter 550 Turbo
Library/.../lw550tt.ppd.gz              DYMO LabelWriter 550 Twin Turbo
Library/.../lw550.ppd.gz                DYMO LabelWriter 550        <- the only right one
```

A queue on the wrong one **looks completely healthy**: `lpadmin` accepts it, it
lists sensible label sizes, a job completes and reports "Finished page 1", and
nothing comes out of the printer. Tested with the CUPS sample driver on a
powered 550. The printer cannot complain, because it advertises no language it
could be judged against.

So the agent matches the device's `make-and-model` string EXACTLY against the
description in `lpinfo -m`, never as a substring, and it checks an existing
queue's PPD `NickName` the same way — a queue on the wrong driver is repaired
in place rather than trusted.

### What the agent can and cannot do

| | |
|---|---|
| `GET /ready` | every fact with what to do about it — the status page renders it, and the bench page reads the same JSON so the wording exists once |
| `POST /printer/setup` `{uri}` | create the queue, or repoint a wrongly-driven one |
| `POST /printer/remove` `{queue}` | remove a queue **this agent created** and nothing else |
| `POST /lightburn/open` | open LightBurn when it is installed and silent |

It cannot install the driver: that needs root, and an appliance that downloads
and runs a vendor installer is not something a bench should carry. It offers
the command and the link instead.

## Which roll, and why the bench has to be told

**The loaded roll cannot be read back.** CUPS answers with no `media-ready`, no
`media-col-ready` and no marker attributes for this driver, and `media-default`
only repeats the PPD's default. The RFID reading stays between the printer and
DYMO Connect. So the roll is a **station setting** the operator states once, and
a wrong statement costs a label rather than raising an error.

The dropdown on the marking bench lists the rolls the bench stocks, in
`ROLLS` in `web/src/components/flasher/BenchStation.tsx`. Add a row there when a
roll is bought. The agent can list all 61 the PPD knows (`GET /printers?printer=…`),
which is how you find the `size` name — it is the PPD's own page-size key and
what `lp -o PageSize=` takes.

| PPD size | Roll | Label | Printable | At 300 dpi |
|---|---|---|---|---|
| `w72h154` | 11352 return address | 25.4 x 54.1 mm | 22.9 x 50.2 mm | 271 x 593 px |
| `w79h252` | 30252 address | 27.7 x 88.9 mm | 25.3 x 81.5 mm | 299 x 963 px |
| `w162h90` | 11354 multi-purpose | 57.1 x 31.8 mm | 55.1 x 28.7 mm | 651 x 339 px |
| `w167h288` | 30256 shipping | 58.8 x 101.6 mm | 56.3 x 94.1 mm | 665 x 1112 px |

A 12-character serial needs **47.5 mm** of barcode at the standard module, so a
narrow roll has to be turned a quarter turn. `rotate` on the step does that, and
it is on by default.

## The four measurements that make a label scannable

All taken on 2026-09-17, on this printer, so nobody has to take them again.

1. **The page is rasterised to the PRINTABLE area, not the label.** A 675 x 375
   px image on a 675 x 375 px label came out scaled to 90.4 % and centred,
   because the printable area is 651 x 339 px. Content must be laid out inside
   the `ImageableArea`, which insets about 1 mm at the sides and 1.5 mm top and
   bottom. There is no full bleed on this printer.
2. **A bar edge on a whole printer dot rasterises with no grey pixel at all.**
   Three dots at 300 dpi is 0.254 mm, which is also the standard minimum
   X-dimension for Code 128. Every one of the 91 bars and spaces came out an
   exact multiple of 3 dots, and the raster held zero antialiased pixels. Below
   two dots the module is under the 0.25 mm a scanner is entitled to expect, and
   the publish gate refuses it.
3. **A label is printed before CUPS says the job is done, by about seven
   seconds.** Where the time goes, measured three times:

   | | cold | warm |
   |---|---|---|
   | `lp` returns | 0.02 s | 0.02 s |
   | the backend starts sending | 0.34 s | 0.11 s |
   | the printer starts printing | 3.34 s | 0.36 s |
   | **printing finished — the label is out** | **4.83 s** | **1.86 s** |
   | CUPS calls the job completed | 11.80 s | 9.09 s |

   The filter chain is 0.03 s of that, and `lp` 0.02 s. The three seconds
   before a cold print starts are the USB backend and the printer waking up. The
   seven seconds afterwards are `cups-waiting-for-job-completed`, a fixed
   timeout in the backend waiting for the printer to acknowledge — it was 6.97 s
   and 7.23 s on two runs and the printer is doing nothing during it.

   So the agent passes a label as printed when **the printer said it was
   printing a page, the backend has finished sending, and no fault stands** —
   not on `job-state = completed`. The fault test is what makes that safe: with
   no roll, `com.dymo.slot-status-error` stands and fails the third condition
   whatever the messages say. **`job-impressions-completed` proves nothing**: it
   reached 1 with the roll out and nothing printed, because it counts pages
   sent.

   The tail still holds the QUEUE, so a second label submitted immediately
   waits for it. Back to back, a warm print reported 4.1 s rather than 1.9 s.
4. **A faulted job waits, and resumes by itself when the fault clears.** With
   the roll removed, CUPS reported `com.dymo.slot-status-error` and the job sat
   in `processing`; putting the roll back printed it. So **a run that gives up
   must cancel its own job** — otherwise the next roll change prints a stale
   serial onto whatever unit is in the fixture. `Agent._print` does that.

## Seeing the label before it prints

The `print_label` step in the Deployments editor draws the label the agent
will produce (the marking station deliberately does not): `web/src/flasher/
label.ts` is a line-for-line mirror of the agent's `code128` and `label_pdf`,
verified module-for-module against it. The picture is the roll at its true
proportions, the printable area dashed inside it, the symbol turned when the
step says so, and the value under it; the caption gives the millimetres of
barcode, and a value that does not fit is refused under the picture with the
same sentence the agent would answer.

Two limits, both deliberate:

* **The printable area is the printer's statement.** It is read from the
  agent's `/printers` when the page runs on the bench's own origin. Anywhere
  else the label is drawn at the nominal size the roll name encodes
  (`w72h154` is 72 × 154 pt) and the caption says the printable area is on
  the bench's printer. The fit check is then against the nominal size, so a
  value within about 2 mm of the edge is only settled on the bench.
* **The picture is not the job.** The agent lays the real label out from the
  PPD on the day; the preview cannot disagree with it about the symbol, but it
  cannot know which roll is loaded either. That stays the operator's answer.

## Checking a label without using one

The printer's own filter chain runs from the command line, so a label can be
rendered and decoded back with no paper:

```
PPD=/etc/cups/ppd/DYMO_LabelWriter_550.ppd PRINTER=DYMO_LabelWriter_550 \
  /usr/libexec/cups/filter/cgpdftoraster 1 me test 1 PageSize=w72h154 label.pdf > label.ras
```

The raster is a CUPS v3 header of 1796 bytes after a four-byte sync word, then
uncompressed rows. `cupsWidth` and `cupsHeight` sit at offsets 376 and 380,
little endian. Reading one row across the bars, converting run lengths to
modules and decoding them proves the geometry end to end. That is how the
numbers above were taken, and it is worth repeating after any change to the
layout.

## When it will not print

The bench page shows the reason under the Printer pill. The one this printer
raises covers three causes at once:

| Reason | What it means |
|---|---|
| `com.dymo.slot-status-error` | no roll, the lid is open, or the labels are not DYMO Authentic |
| `cups-waiting-for-job-completed` | **not a fault.** The backend has sent everything and is waiting for the printer to finish |
| nothing on the queue at all | the agent is not running, or Chrome blocked the loopback — see [laser-marking.md](laser-marking.md) |
