# Platform Web (`platform/web`)

React + TypeScript + Vite frontend for the Project Management Platform. Talks to the
API at `platform/api`. Routing is in `src/App.tsx`; pages live in `src/pages/`,
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

### Jaravis chat is server-persisted (multiple sessions)

The Jaravis page (`pages/Jaravis.tsx`) no longer keeps the conversation in local
state only. Conversations are `JaravisSession`s stored by the API; the page
lists them in a left sidebar (`.chat-sessions` / `.session-item`, reusing the
`--accent-soft` active style) and streams turns via `jaravisSessionChatStream`.
Conventions to keep: the last-open session id is remembered in `localStorage`
under `jaravis.activeSession` (reopened on mount, else the newest); a session is
created **lazily on the first message** (and by the explicit "New chat" button)
so idle empty sessions don't pile up; session switching is disabled while a turn
is in flight (`busy || attaching`). The stored assistant message carries its
`trace` + `proposals`, so a reloaded thread renders the same tool list and
proposal notes as the live run.

Turns run server-side and survive a refresh (see the api CLAUDE.md background-run
note). Because of that: **Stop calls `cancelJaravisRun`**, not just an abort — a
client abort no longer stops the run. On opening a session whose last stored
message is a `user` message (the signature of an unfinished turn), the page
calls `reattach()` → `attachJaravisRun`, which replays the run's events for live
progress and then reloads the stored messages as the source of truth (reload,
don't append, to avoid duplicating the reply). `activeIdRef` mirrors `activeId`
so these async callbacks ignore results after the user switches conversations.
