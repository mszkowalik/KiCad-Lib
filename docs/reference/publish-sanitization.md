# Publish sanitization

`services/geometry_proposals.py` corrects a drawing's derivable metadata on
every publish — `sanitize_footprint` and `sanitize_symbol` run inside the
`normalize_*_text` call site, so every door is covered: MCP, the web editor and
the KiCad plugin push.

## The two rules that decide what may go in

Both are load-bearing. A rule that breaks either one is a CHECK, not a
sanitizer.

**1. Only what the material fingerprint EXCLUDES.** `services/material.py`
leaves out `descr`, `tags` and the `property` fields, so rewriting one carries
verification and production sign-off automatically, and the copper a reviewer
diffed against JLC is untouched. Nothing may go near a pad, a pin, a courtyard
or an `attr` — a silent edit there is the one thing that could scrap a board.

**2. Only where the correct value is DERIVABLE.** If the right answer has to be
guessed, a person has to decide it. That is why `tags` and `descr` are never
touched: their content is written, not computed. It is also why a naive
"strip `easyeda2kicad`" rule was rejected — 64 footprints mention it, and every
one is a 3D model path under `${SEVENSIGMA_DIR}/3DModels/easyeda2kicad.3dshapes/`,
which is our own model folder.

## The two properties every rule must keep

**Idempotent.** Sanitization runs BEFORE the `force=False` no-op comparison.
Run it afterwards and a re-publish of already-clean text reads as a change, so
every KiCad re-save mints a version and repoints every component on the
drawing. Verified across all 420 current drawings: a second pass changes
nothing, and a re-publish of sanitized text still returns `unchanged: True`.

**Reported.** Every return path carries `sanitized`, a list of notes — including
the no-op path, so a caller can read it without knowing which branch answered.
An author is never surprised by an edit they did not make.

## The rules today

| Rule | Corrected when added (2026-09-14) |
|---|---|
| A footprint's hidden `Value` takes the footprint's own name | 74 of 213 |
| `ki_fp_filters` is removed from a symbol | 149 of 207 |
| A symbol's `Footprint` default that is not `7Sigma:` is emptied | 9 |

**The `Value` field.** KiCad writes it as the footprint's name, and
`fp.one_land_per_package` already tells an author to change it when copying a
land. 74 still carried an EasyEDA generator string
(`SW-SMD_4P-L6.0-W6.0-P4.50-LS9.0-H5.0`) or a bare MPN (`BAT-TH_KEYS2466`). The
name is the only correct value, so nothing is guessed.

**`ki_fp_filters` is DELETED outright, and that is safe only because no
component carries its own row.** Deleting a key the base symbol owns would
otherwise drop every component's own field to `(at 0 0 0)` with the default
font, because `generator.schematic_field_visibility` reads the base symbol for
each field's position and effects. The field itself filters the footprint
chooser and nothing else: the HTTP catalog does not send it
(`routers/kicad_http.py`) and a generated component symbol already has
`Footprint` set. A wrong filter is worse than none — 19 symbols carried stock
KiCad globs like `Connector*:*_1x??_*`, whose library prefix can never match our
`7Sigma:` namespace, so the chooser hid the very land the part is built on.

**A `Footprint` default is EMPTIED, not deleted**, for exactly the reason above:
that one IS displayed, and every component inherits its position and effects
from the base symbol. A `PCM_7Sigma:` reference names our own footprint wearing
the client-side nickname, so it is rewritten to `7Sigma:` rather than cleared.
