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
- **Data tables use `components/DataTable.tsx`** — sortable header, per-column
  filter row, fixed column widths with ellipsis (never scrolls horizontally).
  Every BOM/costs table (BomTab, CostsTab) goes through it; pass `Column[]`
  defs with `width` (%), `numeric`, `render`, and `interactive: false` for
  action columns. Don't hand-roll `<table className="data">` headers with
  sorting/filtering — extend DataTable if something is missing.

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
  Pass `onFiled` to refresh the list: a creation makes the parent row at once
  even though its version stays a draft.
- **Preview before filing** — the Preview button POSTs to
  `/api/{kind}/preview.svg` and shows the render of the UNSAVED text. It returns
  an object URL, so revoke the previous one whenever it is replaced, and on
  unmount.

It only ever files a DRAFT. Approval and the published before/after live in
Proposals — do not add an approve control here, and do not rebuild the
side-by-side, `Proposals.tsx` already renders current-vs-draft from
`geometryProposalPreviewUrl(kind, id, "current"|"draft")`.

**Approving a new footprint version must offer to repoint its components.**
Components pin `footprint_version_id`, so an approved v4 leaves them on v3 while
the mirror already serves v4. The Proposals approve step names the components
still pinning the outgoing version and offers to move them. An offer, never
automatic — see the rule in `api/CLAUDE.md`. NOT BUILT YET.

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

### Site structure (UI overhaul, 2026-07-29)

- **Five nav sections**: Library (`/library/...`), Projects (+ `/runs/:id`),
  Production (`/production/...`), Proposals, Setup. Second-level navigation is
  `SectionNav` in `App.tsx`; every pre-overhaul route redirects, so never link
  to `/components/...`, `/invoices`, `/parts-stock`, `/kicad` in new code —
  use the new paths.
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
   `proposals-table`; see `styles.css`) and give it `table-layout: fixed` plus
   `nth-child` width percentages summing to **100%**.
2. Apply `overflow: hidden; text-overflow: ellipsis; white-space: nowrap` to
   every `th`/`td` — the shared `.data-fixed` helper does exactly this, so
   `className="data data-fixed <your-modifier>"` and the modifier only carries
   the widths. Reuse `.data-fixed` rather than re-declaring the ellipsis rules.
3. Add a `title` attribute with the full value on any cell that can truncate, so
   the hidden text is available on hover.
4. If one row genuinely must break the clamp (e.g. a full-width `colSpan`
   expansion row like the proposals before/after preview), opt *that cell* out
   with `white-space: normal; overflow: visible` — never relax the whole table.

Compound selectors (`.data.proposals-table td:nth-child(n)`) are needed to
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
