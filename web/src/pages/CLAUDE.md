# Pages (`web/src/pages`)

One file per route. A page composes shared components; it does not invent its
own input, table or card. Read `web/CLAUDE.md` for the style system and
`../components/CLAUDE.md` for what is already built.

## The Account page is the user's own settings; Setup is administration

`/account` is reached by clicking the signed-in name in the top bar, and it
holds what belongs to whoever is signed in: `AccountSecurityCard` (own password,
own API tokens), `GitCredentialsCard` (git accounts) and `KicadClientCards`
(Effective URLs, the PCM install, the `.kicad_httplib` download, Claude Code /
MCP). Setup stays administration of OTHER people's accounts and the deployment's
knobs, so a new per-user setting goes here, not there.

**The KiCad boxes moved here because every one of them carries the signed-in
user's token** — the PCM URL installs a sync plugin with that token inside it,
and the `.kicad_httplib` embeds it — so they are personal credentials in URL
form and two people must see two different strings. `GET /api/kicad/config`
already personalises itself from the caller's session, so the move needed no new
endpoint. Admin keeps a pointer, on its System tab.

**Admin is SIX TABS, and `TABS` in `pages/Admin.tsx` is the whole list**
(2026-09-19): Configuration, Users, Datasheets, Exchange rates, Fleet broker,
System. A row carries its own one-line blurb, printed in the toolbar, and
`admin: true` on the two the API refuses to a non-admin — those are filtered
out rather than rendered as controls that can only fail, and a URL naming one
falls back to Configuration. A new admin panel is a row there, not another
card appended to a scroll: the six used to be stacked, and the schema readout
was four screens below the Configuration table.

**Changing your own password is `POST /api/auth/password`, which has existed
since sign-in was built** — it ends every OTHER session and RE-ISSUES this one,
so the person is not signed out of the tab they are typing in. Do not add a
second implementation to the account router; the first version of this card did,
and the copy was worse.

- **A token field says "replace", never "edit".** The API returns only whether
  one is stored, the same posture as `SettingsCard`'s secrets.
- **A credential nobody has checked must not read as working.** The Last check
  pill is `not checked` / `ok` / `failed`, and `check_ok: null` means either
  never checked or checked while no project used it — never "fine".
- **A project picks a credential BY NAME, and may still type its own token.**
  The account wins when both are set, so the project page prints
  `token_source`, not just "stored (encrypted)" — that wording is exactly how a
  revoked copy hid on production for weeks (decision 0010).


## Site structure (UI overhaul, 2026-07-29)

- **Five nav sections**: Library (`/library/...`), Projects (+ `/runs/:id`),
  Production (`/production/...`), Reviews (`/reviews` queue,
  `/reviews/checklists` editor), Setup. Second-level navigation is
  `SectionNav` in `App.tsx`; every pre-overhaul route redirects, so never link
  to `/components/...`, `/invoices`, `/parts-stock`, `/kicad`, `/proposals` in
  new code — use the new paths.
- **The Reviews queue is a workbench, not just a table.** A row expands
  inline (`components/ReviewWorkbench.tsx`): one collapsible row per subject on
  the left (`ReviewSubjectRows`, shared with the component page), the
  symbol/footprint renders on the right, Prev/Next walking the FILTERED list.
  The datasheet is a LINK that opens in a tab, never a frame — it was embedded
  until 2026-09-14 and pushed the checks off the screen. Links inside a row must
  `stopPropagation()` — the row itself is the expand toggle. The template
  tabs sort by `used_by` (leverage) before name; keep that ordering, it is
  the point of the column. "Queue shown → agent" files review requests;
  "Confirm agent checks" is the bulk human confirmation.
- **`pages/Checklists.tsx` is ONE `DataTable` of every check in the platform**,
  one row per (scope, check), with a filter on every column. It took three
  attempts to get there and the first two are the lesson: one sidebar entry per
  checklist became sixteen entries once every category stated rules; one tab per
  kind with a scope dropdown fixed that but still showed one scope at a time, so
  "which categories change `cmp.required_props`, and for which transistor types"
  meant opening scopes one by one. Sorting by Key now lines a check up with
  every override of it, and Scope / Applies when / Runs are filters. **Both
  earlier shapes hand-rolled their own table with their own filter chips, which
  is exactly what this file's own DataTable rule forbids** — that is how the
  filtering ended up weaker than the browse page's.
- **A new check is added in the FIRST ROW, not from a toolbar.** The draft row
  carries the same seven columns with Kind, Scope, Key and the text editable in
  place, and `DataTable`'s `group` pins it first whatever the sort — that is
  what `group` is for. It replaced a scope dropdown and an Add button above the
  filter row, which read as a filter for the table and split "which scope am I
  adding to" from "what am I adding" into two questions. A column filter hides
  the draft row like any other, which is right: filtering is looking, not
  adding. Controls inside it `stopPropagation()`, because the row click belongs
  to the expansion.
- **A judgment check can be turned into a DECLARATIVE one in its own panel** —
  "Make it automatic" swaps the text boxes for a fact, an assertion and a value.
  There is deliberately no text box on a declarative check: its sentence is
  generated by the API from the rule, because a sentence typed beside a rule can
  disagree with it.
- **Rows are what a scope STATES, not the cross product.** Sixteen component
  checks against nineteen scopes is three hundred rows of "not stated". The base
  lists state everything, so the catalogue is covered; a category contributes
  only what it changes. `GET /api/checklists/all` serves it.
- **Publishing is PER SCOPE, and the button says how many.** A checklist version
  belongs to one scope, so editing rows from three scopes writes three versions.
  Silently publishing three documents from one button is the kind of thing
  nobody forgives; the toolbar names the scopes before you press it and the
  notice names the versions after.
- **A scope is addressed by (kind, category), never by checklist id** — the id
  does not exist until the scope states something.
  `GET/PUT /api/checklists/scope?kind=&category_id=` creates the row on the
  first save and DELETES it when a save leaves it empty, because "adds nothing"
  and "has an empty list" must not be two states.
- **The editor is where the validator is CONFIGURED, not just switched on.**
  Automatic rows come from `validator.machine_checks` through
  `/api/checklists/meta`: their wording is never typed here — the API rewrites
  it on save from the row's own `params` — but the params themselves are edited
  in the folded detail. That is where the `rules` table went; a category states
  its own by putting the item on a category-scoped list. Full rules in the
  `pages/Checklists.tsx` docstring and decisions
  [0013](../../../docs/decisions/0013-the-validator-owns-the-automatic-checks.md)
  and [0014](../../../docs/decisions/0014-a-check-carries-its-own-configuration.md).
- **In "Datasheets & files", OUR archived copy is the button and the supplier
  URL is a word.** The row used to give the supplier URL a `flex: 1` lane and
  the local copy a small "local copy" link, which put the visual weight on the
  link you should almost never click — supplier URLs rot, and the archived PDF
  is the one KiCad itself is pointed at. So: `.ds-file` carries the icon,
  the filename and the stored version; `.ds-origin` is the word "original"
  with the full URL only in its `title`, pushed right by `.ds-gap`.
  Beside them sit `.ds-revision` (the revision label parsed out of the
  document — "Rev. B", "SLVSF14B" — absent when nothing parsed) and
  `.ds-shared` ("shared with N", the other components whose current copy is
  the very same stored file; both come from `DatasheetRow`).
  **`.ds-row` wraps, and must keep wrapping.** The row carries a variable
  number of chips and the card is a narrow column; without `flex-wrap` the
  file button is squeezed until its name disappears behind the chip after it,
  which is exactly what adding these two did before the wrap.
- **`TextLayerTag` (in `ComponentDetail.tsx`) reads `text_layer` — never
  computes it.** Green `OK` is a searchable PDF, amber `partial` / `no text`
  are not, red `unreadable` is a file that would not open. `none` (a DXF, a
  STEP file, an archived web page) and `""` (the backfill has not reached it)
  render NOTHING — a file with nothing to search is not a defect, and an
  unclassified one is not an answer. The label says "no text" rather than
  "scan" on purpose: some are vector drawings exported without a text layer,
  not raster scans, and a tag people act on must not name the wrong cause.
- **A preview URL must carry the version: `templatePreviewUrl(kind, id, versionId)`.**
  Without it the URL is the same for every version of a template, so a browser
  — or an `<img>` already mounted — has no reason to refetch and a freshly
  pushed land pattern keeps showing the old picture until a hard reload
  (reported 2026-08-24: D_SOD-323's pads went 0.6x0.45 -> 0.7x0.7 and the
  image did not move). With it the server answers `immutable` for a year, which
  also stops re-rendering the most expensive GET in the app. Every payload that
  feeds a preview now carries `version_id` beside `version_no`.
- **The Reviews queue refetches on window focus** and has a Refresh button:
  pushing from KiCad changes its data behind its back, and returning to the
  browser is exactly when it is read.
- **`dialog.select`** exists alongside confirm/prompt/alert — a fixed radio
  set resolving the chosen value or null. Use it where a preset beats free
  text (the skip-reason codes were the first user).
- **"← Back" means BACK, not UP: use `BackLink` from `components/Ui.tsx`.**
  A plain `<Link>` to a parent page is wrong on any page you can arrive at from
  more than one place — opening a footprint from a component and pressing Back
  landed on the footprint LIST, losing the component you were verifying.
  `BackLink` calls `navigate(-1)` when `window.history.state.idx > 0` and falls
  back to its `to` for a directly-opened page, which also keeps a real href for
  middle-click. `to` stays required.
- **A run is edited only on `/runs/:id`** (`pages/RunDetail.tsx`): the Batch
  card (label, quantity planned, devices produced, run date), status, the
  design commit, notes, overrides, materials, costs, files, serials. The
  project Runs tab is a plain list. Do not add run-editing UI anywhere else.
  **That sentence has to stay literally true, and it was not.** The page
  claimed every `PATCH /api/runs/{id}` field was editable here while `label`,
  `qty`, `run_date` and `qty_good` had no control anywhere in the app — so a
  batch opened for 50 could not be corrected to the 60 that were built, and
  the only way to change one was the API (user report 2026-09-22). Adding a
  field to `RunPatch` means adding it to the Batch card, or writing in that
  file why not. The SALE fields are the standing exception: a batch shows
  costs, the ORDER carries revenue (decision 2026-09-19).
  **A figure that MONEY is divided by is edited behind a guard, with Save and
  Cancel** (user request 2026-09-22). The Batch card reads as a `dl.kv` of
  facts and turns into a form only on "Edit…"; nothing is sent until Save, and
  Save is disabled until something differs. Two reasons it is not a row of
  live boxes. `qty` and `qty_good` are the denominators every per-device cost
  is divided by and that cost has already gone out on orders, so a value that
  changes while you tab past it is the wrong affordance. And
  `NumberInput.onChange` fires per keystroke, so a box wired straight to a
  PATCH writes qty 6 on the way to typing 60 — two audit rows and a moment
  where the batch really was 6. The patch carries only the fields that
  DIFFER, so the audit row names the edit rather than the whole form.
- **Batches have TWO lists and they answer different questions.**
  `components/project/RunsTab.tsx` is "what has this product built", and it
  creates and deletes. `pages/Runs.tsx` (Production → Batches,
  `/production/runs`, `GET /api/runs`) is "what is in production anywhere" —
  every batch across every project, and it creates nothing, because a batch
  needs a project's snapshot and board. Both are labelled **Batches**; the
  route is `/production/runs` to match `/runs/:id`.
  It is NOT the Overview's "What each batch cost": that table is money and is
  built from the invoice register, so a batch nobody had billed was missing
  from it. This one is the batches themselves — status, quantity, devices
  recorded, whether the books are closed — and it links to Overview for the
  cost rather than printing it again.
- **Money formatters live in `src/format.ts`** (`usd`, `amount`, `price`,
  `plain`). Never declare a local `money()` — there were eleven copies once,
  and they drifted.
- **Cost-domain primitives live in `components/costs.tsx`**:
  `COST_LINE_KINDS`, `<StepSelect>` (step catalog grouped by stage),
  `<ChargeToSelect>` (run/project/excluded destination). Reuse, never copy.
- **The PROJECT page's tab is in the URL too, and its Devices tab takes
  filters.** `/projects/:id?tab=Devices&state=in_stock&condition=faulty` shows
  those devices and nothing else; `getProjectDevices` has taken `state` and
  `condition` since it was written and the tab simply never passed them, so a
  link could say which project but not which devices. The sticky value is the
  fallback for a bare visit, arriving by link makes that tab the remembered
  one, and leaving the Devices tab drops the two filters from the URL — a
  narrowing nothing on screen explains is worse than none. The tab NAMES the
  narrowing in a pill with a "Show every device" button beside it, because a
  list quietly showing a tenth of the devices reads as a list of all of them.
- **Tab state goes in the URL** (`?tab=`, see RunDetail/Templates/Admin),
  selection state that should deep-link goes in the path
  (`/library/skills/:id`). `useStickyState` is only a fallback for bare visits.
  A link from another page that means one panel names it —
  `/admin?tab=rates`, not `/admin`.
- **Each number has one home.** Run economics render on the run page and the
  Production overview; stock figures on Production → Stock. Link there
  instead of re-rendering a figure on a new surface.
- **The Invoices document list is a `DataTable`, and the ROW is the toggle.**
  It was the last hand-rolled `<table className="data">` on a main page — no
  sort, no filters, and a Lines button as the only way to open a document, on a
  list that had grown to 88 rows. The positions now open by clicking anywhere on
  the row (`expand`, with `openKey`/`onOpenChange` so the open document survives
  navigation in `useStickyState`), and `DataTable` only calls `expand` for the
  open row, which is what keeps one document request from firing per row.
  `stateOf()` returns the ONE word the State column sorts and filters on, and
  the cell draws its pill from that same answer — so typing "unassigned" finds
  exactly the rows showing that pill. Its `.invoices-table` width rules were
  deleted with it: `DataTable` takes widths from `Column.width` and carries its
  own `row-expansion` styling.
- **The shelf has TWO cuts and one source each; neither re-derives the other.**
  Production → **Stock** (`components/FinishedProductsCard.tsx`,
  `GET /api/finished-products`) is per PRODUCT and counts the DEVICE RECORDS.
  Production → **Orders** ("Devices on the shelf", `GET /api/finished-stock`)
  is per BATCH and counts per run. The difference is load-bearing: a device
  that names no batch is invisible to every per-batch figure, and 13 were on
  the real shelf on 2026-09-21 — the platform reported 93 devices while
  holding 106. Such a device is stock and is NOT valued (per-device cost
  belongs to a batch), so it is counted in `no_batch` and the card says so in
  a banner rather than averaging it in.
  A product row opens into its CONDITIONS, and each links to
  `/projects/:id?tab=Devices&state=in_stock&condition=…` — the exact devices
  the number counted, as serials.
- **Supply is what can be SOLD.** The demand card's column is "Sellable now"
  and counts condition `ok` only. A faulty or prototype unit is on the shelf
  and a shipment may never draw it (decision 0032), so counting it against
  open demand says an order can be filled by devices that cannot leave the
  building — it read 34 dongles of supply against 0 sellable ones (user
  decision 2026-09-21).
- **Orders live on Production → Orders** (`pages/Orders.tsx`,
  `pages/OrderDetail.tsx`, decision 0003). Its shelf card counts
  RECORDED DEVICES and nothing else — a batch with no device records is built
  0, whatever quantity is typed on it, and the "No serial" column that used to
  hold the difference is gone (decision 0049). Stock splits into
  `devices_available` and `devices_held`: only a device whose `condition` is
  `ok` may ship, so a faulty or prototype unit is counted and visible but
  never picked (decision 0032). **That card lists
  every batch that was built, empty or not** — it filters on `r.status`
  (planned batches hold nothing yet) and NEVER on what is left on a row.
  Selecting by what a row still holds deleted six of seven dongle
  batches from the page the day `built` started counting passed devices
  instead of the typed run quantity (decision 0007), because everything they
  held had shipped. A batch is a fact; its remaining stock is a number on it.
  `Recorded` sits beside `Built`, and `overbuilt()` marks a row where built is
  above recorded. Under-building is ordinary attrition and is not marked. **The Ship card takes SERIALS ONLY** — no quantity, no batch picker,
  because a number with no device behind it is a guess (decision 0032). Its
  batch table is read-only, there to show the shelf while you scan; returns,
  repairs and disposals are on the DEVICE page (`components/DeviceHistoryCard.tsx`),
  because they are events in a device's history. The run page's sale card
  stays until the register reads the orders; it now points at the order.
  **There is no stock-count card any more** (decision 0032): nothing corrects
  stock automatically, because a mechanism that removes guesses by writing new
  ones is not a correction. `parseScanSheet` stays and decides nothing — it
  strips a scanner's CSV export, and the SERVER names any code that is not a
  device rather than shipping a short list.
  A delivery recorded in error is taken back on its row, never deleted, and the
  `×` follows `sh.deletable`, NOT `sh.devices.length` — a reversed shipment
  carries no device but still carries events. Ship takes scanned serials now.
  The project window has an **Orders tab** (`components/project/OrdersTab.tsx`):
  read-only, one row per order line of that project, headed by the demand
  card (`DemandCard` in `pages/Orders.tsx`, from `GET /api/demand`) — open
  quantity against the shelf and the planned batches. Both surfaces share
  the one component so the figure has one rendering.

