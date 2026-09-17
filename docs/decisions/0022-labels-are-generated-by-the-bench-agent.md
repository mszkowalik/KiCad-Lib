---
status: "accepted"
date: 2026-09-17
decision-makers: Mateusz Kowalik
---

# Print labels through CUPS, and lay them out in the bench agent rather than the page

## Context and Problem Statement

A marked device also needs a barcode label, and the operator should not change
tools between the two. The printer is a DYMO LabelWriter 550, which the vendor
documents as needing DYMO Connect on macOS, and whose rolls carry an RFID chip
the printer checks.

Marking already answers the shape of this problem: decision
[0020](0020-marking-goes-through-lightburn.md) put a local agent on the bench
for the one thing a browser cannot do, and gave the PAGE the artwork, because
the artwork is a versioned file the platform serves. A label has no artwork
file. So where is it built?

The measurements behind every number here are in
[../reference/label-printing.md](../reference/label-printing.md).

## Decision Drivers

* The agent must stay one standard-library file. A printing library would turn
  "run this file" into "set up a machine".
* A label's geometry comes from the printer's PPD, which exists on the bench
  machine and nowhere else.
* The platform must be able to say what a unit was given, so a run has to
  record what was printed and on what.
* A queued job that never printed must not be reported as a label.

## Considered Options

* Drive CUPS from the agent, and lay the label out there.
* Drive CUPS from the agent, but build the PDF in the browser.
* Use the DYMO Connect Web Service on `https://127.0.0.1:41951`.
* Speak the printer's USB protocol directly, as the laser work investigated.

## Decision Outcome

Chosen option: "drive CUPS from the agent, and lay the label out there",
because macOS already carries the DYMO PPD and filter, so a queue exists with
no vendor application at all — verified by plugging the printer in and printing
— and because the geometry the layout needs is in that PPD, on that machine.

The page sends `{value, printer, size, dots, rotate, copies}`. The agent builds
the Code 128 symbol and a one-page PDF and runs `lp`. There is no label
template and nothing pinned to the deployment version for it: **the
`print_label` STEP is the label definition**, and it is versioned because the
steps are.

### Consequences

* Good, because the bench needs no vendor software, no driver install beyond
  the PPD macOS already ships, and no second local service.
* Good, because one implementation turns a serial into bars. A TypeScript port
  beside the Python one would drift, and the symptom of drift is an unreadable
  label rather than an error.
* Good, because the roll list comes from the printer's own PPD rather than a
  table in our code.
* Bad, because the agent grew by about 210 lines, and a label bug now needs the
  operator to download the agent again. `PROTOCOL_VERSION` is how the page
  tells them to.
* Bad, because **the loaded roll cannot be read back.** CUPS reports no
  `media-ready` and no marker attributes for this driver, so the roll is a
  bench SETTING the operator states, and a wrong setting costs a label.
* Neutral, because only DYMO Authentic rolls work at all. That is the
  printer's own lockout, not ours, and it surfaces as a named fault.

### Confirmation

Three checks, all run on 2026-09-17 against the real printer:

1. A label rendered through the printer's own filter chain decodes back to the
   string it was built from, and every bar is a whole number of printer dots.
   `check_raster.py` in the reference document does this without using a label.
2. With the roll removed, CUPS reports `com.dymo.slot-status-error` and the job
   waits. With it back in, the job completes by itself. So the agent reports a
   fault rather than a success, and cancels its own job on timeout.
3. The bench page printed a label end to end, with the log readable in the run
   view.

## Pros and Cons of the Options

### Lay the label out in the agent

* Good, because the PPD is beside the printer and so is the code that reads it.
* Good, because `lp` and `lpstat` are programs, so nothing is installed.
* Bad, because the agent holds more logic than "turn a request into a command".

### Build the PDF in the browser

* Good, because it matches marking exactly: the page owns what goes on the part.
* Bad, because the geometry would have to be shipped to the browser and kept in
  step with the PPD.
* Bad, because the encoder would exist twice, in two languages.

### The DYMO Connect Web Service

* Good, because it is the vendor's supported path and understands `.dymo`
  templates.
* Bad, because it needs DYMO Connect installed on every bench, which is exactly
  the install the agent exists to avoid.
* Bad, because it is a second local service with its own TLS certificate, and
  the bench already has one local appliance.

### Speak the USB protocol directly

* Bad, because CUPS holds the interface, and the protocol is undocumented. The
  laser investigation in [0020](0020-marking-goes-through-lightburn.md) shows
  what that costs.

## More Information

* [../reference/label-printing.md](../reference/label-printing.md) — the
  measurements, the roll table, and how to add a roll.
* [0020](0020-marking-goes-through-lightburn.md) — the agent, and why the page
  owns the laser's artwork.
* [0021](0021-a-device-is-judged-by-the-rule-it-was-made-under.md) — why the
  bench may skip only the two action steps and nothing else.
* Revisit this if a bench ever needs a label that is not generated — a logo, a
  layout with fields. That is the point at which a pinned template file earns
  its place, and the `print_label` step would name one.
