# CE Dongle V3 bench: platform gaps for full tests

**Status:** Open list, from the CE_Dongle_V3 bench work of 2026-10-14 to 2026-10-18. It holds open
items only. Items 1, 3 to 6, 9, 11, 12, 15, 16 and 17, and the platform half of 8 and 10, landed
on 2026-10-18: see
`CHANGELOG.md` and decision 0093. Item 2 (mask secrets in the run log) is refused by user
decision: the run record keeps every value (decision 0094).

Item 13 is answered (user, 2026-10-18): "Program" stays AFTER "Install PCBA in enclosure", because
the antennas must be fitted before the WiFi and LTE steps. To program without leaving gaps, record
the enclosure step on the batch's twins and select that stack on the bench first
(`docs/reference/processes.md`, "The benches").

## Context

Project CE_Dongle_V3 (project 1) programs and tests each unit with deployment 1
"Dongle_V3 blank device", version 6 (id 47, published 2026-10-18). Version 6 has 49 steps and
17 checks. It runs on the bench page with the 7Sigma agent over USB Serial/JTAG. All runs used
unit 28844 (MAC `98:a3:16:be:da:90`). The board-side record is in
`CE_Dongle_v3_board/docs/reference/kicad-lib-platform.md`.

## Missing for full functional tests

| # | Item | What it would test |
|---|---|---|
| 7 | Test jig control through the agent: steps that set jig outputs and read jig measurements, with `assert_range` on the reading. The jig is not designed yet. | Outputs OUT1 and OUT2 under 24 V and a load, V_EXT input and the power OR-ing, RS-485 with a loopback or a Modbus slave, a DS18B20 on the 1-wire input, a supply dip for the brownout behaviour |
| 8 | A test step in the CE_Dongle_V3 process (deployment kind `test`). The `continue_on_fail` mode exists; the test deployment and its place in the process do not. | One run gives the full defect list of a unit |

## Data and process

| # | Item |
|---|---|
| 10 | Signal limits: a version 7 with `assert_range` on `wifi_rssi` (percent) and `lte_rsrp` (dBm), limits from loose parameters (`wifi_rssi_min`, `lte_rsrp_min`, … and `name@slot N` per station). Read the values back from the first 50 units, then set the real limits. |
| 14 | The process step "Laser mark" names no procedure. Deployment 10 "Dongle_V3 marking" exists and is active. The bench shows "no procedure". The project owner is still working on the marking. |
