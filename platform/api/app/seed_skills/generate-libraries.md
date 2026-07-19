# Generating libraries

There is no manual generation step, and you cannot run one. When a proposal is
approved, the affected KiCad symbol library and the file mirror are regenerated
automatically from the database. You never build anything, and you must not tell
the user to run a build or pipeline.

If a user asks how to regenerate or rebuild the library, the answer is: approve
the pending proposal (or in-place edit) — regeneration happens on approval.
