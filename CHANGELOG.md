# Changelog

## 2026-09-17 (the stock count has a screen)

- **Production → Orders can count the shelf.** Paste what a scanner read —
  a plain list, or the CSV a scanner exports, header and timestamps included —
  and the card shows the plan: how many recorded deliveries would be taken
  back, how many refilled from stock, how many left empty, and every order line
  whose delivered quantity would move. Nothing is written until you press again.
  A code that is not a device is named and dropped with one button, which is
  what the two stray EAN barcodes on the 2026-09-17 sheet needed.
- **A shipment row has a "Take back" button** for a delivery recorded in error,
  and shows how many of its deliveries were already taken back. The delete `×`
  now follows whether the API would actually allow a delete: a reversed
  shipment carries no device but still carries events, so it offered a delete
  that answered 409.
- **The Ship card takes scanned serials.** It accepted only device row ids,
  which no scan sheet carries — its own hint told you to go and look each one
  up. Serials and ids now go in the same box, and a serial nothing carries is
  named instead of quietly shipping a shorter list.

## 2026-09-17 (a boxed device stops asking to be built)

- **Demand counts a device allocated to an open line as supply.** An
  `allocated` device is on the shelf, reserved for one order line, and
  `run_stock` leaves it out of stock by design (decision 0003 §9) — but the
  line it is held for still shows its open quantity. `GET /api/demand`
  therefore counted a boxed device as one to build and not as one already
  there: 32 dongles packed for order 17 read as 32 to make. Supply is now shelf
  stock, plus devices allocated to the lines whose open quantity the same
  figure is measuring, plus planned batches. An allocation to a line that is
  already fulfilled counts as neither.

## 2026-09-17 (a shipment can be taken back)

- **A device the stock count put back on the shelf now counts when it ships
  again.** `create_shipment` marks a device as its own replacement when it
  finds an earlier `shipped` event on the same line — the rule that stops a
  repaired device counting twice — and it read the raw event log. A delivery
  that an `unshipped` event had REVERSED still looked like a previous delivery,
  so re-shipping such a device recorded a replacement and added nothing to the
  order. It reads `live_shipped_of` now. A device that really was delivered,
  came back and went out again is still its own replacement.
- **`POST /api/shipments/{id}/reverse` takes back a shipment recorded in
  error.** Every delivery on it is reversed, its anonymous units go to zero and
  the devices return to stock. `dry_run` is the default. The header and its
  events stay — device history is not deleted, and a shipment the customer
  actually received still comes back through `POST /api/devices/{id}/return`.
  See [decision 0028](docs/decisions/0028-a-shipment-recorded-in-error-is-reversed-not-deleted.md).

## 2026-09-17 (a stock count can correct the record)

- **A shelf count now reverses the FIFO guesses it contradicts.** A shipment
  without serials draws devices FIFO (decision 0003 §6), and that pick is a
  guess. Until now a customer return was the only thing that could correct one,
  so a count that found a device sitting on the shelf while the platform said
  it was at a customer had nowhere to go: `create_shipment` refuses a device
  that is not in stock, `delete_shipment` refuses a shipment that carries
  device events, and the device PATCH writes notes. `POST /api/stock/reconcile`
  takes the devices a count found — by id or by the serial a scanner read —
  reverses each `auto` FIFO pick that contradicts it, and refills the slot from
  stock, oldest produced first. `dry_run` is the default, so the first answer is
  always the plan. See
  [decision 0027](docs/decisions/0027-a-stock-count-corrects-a-fifo-guess.md).
- **A `shipped` event somebody typed is never reversed by a count.** The call
  fails and names those devices. A count says where a device is, not who is
  wrong about it.
- **Reversing a delivery no longer reads as a second one.** `DeviceEvent` is
  append-only, so an `unshipped` event lands after the `shipped` event it
  reverses without removing it, and every fulfilment and cost figure counted
  raw `shipped` rows. `live_shipped_events` now pairs the two, and
  `line_shipped`, the order line counts and `order_economics` all read it. This
  also fixes the swap in `_swap_into_line`, which had been inflating a line's
  `qty_shipped` by one for each correction it made — no production order had a
  return yet, so no recorded figure changes.

## 2026-09-17 (the marking bench survives its second device)

- **The agent no longer wedges after one mark.** A bench marked one unit and
  then refused every following one with "the agent is already marking" until it
  was restarted, which cost a restart per device. The agent's health poll and a
  mark each bind the same UDP reply port, and `SO_REUSEADDR` does not let two
  sockets share a UDP port on macOS — the second bind gets errno 48. The
  marking thread built its LightBurn client outside the `try` whose `finally`
  clears the "busy" flag, so the losing thread died before that line, the flag
  stayed set for good and nothing was written to any log. The two now take one
  lock, a poll that finds a mark running answers without binding, and the
  client is built inside the `try`. `_run` and `_print` also gained the
  catch-all `except` that `_esp` already had, so a thread that dies says so in
  the job and in the agent's log. Reproduced and fixed against the bench:
  unpatched, 1 mark passed and the next 19 were refused; patched, 20 of 20
  passed under continuous health polling, then three full sessions on real
  hardware.
- **A quiet device no longer reports a false agent timeout.** The console long
  poll is held by the agent for 10 s and the page aborted at exactly 10 s, so
  any 10 s silence was a coin flip that produced "the bench agent did not
  answer within 10s" from a poll that was working. The page now allows the
  hold plus 5 s.
- **`mark.py` runs again.** The command-line marking tool called `time.time()`
  without importing `time`, so it raised `NameError` on its first line. The
  agent itself was unaffected.
- **A finished mark is machine-proven.** With the laser attached, LightBurn
  answers `STATUS` with `!` for every poll while a job runs and `OK` when it
  ends, measured twice at 9.7 s on the dongle side artwork. The code carried a
  "NOT YET VERIFIED" note saying to treat a mark as operator-confirmed until
  someone checked this on the bench; that note is now the measurement.

**Benches must download the agent again** from the Flasher page. The fix is in
`agent.py`, and an installed copy carries the old one. `PROTOCOL_VERSION` is
unchanged at 4 because no route changed, so nothing will warn you.

## 2026-09-17 (device files know what they are, and the procedure editor grows up)

- **A device file is berryware or artwork, and every screen says which.** The
  pool held the LightBurn `.lbrn2` a mark version engraves beside the `.be`
  scripts a device downloads, and the version card, the diff, the timeline
  line, the bench summary and the pool all called both "berryware". A `kind`
  column on the file now drives the label: a mark version's card reads
  **Artwork**, its change summary reads "artwork (1 changed)", and the pool
  shows a kind pill per row. Backfilled from the extension
  ([decision 0026](docs/decisions/0026-a-device-file-carries-its-kind-and-enters-by-upload.md)).
- **Files are uploaded, not pasted.** The paste-the-text editor on the
  Individual files tab is gone. **Upload a file…** takes one or many files and
  publishes them; an artwork row has its own **Upload** for a new version
  under the same name; berryware rows have none, because the Bundles tab's
  folder import is how berryware is updated. A file that is not UTF-8 text is
  stored and served as bytes instead of being refused.
- **The marking step owns its artwork.** `Engrave the serial` shows the pinned
  drawing's own LightBurn thumbnail, a picker over the project's artwork, and
  **Upload a new .lbrn2…** — the upload publishes into the pool and re-pins
  the draft in the same action. The server refuses a non-LightBurn file there.
  The engine now hands the laser only artwork and the device only berryware,
  and the publish gate says "pins no artwork (.lbrn2)" instead of "no template
  file".
- **The pool says what is in use, previews any file, and deletes one version
  at a time.** A **Used** column reads "in use" or "not used" from the same
  join the delete guard uses; the eye button opens a popup with the LightBurn
  thumbnail and the full text (or, for a binary, its size and a Download);
  the row's × removes the newest version and the server still refuses a
  pinned one. Every version row shows who pins it.
- **A finished device's verdict no longer greets the next one.** PASS, FAIL and
  ABORTED survived a device swap on both benches, so a unit arrived under the
  previous one's result. The verdict, the step label, the progress bar, the
  engraved and printed readouts and the run link now clear when the next device
  arrives — not when the finished one is removed, so the operator still reads
  PASS with the part in their hand. The log is kept, with a line marking where
  one device ends and the next begins.
- **The benches open ready.** Picking a project on the flashing bench now
  selects its latest batch (newest run date) as well as its config version;
  the marking bench selects the project's marking procedure. Clearing the
  batch to "bench trial" sticks until the project is picked again. This
  reverses the 2026-09-16 rule that left the batch empty on purpose.
- **The label is drawn before it is printed.** A `print_label` step now shows
  the label as the bench agent will lay it out — the Code 128 symbol and the
  value under it, at the roll's true proportions, turned when the step says
  so — for a sample serial the author can change, and prints the agent's own
  refusal in red when the value does not fit ("needs 47.5 mm, this roll prints
  22.9 mm across") before the printer ever sees it. On the bench machine the
  roll is picked from the printer's own list and the printable area is the
  printer's; anywhere else the label is drawn at its nominal size and the
  caption says so. `web/src/flasher/label.ts` mirrors the agent's encoder
  and layout, checked module-for-module against it.
- **The procedure has an edit mode.** A draft opens read-only and **Edit
  procedure** turns it into a form; a published version offers **Edit as new
  version**, which mints the draft and opens it editing (so does **New
  version**). Every field is a typed control: a duration is a unit box (type
  `500ms`), a count a number box, a flag a checkbox, a value a
  value/parameter toggle; command, capture and image lists are numbered rows
  that move up and down; a step can be duplicated. Typing is saved after a
  pause instead of on every keystroke, and flushed before a publish.

## 2026-09-17 (the bench agent stops hanging)

- **The 7Sigma agent no longer freezes.** Its window, its status page and the
  bench's `/ready` call each asked CUPS for the printer picture on their own
  and at once, and one of those calls (`lpinfo -l -v`) takes 5.5 s on a Mac
  with nothing plugged in — the window ran it on its own main thread every
  second. Measured before: `/ready` 25 s, the status page 31 s. After: both
  under 0.1 s. One watcher now takes the picture every 10 s and everything else
  reads it. **Benches have to download the agent again** — nothing updates it
  in place, and `/hello` reports the same protocol as before because no route
  changed.
- **A printer button waits for its own result.** "Set up" and "Remove" refresh
  the picture before the page reloads, so the queue they made is on it.

## 2026-09-17 (a device fetches from its own address)

- **Berryware downloads work on production.** Step 16 of `Dongle_V2 config` had
  never run there before, and it failed every retry with `TLS connection error
  296`: the device was sent `https://disfunction.cc/lib`, and a Dongle V2
  completes **0 of about 12** HTTPS attempts against the Cloudflare edge. Over
  plain HTTP by name it succeeds every time.
- **`DEVICE_BASE_URL` is a new setting**, ranked above `PUBLIC_BASE_URL` when the
  engine picks the address a device fetches from. Empty by default, which means
  "the same address browsers use". Production sets it to
  `http://disfunction.cc/lib`. No deployment version changed and none needed
  re-publishing — no step overrides the download URL.
- **Stated rather than buried**: the scripts now cross the internet in the clear,
  and the download step still verifies the byte count rather than the sha256 it
  already holds. Tasmota validated no certificate before this change, so HTTPS
  was buying the device encryption to an unverified peer and nothing else. Full
  reasoning and the measurements in
  [decision 0025](docs/decisions/0025-a-device-fetches-from-its-own-address.md).

## 2026-09-17 (settings that touch hardware live on the platform)

- **The transport profiles left the browser.** The baud a device is flashed at,
  whether a reset re-enumerates USB, and whether the console may touch DTR/RTS
  were TypeScript constants in `station.ts` — so changing any of them needed a
  web deploy and moved every deployment on that profile at once. They are in
  `services/flasher/transports.py` now, `/meta` serves them, and the engine
  sends the resolved profile with each run.
- **A step states its own serial baud.** `esp_connect`, `erase` and `flash` take
  a `baud`, editable in the step editor, blank = the profile's default, and
  refused at publish if the bench cannot speak it. Measured on a Dongle V2:
  **460800 = 45.4 s, 750000 = 32.5 s**, while 576000 and 921600 corrupt the
  transfer — the CH340's 12 MHz clock divides exactly into 750000 and not into
  the others.
- **Three more constants followed**: what a marking template says where the
  serial goes (the browser decided what got engraved), the label rolls (its own
  comment said "add a row here when a roll is bought"), and the serial length
  bounds. All now come from the platform or the printer's own PPD.

## 2026-09-17 (light or dark, and the platform remembers which)

- **The platform can be set to light or dark, on Account → Appearance.** Three
  choices — System, Light, Dark. System is the default and follows the operating
  system, including a change made while the page is open.
- **The choice is stored on the ACCOUNT, not in the browser.** Signing in on the
  bench machine gets the same platform as the laptop, with nothing to set twice.
  The browser still caches it, because the theme has to be applied before the
  page paints and the sign-in request has not answered by then.
- **Kuba Remian's account was set to dark** on the production platform.

## 2026-09-17 (an out-of-date bench agent says so)

- **The flashing bench refuses to start a run against an agent that cannot
  program**, and says which it is. The agent is DOWNLOADED, not deployed, so a
  bench can be weeks behind and look healthy: one was, and the run failed
  part-way with the agent's own 404 — `no such path` — after a device was
  already in the socket. The page now asks at `hello` and shows a banner, and
  the relay refuses before it touches the device, because a banner can be
  scrolled off.
- **It tests the capability, not the version.** `/hello` reports the esptool the
  agent carries, and that is the question. `PROTOCOL_VERSION` had been left at 3
  through the change that added programming, so the number could not tell the
  two apart — it is 4 now, but nothing depends on it for this.

## 2026-09-17 (a version says which parameters it needs)

**Editing a project's parameters can no longer break a version published months
ago without telling you** ([decision 0024](docs/decisions/0024-a-version-declares-the-parameters-it-needs.md)).

- **A deployment is linked to a parameter set, and says so under its
  description.** The link used to exist only on each version, picked inside the
  composer — so a new deployment was wired to nothing and you found out when a
  publish was refused for an unresolved `{MqttHost}`. A new deployment in a
  project with one set now takes it, its first version inherits that, and later
  versions inherit from the version they were composed from. A published version
  keeps the set it was made with whatever the deployment does later, and its
  card says **deployment now defaults elsewhere** when the two differ.
- **A new version is edited where it is read, not in a popup.** `New version`
  creates the draft, selects it, and the card on the right becomes the editor —
  note, procedure, transport, monitor baud and parameter set, each saving as you
  change it. The `Composer` modal is deleted: it rendered the same four sections
  a second time over the top of the read-only ones, so a procedure had two
  renderings and they had already drifted on which controls a section carries.
- **A version can be removed.** `Delete this version` on any draft or rejected
  version takes it out entirely rather than leaving a rejected row behind. It is
  refused for a published version — that is what a device was given — and for
  any version a programming run records, which keeps the old reject-as-history
  behaviour where it belongs.
- **The kind dropdown is three words.** `flash · test · mark`, with what each
  one does on the ⓘ instead of inside every option.
- **A new deployment is an empty card, not two prompts.** The + tile creates
  the row, selects it and puts the caret in the name — the two `prompt` dialogs
  asked for the same fields the card already holds, so the answers were typed
  twice. Pressing + twice gives "New deployment 2" rather than a unique-key
  error.
- **Chip is a dropdown everywhere.** The platform knows which parts it supports,
  and the validator refuses a version whose transport does not match its chip,
  so a free-text box could only ever produce a typo that fails at publish. A
  blank option stays — a mark or test procedure legitimately has no chip.
- **Parameters have their own page**, `Production → Parameters`. They were a
  fourth tab under Files, beside firmware images and berryware bundles — but a
  parameter is not an artefact a version pins, it is what a version depends on
  and does not contain.
- **Each key says which published versions need it.** `Dongle_V2 config` v10
  needs seven keys and v18 needs four, both pointing at the same set; removing
  the three v18 stopped using breaks v10, and nothing said so until a run was
  attempted with a device in the socket. Removing such a key is now **refused**,
  naming the versions. Deleting a set in use is refused too.
- **A history of what moved.** Every save appends a revision with a note: which
  keys arrived, which left, and which changed value. A key whose NAME survives
  and whose MEANING changes — a broker repointed, a salt rotated — used to pass
  every check the platform had. Each programming run now records which revision
  it used, so a unit can be traced back to the values it was given even though
  the secrets themselves are never stored twice.
- **A draft run is validated like a published one.** It was exempt, and that is
  where it mattered most: an unresolved `{MqttHost}` is left as literal text,
  the step that writes it compares what it sent against what it read back, and
  the device shipped configured against a broker called `{MqttHost}` with the
  run reporting **pass**.
- **The history can be reverted to.** "Revert to this" on any earlier revision
  puts those values back — including the secrets — and **appends** rather than
  rewinds: reverting r5 to r2 writes r6, so the record still says r3-r5 happened
  and that somebody undid them. The same refusal applies, since an old revision
  can be missing a key a version published since then needs.
- **Editing is in place.** The Parameters page IS the editor: type in the row,
  and Save, Cancel and the note appear only once something differs from what is
  stored. No dialog, and values are shown in the clear — a parameter is a bench
  setting you came to the page to read, and it is already behind the sign-in
  gate. Storage is unchanged: the set is encrypted at rest either way.
- **A key nothing reads is marked `unused`.** Which versions DO need it is on
  the × and in the refusal — a parameter set belongs to one project, so listing
  them was a wide column naming siblings of the project already selected.
- **The deployment page lost what it did not need.** The tagline is gone, the
  deployment list is tiles with a **+** to add and a **×** to remove, and the
  `→ production` / `→ bench` buttons are gone from every version row — they
  pointed a channel a batch could follow, and no batch in the database follows
  one. Version rows went from 96 px to 78 px, so all seven fit on one screen.
- **`creds_salt` is counted.** `derive_credentials` reads it directly instead of
  interpolating it, so the one key whose loss cannot be recovered from at the
  bench read as "needed by nobody". A version missing it now fails to publish
  rather than failing mid-run, after the erase.

## 2026-09-17 (the bench sets its own printer up)

**A new bench no longer needs anyone to know how CUPS works.** The agent's
status page now says what is missing and gives you the button that fixes it.

- **The printer is found, matched and set up by the agent.** It names the
  printer that is plugged in, matches its driver exactly, builds the queue, and
  repairs a queue that is on the wrong driver. None of it needs a password.
- **It refuses to guess.** CUPS offers five DYMO drivers that look plausible for
  a LabelWriter 550 and only one that works; a queue on any of the others
  accepts jobs, reports success and prints nothing. Measured, on a powered
  printer, which is why the match is exact rather than "close enough".
- **The one step it cannot do is named plainly**: install DYMO Connect for
  Desktop once, with the brew command offered for copying. The application can
  be deleted afterwards — the bench uses only the driver it leaves behind.
- **The queue is built without being asked.** A printer that has a driver and
  no queue gets one within ten seconds of being plugged in. A queue on the
  wrong driver is still repaired by the button, not silently.
- **A console nobody is using gives its port back.** Closing the tab used to
  leave the serial port held until the agent was quit, and anything else
  wanting that port was refused. After two idle minutes the agent closes it —
  never during a mark, a print or a flash.
- **LightBurn gets a button too**: not installed offers the download, installed
  but silent offers to open it.
- Everything the page shows is also served at `GET /ready`, so the bench page
  and the status page cannot end up giving different advice.

## 2026-09-17 (a deployment card you can read)

- **The version's note is prose, under a label.** It was drawn in the caption
  style — 11px uppercase mono — run together with the author and the date, so a
  five-line paragraph looked like a heading nobody could place. It now says
  **Note on this version** and reads as a sentence. The caption keeps the short
  facts: who, when, and what changed.
- **The description box fits what is in it.** Two fixed rows hid the second half
  of every description behind an inner scrollbar with nothing to show it was
  there. It grows to its content and stops at 14 rows.
- **Name and Chip share a line**, the three permanent hint lines are ⓘ markers
  on the labels, and **New version** moved down to the versions bar where it
  acts. The card lost 68 px while showing 67 px more description.
- **The page is two columns, and the wide one is the procedure.** The left
  column used to be a picker for three deployments; they are tiles across the
  top now, keeping the pills that say which version each channel runs. The
  detail column went from 660 px to 864 px at a 1500 px window, which is the
  difference between `Write factory image …` and the whole step with its
  command and value. **The procedure also moved above firmware and berryware**,
  which are one table row and one pill and were pushing 28 steps off-screen.
- **A version row no longer repeats the note.** Seven versions of one deployment
  open with the same sentence, so a clipped copy per row told them apart not at
  all. The row keeps what changed; the note is on its hover and in full on the
  card.

## 2026-09-17 (find the socket by plugging the device in)

- **Assign socket… is a live list.** It opens even when nothing is plugged in,
  watches the agent's ports while it is open, and marks anything that appears
  as **new**, at the top. Plug the device in with the dialog open and take the
  row that appeared — the same trick Chrome's port picker used, now against
  the agent's real `/dev/cu.*` names. Both benches use it.

## 2026-09-17 (the bench asks one question about a batch)

- **One dropdown, not two.** The flashing bench had a `batch run` / `bench
  trial` select beside the batch select, so "batch run" with nothing picked
  was a state it had to warn about and which disabled Automatic. Now the batch
  dropdown starts with **no batch — bench trial**: picking a batch makes the
  run production, leaving it makes it a trial that may run a draft.
- **The Test button is gone from a station.** A test is an ordinary deployment
  with `kind: "test"` — pick its version and press Program. The button ran a
  different version than the one on screen.

## 2026-09-17 (a deployment is configured on its own page)

- **The WiFi, MQTT and the other placeholder values are editable from the
  deployment.** *Edit values…* on a published version's Parameters card and in
  the composer's Parameters section open the same editor the files page uses
  (`ParamSetEditor`); secrets are masked with a show toggle. Both say plainly
  that a param set is shared and not versioned: a change reaches the next run
  of every version that points at it.
- **The deployment's own fields are boxes, not prompts.** Name, description
  (stored on every deployment and never shown until now), kind, chip and the
  test default for new batches are plain fields on the deployment's card;
  **Save** and **Cancel** appear only once something differs from what is
  stored, and one Save writes the whole row. *New version* sits alone beside
  the name and Delete alone at the far end. It used to be six buttons in one
  wrapping line, each opening a popup.

## 2026-09-17 (the bench is browser-independent)

**The bench agent does every byte of serial work, and Web Serial is gone**
([decision 0023](docs/decisions/0023-the-agent-programs-the-device.md)).
Connect, erase, flash, reset and the device console all run in the agent on the
bench machine, against the socket a station owns. The page names the socket and
relays the log; it opens no port.

- **`Assign socket…` is a list of real port names** — the agent's own
  `/dev/cu.*` nodes, with who holds each — instead of Chrome's port picker.
  A station keeps its socket across replugs and reloads.
- **Nothing to grant and nothing to lose.** No serial permission, no per-unit
  picker on a CH340 that has no serial number, no
  `SerialAllowUsbDevicesForUrls`, no secure-context requirement. A deploy can
  no longer break a bench tab that is open, because nothing in the flashing
  path is lazily loaded any more.
- **The agent download carries `vendor.zip`** (esptool 4.8.1 + pyserial, pure
  Python, 634 KB), extracted once on first start. The agent window and
  `/hello` report which esptool it has.
- **A bench with no agent cannot program**, by design — one implementation, no
  fallback. Both benches say so plainly, and the flashing bench keeps a
  heartbeat so the message is current.
- **Confirmed on hardware, then the browser's flashing dependencies were
  deleted.** Runs 6383, 6384 and 6385 all passed through the agent at 460800
  baud on the first rung, and 6385 joined WiFi and pulled its 18 configuration
  files — so `esptool-js`, `js-md5` and the Web Serial types left
  `web/package.json`. The bundle no longer carries a chip module at all.

## 2026-09-17 (a deploy no longer breaks an open bench tab)

- **A bench tab opened before a deploy failed every connect as "BOOT was not
  held"** (prod run 6329). esptool's chip module is a lazily loaded, hashed
  chunk; the deploy replaced it; the browser could not fetch it; and the
  connect ladder treated that as a device that would not answer. The page now
  reloads itself once when a chunk is missing, and the ladder stops at once
  with "this page is out of date — reload" instead of walking its rungs.
- **A mark is now machine-checked.** The first production mark showed
  LightBurn's `STATUS` reporting busy for the whole 10.5 s job, so a job that
  reports idle immediately did not run. Recorded in
  [docs/reference/laser-marking.md](docs/reference/laser-marking.md).

## 2026-09-17 (deployments can be published and re-kinded from the page)

- **A draft version has a Publish button on the timeline.** Publishing lived
  only inside the editor, so a draft finished anywhere else — the API, another
  machine — had no status control at all. Same server gate: no comment or a
  validation error still refuses, and says which.
- **A deployment's kind is a button next to its chip** — flash, test or
  mark. The bench reads the kind, never the name, and it could not be changed
  after creation.
- **The version editor scrolls.** A procedure with 28 steps made the card
  taller than the window, the page behind it is locked while a modal is up,
  and the Publish button sat below the fold with nothing able to scroll to
  it. Every modal's backdrop now scrolls, and a wide card starts near the top.
- **The flashing bench keeps a heartbeat to the agent** and says whether it
  is running, so the agent's own window no longer reports that no bench page
  has ever connected.

## 2026-09-17 (the laser marks)

**The AtomStack M4 marks from the platform for the first time.** Since the
marking bench was built it had traced every job with the pointer and engraved
nothing; a clean LightBurn install had the board in fibre mode with no analog
power output, and "Require framing before start" turned every `START` into a
framing pass. The machine's whole configuration — laser mode, the analog power
line, the port map for the pointer and the second source, how a layer picks
the 1064 nm or the 450 nm source — is now measured and written down in
[docs/reference/laser-marking.md](docs/reference/laser-marking.md).

- **A `mark_laser` step's `device` names a LightBurn PROFILE, not a source.**
  The doc and the field's hint said the agent's `LASER:` command chose which
  laser fired. It does not: the artwork's layers do, and the profile only
  carries the calibration for one of them. The profiles are now named
  `M4 IR 1064nm` and `M4 Diode 450nm`.
- **`AQUA_DONGLE_Side_Info.lbrn2` v3**: the serial layer at 100 % and
  600 mm/s, measured on white ABS, and `DeviceName` set to the IR profile. The
  marking draft (Dongle_V2 marking v2) pins it and names the IR profile; it is
  still a draft.
- **The agent window shows its five facts, and has a status page.** The
  window was blank because the Tk that macOS's own Python carries draws no
  text in any widget except native buttons and the title bar (measured with
  screenshots). It is now five flat buttons — Listening, LightBurn, Printer,
  Chrome, Bench page — with the verdict in the title, and each opens
  `http://127.0.0.1:19842/`, a self-refreshing page with the full text and
  the log. "Open the log" opens the log file itself.
- **The agent reports whether the laser is actually there.** `GET /health`
  carries `laser_usb` — the controller board seen on the bench machine's USB
  bus, or not — because LightBurn's `STATUS` answers `OK` with the board
  unplugged. The agent window has a Laser row for it, and the marking
  station's Laser box says **no laser on USB** and disables Mark when the
  board is missing, instead of "ready".
- **The flashing bench offers the agent, not the setup profile.** The agent
  grants the Chrome serial and loopback policies itself on first start, so the
  `.mobileconfig` link on the bench is gone; the endpoint stays for machines
  with managed Chrome settings, where only an administrator can install it.
- **The agent's Chrome row knows about managed profiles.** A profile in
  `/Library/Managed Preferences` overrides the agent's own grant, so the row
  now says *granted by a managed profile* when one carries the grants, and
  names what a managed profile lacks when it does not — instead of reporting
  the agent's own write as if Chrome were reading it.
- **The two LightBurn profiles live in the repo** —
  `docs/reference/laser-marking/`, with the vendor calibration files and a
  script that writes them into a fresh LightBurn.
- **The agent refuses to switch LightBurn profiles mid-session.** LightBurn
  only connects the profile it started with; a switch answers `OK`, shows
  "Disconnected", and `STATUS` keeps saying `OK`, so the job would report
  success and mark nothing. The first `device` a job names is the session's
  profile; a job naming another fails before anything is loaded, with the
  instruction to restart LightBurn on that profile.

## 2026-09-17 (the marking bench prints labels)

**A device gets its barcode label from the same bench that engraves it**, off
the same reading of its serial, with no DYMO software on the machine. The
printer is a DYMO LabelWriter 550 on the bench agent's own machine, driven
through CUPS.

- **The marking station is now one box with two columns.** Left is the device:
  its serial, its port, and what the station is doing. Right is one box per
  machine — Laser and Printer — each with its own status above its own button.
  A laser that is not answering and a printer with no roll are fixed in
  different places, and one status pill sent the operator to the wrong one.
- **A chain between the two boxes links them.** With it on, one press of Mark
  engraves and then prints the label, so a bench that does both keeps the
  trigger instead of switching on two automatic passes. It refuses to start
  while the printer is not ready, rather than engraving a part it cannot label.
- **Automatic is two checkboxes, one per machine.** A bench can engrave all day
  and print nothing, or print while the laser is down. Each arms only when its
  own machine is ready.
- **Both buttons run the same procedure.** One marking version reads the device
  once and then engraves, prints, or both; which one a press asked for travels
  with the run. The engine allows that for those two actions only, so a bench
  cannot change what a unit was made under.
- **A `print_label` step IS the label definition** — a Code 128 barcode of the
  value with the value under it. Nothing is pinned to the version for it,
  because a generated label has no artwork. The roll is a station setting: the
  printer cannot report what is loaded in it.
- **A print is proven, not assumed, and it finishes when the label is out.**
  The bench waits for the printer to report that it printed the page and the
  backend to finish sending, with no fault standing. It deliberately does not
  wait for CUPS to retire the job, which takes a further seven seconds during
  which the printer does nothing — that turned a two-second step into nine. The
  printer's own progress now appears in the run log, and a failed print cancels
  its own job rather than leaving one queued: a waiting job resumes the moment
  the roll goes back in, which would print a stale serial onto the next unit.
- **The bench reads the device when you plug it in**, not when you press a
  button. The serial appears in the box straight away, so it can be checked
  against the part first, and the run leaves out the step whose only job was to
  wait for the firmware — 0.7-1.1 s off every press. The run still reads the
  identity itself, so nothing is taken on trust. Both buttons stay disabled
  until the device has answered, and the box says what it is waiting for.
- **A serial is checked before anything is put on a part**: 8 to 12 characters,
  no spaces, whether it was typed by hand or read off the device. The bench says
  which rule a value broke, and the engine refuses it too — a capture that went
  wrong used to reach the laser as whatever string it happened to produce.
- **A typed mark is no longer recorded**, and a typed label is not either. It
  names no run and proves nothing about a unit.
- The bench agent is at protocol 3. An older one has no printer routes, and the
  bench says to download it again.

Decision: [0022](docs/decisions/0022-labels-are-generated-by-the-bench-agent.md).
Measurements: [docs/reference/label-printing.md](docs/reference/label-printing.md).

## 2026-09-16 (marking is a run, and the laser is not ours to drive yet)

**The marking bench exists.** Plug a device into the laser machine and it is
read, patched into the artwork and engraved, with a run record and a log like
any flash. It is a separate page from the flashing bench: one laser, one
station, and it starts itself when a part arrives.

- **A marking procedure is an ordinary deployment version** with kind `mark` —
  its own steps, its own pinned artwork, the same publish gate. The `.lbrn2` is
  pinned as a device file exactly like berryware, so the run record answers
  which drawing a unit got. The new step is `mark_laser`.
- **The laser is reached through LightBurn and a small local agent**
  (`api/app/services/bench_agent/agent.py`), not a direct USB driver. The direct path
  was probed on the hardware and rejected on evidence: the BSL controller
  (`04b4:1004`) answers every EZCAD2 opcode with the same idle frame, so the
  open-source LMC drivers do not apply, and decoding its own protocol needs a
  USB capture that no machine here can take. Decision
  [0020](docs/decisions/0020-marking-goes-through-lightburn.md), measurements in
  [docs/reference/laser-marking.md](docs/reference/laser-marking.md).
- **The agent holds no token and never reads the artwork.** It receives a
  finished job and points LightBurn at it. It listens on loopback only and
  checks the Origin of every connection, because Chrome's local-network prompt
  is asked once and after that any page could reach it.
- **The bench profile now carries the loopback grant too**, so a configured
  bench never prompts for the agent connection.
- **A mark is operator-confirmed, not machine-proven.** LightBurn answers `OK`
  to `STATUS` and `START` with no laser attached, so neither proves a part was
  engraved. That stands until `STATUS` is seen reporting busy during a real job.
- **A deployment's kind can finally be SET.** It became readable when the bench
  learned to offer the right button, but nothing could write it — a marking
  deployment could not be created at all. `POST`/`PATCH` take it now, and the
  PATCH leaves it alone when omitted, so an edit form that does not send it
  cannot silently turn a test deployment back into a flashing one.
- **`mark.serial` is a named check**, in its own "marking" category: a unit can
  be fully working and unmarked, so it does not belong under hardware.
- **A bench station is bound to a USB socket at last.** Assign a socket once and
  the station takes that cable and no other, across replugs and reloads, with
  the real port name (`/dev/cu.usbserial-110`) on the card. Nothing is adopted
  automatically any more: an unassigned station stays empty however many devices
  are plugged in. Arrival order is gone — it handed station 1 whatever turned
  up, so moving a cable silently moved the station and nothing said so. The
  flashing bench now wants the agent running too; without it, assignment still
  works for the session but the station cannot remember its socket.
- **The agent can see the serial ports, which is what made that possible.**
  `GET /serial-ports` lists every USB serial node and, from `lsof`, which
  process holds each one. macOS names a node after the USB location, so the name
  IS the socket — and "who holds it" is the correlation a page cannot make on
  its own: open one port, ask the agent which node Chrome just took. Binding a
  station to a socket was documented as impossible from the page alone, and that
  is still true; what changed is that a process outside the page now exists. The
  bench does not use this yet — see `docs/todo.md`.
- **The download sets the browser up too, with no administrator rights.** On
  first start the agent grants this bench's origin the USB serial adapters and
  the loopback connection, merging with anything already there, and asks for
  Chrome to be restarted once. Chrome reads policy from the user's own defaults
  domain as well as from managed preferences, and only the second needs root —
  so one download now covers the whole setup. `--no-browser-setup` turns it off,
  and a machine carrying the bench profile is unaffected: a system profile
  outranks it.
- **A marking step names its laser SOURCE.** This marker carries two, a fibre
  and a blue, and LightBurn holds them as separate devices. `mark_laser` takes
  `device:`, and the agent sends `LASER:<name>` BEFORE loading the job, so a job
  cannot be fired from the other source. The agent also reports what the machine
  has, so nobody guesses the spelling — a wrong name is refused, not ignored.
  Needs LightBurn 2.0+; it answered `!` on 1.7.03.
- **The agent is a macOS app called 7Sigma Agent**, and it starts LightBurn for
  you. It ships as an app rather than a terminal
  command: a small window with the log, the laser's state and a Quit button.
  It is named for the bench, not for marking, because it will pick up the jobs
  a browser cannot do as they arrive — label printing next. On start it opens LightBurn if LightBurn is
  silent, waits for it to answer, and says plainly when it does not — naming the
  two causes that look identical, a dialog waiting for a click and a Core
  licence. The window is tkinter, so it still installs nothing; when no
  available Python has tkinter it says so and runs without a window instead of
  failing.
- **The marking agent is a download.** The bench offers a zip; expand it,
  double-click *7Sigma Agent*, done. The launcher carries that bench's
  own address, so there are no flags to type, and it is an archive rather than
  a bare file because a download loses the execute bit while a zip keeps it.
  Its source moved to `api/app/services/bench_agent/` for the same reason the
  KiCad plugin lives in the api package: the platform serves it, and `clients/`
  is not in the image.
- **The marking agent needs nothing installed.** It speaks plain HTTP from the
  standard library, so whatever Python 3 is already on the laser machine runs
  the file as it stands — verified on macOS's own 3.9.6 with no venv and no pip.
  It was a WebSocket for an afternoon; the one dependency that required was the
  only thing standing between an operator and a working bench.
- **If LightBurn stops answering, check its tier.** LightBurn *Core* cannot
  drive a galvo — EZCad2 and BSL controllers are Pro — and the symptom is not an
  error but silence: the UDP port stays open and every command is ignored. An
  upgrade put this bench on Core and cost an hour before the title bar was read.
- **A mark can be run by hand.** Type a serial, press Mark: no device in the
  loop, for a unit that is dead, uncased, or whose label was spoiled. Same
  template, same placeholder, same agent as a run — only the source of the
  string differs. It lands in the device's history like an erase does, but only
  when what was typed is an identity: 12 hex characters become the MAC, and
  anything else is engraved with the card saying plainly that it will not be
  recorded.
- **The marking station uses the width it has.** One laser means one station,
  so it is laid out in two columns across the page instead of reusing the
  narrow card that exists to fit four side by side, and it shows what was
  engraved in large mono — the operator checks that against the part, not
  against the log. Renaming it no longer renames flashing Station 1.

## 2026-09-16 (a device is proven by its newest run, not by its best one)

**"What this device is proven to do" counted the best result ever recorded per
check, so a unit whose newest attempt failed, aborted or was still running kept
a full green grid from an earlier pass.** That grid is the answer to "is this
unit programmed", and it said yes about units that were not.

- **The device grid now shows the NEWEST run only.** A green cell means that
  run measured it and it passed. Nothing survives a later attempt. The lifetime
  tally stays on the cell hover (`attempts: 3× pass`), so earlier evidence is
  not lost, only demoted.
- **The card states the verdict**: `programmed` or `not programmed`, with the
  run that decided it. A run that is still going, a run that failed or aborted,
  and an erase all read `not programmed` — an erase records `pass`, because the
  erase worked, and that is not the same as a programmed device.
- **The Devices list agrees** wherever it reports a check, because it counts
  the same newest run.
- **PASS and FAIL are no longer the same grey.** The Result column took its
  colour from `STATUS_TONES`, which had no entry for a run's own words, so the
  one column you scan down a 5427-row list said nothing at a glance. Pass is
  green, fail is red, aborted is amber, everywhere a run status is printed.
- **One device is one row, and nothing in it is cut.** The device list carried
  twelve columns in a table that is 1050 px wide on a laptop, so most of them
  were ellipses. Four are gone: **Name** (the serial with a `dongle_` prefix,
  and the search box still matches it), **Project** (the selector above the
  table), **IMEI** (blank on every unit without a modem) and **Checks** (it
  said `4/4` beside a Result that already said PASS — what a run proved lives
  on the device page). What is left — serial, MAC, chip, batch, where it is,
  runs, result, last seen — prints whole from 1100 px up. Column widths on the
  device list and the programming history were re-cut from measured content.
- **A run's duration reads in minutes** above a minute: `3m 24s`, not
  `204.3 s`.
- **"Programmed" now means what the batch asked for** — see
  [decision 0021](docs/decisions/0021-a-device-is-judged-by-the-rule-it-was-made-under.md).
  A device's history holds programming runs, test sweeps, marking jobs and
  erases, and they do not all say the same thing about the unit. The verdict
  reads: the newest **config** run passed, any **test** that started after it
  passed, and no **erase** since. **Marking never changes it.** A test that ran
  and failed always counts, even when the batch asked for none; a test that did
  not run counts only where it was required.
- **A batch carries the test requirement, and every run keeps a copy.** "Units
  of this batch must pass the test" sits on the batch (Devices tab of a
  production run) and is copied onto each programming run when it starts, so
  changing it affects work still to be made and never re-judges a device on the
  shelf. A test deployment's flag in the Deployments tab is now only the
  default ticked on a new batch. **The migration lands with no test required
  anywhere** — every existing batch and run says false, and every test
  deployment starts off, so a deploy changes nothing about devices already
  made. Turn a product's test on when its flow is ready: the Deployments tab
  for new batches, the batch's own Devices tab for one batch. Measured with
  nothing required: of 990 Aqua devices 914 read programmed, and the 76 that do
  not are the ones whose newest test actually failed.
- **The device page fits on one screen.** "Where it is" took half the right
  column whatever it held — four event rows and a button — so the programming
  history started below the fold. It now takes what it needs and the history
  gets the rest. The history's own columns were re-measured at the same time:
  the start time can no longer be cut, and `By` (which now carries a real
  account name) truncates with the full name on hover.
- **A device page no longer prints fields the product does not have.** A
  Dongle_V2 has no modem, so IMEI, ICCID, IMSI, Modem and Modem firmware were
  five dashes on every one of 4400 units. A row is drawn when the device
  carries the value, when one of the project's procedures captures it, or when
  any sibling device in the project has it — so a Dongle_V3 still shows its SIM
  rows before the first unit is programmed, and imported history stays readable
  after the procedure that produced it is gone. The page holds no list of
  fields at all: the server sends the rows with their labels, so a new
  identity field appears without touching the frontend.
- **The configuration card shows what is on the device now**, written by the
  last run to configure it, instead of every value it ever carried — one device
  printed twelve rows of the same three keys. Earlier values are kept and stay
  reachable through their own run.
- **The flash bench can program on plug-in.** "Program automatically when a
  device is plugged in" arms every station: the run starts the moment a device
  appears on that station's port, so a tray of dongles is plug, wait, unplug.
  It is **off by default and remembered per browser once you turn it on**,
  because a programming run erases the device before it writes — the marking
  bench, which does nothing destructive, keeps arriving armed. Each station
  arms ONCE per device: a unit left plugged in after its run is not programmed
  again, and a unit that failed does not retry in a loop — pull it out and the
  station re-arms. The box is disabled until a batch is picked, so auto-start
  can never turn a batch run into a bench trial.
- **The bench opens ready to work, and never on a batch you did not pick.**
  Choosing a project now fills the version box with that project's config
  procedure (its `kind: "flash"` deployment, current version), which is what a
  batch is programmed with all day and was a click at the start of every
  session. The batch dropdown is the opposite: it starts empty every time,
  is never remembered across a reload, and until it is picked the stations
  refuse to start — a batch run with no batch used to be recorded as a bench
  trial. The override-reason box now appears only when the chosen version
  really differs from the one the batch is assigned.
- **The bench asks only for what the procedure uses.** The SIM PIN box appears
  only for a procedure that has an `lte_sim_pin` step — Dongle_V3 today. A
  Dongle_V2 and an Aqua have no modem, and the box was asking for a secret
  that had nowhere to go. A hidden box also stops sending its value.
- **The operator text box is gone; a run is stamped with the signed-in
  account.** `operator` was never device configuration — no procedure in the
  library uses it — it is the record of who was at the bench: the By column in
  a device's history, the actor on the `produced` stock event, and the audit
  line when somebody overrides a batch's assigned version. A name somebody
  types is not that record. The API no longer accepts an `operator` field on a
  run or an erase.
- **A serial is never cut.** It is the MAC without separators — always 12
  characters — and a truncated serial is not an identity. That column, and the
  last-seen timestamp beside it, are now sized in pixels rather than as a share
  of the window, so they hold their full value at any window width. Checked
  from 900 to 1920 px.

## 2026-09-16 (a board that cannot reset itself can still be programmed)

**One V2 dongle would neither erase nor program from the bench, and chasing it
found three separate faults — two of them ours.** Unit `20:e7:c8:92:b6:10`
resets but never enters download mode: EN responds, IO0 does not. Five reset
sequences driven by hand all ended in flash boot, and `esptool.py` from a
terminal failed identically, which ruled the bench out early.

- **Connecting is now a ladder that escalates by itself**: `default_reset` at
  the profile's baud, then at 115200, then `no_reset` after the bench pulses EN
  with the operator holding BOOT. A healthy unit still connects on the first
  rung in two seconds; a faulty one is asked for instead of failed. The third
  rung exists because esptool-js runs 7 resets per connect, and on a board whose
  IO0 is not driven every one of those undoes the download mode the operator
  just established — **more attempts made it worse**.
- **The rung that worked is recorded** as `connect_mode` in the run's results.
  A unit that only answers with BOOT held has a hardware fault, and quietly
  rescuing it on every run is how that stays invisible until a batch fails.
- **The fast baud is now a preference, not a requirement.** esptool-js changes
  speed by closing and reopening the serial port, which toggles DTR/RTS; on a
  board that resets from that, the stub dies and the next command reads
  `Invalid head of packet`. Any failure at 460800 now retries at 115200, where
  esptool-js skips the baud change completely. Erase uses 115200 outright.
- **Holding BOOT no longer costs the fast baud.** The BOOT rung ran at 115200,
  which turned a 2.3 MB image into minutes for every unit that needed a hand.
  Needing BOOT held and refusing 460800 are two different faults; the rung now
  starts at the profile's baud and drops to 115200 only when esptool reached
  `Changing baudrate` — the one failure that holding BOOT cannot fix.
- **An erase now enters the device's history once it has read a MAC.** A
  `programming_runs` row with `action = "erase"` and no deployment version,
  plus its log. A failed erase used to leave nothing behind, which is how a
  troublesome unit stays invisible until the next batch.
- **An open log no longer drags the page.** Each new line scrolled every
  ancestor, so reading anything else on the bench was impossible while a run
  was talking. The log box scrolls on its own now, and only while the operator
  is already at the bottom of it.
- **Errors carry advice.** A connect failure suggests holding BOOT and says what
  it would prove; a mid-operation timeout points at the cable or socket.

## 2026-09-16 (a replugged device needs no new port grant)

**Swapping one device for the next broke the bench.** After a successful run,
unplugging the device and plugging it back in made the next run fail with
"Failed to execute 'open' on 'SerialPort': Failed to open serial port", and the
only way out was re-picking the port in Chrome's popup.

- **The cause is that the PERMISSION does not survive the unplug**, not just
  the handle. Measured from the run log: after a replug `getPorts()` returns
  **zero** ports and `port.connected` on the held handle is `false`. A CH340
  reports no USB serial number, so Chrome cannot durably identify the device
  and drops the grant with it. Nothing in the page can recover that — there is
  no port to re-acquire, and only a fresh `requestPort()` popup would bring one
  back.
- **The bench now asks for the port inside the Start click**, and only when it
  has no live one. That is the baseline everywhere the platform is not the
  machine's owner: one pick per unit, which Web Serial gives no way around for a
  device with no serial number. `ensurePort()` runs before the run row is
  created, because `requestPort()` needs a user gesture and a gesture does not
  survive a fetch.
- **The bench page now offers a one-time setup file.** `GET
  /api/flasher/bench-policy.mobileconfig` builds a macOS configuration profile
  for the origin the browser reports, and a link at the bottom of the bench
  offers it. The operator downloads and opens it once per machine; after that
  the picker is gone. It grants only the listed USB bridges, never "any serial
  port" — this file goes to people on machines nobody here administers. macOS
  only so far.
- **The same policy can be set by hand on a bench somebody owns, and on a
  dev Mac it needs no root** —
  the user-level `com.google.Chrome` domain is honoured. This machine already
  had `SerialAllowAllPortsForUrls` live for `http://127.0.0.1:5174` from an
  older setup, which is what proved the mechanism. It never covered the bench,
  because policy origins are exact: `localhost` and `127.0.0.1` differ, and so
  do two ports. `scripts/bench-serial-policy.plist` documents both that route
  and the narrower `SerialAllowUsbDevicesForUrls` form for a provisioned bench.
  A device that DOES report a serial number, such as the C6's native USB, never
  had this problem — which is why V3 benches never saw it.
- **`Station.resolvePort()` then picks the port up automatically.** Liveness
  comes from `port.connected`; membership of `getPorts()` is not a liveness
  signal, because the spec hands back the same instance for a device across a
  disconnect. Every open path calls it first, including each retry.
- **`settlePort()` closes a half-open port before opening it.** Chrome can be
  left believing a port is open while the OS descriptor is already gone.
- **A failed `port.close()` is no longer silent.** It leaves the port open, and
  the next open then fails with a message that explains nothing.
- **A station never takes a port another station holds.** Re-acquiring by USB
  ids alone is not safe on this bench: every V2 dongle is the same CH340 and
  every C6 the same native USB device, so one slot could have matched, and then
  tried to open, the port another slot was mid-run on. A claim registry makes a
  station skip a port that is spoken for — which also closes the same hole in
  `awaitReenumerate()`, where it predates this change.
- **The transport profiles are untouched.** Which one applies is still pinned by
  the deployment version, and the C6 rule that the monitor phase never drives
  DTR/RTS is unchanged.

## 2026-09-16 (the bench tells the platform its own address)

**`{base_url}` now resolves from the bench, so a step never needs to know where
the platform runs.** Step 18 of every V2 procedure makes the DEVICE fetch its
berryware over HTTP, and the address it fetched from was a single global,
`public_base_url`. That value is correct on the server and wrong on every
development machine, where it is `localhost` — an address a device on WiFi can
never reach. The engine refused the run and told the operator to edit a setting.

- **The browser reports the two addresses it is provably reaching the platform
  by** (`api_base`, the API origin it calls, and `page_base`, the mount point
  the bench page itself was opened by) in its `hello`. The engine takes the
  first usable candidate in this order: the `base_url` param, `public_base_url`,
  the bench API origin, the bench page origin. The run log records which source
  won and why each skipped candidate was rejected.
- **Configuration outranks the bench, deliberately.** The winner is an address
  the engine then tells a device to fetch from, so a value the browser merely
  asserts is used only where the platform has no usable one of its own. **In
  production `public_base_url` is reachable, wins, and the bench candidates are
  never weighed** — the behaviour there is exactly what it was. Every candidate
  is vetted the same way: http(s), a host, no embedded credentials, not
  loopback.
- **On a development machine, opening the bench by the machine's LAN address is
  now the whole configuration.** `compose.yaml` drops `VITE_API_URL` and sets
  `VITE_API_PROXY`, so dev is same-origin through the Vite proxy the way the
  deployed image is through nginx — no CORS entry, no second origin — and
  publishes port 5173 on every interface, because a device being programmed
  fetches its berryware from it over WiFi.
- **Any op that makes the device fetch something takes a `url` template.**
  `download_files` is the first: leave it empty for the default,
  `{base_url}/api/flasher/files/{file_version_id}/{filename}`. The template goes
  through one resolver (`RunEngine._url`), so `{base_url}` means the same thing
  in every op, and the procedure editor shows the field on the step.
**`flash_config.size: "detect"` could never flash from the browser bench, and
every V2 deployment version carries it.** Found on the first V2 hardware run,
which erased the device and then refused the image with "File 1 doesn't fit in
the available flash".

- **esptool-js accepts `"detect"` in one place only** — the image-header
  rewrite, which detects the size itself. Its fit check passes the literal
  string to `flashSizeBytes()`, which looks for "KB" or "MB", finds neither,
  returns -1, and refuses every image. The V2 procedures were reconstructed
  from a Python esptool, where `--flash_size detect` is valid. `Station.espFlash`
  now resolves the value before esptool-js sees it, so the chip's real size
  reaches both the fit check and the header.
- **The erase runs first, so the failure left the device blank.** That is why
  this is gated at publish now: `validate.check()` refuses a flash size, mode or
  frequency outside the values esptool-js declares, rather than letting the run
  die in the browser with the device already wiped.

- **Publishing refuses a template that hardcodes a loopback host.** It is not a
  value that might work — it is one that cannot, so it is an error rather than a
  warning. Every existing published version validates unchanged.

## 2026-09-14 (`_HandSoldering` and `_Soldering` are retired)

**The house mints no hand-solder token** (user decision 2026-09-14). Not
`_HandSoldering`, not `_HandSolder`, not `_Soldering`.

- **One footprint carried one**, and it is renamed:
  `Pin_D0.7mm_Pad1.4mm_Soldering` → **`Pin_D0.7mm_Pad1.4mm`**. The token said
  nothing the name did not — it is a single thru-hole pad and `Pad1.4mm` was
  already in the name. Renamed through `services/rename.py`, so the one
  component on it (`Pin_0.7mm_Soldering_Pin`) was republished with its
  verification carried, the `.kicad_mod` moved in the mirror and the Connectors
  library rebuilt.
- **`fp.name_spellings` no longer looks for the token.** Its pattern drops the
  `_HandSolder` / `_Handsoldering` clauses and keeps the rotation ban, which is
  the rest of what it always did. All 213 footprints pass.
- **Nothing BANS the token, and that is deliberate.** KiCad ships **194**
  footprints whose filename ends in `_HandSolder`, and a Tier 0 adoption keeps a
  stock filename character for character. A ban would collide with that freeze
  the moment one of those lands is adopted. What changed is that the house does
  not mint one — a tier question, not a spelling rule.

**The naming standard contradicted itself on this, which is the best argument
for dropping it.** `docs/footprint-naming/01-standard.md` pinned `HandSolder` as
"the house spelling — never `HandSoldering`" in §3.8, while D2 in the same
document pinned `_HandSoldering` and said `_HandSolder` is "never minted here".
The stock library splits 108 / 86 / 28 across three spellings, and KLC F2.1
rule 10 disagrees with KLC F3.3's own example. D2 is superseded, §3.8 drops
`HandSolder` from the option vocabulary, and the claim that the house "pins one
answer" no longer lists it.

Footprint checklist **v29**; `conventions-footprints` **v45**. Also updated:
`docs/footprint-naming/README.md` and `05-sources.md`.

## 2026-09-14 (the checklist audit, and a sanitizer on publish)

An audit of every judgment check — asked of how many subjects, answered how
many times — drove three changes. Machine checks were excluded from the count:
conformance is computed, not recorded, so a zero there means nothing.

**`sym.fp_filters` is retired** (severity `ignore`). Asked of 194 symbols,
answered **2** times. `ki_fp_filters` filters the footprint chooser and nothing
else, and every curated path already carries the footprint: the HTTP catalog
does not send the field at all, and a generated component symbol has `Footprint`
set. Not one of its 16 findings could reach a board.

**`fp.naming` asks the rename decision and nothing else.** Its text claimed the
twelve-slot order, which is `fp.field_order`'s job, so the name was covered
twice and a reviewer could not tell the two rows apart. The name is already
fully covered by `fp.tier`, `fp.field_order`, `fp.name_charset` and
`fp.name_spellings`; what is left here is the two reasons that justify a rename
and the rule that "ugly" is not one. The 292 existing `checked` answers are
kept: the hint they were read against was already the rename policy — the text
was the part that disagreed with it.

**Six glyph checks became one measurement — `sym.family_drawing`.**
`sym.triangle_body`, `sym.gate_body`, `sym.triangle_pins`, `sym.input_marks`,
`sym.rail_polarity` and `sym.rail_marks_not_names` all compared a drawing
against coordinates the hints quote to the 0.01 mm, and between them had been
answered **zero times in the library's history**. A coordinate comparison is not
a judgement. The new fact `$symbol_family_drawing_off` counts body vertices, pin
positions and polarity marks that are off the house table. Result: **10 checked,
1 na**, no findings — it is a regression guard, and the ten are exactly the
parts the hints name as precedent.

Two false positives the dry run caught before it shipped, both mine:

- **The angled-leader slot was missing from the gate table.** `74LVC1G125`
  (`~{OE}`) and `74LVC1G17` (`NC`) put a spare pin at (5.08, −5.08) with a short
  leader drawn to it — which is what `sym.angled_leader` describes. Both read as
  defects until the slot was added.
- **A multi-input gate has no documented geometry.** `SN74HC21`, a dual 4-input
  AND, measured **15 elements off** against the one-input table. It is drawn as
  the IEC body with an `&`, and the house has never written its numbers down. So
  the fact is now ABSENT there rather than inventing a rule — `sym.drawing_family`
  owns the undocumented case.

What needs the datasheet stays judgment: which rail is actually negative
(`sym.rail_negative_mark`), which input the datasheet calls inverting
(`sym.inverting_on_top`), and comparator vs amplifier (`sym.comparator_glyph`).

### A publish sanitizes before it parses

`sanitize_footprint` / `sanitize_symbol` correct derivable metadata on every
publish, through every door. Full rules in `api/app/services/CLAUDE.md`; the
short form is that a rule may only touch what the material fingerprint excludes,
and only where the correct value is derivable rather than guessed.

| Rule | Corrects today |
|---|---|
| A footprint's hidden `Value` takes the footprint's own name | **74** of 213 |
| `ki_fp_filters` is removed from a symbol | **149** of 207 |
| A `Footprint` default that is not `7Sigma:` is emptied | 9 |

- **Idempotent, and verified across all 420 drawings.** It runs before the
  `force=False` no-op comparison — sanitize afterwards and every KiCad re-save
  would mint a version. A re-publish of sanitized text still returns
  `unchanged: True`.
- **Non-material, and verified across all 420 drawings**: not one material
  fingerprint changes and not one drawing stops parsing.
- **Reported** on every return path, in `sanitized`.
- `ki_fp_filters` is deleted outright because **no component carries its own**.
  A `Footprint` default is **emptied, not deleted** — that one is displayed, and
  every component inherits its position and effects from the base symbol. Same
  trap `LCSC Part` taught this morning.

Checklists: symbol **v33**, footprint **v28**. `conventions-symbols` **v22**,
`conventions-footprints` **v44**. Conformance recomputed across 862 subjects, no
validator errors; symbol findings 77 → 62.

## 2026-09-14 (`sym.pin_numbers_unchanged` is automatic)

**"No pin numbers changed since the previous version"** is now a machine check.
The new fact `$symbol_pins_changed` diffs this version's pins against the
previous version's and counts numbers **added, removed, or moved to a different
unit**.

As a human question it was not working: answered **twice** in the whole library,
and asked of **71 symbols that have no previous version**, where the only honest
answer is "does not apply" and the hint never said so. Comparing two sets of
`(number, unit)` pairs is what a machine does better than a person reading a
diff.

- **A first version answers `na`.** The fact is ABSENT rather than `0` — "nothing
  has been compared" is not the statement "nothing changed".
- **Unit 0 is not a unit**, it means "common to every unit". Moving a shared
  power pin out of it makes that pin appear on unit A alone, so it counts.
- **A duplicated number is not a change.** Stacked power pins share one number,
  so the fact compares the SET of units each number sits in.
- The fact lives beside `$symbol_sim_link` rather than in `_symbol_providers`,
  because it is the one symbol fact that needs more than the source text — the
  predecessor has to be fetched — and the one that is about a CHANGE rather than
  a state, which is why it has no meaning on the component page.

Result across 207 symbols: **71 na, 132 checked, 4 findings.** No validator
errors. Every finding is a real unit reassignment, hand-checked:

| Symbol | | What moved |
|---|---|---|
| `KSZ8864CNX` v2 | 40 pins | Deliberate: split into 5 units, one per block |
| `TLV7022` v3 | 3 pins | Deliberate: one 8-pin box → two comparator units |
| `74LVC2G34` v3 | 2 pins | Deliberate: one 6-pin box → two buffer units |
| `SN74HC21` v4 | 2 pins | **Pins 7 and 14 moved out of unit 0 into unit 1** — the shared power pins now appear on unit A alone. The version comment reads "Edited in the KiCad footprint editor" and says nothing about it. |

The three deliberate re-splits need an answer or a standing exception; the
`SN74HC21` one looks unintended and is worth a look. The hint says what to do in
either case.

- `conventions-symbols` **v21**; symbol checklist **v31**.

## 2026-09-14 (19 base symbols stop carrying a part number)

**`sym.sourcing_defaults` passes on all 207 symbols.** Every base symbol that
stored an `LCSC Part` value now stores an empty one.

- **The value is emptied, the key is kept** — and the key is not decoration.
  `generator.schematic_field_visibility` reads the base symbol for each field's
  POSITION and EFFECTS, and every component that has its own value inherits
  them. Deleting the property drops each component's own field to `(at 0 0 0)`
  with the default font: a diff on every generated symbol for no gain. Emptying
  the value changes **nothing** — proven by generating each affected component's
  symbol both ways and diffing: **0 of 19 differ**.
- **This is already the house pattern.** 16 base symbols carried an empty
  `LCSC Part` before today; these 19 now match them.
- **Published as minor changes, so verification carried** — 19 `carry` records,
  "nothing that reaches the board changed", none lost. Mirror rebuilt: 16 symbol
  libraries, 442 components, 213 footprints, 0 warnings.

| | |
|---|---|
| Symbols fixed | `AP6335XQ` `BSC0702LS` `CH340B` `Conn_01x06` `Conn_01x22` `DF40C-100DS` `ESP32-C6` `FPC-05F-24PH20` `HU2032-LF` `LM2594M-XX` `NCP115ASN` `STM32C071G8U6` `STM32G031G8U6` `TLV62585DRLR` `TPS62826DMQR` `TPS6302X` `USB-B01` `WS2816C-1313/4P` `ZED-F9P` |
| Components affected | 0 — each already carried its own identical code |

- **The hint gave the wrong fix and is rewritten.** It said "Fix by REMOVING the
  property from the symbol", which is the change that moves every component's
  field. It now says to empty the value, shows the edit, and explains why the
  key stays. Symbol checklist **v30**.

## 2026-09-14 (a warning says warning)

- **A warning-level failure said `failed (machine)` and `warning only` on the
  same row**, which reads as a contradiction and was reported as a broken check
  (user report 2026-09-14). The row now says **`warning`**.
- `result` and `severity` are two axes
  ([decision 0016](docs/decisions/0016-severity-and-standing-exceptions.md)):
  the rule IS broken, and the breakage does not fail the part —
  `state_from_record` gives such a subject `checked` with `warnings: 1`. Only
  the word shown changes. The stored `result` is untouched, and the row's
  `title` still names it, so nothing is hidden from somebody who looks.
- The now-redundant "warning only" badge is gone.

## 2026-09-14 (a check that must find none says so)

- **"The count of sourcing defaults stored on the drawing is at most 0" reads
  as a broken rule, not a rule** (user report 2026-09-14). `at_most 0` is not a
  threshold — it is "there must be none", and it is the shape **14 of the 15**
  `at_most` checks take. Every counting fact's `noun` starts "count of", so
  dropping those two words leaves the sentence already written:

  | was | now |
  |---|---|
  | The count of silk lines crossing pad copper is at most 0 | No silk lines crossing pad copper |
  | The count of thermal vias outside their own pad is at most 0 | No thermal vias outside their own pad |
  | The count of sourcing defaults stored on the drawing is at most 0 | No sourcing defaults stored on the drawing |

- **The failure note was worse than the rule**, because it named the fact:
  `$symbol_sourcing_defaults is 1, not at most 0`. Notes now use the same noun
  the rule does — `_fact_noun` is shared by `describe_assert` and
  `evaluate_assert`, so the two can never name one quantity two ways. A
  must-find-none failure reports what was found: **"1 found: sourcing defaults
  stored on the drawing"**.
- **Two facts carried their own negative**, which the new phrasing doubled up.
  `$footprint_zero_annulus_pads` is now "plated holes whose copper is no wider
  than the drill" and `$pins_without_pads` is "symbol pins the footprint has no
  pad for" — read as "No plated holes with no annular ring" before.
- **A stale text on `cmp.value_field` surfaced and is corrected.** All six
  variants stored *"Value is the component's own name"*, which is the rule for
  exactly one of them: a TVS showed that sentence while the check tested
  `^[0-9]+(\.[0-9]+)?V…$`. Regenerating from each variant's own `assert` fixed
  it — the drift [decision 0014](docs/decisions/0014-a-check-carries-its-own-configuration.md)
  exists to prevent.
- Checklists: component **v27**, symbol **v29**, footprint **v27**. Machine
  answers recomputed across 862 subjects, no validator errors.

### `sym.sourcing_defaults` is correct, and 19 symbols trip it

Verified against the ESP32-C6 base symbol behind
`VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm_ThermalVias`: the drawing carries
`(property "LCSC Part" "C5364646")`. `generator.apply_properties` starts from
`{p.key: p.value for p in symbol.properties}` and lets the component override,
so a base-symbol default that a component does not override ships to KiCad on
that component.

**Nothing is broken today** — each of the 18 symbols with a component is
overridden by that component's own identical code, and `WS2816C-1313/4P` has no
component yet. It is a latent defect, which is what `warning` says. The ones
that will actually be reused are the templates: `Conn_01x06`, `Conn_01x22`,
`DF40C-100DS`, `FPC-05F-24PH20`, `LM2594M-XX` and `TPS6302X` — the last two are
named for families, and the next part built on either inherits one specific
orderable code.

## 2026-09-14 (a standing decision sits on the check it excuses)

- **The exception moved onto its item's row** (user request 2026-09-14). It used
  to render in a block of its own above the checklist, so the reason a check was
  quiet — and the only button that withdraws it — sat several rows from the
  check, under a bare key (`fp.npth_mechanical`) that reads as nothing. The row
  now carries the `exception · this part, always` pill beside its state, the
  reason beneath it, and `Revoke exception` in the row's own button row.
- **Linked by `answered.exception_id`, not by key**, because an exception
  carries a `variant` and a waiver on the NMOS rule must not excuse the PNP one.
- **An exception with no row keeps a block of its own.** Its check can be scoped
  out, switched off, or dropped from the checklist since the decision was made,
  and a stale one has stopped closing its item — without that fallback it would
  become impossible to withdraw.

## 2026-09-14 (the third place is gone)

**A shared land records its other package names in `tags` and `descr`, and
nowhere else.** The hidden `Equivalent Packages` property is removed (user
decision 2026-09-14, after asking why only 1 of 213 footprints carried one).

Why it never earned its place:

- **Nothing read it.** KiCad's footprint chooser searches the name, `descr` and
  `tags` — not arbitrary properties. In the shipped KiCad 10.0.5 library, 15,462
  footprints use five property names between them (`Reference`, `Value`,
  `KiLib_Generator`, `Description`, `Datasheet`); a custom one appears **twice**.
- **One reader in the whole platform**: `jaravis._footprint_aliases`, feeding
  `list_footprints`. Nothing in the web UI or the mirror touched it.
- **Writing one was expensive.** The property lives in `source_text`, so editing
  it mints a footprint version and publishes a new component version for every
  part on that land — for a metadata note. (Verification and sign-off do carry:
  `services/material.py` excludes `descr`, `tags` and `property` fields from the
  material fingerprint.)

What changed:

- `fp.shared_land_record` is now **"Other vendor names for this same land are
  listed in tags and descr"**, and the hint says why those two and no third:
  they are the only fields KiCad itself searches. It also says not to
  reintroduce a property for this.
- `list_footprints(query)` matches the name, `tags` and `descr`. `matched_on`
  still says which field answered.
- `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm_ThermalVias` — the only footprint that
  had one — lost the property. Every designation and vendor code it carried is
  in `tags` and `descr`; its `descr` now reads "…QFN, VQFN, WQFN (TI RGT and
  RTE), LFCSP (ADI CP-16-22), JEDEC MO-220 VGGD." Published as a minor change,
  so the five components on the land (`PCF8574RGTR`, `ADA4945-1ACPZ-R7`,
  `74HC123LQ/TR`, `74HC138LQ/TR`, `TPS65135RTER`) were repointed with their
  verification intact.
- **Two retired lands lost a dangling pointer.** `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm_ThermalVias` and
  `WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm_ThermalVias` both said "see its
  Equivalent Packages property" in their `descr`. They now point at the
  survivor's `tags` and `descr`. No components on either, so nothing moved.
- Footprint base checklist **v26**; `conventions-footprints` **v43**.

The measured deltas the property carried are preserved here, because this is
now their only record:

> VQFN-16 3x3 P0.5 (TI RGT, PCF8574RGTR on this land since import) ; WQFN-16
> 3x3 P0.5 (TI RTE, TPS65135RTER on this land since import; KiCad stock
> WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm from ti.com tlv9064 p.44 draws pads
> 0.835x0.25 at +/-1.4575 and EP 1.68: 0.005 mm centre, 0.01 mm length, 0.02 mm
> EP from this land) ; LFCSP-16 3x3 P0.5 (ADI CP-16-22, ADA4945-1ACPZ-R7
> repointed 2026-09-07; KiCad stock LFCSP-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm from
> analog.com CP_16_22.pdf draws pads 0.875x0.25 at +/-1.4375 and EP 1.6:
> 0.025 mm centre, 0.05 mm length, 0.1 mm EP from this land) ; JEDEC MO-220 VGGD

## 2026-09-14 (`fp.tier` says one thing, and the second thing got its own check)

- **"The name follows the right rule for this package, and a KiCad name means
  identical copper" asked two questions in one**, so CHECKED could not mean one
  thing (user report 2026-09-14). The naming half keeps the key: *"The name
  follows the first of the four naming rules that applies"*.
- **The anti-shadowing half became `fp.stock_name_diffed`** — *"A name copied
  from KiCad's own library sits on copper identical to KiCad's"*. DOES NOT APPLY
  on any footprint whose name is not a stock filename, which the hint says
  outright, and which is **110 of 213** footprints.
- **The hint is written for somebody VERIFYING a name, not authoring one.** The
  old one was a naming procedure, so a reader holding a finished footprint had
  to invert every step. It now says: work the four questions yourself, see which
  rule you land on, then ask whether the name came from that rule. It names the
  common miss — question 3 answered with a bare package designation while our
  copper deviates from generic, which needs the vendor in front.
- **`fp.stock_name_diffed` carries the command that answers it.** The shipped
  library is on disk, so the hint gives the `find` over
  `KiCad.app/Contents/SharedSupport/footprints`. No hit means the name is not a
  stock name, which is DOES NOT APPLY.
- Footprint base checklist **v25**; `conventions-footprints` **v42**.

### What the new check is worth: 103 of 213 names ARE stock filenames

Diffed against the KiCad 10.0.5 library installed on this machine — pad numbers,
positions and sizes. **43 of the 103 differ from stock.** Most are the
house-prepared families the skill already declares deliberate (the chip
passives, the SOIC and SOT lands), where the difference is the point. Four are
not, and are the case this check exists for:

| Footprint | Ours | KiCad stock |
|---|---|---|
| `ublox_ZED` | 102 numbered pads | **55** |
| `VSON-8_3.3x3.3mm_P0.65mm_NexFET` | numbers 1–10 | 6 distinct, no 6–9 |
| `DFN-8-1EP_3x2mm_P0.5mm_EP1.36x1.46mm` | no pad numbered 9 | exposed pad **is** 9 |
| `Osram_BPW34S-SMD` | 2 pads | 3, one unnumbered |

A name that matches KiCad's while the numbering does not is the silent failure:
the symbol's pins map to the wrong pads and nothing warns. These are reported,
not changed — a rename repoints every component on the footprint.

## 2026-09-14 (`fp.shared_land_record` says what it means)

- **"Every package designation this land serves is recorded in all three
  places" never said which three places.** The reader had to open the hint to
  learn what the item even asked. The text now names them: *"Other vendor names
  for this same land are listed in tags, descr and Equivalent Packages"* (user
  report 2026-09-14).
- **The hint states when the answer is DOES NOT APPLY**, which it is for most
  footprints. The old hint said a land serving one package "is trivially yes",
  so the same fact could be recorded as `checked` or as `na` depending on who
  read it. The rule is now explicit: one name = does not apply, several names
  all written down = checked, a name missing = flagged, and say which name and
  which field.
- **It also explains WHY the item exists**, with the case that motivates it:
  one 3x3 mm 16-lead land is QFN-16, VQFN-16, LFCSP-16 and RTE to four vendors.
  KiCad has no footprint alias, so a name nobody wrote down is a name the next
  person cannot search — and they draw a second copy of copper we already have.
- **Still asked of every footprint, still a warning.** Nothing in the file says
  whether a land serves more than one name, so the question cannot be scoped
  away — the same reason `fp.thermal_vias` is not scoped on `pad_prop_heatsink`.
- **The procedure for retiring a duplicate land moved to
  `fp.one_land_per_package`**, which is the item about duplicates. Its hint
  already said "the two have to be merged deliberately" and stopped there; it
  now carries the merge steps, because a delete is refused while any historical
  component version still pins the loser.
- Footprint base checklist **v24**; `conventions-footprints` **v41**, where two
  index rows had fallen behind the checks they point at.
- **A long hint no longer runs off the bottom of the window.** The ⓘ tip asked
  whether 160 px fitted below the marker, which is true almost everywhere, so a
  45-line hint opened downwards and lost two thirds of itself past the edge with
  no scrollbar to get it back. It now opens to whichever side has more room, is
  capped to that room, and scrolls.

## 2026-09-14 (two checks became automatic)

- **`fp.thermal_vias` is a machine check.** "Thermal vias share the exposed
  pad's number and sit inside it" is geometry, and the new fact
  `$footprint_vias_outside_ep` measures it: a through-hole pad carrying an smd
  pad's number whose copper is not wholly inside that land. **Two footprints
  fail** — `TexasInstruments_VSON-14-1EP_4x3mm_P0.5mm_ThermalVias` and
  `SON-12-1EP_2.5x4mm_P0.4mm_ThermalVias`, four vias each. On the SON-12 the
  land is 1.0 x 1.0 mm and four vias reach y = ±1.2: they stitch the heat path
  to nothing. `VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm_ThermalVias` passes and is
  the reference.
  - **Scoped on the vias, not on `pad_prop_heatsink`.** Both failing footprints
    have no heatsink property either, so scoping on it made the check blind to
    exactly the parts that got the construction wrong. A check must not need
    the thing it is looking for to be declared correctly.
  - The five companion changes — paste stripped from the EP, windowed
    apertures, the back-side land, `zone_connect 2`, the name suffix — stay in
    the hint and are NOT measured. The hint says so.
- **`fp.silk_clear` split in two.** The silk-over-copper half is now automatic
  (`$footprint_silk_over_pads`) and finds **3 footprints**: a fuse holder, an
  RJ45 and a nanoSIM socket, where a silk line runs straight through pad
  copper. Ink between a pad and its solder is a contaminated joint and the
  assembler's optical inspection reads it as one.
  - **What it does not see is stated in the hint**: straight edges only, so 0
    means no STRAIGHT silk crosses copper. An arc is not tested.
  - The other half became **`fp.pin1_placed`** — is the mark against the pad
    the DATASHEET calls pin 1, and can somebody placing the part see it. That
    is the part no machine can judge; `fp.pin1_mark` already counts the
    Cmts.User circle mechanically.

## 2026-09-14 (navigation) — a reload puts you back where you were

- **Scroll position survives a reload and back/forward, on every page.** The
  browser cannot do it here: `history.scrollRestoration` restores the window,
  and this app scrolls a pane inside a full-height shell. Positions are stored
  per URL and re-applied until they stick.
  - **The scrollers are discovered, not listed** — `.main` on browse,
    `.main-solo` on the review queue, `.detail-left` on a component, and the
    component page scrolls two columns independently.
- **An expanded verification row is remembered too.** Restoring the offset
  alone puts a reader at the same pixel with the section they had opened closed
  again, which is somewhere else entirely.

## 2026-09-14 (review card) — no edit mode, work on top, hints you can read

- **`fp.tier` no longer opens with the word "tier".** "The tier test was run in
  order, and a Tier 0 claim was verified against the stock copper" told a reader
  nothing unless they already knew the standard. It is now **"The name follows
  the right rule for this package, and a KiCad name means identical copper"**,
  with the hint as four numbered questions, one example each, and the reason the
  copper diff matters stated as the consequence: a name matching KiCad's over
  different copper can map the symbol's pins to the wrong pads with nothing to
  warn you.
- **`fp.one_land_per_package` asks a question now**, not gives an instruction.
  "Reuse the footprint the library already has" cannot be answered yes or no —
  a VQFN-40 with a land nothing else uses had no obvious answer, and the
  reviewer was left choosing between `checked` and `does not apply` on a coin
  toss. It reads **"No other footprint in the library draws this same
  package"**, and the hint states outright that a package unique to one part
  answers CHECKED: one land exists and it is this one. There is no case for
  `na`, because every footprint draws some package.
- **`fp.one_land_per_package` is rewritten in plain language**, 1,996 → 1,181
  characters. It was six dense paragraphs that mixed the rule, one family's pad
  coordinates and a 3D-modelling instruction. Now: the rule with a worked
  example a resistor or a push button fits, three numbered steps to reuse a
  land, when it is a different package, when never to adjust one, and what to
  record. Nothing was dropped except the 6x6 tactile family's eight
  measurements — the footprint itself is that specification, and the hint names
  which one to copy.

- **The "Verify…" button is gone.** Every checklist row is answerable straight
  away, and **Save / Cancel appear at the top the moment an answer is staged**.
  Entering an edit mode was a click that carried no decision and hid every
  control behind it.
- **Items sort by how much attention they need**: findings, then warnings, then
  open, then excused by a standing decision, then checked. The rank is read off
  the SAVED answer, never a staged one, so answering a row does not make it jump
  out from under the cursor — it re-sorts on the next load.
- **The state sentence and the buttons that act on it share one line.**
  "Partially verified — 8 item(s) still open." and `Mark checked` /
  `Revoke verification` were stacked, and so were the note box and `Save` /
  `Cancel`; that is two rows of chrome above every checklist. The sentence
  gives way first when the line is tight, because it is the half a reader can
  finish from the pills above it.
- **A hint is behind an ⓘ, shown the moment the pointer is over it.** It used to
  be a `title` attribute: a one-second wait, no sign it existed, and the
  browser's own box with no line breaks — for text that is the only explanation
  of what a check means. New shared `components/InfoTip.tsx`; the item's key
  stays in `title`.

## 2026-09-14 (footprint machine checks) — two checks that could not see

- **`fp.via_dims` looked for a primitive that does not exist in a footprint.**
  It matched `(via ...)`, which lives only in a `.kicad_pcb`; a `.kicad_mod` has
  no via element at all. The regex matched **0 of 213 footprints**, so the check
  answered `na — no vias` on every one, including **19 with a real thermal-via
  field** — `VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm_ThermalVias` has 16.
  KiCad draws a thermal via as a `thru_hole` PAD carrying the exposed pad's own
  number, and the check now reads those: a through-hole pad is a via when its
  number also appears on an smd pad, or when it has no number. Result:
  **19 checked, 194 na**, all at 0.6/0.3 mm.
- **`fp.smd_rratio` counted paste-only apertures.** The four pads it failed the
  VQFN on are `(layers "F.Paste")` stencil openings at `rratio 0.174825`, not
  copper. The house corner ratio is a rule about pads, and KiCad writes whatever
  radius it computed for a paste sliver. Pads with no copper layer are skipped;
  library failures **36 → 33**, and the 33 are real.
- **The conformance digest now includes a hash of `validator.py`.** It covered
  the resolved checklist, the facts and the exceptions — enough for a
  declarative check, because editing one changes the item, and NOT enough for a
  check written in Python. After the `fp.via_dims` fix, 15 footprints kept
  serving `na — no vias` from cache because no fact and no item had moved.
  Editing the validator now invalidates the library once and the warm-up
  refills it, which is what decision 0017 promised.

## 2026-09-14 (states) — a row and its card said different things

- **A list row is measured against TODAY's checklist, not the record's own
  snapshot.** `VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm_ThermalVias` read
  `CHECKED (AGENT)` on its row and `PARTIAL — 8 items still open` the moment you
  opened it. Its record was written against an 18-item checklist with 6 judgment
  items; today's has 38 with 14. **Row and card now agree on all 862 subjects.**
  - The snapshot stays correct for HISTORY — what a past record was measured
    against — which is the history list, not a live state.
  - Resolving a checklist per subject costs 33 ms, so a list page cannot pay for
    it: 862 subjects is 28 seconds. The judgment list is cached on
    `conformance.judgment`, which already rides the digest covering the resolved
    checklist, so it invalidates itself when a check changes. List pages are
    unchanged at **0.48 s** for 442 components.
- **A subject with NO review record read `checked`.** With no record there was
  no snapshot, so the denominator was empty and an unreviewed footprint passed.
  **42 components** were being carried by one. They now read `unreviewed`.
- **The judged fraction counted off-checklist answers.** `SMAJ24CA` read
  "JUDGED 13/13" beside `partial` with four checklist items open, because four
  `custom:` answers filled the places of four unanswered ones. `answered` and
  `total` now count the checklist only; `custom:` answers are still shown, in
  their own list.
- **What this does to the numbers.** Components reading `checked` end to end:
  **174 → 1**. Nothing was un-verified — the old figure measured each part
  against whatever checklist existed when somebody last looked at it, and the
  library gained checks all day. 205 of the 862 individual subjects are checked.

## 2026-09-14 (plain words) — a check nobody understands is not a check

- **The five simulation checks are rewritten in plain language.** The old
  wording assumed the reader already knew the vocabulary. "The model header
  names every behaviour it leaves out, and why" is now **"The model says which
  real behaviours it does NOT reproduce"**, and every hint follows the same
  shape: what the check asks, why it matters with a worked example, then
  numbered steps.
  - The worked example on `cmp.sim_limitations` is a real one. `sigma_npn`
    holds the current gain at `BF=400`; a BC817-40 falls to 170 at 300 mA. Size
    a base resistor from that simulation and you give the transistor 0.75 mA
    where it needs 1.8 mA. The plot shows it saturated. The board does not.
  - `cmp.sim_params` is automatic, so its wording lives in
    `validator._CHECK_SPECS`, not the checklist. Changed there.
  - No scope, severity or result changed.
- **Nine findings that opened "No statement of what the model omits" are
  reworded.** Same flags, same models, nothing re-decided — they now lead with
  what is missing and what it costs.
- **`sigma_npn` v2 has the header comment it never had**, naming what the block
  ignores (beta roll-off, quasi-saturation, self-heating, breakdown, charge
  storage, leakage) and what it is good for. `BC817-40-7-F` goes to **checked**;
  `BC847CLT1G` and `MMBT3904,215` share the model.
- **`BC817-40-7-F`'s `cmp.sim_numbers_read` is answered.** `BF=400` sits inside
  the -40 grade's published hFE band, 250 to 600 at `VCE=1.0V, IC=100mA` (p4).
  The sheet prints no typical, so it is a mid-band choice, not a quotation, and
  `IS`, `VAF`, `RB` and `RC` are fitted block defaults. No value changed.

## 2026-09-14 (families) — a triangle rule needs a triangle

- **A review card folds the checks that are NOT about the part.** "Not about
  parts like this one" and "switched off here" now sit behind a count
  (`5 checks not about parts like this one`) instead of printing inline. A
  MOSFET was showing "IQ is per CHANNEL…" and "the exposed pad is documented"
  in the middle of its checklist, where they read as open work even though the
  scope was correct. Kept rather than dropped — reading them is how somebody
  finds out a scope is wrong.

- **The five analog-triangle geometry checks now require a triangle body**, the
  way the gate-family ones already did. `sym.triangle_body`, `sym.triangle_pins`,
  `sym.inverting_on_top`, `sym.input_marks` and `sym.comparator_glyph` were
  scoped by `comp_type` alone; `sym.gate_body` and `sym.digital_block` had
  carried `$symbol_has_box` from the start.
- **`ADA4945-1` was the part it caught.** A 17-pin fully-differential amplifier —
  differential in, differential out, two feedback pins, VOCM, MODE, DISABLE, two
  clamps and four supplies — correctly drawn as a BOX, and asked for 15.24 mm
  triangle coordinates it can never have. Its judgment list drops 15 → 10 and
  `sym.drawing_family`, which is the right question for it, stays open.
- **The two triangle sizes were verified against every symbol.** They do not
  overlap: 15.24 mm is `COMPARATOR|OPAMP`, 10.16 mm is `LOGIC` without a box.
  A logic buffer (`74LVC1G17`) is on the 10.16 rule, as it should be.
- **`sym.drawing_family` had no scope at all** and reached all 207 symbols, so a
  MOSFET (`Q_NMOS_GSD`, behind `AO3400A`) was asked which of the three IC
  families it belonged in. New fact **`$symbol_family_choice`** reads
  `checklists.FIXED_PICTOGRAM` — 53 families drawn one way by convention:
  transistors, diodes, passives, crystals, relays, connectors and mechanical
  parts. Reach 207 → **98**, all ICs and modules.
  - A symbol with no `comp_type` on any component (a power flag, a bare
    graphic) returns ABSENT and is skipped too.
  - A shared symbol keeps the question if ANY of its components has a choice.
- **Every other judgment check was surveyed for the same fault.** The remaining
  unscoped ones — `cmp.description`, `cmp.category`, `cmp.base_symbol`,
  `cmp.value_field`, the seven `fp.*` naming and geometry items,
  `sym.pin_numbers_unchanged` — are genuinely universal. `sym.drawing_family`
  was the only outlier.

## 2026-09-14 (scope) — a rule that says what it means

- **The two rail checks are scoped by what a part IS, not by how its symbol is
  typed.** `cmp.sim_iq_per_channel` ("IQ is per CHANNEL…") and
  `cmp.sim_supply_current` were reached through `$symbol_power_pins`, which asks
  whether a SYMBOL happens to type a pin as power. New fact **`$powered_die`**
  answers the real question, reading `checklists.NO_QUIESCENT_CURRENT` — 30
  families with no powered die: transistors, diodes, passives, plain LEDs,
  crystals, relays, switches and the house simulation stand-ins.
  - The list is of what is EXCLUDED, on purpose: a new IC type keeps the check
    by default, where a positive list would let it escape silently.
  - **No component changed scope** — all 442 already agreed. The gap it closes
    is the next one: `TPD4E05U06DQAR` is a TVS array that draws two rails, so
    the day it gained a `Sim.Params` row it would have been asked for its
    per-channel quiescent current.
  - The scope now also READS on the card. It was briefly a 265-character
    negative lookahead; a fact puts the family list in `checklists.py`, where it
    carries its reasoning, and leaves `$powered_die matches ^true$` on screen.

## 2026-09-14 (TS24CA) — a pad named MP is not a missing pin

- **`cmp.pads_to_pins` fired on its own fix.** TS24CA's two frame tabs were
  numbered 3 and 4; the owner renamed them `MP` on 2026-09-13 so no net could
  reach them, and the next read reported a pad the symbol does not draw.
  `$pads_without_pins` now ignores pads named `MP` or `SH` — KiCad's own
  libraries use both, and the name IS the statement that no pin lands there.
  Library findings 13 → 9; the nine that remain are numbered pads (an exposed
  pad, an NC lead, a second antenna terminal) and are real questions.
- **The TS24CA package name said `SMD-4P … Right-Angle`.** It has two terminals
  plus two `MP` pads, and the switch is top-actuated. Now `SMD-2P
  4.7x3.5x2.25mm`, matching its TS3625A sibling. Unversioned, so no footprint
  version and no copper change; the Buttons library rebuilt.
- **TS24CA now reads `checked` on all three subjects.** The footprint had been
  held at `failed` by a `custom:` flag saying the name claimed 4P — resolved by
  the v5 rename a day earlier and never closed. Ten open judgment items were
  answered (`fp.one_land_per_package`, `fp.tier`, `fp.field_order`,
  `fp.jlc_land`, `fp.shared_land_record`, `fp.silk_clear`,
  `sym.drawing_family`, `sym.fp_filters`, `sym.easyeda_diff`,
  `sym.pin_numbers_unchanged`).
- **Verification notes rewritten short.** Nothing was re-decided: every result
  is unchanged. The longest was `fp.land_pattern` at 2,368 characters, now 234,
  with the owner's accepted-deviation decision intact and the original finding
  still on `superseded`.

## 2026-09-14 (later) — the CE_Dongle_V3 BOM found eight wrong checks

Walking 57 components one by one was a test of the check system, and it failed
in eight places. All eight are fixed.

- **A startup migration was reverting checklist edits.**
  `migrate_rules_onto_items` re-stamped every CATEGORY checklist from the
  retired rules table on every restart, where the BASE path had been given
  `only_missing=True` for exactly that reason. Removing a bad pattern published
  v4; the next reload published v5 with it back.
- **`Value` had two owners.** `cmp.value_field` splits by `comp_type`;
  `cmp.property_values` carried a competing per-category pattern that did not.
  They disagreed on a ferrite bead and two LAN transformers, and the
  category-wide one was wrong every time. Removed from all four categories.
- **Checks demanded what a part cannot have.** An addressable RGB LED was
  required to have one `Color` and one `Forward Voltage`; five parts on the
  skill's own "deliberately free text" list were failed against a template.
  Split by `comp_type` — four became rules, one became a standing exception.
- **The new simulation checks were over-broad**: 57 of 94 parts carrying
  `Sim.Params` have no supply pins, and a tactile switch was being asked about
  its quiescent current. Scoped to parts with rails.
- **`cmp.datasheet_is_document` was a judgment asked 413 times** that duplicated
  `cmp.datasheet`. All 416 archived documents are PDFs, so its mechanical half
  is now a machine guard and its judgment half goes where it belonged.
- **New `sym.should_stack`** — the half `sym.stacked` could never ask, because
  that one only reaches a symbol that already stacks. Seven real findings,
  including a U.FL jack drawing its ground as two separate pins.
- **`TOGNJING` is `TONGJING`** — the archived datasheet prints
  `www.hftongjing.com` in its own footer, which is the primary source the
  skill's own low-confidence note had asked for.
- **33 verifications restored.** Components that lost their record to a
  `comp_type` edit made before [decision 0019](docs/decisions/0019-a-classification-carries-the-first-time-it-is-set.md)
  existed now carry it again; 24 others stayed blocked on real material
  changes. **418 of 442 components carry a verification, up from 385.**

## 2026-09-14 — every check says which parts it is about

**The convention skills became checks.** `conventions-footprints` (1105 lines),
`conventions-symbols` (654) and `conventions-library` (573) are now 197, 102 and
112 — an index of which check answers which question. Every number, decided case
and trap moved into the check hints, where it is read at the moment it is
needed. Each cut was audited token by token against the new text plus every
hint before publishing; 16 pieces of evidence that were being dropped went back.

**Judgment checks are scoped.** They used to be asked of every subject of their
kind — a two-pin ferrite bead was asked how its functional blocks were grouped.
Nineteen scopes were added, each measured against the whole library first, and
two were built and thrown away for hiding a 94-pin module and a 100-pin
connector. Live standing exceptions fell from **186 to 55**: 131 were revoked
because the checks now say what they mean.

**`comp_type` on all 442 components**, across 94 types, with 385 keeping their
verification — see [decision 0019](docs/decisions/0019-a-classification-carries-the-first-time-it-is-set.md).
`$symbol_comp_types` carries it to the drawing axis, which is what let section 5
of the symbol conventions become nine specific checks (the 15.24 mm triangle,
the inverting input on top, the comparator glyph, the gate body, the digital
block) instead of one yes/no asked of all 207 symbols.

**Eighteen new checks**, nine of them promoted from recurring `custom:` keys.
`sym.sourcing_defaults` found 19 symbols storing an LCSC or Manufacturer default
the generator would inherit onto every component built from them; the custom key
had found 2.

**Fixes.** A declarative check was throwing away its author-written hint on
save. `$electrical_props` counted `Reference` and `LCSC Part Class` as
electrical data and excluded `Sim.Params`, which is one. A pinless drawing and
an unparseable one both reported no pin count, so no scope could tell them
apart.

## 2026-09-14 — Two convention documents audited against what actually runs

Neither footprint nor symbol conventions turned out to be compressible: they are
almost entirely authoring instructions — how to draw a cathode bar, how to size
a box, how to measure a 3D model — and 44 and 31 table rows between them. There
was no data to move into a check. What the audit found instead was worse than
bulk.

**The footprint style section claimed the validator enforced eight rules. It
enforced four.** Auditing the other four found that two of them are wrong:

- "SMD pads carry F.Cu, F.Paste and F.Mask, all three" — 25 footprints differ
  and every one is an exposed pad, which legitimately has no paste or a
  separate aperture.
- "Through-hole pads are circle or oval" — 25 differ and every one is a pin-1
  pad, rectangular by KiCad convention.

The third, the roundrect corner ratio 0.25, is real: 36 of 212 footprints carry
another value. `fp.smd_rratio` checks it now, as a warning, because most of the
36 are stock lands the tier rule freezes. The fourth — the internal footprint
name matching the filename — is satisfied on all 212.

The section now names the check that holds each rule and says plainly which two
were wrong. A document that claims the machine checks something it does not is
worse than one that stays silent: the reader stops checking it too.

**The symbol grid law does not match the library.** It states 2.54 mm in both
axes as absolute; the check enforces 1.27 mm and nothing violates it, while 61
of 206 symbols are off 2.54 — `RPi_CM5` with 200 pins, `ZED-F9P` with 102, every
large STM32. Dense parts do not fit on 2.54 mm. The claim that an off-grid pin
"cannot be wired on a default sheet" is also not so; KiCad's default grid
includes 50 mil. Recorded as an open decision rather than resolved either way.

## 2026-09-14 — A rule leaves a skill only when a check has it

An earlier pass today removed 42 KB from the component-conventions document on
the assumption the new checks held that data. Audited line by line, they did
not: the rule that an RF part spells the key `VSWR` and never `V.S.W.R` had no
check at all, 15 of 31 description templates were in no check, and a decision
rule - "a family-wide deviation defends itself" - was deleted outright. That
pass was reverted.

Redone against a mechanical test: a row leaves only when a check holds its data
AND the row carries nothing else. That removed **60 of 81** manufacturer rows
(a spelling plus a list of feed misspellings, and the check holds the spelling)
and **9 of 31** template rows. The other 21 and 22 stayed, because each carries
a decision, a reason, or has no check.

51 KB to 47 KB. That is the compression actually available: the bulk of that
document is reasoning, and reasoning is what a check cannot hold.

### New

**`absent`** - the assertion for a rule that says there must be no X. Every
other assertion reads a value, so a subject without one is answered "does not
apply" before the assertion runs, which made "this key must not exist"
inexpressible. `cmp.vswr_key` is the first to use it.

[what-a-check-can-hold.md](docs/reference/what-a-check-can-hold.md) records the
mapping and the order - build the check, measure it, then cut.

### Found, not fixed

`Inductors`, `RF` and `Circuit_Protection` carry no `comp_type`, so their Value
and description rules cannot become checks: a fixed inductor, a ferrite bead and
a LAN transformer are three rules sharing one category with nothing in the data
to tell them apart. `Connectors` has the same problem differently - `Pluggable
terminal block; {Pitch}` and `Pluggable terminal block; 3.5mm` coexist in one
family. Work list row 24.

## 2026-09-14 — The conventions point at the checks, and Zener has one n

**Four skill documents were republished** so an agent stops hand-verifying what
the platform already decides. `platform-workflow` v11 was the urgent one: it
still told agents to answer `skipped`, retired in September, and still described
the automatic checks as something recorded on publish. It now says what the
platform does — checks are worked out on read, "does not apply" is a standing
exception that outlives the version and needs a note, notes are capped, a
warning does not fail a part, and a switched-off check is not the same as one
that is not about this part.

The three convention skills now mark the rules the platform enforces —
`fp.quad_numbering`, `fp.zero_annulus`, `sym.top_edge`, `sym.pin_length`,
`cmp.value_placeholder` and `cmp.value_field` — and keep the prose, which says
why the mistake happens and what to do when a check fires. A check cannot
explain itself.

**Zener is spelled with one n, everywhere.** All six Zener diodes were
republished: the property key `Zenner Voltage`, `comp_type=ZENNER` and the
template word "Zenner Diode" all moved together, because they have to — a
dangling `{Zenner Voltage}` fails the template check. No `Zenner` remains on any
live version. The six lost their verification, as a property edit always does.

**The Diodes Value rule is now three rules.** The base list splits on category
and cannot reach inside one, so the Diodes category carries its own variants
split on `comp_type`: the reverse stand-off voltage for a TVS, an RKM V code for
a Zener, the part number for a rectifier.

It found two parts carrying their MPN where the stand-off voltage belongs —
`SMF28A` and `SMF6V0A-E3-08`, now `28V` and `6V`. Both were read off each part's
own **Reverse Stand-Off Voltage** property, not decoded from the part number.
The work list had recorded seven such parts; there were two.

## 2026-09-14 — Changing a check changes the lists, without a restart

Editing a checklist re-fingerprints every subject it reaches, but nothing acted
on that: list surfaces read the cache without re-checking the fingerprint, and a
detail page worked out the new answer and then threw it away. So a check edited
on the platform changed nothing anybody could see until the API happened to
restart. Found by shipping the new checks to production and watching the
numbers not move.

Saving a checklist now re-evaluates that kind in the background, and the pages
that recompute keep what they worked out. Revoke a standing decision and the
list of parts failing that check reports it on the next request.

## 2026-09-14 — Fix: an empty table took the page down

Any list with a default sort crashed when it had no rows. The sort asks the
first row what type it holds to decide between numeric and text ordering, and
on an empty list there is no first row, so the question threw and the whole
page went blank.

It surfaced on Reviews -> Exceptions, which is the first list that is
legitimately empty on a library with no standing decisions recorded yet. It
worked in testing because the test library had six.

## 2026-09-14 — An explanation has a length now

Every field that holds a written reason is capped, and an over-long one is
refused rather than quietly cut.

| Field | Limit |
|---|---|
| a note on a checklist item | 400 |
| a custom check's own wording | 200 |
| the note on a verification pass | 300 |
| an exception's note | 400 |
| an exception's evidence | 600 |
| a revoke reason | 300 |
| a version's change comment | 600 |

The numbers come from what was already stored. A person writes **31**
characters in a note. An agent's median is **367**, and the longest in the
library is **3,316** - about 500 words on one checklist item. Nobody reads that,
so the finding inside it is lost as surely as if it had never been written.
Version comments were worse: symbol edits ran to a median of 876 and a maximum
of 4,087.

Refused, not truncated. A cut-off sentence teaches nobody; the refusal names the
length, the limit and what to write instead - "say what is wrong and how you
know, in a few sentences". A refused item comes back on the blocked list and the
rest of the save goes through.

In the web UI the box simply stops accepting text, with a counter that appears
in the last quarter, so nobody writes three paragraphs and then loses them.

Nothing already stored was changed. The limits apply to what is written from
now on.

## 2026-09-14 — Standing decisions have a register, and a failing check has a worklist

**Reviews → Exceptions** lists every standing decision in the library: the
subject, the check, why, how long it holds, who made it, and whether it still
applies. An exception was visible only on its own component's card before this,
so nothing could answer "what have we excused". A decision that pins nothing
holds for every future version of a part, and now somebody can see which ones
those are.

A **stale** row is the point of the screen. An exception dies when a fact it
named changes, and one that has quietly stopped applying means the check it
excused is failing again somewhere nobody is looking.

**A failing check opens.** The library-health panel already grouped failures by
check rather than by part, because "fp.courtyard_grid on 76 footprints" is one
job and "218 failed parts" is a wall. The numbers were dead text. Click one and
it lists every part it fails on, with each part's own note and a link to it.

**The review state is three facts, not one word.** A card now reads
`ISSUES · FAILS · JUDGED 10/11` instead of `ISSUES` alone. "Partial" used to
mean "nobody has looked", "a question was added last week" and "one item is
still open" all at once, and a footprint could read "unreviewed" straight after
somebody decided every check on it. The queue keeps the single word, because a
list has to sort by something, and carries the facts in the tooltip.

### Fixed

A verification saved after **Mark checked** discarded every answer underneath
it. The one-click confirmation is stored with no item breakdown by design, and
the next save was seeded from it, so a part went from twelve recorded answers to
one. Found 2026-08-25, fixed today. Answers now survive the sequence.

The library-health panel counted some failures twice — once from the agent's
flag and once from the machine's finding — reporting `cmp.datasheet_text` on 47
components where 27 carry it.

## 2026-09-14 — Eight convention rules are checks now, not prose

Rules that lived as paragraphs in the skill documents, for an agent to read and
re-read on every part, are checks the platform runs itself:

| Check | From | Finds today |
|---|---|---|
| `fp.zero_annulus` | footprints section 6 | 0 |
| `fp.quad_numbering` | footprints section 2 | 0 |
| `sym.top_edge` | symbols section 3 | 24 (warning) |
| `sym.pin_length` | symbols section 4 | 2 |
| `cmp.value_placeholder` | library section 3 | 0 |
| `cmp.pins_to_pads` | - | 0 |
| `cmp.pads_to_pins` | - | 13 (warning) |
| `cmp.value_field` | library section 3 | 0 |

Across all 857 subjects the eight add **two** error-level failures, both in
`sym.pin_length`: `Crystal_GND24_Small` mixes 0.635 mm and 1.27 mm stubs,
`LSM6DS3` mixes 2.54 mm and 3.81 mm. Nothing else turned red. That is what
severity and computed conformance were built for.

**The Value rule is now seven rules under one key.** A resistor's Value is
checked against the RKM code, a capacitor's against the unit format, an IC's
against its part number verbatim, a test point's against its own name. A
category no rule covers yet falls through to the same human question as before,
so nothing was lost. The Checks page shows them as `BASE.Resistance`,
`BASE.MPN`, `BASE.Component name` and so on, each with the condition it applies
under.

`fp.quad_numbering` catches the mirrored-footprint defect the skill records as
having shipped once. It reads the direction the pads trace in number order:
every one of the 48 IC packages in the library runs counter-clockwise, and the
seven parts that run the other way are all connectors, whose numbering follows
the datasheet and which the check deliberately does not cover.

**Six parts carry a standing exception instead of a recurring finding.** The
four `15EDGKNM` connectors, `KEYS2466` and `RPi_CM5` are the deviations the
library conventions already document. Each now holds a recorded decision with
the reason on it, so the rule stands for everything else and nobody re-discovers
them.

## 2026-09-14 — A check can read the drawing

Checks could only ask about a component: its category, its base symbol, its
fields. A symbol or a footprint carried three facts - its kind, its name and a
fingerprint - so every geometry rule stayed prose in a skill document for an
agent to read and re-read.

They now carry their own. A footprint check can ask for the pad count, the lead
pitch, how many pads sit off the 0.1 mm grid, which corner pad 1 is in, and
whether a quad package numbers counter-clockwise. A symbol check can ask for the
pin count, the distinct pin numbers, the unit count and which electrical pin
types are present.

Three facts compare two things, which no single assertion can do:

- **`$pins_without_pads`** - symbol pins whose number has no pad. A signal with
  nowhere to land.
- **`$pads_without_pins`** - pads the symbol does not draw. Usually an exposed
  thermal pad or an NC lead.
- **`$value_is_mpn` / `$value_is_name` / `$value_placeholder`** - the three
  shapes the Value rule takes.

Measured over all 439 components: **13 parts** have a gap between symbol and
footprint, and **every one of them is a pad the symbol does not draw** - an
exposed pad or an NC lead. Not one part has a pin with nowhere to go. Splitting
the one "mismatch" number in two is what made that readable.

Two counting errors are fixed with it. The pad count used to include paste
apertures and thermal vias, so a QFN-16 with an exposed pad reported 26 pads
instead of 17. And a two-pad chip resistor was reported as having pad 1 in the
"bottom-left" corner; it has no corner, and now reads "left".

The Checks page reads the fact list from the platform instead of holding its
own copy, so a footprint rule is never offered a component fact.

## 2026-09-14 — "Does not apply" is one decision, and it lasts

N/A is gone as an answer. The button on a check now reads **Does not apply...**
and it records a standing decision instead of a note on one version.

The two used to say the same thing, and only the throwaway one got used: 314
live N/A answers, 312 of them written by agents, not one with a reason on it,
every one due to expire at the next version bump - against zero rows in the
table built to hold such decisions. The reason was simple. N/A was the button on
the row.

Three things change for you:

- **You can say it about a check nobody has run.** Every judgment item offers
  it, not only a failing one. A check that is not about this part does not need
  running first.
- **It asks three questions**: which way it does not apply, why in your own
  words, and how long the decision holds. The note is required, because it is
  the only place the reason will ever live.
- **Excused items leave the count.** A card reads "judged 3 of 9" with "2
  item(s) excused by a standing decision" beside it. An exception says the
  question is not about this part. It never says somebody looked.

An earlier bug is fixed with it: granting an exception on an item nobody had
answered yet did nothing at all until an unrelated save happened to run. It now
takes effect on the response.

The library health panel also reports automatic failures again - `fp.courtyard_grid`
on 76 footprints, `cmp.datasheet_text` on 47 components. Those went invisible
when automatic checks stopped being written into records.

Agents keep working. The API still accepts "na" and turns it into a pinned
exception, so an agent cannot record a blanket waiver over every future version
of a part - only a person can, in the review card. An agent's decision must now
carry a note.

Decision record
[0018](docs/decisions/0018-does-not-apply-is-an-exception-not-an-answer.md).

## 2026-09-14 — Excusing a check takes one button

A standing exception was already in the platform, but nothing said so. The only
way in was Verify... then N/A then "keep this decision?", and that chain sat
under three folds: the verification row, the checklist, and verify mode. A
failing check in front of you looked like something you could only fix or
ignore.

Now a failing row carries an **Excuse...** button. It asks three things - why,
a note, and how long the decision holds - and it needs no verify mode, because
an exception is not an answer and stages nothing.

Four smaller changes in the same place:

- A part with a failing check opens on that check. The row and its checklist
  are unfolded for you.
- Clicking the row LABEL opens it. Before, only the small triangle worked.
- Standing decisions list above the checklist, so one you grant can be found
  again. Each has its own **Revoke exception**.
- The card's own Revoke is now **Revoke verification**. Two identical red
  buttons a few pixels apart withdrew very different things.

A component can now pin an exception to its own fields - "while this
component's own data is unchanged". Its `$material_sha` is the symbol's and the
footprint's joined together, so the drawing scope said nothing about a Value or
a datasheet. The scope label reads what was actually pinned.

## 2026-09-14 — Automatic checks are worked out, not remembered

Change a check and the whole library re-reads itself. There is no "Re-run auto
checks" button and no "Apply to existing parts" button, because there is nothing
left to re-run: the automatic answers are computed when something asks for them,
and cached against a fingerprint of the checklist, the part and its exceptions.
Edit any of those and the fingerprint changes, so the next read works it out
again.

Measured: tightening the drill minimum from 0.3 mm to 0.45 mm reported 19
failing footprints across all 212 immediately — no republish, no backfill.
Publishing a check used to do the opposite: adding one moved 418 components to
"partial" in a single publish, and the only ways out were a mass republish or
answering them by hand.

Two smaller effects worth knowing. Completeness is now measured over the
judgment items only, so a machine check can never sit "unanswered". And "Mark
checked" no longer hides a failing automatic check — it vouches for the
judgment, not for what the code can still see.

Decision record
[0017](docs/decisions/0017-conformance-is-computed-not-recorded.md).

## 2026-09-14 — Warnings, and decisions that last

**A check now has a severity** — error, warning or ignore. A warning-level
failure is shown and counted but never makes a part read as failed, which is
what lets a new check ship at all: publishing one used to re-open the whole
library, and four checks were seeded *switched off* to avoid it. Those four are
now warnings, which is what "off" always meant. The severity is recorded on the
answer, so editing a checklist never rewrites what a past review meant.

`Ignore` replaces the old on/off switch: one control with three values instead
of a switch beside a severity.

**And a decision can be kept.** Answer a check N/A on the review card and it now
asks whether to keep it — for this drawing, or for this part always. A standing
exception outlives the version, so a pad move no longer takes it with it. The
part lists its exceptions with who granted each one, why, and what it is pinned
to; revoking one brings the check straight back.

This is the fix for something the numbers made plain: the library held **zero**
waivers, while agents had invented **188 different `custom:` check names**, 150
used exactly once. Nobody was refusing to record decisions — a waiver died with
the version, so nobody wrote one.

An exception scoped to the drawing dies the moment the copper moves, and one
pinned to a fact the part has not got is refused rather than being quietly
stale. Both halves are copied from KiCad's own DRC model, which has carried a
severity per rule and a list of excluded findings for years. Decision record
[0016](docs/decisions/0016-severity-and-standing-exceptions.md).

## 2026-09-14 — Checks you write instead of code

A check can now be **declarative**: pick a fact about the part, pick one
assertion, and the validator answers it. No new code per rule.

```
$symbol_reference   is one of    J
$symbol_pin_count   is at least  1        when $symbol_on_board ^true$
$footprint_pad_count is at least 2
```

Facts are the same vocabulary `when` reads — properties, `$category`,
`$base_symbol`, `$purchasable` — plus new ones derived from the drawings a
component pins: `$symbol_reference`, `$symbol_pin_count`, `$symbol_unit_count`,
`$symbol_on_board`, `$symbol_sim_link`, `$footprint_pad_count`,
`$footprint_has_model3d`. They are computed only when a check reads one, so a
checklist mentioning none costs nothing.

Assertions: is one of · matches · is exactly · is at least · is at most · is
present. Exactly one per check — the wording is written from it, so the sentence
a reviewer reads cannot disagree with the rule.

This is what makes symbol rules per component category possible: a symbol has no
category, but the component pinning it does, so the check lives on the
component. Trialled on Connectors: `$symbol_reference is one of J` found six
parts drawn as USB, CN, CN, BAT, BAT and FPC, and `$symbol_pin_count is at least
1`, narrowed to board parts, correctly passed over the seventeen off-board
terminal-block plugs instead of failing them.

## 2026-09-14 — One check, several variants

A check can now be stated more than once for one scope, as named **variants**:
`Transistors.NMOS` requires `Drain Source Voltage`, `Transistors.NPN` requires
`Collector-Emitter Voltage`, and both are `cmp.required_props`. That was the one
thing a `when` predicate alone could not do, and it is what
`conditional_required_properties` has been asking for since the original YAML
import.

The Scope column reads `Category.VARIANT`, so filtering `Scope` for
`Transistors.` gives you every sub-type rule at once.

**No ordering to remember.** A key with several variants must split on ONE field
with distinct values, plus at most one variant with no condition — the fallback.
At most one can match, so nothing depends on the order they are written in, and
a sorted table cannot contradict the effective rule. The save path refuses a
variant nothing can reach: a condition matching everything, a duplicate
condition, a second fallback, or a split across two fields.

A disabled variant falls through to the next one; disabling every variant is
what switches the check off. A category restating a key replaces its whole
group.

**And the fragility is now countable.** Open a varied check and it prints how
the live parts fall: `14 part(s) in scope · NMOS 7 · NPN 3 · other 4`. A
non-zero "no match" means the field you are splitting on is not reliable — which
is the honest signal that the category wants a subcategory instead of a
predicate.

## 2026-09-14 — Every check in one table

Reviews → Checklists is now a single `DataTable` of every check in the
platform — one row per scope and check, with a filter on every column. Filter
**Scope** to see what one category does differently, **Applies when** to find
the conditional ones, **Runs** for what is switched off; sort by **Key** and a
check lines up with every override of it, so `cmp.required_props` across
fifteen categories reads as fifteen adjacent rows.

A new check is added in the first row of the table: pick its scope, type its
key and what it asks, press Add. There is no separate form.

Rows are what a scope STATES, not the cross product — a category contributes
only what it changes, which is the same question answered from the other side.
Open a row to edit its settings, its `when` predicate, or a judgment check's
wording.

Publishing is per scope and the button says how many: a checklist version
belongs to one scope, so editing rows from three scopes publishes three
versions, and both the toolbar and the confirmation name them.

## 2026-09-14 — A check says which parts it is about

A checklist item can now carry a **`when` predicate**: "apply this check to
components where `comp_type` matches `^TVS$`", or `$category`, `$base_symbol`,
`$purchasable` — a bare name is a property, a `$` name is a structural fact the
API validates. Every condition must match. Edit it under the caret on any
check; a row that has one is badged `when`. Decision record
[0015](docs/decisions/0015-a-check-says-which-subjects-it-is-about.md).

This is what `conditional_required_properties` has been waiting for since the
original YAML import — it has sat in the Diodes and Transistors rule blocks
since the beginning with no check implementing it.

A check whose predicate a part does not satisfy is reported as **n/a here**, not
as switched off. Those are different statements — one says the check is not
about parts like this one, the other says the owner turned it off — and the
review card prints them separately.

One caution, recorded in the decision: a predicate over a PROPERTY is only as
stable as the property. A category is a row; `comp_type` is free text, and the
library already carries the `ZENNER` spelling the conventions skill flags. An
edit there silently stops the check running.

## 2026-09-14 — A check carries its own settings, and the rules table is gone

**Reviews → Checklists is one tab per kind now**, not one entry per checklist.
Components, Symbols, Footprints in the sidebar; the scope is a dropdown in the
header, with a dot against each category that already states something. A
category's list is created the first time you save one and removed when it
states nothing, so the sidebar cannot fill with empty lists.

**Every check is one row, folded.** Key, what it checks, where it comes from,
whether it runs — and the caret opens the rest: the thresholds, the property
lists, the patterns, the wording of a judgment check. Filter by Stated here /
Automatic / Judgment / Switched off, or search by key.

Every number, list and pattern the validator measures against now lives on the
checklist item of the check that uses it, under the sentence it produces.
Reviews → Checklists → any list, **Automatic checks**: the drill minimum sits
under "No drill hole below 0.3 mm", the courtyard width under its own check, and
a component's required properties under `cmp.required_props`. Decision record
[0014](docs/decisions/0014-a-check-carries-its-own-configuration.md).

**Fifteen per-category rule sets started working.** They were seeded from the
YAML libraries at the original import and **nothing had ever read them**, so
"a Capacitor carries Value and Voltage" had never been enforced on a single
part. Each one is now a category-scoped component checklist you can edit, and
the merge that was already there does the scoping. Measured over 439
components: **189 now have their property values checked where nothing checked
them before**; 13 fail the new `cmp.property_values` and 11 fail
`cmp.required_props` on rules their own category had always stated. Nothing
already recorded moved — a part picks the rules up on its next publish or its
next "Re-run auto checks".

**Two new checks, both per-category.** `cmp.property_values` applies a
category's value patterns. `cmp.base_symbol_allowed` is the first SYMBOL rule
scoped to a component category: a symbol carries no category, one base symbol
is shared across categories, and a symbol nothing uses yet has none at all — so
the check is answered on the COMPONENT, where the category is exact. List the
base symbols a category allows and a part pointing at the wrong one fails
mechanically instead of waiting for somebody to notice. Both are switched OFF
on the base list with an empty set, so no part gained an unanswered item; fill a
set in on a category to turn one on. (Dry run: allowing only `R` for Resistor
flags `NCP15XH103F03RC`, which is drawn as `Thermistor_NTC`.)

The `rules` table is dormant; a startup migration folded it into the
checklists and reports the keys nothing consumes rather than dropping them
(`conditional_required_properties` on Diodes and Transistors is the one real
rule still unimplemented).

Two fixes fell out of it. An empty manufacturer list now means the check does
not apply, which is what `Mechanical_7S` and `TestPoints` were saying — read as
"none of these is filled in" it failed all 14 of those parts. And a parameter
is refused on save unless it fits its type: a threshold above zero, a pattern
that compiles.

## 2026-09-13 — An automatic check is switched on or off, not typed out

The checklist editor no longer asks anybody to write down what an automatic
check does. `services/validator.py` now carries the catalogue — key, text and
hint for every check it answers — and the editor renders that catalogue
read-only with one switch per row. Saving rewrites a machine item's wording from
the code, so an automatic item can no longer describe a rule the validator does
not apply. Decision record
[0013](docs/decisions/0013-the-validator-owns-the-automatic-checks.md).

**A category checklist can now modify what it inherits.** It always merged on
top of the base list, but additively: it could add a check and reword one, and
it could never say "the base list asks for this and my parts have not got the
thing it asks about". The category editor now lists every inherited item with
three choices — inherit it, override its wording here, or switch it off for this
category. `Reviews → Checklists → New category checklist` creates one.

**Switching a check off turns it off, and the card says so.** The resolved
checklist is now the validator's switchboard: a switched-off key is not run into
the record, an answer it already had is dropped from the next record for that
subject, and the review card and the agent's `get_review_checklist` report it
under `switched_off` rather than leaving the question unexplained. Both kinds of
switch only reach COMPONENT checks per category — symbols and footprints have no
category, so their checks switch on their base list, for every part at once.

**Two new ways to re-run the automatic checks without publishing.** "Re-run auto
checks" on a review card does one subject; "Apply to existing parts" on a
checklist does every subject that list governs. Until now the validator ran only
inside a publish, so refreshing the machine answers meant publishing again —
which drops every agent answer the new version cannot carry. A re-run writes at
the machine tier only: it cannot overwrite a human or agent answer, and it
closes no queued review request.

Two automatic checks that were built but never seeded — `sym.sim_link` and
`cmp.sim_params` — now appear in the editor switched off, so the deferred
decision is one click away instead of invisible.

## 2026-09-13 — `LSM6DS3` redrawn to the house geometry

The symbol put VDDIO and VDD on the top edge and both GND pads on the bottom
edge, which §3 of `conventions-symbols` forbids on anything that is not one of
the §5.6 digital blocks. It was also the first symbol the new `sym.pin_length`
check failed. Published as v5; `LSM6DS3TR-C` was repointed automatically and
starts unreviewed.

No pin number, name, electrical type or count changed — only positions, stub
lengths and visibility. Five defects:

- **Supplies and grounds moved to the left edge**, supplies in the top two
  slots and GND 6 and 7 in the bottom two, so a ground symbol drops straight
  into them instead of turning back under the box.
- **Pins 10 and 11 were 3.81 mm stubs** against 2.54 mm on the other twelve.
- **Pins 10 and 11 also ended 3.81 mm INSIDE the body.** Their connection
  points sat at x = 12.7, which is the body outline itself, so the stub ran
  inward. §4 requires the tip to land on the outline.
- **GND 6 and 7 were a coincident stacked pair with neither hidden** — the
  open finding from v3. They are now two separate visible pins.
- **NC 10 and 11 were hidden.** They are not a stack, so nothing justified it,
  and a hidden `no_connect` pin cannot be given the X marker §2 requires.

Grouping follows the §3 right-side order and was checked against ST
DocID030071 Rev 3 Table 2 (p.20): host serial interface (CS, SCL, SDA,
SDO/SA0), then the sensor-hub master I²C that Table 2 gives as MSCL/MSDA
(SCX, SDX), then the interrupts. One blank slot between groups. Still one unit.

**The NC pads sit on the LEFT edge, above the grounds** (owner instruction).
They carry no net, so they cost nothing there, and moving them off the right
edge drops it from 13 slots to 10. Both edges now span the same height and the
body is 27.94 mm instead of 33.02 mm.

`CS` keeps the plain `line` pin style on purpose. The inverted-bubble rule is
scoped to §5.6 digital blocks, and Table 2 gives CS as an I²C/SPI **mode
select** (1 = I²C enabled, 0 = SPI), not a plain active-low strobe.

`Crystal_GND24_Small` (0.635 mm and 1.27 mm stubs) is the remaining
`sym.pin_length` failure and is untouched.

## 2026-09-13 — A dead pad is stacked, not drawn twice

Three hours after the section above was written, the library owner drew the part
a better way, and the rule it stated is reversed.

- **A straight-through routing pad is now STACKED hidden on the pin it faces.**
  The symbol draws one pin per channel, and the netlist carries BOTH pads on
  that channel's net, so pcbnew raises the ratsnest and DRC does not pass until
  the straight-through trace is drawn. The earlier rule drew the dead pads as
  separate visible pins and trusted the designer to remember the wire across the
  body. `conventions-symbols` v17 states the new rule in section 2.1.
- **`no_connect` on a stacked pin is worse than wrong, it is silent.** Measured
  on KiCad 10.0.5 with a netlist export: KiCad DROPS a hidden `no_connect` pin
  out of the stack, gives its pad a private `unconnected-…` net and warns
  `no_connect_connected`. A drawing that looks like it carries the signal
  across the package carries nothing. `free` carries the pad and stays quiet
  when a design leaves the pads open.
- **Small parts may hide a duplicate power pad again.** The "redundant GND/VDD
  pads are NOT stacked" rule was written for large ICs and was being enforced on
  four-pin parts. It now says what it meant: a symbol split into units never
  hides a power pin; a small part may, with a REASON written in the version
  comment and the `sym.stacked` note; and on the boundary the author asks the
  user, while a reviewer records `custom:stacked-power-pad` so the question
  reaches the Reviews queue.
- **The symbol is published and verified.** `TPD4E05U06` v6 carries the owner's
  drawing — four TVS glyphs on a common ground rail, the straight-through pads
  stacked hidden and typed `free`, GND pad 8 hidden on pad 3 — and every
  checklist item on it is answered. `TPD4E05U06DQAR` was verified against the
  section 6.6 table of SLVSBO7L Rev. L at the same time: `5.5V` stand-off,
  `6.5V` breakdown minimum and `10nA` leakage maximum all hold. Note for later
  passes, recorded on the part: the PROSE in section 7.3.5 contradicts that
  table, quoting 6 V and 5 V. The table is the authority.
- **Three corrections to the description templates**, `conventions-library`
  v33. The multi-channel ESD array row hard-coded "4-Channel" — right for the
  one part on the row, and a false channel count on the first 6-channel
  sibling; the count is now a literal written per part, the way the SMAJ row
  already treats the direction word, checked against the datasheet's pin table.
  The simple 2-pin TVS clamp row now says why it carries no direction word
  where the SMAJ row below calls that word mandatory: the row is scoped to the
  `D_TVS_Bi` symbol, so every part on it is bidirectional. And the Transistors
  alternation gained `PNP`, which it had never offered; no PNP part is in the
  library yet, so nothing was mis-described.
- **The synced KiCad library is a working copy.** A symbol drawn in the PCM
  package on disk is replaced by the next **Sync 7Sigma Library**, and nothing
  said so. [docs/reference/kicad-integration.md](docs/reference/kicad-integration.md)
  now does.
- **"A cathode bar is never a C" is a footprint rule.** It lives in a
  validator-enforced section with no domain stated, and a symbol's zener glyph
  is a C on purpose. `conventions-footprints` v36 says which layer it governs.
- **Cite an artifact, not a memory.** The skill had named `TPD4E05U06` as the
  precedent for a stacked `NC` pad; a pass that could not find the stack in any
  published version struck it out as fiction. The platform drawing had never
  carried it and the intent had. A precedent now has to name the symbol AND the
  version it was checked against.

## 2026-09-13 — Pin stub length follows the pin NUMBER, not the pin count

`USB_C_Receptacle_USB2.0_16P` kept failing its `sym.geometry` check. It is a
verbatim stock KiCad `Connector:` drawing with 5.08 mm pin stubs, and the
`conventions-symbols` rule said 2.54 mm with one exception, "very high pin
count", recorded against `STM32H573IITxQ` (176 pins). A 17-pin connector did
not qualify, so every verification pass flagged a symbol that was correct.

The rule was keyed on the wrong thing. KiCad draws the pin NUMBER along the
stub, so the stub is the space the number has. Measured with
`kicad-cli sym export svg`, which reports each string's plotted width, at the
1.27 mm house font:

| Pin number | Width | Against a 2.54 mm stub |
|---|---|---|
| `A` | 1.29 mm | fits |
| `B1` | 2.68 mm | 0.14 mm over — accepted |
| `A12` | 3.71 mm | 1.17 mm over — prints into the body |

A survey of all 198 base symbols confirmed pin count was never the driver: 58
carry a length other than 2.54 mm, including `XC6206PxxxMR` (3 pins) and
`LD1117S` (4 pins) at 5.08 mm, and every `Conn_*` symbol at 3.81 mm.

- **`conventions-symbols` v16** replaces the pin-count exception with a
  pin-number-width one: 2.54 mm by default, 5.08 mm when any pin number runs
  to three or more characters — alphanumeric connector designators (`A12`,
  `B12`), BGA coordinates, three-digit numbers. `USB_C_Receptacle_USB2.0_16P`
  is now correct as drawn and no longer needs a geometry finding.
- **New machine check `sym.pin_length`**: every pin in a symbol uses the same
  stub length. The absolute value stays a judgment call on `sym.geometry`,
  where the new three-character rule is now a hint; mixing lengths inside one
  drawing is purely mechanical, and it is what actually goes wrong. Across the
  library it finds two: `LSM6DS3` (2.54 mm on 12 pins, 3.81 mm on 2) and
  `Crystal_GND24_Small` (0.635 mm and 1.27 mm). Neither is changed here.
- **The `sym.pins_grid` check was reading past pins.** Both symbol checks now
  split the source into pin blocks instead of matching `(at …)` straight after
  the `(pin …)` header. The child tokens are not in a fixed order — `LAN8671`
  carries `(hide yes)` before `(at …)`, and that pin was skipped silently, so
  an off-grid hidden pin could have passed. The block scanner is also anchored
  to the start of a line, because `A_S-1WR3` has the text "5-pin SIP (pin 3
  absent)" in its Description and the old shape matched it.

`sym.pin_length` is seeded for new installations. Adding it to the live base
checklist is a manual step in the Skills → Checklists view, and it un-answers
the item on every existing symbol with no backfill, exactly as
`cmp.datasheet_text` did on 2026-08-25.

## 2026-09-13 — A straight-through routing pad is not a `no_connect`

`TPD4E05U06` reported an ERC error as soon as the schematic wired its right-hand
pads. TI builds the TPD family for flow-through routing: pads 6, 7, 9 and 10 of
the DQA package carry no internal connection and sit directly opposite the pin
whose trace they continue, so the board runs one straight trace onto the signal
pad and off the dead pad facing it (1-10, 2-9, 4-7, 5-6). The datasheet says so
in the description column of the pin table, not in the `NC` name alone —
"Not connected; Used for optional straight-through routing. Can be left floating
or grounded" (SLVSBO7L Rev. L p.5) — and draws it in the layout example on p.16.

- **The four pads are now electrical type `free`, not `no_connect`.**
  `no_connect` tells KiCad the pad must never be connected, so the designer's
  pass-through wire raises `no_connect_connected`. Measured on KiCad 10.0.5:
  `no_connect` errors when a wire lands on it, `passive` errors with
  `pin_not_connected` when the design leaves the pads open, and `free` is clean
  both ways. The pass-through is optional per design, so both cases happen and
  `free` is the only correct type. Pin numbers, names, positions and count are
  unchanged. The symbol now verifies `checked` on every item.
- **The rule is written up as `conventions-symbols` v15, section 2.1.** The
  same reading applies to the rest of the TPD family and to any package a
  datasheet calls flow-through. **Superseded the same day** — v15 asked for the
  dead pads to be drawn as separate visible pins, and v17 stacks them instead;
  see the section above.
- **The pin-1 circle came off the symbol.** A symbol carries no pin-1 marker
  since the house rule of 2026-09-13. Pin 1 is named by its printed number, and
  the orientation marker is a footprint job.

## 2026-09-13 — The SMAJ TVS family reads one way

Verifying `SMAJ28A` turned up four things the family had been carrying, none
of them a defect in the part in front of us.

- **Four SMAJ parts printed a part number where the rule asks for a rating.**
  `Value` plus the reference designator is the only part identity printed next
  to a symbol on a schematic sheet, and the house rule sends a TVS to its
  reverse stand-off voltage. `SMAJ28A` had been moved to `28V` on 2026-09-13;
  `SMAJ12A`, `SMAJ24A`, `SMAJ24CA` and `SMAJ28CA` still read as their MPN.
  They now read `12V`, `24V`, `24V` and `28V`. The MPN is untouched on
  `Manufacturer Part Number 1`, which is what the BOM draws from.
  **`SMAJ24CA` is fitted on CE_Aqua_V2 at D12, D13 and D19**, so those three
  refs will print `24V` after the next library sync. Same symbol, same land,
  same netlist, same part ordered.
- **Two TVS base symbols offered through-hole footprints.** `SMAJxxA` and
  `D_TVS_Bi` both carried `ki_fp_filters "TO-???* *_Diode_* *SingleDiode* D_*"`
  on twelve components that are surface-mount without exception. The filter is
  what narrows the footprint chooser, so naming a package the part is not made
  in turns the one control meant to prevent a wrong land into a source of them.
  Both now read `D_*`, which covers every land actually in use — `D_SMA`,
  `D_SOD-123FL`, `D_SOD-323`, `D_0402_1005Metric` — and every stock KiCad
  diode footprint. No pin, graphic or geometry change, so every verification
  carried.
- **`SMAJ12A` simulated a clamp 21% above the part's guaranteed maximum.** Its
  `Sim.Params` carried `RS=0.5`, where the datasheet clamping point (19.9 V at
  20.1 A, breakdown 14.0 V) gives 0.29 Ω — so the model clamped at 24.05 V
  against a guaranteed 19.9 V. `RS=0.3` now puts it at 20.03 V, 0.7% high, and
  back in line with how its siblings were derived (`SMAJ24A` derives 1.05 and
  stores 1.2; `SMAJ28A` derives 1.44 and stores 1.5 — round up, so the model
  errs pessimistic). `CJ` is deliberately untouched on all three: the SMAJ
  datasheet states no junction capacitance, so there is nothing to check the
  existing estimate against and a replacement would be a guess.
- **Both TVS symbols are now findable by what they do.** `D_TVS_Bi` still
  carried `ki_keywords "diode TVS thyrector"` — no unabbreviated
  "transient voltage suppressor", no direction, and no "ESD" or "clamp" even
  though five of its seven components are ESD protection diodes. It now reads
  `diode TVS transient voltage suppressor bidirectional bipolar ESD clamp
  thyrector`, matching the widening `SMAJxxA` got in 2026-08. Direction is the
  word that most needs indexing here: the library holds both kinds on lookalike
  SMAJ part numbers.

`conventions-library` v31 records the direction word as part of the SMAJ
`ki_description` template — all five parts had carried `Unidirectional` /
`Bidirectional` since 2026-08, but the skill's table still showed the row
without it, so the next standardization pass would have stripped it back out.
It also closes the `Value` question with the reason it went unfixed for so
long: a family-wide deviation defends itself, because when every sibling is
wrong the same way, consistency reads as evidence.

## 2026-09-13 — A flagged machine item can be answered

An `auto` checklist item that an agent flagged as wrong rendered read-only in
the verification card. There was no way to accept it, waive it or re-check it
by hand, so the finding sat on the part for ever.

- **The Checked / N/A / Flag buttons now appear on any machine item that
  carries a finding**, `failed` or `flagged`. Before, the card offered them on
  `failed` alone. A machine item that PASSED still offers none — the validator
  owns those.
- **`cmp.datasheet_text` is the item this shows up on.** An agent flags it when
  the archived PDF is only partly searchable, which is a judgement a person has
  to close, not a rule the validator can re-run.
- **Nothing changed in the API.** A human answer has always outranked an
  agent's on any key, and the answer it replaces is still kept as `superseded`,
  so accepting a flag does not erase the description of what was found.
- **A machine item nobody has answered yet is still read-only.** Backfilling
  one still needs the API.
- **The lifecycle pill is drawn the same size as the pills beside it.** It sat
  in a button row, which stretched it to the height of the select next to it
  and pushed the pair out of line. The component detail header also wraps now
  instead of letting a long part number push the pills on top of each other.

## 2026-09-13 — The nano-SIM socket is drawn the size it really is

`7Sigma:nanoSIM_ShouHan_TL6P-H1.35` published an outline of 11.18 x 12.82 mm
for a part that measures 11.00 x 12.30, sitting 0.06 mm off centre. Version 7
redraws it. No copper moved.

- **`F.Fab` and `F.SilkS` now trace the part.** Body 10.0 x 10.4 mm with the
  top-left corner chamfered, four corner legs out to y +/-6.15, two shell tabs
  out to x +/-5.5. The silk used to stand visibly outside the connector in a
  3D render; it no longer does.
- **Two sources agree on the size to a hundredth of a millimetre.** The STEP
  model's own vertices, and the vendor drawing measured at 600 dpi with the
  scale taken from the two mounting-hole centres. The old outline's own commit
  message quoted 11.0 x 12.3 and then published 11.18 x 12.82.
- **The courtyard is symmetric again**, x +/-6.1 by y +/-6.9, and never larger
  than before in any direction, so it cannot raise a new clearance violation on
  a board already laid out.
- **The `F.Fab` pin-1 circle moved inside the outline**, from (2.5, 6.0) to
  (2.5, 4.9).
- **Boards keep their own copy until they are updated from the schematic.**
  CE_Dongle_V3 carries this part; nothing breaks, and the board shows the old
  silkscreen until its owner refreshes it.
- **The land pattern was verified, not changed.** Pad sizes match the drawing
  exactly; every pad and hole position is within 0.10 mm of it, which is the
  0.1 mm grid the house convention asks for. The part's own leads sit inside
  their pads with at least 0.16 mm to spare.
- **`conventions-footprints` v35 drops this footprint from its origin-offset
  list.** The +0.060 recorded there was the centre of the wrong outline, not
  the centre of the part.

## 2026-09-13 — A footprint preview looks like the footprint editor

The pad numbers landed earlier today on a plot: every layer visible, mask and
paste washing the copper mauve, and the numbers in whatever colour was spare.
A preview is meant to be recognisable as the thing KiCad shows, so the render
now matches the footprint editor's own palette and layer visibility.

- **Mask, paste and adhesive are no longer drawn.** They are translucent
  washes over the copper and they turned KiCad's red pads into mauve ones.
  The visible set is the editor's default, passed to `kicad-cli --layers`.
- **Pad numbers are white, holes are the editor's cyan, and the canvas is the
  board background.** A footprint preview now sits on navy, not on the
  schematic grey a symbol uses.
- **Both renderers are told the same thing.** The layer list is decided by the
  api and travels in the render request, so the container obeys and decides
  nothing.
- **`footprint_theme` is `Skyline-7S` instead of empty.** With no theme named,
  kicad-cli falls back to "footprint editor settings" — whatever KiCad config
  the renderer happens to carry — and the hole colour really did differ
  between a developer's Mac and the server.
- **Editing a theme file now re-renders.** The preview cache keyed on the
  theme's NAME, so a colour change left every cached picture showing the old
  palette with no way to ask for a new one. The key carries a digest of the
  theme file.
- **Trap worth knowing: KiCad discards a pure-white layer colour.** A layer
  set to `rgb(255,255,255)` plots in a fallback grey instead. The label layer
  is `rgb(254,254,254)`.

`services/pad_labels.py` is now `services/preview_style.py`: it owns the pad
numbers, the layer list and the re-stacking together.

## 2026-09-13 — A footprint preview prints its pad numbers

Every 2D footprint preview — the footprint page, the component page, the
paste box, both panes of a geometry diff — now carries the pad number on each
pad, the way KiCad's own footprint editor draws it. Reading a pinout off a
preview no longer means counting pins from the pin-1 mark.

- **The numbers are drawn, not guessed.** `kicad-cli` plots no pad numbers, so
  the render path writes one `fp_text` per pad into a COPY of the source and
  renders that. Nothing is stored: the `.kicad_mod` in the mirror, the file
  KiCad downloads and the version history are untouched. A preview is
  therefore no longer a byte-faithful plot of the stored source — read
  `api/app/services/pad_labels.py` before comparing one against it.
- **One number per land.** An exposed pad and its thermal vias share a number
  and are labelled once. Two numbers on one land (USB-C A1/B12) are spread
  along the pad rather than written over each other.
- **Through-hole numbers sit on top of the hole.** KiCad plots drill holes
  last, over everything, so the finished SVG is re-stacked to put the labels
  above them.
- **Existing previews re-render once.** The cache key includes the labels, so
  the first view of each footprint after the update costs one kicad-cli run.

## 2026-09-13 — A footprint or a base symbol can be renamed

Until now a name chosen wrongly was permanent. There was no rename, and
delete-and-recreate was refused while any component version referenced the row
— and would have discarded the version history, the review record and the
production sign-off anyway.

- **Rename moves the name AND every reference to it, in one transaction.** One
  new geometry version carrying the new name, one republished component
  version per component that references it, the `.kicad_mod` moved in the
  mirror, and the stale entries in `categories.defaults` rewritten. On the
  footprint page, under "Rename this footprint"; as the agent tools
  `rename_footprint` and `rename_base_symbol`; over HTTP as
  `POST /api/{footprints,symbols}/{id}/rename`.
- **A rename costs no verification and no sign-off.** The land pattern, the pin
  map, the pinned geometry and the part are unchanged, so both carry. The
  `Footprint` property and `base_component` stay material for every other kind
  of edit — the exemption is a mapping on the one pair being renamed, and it
  has one caller.
- **History keeps the old name.** Superseded versions are immutable and go on
  saying what they published under.
- **A board already laid out keeps the old library id** until its owner updates
  the project from the schematic. The geometry lives in the board file, so
  nothing breaks, but KiCad reports the old id as missing until then.
- **`L_Changjiang_FTC404030S` is now `L_CJIANG_FTC404030S`.** `CJIANG` is the
  canonical manufacturer name decided on 2026-09-13. The old name was also a
  KiCad **stock** filename while our land is not the stock land — stock pads sit
  at ±1.35 mm and ours at ±1.4 mm — so it claimed a Tier 0 identity the copper
  does not support. Affects `CE_Dongle_V3` (L4, L5) and `EVSE_20_CTRL` (L8, L9)
  at their next update from the schematic.
- Reasoning, and the three rejected alternatives:
  [docs/decisions/0012](docs/decisions/0012-rename-a-footprint-or-base-symbol-in-place.md).

## 2026-09-13 — A cathode bar is one straight line, and the validator decides its width

- **The 0.2 mm polarity mark is no longer an accepted FAILURE.** It was a rule
  an agent had to remember, and one had already broken it by narrowing
  `D_SOD-123FL`'s bar. `fp.silk_width` now passes exactly **one** `F.SilkS` line
  at 0.2 mm and fails the rest, so a footprint drawn wholly at 0.2 mm is still
  caught. Both 0.1 mm and 0.2 mm are legal for the mark itself.
- **A cathode bar is a single straight line** — never a C-shaped bracket — with
  both endpoints on the 0.1 mm grid, on or within the courtyard, and at least
  0.1 mm clear of pad copper. Its stroke may overhang the courtyard outline,
  which is thinner; only the line's position matters.
- **Nine footprints corrected.** `D_0402`, `LED_0402`, `LED_0603` and
  `LED_Silverlight_M3535N1` were C-shaped, and the Silverlight bar was two
  overlapping segments. `D_SOD-323` sat off-grid at x = −1.61. `D_SOD-323`,
  `D_SOD-123FL`, `LED_OSRAM_SFH4725AS` and `LED_Silverlight` had bars hanging
  outside the courtyard. `D_0402` and `LED_0402` had endpoints at y = ±0.45.
  Widths were left as drawn.

## 2026-09-13 — Verifying a land: JLC beats a dimension read off a drawing

- **`conventions-footprints` §1 now covers CHECKING a footprint, not only
  creating one.** A pass read "0.60 x 1.40" off a scanned XKB drawing and
  changed `USB_C_Receptacle_XKB`'s rear shield slot to a 1.4 mm drill. The JLC
  land for the same LCSC code uses 1.2999974 — what the footprint already had.
  Reverted. One `easyeda2kicad --lcsc_id=` call answers the whole question, and
  when a scan and JLC disagree, JLC wins.
- **The origin follows the vendor land, not the body centre**, for a connector
  or switch whose body overhangs its pads. Six footprints on this BOM anchor
  that way, from −4.495 mm on the RJ45 to +0.060 mm on the nanoSIM. The
  `fp.origin` checklist item still says "centred on the body" and is what made a
  pass flag a correct footprint.
- **The platform copy and the installed copy use different variables.**
  `${SEVENSIGMA_DIR}/3DModels/…` on the platform is rewritten at PCM package
  time to `${KICAD10_3RD_PARTY}/3dmodels/com_sevensigma_models3d/…`. Converting
  between them is expected in both directions — it is not KiCad corrupting the
  path on save.
- **`CJIANG` is the canonical manufacturer**, added to the table in
  `conventions-library`. `L_Changjiang_FTC404030S` was renamed in place to
  `L_CJIANG_FTC404030S`, carrying its verification across.
- **Accepted deviations recorded rather than "corrected":** the SOT-23 family's
  1.00 mm pitch, the `Crystal_SMD_3225` pads at y = ±0.90, the house chip lands
  under Tier 0 names, and `TS24CA`'s contact placement — all deliberate, all
  now carrying the numbers that prove a later pass does not need to re-derive
  them.

## 2026-09-13 — Every footprint on CE_Dongle_V3 is verified, and a 3D model can finally be measured

All 38 distinct footprints on the CE_Dongle_V3 BOM were checked against their
documentation. Twenty had never been verified at all. Machine-item failures on
that BOM went from nine to zero.

- **`fp.model_fit` is no longer unverifiable.** Every pass before today recorded
  it `skipped`, for want of a tool. `scripts/model-bbox.py` measures a STEP
  model from its own coordinates, and `scripts/footprint-render.py` renders a
  footprint in 3D with `kicad-cli` so a model can be judged by eye. Both are
  now required by `conventions-footprints` v31.
- **Measure vertices, not every point.** A bounding box over every
  `CARTESIAN_POINT` is invalid: a STEP `LINE` carries a reference point that can
  sit far out along its own infinite line. That error produced four false model
  defects in this sweep — a −3578 mm enclosure, an 80 % oversize switch, a 58 mm
  RJ45 and a lightpipe said to have no clearance. All four were withdrawn.
- **Thermal vias were eating their exposed pads.** `VQFN-40` (ESP32-C6) had
  0.00 mm of EP copper outside the via ring, against the 0.2 mm minimum;
  `QFN-16`, both `QFN-56` variants and `QFN-68` were 0.05 mm or less. Cause: the
  via was enlarged to the house 0.6 mm on a 0.3 mm drill while keeping the via
  centres KiCad stock drew for its smaller 0.5/0.2 vias. Rings pulled inward;
  `VQFN-40` also gained the back-side `B.Cu` land that stock carries.
- **Mechanical pads no longer carry pin numbers.** The support tabs on
  `SW_Push…TS24CA` and the steel bracket feet on `SW_Push…TC-6615` are now named
  `MP` instead of `3` and `4`. The bracket numbering is what made SW2 on
  CE_Dongle_V3 electrically dead. No net changes on any existing board.
- **`RJ45_RCH_RC01812`'s model** sat 4.1 mm inside the board. Z offset set to 0.
- **The SOT-23 1.00 mm pitch is a decided house choice**, not the defect three
  separate passes filed it as. Recorded in `conventions-footprints` v31.
- **Section 8 of the footprint conventions was wrong.** It told agents to omit
  `F.CrtYd` on non-electrical parts, relying on a
  `footprint_style.exempt_base_components` list that does not exist in the code.
  `validate_footprint` fails `fp.courtyard_present` unconditionally and never
  reads the rule block. Two agents followed the old text and published
  footprints that failed validation. Corrected in v29.
- **The validator had never run on most of these footprints.** Their versions
  predate the 2026-08-24 validation subsystem, so their twelve machine items
  read as unanswered, which is easy to mistake for passed. Backfilled by
  republishing identical drawings with `force`. Library-wide, 89 of 213
  footprints would fail a machine item today; 76 of those on
  `fp.courtyard_grid`.

## 2026-09-13 — A verification has four answers, and "skipped" is not one

- **`skipped` is retired** (decision
  [0011](docs/decisions/0011-retire-the-skipped-verification-result.md)). It
  meant "this item applies, but I could not verify it". Everybody read it as
  "does not apply" — the job `na` already does — so agents used it to mean "I
  did not re-open the datasheet on this pass", even on items a previous pass had
  verified and that had not changed since.
- **An item nobody can verify is now LEFT UNANSWERED**, which produces the same
  `partial` state `skipped` always did. The verification vocabulary is
  `checked` | `na` | `failed` | `flagged`.
- **What it was costing:** 138 stored skips, every single one carrying reason
  `unstated` because the agent tool never had a reason argument; 45 subjects
  held at `partial` by one; **38 of those with nothing else open**. Most notes
  said only that a datasheet was out of scope for that pass, and several added
  that a prior datasheet-backed check had already confirmed the item.
- **`na` now requires a reason code** — `feature_absent`, `kind_exempt`,
  `waived` or `other` — from an agent or a human. `na` is the answer that closes
  an item, so it is the one that has to justify itself. The machine tier is
  exempt: the validator answers `na` in a dozen places ("no SMD pads", "no
  vias") with a note and no code.
- **Nothing was migrated and no subject changed state.** Stored `skipped` rows
  keep the value, are read as unanswered, and are reported separately on the
  health panel as "Left over from the retired skipped answer", so the open work
  stays visible instead of disappearing.
- The review card drops its Skip button; the health panel's "why items are
  skipped" becomes "why items do not apply".

## 2026-09-13 — A symbol shows every unit, one at a time

- **A multi-unit symbol drew only its first unit, everywhere.** A dual op-amp
  looked like a single one and a 10-bank STM32 showed one bank, on the
  component page, the template page, the review workbench, the change feed and
  the paste box. `kicad-cli sym export svg` plots ONE FILE PER UNIT and has no
  switch to write one file, and every preview took the first of those files.
- **Every symbol preview now carries a ‹ A · 1/10 › pager.** The renderer takes
  `?unit=N` and answers with an `X-Unit-Count` header; one control, shared by
  the preview and the before/after diff panes, reads it. The letter is KiCad's
  own — unit 1 is A, the suffix it prints after the reference as `U7A`.
- **The paste box pages too**, by re-rendering the unsaved text. A `blob:` URL
  carries no headers, so there is nothing else it could read the count from.
- **A single-unit symbol and every footprint are untouched**, URL included:
  `?unit=` is only added past the first unit, so their renders keep their place
  in the browser cache and the server's `immutable` promise.
- **Previews were answering 401 on a dev server.** Only `request()` in `api.ts`
  asked for the session cookie, so the big preview's own `fetch` — and the
  thumbnails, and the paste-box render, and the STEP/IGES viewer — were sent
  cross-origin without it and refused by the default-deny gate. The deployed
  app is same-origin and never showed this.
- **The geometry review workbench drew nothing at all.** Its preview pane sat
  directly in a flex COLUMN, where `.preview-fill`'s `flex: 1` (basis 0) beat
  the `height: 420px` beside it, so the box collapsed to its own 10px of
  padding and border. A symbol or footprint review had no drawing to review.

## 2026-09-13 — Counts stop stacking one digit per line

- **Library health reads again.** Every three-digit count on Reviews → Library
  health wrapped vertically — `162` came out as `1`, `6`, `2` on three lines.
  The cards sit in a `.field-grid`, whose tracks are 200px wide at their
  narrowest, and `dl.kv` pinned its label column at a fixed 150px. That left
  the value column about one character wide, and `overflow-wrap: break-word`
  on `.kv dd` did the rest.
- **The label track gives way now, the value track does not.** `dl.kv` is
  `minmax(0, 150px) minmax(min-content, 1fr)`, so the label shrinks first and a
  number keeps its width. Long prose values still wrap, because `break-word`
  keeps their min-content small. `.num` is `white-space: nowrap` as well — a
  number is one token and must never break.

## 2026-09-13 — A gain gets its prefixes too

- **An op-amp's open-loop gain reads and writes `100k`, `1M`, `10M`.** It has
  no unit, so nothing is printed after the prefix and there is no space before
  it — the way a gain is written on a datasheet. Its form allows 1e2 to 1e7 and
  its own default was already the string `100k`, which nothing parsed.
- **The rule is the form's own, not a list of field names.** A unitless value
  gets prefixes when its scale is LOGARITHMIC, because a form asks for a log
  slider exactly when its value spans decades. Anything linear stays a plain
  box: a dielectric constant of 4.3, an emission coefficient of 1.9, a
  threshold at 0.5 of the rail, twenty points per decade. A future parameter
  opts in by declaring `scale="log"` with no unit, with no frontend edit.
- **Loss tangent is deliberately left alone.** `0.002` could print as `2m`, but
  every fab and every datasheet publishes `Df = 0.02`. The same reasoning keeps
  RKM notation off length fields: a box should not fight the convention the
  number is copied from.

## 2026-09-13 — The simulator's numbers carry their units

- **Capacitance, inductance, voltage, current and time are unit-aware fields
  now.** Every ngspice parameter used to be a plain box with its unit printed
  beside it in grey. A diode's saturation current defaults to `2.5n` and its
  form allows down to 1e-18; a capacitance goes to 1e-15 and a PULSE edge to
  1e-12. Typing those as decimals is the defect the length field was built to
  stop. Nine quantities exist in `si.ts` now, up from four.
- **Three places changed, and no form definition did.**
  `sch_lib.PARAM_FORMS`, `sim_scenario.ANALYSIS_FORMS` and `LiveControl`
  already declared a unit per field, so the part inspector, the run bar and the
  live knobs are driven from what the server already sends. A new parameter
  becomes unit-aware with no frontend edit.
- **ngspice spells mega `MEG`, and a field that ignored that would be wrong by
  a factor of a billion.** To ngspice, `M` is MILLI. Our boxes read `M` as
  mega, because that is what a schematic means and what the resistance box
  beside them already did (user decision). So the two directions use different
  tables: what is already stored is read with ngspice's rule, and what we write
  back always spells mega `MEG`. Verified end to end — typing `1M` into a
  resistor puts `1MEG` in the downloaded `.kicad_sch`.
- **A field with no unit stays a plain box.** An op-amp's open-loop gain is
  `V/V`, an inverter's threshold is `x rail`, a sweep is a point count. A
  prefix on a dimensionless number is nonsense, so `quantityForUnit` returns
  nothing for them and the old control renders.
- **Audited every input in the app first**: 379 controls across 73 files, 228
  of them value fields. The simulator was the whole gap. Copper weight is
  deliberately untouched — it is a preset list mapping an ounce label to
  millimetres, not a typed value — and no temperature or mass input exists.

## 2026-09-12 — The agent instructions moved next to the code they govern

- **`api/CLAUDE.md` was 2764 lines and `web/CLAUDE.md` was 1688.** A `CLAUDE.md`
  in a subdirectory is read when an agent opens a file in that directory, so
  every backend task paid for the frontend rules and every frontend task paid
  for the whole backend. Two files carried the rules for about 70 services, 17
  routers, the simulator, the field solver, the flasher and the sync plugin.
- **There are 17 `CLAUDE.md` files now, and the largest is 510 lines.** Each one
  holds what applies to its own directory: `api/app/services/`,
  `api/app/routers/`, `api/app/services/fieldsolver|flasher|pcm_plugin/`,
  `mcp/`, `web/src/components/`, `web/src/pages/`, `web/src/sim/` and its three
  sub-directories. The root file merged its layout and
  routing tables into one that sends a task to the right file.
- **Long-form topics moved to [docs/reference/](docs/reference/)** — datasheets,
  production economics, the review axis, the projects module, SPICE runs,
  simulation models, PCM packaging, KiCad integration, deployment, the Jaravis
  implementation and two past simulator audits. The nearest `CLAUDE.md` links to
  each page, so a rule is written once and read where it applies.
- **The rules that keep this working are written down and checked.**
  [docs/reference/writing-instruction-files.md](docs/reference/writing-instruction-files.md)
  states the six: a 200-line budget per file, the derivability test, link never
  summarise, put a rule in the narrowest file that covers it, never use `@path`
  imports (they load at launch and defeat the split), and state the current fact
  with no narration of what the file used to say. `scripts/check-docs.py`
  enforces the three a machine can decide — line budget, broken relative links,
  and `@path` imports — and reports 0 errors today.
- **No rule was dropped.** Every line of the three original files is either in a
  new file or is a heading level, a table row or a cross-reference that the move
  itself changed. A link check over all 29 files reports no broken relative
  link.

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

## 2026-09-12 — The git mirror is the source archive

- **Ingest no longer stores a `source.tar.gz` per snapshot.** It wrote one for
  every commit and nothing ever read it back. The key appeared twice in the
  whole codebase: the write, and a line in a docstring.
- **The mirrors already held the same content, four times smaller.** Measured on
  the server: 16 stored tarballs came to about 950 MB, which was 68% of the
  bucket, while the bare mirrors that hold EVERY commit of EVERY project come to
  214 MB. One project shows the shape of it — 117 MB of mirror against 533 MB of
  tarballs for 8 commits.
- **The first start after this deploy removes the stored tarballs**, in the
  background and behind the marker `maintenance/snapshot-archives-dropped.v1`,
  the same way the schematic render purge works. The bucket should fall to about
  450 MB.
- **`gitrepo.archive_tgz` rebuilds any tree on demand** from the local mirror,
  with no network call. It is now the only way back to a byte-exact tree.
- **`DATA_DIR/git` must be in the backup set.** After the purge the mirror and
  the upstream remote are the only copies of project source. See
  [decision 0009](docs/decisions/0009-the-git-mirror-is-the-source-archive.md).

## 2026-09-12 — One control, one unit rule, and a tooltip that stays on screen

- **Three input designs became one.** Only `.text` ever declared a border,
  background and focus ring; `.row-input` was used bare 83 times and fell through
  to the browser's NATIVE widget, so the Admin page, the table filters and the
  field solver rendered three different-looking forms. One rule now draws every
  text control, and the size classes carry size only — three heights, 34 / 26 /
  22 px, and nothing else varies.
- **Every unit now prints the same way**: the prefix that puts 1-999 before the
  decimal point, at most three decimals. `0.05 Ω` reads `50 mΩ`, `1 560 432 Ω`
  reads `1.56 MΩ` with a warm ⓘ carrying the exact value. Impedance and
  percentage joined length and frequency, so Target Z and tolerance are the same
  control as design frequency. On a resistance `10M` is megohms and `10m` is
  milliohms.
  - Length changed with it: prepreg 3313 now reads `99.4 um` rather than
    `0.0994 mm`. One rule everywhere was judged worth more than matching a
    single datasheet's spelling.
- **`2.4e9` never parsed**, in any unit field, despite the frequency field's own
  help text advertising it — the exponent was read as a unit suffix.
- **The ⓘ moved inside the box, and its tooltip stays on screen.** Beside the
  box the marker took 18 px of the field's width and cut `500 um` to `500 u`;
  the tip itself was anchored `right: 0` and ran off the LEFT edge of the window
  on every field in the solver, measured at x = −132.
- **`4k7` now parses.** RKM notation — the prefix standing in for the decimal
  point — is how values are printed on parts and in schematic Value fields, so
  `4k7`, `4R7`, `1M5` and `2G4` all read correctly. Enabled for impedance and
  frequency only: a length is based on mm, so `1m5` there would mean 1.5 metres
  in a box expecting a fraction of one.
- **Rounding could break its own rule.** 999 999 999 Hz sits below 1 GHz, so it
  was printed in MHz, rounded to three decimals, and came out as `1000 MHz` —
  four digits before the point, which is the one thing the prefix ladder exists
  to prevent. The prefix is now re-picked AFTER rounding: it reads `1 GHz`.
- **Field solver**: coplanar is a segmented Off/On beside Signal rather than a
  checkbox, target Z, tolerance and design frequency share one row (the property
  panel widened to fit the widest legitimate value, `999.999 kHz` at 121 px,
  three across), the structure
  box lost its redundant `mm` column, and the cross-section view is remembered
  PER PROFILE — it used to reuse the previous profile's zoom and centre, which
  "lock view" then made permanent.
- **Stock's held parts are grouped by component**: 120 project-rows became 46
  part-rows, folded to 15, with the boards and reference designators behind each
  row grouped by project.
- **Library health folds its long lists** to two rows plus a count.
- **Admin**: the display currency is a dropdown of the currencies that actually
  have an exchange rate, and its fields fill their column instead of sitting at
  the browser's default 176 px with the placeholder cut off.

## 2026-09-12 — One way to label a field, and Setup becomes Admin

- **Setup is now Admin, and it is the same width as every other page.** It
  carried a 860px cap and was the only page in the app narrower than the rest,
  so the same card rendered at two sizes depending on how you reached it. The
  name follows what the page is: administration of the DEPLOYMENT, now that
  everything belonging to the signed-in person has moved to Account. `/setup`
  redirects to `/admin`.
- **Four competing form styles became one.** `edit-grid`, `user-form`,
  `cred-form` and the field solver's `fs-field` all existed at once, and their
  labels were mono UPPERCASE 11px in one and sans sentence-case 12px in another
  — so a form looked different depending on the page it was on. The field
  solver's shape won, promoted to a shared `<Field>` / `<FieldRow>` /
  `<FieldSet>` and a `.field` CSS family. Every form in the app now labels the
  same way.
- **The two input sizes stay, and are now written down.** `.text` for a standard
  field, `.row-input` for the compact one inside table rows and toolbars. A
  duplicate `select.sel` style was folded into the shared one.

## 2026-09-12 — Git tokens belong to an account, not to each project

- **One revoked token was hiding behind three good copies.** Every project kept
  its own encrypted git token, so four projects on one GitHub account held four
  independent copies of one secret. Three were live and the fourth had been
  revoked, and nothing in the platform compared them — the only symptom was one
  project failing to fetch with `could not read Username`, which reads like a
  terminal bug rather than a refused credential. Decision 0010.
- **Credentials are now named accounts.** Add a token once on the new **Account**
  page — click your name in the top bar — and pick it by name on any project.
  Rotating it is one edit in one place, and two projects on one account can no
  longer disagree about the secret.
- **A project can still carry its own token** for a one-off repository. When both
  are set the account wins, and the project page says which is in force rather
  than only "stored (encrypted)" — that wording is how the stale copy hid.
- **Check tells you whether a credential still works**, before somebody needs it.
  It runs the same `git ls-remote` a real fetch uses, once per project on that
  account, and stores the verdict with its date. A credential nobody has checked
  reads "not checked", never "ok". The refusal message is translated where it is
  shown: "the remote refused this token (expired, revoked, or no access to this
  repository)".
- **The Account page holds everything that is yours, not the deployment's.**
  Your password, your API tokens (create, revoke, and read the value back), your
  git credentials, and the four boxes that used to sit on Setup — Effective
  URLs, the KiCad plugin install, the `.kicad_httplib` download and the Claude
  Code / MCP settings. Every one of those carries YOUR token, so two people must
  see two different strings; Setup keeps the deployment's shared configuration
  and a pointer here.
- **Existing tokens migrate themselves** on first start. Distinct token values
  become one credential each, named after the host and numbered when one host has
  several accounts; rename them to whatever you recognise.

## 2026-09-12 — The snapshot-archive purge checks before it deletes

- **The purge would have destroyed the only copy of one project's source.**
  Decision 0009 stops storing a `source.tar.gz` per snapshot because the git
  mirror holds the same commits for a quarter of the space, and a startup purge
  removes the ones already stored. That is right for three of the four projects
  on the server. Project 3 had no mirror directory, an empty checkout, and a
  remote the platform holds no credential for, so its 102.9 MiB archive was the
  only copy of that tree — and that snapshot is the project's current one and is
  pinned by a production run.
- **The purge now verifies the premise per archive.** `gitrepo.can_rebuild`
  asks whether the commit is still an object in that project's mirror — the
  directory existing is not enough, because a re-clone of a rewritten remote can
  lose a commit. What cannot be rebuilt is kept and logged by key, and the
  completion marker is withheld, so fetching the missing mirror and restarting
  finishes the job. Dry-run against production: 743.9 MiB deleted, 102.9 MiB
  kept.
- **A missing mirror is no longer invisible.** The Projects page announced it
  only for a project with no snapshot, so one that was ingested and later lost
  its mirror looked healthy. It now shows a red `no mirror` pill either way —
  without the mirror nothing can rebuild that tree, and backing up `DATA_DIR/git`
  does not cover it.
- **A failed checkout no longer leaves an empty directory behind.**
  `materialize` created the destination before extracting into it, so a missing
  mirror left a directory that answers `.exists()` and holds nothing; an audit
  counted one as a checkout on disk. It now names the missing mirror instead of
  dying on its `cwd` with a bare `FileNotFoundError`, and removes a half-made
  checkout.

## 2026-09-12 — One symbol viewer, one footprint viewer, one canvas

- **The review workbench drew symbols and footprints on a white card.** Its
  preview asked for `background: var(--paper, #fff)` and `--paper` is defined
  nowhere in the stylesheet, so the fallback always won — in dark theme and in
  light. kicad-cli renders light strokes on a transparent background, so the
  picture needs a dark ground under it, which the other previews supplied and
  this one did not.
- **Every preview now goes through one component**, `GeometryPreview`. There
  were six near-identical `<img>` shells across the component page, the template
  page, the templates list, the review workbench and the paste box, with four
  different missing/error stories and three different canvas colours. The canvas
  is now a single palette entry, `--kicad-canvas`, and a caller's class carries
  the size only.
- **The 2D/3D footprint switch was written twice** — component page and template
  page — and the copies had drifted on which state they remembered. One
  `FootprintPreview` owns it now.
- **A preview that has nothing to show says what is missing.** The templates
  list used to render an em dash, and the review workbench a broken-image icon;
  both now carry the server's own explanation where it sends one.

## 2026-09-12 — Table columns that cut their own pills

- **Every sign-off and review pill in the component browser was cut in half.**
  The columns were 4% wide each, which is 55 px — a pill is `inline-block`, so
  the column's ellipsis cannot shorten it and the word is simply clipped:
  "NOT S…", "CHECK…", "UNREV…". The widths the browser needs were written down
  once, in `styles.css`, with a comment saying 9% fits "not signed"; when the
  page moved to the shared `DataTable` the numbers were re-typed as 4 and the
  CSS was left behind as dead rules. Restored, with the reasoning now next to
  the numbers.
- **The bulk sign-off checkbox had an ellipsis stuck to it.** A checkbox is
  13 px of replaced content in a 3%-wide column with 12 px of padding either
  side, so it overflowed and `text-overflow: ellipsis` drew a "…" beside every
  one. Action columns now clip instead of ellipsising, and take 6 px of padding.
- **Centred columns now have centred headers.** `SIGN-OFF` and `REVIEW` sat
  left of the pills they name. `DataTable` copies `ctr` onto the header cell.
- **Nine more tables re-measured.** Reviews (lifecycle, used-in), Orders (net
  total, invoiced, status), Devices (MAC, project, last seen — and its widths
  summed to 103%), the project BOM (tier, qty/dev), Stock (written off, paid
  unit, market unit), the production overview (cost/dev, margin, sale) and the
  project orders tab (its widths summed to 93%). Every header now fits its
  column, and the only cells that still truncate are free text — manufacturer
  names, reference designator lists, repository URLs — where the full value is
  on hover.
- **Filtering the browser's review column for "issues" found nothing.** The
  pill prints "issues" for a failed check; the filter text said "checks fail".

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
