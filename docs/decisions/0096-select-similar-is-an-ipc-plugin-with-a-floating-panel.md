---
status: accepted
date: 2026-10-23
decision-makers: Mateusz Kowalik
---

# Build Select Similar as an IPC plugin with a floating panel, not as a docked SWIG panel

## Context and Problem Statement

Altium's Find Similar Objects takes one object as a template. The user sets
each attribute to Any, Same or Different, and Altium selects every matching
object, so the Properties panel edits them together. We want the same tool in
the KiCad PCB editor, preferably as a panel that docks like KiCad's Properties
panel. KiCad 10 gives a plugin two APIs, and neither gives both a docked panel
and a complete selection. Which API does the plugin use?

The code is in [clients/kicad-select-similar](../../clients/kicad-select-similar/).

## Decision Drivers

* The matches must go into KiCad's REAL selection. Only then does KiCad's own
  Properties panel edit them in batch, which is the point of the tool.
* Pads and footprint fields (the reference designators) are the most common
  templates. A design that cannot select them misses the main use.
* KiCad plans to remove the SWIG bindings in 11.0
  ([PCB Python Bindings](https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/)).
  A forum report (not verified here) says the 10.99 nightly builds already ship
  without Python and SWIG.
* The schematic editor gets IPC API support in KiCad 11. KiCad 10 has no
  schematic API of either kind, so in 10 the tool is PCB only.

## Considered Options

* An IPC plugin (kicad-python) with its own floating window.
* A SWIG action plugin that adds an AUI pane to the PCB editor frame.
* Both, on one shared matching engine.

## Decision Outcome

Chosen option: "an IPC plugin with its own floating window", because it is the
only option that selects pads and fields and that still runs on KiCad 11.

### Consequences

* Good, because `AddToSelection` resolves any item id through
  `BOARD::ResolveItem`, footprint children included. Verified on KiCad 10.0.5:
  276 reference fields and 874 pads went into the selection, and KiCad's status
  bar showed the multi-selection.
* Good, because the same plugin can gain a schematic scope when KiCad 11 ships
  the schematic API.
* Bad, because the panel cannot dock. It is a separate window that stays on
  top, and on macOS it shows as a separate "Python" application.
* Bad, because the plugin depends on kicad-python, pynng and protobuf from
  PyPI. KiCad installs them into the plugin's own venv from
  `requirements.txt`, so the first run needs network access.
* Bad, because the API offers no per-item dimming. Altium's Mask and Dim
  filtering, and Create Expression (KiCad has no filter panel), are left out.
* Neutral: the API serves "Zoom to Selection" only through `RunAction`, whose
  action names KiCad states are not API. A renamed action makes Zoom Matching
  do nothing. The selection still works.

### Confirmation

The tests in `clients/kicad-select-similar/tests` cover the matching rules, the
reading of board messages and the PCM archive. A test against a sandbox
KiCad 10.0.5 confirmed the selection itself (the recipe is in that directory's
`CLAUDE.md`).

## Pros and Cons of the Options

### An IPC plugin with a floating window

* Good, because it selects every item kind the plugin matches.
* Good, because it uses the API KiCad supports after 10.
* Bad, because the window floats.

### A SWIG action plugin with a docked AUI pane

* Good, because the pane docks next to the Properties panel and needs no PyPI
  package.
* Bad, because `pcbnew.Refresh()` moves only items from `BOARD::GetItemSet()`
  into the selection tool (`PCB_EDIT_FRAME::RebuildAndRefresh`, 10.0 source).
  That set holds top-level items only, so pads and footprint fields flagged as
  selected never reach the selection, and the Properties panel never sees them.
* Bad, because it stops working in KiCad 11.

### Both, on a shared engine

* Good, because KiCad 10 users get the docked pane.
* Bad, because two front ends cost twice the UI work, and the docked one still
  cannot select pads or fields, and dies with KiCad 11.

## More Information

* Altium's description of the feature:
  [Using Find Similar Objects Tools](https://www.altium.com/documentation/altium-designer/find-similar-objects-tools).
* Revisit when KiCad lets an IPC plugin contribute a docked panel, or when
  KiCad 11 ships the schematic API.
