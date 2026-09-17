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

## Setting up the printer

1. Plug it in and give it its own power adapter. USB alone does not bring it up.
2. **The DYMO driver has to be on the machine, but no DYMO application has to
   run.** On the current bench macOS created the queue by itself the moment the
   printer was plugged in — `usb://DYMO/LabelWriter%20550?serial=…`, with the
   `lw550` PPD and the `raster2dymolw` filter — because that driver was already
   installed. **Do not read that as "macOS ships it".** What is on this Mac is
   DYMO's own payload: 40 DYMO PPDs in
   `/Library/Printers/PPDs/Contents/Resources/`, filters and a `pnpd` helper in
   `/Library/Printers/DYMO/`, all code-signed by Sanford, L.P. (DYMO's parent,
   team `N3S6676K3E`) and timestamped 24 April 2024.

   **How it got there cannot be established from the machine**: no installer
   receipt claims those files (`pkgutil --file-info` reports none) and
   `install.log` has rotated past it. Either DYMO's own installer or an Apple
   printer-driver update put it there, before this OS was in use.

   So on a NEW bench: plug the printer in, and if no queue appears, install
   DYMO Connect for Desktop or DYMO's standalone LabelWriter driver once. After
   that the application can be removed — the CUPS driver is what the bench
   uses, and nothing of DYMO's needs to be running.
3. Load a **DYMO Authentic** roll. The 550 series reads an RFID chip on the
   roll and refuses anything else, including older DYMO rolls without a chip.
4. The bench agent reports the queue on its own window and to the bench page.

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
