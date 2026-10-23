"""The material ledger (decision 0097): items, lots, moves, links, properties,
events and cost aims, in one model for stock, work and units.

Phase 1: a shadow of today's tables, never the truth. `project.rebuild` builds
it again from the pool, the lots, the transformations and the twins;
`state` reads it; `parity` compares the two models. The rules are in
docs/reference/material-ledger.md and the design in
docs/material-ledger/design.md.
"""
