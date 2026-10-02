---
status: "accepted"
date: 2026-10-03  # accepted 2026-10-03
decision-makers: Mateusz Kowalik
consulted: Claude (design discussion 2026-10-02/03, after the stock count)
---

# A production process is versioned stages over the component pool

## Context and Problem Statement

The platform holds materials as pool quantities and finished units as device
records, and nothing in between. Real production stops at arbitrary points:
the 2026-10-02 count found 63 assembled-but-unprogrammed Aqua PCBs, 6 fully
assembled unprogrammed Aquas and 10 unprogrammed dongles that no record
counted ([stock-count-2026-10.md](../reference/stock-count-2026-10.md)). The
costs of such boards smear onto the units that did finish: Batch 5's 184
produced devices carry the components of 250 boards. CE_Dongle_V3 adds
per-product steps (drill the enclosure, UV-print it) and alternatives (print
or sticker), and the process will change over time.

## Decision Drivers

* A batch built straight through must record NOTHING new (zero ceremony).
* One counting path per thing. A quantity is never also a set of records.
* An identity that is not readable off the object is a guess, and a guess
  written down is indistinguishable from an observation
  ([0032](0032-a-shipment-names-its-devices.md)). No future MAC readouts are
  planned.
* Costs travel with material, and closed books do not move
  ([0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md)).
* Work is judged by the rule it was made under
  ([0021](0021-a-device-is-judged-by-the-rule-it-was-made-under.md)).
* The bench is never blocked by bookkeeping
  ([0037](0037-the-bench-says-what-it-already-knows.md)).

## Considered Options

* Versioned stages over the pool: internal parts, recipes, transformations.
* Serialize WIP as devices with platform-assigned ids.
* Counts in notes only (the status quo plus discipline).
* A full MRP work-order module.

## Decision Outcome

Chosen option: "versioned stages over the pool".

1. **A stage is an internal part.** "Enclosure with holes", "glued
   subassembly", "assembled unprogrammed Aqua" are components in the library
   with no supplier. Stock of unfinished units is a pool quantity of such a
   part — rule 5 of the 2026-09-18 stock model stands. WIP units stay
   anonymous: a platform id with nothing printed on the object would be
   invented identity. (The 2026-10-02 MAC readouts remain count evidence on
   their lots, nothing more.)
2. **A project's PROCESS is a versioned document**: the stage graph, the
   recipes (inputs per unit of output, expected scrap, a `preferred` flag
   where alternatives exist) and exactly ONE programmable form. Published
   versions are immutable; an edit mints a draft; publishing requires a
   comment and a machine check — the graph is a DAG that closes on the
   programmable form, every input exists, no cycles. Batches resolve a
   version at start and record it; every transformation records the version
   and recipe it ran under (0021 generalized). **Stock ignores versions**:
   lots belong to parts, so a process change moves no lot, and a removed
   stage's leftovers stay visible until consumed or written off.
3. **A TRANSFORMATION consumes input lots and deposits an output lot**,
   valued at the inputs drawn (frozen prices) plus conversion costs plus the
   stated scrap. It is entered from the Process tab or a batch page: recipe,
   quantity, scrap, input lots (oldest first by default), dry run first. The
   pool replay (`run_actuals._pool_events`) is EXTENDED with these events,
   never forked — `lots.py` exists as a replayer for exactly this reason. The
   guard of [0040](0040-a-purchase-cannot-be-removed-from-under-its-draws.md)
   extends transitively: inputs cannot be removed from under an output lot
   that anything has drawn.
4. **Conversion costs are invoice positions aimed at a transformation** — a
   fourth destination beside run, pool and excluded, extending
   [0045](0045-a-position-says-where-its-money-goes.md) and
   [0047](0047-the-step-says-what-a-position-is.md). A UV-print service
   invoice lands on the print transformation; sticker rolls are an ordinary
   pooled purchase its transformation draws. Labor stays on the batch unless
   a position is split onto a transformation deliberately.
5. **Alternatives are recipes, not mechanisms.** Interchangeable downstream →
   ONE part, several recipes, provenance at lot level (the lot names its
   transformation, the transformation its inputs). Not interchangeable →
   different parts, picked by the device's BOM variant.
6. **Programming draws automatically, one per `produced` event.** A batch
   pins a LOT of the programmable form (never a part); when several candidate
   lots exist the bench offers a picker and the chosen lot is recorded on the
   draw; with no candidates nothing is shown and nothing drawn — the
   straight-through batch stays silent. The draw is written in the same
   transaction as `mark_produced` and hangs off the produced EVENT, so a
   rebatch moves it with the device
   ([0029](0029-the-batch-on-a-produced-event-is-correctable.md),
   [0043](0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md)).
   Reflash, draft runs, erases, marking and retro-links draw nothing. A
   device whose runs are all fails prompts "scrap one from the lot?". An
   empty lot WARNS and records the device with an uncovered-draw flag on the
   batch — never a block, never a negative draw.
7. **A stage stocktake corrects drift** the way
   [0057](0057-a-device-the-count-cannot-find-is-missing.md) corrects
   devices: count the shelf, dry run, write the delta with evidence.
8. **The Process tab is the map AND the control panel**: the stage graph with
   per-stage stock and value, recipes as actions, transformation history, the
   per-batch arithmetic panel (made = consumed by next stage + left over +
   scrap, anchored on the bench's produced count), and the version selector.

Phases: **1** — internal parts, process versions, transformations, costs,
the bench draw, the tab, and the stock entries for today's spares. **2** —
shortage explosion through recipes for planning, and a "bank the batch" form
that pre-fills transformation entries from leftover counts. **3, maybe
never** — per-device material draws, or labeled WIP identity (print at
banking, scan at the bench) if lot-level trust ever stops being enough.

### Consequences

* Good, because the shelf is countable and valued at any stop point, and the
  components consumed into WIP are visibly gone from the pool.
* Good, because cost attribution is fixed going forward: a banked board's
  value lands on the batch that finishes it, not on the batch that bought it.
* Good, because a process change costs one part and one version, and no
  existing lot or book moves.
* Bad, because the riskiest code extends the single pool replay, and a
  mistake there corrupts every stock figure at once.
* Bad, because which physical pile fed the bench is only as true as pile
  discipline — software records the stated lot and cannot verify it.
* Neutral, because operators gain one duty: entering what was made when they
  stop. The straight-through batch gains nothing to do.

### Confirmation

Tests over the pool replay (a transformation's output value equals inputs
plus costs; the 0040 guard holds transitively; shortage checks see WIP
consumption), over the bench draw (one per produced event, idempotent on
reflash, follows a rebatch, uncovered when the lot is empty), and over the
arithmetic panel. The first real use is banking the 2026-10-02 spares: 63 +
6 Aqua stages and 10 dongle boards, entered through the tab, matching the
count evidence.

## Pros and Cons of the Options

### Versioned stages over the pool

* Good, because it reuses the pool, lots, destinations and version patterns
  the platform already trusts.
* Bad, because it adds a second place (after devices) where an operator's
  entry is the truth.

### Serialize WIP as devices with platform ids

* Good, because the bench would decrement spares automatically by identity.
* Bad, because an id nobody can read off the object is a pretend serial —
  the thing 0032 removed — and stages without MACs (an enclosure) would
  still need the pool mechanism, leaving two WIP systems.

### Counts in notes only

* Good, because it costs nothing now.
* Bad, because the 2026-10-02 count IS the result: uncounted stages, smeared
  costs, and a readout session to rediscover the shelf.

### A full MRP work-order module

* Good, because it is the textbook answer.
* Bad, because work orders per stage impose ceremony on the straight-through
  batch, which is the common case here.

## More Information

The found historical WIP enters the pool at ZERO value, each lot carrying a
note naming the closed batch whose books still hold its component cost
(user decision, 2026-10-03). Batch 5's 184 produced units keep carrying the
63 banked boards' cost — 0044 forbids moving closed books, and nobody wants
a correction document for a product that is closing.

Supersedes nothing. The design discussion is summarized in
[stock-count-2026-10.md](../reference/stock-count-2026-10.md) while it is a
working file.
