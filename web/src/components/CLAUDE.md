# Shared components (`web/src/components`)

Every page draws from here. Read `web/CLAUDE.md` first: it holds the style
system, the class inventory, and the three rules that decide what a new
component may look like — one CSS rule draws every text control, a value with a
unit is an `SiInput`, and a labelled control goes through `Field.tsx`.

A component in this directory is used by more than one page. If you are about to
write a page-local copy of something here, extend the shared one instead.

Sub-directories carry their own rules: `flasher/`, `invoices/`, `project/`,
`run/`.

## Symbol/footprint geometry from the clipboard: `components/GeometryPaste.tsx`

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


## Production sign-off is NOT a status — never render it with `StatusPill`

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


## Attachments open in a viewer, never as a download

Link file attachments through `viewkind.fileHref(path, filename)` with
`target="_blank"`: it routes PDFs to the browser's own viewer and CAD/mesh/image
formats to the `/view` page, and only falls back to a plain link for formats
nothing can render. For API-served bytes, pass the same-origin PATH (e.g.
`attachmentPath(id)` → `/api/run-attachments/3?inline=true`), not an absolute URL —
`fileHref` needs to recognise it as ours. The `inline=true` flag makes the API send
`Content-Disposition: inline`; without it the browser saves the file to Downloads
instead of showing it (user preference, 2026-07-27).

## ONE stackup table, and it is not a DataTable (`components/StackupTable.tsx`)

Every view of a board stackup goes through it — the project's Stackup tab comparing a
`.kicad_pcb` against the assigned stackup, the field solver showing the one it is
solving on, and the stackup EDITOR. Three views, one component, so they cannot drift
apart about what a layer is.

- **The rows come from the server** (`field_state.stack_rows`), already aligned. The
  page never pairs a board file against a stackup itself: the picture would then be
  able to disagree with the verdict the platform computed, which is the one thing this
  table must not do. The editor is the exception and shapes its own rows, because a
  draft being typed into cannot round-trip per keystroke — shaping only, no tolerances.
- **It is deliberately not a `DataTable`.** A stackup's ORDER is its meaning — the rows
  are a physical sequence from the top of the board down — so a sortable header would
  let a reader destroy the only thing it says, and sixteen rows have nothing to filter.
  What the house rule protects (fixed layout, no sideways scroll, one line per row) is
  honoured in the stylesheet, per mode, with widths summing to 100%.
- **Colour carries the layer KIND; in compare mode a second colour carries the
  VERDICT, on the right edge only** — two meanings that must never compete for the same
  pixels. Copper is the saturated one because it is the layer that conducts;
  dielectrics stay neutral and separate from each other by value, core darker than
  prepreg in both themes.
- **`renderCell` is what makes the editor the same table** rather than a second one
  that drifts: it puts a control in a cell and falls back to the default rendering when
  it returns `undefined`.
- **Board colour is passed in, never read from the stackup** (decision 0008). A row
  painted in the board's own ink carries its own text colour, chosen by WCAG relative
  luminance — a black mask is a legal choice and the theme's text is unreadable on it.

## Numbers that carry a unit: `SiInput` / `components/si.ts`

Every dimension and frequency field in the stackup editor, the field solver and the
production rules is an `SiInput`. Type `35um`, `0.035`, `1.4mil`, `2.4GHz`.

- **A bare number means the field's base unit**, and the box re-prints itself with the
  unit it used — so a misread is visible immediately instead of silent. `assume` /
  `fixedUnit` are for a value STORED in something other than the base (µm rules).
- **Display switches to µm below 50 µm, not below 1 mm.** A fab quotes laminates in
  millimetres (prepreg 3313 is 0.0994 mm) and foils and coatings in micrometres
  (copper 35 µm). At a 1 mm threshold the prepreg read as "99.4 um", which is not how
  anyone quotes it.
- **Copper thickness is validated against the foils that exist** (`COPPER_WEIGHTS`),
  and the weight is READ OFF it — never computed by division, because 0.0152 ÷ 0.0348
  rounds to the wrong weight. Both the nominal weight and the figure a fab publishes as
  built are accepted: JLCPCB states its half-ounce inner layers as 15.2 µm, the etched
  thickness, and marking the fab's own number as an error would be wrong.
- **The solder mask over a trace is derived, not typed** — half the figure over the
  substrate. Subtracting the copper thickness (the intuitive rule) gives −4.5 µm on
  JLCPCB's published pair, because its 30.5 µm over substrate is THINNER than the 35 µm
  copper it covers; a conformal coating thins over a raised feature instead of
  levelling across it, and 1.2 mil / 0.6 mil is exactly half.

## Every modal: `useModal` — locked page, click outside, Escape

**Any overlay that covers the page goes through `useModal` in
`components/modal.ts`.** It is three behaviours the platform applies everywhere, and
the reason they live in one hook is that nine of the ten modals here had none of them:

1. **The page behind does not scroll.** A wheel over a dialog scrolled the page under
   it, so closing the dialog left the reader somewhere else. The lock pads `body` by
   the scrollbar width, or everything behind the modal jumps sideways as it opens.
2. **A click outside closes it** — on `mousedown`, not `click`: a press that starts
   inside the card and releases outside (the end of a text selection, a dragged
   slider) is not "clicking outside", and closing on it loses work mid-gesture.
3. **Escape closes it.**

```tsx
const modal = useModal(() => setEditing(null), { active: !!editing });
// ...
<div className="modal-backdrop" {...modal.backdropProps}>
  <div className="card pad modal-card" {...modal.cardProps}>
```

- **Escape is bound on `document`, never on the backdrop's `onKeyDown`.** A key
  handler on an element only fires while focus is inside it, and focus sits on
  `document.body` until something in the dialog takes it — so a backdrop-bound Escape
  silently does nothing on any dialog that does not focus itself first. `RecheckDialog`
  had to focus its own button to work around exactly this; new dialogs do not.
- **`active` exists because several modals are rendered inside a `&&`**, and a hook
  cannot be called conditionally. Call it at the top of the component and say whether
  the modal is open.
- **Both effects are stack-aware**, because modals nest: Escape reaches only the top
  one, and the scroll lock lifts when the last one closes, not the first.
- **A modal that must be answered passes `useModal(null, { active })`** — it still
  locks the page, and neither Escape nor a click outside dismisses it. The bench's SIM
  PIN prompt is the one case: a flashing run is waiting on the answer.
- Dismissing goes through the same path as the dialog's own Cancel, so a confirm
  dismissed by Escape resolves false — it never confirms by accident.

## No native browser popups — use the in-app dialog system

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

## Every table: fixed layout, no horizontal scroll, single-line rows

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



## The change feed (`components/ChangesFeed.tsx`, `ChangeDetail.tsx`)

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

## `GeometryDiff`: flatten each render before blending, or the diff lies

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

## ONE symbol/footprint viewer, everywhere (`components/GeometryPreview.tsx`)

**Every preview of a KiCad drawing goes through `GeometryPreview`** — the
component page, the template page, the templates list, the review workbench and
the paste box. Do not add a seventh `<img>` shell, and do not put a drawing
behind a bare `<img>` again. (The schematic has its own single renderer,
`sim/draw/SchematicView` — see `../sim/draw/CLAUDE.md`. A symbol or a
footprint is this one.)

There were six shells before, with four different missing/error stories and
**three different canvas colours**. That is not cosmetic: kicad-cli renders with
the dark Skyline-7S theme — light strokes on a TRANSPARENT background — and the
viewer's light/dark preference is never sent to the renderer, so every frame has
to supply the dark ground itself. One of the six asked for
`var(--paper, #fff)`, and `--paper` is defined nowhere in the stylesheet, so the
review workbench drew light strokes on white in both themes.

- **The canvas is `--kicad-canvas`, once, on `:root`,** applied by
  `.preview-fill`. Keep it equal to `schematic.background` in
  `api/app/services/themes/Skyline-7S.json`. A caller's own class carries the
  SIZE and nothing else (`template-preview`, `workbench-preview`, `tpl-thumb`).
- **`lazy` picks the loading strategy, and the choice is real.** A single large
  preview `fetch`es, so a 404 can show the server's own sentence ("no published
  version") instead of a broken-image icon. A LIST of miniatures must not: one
  fetch per row loads every render at once and defeats `loading="lazy"`.
- **`FootprintPreview` owns the 2D/3D switch**, because a footprint has a board
  to render and a symbol does not. It was written twice — component page and
  template page — and the copies had already drifted on which state they
  remembered. It takes the two URLs; `glbUrl === null` means no board and no
  switch.

**A backend SVG cannot be themed by the viewer, and its cache never
invalidates** (`render.py` keys on `sha256(kind, name, theme, source)` and
nothing ever deletes from `render_cache_dir`, so changing `symbol_theme` doubles
the cache instead of clearing it). Measured 2026-09-12 on the running platform:
a cold kicad-cli render is **410-550 ms**, a warm cache hit 2-3 ms, and the SVG
is 10.3 kB against a 3.5 kB source. Parsing that symbol into a draw document
server-side is **0.74 ms** and 4.0 kB. So if these previews ever move off
kicad-cli, the answer is the hybrid the schematic already uses — parse to JSON
on the server, draw in `KicadSheet` — and never shipping raw s-expressions to
the browser, which is the biggest payload of the three AND a second parser to
keep in step with the Python one. Footprints stay on kicad-cli: nothing in the
browser parses a `.kicad_mod`, and pad shapes are where a re-implementation
would be wrong.

## `components/Viewer3D.tsx` takes a URL, not an entity

The GLB board view is reachable two ways — through a component version, and
directly from a footprint template — so the viewer knows about neither. It
fetches the GLB itself rather than handing `<model-viewer>` a URL, which is
what gives a clean 404 ("nothing pinned") and a spinner during the slow first
server render instead of a silently empty canvas.

**`.preview-fill` is `flex: 1`, so it only has a height when its parent gives
it one.** The component page's preview panel does; a plain card does not, and
the viewer collapsed to nothing on the template page. Pass a `className` with a
height (the template page passes `template-preview`).


## A PDF is framed from a BLOB, never from its URL (`components/PdfFrame.tsx`)

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

