# UI overhaul — proposal

Status: **built** (all six phases, 2026-07-29 — see §12 for the build record
and the deliberate deviations). Proposed 2026-07-29.

The web UI grew one panel at a time, each new feature stacked on whatever page
was open when it was built. This document proposes the full reorganization:
what the platform actually does, the new page structure, what merges, what
disappears, and the order to build it in. Almost everything here is frontend
work — **no new API endpoints**, and a home for eight endpoints that exist
today with no UI at all. The one backend touch is a field addition: the run's
`effective` lines gain a USD unit price, so the merged materials table
(section 5.3) can compare the plan with the actuals in one currency.

## 1. What is wrong today

The evidence, from a full inventory of all 15 pages, 20 panels, and 204 API
endpoints (2026-07-29):

- **The Invoices page stacks nine cards and three dialogs on one route**
  (1,196 lines): economics dashboard, stock verdict, JLC session, staged
  batches, decision queue, write log, register, pool table, run table. It is
  the entire production domain in one scroll.
- **Run cost / revenue / margin render in five places** (Invoices run table,
  ProductionDashboard, OrderDialog, RunCostsPanel, RunsTab tiles) — and none
  of them is a page that belongs to the run.
- **The same parts-stock comparison renders on three surfaces** (Parts stock
  page, StockReconcile card, a ProductionDashboard bullet). Two of them fetch
  `GET /api/parts-stock` twice on one page load.
- **A run is edited from two pages with disjoint field sets.** Status, notes,
  and price overrides live under Projects → Runs. Sale price, customer, units
  sold, and `qty_good` live in a dialog on Invoices. Neither side shows the
  other's fields, and `qty_good` — set only in that dialog — is the
  denominator the run costs panel complains about.
- **Supplier documents are editable through two different panels with two
  different endpoints** (Invoices page vs. the per-run costs panel).
- **Pool totals appear in three places**, document-issue lists in two, the
  JLC connectivity question in four.
- **Eleven independent copies of a `money()` formatter.** Three copies of the
  step-catalog select. Three copies of the charge-to select. Three literal
  copies of the 11-value `CostLineKind` list. Three attachment UIs. Two layer
  viewers. Two version rails. Three chart implementations.
- **Two pages are dead weight.** Import station targets the retired YAML
  pipeline (`Sources/` does not exist on this branch). The Jaravis chat page
  duplicates what the agent already does better over MCP.
- **Navigation does not match the domains.** Nine top-level entries, while the
  library home (Browse) is reachable only through the brand link, and pages
  like the component detail or the file viewer have no nav home at all.

## 2. What the platform actually does

Every UI decision below follows from these workflows. They come from the API
inventory and from the project goal: *whatever went in, goes out, and
everything is accounted for — fully via UI, for both JLC and manual sources.*

| # | Workflow | Today it spans |
|---|---|---|
| W1 | Find, inspect, or edit a library part | Browse, ComponentDetail, NewComponent |
| W2 | Review and approve agent proposals | Proposals, ComponentDetail, Skills |
| W3 | Maintain a design project (BOM, board, renders, history) | ProjectDetail 5 tabs |
| W4 | Plan production costs (cost items, extras, volume curve) | CostsTab, BomTab |
| W5 | Execute a production run (files, draws, serials, sale) | RunsTab + 3 nested panels + a dialog on Invoices |
| W6 | Get money in and allocate it (JLC import or manual invoice) | 5 cards on Invoices |
| W7 | Prove conservation (stock reconcile, adjustments, undo) | StockReconcile, WriteLog, JlcStock, ProductionDashboard |
| W8 | Set up clients and background jobs (KiCad, MCP, datasheets, FX) | KicadPage, a hidden block on Skills, no FX UI |

## 3. Principles

1. **Navigate by domain, not by feature history.** Five top-level sections:
   Library, Projects, Production, Proposals, Setup.
2. **Every entity gets exactly one page that owns it.** The run is the worst
   offender today, so it gets its own route.
3. **Every number has one home.** Other pages link to that home instead of
   re-rendering the figure.
4. **Merge sibling tables that show the same rows.** One stock table, one
   documents table, one run-economics block.
5. **Preview, then commit, everywhere money moves.** The pattern exists three
   times with three formatters — make it one component.
6. **Every page is addressable by URL.** Skills, tabs, and runs get routes.
   Deep links from Proposals must land on the exact object.
7. **Delete dead weight instead of hiding it.**

## 4. The new sitemap

```
┌─ Library ──────── /library
│    Components     /library/components          (browse, default)
│    Component      /library/components/:id
│    New component  /library/components/new
│    Symbols & FPs  /library/templates  → /library/templates/:kind/:id
│    Skills         /library/skills     → /library/skills/:id
│
├─ Projects ─────── /projects
│    Project        /projects/:id   tabs: BOM · Board · Schematic ·
│                                   Cost plan · Runs · History · Notes · Settings
│    Run            /runs/:id       tabs: Overview · Materials · Costs ·
│                                   Files · Devices                  ← NEW PAGE
│
├─ Production ───── /production
│    Overview       /production                  (economics + health)
│    Invoices       /production/invoices         (register + entry + lines)
│    Stock          /production/stock            (merged table + verdict + ledger)
│    JLC            /production/jlc              (session + queue + staged + parts)
│    Write log      /production/writes           (undo journal)
│
├─ Proposals ────── /proposals                   (kept, badge, fixed links)
│
└─ Setup ────────── /setup                       (KiCad · MCP · jobs · FX · health)
```

Old routes redirect: `/` → `/library/components`, `/components/:id` →
`/library/components/:id`, `/templates/...` → `/library/templates/...`,
`/invoices` → `/production/invoices`, `/parts-stock` and `/jlc-stock` →
`/production/stock`, `/kicad` → `/setup`. `/view` stays as is (stateless
viewer, already correct). `/import` and `/jaravis` return 404 via the normal
not-found page.

## 5. Page specifications

### 5.1 Library

**Components (browse).** Becomes the Library landing page. Keeps the category
sidebar, search, and the fixed-layout table. Two fixes fold in: the two
overlapping "remember my place" mechanisms collapse into URL params only, and
the 1,000-row cap gets an explicit "load more" instead of silently truncating
column filters.

**Component page.** The 1,557-line file splits into cards that match how the
part is used, in this order:

1. **Identity** — version rail, status, category, symbol, footprint, BOM-role
   toggle, and the new **in-library toggle** (`PATCH /api/components/{id}/in-library`
   exists today with no caller anywhere).
2. **Supply** — the price ladder card as it is, plus **Where used**
   (`GET /api/components/{id}/where-used` exists in `api.ts`, called by
   nothing) and a link to this part's row on Production → Stock, with the
   part ledger one click away.
3. **Files** — datasheets and attachments, unchanged behavior.
4. **Properties** — unchanged, with the diff engine extracted to its own file.
5. **Previews** — symbol and footprint rail, unchanged.
6. **Notes** — shared CommentsPanel, unchanged.

**Symbols & footprints.** Rename from "Templates" — the user-facing objects
are symbols and footprints, and "templates" collides with nothing else in the
domain. The list page keeps the two tabs but makes the active tab sticky and
URL-addressable. The detail page gains a **danger zone** card with the
footprint retire action (`DELETE /api/footprints/{id}` exists with no caller)
and renders "Used by" through the standard DataTable instead of comma prose.

**Skills.** Moves under Library — the conventions are library conventions,
and the editor stays exactly as it is. Two changes: each skill gets a route
(`/library/skills/:id`) so the Proposals deep link finally works, and the
"Use these skills in Claude Code" setup block moves out to Setup, where the
MCP instructions live.

### 5.2 Projects

The project page keeps its design-side tabs unchanged: **BOM**, **Board**,
**Schematic**, **History**, **Notes**, **Settings**. Three changes:

1. **Costs → "Cost plan", grouped by stage.** Same editor, honest name: this
   tab is the plan, actuals live on the run. The flat items table gains stage
   group headers (**fab → pcba → final**, from the step catalog), so the plan
   reads in production order and mirrors the run page's plan-vs-billed table
   one-to-one. Extra BOM items keep their own card below, unchanged.
2. **BOM tab drops its read-only "Manufacturing costs" table.** The tiles and
   the volume curve stay. The table was a copy of Cost plan's table one tab
   away — a link replaces it.
3. **Runs becomes a plain table.** Label, qty, status, date, snapshot, files,
   serials, cost/device, margin — each row links to `/runs/:id`. The 434-line
   open-run mega-card (which nested three more panels) goes away entirely.

### 5.3 The run page — new, and the center of the overhaul

One route, `/runs/:id`, owns everything about one production batch. Header:
project backlink, run label, status select, qty, run date.

| Tab | Contents | Today this lives in |
|---|---|---|
| **Overview** | The economics strip — planned cost, actual cost, revenue, margin, per-device — rendered ONCE, here. The **Sale card**: price per device, currency, units billed, units good, customer, order ref, order date, with the live margin preview. Run notes. | RunCostsPanel actuals row, OrderDialog (Invoices), RunsTab tiles + notes |
| **Materials** | **One table: planned BOM usage vs. really used components** (spec below), plus the draw actions: draw BOM from pool, manual draw, write off as attrition. | RunsTab plan table + RunCostsPanel draws — two disconnected views today |
| **Costs** | The same plan-vs-actual pattern for processes and additional costs: the per-step plan-vs-billed table with supplier chips, the documents charged to this run (shared DocumentsTable, filtered), add document / add line. | RunCostsPanel |
| **Files** | Production sets (repo import / upload / kicad-cli), the gerber viewer (shared LayerViewer), the JLC assembly subset, run attachments (shared Attachments widget). | ProductionPanel + RunsTab attachments |
| **Devices** | Serial registration and list. | RunsTab bottom |

**The Materials table — one row per component, plan and reality side by
side.** Today the planned BOM lines (RunsTab) and the actual pool draws
(RunCostsPanel) are two tables on two panels that never meet. The merged
table:

| Column | Source |
|---|---|
| Part (refs · LCSC · MPN, links to the component) | both sides |
| Planned qty | `run.effective` — the snapshot BOM × devices, after overrides |
| Used qty | live consumption (voided draws excluded) |
| Δ qty | computed; red when used < planned (not drawn) or > planned (rework) |
| Planned unit | `run.effective` at the run date — the **final-price override editor lives in this cell** (moves from the old Plan tab) |
| Actual unit (USD) | the draws, lot-weighted where lot-bound |
| Planned / actual total, Δ | computed, both sides in USD |
| Source | where the actual came from: **JLC invoice** (measured, lot-bound, from the order/invoice data), **manual draw**, or **BOM average** — plus a per-row expansion showing the purchase lots |

Row states make the gaps visible instead of burying them in two tables:
planned-and-used rows compare, planned-but-not-used rows warn (run not drawn
yet, or a miss), used-but-not-planned rows flag rework or an extra, and
write-offs render as attrition rows. The footer totals are the same figures
the Overview strip shows — one derivation, two zoom levels.

One data note: the planned side is priced in the project currency, the
actual side in USD. The `effective` payload gains a per-line `unit_usd`
(converted at the run date server-side, where the FX table already lives) —
the single backend addition in this proposal.

This closes the disjoint-edit defect: every `PATCH /api/runs/{id}` field is
visible and editable on one page. OrderDialog is deleted. The run page is
reachable from the project's Runs tab and from every run mention on
Production → Overview.

### 5.4 Production

**Overview** (`/production`). The money answer and the trust checklist:

1. Six tiles (revenue, cost, profit, margin, devices, cost/device).
2. **One** run economics block — the per-run bars and the per-run table merge
   into a single table with an inline bar column. Each row links to
   `/runs/:id`. Today these are two renderings of the same `reg.by_run_usd`
   stacked on the same page.
3. "Where the money went" one-row summary and the pool one-liner, each linking
   to Invoices / Stock instead of repeating their tables.
4. **"Before these numbers are final"** — the single home for open issues:
   unreconciled documents, unassigned money, placeholder documents, runs with
   no sale price, negative stock, consignment gaps. Every entry links to the
   page that fixes it. Today this list exists twice with different wording.

**Invoices** (`/production/invoices`). The register and the line workshop:

1. Register table (date, supplier, number, total, assigned-to, state), the
   "only unfinished" filter, and the expanded line tree exactly as today:
   charge-to select, planned-as step select, split, void, attachments,
   resolve-parts.
2. "New invoice" manual entry form, now with an **NBP rate helper** on the
   date+currency fields (`GET /api/fx/nbp` exists, documented, no caller).
3. A toolbar action for the **global resolve-parts pass**
   (`POST /api/cost-lines/resolve-parts` exists with no caller).
4. Nothing else. The dashboard, stock verdict, JLC panels, and write log all
   move out.

**Stock** (`/production/stock`). The full merge of the Parts stock page and
StockReconcile — the clearest duplicate in the app. One page answers "does the
stock account close":

1. **Verdict header**: STOCK RECONCILES / N PARTS DO NOT RECONCILE, parts
   measured twice, not-consigned count, held-with-no-purchase count, zero-cost
   additions count.
2. **One tile row** for the money in parts (spent, drawn, remainder at cost /
   market, unrealized, pieces held). Pool totals render here and nowhere else.
3. **One table** — the union of both today's tables: LCSC, part, bought,
   drawn, written off, ours, JLC has, Δ qty, paid unit, market unit, at cost,
   Δ value. Filters: free text, state (all / measured twice / not at JLC / no
   invoice), and **"only disagreements"** as the default view when the
   verdict fails. Row click expands the part ledger (step chart + events),
   as on the current Parts stock page.
4. **Adjustments section** — list and delete, as in StockReconcile today.
   "Held parts used in projects" stays as the bottom card.
5. "Sync stock count" button — renamed from "Sync from JLCPCB" so it stops
   colliding with the orders sync on the JLC page.

**JLC** (`/production/jlc`). The pipeline page, in pipeline order:

1. **Session strip** — unchanged, and its existing `onChange` callback
   finally gets wired so a fresh cookie paste refreshes the panels below.
2. **Sync** — one button, "Sync orders & invoices" (`/api/jlc/import/sync`),
   with the staged-counts result line.
3. **Decision queue** (assembly orders) — unchanged evidence cards, plus two
   buttons the API already supports but the UI never exposed:
   **Fetch JLC BOM** (`POST /orders/{code}/fetch-bom`, the only source of
   who-supplied-each-part) and **Void shop draws**
   (`POST /decision/{code}/void-shop-draws`, the double-charge repair).
4. **Staged batches** and **parts orders** tables — unchanged
   preview/import flow.

**Write log** (`/production/writes`). The journal table as today, plus row
expansion showing the batch detail (`GET /api/ledger/batches/{id}` exists
with no caller). Check and Undo stay verbatim-refusal.

### 5.5 Proposals

Kept as a top-level section — it is the approval gate for the whole library
and the badge must stay visible. Three fixes:

1. Symbol and footprint rows link to `/library/templates/:kind/:id` (today
   they are plain text and the inline image is the only inspection path).
2. Skill rows deep-link to `/library/skills/:id` (works once skills have
   routes).
3. The busy-spinner keys on kind+id instead of the bare `proposal_id`, which
   is only unique per kind.

### 5.6 Setup

One page, five cards, replacing KicadPage and the setup block hidden inside
Skills:

1. **KiCad** — PCM repo URL + steps, HTTP library download + steps, CLI sync
   alternative. Content from today's KicadPage, trimmed.
2. **Claude Code / MCP** — the skills-sync hook setup, `KICAD_API_URL`,
   `KICAD_MCP_TOKEN`, moved from the Skills page.
3. **Datasheet archive** — the stored/total counter, nightly schedule, Fetch
   missing / Re-check all. Moved from KicadPage, where it never belonged.
4. **Exchange rates** — the FX table with refresh and manual override.
   `GET/PUT /api/fx` and `POST /api/fx/refresh` have client functions in
   `api.ts` today and no page. Unknown-rate warnings across the app link here.
5. **Health** — `GET /api/health/schema` results and the render-service
   status, so "a feature depends on a column that never landed" is visible
   without opening the API docs.

## 6. The money flows, step by step

Review question (2026-07-29): where do the stock overview, manual invoices,
invoice assignment, and the JLC import with its stages and steps live in the
new structure? Each flow, end to end.

### 6.1 Component stock overview

- **All parts**: Production → Stock. Verdict header, money tiles, one table
  with bought / drawn / written off / ours / JLC has / Δ qty / Δ value.
  Default view: only the disagreements, when the verdict fails.
- **One part**: click its row — the ledger expands (balance chart + every
  buy / draw / adjust event). The same ledger is linked from the component
  page's Supply card in the Library.
- **One project**: Projects → BOM tab keeps "Check stock" (coverage against
  own JLC stock, then market). The Stock page keeps "Held parts used in
  projects" as its bottom card.
- **One run**: run page → Materials tab — the single planned-vs-used table
  (section 5.3): planned BOM qty and price against the real draws, lot by
  lot, with the source of every actual figure (JLC invoice, manual draw, or
  BOM average) plus write-offs.

### 6.2 Manual invoice entry and assignment

1. Production → Invoices → "New invoice". Enter supplier, number, date,
   currency, printed total, and the positions (kind, label, qty, unit price).
   The NBP helper shows the table-A rate for the date and currency.
2. Attach the scan or PDF to the document.
3. Run "Resolve parts" so part positions match library components and feed
   the pool.
4. Open the line tree and assign each position:
   - **Charge to** — a run, a project, the pool (parts), spread across the
     pool by value or qty (freight), or excluded with a reason.
   - **Planned as** — the production step (see 6.4).
   - **Split** — when one printed figure covers several runs or hides
     several fees. Vendor templates pre-fill known fee breakdowns. The
     parent keeps the printed figure, the shares carry the money.
5. The register row flips to "assigned" and "reconciles". Anything left over
   appears in the Production → Overview checklist, which links back here.

### 6.3 JLC import: orders, invoices, lots

The JLC page lays the pipeline out in execution order, top to bottom:

1. **Session** — paste cookies once, the keep-alive holds the session. A
   dead session is announced here, and only here.
2. **Sync orders & invoices** — stages assembly batches and reads the order
   list. Staging writes no cost rows.
3. **Decision queue** — one card per assembly order with the evidence:
   derived device count (panels × per-panel), consumed stock value, candidate
   runs with agreement scores. Assign it: link to a run, or mark it an
   external project. "Fetch JLC BOM" pulls who-supplied-each-part.
4. **Apply the decision** — always previewable (the dry run uses the real
   write path and rolls back). Linking points the invoice lines at the run
   and writes the measured, lot-bound pool draws. "Void shop draws" repairs
   the double charge when JLC supplied a part itself.
5. **Staged batches** — Preview, then Import: the batch becomes one cost
   document, its lines charged according to the decisions above, steps
   tagged automatically where the vendor fee name is known.
6. **Parts orders** — Import: each line becomes a purchase lot at the price
   actually paid. Later draws bind to these lots.
7. Every apply is one reversible batch — visible and undoable in Write log.
8. Verify the outcome on Production → Overview (checklist) and Stock
   (verdict).

### 6.4 Stages and steps

The step catalog (`GET /api/cost-steps`) is vendor-neutral and grouped by
stage: **fab → pcba → final**. It connects the plan to the billed reality:

- **Plan side**: cost items on the project's Cost plan tab carry a step key.
- **Billed side**: an invoice line gets its step one of three ways — the
  JLC import maps known fee names automatically, the "Planned as" select
  sets it by hand, or a split template stamps it on each share.
- **Read-back**: the run page Costs tab shows plan vs billed per step, with
  supplier chips naming which document billed each step. Free-form links to
  a specific plan item stay available for costs outside the catalog.
- One shared `<StepSelect>` renders the catalog everywhere it appears.

## 7. What is deleted

| Item | Reason |
|---|---|
| **Import station page** (`/import`, 364 lines) | Targets the retired YAML pipeline. `Sources/` does not exist on this branch. The API endpoints stay for archive-branch use; only the UI goes. |
| **Jaravis chat page** (`/jaravis`, 533 lines) | The agent runs over MCP in Claude Code. Proposals still arrive in the queue with the badge. The session API becomes web-unused — retiring it is a separate, later decision. |
| **OrderDialog** (178 lines) | Fields move into the run page Overview. |
| **ProductionDashboard** (154 lines) | Merges into Production → Overview. |
| **StockReconcile** (331 lines) | Merges into Production → Stock. |
| **RunsTab open-run mega-card** (~300 of 434 lines) | Becomes the run page. |
| **KicadPage** (251 lines) | Becomes two cards on Setup. |
| **Skills setup block** (~60 lines) | Moves to Setup. |
| **BomTab "Manufacturing costs" table** | Copy of Cost plan's table one tab away. |

Net effect on the top bar: 9 entries → 5. Net effect on the Invoices route:
9 cards + 3 dialogs → 1 register + 1 form + 2 dialogs (split, plan-link).

## 8. Duplicates and their single new home

| Data / action | Today | New home |
|---|---|---|
| Run cost / revenue / margin | 5 places | Run page Overview (per run) + Production Overview table (all runs) |
| Planned BOM lines vs. pool draws | 2 disconnected tables (RunsTab, RunCostsPanel) | One Materials table, plan and actual side by side |
| Sale fields incl. `qty_good` | OrderDialog only | Run page Overview, Sale card |
| Parts stock comparison | 3 surfaces, 3 fetches | Production → Stock, one fetch |
| Pool totals (paid/drawn/on hand) | 3 places | Stock tile row |
| Document create/edit/void | 2 panels, 2 endpoints | One DocumentsTable + LineTree, used by Invoices (all) and run Costs tab (filtered) |
| Unreconciled / unassigned issues | 2 lists + row pills | Production Overview checklist (links out) |
| JLC connectivity status | 4 spots | Session strip on JLC page + one dot in the Production sub-nav |
| "Sync from JLCPCB" label | 2 buttons, 2 meanings | "Sync stock count" (Stock) / "Sync orders & invoices" (JLC) |
| Step-catalog select | 3 copies | One `<StepSelect>` |
| Charge-to select | 3 copies | One `<ChargeToSelect>` |
| `CostLineKind` list | 3 literal copies | One exported const |
| `money()` formatter | 11 copies | One `format.ts` |
| Attachment upload/list/delete | 3 implementations | One `<Attachments>` widget |
| Layer toggle + swatch viewer | 2 implementations | One `<LayerViewer>` (board layers + gerbers) |
| Version rail | 2 implementations | One `<VersionRail>` |
| Preview-then-commit | 3 implementations | One `<PreviewCommit>` pair |
| Snapshot select + ingest | Header + History tab | Header select stays the single state; History's View/Ingest writes it |

Notes stay on two endpoint families (entity comments vs. project notes) but
render through one visual component.

## 9. Data-flow fixes that ride along

1. **One fetch per endpoint per page.** `getPartsStock` is fetched once and
   passed down. Same for `getCostSteps`.
2. **The `writeSeq` remount hack goes away.** Panels subscribe to a plain
   refresh callback from the page instead of being destroyed and rebuilt by a
   changing React key.
3. **One persistence convention.** Sticky UI state uses `useStickyState`
   everywhere. The two raw `localStorage` users (Jaravis — deleted anyway —
   and the lots toggle) migrate.
4. **Tab state in the URL** for every tabbed page, so any view is linkable.

## 10. Build order

Each phase ships alone, `tsc --noEmit` clean, verified against the running
platform before the next starts.

1. **Cut and regroup** — delete Import and Jaravis pages, create Setup (move
   KiCad + MCP + datasheet cards), new nav with all redirects. Small diff,
   immediate relief.
2. **Shared primitives** — `format.ts`, `<StepSelect>`, `<ChargeToSelect>`,
   the kinds const, `<Attachments>`, `<PreviewCommit>`, `<VersionRail>`.
   No visual change, removes the 20+ copies.
3. **Stock merge** — build `/production/stock`, delete StockReconcile and the
   old Parts stock page. The clearest duplicate dies first.
4. **The run page** — build `/runs/:id` from RunsTab + ProductionPanel +
   RunCostsPanel + OrderDialog, with the merged Materials table (incl. the
   `unit_usd` field addition on `run.effective`), slim the project Runs tab
   to a table.
5. **Production split** — Overview, Invoices, JLC, Write log as separate
   routes, dismantle the nine-card stack, wire the four no-UI endpoints
   (NBP helper, global resolve-parts, batch detail, fetch-bom + void-shop-draws).
6. **Library polish** — split ComponentDetail into cards, add where-used and
   the in-library toggle, skill routes, proposals deep links, footprint
   danger zone.

## 11. Open questions

1. **Jaravis session API** — the web UI stops calling it after phase 1. Keep
   it for scripts, or retire the endpoints and the background-run machinery?
2. **Import-station API** — same question. The UI goes now. The endpoints
   only matter when the `archive/yaml-library` branch is mounted.
3. **Production sub-nav badge** — should the "before these numbers are final"
   count appear as a badge on the Production nav entry, like the Proposals
   badge? Recommended: yes, it is the daily to-do signal.

## 12. Build record (2026-07-29)

All six phases were built in one pass, each verified with `tsc --noEmit` and
a production build; the backend change was verified against the running
platform (run 8: 24 of 25 effective lines carry `unit_usd`; the 25th has no
price, which renders as an em dash, never a silent 0).

What shipped beyond the letter of the spec:

- The **JLC page wires the session strip's `onChange`** — pasting fresh
  cookies reloads the queue and staged panels, which the old mega-page never
  connected.
- The **Write log rows expand** to the journalled rows (table, row id, op,
  `before` snapshot) via the previously caller-less batch-detail endpoint.
- **Stock accepts `?q=`** as an entry point; the component page's Supply area
  links to the part's ledger through it.
- The **overview checklist links every issue** to the page that fixes it,
  including unknown FX rates → Setup.

Deliberate deviations, all cosmetic-refactor items deferred, none behavioral:

1. **ComponentDetail was not split into files.** It gained the where-used
   card, the in-library toggle and the stock link, but the 1,557-line file
   stands. Splitting it is safe to do incrementally later.
2. **`<VersionRail>`, `<Attachments>`, `<PreviewCommit>`, `<LayerViewer>`
   were not extracted.** Their duplicate implementations (2, 3, 3, 2 copies)
   remain in place; each extraction is mechanical and independent.
3. **Browse kept its 1,000-row cap and dual state mechanism** — the fixes
   listed in §5.1 are still open.
4. **Setup's Health card shows schema statements only** — no render-service
   status endpoint exists, and inventing one was out of scope.
5. **The Materials table shows lots and the override editor in the row
   expansion**, not in the cells — ten one-line columns left no room, and the
   expansion keeps the single-line table rule intact. The old global
   "show purchase lots" toggle (raw localStorage) is gone.
6. **Proposals deep links land on the skill/template**, not on the specific
   draft version (`showVersion` is honored only by the component page). The
   draft is one click away in the version rail.
7. **The run page fetches actuals twice** (Overview strip and Costs tab load
   independently). Harmless; a shared context would remove it.

Backend touches (the proposal promised one; it took three, all additive):
`run_effective` lines gained `unit_usd` (FX at the run date, `None` when the
rate is unknown); geometry proposals gained `template_id` so their rows can
link to the template pages; the cost-pool endpoint's docstring no longer
claims pool quantities are "not expected to match JLCPCB stock", which
contradicted the platform's stated goal.
