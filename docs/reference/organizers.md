# Office organizers

Decision [0104](../decisions/0104-an-organizer-box-says-where-the-ledger-says-what-it-cost.md).
Code: `services/organizers.py`, `routers/organizers.py`, `pages/Organizers.tsx`
(Stock → Organizers). A box says where the pieces are. The material ledger says what
they cost.

## What each write does

| Write | Box | Material ledger |
|---|---|---|
| Take for R&D | down | Draw, `basis="research"`, no batch. The note is required |
| Take for a batch | down | Draw charged to the batch. Refused on closed books and on another company's batch |
| Take for a crafted batch | down | Nothing: its process steps draw the parts (decision 0060) |
| Count, more pieces | up | Free pieces first, then the rest as an adjustment at zero value: `found`, or `opening_balance` in an import |
| Count, fewer pieces | down | Adjustment `miscount`, no batch pays |
| Move to another box | down and up | Nothing |
| Use with no box (`POST /api/organizers/research`) | no box | Draw with no batch: `basis="research"`, or `basis="external"` for a project the platform does not track. For pieces used before Henry knew about them |
| Loss with no box (same route, `purpose=loss`) | no box | Adjustment `scrap` of that company, at the average of the day. It names no batch and no project, so another company's records do not change. Date it after the purchase: the replay puts an adjustment before a purchase of the same day, which reads as negative stock |

**Free pieces** are `pool − JLC's count − all boxes`, floored at 0. They are pieces
the pool holds and nobody has placed. A count that finds pieces uses these first, or
the same purchase would enter stock twice.

## Traps

- **A count is absolute.** The person reads the number off the box. The same count
  twice writes nothing.
- **A box's company.** A box belongs to no company. A balance does. A take asks whose
  pieces only when both companies hold the part in that box. A row shows one part in
  one box, with the companies inside it.
- **`Draw.basis == "research"` is not an uncharged draw.** The register reports it as
  `pool.research_drawn_usd`. An uncharged draw waits for a batch, and this one never
  will. A new reader of `run_id IS NULL` must keep the two apart.
- **Zero value is a fact, not a default.** It means no purchase in the records covers
  the piece. Such a lot pulls the part's moving average down, and the next draw takes
  that average.
  `GET /api/stock-adjustments` counts these as `zero_cost_from_boxes`, apart from
  `zero_cost_positive`, whose warning stays for rows with no evidence.
- **The Stock page reads the boxes as they stood at JLC's count**, the same as it
  reads the pool (`run_actuals.parts_stock`). A box dated after the count was not
  there when JLC counted.
- **The pool can hold more than the boxes and JLC together.** A part may be at the
  assembler, or used with no draw. Nothing writes it off. Stock → Parts shows the two
  numbers, and a person decides.
- **A part used up stays on its box** at 0, as it did in the sheet. Clear takes the
  row away. A part moved away leaves by itself.
- **Every write but one is a journal batch**, so History → Write batches undoes it. An
  import is one batch, and a second run writes only what is new. Deleting a box is a
  batch too: undo the delete first if an older batch made that box.
- **The same part can show as two rows on one box.** A row that names an MPN makes an
  item with no component when `jlc_apply._component_index` does not know that MPN. The
  index reads component names, LCSC codes and JLC's links, not the MPN property. The
  picker names the component, so it makes a second item. The money does not split,
  because the pool matches by identity overlap.
- **The "Used for R&D" list reads `basis="research"` only.** A use for an untracked
  project is in the part's ledger on Stock → Parts. A loss is under Stock adjustments on
  the same page.

## Loading a list

`POST /api/organizers/import` takes rows with `organizer`, `code`, the part, `qty`,
`company_id` and `note`, and a dry run is the default. A row with no part makes an
empty box. `at` dates the whole list.

"Load a list" on the page sends pasted rows, one per line, with the columns split by a
tab or a semicolon: organizer, box code, MPN, LCSC code, pieces, company, note. The
page refuses a bad line before it sends anything, and names the line. A row that names
no company takes the one chosen in the dialog. A count with a thousands separator is
refused, because `1,000` is 1 in one locale and 1000 in another.

The page must send a box code. A row with an empty code answers 500, because
`import_rows` looks up a box it did not make.
