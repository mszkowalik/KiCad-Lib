# Changelog

## 2026-09-12 — The programming log paid for an index nobody used

- **`programming_logs` carried two indexes of 52 MB and only ever read one.**
  The table holds 2,444,307 rows across 6321 runs, the largest row count in the
  database, and it only grows because every line of every run is kept on
  purpose. It had a surrogate `id` primary key beside a unique constraint on
  `(run_id, seq)`. `pg_stat_user_indexes` reported **zero scans, ever**, on the
  `id` index: nothing addresses a log line by anything but its run and its
  sequence, no foreign key pointed at it, and the writer never supplied one.
- **`(run_id, seq)` is the primary key now**, and the table went from 375 MB to
  304 MB — 53 MB of index and 18 MB of row overhead. Nothing was deleted: the
  row count and the run count are unchanged.
- **A startup migration applies it once**, guarded by the presence of the `id`
  column, and reports itself at `GET /api/health/schema` as
  `programming_logs.pk`. It ends in a `VACUUM FULL`, because `DROP COLUMN` only
  marks a column dead in Postgres and the bytes stay until the table is
  rewritten. Measured on the full 2.44 M rows: 0.54 s of DDL and 1.7 s of
  rewrite, which is why it runs at startup rather than in the background.

## 2026-09-12 — Every IC in the library now draws its supply current

- **The amplifiers, comparators and logic gates delivered current to their
  loads and took none from their rails.** A behavioural output stage is a
  controlled source, and a controlled source referenced to node 0 manufactures
  its current out of the ground node; the supply pins were only read, by ideal
  sensors that draw nothing. Measured with an ammeter in every supply leg:
  `sigma_opamp` put 5.00 mA into a 1k load and drew 14 pA from its rail,
  `sigma_rail_buf` put out 3.22 mA and drew exactly zero, and `sigma_ldo`
  delivered 100 mA while drawing only its own 3 mA. Every rail-current,
  decoupling, regulator-loading and efficiency answer from those models was
  wrong. Signal-path answers were not, which is why it lasted: the verdict
  harnesses check signals.
- **Eighteen models corrected, plus one new shared block.** `sigma_supply`
  does the two jobs that belong to whichever block owns the rails: it draws a
  quiescent current from rail to rail, and it moves the stage's output current
  off node 0 and onto the supplies. It carries an RC lag because the
  correction closes a real loop — rail to clamp to output to current — and an
  algebraic one aborts the operating point.
- **Models built from a real switch were always right.** `sigma_ucc27538` and
  `sigma_hss` measured 117 mA and 2.38 A from their supplies, correctly; they
  only needed a quiescent current. The split between the two kinds is
  structural and now recorded in the simulation skill.
- **`IQ` is per channel, not per package.** A composed wrapper shares one
  parameter across every block it holds, so a dual part would charge a package
  figure twice. Divide by the channel count and show the arithmetic in the
  component's `Sim.Params` comment.
- **Nothing in the signal path moved.** Against the old models a corrected
  op-amp matched the closed-loop output and the saturated swing to seven
  digits. All six `EVSE_20_CTRL` harnesses still pass every check — 102 of
  102 — with no convergence trouble. The verdict numbers shift in the fourth
  decimal, in the direction of a rail that now sags under real load.
- **All 34 affected components now carry their own number**, each with the
  datasheet page in its version comment. Five regulators held values that were
  already wrong, one of them by a factor of ten. Three parts are marked
  `placeholder` and say what would confirm them: the negative 12 V regulator,
  whose datasheet publishes no typical at all; the gate driver, whose only
  tabulated bias current is measured below its own turn-on threshold; and the
  buck's efficiency, whose curve in the datasheet is drawn for a sibling
  variant's board.
- **The buck converter conflated two states.** It drew its SHUTDOWN current
  whether enabled or not, and those differ by about an order of magnitude. It
  now follows the enable pin.
- **A component edit does not reach a board that already exists.**
  `Sim.Params` is baked into the project's own schematic, which is a git
  checkout, so a board picks these numbers up only after Tools → Update
  Symbols from Library and a commit. A model edit is different: it reaches
  every snapshot at once. The two halves of this change therefore land at
  different times.

## 2026-09-12 — A run that says how far it has got, and a scope you can zoom

- **The Run button reports real progress, not just "Running…".** ngspice says
  where it is: during a transient it prints the simulated time it has reached.
  The process that owns the solver records that against the transient's own
  stop time, and the browser polls it once a second. The bar names its phase
  too, because reading the schematic through kicad-cli is several seconds
  before the solver starts and a bar frozen at zero reads as a stall.
- **A verdict harness solves its transient TWICE**, which the progress bar
  made visible. The deck's own `.tran` writes the rawfile the scope plots, and
  the `tran` inside `.control` is the run the `meas` verdicts read. Every
  `_sim` project in EVSE_20_CTRL is built that way, so a 720 ms scenario costs
  about 27 s instead of 14 s. The bar counts the sweeps and names which one is
  running, so it stays monotonic instead of reaching 98% and starting again.
- **The scope zooms and pans.** Drag selects a window, as it always did but
  nothing said so. The wheel now zooms about the pointer, shift-wheel and a
  trackpad's horizontal scroll pan, and Reset zoom appears once the view is
  not the whole run. Every pane moves together, because they share one time
  axis and a zoom that moved one of them would break the reading that stacking
  them is for. A new run resets the window.
- **Taller doubles the pane height**, and gives the scope more of the window
  so two tall panes still fit without scrolling. The setting is remembered per
  sheet.

## 2026-09-12 — A mirrored part on its side is placed the way KiCad places it

- **The schematic transform applied `(mirror x|y)` before the rotation. KiCad
  applies it after, in sheet axes.** At 0 degrees the two orders agree, so
  every sheet but one looked right. At 90 or 270 degrees the mirror flipped
  the symbol's own axis, which is the OTHER sheet axis: a mirrored resistor
  lying on its side had pin 1 drawn and connected at pin 2's end, and a
  mirrored zener the wrong way round. CP_PWM carries eight such parts and
  the Simulator reported nine "group touches more than one net" conflicts
  for it. The overlay's `_place`, the server drawing's `placement_matrix`
  and the browser's `matrixOf` all moved together; on the EVSE_20_CTRL
  snapshot every one of 1511 placed pins now sits on the net the kicad-cli
  netlist gives it, and the conflicts are gone. The netlist and the
  simulation were never affected — they come from kicad-cli, not from this
  transform.
- **The "No charge is drawn on N nets" notice counts nets, not wire groups.**
  A power net drawn in several places was listed once per place, so GND
  appeared twice in a list of 19.

## 2026-09-11 — The Board dropdown lists boards, not simulation harnesses

- **A project's Board selector no longer offers its `_sim` projects.**
  `EVSE_20_CTRL` carries six simulation harnesses beside the design, each a
  real `.kicad_pro`, so the project view listed seven "boards" and a project
  with one board and six harnesses showed a dropdown at all. The ingest now
  classifies every discovered project as a `board` or a `harness` from its
  root sheet: a sheet carrying a SPICE directive is a harness. The project
  view, the project list and the BOM/board/schematic tabs show boards only;
  the Simulator keeps listing the harnesses as before. The name suffix is not
  the rule, so a schematic-only design stays a board and a harness is one
  whatever it is called.
- **The Schematic tab gained a Simulation picker.** It lists the design and
  every harness of the snapshot, so a harness sheet is still readable in the
  project view. Simulate and Play live open the harness that is picked. With
  the design picked, they let the Simulator open its first harness instead of
  the design and a "carries no directives" notice.
- **Old snapshots are classified on first read** and the answer is stored, so
  no re-fetch is needed.

## 2026-09-11 — A part with no land pattern stays off the board

- **A cabled antenna, an RF pigtail or an enclosure with no drawn outline is no
  longer pushed onto the PCB.** The generator forced `on_board yes` on every
  part outside the `Simulation` category, so a base symbol's own
  `(on_board no)` was thrown away — `Antenna_Cabled` and `RF_Pigtail` were
  emitted as on-board although both drawings say otherwise, and the note on
  `Antenna_Cabled` claiming this flag prevents a missing-footprint report had
  not been true for any of six parts. A part is now off-board when **the base
  symbol declares `(on_board no)` AND the component has no footprint**. See
  [decision 0005](docs/decisions/0005-off-board-parts.md).
- **Both halves of that rule are load-bearing.** Without the declaration, a
  `Footprint` somebody merely forgot would drop the part off the board in
  silence. Without the footprint test, the 17 terminal-block plugs would drop
  off too: `TERMINAL_BLOCK_PLUG` declares `(on_board no)` while every component
  on it carries the deliberate `TerminalBlock_Plug_Invisible` land, so the next
  *Update PCB from Schematic* would have **deleted those footprints from boards
  that already exist**.
- **One predicate, three readers.** `generator.off_board` is called by the
  mirror, by the KiCad HTTP catalog record (which is what KiCad actually places
  from) and by the validator, so what the validator forgives and what KiCad is
  told cannot drift. `in_bom` is deliberately not derived the same way —
  `RPi_CM5` carries an `(in_bom no)` this library does not mean, and honouring
  it would drop the most expensive line on the board out of every BOM.
- **The validator gained its third footprint-less branch.** It already answered
  `na` for BOM-only and simulation-only parts; an off-board part was the case
  with no branch, so `cmp.required_props` and `cmp.footprint_ref` failed by
  construction on every cabled antenna and pigtail and had to be answered by
  hand. An ordinary part with an empty `Footprint` still fails.
- **Two RF pigtails and a shared symbol.** `BWIPX1-SMA-1.13L100` (C784403,
  I-PEX Gen 1 to SMA female) and `ACA-RFSMA-K TO IPEX1 001` (C22467635, to
  RP-SMA female), on a new 0-pin `RF_Pigtail` base symbol with reference `W`.
  Both are bulkhead types and both mate with an antenna already in the library.
  Gender was confirmed from each manufacturer's own drawing: the Chinese
  `外螺内孔` reads like RP-SMA to an English eye and is a standard SMA jack,
  because the jack carries the external thread and the plug carries the nut.
- **`Enclosure` now declares itself off-board.** This moves only the three
  Italtronic enclosures, which have no footprint; the four Hammond and the
  Takachi parts carry real lands and are untouched. Whether the Italtronic
  three should get their own mechanical footprints is still open
  ([docs/todo.md](docs/todo.md)).
- **RF uses one spelling for VSWR.** The category carried both `V.S.W.R` (four
  on-board antennas) and `VSWR` (four cabled parts) for one quantity, which
  splits any template or parametric filter. All four were renamed; none was
  reviewed or signed, so the rename cost no verification.

## 2026-09-11 — JLC06121H-3313A, and a board file checked against its stackup layer by layer

- **`JLC06121H-3313A` joins the stackup library.** JLCPCB's published 6-layer
  1.2 mm controlled-impedance build, outer 1 oz and inner 0.5 oz: prepreg 3313
  0.0994 mm under each outer layer, a 0.1 mm core under each of those, and
  **three 7628 sheets — 0.2104, 0.218 and 0.2104 mm — in the middle gap**.
  Copper and dielectric sum to 1.1684 mm. The Dk of every sheet was already in
  the material library, so nothing was assumed that the fab does not publish.
  JLCPCB renders the 1.2 mm tables only after a click, which is why the code
  appears nowhere in the page source; the figures were read from the rendered
  page on 11 September 2026.
- **The project Stackup tab now says WHERE the board file and the assigned
  stackup disagree**, not only that they do. Both sides are reduced to the same
  normal form — the ordered copper layers, and the dielectric GAP between each
  neighbouring pair — and every copper thickness, gap thickness, sheet
  thickness, Dk and loss tangent is compared, each with its own verdict.
  Inside tolerance counts as the same: copper 0.005 mm, dielectric 0.02 mm, Dk
  0.05, loss tangent 0.002.
- **Why the gap and not the layer.** KiCad allows only `copper - 1` dielectric
  layers, so a fab gap built from three prepreg sheets becomes one KiCad
  dielectric carrying three sub-layers, written with the bare `addsublayer`
  token. Counting `(layer …)` nodes could therefore never agree with the fab's
  own table, and the old reader returned the first sheet of such a layer and
  silently lost the rest. What a field sees is the gap.
- **"No stackup in the file" and "the checkout is gone" no longer look the
  same.** The board file was read inside a bare `except`, so a pruned mirror
  reported the board as declaring no stackup of its own. The page now states
  which of the two happened, and what to do about it.
- `total_mm` of a board file is now the copper-plus-dielectric build, the way a
  fab states a stackup; the solder mask is reported separately as `mask_mm`.
  The two sides describe a mask differently and are not compared on it.
- The agent tool `fieldsolver_board` returns the same table as `comparison`.

## 2026-09-11 — One stackup table everywhere, a stackup that is electrical only, and a board that has a colour

- **`JLC06121H-3313A` joins the stackup library** — JLCPCB's published 6-layer
  1.2 mm build, with **three 7628 sheets in the middle gap** (0.2104, 0.218,
  0.2104 mm). 1.1684 mm of copper and dielectric. JLCPCB renders its 1.2 mm
  tables only after a click, which is why the code appears nowhere in the page
  source; the figures were read from the rendered page.
- **EVSE_20_CTRL is built to it.** The board file carried a placeholder — FR4 at
  Er 4.5 everywhere, prepreg 0.1 mm, core 0.35 mm — that no fab states, so no
  width solved against it would have been the width the board gets.
- **One stackup table, everywhere** (`web/src/components/StackupTable.tsx`):
  the project comparison, the field solver and the stackup editor all draw the
  same colour-coded, top-to-bottom rows, aligned by one backend function so the
  picture cannot disagree with the verdict.
- **The board-file check is layer by layer.** It compared two things — copper
  count and total thickness — so a board could carry the wrong laminate in every
  gap and read as agreeing. Now every copper thickness, dielectric gap, sheet,
  Dk and loss tangent has its own verdict, plus solder mask ink thickness and Dk
  and the presence of a legend, each against a published figure.
- **KiCad sub-layers are read.** A fab gap of three prepreg sheets is one KiCad
  dielectric carrying `addsublayer` groups; the old reader took the first
  `(thickness)` and silently lost the rest. `total_mm` also counted the solder
  mask, which a fab stackup does not, so every comparison was 0.02 mm out.
- **"No stackup in the file" and "the checkout is gone" no longer look the
  same** — the board file was read inside a bare `except`.
- **A stackup is electrical only**
  ([decision 0008](docs/decisions/0008-a-stackup-is-electrical-only.md)). Board
  **colour is project data**, versioned like the assignment, chosen from
  JLCPCB's own list with the legend following the mask; picking one writes
  nothing to the library. Outer layers are **per face**, so a board can carry
  legend or a different finish on one side. Copper is named `L1`…`Ln` by
  position and dielectric labels are generated — neither is typed — and a save
  that would put **copper against copper is refused**.
- **Impedance profiles survive a refresh** (`field_workspaces`, one row per
  person) and are banked **per stackup**: switching parks the open set and picks
  up the other, because a profile's cells are keyed by copper layer name.
  Saving to a board is **all-or-nothing** and refuses a stackup mismatch,
  server-side. Removing a profile, a stackup or a rule set now asks first.
- **The solder mask is drawn as one object.** It arrives as several overlapping
  rectangles and each was filled with a translucent green, so every overlap
  doubled the alpha — three different greens, darkest where two met, and a
  coplanar ground that looked mis-drawn.
- **Numbers carry their unit** (`SiInput`): type `35um`, `0.035`, `1.4mil`,
  `2.4GHz`. Copper thickness is checked against the foils that exist and the
  weight is read off it. The mask over a trace is derived as half the figure
  over the substrate — subtracting the copper gives −4.5 µm on JLCPCB's own
  published pair.
- **Every modal locks the page behind it, closes on Escape and on a click
  outside** (`web/src/components/modal.ts`). Escape is bound on the document:
  on the backdrop it only fires once focus is inside, which is why dialogs had
  to focus themselves to be dismissable at all.

## 2026-09-10 — Datasheets stored once, versioned by text; re-signed PDFs no longer bump parts

- **One stored file per distinct content.** Datasheet bytes moved from
  `datasheet_versions` into a content-addressed `documents` table; a version
  is now a history row that points at a document, and two components that
  link the same PDF share one copy (24 files were shared between parts, the
  TPS7A20 variants among them). The page index follows the document, so a
  shared file is indexed once. The move ran at startup in SQL and rewrote the
  tables, which handed the disk back
  ([decision 0004](docs/decisions/0004-datasheet-identity-and-storage.md)).
- **A new version means the text changed.** TI re-signs every PDF about every
  two days and generates the whole tail of the document at download time, so
  one TPS61023 datasheet had 37 stored copies, each of which bumped the
  component to a new version and dropped its verification. The identity is
  now a hash of the page text with a role per page: the body in order, the
  orderable-part table reduced to its part-number and lifecycle pairs, the
  drawings as an unordered set, the live tape-and-reel tables excluded. On a
  copy of the production library that took 704 versions down to 616 and 557
  stored files down to 484, and every difference left is real. A re-signed
  file answers `restamped` and stores nothing. The revision label parsed from
  the document ("Rev. B", "SLVSF14B") shows on the datasheet card and in the
  history.
- **A real revision is a review event.** The automatic bump now runs through
  the shared publish path; the review record does not carry across a
  datasheet whose text changed (the sign-off does), and a review request is
  opened with the revision labels, the pages that are new or edited, how many
  drawings were removed, and whether the orderable-part table moved.
- **A stored web page is no longer counted as an unsearchable datasheet.**
  LCSC serves its "document not available" page as `C10425.pdf` with
  `Content-Type: text/html`; the leading bytes now decide what a file is, so
  186 such pages moved from `scan` to `none`. One of them is a current copy
  and needs a real datasheet.
- **The fetcher learns which user agent a host accepts.** Infineon and
  Nexperia refuse `curl` and serve a browser string; onsemi does the reverse.
  A refusal retries with the other string and the answer is remembered per
  host. The 11 empty Infineon downloads in the audit log were this.
- **A saved URL is fetched at once**, not at the nightly run.
- **Clean-up endpoints.** `GET /api/datasheets/restamps` lists the history
  the byte rule wrote; `POST /api/datasheets/restamps/collapse` folds it into
  the surviving version and drops the orphaned files.

## 2026-09-10 — Sync plugin 1.5.0 owns library updates; HTTP catalog every 2 minutes

- **Sync plugin 1.5.0 records what it installed in the Plugin and Content
  Manager.** The PCM decides "update available" from its own record,
  `installed_packages.json`, and only its dialog writes it — so a library the
  Sync button had already refreshed still showed a badge on every start, and
  Update All re-downloaded the 259 MB models zip the delta had delivered.
  After a successful sync the library and 3D-model packages are recorded at
  the served version and pinned, KiCad's own switch for "updated elsewhere":
  no badge, no Update All, a manual Update still in the menu. The plugin
  package is left alone and still updates through the PCM. KiCad reads the
  record at start-up and writes its in-memory copy back when the PCM dialog
  closes, so a dialog closed later in the same session can restore the old
  versions; the next sync corrects them. The closing notification now also
  says that placed parts are copies (Tools → Update Footprints / Symbols from
  Library).
- **KiCad re-fetches the part catalog every 2 minutes instead of every hour.**
  The `.kicad_httplib` now carries `timeout_categories_seconds` and
  `timeout_parts_seconds` of 120. KiCad 10 refreshes the catalog in a
  background thread every `max` of the two, and no menu action, IPC command or
  plugin can force it, so the interval is the only lever. A published
  footprint or field change reaches the symbol chooser within two minutes;
  one refresh costs 17 requests and about 44 kB on the wire. The values are
  embedded in the file: download `7Sigma.kicad_httplib` again from Setup and
  replace the installed copy.

## 2026-09-10 — Built means finished and passed; the Aqua history, again

- **The shelf no longer holds units nobody can pick up.** Stock per batch used
  to add the quantity typed on the production run to the devices recorded in
  it, which claimed 118 units that exist in no record and $1,700 at cost —
  four on Dongle Batch 1 against 521 real devices, 44 on Batch 3, 67 on Aqua
  Batch 5 — while two other batches read as 113 and 47 units "overdrawn". A
  batch that has any device record is now counted from its devices and from
  nothing else; the typed quantity rides along as `qty_recorded` so a wrong
  run quantity stays visible. Only a batch with **no** device records at all,
  which is the V3 prototype runs, is still counted from its quantity, and that
  is the one remaining source of an unserialized unit. See
  [decision 0007](docs/decisions/0007-built-means-finished-and-passed.md),
  which overrides item 8 of [decision 0003](docs/decisions/0003-orders-shipments-and-device-history.md).
- **A board that never passed is not stock.** The retro import had written a
  `produced` event for every imported device, failed ones included, so 82
  boards whose newest programming or test run failed sat on the shelf and
  could be picked for a shipment. They are unbuilt until a later run passes.
  Production after the pass: dongles 4,429 passed, 4,366 shipped, 63 on the
  shelf; Aqua 914, 867, 47.
- **Every built batch stays on the shelf card.** The card selected rows by what
  was left on them, so the moment `built` started counting passed devices, six
  of seven dongle batches vanished — everything they held had shipped. The
  filter now drops planned batches and keeps the rest, and **Recorded sits next
  to Built**: a row is marked when built is above recorded, which is impossible
  rather than merely unlucky. Dongle Batch 5 is recorded as 455 boards and has
  568 devices, Batch 6 as 945 against 992. Under-building is ordinary attrition
  and is not marked.
- **347 more Aqua units were filed under the dongle.** The July re-attribution
  used the functional test and the pushed GPIO template and called an untested
  Aqua indistinguishable. It is not: every config report carries the device's
  own `INFO1` line, `"Module":"CE_Aqua"` or `"Module":"CE_Dongle_v2"`. The
  signal agrees with the test everywhere the two overlap — none of the 4,121
  Module=Dongle devices ever ran the Aqua test, and all 584 Aqua-tested devices
  are Module=Aqua.
- **77 boards had two records each.** The 2025-11-05 firmware names a device by
  its full MAC where earlier builds used the last three bytes, so a board
  re-flashed after that date appeared as both `dongle_<6 hex>` and
  `dongle_<12 hex>`. They are merged into the older record. One pair survived
  the merge: `8BD26C` and `78:42:1C:8B:D2:6C` are a genuine three-byte
  collision between two products.
- **Two Aqua batches had been sold twice.** The run migration turned the build
  quantity of runs 12 and 13 into orders of 315 and 200 units that no invoice
  covers, on top of the real Aqua sales. Both orders are gone and the runs'
  sale columns are blank, so the idempotent migration cannot recreate them.
- Scripts: `docs/flasher/fix_aqua_attribution_2.py` and
  `docs/flasher/fix_built_is_passed.py`, both dry-run by default. The reasoning
  and the numbers are in `docs/flasher/design.md`.

## 2026-09-07 — Order page layout, device list sorting, sort hints

- **Sync plugin 1.4.1 quarantines the duplicates iCloud makes at install.**
  A PCM install into an iCloud folder can leave a `7Sigma_Base 2.kicad_sym`
  (the previous library) beside the real one. KiCad registers it as a second
  symbol library and the sync plugin, which has no baseline for it, listed
  every symbol in it as "only here — never sent" (153 rows on 2026-09-06).
  The sweep that runs at the start of every sync now handles duplicate
  files as well as folders: empty folders are deleted, anything with content
  is moved to `strays/<timestamp>/` inside the plugin folder, and the dead
  `sym-lib-table` / `fp-lib-table` rows go with it. Nothing is deleted. The
  sweep itself, from 2026-08-27, never reached installed plugins because that
  change did not bump `PLUGIN_VERSION`; this one does.
- **`list_footprints` finds a shared land by any package name it serves.**
  The agent tool matches the query against a footprint's `tags`, `descr`
  and hidden `Equivalent Packages` property as well as its name, and a hit
  made that way says which field matched and quotes it. Searching "WQFN-16"
  or "LFCSP-16" now returns the QFN-16 3x3 mm land those packages share
  (conventions-footprints v27, §1), instead of nothing.
- **Order page**: the products, invoices and shipments tables size their
  columns to the content and scroll inside the card instead of clipping;
  under 1700 px the tables take the full width with the two short cards
  beneath. Notes is a full-width row of the order form.
- **Devices list**: Project, Batch and Runs sort and filter on the server,
  and a Where column shows the device state (in stock, shipped, …). The
  batch shown is the one the orders side linked to the device.
- **Every sortable header** shows a faint sort glyph and the whole header
  cell is the click target — before, the title alone was the button and
  nothing marked it as one.

## 2026-09-06 — Orders in the project window, demand, decided JLC orders

- **Orders tab** on every project, next to Batches: one row per order line
  for that project's products, with the order's status and a link to it.
- **Demand card** on the Orders page and at the top of the Orders tab: open
  order quantity against devices on the shelf and the quantity of planned
  batches, with the shortfall or the surplus. `GET /api/demand`.
- **A JLC import decision now overrides JLC's cached panel count.** Before,
  an order decided as 4-up kept showing JLC's 1-up count in the queue and in
  the run-fill check (Batch 8: 200 devices and "short" against 800). The
  queue shows a decided order as decided, keeps JLC's own factor for
  reference, and names the parts JLC sourced from its own stock, which the
  BOM vote cannot see.

## 2026-09-03 — Sales orders, shipments and a per-device history

Decision record [0003](docs/decisions/0003-orders-shipments-and-device-history.md).
A sale is no longer a set of columns on a production run.

- **Customers and orders** are tables: an order holds one line per product,
  so an Aqua and a dongle sit on one order. Status (open / partial /
  fulfilled) follows the shipments and is never set by hand.
- **Invoices per order**: proforma, advance, final, correction. Advance +
  final + correction should equal the net total; the page warns, nothing
  blocks. Due date defaults to issue + the customer's terms. Revenue converts
  per invoice at the invoice date.
- **Every device has a history**: produced in a batch, shipped on an order,
  returned, repaired, replaced, disposed of. The flasher writes the first
  event on the first pass in a batch. Finished-device stock is a count of
  devices on the shelf per batch, valued at the batch's actual per-device
  cost; batches from before device records are counted from the batch
  quantity ("without a serial").
- **Shipping draws oldest-first** from the batches the user ticks, or takes
  pasted device IDs. A return against a device FIFO never picked swaps it in
  and puts the guessed device back. A warranty replacement is charged to the
  original order, so an order with three replacements shows the cost of
  503 devices against the revenue of 500.
- **Migration at startup**: each run with a price became an order line and
  one unserialized delivery; runs sharing an order reference share the order.
  The run's own sale columns stay for the register, whose figures do not move.
- New: Production → Orders, an order page, "Where it is" on every device page.

## 2026-08-31 — Field solver

Controlled-impedance geometry moved from the standalone prototype into the
platform, as **Simulator → Field solver**. A 2D quasi-TEM FEM solver for
microstrip, stripline, coplanar and differential lines with via fences, checked
against closed forms (microstrip Hammerstad-Jensen 0.6 %, stripline Wheeler
0.1 %, CPWG conformal 2.5 %) and against JLCPCB's own calculator.

- Stackups and production rules are library data in Postgres. Stackups are
  written by administrators only; anybody may assign one to a board.
- A board's stackup and its impedance profiles are commit-versioned like the
  cost plan: assigned at a commit, carried forward until changed. Changing the
  stackup keeps every profile and result and marks the results outdated.
- The board file and the assigned stackup may disagree; the difference is
  reported, nothing is blocked.
- The sweep is floored at 1 MHz — below that a perfect conductor stops
  describing a real board.
- `triangle`, the mesher, is licensed for personal and research use only and
  must be replaced before any commercial release.
- The solver runs on both architectures. amd64 installs the mesher's wheel;
  arm64 has no wheel published, so the image builds the same version from the
  upstream git tag. The two builds agree on Z0 to 0.0013 % and produce meshes
  that differ by about 3 % in node count.
- The server VM went from 2 cores and 8 GB to 8 cores and 16 GB, and from a
  `x86-64-v2-AES` CPU model, which has no AVX at all, to `host`. A geometry
  search that took 21.1 s takes 8.2 s. The api container's memory ceiling rose
  from 1500 MB to 6 GB to hold six solver workers.

This file starts on 2026-08-28. For earlier work, read the git history.

Each entry says what changed and why. Put a note here when a change alters how
the platform behaves in production, not for every commit.

## 2026-08-29

### Added

- **A package simulation wrapper is now built from blocks, not written.** KiCad
  netlists one element per reference designator, so the subcircuit `Sim.Name`
  points at is always package-level. Those wrappers were typed by hand, one per
  part, and nine of the sixty-five models in the library held no behaviour at
  all — two instance lines and a parameter pass-through. Two of them,
  `sigma_74hc21` and `sigma_buf2`, were written, linked to nothing, and never
  noticed. A symbol's link now stores a block design and the platform generates
  the `.subckt` from it. See
  [decision 0001](docs/decisions/0001-generate-package-sim-wrappers-from-blocks.md).

  The rule that shapes it is one wrapper port per unique symbol pin, never
  fewer. Two pins are never merged onto one port, because the schematic may put
  them on different nets and one port carries one node. The result is that the
  port list is `p1 p2 p4 …` by construction, so **`Sim.Pins` is derived and can
  no longer be mis-authored** — the swapped pair that `validate_pin_map` admits
  it cannot catch is not expressible in this mode.

### Changed

- **Eleven symbols moved to composed models and thirteen hand-written wrappers
  were deleted.** The conversion preserved every wrapper's interface, so no
  component's `Sim.Params` row moved: `cli/simrecompose.py apply --verify`
  reported 0 lost parameters and 0 moved defaults. Checked under ngspice
  against the deployed library, the composed wrapper beside the hand-written
  one on the same stimulus: `v(y1) = v(o1) = 3.283582 V`, `v(y2) = v(o2) = 0 V`.

- **Nine superseded simulation primitives were deleted**: `sigma_and4`,
  `sigma_buf`, `sigma_buf_3st`, `sigma_dff`, `sigma_dff_r`, `sigma_dff_sr`,
  `sigma_inv`, `sigma_monostable` and `sigma_iso7721`. Each has a
  `sigma_rail_*` equivalent that reads its own supply pins at run time, and
  every one of those is in use. The library holds 54 models, from 65.

### Fixed

- **The rail check no longer reports correctly wired supplies as miswired.** It
  failed sixteen links, and all sixteen were right. Its list of rail port names
  held eleven entries, so `vdd1`, `gnd2`, `vcc1`, `vinp`, `vinn` and `vs` were
  not rails as far as it knew; rail ports are matched by shape now.

  The second half of the check is deleted rather than widened. "A `power_in`
  pin on a port that is not rail-shaped" cannot tell an LDO's `in` from an
  op-amp's `in+`, because the difference lives in the model and not in the
  name. It reported ten LDOs, three DC/DC bricks, an isolator, a high-side
  switch and a flip-flop whose `pren` is tied high because it has no preset —
  and not one real fault. Nothing is lost: each port takes exactly one pin, so
  a supply pin landing on a signal port displaces another pin onto the real
  rail port, and that pin is not a power pin, which is what the surviving half
  tests. All 62 simulation links now validate clean.

- **Generated text is emitted in a fixed order.** `SimModelVersion.parsed` and
  `SymbolSimLink.composition` are JSONB, and Postgres reorders an object's
  keys, so a dict iterated in the session that wrote it gives one order and the
  same dict read back gives another. A wrapper therefore differed from itself
  across a round trip, and the mirror withheld the `Sim.*` fields of
  `74LVC1G175GW,125` over a moved word in a comment. Any list the composer
  derives from a dict is now ordered explicitly.

## 2026-08-28

### Fixed

- **The API no longer exhausts the server.** The `kicadlib-api` container held
  4.8 GB of memory (1.8 GB resident and 3.0 GB in swap) on an 8 GB host, and it
  peaked at 6.0 GB. The kernel killed it four times in August (18 August, and
  three times on 23 August), each time at 6.9 GB to 7.5 GB. The kill was a
  global out-of-memory event, so it also damaged the unrelated stacks on the
  same machine. Four defects caused this:

  1. `datasheet_pages.index_one` started one thread for each stored datasheet
     version and limited nothing. One `pymupdf4llm` extraction uses 400 MB to
     450 MB at peak, even for a document of 10 pages. The nightly re-check
     walks all 678 datasheets, so many extractions ran together. A
     `BoundedSemaphore(1)` now permits one extraction at a time. Extraction is
     CPU-bound and the host has 2 cores, so the threads never ran in parallel.
     They only held memory together.
  2. glibc kept the freed memory. The process held 67 malloc heaps of 64 MB,
     which is 4.2 GB of arena, for approximately 48 MB of live objects. The
     image now sets `MALLOC_ARENA_MAX=2`, and the new `services/memory.py`
     calls `malloc_trim(0)` after each large document. Both halves are
     necessary. A measurement on the real corpus shows 16 documents plateau at
     636 MB with 2 arenas, instead of a continuous climb.
  3. No container had a memory limit, so a fault in one container became a
     fault of the whole host. The api service now sets `mem_limit: 1500m` and
     `memswap_limit: 1500m`. A regression now restarts one container instead
     of stopping the machine.
  4. Datasheet versions 367 and 368 failed to index on every boot, for ever.
     `pymupdf4llm` returns lone UTF-16 surrogates for some malformed CID fonts.
     Postgres refuses them, and the error arrived after the guard that stamps
     `pages_indexed_at`. The two documents therefore repeated approximately
     900 MB of extraction at each start. `_drop_surrogates` now removes these
     characters. A lone surrogate carries no text, so this loses nothing.

### Changed

- `mirror.write_manifest` hashes each file in blocks of 1 MB. Before, it read
  each file complete. This is a small improvement, and it is not the cause of
  the memory fault above.
