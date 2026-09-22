# Invoice UI (`web/src/components/invoices`)

The invoice register and its line tree. The backend rules are in
[docs/reference/production-economics.md](../../../../docs/reference/production-economics.md).

## The invoice line "charge to" cell mirrors `line_destination`, never re-derives it

The destination cell in the Invoices line tree must cover every branch the backend's
`run_actuals.line_destination` can take: header → "shares below", pooled part →
"pool", **spread carrier (`allocate` by_value/by_qty with no run/project) → "pool
(spread)"**, excluded → the select's "nobody, on purpose", else the run/project
select. A missing branch falls through to the select and reads "— nobody —" for
money that IS charged (a landed-cost transport line spread into part prices looked
unassigned, user report 2026-07-28). When a new `allocate` value or destination
appears in the backend, add its branch here in the same change.


## A part line's library link is editable in the UI, not only by the resolver

The picker is `components/ComponentPickDialog.tsx`, shared with the batch
Materials tab — its contract is in [../CLAUDE.md](../CLAUDE.md). Here it is
reached from the **Component** column of the line tree, on `kind === "part"`
leaves, with no `onPick`: given a line id it writes `component_id` itself
through `updateCostLine`, and fills `mpn` from the chosen part only when the
line had none — overwriting an MPN the invoice printed would lose what the
supplier billed.

Before it existed the link had exactly two sources: `Resolve parts`, which
matches on MPN and gives up unless the hit is unique, and an API client passing
`component_id` itself — which the manual line form never sent. A line the
matcher could not place was therefore unlinkable forever, and an unlinked part
line keys the pool as `m<MPN>` instead of `c<id>`, so it can never meet a BOM
draw and the part silently costs nothing. Unlinking one splits a pool entry in
two, which is why the button's title says so.

The button's label is `component_name`, added to `run_actuals.line_json` for
this column. It is `""` when the line is unlinked, so the cell falls back to
"— link —".

## ONE line table for entering and for editing: `InvoiceLinesTable.tsx`

Two tables existed — the New invoice card's draft rows and the document view's
read-only tree — and they drifted: the creator offered no component link and no
exact planned cost, so a hand-typed position had to be finished by reopening the
document. `InvoiceLinesTable` is both, switched by `mode`.

- **`draft`** — every row editable, the parent owns the rows, nothing is written
  until the document is created. `draftToLineIn` shapes a row for the POST.
- **`saved`** — rows are read-only until their OWN checkbox is ticked, and the
  whole set goes through `editDocumentLines` as one call.

**ONE checkbox opens the whole document, and one Save writes it** (user
decision 2026-09-19). "Edit this invoice" turns the header fields AND every
position editable together, and `editDocumentLines` sends the header patch, the
line updates, the new rows and the voids as a single transaction. Swapping the
component mapping of two positions is legal, but neither half is legal alone —
each strands the draws priced against it — so a per-row switch or a per-field
save could not express it. The backend nets the batch before guarding it
(`batch_purchase_losses`,
[0040](../../../../docs/decisions/0040-a-purchase-cannot-be-removed-from-under-its-draws.md)).

`InvoiceFields.tsx` is the header half of the same idea: the fields a document
is CREATED with are the fields it can be CORRECTED with. Before it there was no
way at all to fix a mistyped supplier, date or printed total on a saved
document. Changing the currency or the date in it makes the server re-resolve
the pinned NBP rate, because the old one was read at the old date.

Three traps this table has already hit:

- **COUNT THE COLUMNS before touching the widths, and remember the cells hold
  INPUTS.** A width that fits a printed value still cuts the box that edits it.
  This has gone wrong twice in one day: adding the Component column without
  updating the widths pushed Split off the right edge, and removing the per-row
  edit checkbox afterwards shifted every width by one, collapsing the Kind
  select to a bare caret.
- **`note-textarea` is `flex: 1` and belongs to `.note-form`.** In a plain
  label it collapses to a stub, which is what the old New invoice card did to
  its Notes box. A multi-line value is an `AutoTextarea` on `.text`.
- **`depth` is passed in, not read off the row.** `RunCostLineRow` has no such
  field; the page computes it with `depthOf` over `parent_line_id`.
- **A header row is never editable.** It is worth zero — its children carry the
  money — so editing its quantity would be editing a number nothing reads.

## A supplier-parts position is filled in place, not in a dialog

A factory bills one figure for the components it sourced itself, and that figure
is a small BOM. The position carries ONE button — **supplier** — which fills it
from the supplier's own BOM, one row per part. There is no dialog: the rows land
in the table the reader is already looking at, and the document's own **Edit this
invoice** mode makes them editable in place, because the columns a part needs —
qty, unit, component, charge to — are already there. A second editor would be a
copy of that one. Reasoning in
[0041](../../../../docs/decisions/0041-the-supplier-parts-lump-is-a-small-bom.md).

- **Every header folds**, labelled with what it holds — `▾ 13 shares`,
  `▸ 20 parts`. A split position IS a breakdown, so it is worth opening when you
  need it and out of the way otherwise. A PARTS header starts folded because it
  is the long one; a fee breakdown starts open and keeps the shape people are
  used to. The default is seeded per document, so it survives a re-render but
  re-applies when a different document is opened.
- **It still goes through `split`**, which carries the stock guard and the
  children-may-not-exceed-the-parent rule. One write path, whichever button
  starts it.
- **A part share is a QUANTITY at a price, never a percentage.** Coverage counts
  pieces, and `amount` alone sets qty to 1 and loses them. `SplitLineDialog`
  shows Qty and Unit instead of Amount and % on a part line, and hides "Split
  evenly" and "Balance last row" — both divide a printed figure, which means
  nothing on a parts list (user report 2026-09-19).
- **Position IS the identity, and on a part line that means the component.**
  The cell holds `ComponentPickDialog` with `allowFreeText`, because a part the
  SUPPLIER provided off its own shelf legitimately has no library entry —
  batch 8's C7223 is exactly that. MPN had its own column until 2026-09-19 and
  Component until later the same day; both said what Position now says, and the
  designators a position covers are not read here. Eight columns, and the
  widths have been wrong three times — count them before you touch them.
- **A share charged to NOBODY states why, in the same cell.** `allocate:
  "excluded"` is the one destination that needs no batch and no project, so it
  is the one a person walks away from — and `excluded` passes every check the
  register has, so nothing downstream notices. The API refuses it without an
  `exclude_reason` (422) and the dialog refuses it before the save. The control
  is `costs.tsx`'s `<ExcludeReasonInput>`, shared with the line table's "How"
  column: one input, one list of the reasons already in use, so the two paths
  cannot grow two vocabularies. The dialog had NO field for it until
  2026-09-21, which is why every prepaid component share JLC's populated-board
  invoices produce arrived unlabelled.
- **The pool warning is wrong for a supplier lump and must stay conditional.**
  "Parts feed the shared pool" is true of a purchase; a supplier lump is charged
  to the batch and never pooled, which is the OPPOSITE case. `supplierLump`
  picks the right sentence.


## The JLC matcher's shortlist is a SUGGESTION — the picker offers every batch

`PUT /api/jlc/import/decision/{code}` accepts any run that exists; it checks
nothing else. The only thing that ever narrowed it was this panel, and it
narrowed it to nothing on the case that needed a human most: the "link to
another run…" select was rendered only when `candidates.length > 1`, so an
order the matcher scored no run for showed **`External project` as its one
button**. That answer is not a smaller version of the right one — it takes the
order's consigned stock value out of batch costing altogether ($1,218.98 on
SMT026092263197, reported 2026-09-22).

`RunPicker` therefore always renders, with the shortlist first and every batch
after it. Two rules for anyone changing it:

- **`propose_run_from_devices` scores only runs within the yield tolerance of
  what JLC built**, so a batch that was deliberately over-built scores nothing —
  batch 2164 is for 50 and JLC populated 60, no candidates. A batch being absent
  from `candidates` says the quantities differ, never that the link is wrong.
- **Label every count; never print them as one calculation.** `jlc_number` is
  what the invoice BILLS and `panels_assembled` is JLC's `pasteNumber`, which
  the backend prefers for `implied_devices`. The row printed "60 boards × 1 per
  panel = 75 devices" — the billed figure times the factor, beside a total
  derived from the other one — and called the factor BOM-derived while
  `panel_source` said JLC had stated it.
- **`pasteNumber` is NOT reliably the assembled count.** On SMT026092263197 the
  user ordered 75 bare PCBs and 60 populated: JLC states 75, bills 60, and the
  order drew exactly 60 of each 1-per-board part. The two figures differ on 16
  of 46 orders and `pasteNumber` is the round one every time, so the row shows
  the conflict as a banner instead of trusting either. Whether the backend
  should switch its source is an open question, not a settled rule.
