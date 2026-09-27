---
status: "accepted"
date: 2026-09-27
decision-makers: Mateusz Kowalik
---

# Open a shipment before it is sent, and record every device packed into it

## Context and Problem Statement

A shipment could be recorded only in one step, after the box had left: the
order page's Ship card takes every serial at once and writes the `shipped`
events at once ([0032](0032-a-shipment-names-its-devices.md)). Packing a carton
of 175 devices therefore happened outside the platform: somebody scanned into a
text file and pasted the file afterwards.

The user wants the platform to be the packing station: open a shipment, scan
devices into it as they go into the carton, check each one, and mark the box as
sent when it is closed. The scanner is a Zebra in keyboard mode that types the
code and CR LF, faster than the server can resolve serials.

## Decision Drivers

* A shipment still names its devices and nothing else
  ([0032](0032-a-shipment-names-its-devices.md),
  [0049](0049-a-delivery-names-its-devices-and-nothing-else.md)).
* A device in a box being packed must not be taken by another shipment.
* Nothing is shipped, and no order figure moves, until the box is sent.

## Considered Options

Three questions, each answered by the user on 2026-09-27.

* **Which order a shipment belongs to.** (a) One order, chosen when the
  shipment is opened. (b) A shipment is a physical box, and each device names
  its own order line.
* **How a packed device is held.** (a) A reservation stored beside the device,
  with no history until the box is sent. (b) An `allocated` event on the device,
  and an `unallocated` event when it is taken out again.
* **Where the scanned-but-not-packed list lives.** (a) In the browser, per
  shipment. (b) On the server.

## Decision Outcome

Chosen: one order per shipment, `allocated` / `unallocated` events, and the
scan list in the browser.

1. **`shipments.status` is `open`, `sent` or `cancelled`.** Every row that
   existed before was a delivery that had left, so the column defaults to
   `sent`. The one-step Ship card still writes a `sent` shipment directly.
2. **Packing writes `allocated`, naming the shipment and the order line.**
   The line is the order's only line for the device's product; when two lines
   carry the same product the caller must name one. A device is in a box
   exactly while its newest event is that `allocated`, so the box's contents are
   read from the device log and need no table of their own.
3. **Taking a device out writes `unallocated`, and the device is `in_stock`
   again.** The packing mistakes stay in the device's history. That is the
   trade the user chose over a history-free reservation.
4. **Sending writes the `shipped` events** through the same code as the
   one-step path, dated by the "Sent on" field, and the order's status follows.
   An empty box cannot be sent.
5. **A box is cancelled, not deleted, once anything was packed into it.** Its
   devices get `unallocated`, and the header stays, marked `cancelled`, because
   their history names it. A box nothing was ever packed into can be deleted.
6. **A device packed in one open box is refused by every other shipment**,
   including the one-step Ship card. `allocated` alone used to be accepted
   there.
7. **The scanned list lives in `localStorage`, keyed by shipment.** It survives
   a reload on the same PC. Its check results are not stored; they are asked
   again on load, because stock may have moved.
8. **A sent shipment stays a permanent record.** Its header is not edited, and
   a delivery recorded in error is still taken back by
   [0028](0028-a-shipment-recorded-in-error-is-reversed-not-deleted.md).

### Consequences

* Good, because the carton and the platform are packed together, and a
  refused device (faulty, prototype, unknown, already in another box) is found
  while it is still in the hand.
* Good, because a packed device is out of "available" stock at once, so two
  boxes cannot claim it.
* Good, because the contents of an open box need no new table.
* Bad, because a device's history now carries every packing mistake as an
  `allocated` / `unallocated` pair.
* Bad, because a scan on one PC is invisible on another until it is packed.
* Neutral, because a box for two orders is still two shipments, as the 25
  devices of 2026-09-25 were.

### Confirmation

`api/tests/orders/test_open_shipments.py`, 7 tests: packing reserves and sending
ships; unpacking writes history and returns the device to stock; the scan check
names every refusal; a pack is all or nothing; a packed device cannot leave on
another shipment; cancelling releases every device and keeps the header; an
empty box cannot be sent. A headless browser run on 2026-09-27 against the dev
stack scanned six codes with CR LF at keyboard speed, packed four, took one
back, reloaded, and sent three.

## Pros and Cons of the Options

### A box that holds devices for several orders

* Good, because it matches a carton that holds two orders.
* Bad, because the order moves from the shipment header to every device, and
  every order-side figure and page reads a shipment through its order.

### A reservation with no device history

* Good, because a device's history shows only what left.
* Bad, because it needs a table of its own for the open contents, and the user
  preferred to see the packing in the device log.

### The scan list on the server

* Good, because a second PC sees the same list.
* Bad, because it needs another table and more endpoints for a list that exists
  only while one person scans.

## More Information

* [0003](0003-orders-shipments-and-device-history.md) — the event log this
  extends with `unallocated`.
* Revisit the order question if a carton for two orders becomes common.
