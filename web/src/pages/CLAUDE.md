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
endpoint. Setup keeps a pointer.

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
  inline (`components/ReviewWorkbench.tsx`): ReviewCards on the left, the
  archived datasheet in an iframe plus the symbol/footprint renders on the
  right, Prev/Next walking the FILTERED list. Links inside a row must
  `stopPropagation()` — the row itself is the expand toggle. The template
  tabs sort by `used_by` (leverage) before name; keep that ordering, it is
  the point of the column. "Queue shown → agent" files review requests;
  "Confirm agent checks" is the bulk human confirmation.
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
- **Tab state goes in the URL** (`?tab=`, see RunDetail/Templates), selection
  state that should deep-link goes in the path (`/library/skills/:id`).
  `useStickyState` is only a fallback for bare visits.
- **Each number has one home.** Run economics render on the run page and the
  Production overview; stock figures on Production → Stock. Link there
  instead of re-rendering a figure on a new surface.
- **Orders live on Production → Orders** (`pages/Orders.tsx`,
  `pages/OrderDetail.tsx`, decision 0003). The Orders page is also the ONE
  home of finished-device stock ("Devices on the shelf"), which counts
  recorded devices next to legacy units without a serial. **That card lists
  every batch that was built, empty or not** — it filters on `r.status`
  (planned batches hold nothing yet) and NEVER on what is left on a row.
  Selecting by `stock > 0 || overdrawn > 0` deleted six of seven dongle
  batches from the page the day `built` started counting passed devices
  instead of the typed run quantity (decision 0007), because everything they
  held had shipped. A batch is a fact; its remaining stock is a number on it.
  `Recorded` (`qty_recorded`, what the run says) sits beside `Built` (devices
  that passed), and `overbuilt()` marks the row when built is above recorded —
  the one impossible arithmetic left, since a device-tracked batch can no
  longer report `overdrawn`. Under-building is ordinary attrition and is not
  marked. The Ship card
  draws devices oldest-first from the batches the user ticks; returns,
  repairs and disposals are on the DEVICE page (`components/DeviceHistoryCard.tsx`),
  because they are events in a device's history. The run page's sale card
  stays until the register reads the orders; it now points at the order.
  The project window has an **Orders tab** (`components/project/OrdersTab.tsx`):
  read-only, one row per order line of that project, headed by the demand
  card (`DemandCard` in `pages/Orders.tsx`, from `GET /api/demand`) — open
  quantity against the shelf and the planned batches. Both surfaces share
  the one component so the figure has one rendering.

