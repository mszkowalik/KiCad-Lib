# Open questions on the material ledger (2026-10-24)

Working file. Each item says what is done meanwhile, so nothing waits on it.
Delete this file when the questions are answered.

The cut-over is deployed and the rundown is done. The result is in
[cutover.md](cutover.md), "On production". Answered on 2026-10-24: the deploy
(go ahead) and the lot history (bound).

## Questions

1. **CE_Aqua_V2 and the DC_* projects have no process.** Their batches cannot
   be rebuilt into twins until a process says their steps. Meanwhile: their
   material stays on the batch as draws, as before. Which steps do these
   products have?
2. **128 devices have no batch.** 76 are CE_Aqua_V2 devices with no state and
   no event (28 have no MAC, first seen 2024-08-05 to 2025-12-22). 52 are
   CE_Dongle_V2 devices whose `produced` event names no batch (43 have no MAC;
   40 are shipped/unidentified, 10 missing prototypes, 1 missing faulty). Only
   one has a programming run that names a batch. Meanwhile: they stay without
   a batch. Do you know their batches?
3. **The rebuild of V2 Batches 1–7**: a part drawn for a board that was never
   programmed stays in the batch's own cost (`loss`), and a part the records
   show short stays short. No step without a record is stated as done. Is
   that the treatment you want, or do you want some steps stated (laser mark,
   label, leaflet)?
4. **Batches 5–7 of CE_Dongle_V2 drew 115, 47 and 25 fewer antennas,
   enclosures and cartons than devices they produced.** Rebuilt as `short`.
   Do you know where those parts came from (another batch's draws, stock not
   recorded)?
5. **`lot_pricing` (FIFO for new draws).** The history is bound, so the switch
   can go on. It refuses a draw that no lot covers, which can stop the bench
   when a purchase is not entered yet. Switch it on?
6. **Uncharged draws: 34 small JLC movements, $25.87 in total.** Parts of 7
   assembly orders that no batch claims (SMT025030460758, SMT025030460766,
   SMT025040962123, SMT025082862560, SMT025090262482, SMT026032562986,
   SMT026062262938) and 7 JLC warehouse picks. Which batches, if any?
7. **No company on 6 JLC warehouse picks** (2024-09-27 to 2025-03-25) and on
   2 placeholder documents (antennas and cartons, 2024, "no invoice found").
   Whose stock were they?
8. **The next CE_Dongle_V3 batch stops at "Take enclosure"**. Process v6 and
   v7 (v7 is v6 with an LTE test) draw raw SIM6-12-3W, of which 0 are left;
   the 40 cut ones are part 577. Batch 2164, programmed today on v7, took its
   60 enclosures on 2026-10-19 and is past that step. The state map
   577 = 233 + cut_* is stored. Building the phase-4 abilities
   (states as properties, conditions on them) fixes this; until then a v7
   that takes part 577 would. Which do you want first?
9. Design questions 2–8 of [design.md](design.md) §10 are still open.
