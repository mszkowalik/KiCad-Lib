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
- **A run is edited only on `/runs/:id`** (`pages/RunDetail.tsx`): status,
  sale (price/device, qty_good…), notes, overrides, materials, costs, files,
  serials. The project Runs tab is a plain list. Do not add run-editing UI
  anywhere else.
- **Money formatters live in `src/format.ts`** (`usd`, `amount`, `price`,
  `plain`). Never declare a local `money()` — there were eleven copies once,
  and they drifted.
- **Cost-domain primitives live in `components/costs.tsx`**:
  `COST_LINE_KINDS`, `<StepSelect>` (step catalog grouped by stage),
  `<ChargeToSelect>` (run/project/excluded destination). Reuse, never copy.
- **Tab state goes in the URL** (`?tab=`, see RunDetail/Templates/Admin),
  selection state that should deep-link goes in the path
  (`/library/skills/:id`). `useStickyState` is only a fallback for bare visits.
  A link from another page that means one panel names it —
  `/admin?tab=rates`, not `/admin`.
- **Each number has one home.** Run economics render on the run page and the
  Production overview; stock figures on Production → Stock. Link there
  instead of re-rendering a figure on a new surface.
- **Orders live on Production → Orders** (`pages/Orders.tsx`,
  `pages/OrderDetail.tsx`, decision 0003). The Orders page is also the ONE
  home of finished-device stock ("Devices on the shelf"), which counts
  recorded devices next to legacy units without a serial. Stock splits into
  `devices_available` and `devices_held`: only a device whose `condition` is
  `ok` may ship, so a faulty or prototype unit is counted and visible but
  never picked (decision 0032). **That card lists
  every batch that was built, empty or not** — it filters on `r.status`
  (planned batches hold nothing yet) and NEVER on what is left on a row.
  Selecting by `stock > 0 || overdrawn > 0` deleted six of seven dongle
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

