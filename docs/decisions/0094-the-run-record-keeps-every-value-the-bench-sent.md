---
status: "accepted"
date: 2026-10-18
decision-makers: Mateusz Kowalik
---

# Keep every value the bench sent in the run record, secrets included

## Context and Problem Statement

A programming run stores three records of what a unit got: every line sent and
received (`programming_logs`), the values the run used (`params_snapshot`), and
what it captured (`results`). Until 2026-10-18 the engine hid secrets in two of
them: the SIM PIN in the sent line and in the step response, and every
parameter whose key matches `password|pin|salt|secret|token` in the snapshot
(`•••`). The WiFi password and both MQTT passwords still reached the log in
clear, in the sent `Backlog` line and in the device's `CMD:` echo (run 8867).
Item 2 of [ce-dongle-v3-bench-gaps.md](../ce-dongle-v3-bench-gaps.md) proposed
to mask those too.

## Decision Drivers

* The run record is the proof of what a unit was programmed with. A value that
  is masked cannot be checked against the device, a customer report or a later
  parameter edit.
* The parameter set holds the same values, encrypted, and any signed-in user
  can already read them on the Parameters page.
* Decision [0089](0089-every-change-is-recorded-and-can-be-undone.md) promises
  that the change history never stores a secret.

## Considered Options

* Keep every value in clear in the log, the snapshot and the results
* Mask every secret value in every stored line (the item 2 proposal)
* Keep the masking as it was: the PIN and the snapshot keys only

## Decision Outcome

Chosen option: "keep every value in clear", by user decision on 2026-10-18,
because the run record exists to prove what was sent.

1. **`RunEngine` masks nothing.** The sent line, the received line, the step
   response, `params_snapshot` and `results` hold the values the run used,
   the SIM PIN included.
2. **The change history still never copies a secret.**
   `tracking._is_secret` names `programming_runs.params_snapshot`, so the
   `row_changes` trigger stores `<redacted>` for it. `programming_logs` has no
   trigger at all.
3. **Nothing else changes.** A parameter set's revision history
   (`values_public`) still lists a secret key without its value, and a
   device's configuration card still hides a secret until somebody asks to see
   it.

### Consequences

* Good, because a run says exactly which WiFi, MQTT account and PIN a unit got.
* Bad, because the fleet salt (`creds_salt`), from which every device's MQTT
  password is derived, is now in the snapshot of every run that uses it. Anyone
  who can open a run can read it, as they can on the Parameters page, and every
  database backup carries it once per run.
* Bad, because a rotated secret stays readable in every run made before the
  rotation.
* Neutral, because the runs before this change keep their masked snapshots and
  their clear log lines. Nothing is rewritten.

### Confirmation

`tests/flasher/test_bench_gaps.py`: the SIM PIN is in the sent line and the
step response, the snapshot keeps `Password1`, and
`tracking._is_secret("programming_runs", "params_snapshot")` is true. The
local trigger was checked to list `params_snapshot` as its secret column.

## Pros and Cons of the Options

### Keep every value in clear

* Good, because the record answers "what did this unit get" without a second
  source.
* Bad, because the run record becomes a copy of the fleet's credentials.

### Mask every secret value in every stored line

* Good, because no secret leaves the parameter set.
* Bad, because the record no longer proves which value a unit got, and a
  short value cannot be masked without blanking ordinary text.

### Keep the masking as it was

* Good, because nothing changes.
* Bad, because it was inconsistent: the PIN was hidden while three passwords
  were in clear in the same log.

## More Information

The engine rules are in `api/app/services/flasher/CLAUDE.md`. Revisit this
record if run records leave the platform, for example in an export to a
customer.
