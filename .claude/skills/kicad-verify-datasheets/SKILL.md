---
name: kicad-verify-datasheets
description: "How to check a part against its datasheet: SEARCH every archived PDF with search_datasheets, map a document with datasheet_outline, then read the exact pages with read_datasheet (text AND rendered images). Covers pinout vs symbol pin directions, land pattern vs footprint, electrical values vs properties, and why the extracted text is a finding aid rather than the authority. Use when verifying or cross-checking a component against its documentation."
---
<!-- platform-skill: verify-datasheets v8 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Verify a part against its datasheet

You **can** read datasheets, and since 2026-08-25 you can **search** them. The
library archives every PDF, extracts every page as layout-aware markdown, and
indexes it. Three tools, and the order matters:

| Tool | Answers |
|---|---|
| `datasheet_outline(component)` | What is in this document, and on which page |
| `search_datasheets(query)` | Which page of which document says this |
| `read_datasheet(component, pages)` | The page itself, as text AND a rendered image |

## How to read one — outline first, never blind paging

1. **`datasheet_outline(component)`.** It returns the section map with the page
   each section starts on, plus `table_pages`, `drawing_pages` and
   `unreadable_pages`. `sections` comes from the document's own PDF outline, so
   it is present on about a quarter of the library's documents and absent on
   the rest.
2. **`search_datasheets("\"recommended land pattern\"")`** when the outline is
   empty or too coarse. Quotes force a phrase, `OR` and `-` work. Add
   `component=` to scope it to one part. Each hit names the component, the
   document, the page, the section and a snippet.
3. **`read_datasheet(component, pages="26")`** on the pages the first two steps
   named. Six pages per call maximum, so the point of steps 1 and 2 is that you
   spend those six on the right pages. RP2040 is 642 pages and its absolute
   maximum ratings are on page 615. You will not find that by paging.
4. Several datasheets on one component: select with `datasheet_label`, a
   case-insensitive substring of the label. Empty means the primary document.

If there is no local copy yet it is fetched on first call. `web_fetch` reads a
PDF natively when the document is attached to no component at all.

## The extracted text is a FINDING AID. The image is the authority.

This is the most important rule on this page. The extractor keeps a table's
grid and recovers the text drawn inside a mechanical figure, both of which
plain text extraction destroys. It also fails in two ways that look like data:

- **Text that wraps inside a merged cell is shredded.** On STM32H725 p117
  "voltage must be supplied from" came back as "voage mus e suppe rom", and
  "AHB clock frequency" as "AHB lk f / coc requency".
- **Multi-line pin labels get reordered.** In the UFBGA169 ballout
  "PC15-OSC32_OUT" came back as "OSC32_OUTPC15-".
- A unit in a vertically merged column lands on **one** row of the group, so a
  single-row read can silently lose the `MHz`.

So: use the index to find the page. Read the number off the page image before
you record it. Never quote a dimension, a rating or a pin name straight out of
a search snippet.

`extract_kind` on every hit tells you what you are holding:

| Value | Meaning |
|---|---|
| `text` | Prose or a table. Normal case. |
| `picture_text` | The words came from INSIDE a drawing — dimension callouts, a ballout grid. Often exactly what you want, but reading order is not guaranteed. |
| `empty_scan` | The page has no text layer. The image is the only content. |
| `fallback_text` | Layout extraction failed here and plain extraction was used. Tables are collapsed. |
| `failed` | Nothing extracted, on a document that should have text. Suspect the page, and report it. |

## A scan is not a verification

`get_component` reports the document's `text_layer`. When it is `scan`, every
page comes back with **no text** and `read_datasheet` returns blank pages
beside the images. That is a real trap: a verification can look like it read
the datasheet while resting on the images alone.

- Answer `cmp.datasheet_text` honestly. The machine tier already fails it for a
  scanned document.
- If you genuinely cannot read the value, record `skipped` with reason
  `no_document` or `html_datasheet` — never `checked` on a guess.
- A scanned or non-PDF datasheet is a **defect worth reporting**, not a fact of
  life. Say so in your report and name a better source URL if you find one.
  About 25 documents in the library are scans and 7 more are part-text; in every
  part-text document the unreadable pages are the TRAILING ones, which is where
  the package outline and the land pattern live.

## What to check

**Pinout vs. symbol.** Find the pin-description table with
`search_datasheets("pin description", component=...)`, then compare against
`get_symbol` for the base symbol: pin numbers, pin names, and — the part that
actually catches bugs — the direction of each pin. A pin the datasheet
describes as an output on a module must be `output` on the symbol, not
`passive` ([[conventions-symbols]] §2). Watch for V.24-labelled UART pins,
where the datasheet names from the host's perspective and the sense inverts on
the module.

**Land pattern vs. footprint.** `drawing_pages` in the outline is usually the
fastest way to the recommended land pattern. Compare against `get_footprint`:
pad count, pitch, pad dimensions, exposed-pad size and the pin-1 marking. Two
things to hold on to. First, pad-to-pin-number mapping is the silent failure
mode — a mismatch produces a wrong netlist with no error anywhere
([[conventions-footprints]]). Second, **check which way the drawing faces**: a
top view and a bottom view mirror the pad order, and the answer is usually
printed on the figure ("the above figure shows the package top view").

**Electrical properties vs. component properties.** The values in
`ki_description` must come from the datasheet, not from a supplier catalogue
blurb. Verify anything that looks copy-pasted or suspiciously round. In
particular, confirm whether a regulator is fixed or adjustable before
templating an `Output Voltage` ([[conventions-library]] §2). Note whether a
rating is per-channel or total, and continuous or peak — a value copied from a
sibling variant's table is a recurring finding.

**Package and marking.** Confirm the package matches what `lcsc_lookup`
reported, and that the ordering-code suffix matches the variant being added
(tape-and-reel, temperature grade, tolerance bin).

## Recording the datasheet

The datasheet URL is not a component property. Pass `datasheet_url` to
`propose_new_component` and the platform archives a local copy and links it
into the generated library. `get_component` surfaces the stored URL for a part
that already has one.

## Over HTTP, for a caller without the MCP tools

Same data, under `/api/datasheets`:

- `GET /search?q=&component=&limit=` — the search above.
- `GET /{ds_id}/outline` — the section map, table pages, drawing pages,
  unreadable pages.
- `GET /{ds_id}/pages/{page_no}` — one page as markdown.
- `GET /{ds_id}/file#page=N` — the PDF itself, opening at that page. Search
  hits carry this string ready-made in `uri`.
- `GET /index-status` — coverage. `POST /index {"mode":"missing"}` re-runs the
  backfill; startup arms it by itself, so a freshly stored document is indexed
  within a minute or two and needs no action from you.

## Reporting

State what you verified and on which pages — "pinout confirmed against pp.
14-15, package dimensions against p. 22" — and say plainly what you could not
check. If the archived PDF is a scan, is a short-form datasheet, is missing
pages, or disagrees with the LCSC metadata, report the discrepancy rather than
resolving it silently in either direction.

See [[add-component]] for where verification fits in adding a part.
