# Platform Web (`web`)

React + TypeScript + Vite frontend for the Project Management Platform. Talks to the
API at `api`. Routing is in `src/App.tsx`; pages live in `src/pages/`,
shared pieces in `src/components/`, and the typed API client is `src/api.ts`.

## Reuse the existing style system — do NOT create new styles

This is the most important rule for this directory. The UI has **one** global
stylesheet, `src/styles.css` (~190 classes, one CSS-variable palette, full
light/dark theming). New work must **reuse** it. When you build a screen or
component:

- **Reuse existing classes** before writing any CSS. There is almost certainly
  already a class for what you need (card, button, table, pill, banner, form
  field, layout region — see the inventory below). Match an existing screen that
  looks like what you're building and copy its markup + classes.
- **Never hardcode colors, fonts, spacing tokens, or radii.** Use the CSS
  variables: `var(--bg)`, `var(--surface)`, `var(--surface-2)`, `var(--text)`,
  `var(--muted)`, `var(--line)`, `var(--accent)` / `--accent-soft`,
  `var(--copper)` / `--copper-soft`, `var(--ok)` / `--warn)` / `--err)` (+ their
  `-soft` fills), `var(--mono)`, `var(--sans)`, `var(--radius)`. Raw hex codes,
  `px` colors, or a second font stack are not allowed in components.
- **Avoid inline `style={{…}}`.** Inline styles bypass the theme and the design
  system. Use a class. Only exception: a genuinely dynamic value that can't be a
  class (e.g. a computed width percentage) — even then, reference a CSS var.
- **Add a new class only as a last resort**, when nothing existing fits. If you
  must, add it to `styles.css` (not a new stylesheet, not a CSS module), build
  it from the variables above, place it near its siblings, and make sure it
  works in **both light and dark** (the palette flips via
  `@media (prefers-color-scheme: dark)` and `:root[data-theme=…]`). Prefer
  extending/generalizing an existing class over adding a near-duplicate.
- **Reuse the shared UI atoms** in `src/components/Ui.tsx` instead of
  re-implementing them: `<Spinner label?/>`, `<ErrorBanner message/>`,
  `<StatusPill status/>` (which already maps statuses → ok/warn/err tones — feed
  it `"draft"`, `"published"`, `"rejected"`, `"running"`, etc.). Other reusable
  components: `CategoryTree`, `ModelViewer`, and the form pieces in
  `components/editing.tsx`. **Notes/comments on anything** (component, symbol,
  footprint) use the shared `components/CommentsPanel.tsx`
  (`<CommentsPanel kind="components|symbols|footprints" id={n} noun="…" />`) —
  it wraps the generic `getComments/addComment/deleteComment(kind, id)` client
  fns; never re-implement the notes list/form.
- **EVERY list goes through `components/DataTable.tsx`** — sortable header,
  per-column filter row, fixed column widths with ellipsis (never scrolls
  horizontally), optional expandable rows, and chunked rendering. Pass
  `Column[]` defs with `width` (%), `numeric`, `render`, and
  `interactive: false` for action columns. Never hand-roll a
  `<table className="data">` with its own sort buttons and filter inputs —
  three pages had grown their own near-identical copies (Browse, Stock, the
  review queue) and they had already drifted. Extend DataTable instead.

  The props that matter, and why each exists:

  | Prop | For |
  |---|---|
  | `pageSize` | rows laid out per chunk (default 60); more are added as the reader nears the end. Filtering and sorting still run over the WHOLE `rows` array, so this never narrows what a filter can find |
  | `defaultSort` | the sort before the user touches a header |
  | `sortValue` (column) | sort key when it must differ from the printed text — the review and sign-off columns sort worst-first by RANK while their filter matches the visible word |
  | `expand` / `openKey` / `onOpenChange` | inline detail panel. Uncontrolled by default; pass `openKey` when the PARENT owns it (the review workbench steps Prev/Next from inside the open panel) |
  | `onRowClick` | click the row to open its page. Links inside must `stopPropagation()` |
  | `serverFilter` (column) / `serverSort` / `onServerFilters` / `onSortChange` | the table is a WINDOW on server-paged data, so its filter and sort must reach the server — see below |
  | `persistKey` | remember sort + filters across navigation (`useStickyState`) |
  | `onVisibleChange` | the filtered rows, for a toolbar acting on "everything shown" (the browser's bulk sign-off selects the FILTERED set) |
  | `footer` | where a server-paged list puts its own loading sentinel |

- **`onVisibleChange` compares CONTENT, and must keep doing so.** `visible` is
  a `useMemo` over `columns` and `group`, and every caller builds both inline —
  so both have a new identity each render, `visible` is a new array each
  render, and a naive effect calls back every render. The caller stores that
  array in state, which re-renders, which rebuilds `columns`. React caught it
  as "Maximum update depth exceeded" on all three review-queue tabs. The fix is
  the element-wise comparison in DataTable, not memoised columns in 12 callers.

- **Client chunking vs server paging — pick by data size, and be honest about
  filtering.** `components/useInfiniteScroll.ts` holds the shared trigger (an
  IntersectionObserver on a sentinel INSIDE the table, so a short list does not
  load everything at once; `busy` is as load-bearing as `hasMore`, or the
  observer asks for the same page three times). Two lists genuinely do not fit
  and page from the server — the change feed (keyset cursor) and the device
  list (offset) — and both mark their columns `serverFilter` and set
  `serverSort`, because a browser holding 100 of 5502 rows cannot honestly
  report "no rows match". Everything else fetches its set and renders it in
  chunks, which keeps filters instant and exact. A column whose filter cannot
  reach the server on a paged list must be `interactive: false` rather than
  offering a box that quietly searches one page.

### `.kv` names TWO designs — keep both selectors element-qualified

`dl.kv` is a two-column CSS grid (PartInfo, ProjectDetail, ComponentDetail).
`table.kv` is a plain table (SettingsCard, Setup's Effective URLs,
TemplateDetail). They were both written as bare `.kv`, so `display: grid` also
landed on every `<table class="kv">`: the `<tbody>` collapsed into a single grid
item, the rows lost table layout, and each table shrank to its content. The
Configuration card rendered its labels one word per line with every input about
50 px wide. Fixed 2026-07-31 by qualifying both. Never drop the element
qualifier, and never add a third meaning.

A related trap that made it worse: `.row-input` is `width: 100%`, so it
contributes **nothing** to a table's intrinsic minimum width. Any auto-layout
table whose value cells hold one will shrink to the width of its labels — give
such a table `table-layout: fixed` and explicit column widths (see
`table.kv.settings-table`).

### Class inventory (reuse these)

| Family | Classes |
|---|---|
| Buttons | `btn`, `btn-sm`, `btn-primary`, `btn-accent`, `btn-ok`, `btn-danger`, `btn-row` |
| Cards | `card`, `card-title`, `card-subtitle`, `meta-card`, `edit-card`, `live-card`, `prices-card`, `ds-card`, `danger-card` |
| Tables | `data`, `table-wrap`, `th-sort`, `sort-ind`, `filter-row`, `filter-input`, `clear-filters`, `cell-desc`, `cell-fp`, `cell-cat`, `row-del`, `empty` |
| Status / tags | `pill` (+ `ok`/`warn`/`err`/`neutral`), `badge`, `tag-hidden` |
| Banners | `banner-error`, `banner-ok`, `banner-warn` |
| Forms / inputs | `text`, `search`, `filter-input`, `row-input`, `note-textarea`, `chat-input`, `chat-textarea` |
| Layout | `browse`, `sidebar`, `main`, `main-solo`, `toolbar`, `toolbar-total`, `detail-page`, `detail-left`, `detail-right`, `edit-grid` |
| Text | `mono`, `num`, `muted`, `dim`, `comp-link`, `val-link`, `backlink` |

(Full list: `grep -oE '^\.[a-zA-Z][a-zA-Z0-9_-]*' src/styles.css | sort -u`.)

## Data access — reuse the typed client

All server calls go through **`src/api.ts`**. Do not call `fetch` directly from
a component. When you add an endpoint:

1. Add its request/response **interface** to `api.ts` (mirror the FastAPI
   router's shape).
2. Add a thin function using the existing `request<T>()` / `API_URL` helpers
   (they already handle `ApiError`, abort signals, and Pydantic error parsing).
3. Consume it from the page with the standard pattern seen across pages: an
   `AbortController` in `useEffect`, `errorMessage(err)` for messages,
   `isAbortError(err)` to ignore aborts, `<Spinner/>` while loading, and
   `<ErrorBanner/>` on failure.

### `request()` renders a structured refusal from `detail.error`

FastAPI routers may raise `HTTPException(400, detail={"error": "…", …context})`
so a non-browser caller keeps the machine-readable context. `request()` reads
`detail.error` for the message; without that branch an object detail matched
neither the string nor the Pydantic-array case and the user saw a bare
"400 Bad Request". Backend side of the contract: the `error` string must be
self-contained — never leave a fact only in a sibling key.

### Symbol/footprint geometry from the clipboard: `components/GeometryPaste.tsx`

**One widget covers all four cases** (symbol|footprint x edit|create) — the flow
is identical and a second copy would drift. A monospace textarea
(`text skill-textarea`) that also accepts a dropped `.kicad_mod`/`.kicad_sym`,
plus a required comment.

- **Edit** — pass `id` and `publishedSource`. `TemplateDetail` does this.
  `POST /api/{kind}/{id}/propose`; the name is never sent, so a paste cannot
  rename the template.
- **Create** — omit `id`. The `Templates` page does this, per tab. The server
  reads the name out of the pasted text, so there is no name field either.
  Pass `onFiled` to refresh the list: a creation makes the parent row and its
  first published version at once.
- **Preview before filing** — the Preview button POSTs to
  `/api/{kind}/preview.svg` and shows the render of the UNSAVED text. It returns
  an object URL, so revoke the previous one whenever it is replaced, and on
  unmount.

**It PUBLISHES.** There is no approval step anywhere in the platform any more
(2026-08-24), so the Preview button is the only look before the fact — say so
in the copy, and never write "draft" here again. The box also carries the
**minor-change waiver** (`minor_change`), the one control the deleted approve
dialog owned that had nowhere else to live: ticked, it carries the sign-offs
and verification records of every affected component across the new drawing
under the user's name; unticked sends `null`, and the server compares material
fingerprints instead. Default it to unticked — the safe answer is the one that
makes people look again.

**A footprint publish repoints its components by itself** (`services/repoint.py`),
so nothing here has to offer it. What the UI must show instead is the state a
repoint prevents: `PinnedRef.is_current === false` on the component page, which
renders as "library serves v5" beside the pinned version.

### The API is same-origin — `API_URL` defaults to `""`

`API_URL` in `src/api.ts` is a **path prefix**, and its default is the empty
string. In the deployed image nginx serves the SPA and proxies `/api`, `/kicad`
and `/files` to the api container (`web/default.conf.template`, whose
`${API_UPSTREAM}` is substituted at container start so a stack sharing a docker
network can point at a prefixed service name); `npm run dev` proxies the
same paths (`vite.config.ts`, target `VITE_API_PROXY`). Vite inlines
`VITE_API_URL` at **build time**, so an absolute default would tie one image to
one hostname — set `VITE_API_URL` only to aim a build at another origin.

Two consequences when you touch this:

- **Never test a string against `API_URL` with `startsWith`** without checking
  it is non-empty first: every string starts with `""`. That is why
  `viewkind.fileHref` guards the prefix test — without it, external datasheet
  URLs were treated as ours and routed into the local viewer.
- Show `apiOrigin()`, not `API_URL`, in anything the user reads. `API_URL` is
  `""` for a same-origin build, which reads as a blank in an error message.

### Sign-in: the gate replaces the app, it is not a route

`AuthGate` (`src/auth.tsx`) wraps the router in `App.tsx`. Until `/api/auth/me`
answers, **nothing** renders; if the answer is "nobody", `pages/Login.tsx`
renders INSTEAD of the router.

- **Not a `<Route path="/login">`.** A route would mount the shell first, so a
  signed-out visit fires a request per screen and paints an error banner per
  panel before the form appears. It also means a deep link survives sign-in: the
  URL never changed, so the router picks it up once the user exists.
- **`Shell` holds the app** and must stay free of background fetches: anything
  in `App` would run anonymously on every visit, and anything in `Shell` runs on
  every page. (It used to poll `/api/proposals` for a nav badge; that queue is
  gone.)
- **Any 401 from any endpoint drops back to the form.** `api.ts` exposes
  `setUnauthorizedHandler`, which `AuthGate` registers once. `/api/auth/*` is
  excluded from that hook: a wrong password is a 401 the login form itself must
  render, not a reason to re-mount.
- **`request()` sends `credentials: "include"`.** The session is a cookie and a
  dev server aimed at a remote API is cross-origin. This is why `CORS_ORIGINS`
  is an explicit list — the CORS spec forbids `allow_credentials` with a
  wildcard, so a `"*"` there silently breaks the dev login.
- **No sign-up link and no password-reset link, ever.** The API has no endpoint
  for either (user decision 2026-07-31). Accounts and resets live in
  `components/UsersCard.tsx` on the Setup page, admin only.
- **`useAuth().isAdmin` is true when auth is DISABLED.** A dev box with
  `AUTH_ENABLED=0` has no user to ask, and the API takes the same posture — so
  gate admin UI on `isAdmin`, never on `user?.role === "admin"`.

## Conventions

- **Pages** are route targets (`src/pages/`, wired in `App.tsx`). **Reusable
  UI** goes in `src/components/`. Don't duplicate a widget across pages — lift it
  into `components/`.
- **File references** in code and the API mirror the backend field names exactly
  (e.g. `mfg_pn`, `manufacturer`, `category_path`) — keep the TS interfaces in
  sync with `api/app/routers/*`.
- **Typecheck** before declaring done: `tsc --noEmit` must pass (node is under
  nvm here — `~/.nvm/versions/node/v22.19.0/bin`).
- The dev server is Vite with HMR (`npm run dev`, port 5173) — component edits
  hot-reload without a restart.
- When a non-obvious frontend convention emerges, record it here.
- **No per-property visibility UI.** KiCad field visibility is curated on the
  base symbol, never per component (see `api/CLAUDE.md`). The property editor
  has no Hide checkbox and the views show every parameter plainly. `EditRow`
  and the POST body still carry `hide`/`show_name`/`layout` untouched — they
  round-trip the dormant DB columns; do not resurface them as controls.

### Production sign-off is NOT a status — never render it with `StatusPill`

"Published" and "signed off" are different claims: a published component may
never have been checked by a human (see the sign-off section of
`api/CLAUDE.md`). So the state has its own atom, `<SignoffPill state/>` in
`components/Ui.tsx`, its own vocabulary (`signed` / `re-check` / `revoked` /
`not signed`) and its own colours. On `ComponentDetail` the two pills sit side
by side in the header, and `SignoffCard` is deliberately a separate card from
the meta card that shows "Approved by". Do not merge them, and do not add
sign-off states to `STATUS_TONES`.

- **`SignoffCard` asks for its note INLINE, not through `dialog.prompt`.** The
  prompt dialog refuses to resolve on empty input, so an OPTIONAL note asked
  that way leaves the user unable to say "nothing to add". A revoke DOES use
  `dialog.prompt`, because there a reason is required and that is exactly the
  dialog's behaviour.
- **`RecheckDialog` is its own overlay because the answer is three-way** —
  re-check / carry the sign-offs / cancel — and `dialog.confirm` cannot express
  it (its cancel and its "no" are one boolean). It reuses the `modal-backdrop`
  / `modal-card` classes. **It focuses its suggested button on mount**: the
  Escape handler sits on the backdrop's `onKeyDown`, which never fires while
  focus is on `document.body`, so without that focus the dialog could not be
  dismissed by keyboard at all. Any new overlay built this way needs the same.
- **A pill is `inline-block`, so a column's ellipsis cannot shorten it** — too
  narrow simply cuts it off with no visual hint. The browse table's sign-off
  column is sized for the longest label. Check the rendered width when you add
  a pill to a `table-layout: fixed` column.
- The browse filter matches the PRINTED label, not the API's state string
  (`SIGNOFF_TEXT` in `Browse.tsx`), so typing "re-check" finds the stale rows.
  Sorting that column uses rank order (worst first), not alphabetical — sorting
  by it means "show me what still needs looking at".

### Site structure (UI overhaul, 2026-07-29)

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
  recorded devices next to legacy units without a serial. The Ship card
  draws devices oldest-first from the batches the user ticks; returns,
  repairs and disposals are on the DEVICE page (`components/DeviceHistoryCard.tsx`),
  because they are events in a device's history. The run page's sale card
  stays until the register reads the orders; it now points at the order.

### Attachments open in a viewer, never as a download

Link file attachments through `viewkind.fileHref(path, filename)` with
`target="_blank"`: it routes PDFs to the browser's own viewer and CAD/mesh/image
formats to the `/view` page, and only falls back to a plain link for formats
nothing can render. For API-served bytes, pass the same-origin PATH (e.g.
`attachmentPath(id)` → `/api/run-attachments/3?inline=true`), not an absolute URL —
`fileHref` needs to recognise it as ours. The `inline=true` flag makes the API send
`Content-Disposition: inline`; without it the browser saves the file to Downloads
instead of showing it (user preference, 2026-07-27).

### No native browser popups — use the in-app dialog system

Never call `window.confirm` / `window.prompt` / `window.alert` (or the bare
globals) anywhere in the platform. All confirmations, small text inputs, and
error notices go through the promise-based dialog system in
`src/components/Dialog.tsx` (`DialogProvider` is mounted once in `App.tsx`):

```tsx
const dialog = useDialog();
if (!(await dialog.confirm("Delete run X?", { title: "Delete run", confirmLabel: "Delete", tone: "danger" }))) return;
const name = await dialog.prompt("New skill name:", { title: "New skill" }); // null = cancelled
await dialog.alert(errorMessage(err), { title: "Adding the file failed" });
```

- `tone`: `"danger"` for destructive/discard actions, `"ok"` for approvals,
  default `"primary"` otherwise.
- Handlers become `async` — awaiting the dialog in an `onClick` is fine.
- Styling lives in `styles.css` under the “modals” section (`.modal-backdrop`,
  `.modal-card`, …) using the `--scrim` / `--modal-shadow` palette variables;
  reuse the same classes for any future overlay instead of new ones.

### Every table: fixed layout, no horizontal scroll, single-line rows

This is a hard rule for **all** tables in the platform — not just BOM/costs or
the component browser. **No table may scroll horizontally, and no row may fold
to fit its cell contents.** Every row is exactly **one line of text tall**; long
values truncate with an ellipsis, they never wrap.

Why: `table.data` defaults to `table-layout: auto`, so a single long value in an
unclamped column (a verbose name, a long MPN, a comment) widens that column for
every row, pushing the whole table past its `.table-wrap` container into a
horizontal scrollbar — even though most rows would fit fine. Per-cell
`max-width` classes (`cell-desc`, `cell-fp`, `cell-cat`) help but don't
guarantee the *sum* of columns fits the container.

The fix for any table (add it when you create the table, don't wait for it to
overflow):

1. Add a table-scoped modifier class (e.g. `jlc-stock-table`, `browse-table`,
   `users-table`; see `styles.css`) and give it `table-layout: fixed` plus
   `nth-child` width percentages summing to **100%**.
2. Apply `overflow: hidden; text-overflow: ellipsis; white-space: nowrap` to
   every `th`/`td` — the shared `.data-fixed` helper does exactly this, so
   `className="data data-fixed <your-modifier>"` and the modifier only carries
   the widths. Reuse `.data-fixed` rather than re-declaring the ellipsis rules.
3. Add a `title` attribute with the full value on any cell that can truncate, so
   the hidden text is available on hover.
4. If one row genuinely must break the clamp (e.g. the full-width `colSpan`
   expansion row in the users table), opt *that cell* out with
   `white-space: normal; overflow: visible` — never relax the whole table.

Compound selectors (`.data.users-table td:nth-child(n)`) are needed to
outrank existing width rules such as `.data td.ctr { width: 1% }`.


### The invoice line "charge to" cell mirrors `line_destination`, never re-derives it

The destination cell in the Invoices line tree must cover every branch the backend's
`run_actuals.line_destination` can take: header → "shares below", pooled part →
"pool", **spread carrier (`allocate` by_value/by_qty with no run/project) → "pool
(spread)"**, excluded → the select's "nobody, on purpose", else the run/project
select. A missing branch falls through to the select and reads "— nobody —" for
money that IS charged (a landed-cost transport line spread into part prices looked
unassigned, user report 2026-07-28). When a new `allocate` value or destination
appears in the backend, add its branch here in the same change.

### Flasher UI — where things live

- `src/flasher/station.ts` is the PORTED, HARDWARE-VERIFIED PoC (one USB
  adapter = one Station: esptool phase + monitor byte pipe). The transport
  rules in it are measured requirements (ESP32-C6 native USB: never call
  `setSignals()` in monitor mode; explicit reset pulse because esptool-js's
  `after("hard_reset")` is a no-op) — do not "clean them up".
- `src/flasher/runClient.ts` talks to the engine WebSocket: it executes
  `action` ops, pipes `tx`/`rx`, answers `prompt`s (SIM PIN modal) and
  forwards every station log line as `{t:"log"}` so the stored record is
  complete. The scenario itself NEVER runs in the browser.
- Pages: **`/production/deployments`** is the home of the flasher — three
  columns (deployments → version timeline → composed view of the selected
  version), with `Composer` for new versions and `DiffView` for comparisons.
  **`/production/files`** administers everything a version pins, one kind per
  tab (`?tab=bundles|firmware|files|parameters`) — bundles first, because that
  is the unit berryware ships in. `/production/artifacts` redirects there. Then `/production/bench` (stations),
  `/production/devices` (+ `/:id`), `/production/flash-runs/:id` (step
  timeline + full log, live-tails by polling `after=<last seq>`). The bench log
  box keeps a bounded tail — the full log is in Postgres.
- **The composer inherits by omission.** A section left untouched sends
  `undefined` and the backend inherits it from `from_version_id`; only touched
  sections are transmitted. Keep that contract — sending a section you did not
  edit turns "berryware bump" into a full rewrite of the version.
- **Validation comes from the server, always.** The composer PATCHes the draft
  and renders the returned `validation`; never re-implement a rule in the
  browser, or the editor will eventually disagree with the publish gate.
- **`StepEditor` renders the procedure in BOTH places** — editable in the
  composer, `readOnly` on a published version — from one schema
  (`stepSchema.ts`, keyed by op). Add an op there and both views get it. The
  read-only path takes its context from the version payload itself
  (`assetsOf` / `bundlesOf` in `VersionView`), so it needs no extra fetches;
  making a published procedure editable later is a flag, not a second view.
- **A flash step selects its firmware and a download step its bundle**, and
  both write the VERSION's pins. Keep it that way: the version stays the single
  definition of a payload (fingerprints, diffs and bundle identity all derive
  from it) — the step editor only puts the controls where the work happens.
- **Berryware reads as a BUNDLE, not a file list** (user feedback 2026-07-30).
  The version view and the composer lead with one pill — bundle name + file
  count, green for a named bundle and amber for an unnamed ad-hoc set — and put
  the file table behind a Show-files toggle. Deleting an artifact goes through
  the API's usage guard; surface the 409 text, never pre-filter in the browser
  (the backend knows every reference).
- The vite dev proxy has `ws: true` for `/api` — required by the run
  WebSocket; keep it when touching `vite.config.ts`.

### The "Planned as" column is the step EDITOR, not a label

Every non-header invoice line renders a step select (catalog from
`GET /api/cost-steps`, grouped by stage) writing `plan_key` directly; the
"link to a specific plan item…" option opens the old PlanLinkDialog for
free-form `c<id>` links. The split dialog carries the same select per row, and
picking a step back-fills the row's kind from the catalog default. The run
panel's "Where the money goes" table shows per-step plan-vs-billed with
supplier chips whose data comes from `RunActuals.steps[].sources` — computed
server-side in `run_actuals`, never re-derived in the browser.


### The change feed (`components/ChangesFeed.tsx`, `ChangeDetail.tsx`)

Reviews → "Recent changes": what moved in the library lately and who moved it,
newest first. Rows are cheap; `ChangeDetail` fetches a row's diff on mount and
is only mounted while that row is open. Never prefetch it — the feed carries
~18k events and rendering a symbol costs a kicad-cli invocation.

Each kind answers "what changed" in the terms it is edited in: components as a
property table, drawings as before/after renders plus their pin or pad rows,
skills as a text diff, events as their audit detail.

**The feed lists SUBJECTS, not individual changes.** A burst of agent work
writes a check, a carry and a publish against the same part within seconds, so
an ungrouped feed reads as a wall of near-identical lines with the one
interesting row buried in it (user report 2026-08-25: `LQW15AN2N2C10D` appeared
three times in fifteen rows). `groupRows` merges by NAME across everything
loaded — not just adjacent rows, because those three copies were seven rows
apart — and a group sits at its newest change, growing as older pages arrive.
The row advertises the member that carries a diff (a version publish outranks
an event, `KIND_RANK`); the unfold lists every member and fetches the diff for
the selected one only. A nameless event has no subject to group on and stays
its own row rather than being lumped in with every other nameless event.

### `GeometryDiff`: flatten each render before blending, or the diff lies

The difference pane draws both versions at ONE shared px-per-mm scale (kicad-cli
emits SVG sized in millimetres, so identical geometry then lands on identical
pixels) and blends them with `mix-blend-mode: difference` over black: unchanged
pixels go black, only movement lights up.

- **Each render is flattened against opaque black in its own `.diff-layer`
  first.** SVG strokes are anti-aliased, so their edge pixels carry partial
  alpha, and a partly transparent pixel differenced against the backdrop leaves
  `(1-a)·backdrop` behind instead of zero. Every outline and every glyph then
  glows on a comparison of a drawing with ITSELF. Verified 2026-08-25 by
  overlaying one version on itself: it must come out pure black, and without
  the flattening step it did not.
- **The layers are centred explicitly, not by the parent's flexbox.** An
  absolutely positioned flex child with `auto` offsets takes its static
  position, which laid the two layers side by side instead of stacking them.
- **The viewBox origin is the bounding box, not the footprint origin.** When an
  edit changes the bounding box the two renders are anchored differently and
  the overlay reports more than moved. The pane SAYS so rather than hiding it;
  it does not arise for the common cases (a pad resize inside an unchanged
  courtyard, a silkscreen width, a text move).

### `components/Viewer3D.tsx` takes a URL, not an entity

The GLB board view is reachable two ways — through a component version, and
directly from a footprint template — so the viewer knows about neither. It
fetches the GLB itself rather than handing `<model-viewer>` a URL, which is
what gives a clean 404 ("nothing pinned") and a spinner during the slow first
server render instead of a silently empty canvas.

**`.preview-fill` is `flex: 1`, so it only has a height when its parent gives
it one.** The component page's preview panel does; a plain card does not, and
the viewer collapsed to nothing on the template page. Pass a `className` with a
height (the template page passes `template-preview`).


### A PDF is framed from a BLOB, never from its URL (`components/PdfFrame.tsx`)

The shared nginx in front of this deployment sends `X-Frame-Options: DENY` for
every route it serves, and DENY forbids framing even by the same origin — so
`<iframe src="/api/datasheets/30/file">` rendered as the browser's
broken-document icon. Every PDF preview in the app was dead in production
(reported 2026-08-25 on the review workbench, where comparing the part against
its documentation IS the task). It worked on a bare dev server, which is
exactly why it went unnoticed.

`PdfFrame` fetches the bytes and frames a `blob:` URL instead: a blob the page
created carries no HTTP headers, so there is no `X-Frame-Options` to honour,
and same-origin credentials still apply to the fetch so the file stays behind
the auth gate. Both call sites go through it (`ReviewWorkbench`, `FileViewer`).
Never "simplify" one back to a plain `src`. The alternative fix — scoping the
header to SAMEORIGIN for `/lib/` — means editing an nginx config shared with
unrelated services, and nginx's `add_header` in a nested block replaces every
inherited one, so it would silently drop the other two security headers.

## ONE schematic renderer, everywhere (`src/sim/draw/`)

**Every view that shows a schematic goes through `SchematicView`** — the
project's schematic tab, the simulator overlay and the editor. Do not add a
fourth way to draw a sheet, and do not put a schematic behind an `<img>` again.
One renderer is why those three pages cannot disagree about where a part is or
what colour a wire has.

| File | What it is |
|---|---|
| `draw/types.ts` | the draw document `api/app/services/sch_draw.py` emits |
| `draw/geom.ts` | the placement matrix, arcs, text placement, pin geometry |
| `draw/KicadSheet.tsx` | the sheet as SVG — symbols, wires, labels, sheets, notes |
| `draw/SchematicView.tsx` | fit box, wheel zoom, drag pan, layer slots |

`SchematicView` owns the viewport and nothing else. Callers add what is theirs:
SVG `children` are drawn in the sheet's millimetres, `underlay` goes beneath
the drawing (the editor's grid), and `layers` gets the live viewport for
anything that cannot live inside an SVG — which is the simulator's charge
canvas, and only that.

**The viewport resets on `resetKey`, never on a content change.** An editor
that re-fits the page every time a part is placed moves the circuit out from
under the pointer between two clicks.

**A live run re-renders this page thirty times a second. Two rules follow.**
Both were found by a field that could not be typed into while a run streamed:

- **A text field in the inspector is UNCONTROLLED.** React rewrites a
  controlled input's DOM value on every render, and one of those rewrites
  lands between the keystroke and the change event — the character appears and
  is silently taken back. The field owns its text; the outside value reclaims
  it only when it changes and the field is not focused.
- **Never call `.focus()` from a ref callback.** A ref callback runs on every
  render, so a knob that focused itself took the cursor back off whatever the
  user had moved it to, continuously. Focus follows a CHANGE, once.

**Colours come from `/api/sim/theme`** — the same KiCad theme file kicad-cli
renders with (`api/app/services/themes/`, mirrored byte-identical into
`render/themes/`). Never hard-code a schematic colour, and never add a second
palette for one view. `FALLBACK_THEME` in `draw/types.ts` is that theme's own
values, so a failed fetch looks the same, not different.

The renderer was checked against `kicad-cli sch export svg` side by side on a
real 87-part sheet before it replaced it. Three things it had to be told,
because reasoning about them gave the wrong answer:

- **A field is drawn at its own angle PLUS the symbol's.** R157 (symbol 90,
  field 90) comes out horizontal and D29 (symbol 90, field 0) vertical.
- **A label's justification is already the one for the text AS DRAWN.** Do not
  flip it again for a 180-degree label — that lays every one across its wire.
- **Body lettering is drawn after the fills.** The `&` inside a gate is a
  library text item, and the filled body would cover it.

## The simulator overlay (`src/sim/`, `pages/Simulator.tsx`)

Layers share ONE coordinate space — millimetres, exactly as the `.kicad_sch`
stores them. Nothing here converts, scales or offsets a coordinate, and nothing
should start: the moment a transform appears, the current dots stop sitting on
the wires.

1. `SchematicView` — the sheet, with wires tinted by node voltage drawn into it
2. `<canvas class="sim-charge">` — the moving charge
3. `<svg class="sim-pick">` — the invisible thick click targets
   (`.sim-hit`, `pointer-events: stroke`) and, in live mode, the steerable
   parts (`.sim-part`)

**The charge is on a canvas on purpose.** A sheet with a few hundred wires
carries thousands of dots, and re-creating that many DOM nodes sixty times a
second is exactly what makes a page like this stutter. The canvas is redrawn
imperatively from a `clock` prop; React never re-renders for an animation
frame.

**Colours come from `color-mix`, not from arithmetic.** `--sim-hot`,
`--sim-cold` and `--sim-zero` are palette variables like everything else, and
a wire's tint is `color-mix(in oklab, var(--sim-hot) N%, var(--sim-zero))`.
That keeps the overlay theme-aware without a hex code in a component.

**`.pill` uppercases its text, and net names are data.** `/lowpass` is not
`/LOWPASS`, and the transform also turns the SI micro prefix into a capital M
(`204 µV` became `204 ΜV`). Any readout showing a net name or a measured value
opts out with `text-transform: none` — `.sim-legend-item` and `.sim-nets .pill`
already do.

**Crop to the drawing, not the page.** A KiCad sheet is mostly empty paper, so
`SchematicView` measures what the sheet actually uses and opens on that.
"Whole sheet" turns it off. Wheel zooms, drag pans, everywhere.

**In live mode you reach for the thing on the drawing.** A switch clicked on
the schematic flips there and then; anything else moves onto the knob panel
with its box focused. That is the point of the mode — a list of SPICE
instance names beside a circuit is not an interactive circuit.

**A flipped contact changes the drawing, not only the netlist.** `alter`
changes the run; the file still says what it said. `SimSheetView`'s `partSwap`
therefore swaps the symbol's `lib_id` AND the Value that goes with it — a
sheet the editor wrote embeds both blade positions, so the graphics are
already there. The altered values live on the page, not inside
`LiveControls`, because the drawing and the panel change the same number.

## A sketch has no edit mode, and it opens RUNNING

Falstad has no Edit button, and neither does a sketch any more: the tools are
always out, the page opens in Live, and Scenario is the mode you switch to
deliberately — the formal run, the harness, the verdicts. A project sheet's
schematic tab offers both doors: **Simulate** (scenario) and **Play live**
(`?mode=live`).

The click grammar that makes always-editing coherent (Falstad's own):

- **click** selects — a wire click also plots it, a pin click plots the
  terminal; neither has a drag gesture to collide with;
- **drag** moves;
- **double-click** opens the part dialog (Plot current lives in there now —
  plotting on every selection put a trace on the scope each time a part was
  picked up to move it).

Two rules with teeth:

- **Live edits never write a project file.** A sketch is scratch space in
  `sim_uploads/`; a sheet from a git project is read-only in live, knobs only.
  Download is the only way out of the playground, by design — the git checkout
  is the source of truth.
- **A pin dropped on the MIDDLE of a wire is connected** (`attach()` in the
  netlister, same rule as labels and junctions). That is what makes dragging a
  part onto a live circuit join it mid-gesture; the reload pipeline needs no
  drag-special-casing at all, because a reload only fires when the netlist
  STRUCTURALLY changed — a part floating in space between two connections
  produces no reloads, severing and rejoining each produce exactly one.

## Sketch live mode is a RELOAD, never a restart (`sim/edit/netlist.ts`)

The Falstad feel — edit the circuit while it runs, parts keep their state —
rests on three pieces, and each exists for latency:

1. **The browser netlists the document itself.** For a sketch we own every
   byte, so `netlistDoc` writes the SPICE netlist in under a millisecond and
   the start frame carries it — kicad-cli (the slowest step, QEMU-emulated on
   a Mac) is not in the path at all. Project sheets still go through
   kicad-cli; that file is not ours to reinterpret.
2. **An edit is `session.reload(...)`, debounced 120 ms.** Same worker, same
   websocket; the worker halts, swaps the circuit, and resumes. The session is
   created ONCE per live toggle — geometry refreshes and vector changes must
   not tear it down, or every autosave would restart the run.
3. **State travels on the components.** Each C and L card in a reload carries
   `IC=%IC_<ref>%`; the WORKER fills the token from its own last data point
   (cap voltage across its OLD nodes, inductor branch current) and `.tran uic`
   starts from there. Keyed to the reference, not the node — a charged cap
   unwired, dragged away and rewired elsewhere is still charged. `rshunt=1e12`
   keeps the floating island solvable in between.

Rules that were paid for:

- **Node names are lowercase from birth, and an edit REUSES the running run's
  names** (`reuse` callback: last netlist first, server geometry second — the
  geometry is a save behind during a burst of edits). One vocabulary across
  the netlist, the frames and the overlay, or traces die on every edit.
- **A name is claimed ONCE per build, biggest net first.** Reuse works by pin
  membership, and a pin that LEFT a net still remembers it — so a severed
  op-amp's floating output pin reclaimed `/ampout` while the labelled wire
  kept it too, SPICE merged the two same-named nodes, and the part went on
  driving a wire it was visibly not connected to (the drawing said severed,
  the voltage kept swinging). Labels and power names are claimed first; then
  nets in descending pin count, so the net that kept most of the membership —
  not a lone runaway pin — carries the name forward.
- **A label names the wire it sits ON, not the endpoint it touches.** People
  put labels mid-segment; joining labels only by endpoint coordinates renamed
  `/in` to `net-_u1-pad1_` silently — measured on the worked example itself.
- **Frame v2 carries its own overlay count.** A reload changes the overlay
  while frames closed against the old list are in flight; a frame must be
  sliced by what IT holds, not by what the config now says.
- The netlist names the model library by token (`%SIGMA_SIM_LIB%`); the render
  server substitutes the real path and refuses any other `.include`.

## Adding a dependency needs `--renew-anon-volumes`

The dev web container mounts `./web:/srv` and keeps the image's linux
`node_modules` behind an **anonymous volume**, so the host's macOS builds do not
shadow them. That volume survives `docker compose up --build`: the image gets
the new package and the container keeps the old tree, and Vite answers every
request with `Failed to resolve import`.

    docker compose up -d --build --force-recreate --renew-anon-volumes web

## The scope: stacked panes on one X axis (`sim/Plots.tsx`, `sim/panes.ts`)

Drawn by **uPlot** — 45 kB, no dependencies, canvas, built for tens of
thousands of points with a synchronised crosshair across several charts. The
hand-drawn SVG scope it replaced could not stack, redrew every path on every
frame, and had no cursor worth the name.

`sim/panes.ts` is the model and holds no React: a pane is one pair of axes, a
trace belongs to exactly one pane, and merge/split are list operations. Three
things are deliberately ours rather than uPlot's:

1. **The legend.** A row of pills carrying the statistics — value at the
   cursor, min…max, mean, rms, peak-to-peak, over the window ON SCREEN. Click
   the name to hide a trace, the × to drop it. Hiding is not removing: reading
   the trace underneath is not the same as being done with this one.
2. **The layout.** Panes are React, so stacking is a list and not a chart's
   internals.
3. **The band.** A live run sends a min-max COLUMN per pixel, so a live trace is
   a band between two hidden series with the mid-line over it.

Two traps, both measured:

- **A new trace goes in with its own UNIT.** Volts and amps on one pair of axes
  is a chart with two meanings and one scale, and the number that gets squashed
  is always the interesting one. Merge them by hand if that is what you want.
- **The cursor hook fires for a crosshair the PAGE moved too.** Reporting that
  back as a scrub stopped replay the instant it started — play moved the
  cursor, the hook called it a scrub, and a scrub pauses. It reports only while
  the pointer is over that chart.

## Voltage colour is a SCALE, not an autorange

Green above ground, red below, nothing at zero — Falstad's convention, and the
one every reader of a simulated schematic already knows. It saturates at a
reference the user picks (±10 V by default), NOT at the run's own extremes.
Autoscaling reads well on one circuit and lies on the next: a board whose
largest excursion is 40 mV of noise gets drawn in full colour, and the same
green then means 5 V on the sheet beside it.

`--sim-pos` / `--sim-neg` are that pair. They are not `--sim-hot` / `--sim-cold`,
which belong to the field solver and mean something else.

## Click a wire, a pin or a part — and get BOTH readings

A net has no current: ngspice reports device branches, never wires. A **wire**
does have one, and so does a **pin**, and both are reconstructed from the
currents around them (`sim/currents.ts`). So:

| Click | Voltage | Current |
|---|---|---|
| a wire | its net | that SEGMENT's own, `iw(<wire id>)` |
| a pin | the net it sits on | that terminal's, `ip(<ref>.<pin>)` |
| a part body | — | its branch, `i(@r1[i])` or `i(v1)` |

The two land in separate panes on one time axis, because volts and amps do not
share a scale. `Merge up` overlays them when that is what you want.

**A pin on a part with more than two legs is the interesting case.** SPICE
reports no per-terminal current for one, so an op-amp output would otherwise be
unplottable. The net around it names it: where a terminal is the only one on
its net whose current is unknown, conservation fixes it exactly. Where two are
unknown it cannot be named, and the pin plots its voltage alone rather than a
number nobody can stand behind — the same rule the charge animation already
followed.

Verified numerically on the worked example at one sample: `v(/ampout)` 0.9805 V,
`i(@r2[i])` −89.136 uA, the wire on that net +89.136 uA, and **U1 pin 5**
−89.136 uA — a reading that is in no rawfile.

These are not SPICE vectors and the names say so: `iw(` is a wire, `ip(` is a
terminal, `i(` is a device. On a finished run they are solved across the whole
of it, once, and only when one is on the scope; over a budget the run is sampled
at a stride and the gaps are straight lines. On a live run there is no history
to solve over, so one is kept: a probe is solved per FRAME into a ring buffer
the width of the scope, then put on the worker's column grid by time.

## Two bars, one drawing, and everything else closed

The simulator page is: a bar that says what you are looking at, the drawing, a
bar that says what will run and what it said, the waveform, and then reference
material behind disclosures.

It was not. There was ONE toolbar carrying the simulation, the sheet, the mode,
the view, the speed, the status, the plot name, the point count and Play — it
grew with the data and wrapped onto three lines — and under the drawing came
four full-width cards in a row: the knobs, "What to run" (a row of big buttons
per scenario, a second row per analysis, a form, Run, a verdict table and a
textarea), the scope, and the net list with the whole SPICE netlist inside it.

Rules that came out of fixing it:

- **A choice among a handful of named things is a menu, not a row of buttons.**
  The scenario and the analysis are `<select>`s in `sim/RunBar.tsx`, on one
  line with Run and the directive they build.
- **A form row appears only for an analysis someone chose.** "From the sheet"
  has no numbers to ask for, and an empty form under every run is furniture.
- **The verdict summary belongs on the run bar; the table belongs under the
  waveform** (`sim/Verdicts.tsx`). One is the answer at a glance, the other is
  the working.
- **Reference goes in `<details>`** (`sim/Disclosure.tsx`): the net list, the
  SPICE netlist, the control block, the off-drawing knobs. Each is something a
  person wants twice a day and never while reading a waveform.
- **Plot metadata sits with the plot.** Play, the point count and the duration
  moved off the top toolbar into the scope card's own head.

## The overlay is matched to the file by POSITION, never by list index

`useSimOverlay` draws the editor's own wires when there is a document, so the
tint lands on the wire the user is looking at rather than on the last save. It
used to pair the document's wires to the file's **by list index**, and drop the
whole overlay when the two lengths disagreed.

They always disagree. A document holds RUNS; a `.kicad_sch` holds one two-point
wire per segment (`sch_write._wires`), so one bend is enough to break the count.
On the worked example it is 26 runs against 36 wires — and "drop the overlay"
means **no tint, no charge dots and no clickable wires at all**, on every
circuit drawn in the browser, in every mode. That is what "nothing is animated
and I cannot select a net" was.

Match by position instead: a segment's two endpoints name exactly one wire in
the file. A segment the file has not caught up with goes untinted on its own
rather than taking the overlay with it.

## A live command sent before the socket opens is QUEUED, not dropped

`LiveSession.send` used to drop a command while the socket was still
connecting — and that is exactly when the page sends. The effect that creates
the session and the effect that tells it which scopes to watch run in the same
commit, microseconds apart and long before the handshake finishes. So a live
run opened with a trace already picked watched nothing at all.

Commands are now queued and flushed on open, after the start frame — the worker
reads that one first and refuses anything before it. It fixes `setSpeed` and
`alter` on the same path.

The other half of the same bug is in `render/sim_worker.py`: `set_scopes`
resolves its vector names against the run's index. A frame is keyed by the
run's own bare names (`/in`) while the rest of the platform speaks the wrapped
form (`v(/in)`), and only `on_init` used to resolve — so a scope set at START
worked and a scope set LATER, which is every trace the user clicks mid-run,
matched nothing and closed no columns. No error, just an empty plot.

## Audit findings, 2026-09-01 — the naming seams are where the bugs live

A sweep after the severed-op-amp bug, looking for the same disease elsewhere.
Fixed:

- **The diode card doubled its element letter.** `spiceName("D1")` is already
  `d1`; the card prepended another `d`. `dd1` ran fine — under a name the
  geometry does not know, so the diode's current, charge dots and alter were
  all dead. Any card built from `spiceName` must NOT re-prefix.
- **`liveReader.current` tried only the savecurrents spelling.** A source's
  current is its own branch (`i(v1)`), so every source read null in live
  mode, every source pin became an "unknown terminal", and the charge overlay
  and probe fallback quietly degraded.
- **Adding a capacitor or inductor mid-run killed the reload.** The browser
  measures carry-state on the circuit being REPLACED, so a brand-new part's
  `%IC_<ref>%` token had no state entry, reached ngspice unfilled, and the
  whole edited netlist was refused ("error" banner). The worker
  (`render/sim_worker.py`) now zero-fills every leftover token — a new part
  arrives uncharged, which is what adding it mid-run means.
- **A switch on a net zeroed every wire current on it.** The drawing says
  `SW1`; the run's element is `rsw1` (`Sim.Device` prefix). The current
  solver asked the run for `sw1`, got null, counted the switch an unknown
  terminal — two unknowns with the op-amp, and the whole net's segments came
  back 0. `currents.ts` now translates ref → element (`elementOf`, from
  `sym.spice`) everywhere it reads or names a current, `probeTerms` counts
  unknown terminals up front (a coefficient read off a pre-zeroed unresolved
  net is a silent 0, not a NaN), and the KiCad-sourced live overlay list asks
  for element-named currents too.
- **A dying transient froze the page at RUNNING.** ngspice aborts a
  background run (timestep too small, singular matrix) with no callback the
  worker listened to — frames just stopped. `sim_worker.py` now keeps
  ngspice's own output in a ring (`_on_char`) and a watchdog thread turns an
  unexpected `ngSpice_running() == False` into an `error` event carrying the
  last error lines. Deliberate halts (Hold, an alter's pause, a reload's
  swap) set `deliberate_halt` and stay silent; bg_run re-arms the watch, so
  fixing the circuit and reloading recovers the same session.
- **A severed terminal's current vanished instead of reading zero.**
  `solveSegmentCurrents` skipped wireless groups entirely, so a pin left on a
  floating one-pin net had no entry and its probe drew gaps. The injection
  accounting now runs for pin-only groups too — a lone unknown pin reads 0 by
  conservation, a pin-to-pin contact still resolves — so a disconnected
  current drops to zero the way a floating node's voltage does.
- **A speed change kept history at the old timebase.** Carried columns are
  sim-seconds-per-column; the carry now requires the pitch to match, and the
  worker's backlog (which resets on the same change) reseeds.

The circuit tab is a SPLIT that fills the window: `.sim-split` (height
measured from its top edge to the viewport bottom) holds the canvas slot
(flex:1) over `.sim-dock` (run bar + scope, natural height, scope card
scrolling internally past ~36vh) — schematic and waveform share one screen,
Falstad's one-window reading. `SchematicView` gained a `fill` prop for this:
instead of sizing the frame by the view's aspect (which shrank the drawing to
a stamp in a fixed-height slot), the frame fills the box and the VIEW is
padded to the box's aspect around its centre — the viewBox always fills the
frame, so the pixel-mapping layers (charge canvas, click targets) stay honest.
Wheel, pan and all mm mapping work in that `shown` window. The reference
drawer still sits below the split in page flow. The pixels go to the drawing,
Falstad's proportions: no page `<h1>`, the Circuit/Field-solver tabs share
the topbar row, `.page-sim` compacts card padding/margins and gaps to
hairlines, panes are 104px with the scope's status folded into the Plots bar row
(`head` prop — the `.sim-scope-head` row is gone) and a hairline legend, the
scope card caps at 34vh (sized so TWO compact panes fit unscrolled at 1080p), the canvas slot
never drops under 300px, and a sketch that already carries a circuit opens
FITTED (`openFit`, decided once per document uuid) instead of on the fixed
`OPENING_VIEW` working window. In LIVE mode the run controls (Hold, status,
Speed, the t/points readout) render `bare` inside the topbar beside the volt
scale and current slider — the dock carries a run bar only in scenario mode.
The `.sch-props` card under the canvas renders
only when it has something to say (a label/directive editor, or the how-to on
an EMPTY sheet) — as a standing hint it was the tallest decoration on the
page.

The measurement setup is STICKY per circuit: the scope panes, the picked net
and the live speed are `useStickyState` under `sim:<source>:*`, so a refresh
restores them (volt-ref and current-speed were already sticky, globally). The
post-run default trace seeds only an EMPTY scope for the same reason.

Editor interactions (SimulatorView): right-click opens `.sim-menu` (Copy /
Cut / Rotate / Mirror / Delete / Properties / Paste — Paste lands at the
click's mm, converted through `viewRef`); Ctrl/Cmd-C/X/V copy, cut and paste
the selected symbol (paste under the pointer, next free reference for its
prefix). A pointer-down that hits a part's body suppresses the pin-dot probe
under the same pixels (`downHit`), and `unconnected-*` nets are never added
to the scope — both stop an edit session flooding the plots. The probe
grammar is two-tier: a SINGLE click on a wire or pin only selects its net
(toggle); a DOUBLE click opens a chooser (`.sim-menu`) at the pointer —
Plot voltage / wire or pin current / both — wired overlay `onProbe` →
SimulatorView `probe` state → page `pickNet`/`pickPin` with a
`"v" | "i" | "both"` selector. A power
symbol's dialog edits its NET (the Value field), not the #PWR reference.

Known and accepted, so nobody re-finds them as surprises:

- Two different labels on one net: the browser picks the first in document
  order, kicad-cli may pick the other — that net's overlay readings can go
  dead until the names agree. Label a net once.
- A trace whose WIRE is deleted outright keeps its carried history as a
  frozen band until removed by hand (a severed wire or pin reads 0 instead).
- The overlay's net map (groups, pin membership) comes from the SERVER
  geometry, refreshed by the sketch autosave + re-parse — about a second
  behind the run. After a reconnect, current cannot be routed into the
  segment that ends at the rejoined pin until the map knows the pin is back,
  so charge beads there lag the rest of the sheet by that round trip.
- The raw `alter` box steers the RUN only; a sketch reload rebuilds from the
  document, so raw alters do not survive an edit (dialog edits do — they
  write the document).
- A subckt part's `i(@u1[i])` overlay vector never exists (subcircuits have
  no branch current); it is requested and ignored, by design.

## A trace opened late is seeded with its own PAST

The run has been solving since the session opened; only the scope was
forgetting it. The worker keeps a rolling one-window min/max history for every
overlay vector (`HISTORY_COLS` in `sim_worker.py`, a couple of MB at worst),
and a newly opened scope is seeded from it — so clicking a net five seconds in
shows the full window immediately, on the fixed time base, instead of a band
that takes one window-length to arrive.

The parts that keep it honest:

- **`backlog` is per scope and set by the browser** ("I hold no columns for
  this one"): re-sent scope lists — a speed change, a pane merge — keep their
  columns browser-side and must not receive them twice.
- **The speed knob changes the pixel pitch**, so a new `history_span` resets
  the history; old columns are at the wrong timebase.
- **Terms scopes (wire and pin probes) are seeded by interval arithmetic**
  over their components' rings — a positive coefficient maps lo->lo, a
  negative one swaps them. Conservative (a sum's true envelope can be
  narrower), but a column is microseconds of simulated time, the components
  move together at that scale, and an envelope a hair wide beats a current
  pane arriving one window after the voltage beside it. The rings share one
  edge grid, so aligning from the newest end is exact.
- `render/server.py` rebuilds the worker's start frame field by field;
  forgetting to forward a new field there disables a feature silently — that
  is exactly how this one shipped broken the first time.

## Live current names are RAW; a scope keeps WALL pace

Two defects that presented together as "the plot takes seconds to appear, and
two panes drift apart":

- **`LiveState.vectors` holds raw ngspice names** — `@r2[i]`, `v1#branch` —
  never the wrapped `i(...)` a rawfile speaks. `hasCurrent` tested the wrapped
  form, returned false for every device in live mode, and every wire/pin probe
  silently fell back to the 30 Hz reconstruction while the voltage beside it
  ran at full column rate: one pane visibly sparser than the other. The
  worker's `resolve` now tries all three spellings of a current, and the
  browser tests the raw ones.
- **A scope closed at most one column per solver point.** At the default speed
  the point rate (~110/s) is below the 150 columns/s a 4-second window needs,
  so every plot crept slower than wall clock — the band "took seconds to start
  showing". The worker now closes EVERY edge a data point crossed; when the
  solver's step is larger than a pixel the extra columns repeat the last
  value, which is what a scope showing a signal slower than its beam has
  always drawn. Measured 153/153/153 columns per second — identical to the frame —
  across a voltage, a wire probe and a source pin after the fix.

## Send the worker the SUM, not the answer

A wire's current and a terminal's are not vectors — they are reconstructed from
the device currents around them. Reconstructing one in the browser means doing
it once per FRAME, thirty times a second, and the result is a staircase drawn
next to a smooth voltage on the very same net: the worker closes a column every
few microseconds of simulated time, the browser can only supply a value every
thirty milliseconds of wall clock.

The reconstruction is LINEAR in the terminal currents, so it can be sent instead
of computed. `probeTerms` reads the coefficients off by solving once per device
with a reader that says "this one is 1 A, everything else is 0" — no algebra to
get wrong, and it is the same solver either way. A live scope then carries
`terms: [{vec, coeff}]` and the worker closes its columns like any other.

Two rules that follow:

- **The basis must keep the run's NULLS.** A device the run reports no branch
  current for is what makes a terminal the unknown one; answering 0 for it
  instead solves a different circuit. `probeTerms` takes a `hasCurrent`
  predicate for exactly that, and it comes from the run — `LiveState.vectors`
  live, `plot.byName` for a finished one — never from a guess about naming.
- **`liveState` changes thirty times a second and its vector LIST does not.**
  Depend on `liveState.vectors`, or the scope list is re-sent every frame.

Measured on the worked example: the terms are exact — `iw(w10)` is `-i(r2)`,
U1 pin 5 is `+i(r2)`, and the sum matches the direct solve to 0.00e+0 A across
the whole run. Live, a summed scope closed 946 columns against the voltage
scope's 946 over the same ten seconds.

The frame-rate reconstruction is still there, as a fallback for a probe that
cannot be expressed at all — a net with two unknown terminals, or a loop. That
one is a staircase by nature.

## A live scope's columns are addressed by POSITION — carry them by NAME

`LiveState.columns[i]` belongs to `config.scopes[i]`, so changing the scope list
moves every trace's history one slot along. `setScopes` used to answer that by
clearing the lot, which meant **removing one trace blanked every other trace on
the page**: the whole scope went back to zero columns and the plots had nothing
left to draw.

It now carries each surviving trace's columns across by vec name; only a new
trace starts empty. Frames already in flight were closed against the old list,
so for about one round trip a column can land in the wrong slot — one or two out
of six hundred, against a history that would otherwise be thrown away.

The other half was in the page: live `plotData` returned **null** when no
columns had arrived, and a null there destroys every chart and rebuilds it when
data returns. The live grid is now always the full width, padded with NaN, so a
moment with no columns is an empty scope rather than no scope.

## The charge-dot speed is a knob, and it says nothing about the simulation

The dots on a wire move at a speed proportional to that wire's share of the
run's peak current. How fast the whole picture runs is a viewing preference —
too fast to follow on one circuit is too slow to see on another — so it is a
slider in the top bar, remembered for the session.

Two things it is NOT: it does not change the simulation, and it is not the live
run's `speed` (simulated seconds per second of wall clock), which lives on the
run bar in live mode. Keep them apart in any wording — a user who confuses them
will think a slower picture is a more accurate one.

The mapping is logarithmic with 1x in the middle, because the useful range is a
factor of sixty and a linear slider spends four fifths of its travel above "too
fast to follow". Zero stops the dots where they are; the tint still says what
every net is worth, which is the right picture for a screenshot.

## A live run learns its own scale

`voltageRange` and `currentPeak` come from a finished run's extremes, which a
live run does not have — it has the latest frame. Left at their defaults a 5 V
circuit tinted against ±24 V and every dot ran at the wrong speed.

The live scale is learned from the frames and only ever GROWS. A peak that
tracked the instant would change the tint and the dot speed thirty times a
second, which reads as noise rather than as current. The effect returns the
same object when nothing grew, or it would re-render the page every frame for
no change.

## A live run has a scope too (now `sim/Plots.tsx`)

Live mode drew a circuit and no waveform, and clicking a net appeared to do
nothing — because the scope card was rendered only for a FINISHED run, so
`pickNet` was adding traces to something that was not on the page.

The whole path existed except the browser end. The worker has accepted a scope
list since it was written, closes one min/max COLUMN per pixel of scope, and
ships the closed columns in every frame; `LiveState.columns` has always carried
them. The page passed `scopes: []` and never called anything to change it.

- `LiveSession.setScopes` is new. Changing what a scope watches must NOT go
  through the session config — rebuilding that restarts the simulation, so a
  new trace would throw the run away.
- Columns already closed belong to the OLD scope list and are dropped with it.
  Keeping them would draw one trace's history under another's name.
- A live trace is a **band** between a column's min and max, not a line. That
  is honest: one column of a 1 kHz square sampled over 10 ms really does span
  both rails.
- `sim_s_per_px` is tied to the speed, so a scope shows the same few seconds of
  WALL clock at every setting — which is what a person means by "the last few
  seconds".

## Click the part, not a table (`sim/PartPopup.tsx`)

A part is set in a dialog that opens ON the part. What this replaced listed
every steerable part in the design under the drawing — forty text boxes in a
grid, in an order nobody chose, for a circuit three inches above them. Falstad
has always done it the other way, and so has every schematic editor: click the
component, get a dialog about that component.

The dialog is deliberately two halves, and only the second is about simulation:

1. **What the part is** — reference, value, the library part behind it, and
   whatever the placement carries: footprint, datasheet, description, the
   manufacturer's number, the model it is simulated as. This half is the reason
   the component is a separate file: the same dialog is meant to open on a
   project's schematic tab and answer "what IS this?" out of the catalogue.
2. **What it can be set to** — `ComponentInspector`, unchanged.

Rules that follow from how it works:

- **Every part gets a hit target, in every mode**, and the target is invisible
  until hovered. A hotspot that appeared only during a live run would make the
  same part clickable and then not; 87 accent boxes on a real sheet would be a
  diagram of the hit targets rather than of the circuit.
- **A sheet KiCad wrote is never rewritten**, so its dialog is `readOnly` and
  steers the RUN through `onLive`. The dialog says so rather than looking
  broken. A sketch's dialog writes to the document like the editor always did.
- **The dialog is dragged by its title bar**, because the part it describes is
  underneath it.
- **It stops its own pointer events.** The drawing under it listens for clicks
  on wires and parts, and without that every click inside the dialog would also
  pick whatever is behind it.
- The panel under the drawing kept only what a drawing CANNOT show: a source
  living in a SPICE text block, and the parts on OTHER sheets of the design —
  those by a search box, not a grid.

## An upload runs itself once, a snapshot does not

Every measurement in the simulator reads from a run: the scope, the readout,
the value beside a probed net. So a source that has not been run shows no
plot, no scope card and no reading — and clicking a net does nothing VISIBLE,
because `pickNet` adds a trace to a scope that is not rendered. That reads as
a broken page, not as "press Run", and it is exactly what the example did
before this.

`Simulator.tsx` therefore runs an **upload** source once when its geometry
arrives — a sketch, the worked example, a dropped sheet: all small, and all
opened in order to be simulated. A **snapshot** board is left alone, because
those runs are long and a reviewer picks the scenario before spending one.
The guard is a ref holding the upload id, not the effect's dependency list:
`doRun` is rebuilt whenever the chosen scenario changes.

## What to run, and what it said (now `sim/RunBar.tsx` + `sim/Verdicts.tsx`)

A harness carries its scenario as SPICE text beside the circuit. Left as text
it is a wall the user is asked to take on faith before pressing Run, so the
panel turns it into three things:

- **the runs it offers** — every `.control` block, named by its own first
  `echo`, with how many PASS/FAIL lines it prints. "The sheet's own" is the
  default and leaves the harness alone.
- **the analysis** — Transient / AC / DC / Operating point as a form that
  builds the directive, or "From the sheet" to use the one it carries. Same
  `params.ts` machinery the component inspector uses.
- **the verdicts** — `scenario.ts` reads the PASS/FAIL table out of the run's
  own log. That convention is already in every harness in `EVSE_20_CTRL`;
  nothing new is asked of anyone.

**A verdict run has no waveform, and that is not a failure.** It runs its
analysis inside the `.control` block, so ngspice writes no rawfile. The payload
comes back with zero plots and a log — render the verdicts, not an error.

**An unlabelled net cannot be probed from a `.control` block.** KiCad names it
`Net-(R1-Pad2)`, which SPICE reads as an expression with a minus in it. Put a
label on any net a check measures.

## Editing and simulating are ONE view (`sim/SimulatorView.tsx`)

There is no separate editor screen and there must not be one again. The
schematic, its readings and its drawing tools are the same surface: `Edit` on
the toolbar reveals the tools, and the overlay stays underneath them. A user
asked for this in exactly those words — "all in one place" — after having to
leave the simulation to change a resistor.

`sim/edit/doc.ts` holds the document and every derivation from it
(`docToDrawing`, `autoJunctions`, `symbolPins`, `orthoRun`). The document is
the ONLY state that is mutated — everything drawn comes from `docToDrawing`,
so there is never a second copy of the circuit to keep in step.

Three things hold it together:

- **A document draws from itself, anything else from the geometry.** A dragged
  part must follow the pointer, not a round trip. The overlay is matched to
  the document's wires BY POSITION — which holds because `sch_write` emits one
  `(wire)` per document wire in order, and because a drawn run is stored as
  one wire PER SEGMENT, the shape KiCad uses. When the counts disagree (a save
  has not landed), the overlay is dropped rather than drawn on the wrong wire.
- **The file follows the drawing without being asked.** An edit saves 700 ms
  after the last change, in place (`POST /api/sim/sketch?id=…`), then bumps a
  revision so the geometry and the netlist are read again. A new source per
  keystroke would fill the disk and move the address bar under the user.
- **`useSimOverlay` is the overlay, once.** Tint, charge canvas, click targets
  and live part hotspots. Both the editable and the read-only paths use it, so
  they cannot disagree about what a wire is worth.

- **Junctions are derived, never placed.** `autoJunctions` puts a dot where
  three wire ends meet or a wire end lands inside another wire. A dot a user
  could place by hand would be a short nobody can see.
- **The keyboard is KiCad's**: `w` wire, `r` rotate, `m` mirror, `l` label,
  `t` directive, Delete, Escape, Ctrl+Z. The people using this already know
  that keyboard.
- **A part's Value IS its SPICE value.** `10k`, `DC 5`, `PULSE(0 5 0 1u 1u 1m
  2m)`. Nothing translates it, and nothing should start — but nothing asks the
  user to type it either. `edit/ComponentInspector.tsx` shows a form per shape
  a part can take and a row per number, and fills the template in
  (`sch_lib.PARAM_FORMS` declares them, `edit/params.ts` builds and parses).
  A raw form is always the last option, because a value the fields cannot
  express is still a value.
- **A row that a running transient cannot follow says so.** ngspice accepts
  `alter` on a waveform and silently keeps the old script, and a `.model`
  parameter cannot be altered at all — those rows are marked "needs a re-run",
  which the auto-save then does. A knob that does nothing is worse than no
  knob.
- **The knob panel lists what the DRAWING cannot.** A harness source in a
  SPICE text block has no symbol to click. A part that has one is set in its
  inspector; listing it in both is two boxes for one number, and the second
  goes stale the moment the first is used.
- **Saving is `POST /api/sim/sketch`**, which writes a real `.kicad_sch` and
  returns an upload id — the source kind the simulator already runs. A circuit
  drawn here goes through exactly the same pipeline as one drawn in KiCad.
  Pass `?id=` to rewrite one in place; uploads are not cached, so the next
  netlist reads the file that is there now.
- **It opens what it drew, not what KiCad wrote.** A KiCad file carries tokens
  the document does not model, and writing it back would drop them silently.
  The Edit button appears only when `/upload/{id}/sketch` answers.

**An AC run is complex.** The payload stores real/imaginary in pairs and
`decodeSimPayload` folds them to magnitude — the thing a scope shows and the
thing that can colour a wire. A transient is real and passes straight through.

## The field solver (`src/sim/field/`)

Simulator → Field solver (`/sim?tab=field`), a subtab beside Circuit. It sizes
controlled-impedance traces against a stackup and draws the solved cross-section.

- **The cross-section is a canvas, and every colour is read from the palette.**
  A solved mesh is 150 000 triangles, which the DOM will not take. `draw.ts`
  resolves `--sim-hot` / `--sim-cold` / `--fs-signal` / `--fs-mask` and the rest
  with `getComputedStyle` on every paint — the same trick `useSimOverlay` uses —
  so the drawing follows the light/dark theme. Never hard-code a colour there.
  `--fs-signal`, `--fs-reference`, `--fs-mask` and `--fs-finish` are its own
  palette entries and have a dark variant.
- **The chart is SVG and takes its colours as `var(...)` strings**, which is why
  it can stay in the stylesheet while the canvas cannot.
- **A solve is a job, not a request** (`useSolverJob.ts`): it polls, streams the
  design-frequency result before the sweep finishes so the field appears early,
  and cancels — both on the Cancel button and when the component goes away.
- **The page calls the single-ended line "single"; the solver calls it
  "microstrip".** `cellParams` maps it. Sending the page's word produced a
  differential geometry with no error at all.
- **Two surfaces write the same project data**: the project's Stackup tab
  (`components/project/StackupTab.tsx`) and the "Save to a project" panel inside
  the solver (`ProjectPanel.tsx`). Both go through the same endpoints, and both
  must keep saying that an assignment applies from the chosen commit forward.
- **Stackup editing is gated on `useAuth().isAdmin`**, matching the API.
