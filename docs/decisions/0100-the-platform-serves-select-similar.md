---
status: accepted
date: 2026-10-24
decision-makers: Mateusz Kowalik
---

# Serve Select Similar from the platform's PCM repository, as a fourth package (amends the code location in 0096)

## Context and Problem Statement

Decision [0096](0096-select-similar-is-an-ipc-plugin-with-a-floating-panel.md)
built Select Similar as an IPC plugin and kept its code in
`clients/kicad-select-similar`. A user installed it by building a zip and
choosing **Install from File** in the Plugin and Content Manager (PCM). The
user asked to install it from the PCM like the library. Every user already
has one personal repository URL that installs the library, the 3D models and
the sync plugin. How does Select Similar reach that repository?

## Decision Drivers

* One URL per user is the install path users already know. A second path is a
  second thing to explain.
* `clients/` is not in the api image. The platform can only serve files the
  image carries.
* Adding a package must not re-version the library or the 260 MB models
  package. PCM would then offer every user an update of unchanged content
  ([pcm-packaging.md](../reference/pcm-packaging.md)).
* The sync plugin writes the PCM's own record of installed packages and sweeps
  every `com_sevensigma*` install folder. A new package must not upset either.

## Considered Options

* A fourth package in the existing repository.
* A second repository URL for tools.
* Keep "Install from File" with a zip built by hand.
* Add a button to the sync plugin package.

## Decision Outcome

Chosen option: "a fourth package in the existing repository", because it uses
the URL every user already has, and the PCM then delivers updates.

1. The source moves to `api/app/services/select_similar_plugin/`, beside the
   sync plugin's `pcm_plugin/`, and `pyproject.toml` lists it in
   `package-data`.
2. `services/pcm.py` zips every top-level file of that folder into
   `plugins/`, except `README.md`, `CLAUDE.md` and `icon-pcm.png` (the package
   icon). The local zip builder, `build_package.py`, is deleted, so one
   packager remains.
3. The package is `com.sevensigma.select-similar`, type `plugin`,
   `kicad_version` 10.0, `runtime` `ipc`. With `runtime` `ipc`, the PCM offers
   to switch the KiCad API on during the install when it is off.
4. Its version is the manual `SIMILAR_VERSION`, under the same rule as the sync
   plugin's `PLUGIN_VERSION`.
5. It carries no token, so it is one shared zip. The download URL carries the
   token, as every package URL does.
6. The hash of its files enters the build tag. `BUILDER_REV` stays at 13, so
   the three old packages keep their versions and zips.

### Consequences

* Good, because a user installs and updates Select Similar from the dialog
  they already use.
* Good, because the sync plugin leaves it alone. It records and pins
  `type == "library"` packages only, and its stray sweep judges empty folders
  and library files only (`sync.py.tmpl`, read 2026-10-24).
* Bad, because every top-level file in the plugin folder now reaches every
  user who updates. The folder's `CLAUDE.md` says so.
* Bad, because the plugin's own tests (`select_similar_plugin/tests`) are
  outside `api/tests` and need kicad-python, so the api suite does not run
  them. `api/tests/pcm` covers the packaging.

### Confirmation

`api/tests/pcm/test_select_similar_package.py` checks the zip contents, the
package entry, the personal URL, an index from before the package, and that a
Select Similar change keeps the content versions. On the dev stack, the
packages document validated against KiCad's `pcm.v1` schema. The repository,
packages and zip chain verified its hashes over HTTP. A sandbox KiCad 10.0.5
loaded the served zip from `3rdparty/plugins/com_sevensigma_select-similar`
and built the plugin's environment.

## Pros and Cons of the Options

### A fourth package in the existing repository

* Good, because there is no new URL and no new credential path.
* Neutral, because the PCM lists the plugin to every user. Installing it stays
  optional.

### A second repository URL for tools

* Good, because the library repository stays library only.
* Bad, because each user then pastes and keeps a second personal URL.

### Keep "Install from File"

* Good, because it needs no platform change.
* Bad, because there are no updates: each user rebuilds and reinstalls by hand.

### Add a button to the sync plugin package

* Good, because there is one plugin to install.
* Bad, because that package is personalised per token and versioned for the
  library. A Select Similar fix would re-issue every user's sync plugin, and
  the two would share a release cycle for no reason.

## More Information

* Decision 0096 still holds in full, except for the code location in its
  context section.
* Decision [0006](0006-sync-button-owns-library-updates.md) still holds: the
  Sync button owns library updates, and the PCM owns plugin updates.
