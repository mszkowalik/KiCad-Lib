---
name: kicad-verify-datasheets
description: "How to check a part against its datasheet with read_datasheet, which returns page text AND rendered page images: pinout vs symbol pin directions, land pattern vs footprint, electrical values vs properties. Use when verifying or cross-checking a component against its documentation."
---
<!-- platform-skill: verify-datasheets v7 — source of truth is the platform; check with list_skills, refresh with get_skill -->

# Verify a part against its datasheet

You **can** read datasheets. `read_datasheet` opens a component's locally
archived PDF and returns the requested pages as **extracted text and rendered
page images**, so pinout drawings, package dimension tables and land-pattern
figures can be inspected visually — not just grepped for keywords.

## How to read one

1. Call `read_datasheet(component)` with no `pages` first. That returns page 1
   plus the **total page count**.
2. From the contents/index, request the exact pages you need:
   `read_datasheet(component, pages="3,14-15")`. Max 6 pages per call.
3. If the component has several datasheets, select one with `datasheet_label`
   (a case-insensitive substring of its label). Empty = the primary.

If there is no local copy yet, it is fetched from the datasheet's source URL on
first call. `web_fetch` also reads PDFs natively when you need a document that
isn't attached to a component at all.

## What to check

**Pinout vs. symbol.** Pull the pin-description table and compare it against
`get_symbol` for the base symbol: pin numbers, pin names, and — the part that
actually catches bugs — the direction of each pin. A datasheet that describes a
pin as an output on a module must be `output` on the symbol, not `passive`
([[conventions-symbols]] §2). Watch for V.24-labelled UART pins, where the
datasheet's naming is from the host's perspective and inverts on the module.

**Land pattern vs. footprint.** Compare the recommended land pattern figure
against `get_footprint`: pad count, pitch, pad dimensions, exposed-pad size,
and the pin-1 marking. Pad-to-pin-number mapping is the silent failure mode —
a mismatch produces a wrong netlist with no error anywhere
([[conventions-footprints]]).

**Electrical properties vs. component properties.** The values that end up in
`ki_description` should come from the datasheet, not from a supplier catalogue
blurb. Verify anything that looks copy-pasted or suspiciously round — in
particular, confirm whether a regulator is fixed or adjustable output before
templating an `Output Voltage` value ([[conventions-library]] §2).

**Package/marking.** Confirm the package matches the one `lcsc_lookup` reported
and that the ordering-code suffix corresponds to the variant you are adding
(tape-and-reel, temperature grade, tolerance bin).

## Recording the datasheet

The datasheet URL is not a component property. Pass `datasheet_url` to
`propose_new_component`, and the platform archives a local copy and links it
into the generated library automatically. `get_component` surfaces the stored
URL for a part that already has one.

## Reporting

State what you actually verified and on which pages — "pinout confirmed against
pp. 14–15, package dimensions against p. 22" — and say plainly what you could
not check. If the archived PDF is missing pages, is a short-form datasheet, or
disagrees with the LCSC metadata, report the discrepancy rather than resolving
it silently in either direction.

See [[add-component]] for where verification fits in adding a part.

