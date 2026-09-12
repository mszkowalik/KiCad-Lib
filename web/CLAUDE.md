# Platform Web (`web`)

React + TypeScript + Vite frontend for the Project Management Platform. Talks to the
API at `api`. Routing is in `src/App.tsx`; pages live in `src/pages/`,
shared pieces in `src/components/`, and the typed API client is `src/api.ts`.

## Layout — the deep rules live beside the code

A CLAUDE.md in a subdirectory is read when you open a file in it. This file
holds what applies to the whole frontend. Everything else sits next to the code
it governs.

| Path | Holds | Its own rules |
|---|---|---|
| `src/api.ts` | The typed client — every call to the backend | below, "Data access" |
| `src/auth.tsx` | The sign-in gate | below, "Sign-in" |
| `src/styles.css` | The one stylesheet | below, "Reuse the existing style system" |
| `src/components/` | Everything more than one page uses | `src/components/CLAUDE.md` |
| `src/components/flasher/` | Production programming screens | `src/components/flasher/CLAUDE.md` |
| `src/components/invoices/` | The invoice register and its line tree | `src/components/invoices/CLAUDE.md` |
| `src/pages/` | One file per route | `src/pages/CLAUDE.md` |
| `src/sim/` | The simulator overlay, the scope, the live run | `src/sim/CLAUDE.md` |
| `src/sim/draw/` | The schematic renderer | `src/sim/draw/CLAUDE.md` |
| `src/sim/edit/` | The sketch editor | `src/sim/edit/CLAUDE.md` |
| `src/sim/field/` | The field solver UI | `src/sim/field/CLAUDE.md` |

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
- **ONE CSS rule draws every text control, and the size classes carry SIZE
  ONLY.** `input.text, select.text, textarea.text, input.row-input, …` in
  `styles.css` is the single place a border, background, radius, focus ring or
  font-size is declared. A size class that restates any of those puts the app
  back to looking like three different apps — which is exactly what happened:
  only `.text` had an appearance, `.row-input` was used bare 83 times and fell
  through to the BROWSER'S NATIVE widget, so Admin, the browse filters and the
  field solver rendered three different-looking forms (screenshots, 2026-09-12).
  - **`font-size` is stated, never inherited.** `font: inherit` made the same
    class render at 31, 33, 35 and 36 px on four pages, because each card sets
    its own size.
  - **Heights are pinned per size: 34 / 26 / 22 px.** A `<select>` computes
    `line-height: normal` whatever the rule says and its intrinsic box is a
    pixel taller again, so it never matched the `<input>` beside it. Three
    heights, and a fourth is a bug.

- **A value with a UNIT is an `SiInput`, on every page.** Quantities:
  `length` (base mm), `frequency` (Hz), `resistance` (Ω), `percent`,
  `capacitance` (F), `inductance` (H), `voltage` (V), `current` (A), `time` (s).
  Adding a field that carries a unit means adding it here, not writing a number
  box.
  - **One prefix ladder: print in the prefix that puts 1-999 before the point**
    (user decision 2026-09-12). `0.05 Ω` reads `50 mΩ`, `1560432 Ω` reads
    `1.56 MΩ`. This REPLACED a length-only rule that kept a fab's own spelling
    (prepreg as `0.0994 mm`); length now reads `99.4 um` and that was accepted
    deliberately in exchange for one rule everywhere.
  - **Max three decimals, and say when that rounded.** The ⓘ marker is shared
    with the help tooltip — never a second marker on one box — and tints warm
    when digits were dropped, with the exact value in the tip.
  - **Do NOT remember the unit the user typed.** It was tried and removed: a box
    pinned to mΩ printed 1 000 000 Ω as `1000000000 mΩ`. The ladder already
    answers `10m` with `10 mΩ`, because mΩ IS the prefix that suits 0.01.
  - **RKM / R-notation is accepted where it is a real convention.** `4k7` is
    4.7 kΩ, `4R7` is 4.7 Ω, `2G4` is 2.4 GHz — the prefix stands in for the
    decimal point, which is how values are printed on parts and in schematic
    Value fields. It is enabled per quantity (`rkm: true`), NOT globally:
    length is based on mm, so `1m5` would read as 1.5 METRES in a box that
    expects a fraction of one. Nobody writes a board dimension that way, so
    there it buys nothing and costs a silent factor of a thousand.
  - **Case matters for `M` vs `m`** on a resistance — `parseSi` tries the exact
    spelling before the lowercase one precisely so `10M` is megohms and `10m` is
    milliohms. The number may carry an exponent (`2.4e9`); no unit begins with
    `e`, so taking it greedily is unambiguous.
  - **The simulator's fields are SPICE strings, and SPICE spells mega
    differently.** ngspice reads `M` as MILLI and spells mega `MEG`; our boxes
    read `M` as mega, because that is what a schematic means and what the
    resistance box beside them does (user decision 2026-09-12). The two
    directions therefore use different tables: `parseSpice` reads what is
    already stored with ngspice's rule, `toSpice` writes it back and ALWAYS
    spells mega `MEG`. Type `1M` into a resistor and the sheet gets `1MEG` —
    verified end to end against a downloaded `.kicad_sch`. A field the server
    gave no unit (a gain in `V/V`, a threshold in `x rail`, a point count) stays
    a plain box: a prefix on a dimensionless number is nonsense.
  - **`quantityForUnit` is the only place a unit SYMBOL becomes a quantity.**
    `sch_lib.PARAM_FORMS`, `sim_scenario.ANALYSIS_FORMS` and `LiveControl` all
    already declare a unit per field, so a new simulator parameter becomes
    unit-aware with no frontend edit at all.
  - **The ⓘ sits INSIDE the box** and the caller's size class goes on the WRAP
    as well as the input. Beside the box it took 18 px of the field's own width
    and cut `500 um` to `500 u`; capping only the input left the marker floating
    in the gap next to it.
  - **The tip is `position: fixed`, placed from the marker's box by JS, and
    nothing in its ancestry may carry a `transform`.** A transformed ancestor
    makes `fixed` resolve against IT, not the viewport — which silently broke
    every tooltip the moment the marker moved inside the box. Same reasoning as
    `TemplateThumb`'s popup.

- **EVERY labelled control goes through `components/Field.tsx`.** `<Field label=…>`
  wraps any control — `<input className="text">`, `<select className="text">`,
  `SiInput`, `NumberInput`, a checkbox — with `<FieldRow>` for a few side by
  side, `<FieldSet legend=…>` for a named group and `<CheckField>` for a
  checkbox. Never write a page-local label wrapper again: `edit-grid`,
  `user-form`, `cred-form` and `fs-field` all existed at once, and their labels
  were mono UPPERCASE 11px in one and sans sentence-case 12px in another, so the
  same form looked different depending on which page you opened it from
  (unified 2026-09-12).

  - **`<Field>` wraps the control, it never replaces it.** A special control
    keeps its own behaviour and only its FRAME is shared. Putting a unit parser
    behind a project-name field so the boxes match would be a worse kind of
    uniformity — `SiInput` exists for reasons its own docstring gives (browser
    locale on `type="number"`, a spinner floating over a narrow field), and
    those reasons do not apply to a name.
  - **There are exactly TWO input sizes, and both are needed.** `.text` is the
    standard form field (7/10px padding); `.row-input` is the compact one
    (3/8px, 13px) for table rows, filter bars and toolbars, where a full-height
    input would break the one-line-per-row rule every table here follows. A
    third size is a bug.
  - **Containers**: `.field-row` (a handful of fields on one line, wrapping) and
    `.field-grid` (a whole form, auto-fit columns). A bare `<label>` inside
    either still renders correctly, so older markup was not all rewritten at
    once — but new code uses the component.
  - Modifiers compose onto `.text` rather than replacing it: `num-input`
    (90px, tabular), `modal-input` (full width in a dialog), `mono`. That is the
    pattern for anything narrow or special — never a new standalone input class.

- **Every page is `.page` unless it has a reason not to.** `min(1680px,
  max(1100px, 80%))`. `.page-wide` (the simulator) and the browse sidebar layout
  are the two deliberate exceptions. The Admin page carried `max-width: 860px`
  until 2026-09-12 and was the only page in the app at a different width, so the
  same card rendered at two sizes depending on the route it was reached from.
  If a card inside a wide page then looks stretched, cap the CARD — as
  `table.kv.settings-table` does — never the page.

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

- **`width` is a budget, and a pill does not fit in a small one.** The `width`
  numbers must sum to 100 (they are `<col>` percentages on a
  `table-layout: fixed` table) and each one has to hold the WIDEST thing the
  column prints. A `.pill` is `inline-block`, so the column's ellipsis cannot
  shorten it — too narrow simply cuts the word in half. A sign-off pill needs
  about 9% of a full-width table ("not signed"), a review pill about 10%
  (`ReviewPill` prints the provenance too: "checked (agent)"). Free text may
  truncate, a pill may not.

  Browse is the cautionary tale. Its widths used to live in `styles.css` as
  `.browse-table th:nth-child(n)` rules, with a comment explaining the 9%. When
  the page moved to DataTable the numbers were re-typed into `Column.width` as
  4 and 4, the CSS was left behind as dead rules, and every pill in the
  component browser read "NOT S…" / "CHECK…" until 2026-09-12. Measure before
  you change a width: `td.scrollWidth > td.clientWidth` on real rows says
  which columns clip.

- **Only `ctr` travels from `className` up to the header.** `Column.className`
  styles body cells. DataTable copies `ctr` (and `numeric`) onto the `<th>` as
  well, because a centred column whose header is left-aligned reads as broken,
  and because `ctr` is what trims the 12 px cell padding down to 6 px — without
  it a 3%-wide checkbox column cuts off its own header checkbox. `mono`,
  `muted` and `cell-cat` deliberately do NOT travel: they describe cell text.

- **An action column gets `text-overflow: clip`, not `ellipsis`.** A checkbox
  is 13 px of replaced content, not text; `ellipsis` answers an overflow by
  drawing a stray "…" beside it. `.data-fixed th.ctr, .data-fixed td.ctr`
  clips instead.

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


## Adding a dependency needs `--renew-anon-volumes`

The dev web container mounts `./web:/srv` and keeps the image's linux
`node_modules` behind an **anonymous volume**, so the host's macOS builds do not
shadow them. That volume survives `docker compose up --build`: the image gets
the new package and the container keeps the old tree, and Vite answers every
request with `Failed to resolve import`.

    docker compose up -d --build --force-recreate --renew-anon-volumes web

