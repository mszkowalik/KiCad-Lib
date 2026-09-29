---
status: "accepted"
date: 2026-09-29
decision-makers: Mateusz Kowalik
---

# Link a component to its suppliers in a register, and price it by a dated supplier order

## Context and Problem Statement

A component named its sources in the free-text properties `Supplier N` and
`Supplier Part Number N`. The pattern comes from Altium, where a BOM can only
read what is on the part. On 2026-09-29, 423 of 456 components carried them:
LCSC 400, Mouser 19, Phoenix Contact 17, TME 5, CODICO 1. Nothing read them.
Prices were a separate table keyed by a free-text `source`, and only JLCPCB and
LCSC prices were refreshed. A hand-entered price named no supplier. The
Takachi enclosure had "Manual" prices from LC Elektronik, and nothing linked
the two.

Price resolution was one hard-coded rule: a JLCPCB price hides the LCSC price,
and every hand-entered price mixes in by quantity break. That cannot express
"this module is cheaper at DigiKey", and it has no place for TME, Mouser or
DigiKey prices.

The user asked for the other distributors, a library-wide supplier order with a
per-component override, and a replacement for `Supplier N`. Prices reach money:
a production run's planned side (`project_bom.run_effective`) prices every part
that was not yet bought from invoices by the run date. The change must not move
a past run, and must not cost any component its sign-off or verification.

## Decision Drivers

* A past run's planned cost must not change when somebody reorders suppliers
  today.
* No component may lose its sign-off or its review record to the migration.
* A supplier, its part number and its price are one fact. They must live in
  one place.
* The TME, Mouser and DigiKey connections (phase 2) need somewhere to write.

## Considered Options

* A supplier register, component-to-supplier links, and prices that belong to
  a link, resolved by a supplier order that is recorded with the price history.
* Keep `Supplier N` and read `Supplier 1` as the preferred supplier.
* One aggregator (Nexar, formerly the Octopart API) in place of per-distributor
  connections.
* A single preferred supplier per component, in place of an order.
* Let stock decide: skip a supplier that cannot cover the quantity.

## Decision Outcome

Chosen option: **the register, the links and the dated order**, because it is
the only option that keeps past runs fixed and keeps every verification.

1. **The supplier register.** One row per supplier: name, website, notes, and
   a connector (`jlcpcb`, `lcsc`, or none). An admin adds, edits and orders
   suppliers. Everybody can read the register. **A name cannot change**, because
   price rows and price history refer to a supplier by name.
2. **The library order is the register order.** It starts as JLCPCB, LCSC, TME,
   Mouser, DigiKey, then the suppliers that have no connection.
3. **A component links to its suppliers.** A link holds the supplier's part
   number, a product URL, a note and an optional position in the component's
   own order. Links have no versions. Any signed-in user edits them, and the
   activity log records who did it.
4. **One source gives the whole ladder.** The platform takes the sources in
   this order and uses the first one that has a price:
   1. A hand-entered price that names no supplier. The legacy "Manual" rows
      are the only ones. A new price must name a supplier.
   2. The component's own order.
   3. The library order.

   Two sources never mix by quantity break any more.
5. **A hand-entered price goes to the top.** When a link gets hand-entered
   prices for the first time, it moves to the top of the component's order.
   The user can move it down again.
6. **The order is recorded with the price history.** Each price-history
   snapshot stores the position of every source in it. A run is priced with
   the snapshot at its date, so it uses the order that was in effect on that
   date. A snapshot recorded before this change has no positions, and it
   resolves with the old rule. **This is what keeps every past run fixed.** A
   change to the library order writes a new snapshot for each priced component.
7. **`Supplier N` and `Supplier Part Number N` leave the component record.**
   A startup migration copies them into links. It then publishes a new version
   of each component without them. The sign-off and review carry treat these
   keys as non-material: they record where a part is bought, not which part it
   is. The migration therefore costs no verification. Afterwards the component
   editor and the agent refuse these keys, as they refuse price keys.
   **`LCSC Part` stays a property.** The KiCad BOM export and BOM matching read
   it, and the JLCPCB and LCSC links follow it.
8. **Stock does not choose the supplier** (the user's choice, 2026-09-29). The
   platform keeps no stock history, so a stock-aware rule could not price a past
   run. A BOM still shows the stock of the supplier it used.

Phase 2 (the TME, Mouser and DigiKey connections, their credentials, and stock
per link) gets its own record.

### Consequences

* Good, because a supplier, its part number and its prices are one row and its
  children, in one place.
* Good, because the migration was measured against a copy of production before
  it shipped. Of 556 lines in 20 runs, 412 are priced from invoices and cannot
  move. The other 127 resolve the same under the new rule, because no part has
  both a hand-entered price and a JLCPCB or LCSC price.
* Good, because the order carries a date, so a reorder or an override today
  cannot reprice a run that is already closed.
* Bad, because KiCad symbols no longer carry `Supplier` fields. A schematic
  BOM that read them has to use the platform BOM.
* Bad, because a change to the library order writes about 400 price-history
  rows. The change is rare and the rows are small.
* Bad, because a supplier cannot be renamed. A wrong name must be retired and
  a new supplier created.
* Neutral, because a wrong supplier part number is no longer part of the
  sign-off. The invoice and the receipt catch a wrong delivery, and the MPN and
  `LCSC Part`, which do identify the part, stay material.

### Confirmation

* `scripts/price-snapshot.py` captures every run's planned lines, every project
  BOM at four volumes, each component's resolved price at five quantities, and
  each component's sign-off, review and machine-tier state. It runs before and
  after the migration on the same database copy. Unit prices must not change.
  Only the source labels that the migration re-attributes may change.
* `api/tests/costs/test_supplier_order.py` tests the resolution rule, the
  legacy fallback and the carry.
* `api/tests/auth/test_role_gates.py` lists the admin routes of the register.

## Pros and Cons of the Options

### Keep `Supplier N` and read `Supplier 1` as the preferred supplier

* Good, because it needs no new table.
* Bad, because a property is versioned. Each override would publish a new
  component version, and a material edit costs the verification.
* Bad, because the library rule put `Supplier 1 = LCSC` on 400 parts. LCSC
  would then come before JLCPCB on almost every part.
* Bad, because it has no place for a price.

### One aggregator (Nexar)

* Good, because one key covers every distributor.
* Bad, because the free plan is 100 matched parts for the life of the account.
  The paid plans (2,000 and 15,000 parts a month) publish no price.
* Bad, because it returns public list prices, not the prices of our own TME and
  DigiKey accounts.

### A single preferred supplier per component

* Good, because it is one field.
* Bad, because the user wants a hand-entered price at the top of an order, with
  the rest of the order behind it as the fallback.

### Let stock decide

* Good, because a live BOM would show a price that can be bought.
* Bad, because stock has no history, so the rule cannot price a past run. The
  same component would resolve one way on a BOM and another way on a run.

## More Information

* The design: [docs/reference/suppliers.md](../reference/suppliers.md).
* Pricing a run from invoices first: the `_component_data` docstring in
  `api/app/services/project_bom.py` (user decision 2026-07-28).
* The carry rule this extends: [0019](0019-a-classification-carries-the-first-time-it-is-set.md).
* Revisit this when a supplier needs more than one part number for one
  component, for example cut tape and reel at DigiKey. A link is unique per
  component and supplier today.
