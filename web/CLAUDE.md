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
