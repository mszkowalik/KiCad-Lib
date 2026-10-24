# Select Similar for KiCad

Altium's **Find Similar Objects** for the KiCad 10 PCB editor. Select one
object, open the panel, set each attribute to **Any**, **Same** or
**Different**, and click **Apply**. The plugin puts every matching object into
KiCad's selection. KiCad's own Properties panel then edits all of them at once.

Example: select one reference designator. Set **Field Name** and **Text Height**
to Same, and type `R*` into **Parent Footprint**. Apply selects the designators
of all resistors. Set their height in the Properties panel.

## Install

1. Run `python3 build_package.py`. It writes
   `dist/com.sevensigma.select-similar-<version>.zip`.
2. In KiCad, open **Plugin and Content Manager** and click **Install from File…**.
   Select the zip.
3. In the PCB editor, open **Preferences > Plugins**. Make sure that **Enable
   KiCad API** is on.
4. Restart the PCB editor. On the first start, KiCad installs `kicad-python`
   into the plugin's own Python environment. This needs network access and
   takes some seconds. Then the button (four squares) appears at the right end
   of the top toolbar.

To show the batch edit, keep KiCad's Properties panel open: **View > Panels >
Properties**. The plugin cannot open it for you (see Limits).

## Use

1. Select an object in the PCB editor: a pad, a track, a via, a footprint, a
   designator, a text, a graphic, a zone or a dimension.
2. Click the **Select Similar** button. The panel opens with the object as the
   template. Click the button again later to bring the panel forward and load
   the current selection.
3. Click a **Match** cell to choose Any, Same or Different. With rows
   selected, the keys **S**, **A** and **D** do the same. Right-click for the
   menu.
4. To find a value that is not the template's, double-click the **Value** cell
   and type it. `*` matches any text and `?` matches one character. A typed
   length is in mm. A typed value sets the row to Same.
5. Read the preview count under the options. Click **Apply** or **OK**.

With **Follow KiCad Selection** on, a new selection in KiCad becomes the
template. The selection that Apply made does not. With several objects
selected, Same means "equal to one of them".

**Owner** is a second row in the Kind group. It starts at Same, so a board line
matches board lines and not the lines inside footprints. Set it to Any to
include footprint graphics and texts. Altium never matches a footprint's own
primitives (except pads).

## Altium options

| Altium | Here |
|---|---|
| Any / Same / Different per attribute | Same |
| Object Kind starts at Same, the rest at Any | Same, and Owner also starts at Same |
| Wildcards `*` and `?` in the Value column | Same, case-insensitive |
| Zoom Matching | KiCad's Zoom to Selection |
| Select Matching | Same: matches go into KiCad's selection |
| Clear Existing | Same. Off adds the matches to the current selection |
| Apply / OK / Cancel | Same |
| Open Properties | Not available. Keep the Properties panel open |
| Mask / Dim filtering | Not available |
| Create Expression | Not available |
| Schematic editor | Not available in KiCad 10 |

## Limits

* **PCB editor only.** KiCad 10 has no schematic API. KiCad 11 adds one.
* **The panel floats.** A KiCad 10 plugin that uses the supported API runs in
  its own process and cannot dock. On macOS the panel shows as a separate
  "Python" application. Decision
  [0096](../../docs/decisions/0096-select-similar-is-an-ipc-plugin-with-a-floating-panel.md)
  gives the reasons.
* **No Mask, Dim or Open Properties.** The API has no per-item dimming. KiCad's
  Properties action is a toggle and the API cannot read its state, so the
  plugin would close the panel as often as it opens it.
* **Zoom Matching uses a KiCad action name**, which KiCad states is not a
  stable API. If a KiCad release renames it, Zoom Matching does nothing and the
  selection still works.
* **Verified on macOS with KiCad 10.0.5.** On Linux, KiCad uses the system
  Python, which needs the `tkinter` package (for example `python3-tk`).
  Windows is not tested.

## Development

Run the tests with the plugin's venv, or any Python that has kicad-python:

```
python -m unittest discover -s tests
```

Without kicad-python, only the matching tests run. [CLAUDE.md](CLAUDE.md) tells
how to test against a running KiCad without touching an open board.
