---
status: accepted
date: 2026-09-10
decision-makers: Mateusz Kowalik
---

# Update installed KiCad libraries through the Sync button, and leave the Plugin and Content Manager to the plugin

## Context and Problem Statement

The platform reaches a user's KiCad by two channels. The Plugin and Content
Manager (PCM) installs three packages from the personal repository URL: the
base symbols and footprints, the 3D models, and the Sync plugin. The Sync
button in the PCB editor then pulls updates in place, with 3D models as a
per-file delta. Both channels updated the libraries, and they disagreed: the
PCM decides "update available" from its own record, `installed_packages.json`,
which only its dialog writes. A library the Sync button had refreshed still
showed a badge on every start, and Update All re-downloaded the 259 MB models
zip the delta had already delivered. Which channel owns library updates, and
how does the other one stay quiet?

A second, smaller question sat next to it. The HTTP catalog, the part records
KiCad browses live, is cached by KiCad and refreshed on an interval read from
the `.kicad_httplib`. KiCad 10 has no menu action, no IPC command and no plugin
hook that forces a refresh (verified in the 10.0 source, 2026-09-10), so the
interval is the only lever, and it was one hour.

## Decision Drivers

* A published footprint or field change must reach an open KiCad in minutes,
  without a restart.
* A model change must not cost 259 MB per user; the delta exists for that.
* The PCM must keep offering updates of the Sync plugin, because the plugin
  cannot replace its own running files.
* The plugin runs with KiCad's bundled Python and one dependency, certifi. No
  protobuf, so no IPC API calls from the plugin.

## Considered Options

* Keep both channels and tell users which one to press.
* The Sync button owns library updates and writes the PCM's record, pinning
  the two content packages.
* Freeze the content package versions in the repository so the PCM never
  offers a library update.
* Let the Sync plugin update itself as well, so the PCM is never opened again.

## Decision Outcome

Chosen option: "the Sync button owns library updates and writes the PCM's
record", because it is the only option that keeps the PCM truthful and quiet
without taking anything away from it. After a successful sync the plugin
records the library and 3D-model packages at the served version, with the
served package body, and sets `pinned: true`. Pinned is KiCad's own switch for
"updated elsewhere": the package leaves the badge count and Update All, and a
manual Update stays one menu entry away. The plugin's own entry is never
touched. Details in `api/CLAUDE.md`, bullet "The sync plugin writes KiCad's PCM
record", and in `_record_pcm_installed` in
`api/app/services/pcm_plugin/sync.py.tmpl`.

The catalog interval drops from 3600 / 600 to 120 / 120 seconds, both values,
because KiCad 10 sleeps for the larger of the two between full re-fetches. One
refresh is 17 requests and about 44 kB gzip on the wire (16 categories, 439
parts, measured 2026-09-10), so a client costs about 1.3 MB per hour.

### Consequences

* Good, because a library change reaches an open KiCad on the next Sync press
  and a catalog change within two minutes, with no restart.
* Good, because the PCM stops offering a 259 MB download for a tree the delta
  already updated.
* Bad, because KiCad holds the PCM record in memory: a PCM dialog closed later
  in the same session writes the old versions back, and the badge returns
  until the next Sync. The next Sync corrects the record.
* Bad, because the `.kicad_httplib` carries the interval, so every installed
  copy had to be downloaded again once.
* Neutral, because parts already placed on a board or schematic are copies.
  Tools → Update Footprints / Symbols from Library is still a manual step; no
  IPC API command does it.

### Confirmation

After a Sync, `installed_packages.json` in the KiCad settings folder lists
`com.sevensigma.library` and `com.sevensigma.models3d` at the version the
repository serves, with `pinned: true`, and the PCM shows no badge at the next
start. `GET /api/kicad/httplib-file` carries `timeout_categories_seconds` and
`timeout_parts_seconds` of 120. The record function was exercised against a
copy of a real record on 2026-09-10: untouched when nothing is current, pinned
and versioned when current, idempotent, a stale record corrected, a broken file
ignored.

## Pros and Cons of the Options

### Keep both channels and tell users which one to press

* Good, because nothing changes in code.
* Bad, because the PCM badge keeps saying a library is outdated after every
  Sync, and one click on Update All costs 259 MB.

### The Sync button owns library updates and writes the PCM's record

* Good, because the PCM record stays truthful and the pin is a KiCad feature,
  not a trick.
* Good, because the plugin already resolves the KiCad settings folder for the
  library table repair, so the record is found the same way.
* Bad, because the record is read by KiCad once at start-up; the in-session
  view lags until a restart.

### Freeze the content package versions in the repository

* Good, because the PCM never offers a library update again.
* Bad, because a user who never presses Sync falls behind silently, and a
  fresh install reads a version string that no longer describes the content.
* Bad, because PCM behaviour for an unchanged version with a changed sha256
  is not verified.

### Let the Sync plugin update itself

* Good, because the PCM would never be opened again.
* Bad, because replacing the running plugin files from inside the plugin is
  untested, and the PCM's own record of the plugin version would go stale.
* Neutral, because plugin updates are rare; the PCM handles them well.

## More Information

* `CHANGELOG.md`, 2026-09-10, "Sync plugin 1.5.0 owns library updates".
* KiCad 10.0 source, read 2026-09-10: `kicad/pcm/pcm.cpp` (record read in the
  constructor, `GetPackageUpdateVersion`, `RunBackgroundUpdate` skipping pinned
  entries), `kicad/pcm/dialogs/dialog_pcm.cpp` (record written in the
  destructor), `eeschema/sch_io/http_lib/sch_io_http_lib.cpp`
  (`backgroundRefreshWorker`).
* Revisit if KiCad adds an IPC command that reloads libraries or refreshes an
  HTTP library, or if the plugin gains a self-update path.
