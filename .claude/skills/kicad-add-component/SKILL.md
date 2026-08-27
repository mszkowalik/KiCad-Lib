---
name: kicad-add-component
description: "Full procedure for adding a part to the 7Sigma library: duplicate check, LCSC metadata lookup, category/base-symbol/footprint selection, property construction, the per-category rules a version must satisfy BEFORE you publish it (nothing gates a bad one), and what still has to be done by hand afterwards. Use when adding, editing or publishing any component."
---
<!-- platform-skill: add-component v13 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Add a component

End-to-end procedure for adding a part to the 7Sigma library. Every write
**publishes immediately** — there is no draft gate and no approval queue
([[platform-workflow]]). Accountability is on the review axis instead: verify
what you publish and record it.

**Inputs.** Preferred: an LCSC part number (`Cxxxxx`). Otherwise: manufacturer
part number + datasheet URL.

## Procedure

1. **Check for duplicates.** `search_components` by LCSC id **and** by
   manufacturer part number. If it already exists, stop and report the existing
   component instead of adding a second one.

2. **Look up metadata.** For an LCSC part, `lcsc_lookup(Cxxxxx)` returns
   manufacturer, MPN, description, datasheet URL, LCSC's own category, and the
   package string. Use it — don't retype values from a web page.
   `search_jlc_parts` / `get_jlc_details` cover the JLCPCB assembly catalogue.

   **Then pull the EasyEDA/JLC component itself:**

   ```
   .venv/bin/easyeda2kicad --lcsc_id=C<number> --full --output ./easyeda_tmp
   ```

   `--full` gets the symbol, the footprint and the 3D model. This is the default
   source for new geometry — these boards are assembled by JLCPCB, so JLC's land
   is the one their process is built around. Always `--output ./easyeda_tmp`;
   `easyeda_tmp.*` is the git ignore rule.

   **`easyeda_tmp.*` is one fixed path in the repo root, so it is SHARED.** A
   second agent session running the same command overwrites your files with its
   part's, and `easyeda_tmp.kicad_sym` accumulates every symbol any session has
   pulled. Observed 2026-08-27: a `.step` read successfully at one moment was
   gone minutes later, replaced by two unrelated parts. Two habits make this
   harmless — **check the file you are about to use is still the part you
   downloaded** (the footprint name and the LCSC id are both in it), and
   **re-run the export rather than trusting a file you read earlier**. If you
   must hold the files across a long task, copy them somewhere private first.

3. **Pick the category.** Match where similar parts already live (chip resistors
   → `Resistor`, MLCC → `Capacitor`, TVS → `Circuit_Protection` or `Diodes` per
   existing placement). Check LCSC's own category field from step 2 rather than
   inferring from the part-number shape — see the category-placement section of
   [[conventions-library]] for the miscategorisations that keep recurring. When
   genuinely unclear, ask rather than guess.

4. **Pick the base symbol.** `list_base_symbols`: `R` for resistors, `C` for
   MLCC, `CE` for polarized caps, `L` for inductors, `D_*` for diodes, `Q_*` for
   transistors, part-specific symbols for ICs. Never invent a name — the write is
   rejected if it doesn't exist.

   **If nothing fits, start from the EasyEDA symbol** in
   `easyeda_tmp.kicad_sym` rather than drawing from scratch, then bring it up to
   [[conventions-symbols]]: pin electrical types (EasyEDA leaves nearly
   everything `unspecified`), functional grouping, and the field defaults — clear
   the `easyeda2kicad:` Footprint default and the HTML Datasheet URL it ships, or
   they emit as real library data later.

5. **Pick the footprint.** `list_footprints`, referenced as `7Sigma:<name>`.

   **If the library already has one for this package: use it, and COMPARE it
   against the JLC land from step 2 rather than replacing it.** Record the
   differences in the verification note.

   **Never edit an existing footprint to fit the part you are adding.** The land
   was drawn and verified for the parts already on it; re-cutting it silently
   changes their boards. Record a verification item on your NEW component instead,
   stating the new part's lead pitch, lead span and body against the drawn pads, so
   a human can confirm the part really can sit on this land. If it cannot, author a
   new footprint — do not modify the old one. Escalate to the user — do not fix —
   when the diff shows different pad numbering or ordering, a different pad
   count, an exposed pad present in one and not the other, the body on a
   different side of the pins, or a different pitch. Note and move on when it is
   only pad size within a few tenths, silk or courtyard width, or text placement.
   Several families here are hand-drawn on purpose; see the house-prepared list
   in [[conventions-footprints]] §1.

   **If nothing matches: import it from `easyeda_tmp.pretty/`**, conform it to
   house style ([[conventions-footprints]] §10 checklist and §4), and **take the
   EasyEDA 3D model too** from `easyeda_tmp.3dshapes/` — it is drawn to the same
   land, so it aligns. Measure the mesh bounding box before setting the offset;
   EasyEDA meshes are frequently z-centred while the footprint ships
   `(offset 0 0 0)`, which buries half the part in the board.

   Pad count must match the symbol's pin count, counting any exposed pad. Never
   force the part onto a near-miss because the package name looks similar —
   `SOIC-16` and `SOIC-16W`, `SOT-23-6` and `TSOT-23-6` are different lands.

6. **Build the properties** in the conventional order for the category. The
   reliable way to get this right is to mirror a sibling: `get_component` on an
   existing part in the same category and copy its shape. Typical order:

   `Value`, category parameters (`Power` / `Tolerance` / `Voltage` /
   `Dielectric` / …), `Footprint`, `ki_description`, `Manufacturer 1`,
   `Manufacturer Part Number 1`, `Supplier 1` = `LCSC`,
   `Supplier Part Number 1`, `LCSC Part`.

   **Do not set `Footprint_Name`.** It is the footprint's short package name
   ("0402", "SOT-23-6") and lives on the footprint itself — the generator
   injects it, so `{Footprint_Name}` resolves in `ki_description` without the
   component carrying a copy. If it is missing or wrong, fix it on the
   footprint ([[conventions-footprints]]), not here.

   Naming and description style are in [[conventions-library]] — the
   manufacturer name goes in canonical form (never the raw ALL-CAPS feed value),
   and `ki_description` is a `{Key}` template, not free text.

7. **Never set**: any `Price` key (prices are auto-managed — refreshed from the
   JLCPCB assembly ladder, with LCSC retail as fallback for parts JLC doesn't
   carry), or `Datasheet` as a property. Pass `datasheet_url` to the proposal
   tool instead ([[verify-datasheets]]).

   **Check that the PDF actually archived — and READ THE `text_layer`.**
   `propose_new_component` downloads the URL and reports a `datasheet_archive`
   block. `archived: true` is not the whole answer; the field that decides
   whether the document is usable is `text_layer`:

   | `text_layer` | What you got | What to do |
   |---|---|---|
   | `text` | a searchable PDF, every page | nothing — this is the good case |
   | `mixed` | some pages text, the rest images | usable, but `search_datasheets` silently misses the image pages — read those with `read_datasheet` page images |
   | `scan` | a PDF with no text layer at all | search finds nothing and `read_datasheet` returns empty text — replace it |
   | `none` | **not a PDF.** A web page, a DXF, a STEP | replace it: nothing can read this as a datasheet |

   `archived: false` means the download failed or was refused outright. **A
   supplier serving HTML is NOT refused** — it is stored, `archived: true`,
   with `text_layer: "none"`, which is exactly the case that looks fine at a
   glance and is worthless. Verified 2026-08-27.

   Either way, fix it before you verify anything: `read_datasheet` retries the
   download on demand, and `POST /api/datasheets/<ds_id>/fetch` forces a full
   re-fetch once the URL is right. **Prefer the manufacturer's URL over the
   distributor's copy** in the first place: LCSC and JLC rehost datasheets that
   can be older revisions, or a different part in the same family.

   Until a real PDF is stored, `search_datasheets` cannot see the part and
   `read_datasheet` has nothing to open.

8. **Publish.** `propose_new_component(name, category, base_component,
   properties_json, datasheet_url, comment)`. The component name is the
   manufacturer part number and must be globally unique.

   **It publishes immediately.** There is no draft, no Proposals view and no
   approval queue — the library, the mirror and the KiCad catalog update on the
   call, a machine validation record is written, and the version starts
   UNREVIEWED on the review axis. Get it right before you call, then verify it
   (§9).

   **Order still matters, for a different reason.** A component references
   geometry by name, so the symbol and the footprint must already EXIST when
   you call: publish new geometry first (§4, §5), then the component. What no
   longer applies is waiting for anyone to approve them.

9. **Verify what you published, and name the new footprint.** Two things are
   only done by hand:

   - **Set the package name on any footprint you created**, or this component's
     `{Footprint_Name}` will not resolve — see [[conventions-footprints]] §3.
   - **Record the verification**: `get_review_checklist` then
     `record_verification`, for the component AND for each piece of geometry you
     authored. The machine items answer themselves on publish; the judgment
     items are yours, and "checked" means you actually compared it with the
     datasheet ([[verify-datasheets]]).

For an existing part, `propose_component_edit` follows the same property rules.
Before editing a part that may already be placed on a board, check
`component_where_used` to confirm the change is property-only and safe.

## Get these right BEFORE you publish

Validation runs server-side against the platform's rule set; you don't run it.
Since 2026-08-23 there is nothing to fail: a write that breaks these rules
**publishes anyway** and hands back warnings on a version that is already live.
So this is not a gate you can lean on — it is a list to satisfy first.

- **Required, non-empty properties** — per category. Globally: `Footprint` and
  `ki_description`. Resistors additionally: `Value`, `Power`, `Tolerance`.
  Mirror a sibling with `get_component` rather than guessing which apply.
- **Manufacturer/supplier set** — `Manufacturer 1`, `Manufacturer Part Number 1`,
  `Supplier 1`, `Supplier Part Number 1` are the tracked identity properties.
- **Property patterns** — values must match the category's format:
  - `Value` → `5K1`, `100R`, `4M7` (digits + `R`/`K`/`M` multiplier)
  - `Power` → `63mW`, `0.25W`
  - `Tolerance` → `1%`, `0.1%`
  - `Footprint` → must start `7Sigma:` and the footprint must exist
  - `LCSC Part` → `C` followed by digits
- **Property length** — 200 characters max.
- **Template expressions** — every `{Key}` inside a value (typically in
  `ki_description`) must resolve to another property **on the same component**.
  Resolution is order-independent: a `{Key}` may reference a property defined
  anywhere in the list. An unresolved `{Key}` comes back as a mirror warning on
  publish and means the property genuinely isn't there — add it, or for
  `{Footprint_Name}` give the footprint a package name
  ([[conventions-footprints]] §3). A footprint you created yourself has no
  package name until you set one, so this warning is the DEFAULT outcome of
  pairing a new component with a new footprint, not a rare mistake.

When unsure what a category needs, copy the shape from an existing component in
it — never invent a property key.

## Related

[[conventions-library]] — naming, descriptions, category placement.
[[conventions-symbols]] / [[conventions-footprints]] — choosing and authoring geometry.
[[verify-datasheets]] — checking the part against its documentation.
[[platform-workflow]] — what a publish sets in motion.
