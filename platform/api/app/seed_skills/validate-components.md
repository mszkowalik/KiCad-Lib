# Validation rules (draft so you pass them)

Validation runs on the server against the platform's rule set — you do not run
it. But draft components so they will pass. The rules are per-category; the ones
to respect while building properties:

- **Required properties** — each category requires a set of properties to be
  present and non-empty (e.g. resistors: `Value`, `Power`, `Tolerance`,
  `Footprint`). The reliable way to know which apply is to mirror a sibling in
  the same category with `get_component`.
- **Property patterns** — some values must match a format, for example:
  - `Value` like `5K1`, `100R`, `4M7` (digits + `R`/`K`/`M` multiplier)
  - `Power` like `63mW`, `0.25W`
  - `Tolerance` like `1%`, `0.1%`
- **Footprint reference** — must be `7Sigma:<name>` and must already exist.
- **Template expressions** — every `{Key}` used inside a value (e.g. in
  `ki_description`) must resolve to another property on the same component.

When unsure which properties or patterns a category needs, copy the shape from
an existing component in that category rather than guessing ([[conventions-library]]).
