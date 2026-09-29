# Suppliers — the register, the links, and the order that prices a part

The decision, and the options it rejected, are in
[0055](../decisions/0055-a-component-links-to-suppliers-in-a-register.md). The
code is `api/app/services/suppliers.py` and the resolution in
`api/app/services/ladder.py`. The UI is Admin → Suppliers and the component
page's "Suppliers & pricing" card.

## The three pieces

| Table | Holds | Who writes it |
|---|---|---|
| `suppliers` | One row per supplier. Its `position` order is the LIBRARY order. `connector` is `jlcpcb`, `lcsc`, or empty. | An admin. The four write routes are in `api/tests/auth/test_role_gates.py`. Reading is open. |
| `component_suppliers` | A component's link to a supplier: part number, product URL, note, and an optional `position` in the component's OWN order. Not versioned. | Any signed-in user, and the agent's `link_supplier`. |
| `component_price_points` | Price breaks. `source` is a supplier NAME. | The refresher for JLCPCB and LCSC. A person for every other supplier. |

A supplier's name never changes. Every price row and every price-history
snapshot refers to it by name, so a rename would detach them.

## Which source prices a part

`ladder.effective_points` is the one place that decides. It takes the source
with the lowest rank, and that source gives the WHOLE ladder. Two sources never
mix by quantity break.

`suppliers.ranks` gives the ranks, lowest first:

1. A price that names no supplier (`LEGACY_RANK`). Only legacy rows have one:
   "Manual", and "Pool average (landed)". A new price must name a supplier.
2. The component's own order: links with a `position`.
3. The library order: every other supplier, in register order.

Stock does not take part (user decision 2026-09-29). A BOM line still shows the
stock pools, and `stock_ok` still says whether they cover the order.

The first time a link gets hand-entered prices, it moves to the top of the
component's own order (`suppliers.move_to_top`). The user can move it down
again. Later price edits do not move it.

## The order is dated — this is what keeps a run fixed

A production run prices every part it did not yet buy from invoices through
`ladder.history_points_at`, at the run's date. So the order must be the one in
effect on that date, not today's.

- `ladder._effective_state` writes a dense `rank` into every point of a
  price-history snapshot.
- A snapshot with no `rank` was written before the register. It resolves with
  the old rule: a JLCPCB ladder hides the LCSC one, and every other source
  mixes in by quantity break. Do not "upgrade" old snapshots.
- **Every function that changes an order must record price history in the
  same transaction.** `set_component_order`, `set_link_prices`,
  `attribute_legacy` and `remove_link` do. `set_library_order` records a
  snapshot for every priced component, about 400 rows.

A change to any of this must be proved against a copy of production with
`scripts/price-snapshot.py`. It captures every run's planned lines, every
project BOM at four volumes, each component's resolved price, and each
component's sign-off, review and machine-tier state. Capture before, change,
capture after, diff. Run it with the background refreshes off, or the diff
reports the market.

## JLCPCB and LCSC follow `LCSC Part`

`LCSC Part` stays a component property. The KiCad BOM export and BOM matching
read it (`project_ops.BOM_FIELDS`, `project_ingest`). The JLCPCB and LCSC links
follow it: `ladder.refresh_component` calls `suppliers.ensure_lcsc_links`.

- Their prices cannot be typed, and their links cannot be removed on the page.
  Edit the property instead.
- A component with JLCPCB or LCSC prices and no link still resolves correctly.
  A missing link ranks in library order.

## `Supplier N` is gone

`Supplier N` and `Supplier Part Number N` were properties. The startup migration
(`suppliers.run_startup_migration`) moves them into links and publishes each
component again without them. After it:

- The component editor and the agent refuse the keys, as they refuse price keys.
- `generator.apply_properties` never emits them to KiCad.
- `signoff._is_non_material` treats them as non-material. They say where a
  part is bought, not which part it is. This is what lets the migration keep
  every sign-off and review record.
- The migration copies the old version's datasheet pins onto the new version.
  A plain publish pins today's revision, and a datasheet revised since would
  refuse the review carry.
- A standing exception pinned to `$property_sha` is re-pinned
  (`suppliers._repin_exceptions`). That digest covers EVERY property, so
  removing the keys changes it. The re-pin runs BEFORE the publish, because the
  publish warms the conformance cache.

The base symbols `HSBB6115`, `Q_NMOS_GSD` and `Q_PMOS_GSD` still declare empty
`Supplier` fields in `7Sigma_Base.kicad_sym`. The component libraries drop
them; the base library does not, until those symbols are edited.

## Not done yet

Phase 2 connects TME, Mouser and DigiKey, stores their credentials encrypted
and admin-only, and moves stock onto each link. It gets its own decision record.
A link is unique per component and supplier. A second part number at one
supplier (cut tape and reel) needs a change to that.
