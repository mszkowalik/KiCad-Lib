---
status: "accepted"
date: 2026-09-16
decision-makers: Mateusz Kowalik
---

# Judge a device by the rule its batch carried, and pin that rule on every run

## Context and Problem Statement

"Is this device programmed?" was answered by one line: the newest programming
run passed. The history a device carries is richer than that — a config run, a
test sweep, a marking job, an erase — and the answer differs per product: an
Aqua must pass its test sweep, a Dongle has no test in its flow at all.

The first attempt put a boolean on the deployment (`Deployment.active`): the
project's test is required, or it is not. Measured against the real history,
that switch would have re-judged the fleet the moment it moved. Of 989 Aqua
units with a passing config run, only 434 have a passing test after it; 401
have no test run at all, because their batches predate the sweep. Turning the
flag on marks 555 finished devices unverified; turning it off hides 76 that
genuinely failed a test.

## Decision Drivers

* A device's verdict must not change because somebody edited a setting today.
* "Which batches required a test?" is a question with a real answer, and
  batches differ: one was tested, the next was not.
* A test that was RUN and failed is knowledge about that unit, whatever any
  setting says.
* Marking a case, and erasing a device, are also history and must not be
  confused with evidence.

## Considered Options

* Requirement on the batch, copied onto every programming run
* Requirement declared by the config deployment VERSION
* Project-wide flag on the test deployment, plus an `active_since` timestamp

## Decision Outcome

Chosen option: "Requirement on the batch, copied onto every programming run",
because the batch is the unit a person actually decides about, and the copy on
the run makes the verdict immutable. `ProductionRun.requires_test` holds the
decision; `ProgrammingRun.test_required` is written from it when the run is
created, beside `firmware_fingerprint` and the version id that are pinned for
the same reason. A bench trial with no batch copies the project's current
default. `Deployment.active` survives, demoted to exactly that: the default
ticked on a NEW batch.

The verdict (`services/flasher/checks.verdict`) reads, in order:

1. The newest CONFIG run (`kind="flash"`) passed.
2. If any TEST run started after it, the newest of those passed — required or
   not.
3. If no test ran, the config run's own `test_required` decides whether that is
   acceptable.
4. No ERASE started after whichever of those is newer.

A MARKING run is never consulted.

### Consequences

* Good, because every device already made keeps the verdict it earned: legacy
  runs carry `test_required = false`, so the 401 never-tested Aquas stay
  verified with no date arithmetic and no backfill.
* Good, because a failed test always counts. The 76 units whose newest test
  failed read "not programmed" even though their batches required nothing.
* Good, because the question "was a test required for this batch" is a column,
  not an inference.
* Bad, because the requirement is now stored in three places (deployment
  default → batch → run). Reading one of them and calling it the rule is the
  mistake this record exists to prevent: the RUN is the authority for a device
  that exists, the BATCH for work still to be done.
* Bad, because changing a batch mid-production means its units are judged by
  two different rules. That is the honest record of what happened, but it will
  surprise somebody.

### Confirmation

`checks.verdict` was exercised against the live database, on synthetic devices
covering every branch (config fail, test fail, test pass, erase after a pass,
re-flash after a pass, marking job) and on real fleet rows from each bucket.
Counts after the change: Aqua 914 of 990 read programmed, Dongle_V2 4430 of
4437.

## Pros and Cons of the Options

### Requirement on the batch, copied onto every programming run

* Good, because the granularity matches how work is actually planned.
* Good, because the copy on the run makes history immutable by construction.
* Bad, because it is two columns and a UI control rather than one flag.

### Requirement declared by the config deployment VERSION

* Good, because a run already pins its version, so the requirement would be
  historical for free.
* Good, because the requirement would travel with the procedure it belongs to.
* Bad, because two batches running the same version could not differ, which is
  the case that prompted the change.

### Project-wide flag on the test deployment, plus `active_since`

* Good, because it is one column and no new UI.
* Bad, because the rule stays project-wide: "batch 9 was tested, batch 10 was
  not" is unsayable.
* Bad, because moving the date re-judges devices in bulk, which is the failure
  mode being fixed.

## More Information

* [0007](0007-built-means-finished-and-passed.md) counts a batch by the devices
  that passed; this record decides what "passed" means for one device.
* [0003](0003-orders-shipments-and-device-history.md) §5 makes the first PASS
  of a batch run the device's `produced` event. That event still fires on the
  config run's pass, NOT on this verdict — a unit enters stock when it is
  programmed and leaves it on a shipment, while the verdict answers a different
  question and may change later.
* Revisit if a product ever needs two tests, or a test that is required only
  for part of a batch.
