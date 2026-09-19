
## Batch-scoped supply reaches the Materials rows through the SUBSTITUTION

A part bought straight for one batch never enters the pool, so no draw reports
it and nothing else on this tab can see it — `MatRow` is built from the BOM, the
draws, the write-offs and the substitutions. `getBatchSupply` adds it.

**Match on the FITTED part, not the row's own key.** The row is keyed by what
the design specifies and the batch bought what was actually fitted, which is a
different part number by definition — `C110548` on the row, `C7223` on the
invoice. Keying on the row alone finds nothing precisely when a substitution is
what made the batch buy the part.

**The lookup belongs ABOVE the `if (r.cons.length > 0 || r.subs.length === 0)
continue;` guard.** Put it below and it runs only for rows with no draw and a
substitution — 1 row of 20 on batch 8.

The used COST used to stay blank on a supplier-supplied position, because that
money was one lump inside the assembly fee. Itemising the lump splits it exactly
([0041](../../../../docs/decisions/0041-the-supplier-parts-lump-is-a-small-bom.md)),
so the row now shows what the batch really paid — batch 8's substituted C2 reads
301.12 against a planned 239.41, a 61.71 overspend that was previously invisible.

## Supply coverage runs even with no supplier BOM

`SupplyCoverage` has two halves and only one of them needs the supplier to
publish anything:

- **Who supplied each position** — needs a cached supplier BOM. Without one the
  panel says so and makes up no verdict.
- **Paid for twice** — compares OUR OWN rows: a part on an invoice line charged
  straight to the batch that was ALSO drawn from the pool. No BOM, no supplier,
  no import path required, so it covers a hand-entered invoice, which is exactly
  the case the first half cannot see.

So `known: false` is not "nothing to say". Check `checked_without_bom` before
printing the empty state, or the one check that works everywhere goes unshown on
every run the importer never touched.

## A fully substituted position is TWO rows, and the second sits under the first

The design's part shows `used = 0`; the row beneath it carries what actually
went on, its quantity and its cost (user 2026-09-19).

They used to be merged into one row, and the reason was sound: apart, the
design's part read "not drawn" and the fitted part read "not planned", so a
batch built correctly showed two faults. **Stating the zero is what makes them
safe to separate** — the design's row says plainly that nothing was used against
it, instead of leaving a blank somebody would fill in, and a typed quantity
there would write a draw for a part that never left our pool. Merged, the two
parts' quantities and prices were summed and neither could be read on its own.

Three things this needs, each of which was wrong first:

- **A substituted-away row has NO delta.** Its used side is zero by design, so
  `Δ qty` would print −800 and `Δ $` −239.41 on a batch that was built
  correctly — exactly the false fault the merge existed to avoid.
- **The stand-in is named after what was BOUGHT.** A substitution's
  `fitted_mpn` is the supplier's own comment on its BOM line and is often the
  VALUE, not the part: batch 8's reads `100uF`, which names nothing. Prefer the
  matching `batch_supply` row's MPN.
- **A stand-in has no plan of its own**, so the "supplier supplied it" branch
  must not copy `plannedQty` into its used column — its quantity comes from what
  the batch bought.

Only when the substitution covers EVERY designator on the line. Replacing one
LED of six means both parts were genuinely used.

## Naming a part: the library wins, otherwise print what was entered

`subName` is the one place that decides what a substitution's two sides are
called, and the rule is general (user 2026-09-19):

1. **In the library — its manufacturer part number.** The backend resolves it by
   component id or by the `LCSC Part` property and says so with
   `*_in_library`. An LCSC code names nothing to a reader: the pill used to say
   `→ C7223`, which told nobody which capacitor went on the board.
2. **Not in the library — the best string available.** A substitution's
   `fitted_mpn` is the supplier's own comment on its BOM line and is often the
   VALUE, not the part — batch 8's reads `100uF` — so an invoice line that
   carries the real part number is preferred over it.
3. **Otherwise exactly what was entered**, LCSC code or not. A part the SUPPLIER
   provided off its own shelf legitimately has no library entry, and inventing a
   name for it would be worse than printing what somebody typed.

`*_in_library` is why step 2 is safe: without it the frontend cannot tell a
library name from a typed one, and "prefer the invoice" would override the
library. The raw `*_lcsc` / `*_mpn` stay on the wire for MATCHING; they are not
for display.

## `source` says WHERE a substitution was defined, never who decided it

The pill reads **"chosen in the order"** or **"recorded here"**. It said "factory
decided", which was wrong: the common case is us picking a different part on the
supplier's web page while placing the order — our decision, made outside the
schematic, which is exactly why the design never caught up
([0042](../../../../docs/decisions/0042-a-substitution-records-where-the-change-was-defined.md)).

JLC's `matchType: "update"` means *a human changed this line*. It does not say
which human, and the platform cannot know. Never write a label that claims it.

`supplied_by` is the other axis and is unrelated: whose PARTS went on the board.
The two cross — a part chosen on the supplier's order can still come out of our
own stock — which is why they are two pills and one sentence explains both.

## Markers in a fixed-width cell are GLYPHS, and a pill must fit whole

`.run-materials-table` is `table-layout: fixed` with percentage widths, and two
of its cells carry more than one thing: Part holds a part number plus a
substitution marker, Source holds an evidence pill plus a supply pill.

**A pill is `inline-block` and `nowrap`, so the column's ellipsis cannot shorten
it — too narrow simply cuts it off, with no hint that anything is missing.** The
substitution marker was the word "substituted ↓" and was invisible at 1500px:
the reader could not tell a substituted row from an ordinary one (user report
2026-09-19). It is now a single glyph, `⇄` on the design's row and `↳` on the
one standing in, with the full sentence on the hover — the same reasoning as
`actorMark` in `Ui.tsx`.

Two more rules that fell out of the same report:

- **One supply pill, never two.** `batch-supplied` and `supplier-supplied` were
  both true on an itemised factory position — the same fact twice — so the
  second was cut off. They are merged, and a row with BOTH a pool draw and
  batch supply reads "ours + factory's", which is what it is.
- **Shorten the label, do not widen the column forever.** `JLC invoice` became
  `JLC`; the title still carries the sentence. Widths were rebalanced four times
  chasing this before the labels were shortened, which is the wrong end to pull.

Measure rather than guess: `td.scrollWidth - td.clientWidth > 3` over real rows
names every cell that is cut, and it is one line in a browser check.
