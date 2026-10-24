---
status: "accepted"
date: 2026-10-15  # accepted 2026-10-15
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-15)
---

# Give an unserialised product's boards placeholder units that can ship

## Context and Problem Statement

The DotConnect boards (DC_GPS, DC_LIDAR, DC_BMS, DC_Temp) carry no MAC and no
serial, and the flasher never sees them. The platform counts the shelf, the
unit cost and every delivery from device records
([0007](0007-built-means-finished-and-passed.md),
[0031](0031-a-batch-that-records-its-devices-has-no-anonymous-units.md),
[0043](0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md)). A batch
with no device records is built 0. [0039](0039-a-prototype-is-counted-without-being-named.md)
allows placeholder units only for prototypes, and those cannot ship.

On 2026-10-13 the DC batches were made one per sales invoice. So the shelf
shows no DC board, although 8 assembled DC_GPS boards are in stock, and the
sales sit in run columns that nothing reads since 0043. The user asked on
2026-10-15 for the board stock to be correct.

## Decision Drivers

* The shelf shows the boards that exist, by the same code path as every
  other product.
* A sale is an order with a delivery, so the order carries the revenue (0043).
* No unit gets an identity that nobody observed.
* No code change: a one-time script, as for the 0039 placeholders, because
  no API creates a device unit.

## Considered Options

* Placeholder units that can ship, one per assembled board, in batches that
  are assemblies.
* Parts and costs only: the boards stay off the shelf.
* One batch per sale, with a unit per board sold.
* A new API endpoint that creates the units.

## Decision Outcome

Chosen option: "placeholder units that can ship", because it is the only
option that puts the boards on the shelf with no code change.

1. **A batch of an unserialised product is one ASSEMBLY**: one JLCPCB
   assembly order, or one hand build. Its `qty` is the boards assembled. A
   batch that was only a sale merges into the assembly that made its boards
   and is deleted: DC_GPS Batch 6, DC_LIDAR Batch 5 and DC_BMS Batch 3.
2. **Each assembled board gets one unit**: `mac` NULL, `serial` empty, a
   `produced` event at the batch date (0039 items 1, 2 and 4). Its
   `condition` is `ok`, so it can ship. This is where it differs from 0039
   item 3. The note on each unit says it is a placeholder for an
   unserialised board.
3. **The units of one batch are interchangeable.** A shipment names them by
   id, lowest first, from the assembly made for that sale: the JLCPCB order
   placed for its proforma, or the hand build before its invoice. Oldest batch
   first would ship the unsold 2023 V1 DC_BMS boards on a 2025 V2 sale. This is
   the one case where a shipment names units that have no identity of their
   own (0032). It is honest because no observation could tell two units of one
   batch apart.
4. **A sale is an order of customer DotConnect**, with its proforma and VAT
   invoice, and one shipment dated on the VAT invoice. An order with no VAT
   invoice yet has no shipment.
5. **A part fitted by hand is a typed draw on the batch whose units got it**,
   on the day it was fitted: ZED-F9P, NID65-12, enclosures and plugs. A part
   fitted later to units already in stock is drawn then, on the batch those
   units came from.
6. **The units come from a one-time script** run on the server, as
   `scripts/fill-v3-placeholders-2026-10-03.py` did. It refuses a batch that
   already has units.

### Consequences

* Good, because the shelf shows DC_GPS 8, DC_LIDAR 5, DC_BMS 15 and DC_Temp 7
  units, counted by the same code as every other product.
* Good, because each DotConnect sale is an order with its invoices, and its
  delivered quantity is a count of named units.
* Bad, because a unit's cost is its batch's average. A unit sold with two
  ZED-F9P and a unit still waiting for them cost the same until the later
  draw lands.
* Bad, because the counts outside DC_GPS are derived from assemblies minus
  sales, not counted. DC_BMS Batch 1b (10 boards, 2023) may have left with no
  invoice. A stock count marks a unit that is not found as missing
  ([0057](0057-a-device-the-count-cannot-find-is-missing.md)).

### Confirmation

`GET /api/finished-stock` shows the counts above. Each DotConnect order
shows as delivered the units its VAT invoice billed. The invoice register
keeps `gap_usd` at 0.

## Pros and Cons of the Options

### Placeholder units that can ship

* Good, because it uses the existing counting, delivery and costing paths.
* Bad, because it amends 0039 item 3 for unserialised products.

### Parts and costs only

* Good, because it changes no rule.
* Bad, because the shelf stays wrong. The user rejected it on 2026-10-15.

### One batch per sale

* Bad, because the boards not yet sold belong to no sale, so they have no
  batch.

### A new API endpoint

* Good, because a person could add units from a screen.
* Bad, because it needs a code change and a deploy for one data load of
  about 500 units (DC_GPS 30, DC_LIDAR 61, DC_BMS 42, DC_Temp 369).

## More Information

The working rules are in `docs/reference/production-economics.md`, section
"The DotConnect boards". Revisit this record if an unserialised product
gets a process ([0059](0059-every-unit-has-a-twin-and-programming-names-it.md)):
its twins would then be the units.
