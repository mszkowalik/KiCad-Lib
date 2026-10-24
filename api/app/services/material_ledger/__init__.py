"""The material ledger (decisions 0097, 0098): items, lots, events, moves and
their lots, event lots, cost aims, links and properties — the one model for
stock, work and units.

`core` holds the writing helpers every writer uses; `cutover` is the one-time
move of the old tables into the ledger. The readers live with their topics:
`run_actuals` (the pool), `lots` (the lot ledger), `twins` (units and prices).
Rules: docs/reference/material-ledger.md.
"""
