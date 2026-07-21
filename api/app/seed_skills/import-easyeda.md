# Importing from LCSC / EasyEDA

**What you can do:** look up part metadata from LCSC with `lcsc_lookup`
(manufacturer, MPN, description, datasheet URL, package) and use it to draft a
component that references an existing base symbol and 7Sigma footprint.

**What you cannot do:** download or create symbols, footprints, or 3D models.
Automated symbol/footprint import is not available to you. If a part needs a
footprint or base symbol that is not already in the library, say so and stop —
ask the user to add it. Do not invent names; the proposal tools reject
references to footprints or base symbols that do not exist ([[conventions-footprints]],
[[conventions-symbols]]).
