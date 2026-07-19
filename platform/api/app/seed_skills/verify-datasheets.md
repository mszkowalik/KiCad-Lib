# Datasheet verification

You cannot read PDF datasheets, so you cannot verify a component's pinout,
footprint, or pin names against its datasheet — that stays a desktop/manual
task. Do not claim to have checked a part against its datasheet.

What you can do: record the datasheet URL on a component (pass `datasheet_url`
to `propose_new_component`; the platform stores it and can keep a local copy),
and surface an existing datasheet URL from `get_component` when a user wants to
check a part themselves.
