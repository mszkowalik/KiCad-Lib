# Web-only ESP flasher — proof of concept

Throwaway harness that answers one question: **can a browser do the whole
production flashing job — erase, flash, then talk Tasmota over serial — with no
local Python install?** It is also the executable spec for the scenario step
vocabulary that moves into the platform (`docs/flasher/design.md`).

## Run it

```bash
cd clients/flasher-poc
npm install
# firmware images (already copied if you ran this once):
cp ~/Projects/CE_Production_flasher/binaries/*.bin public/firmware/                                    # ESP32 V2
cp ~/Projects/CE_Dongle_v3_board/firmware/build_output/firmware/tasmota32c6-CE_DONGLE_V3*.bin public/firmware/   # C6 V3
cp ~/Projects/CE_Dongle_v3_board/firmware/.pio/build/tasmota32c6-CE_DONGLE_V3/ce_littlefs.bin \
   public/firmware/tasmota32c6-CE_DONGLE_V3-littlefs.bin                                              # C6 filesystem
npm run dev            # http://127.0.0.1:5174  — Chrome or Edge only
```

Scenarios in the picker: `CE_Dongle_V2` / `CE_Aqua_V2` (ESP32 over a UART
bridge), `CE_Dongle_V3` blank device (**ESP32-C6**: factory @0x0 + LittleFS
@0x4B0000), `CE_Dongle_V3` app-only (@0xE0000, keeps `/.settings`), and
`Monitor only` (erases nothing — **use this first on a C6**).

Then per device: **Connect port…** → pick the adapter → **Run scenario**.
`+ Station` adds slots (max 5); **Run scenario on all ready stations** fires them
in parallel, which is the multi-device measurement.

- `/probe.html` — reports what this browser actually supports (Web Serial in the
  page, in a worker, granted ports, signal control).
- **Download run JSON** — the full per-station log, captured values and per-step
  timings, i.e. exactly what the platform will store in Postgres.

## Test without hardware

```bash
npm test
```

Replays the **real** serial output recorded by the Python tool
(`real_lines.json`, extracted from `reports/dongle_F8B3B742DAF8_*.json`) against
a simulated device and checks the interpreter: line framing, the two-stage JSON
parse ported from `serial_device.py`, command/response matching,
`set_and_check` confirmation, captures, asserts, timeouts and the failure paths.

## Files

| File | Role |
|---|---|
| `station.js` | One device slot: esptool-js flashing **and** the Tasmota line protocol on the same port |
| `runner.js` | The step interpreter (the ops that move to `services/flasher/` in Python) |
| `scenario.js` | Scenario definitions + **transport profiles** (UART bridge vs ESP32-C6 built-in USB-Serial/JTAG) |
| `main.js` | Station grid, port re-attach, parallel run, JSON export |
| `test_sim.mjs` | Node test against the simulated device |
