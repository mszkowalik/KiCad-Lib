// Demo scenarios — deliberately written in the exact declarative shape the
// platform will store per project in Postgres, so the PoC doubles as the spec.
// Ported from CE_Production_flasher config.py / test.py.

// ---------------------------------------------------------------------------
// Transport profiles. The ESP32-C6 talks over its built-in USB-Serial/JTAG
// peripheral, where DTR/RTS are NOT a UART bridge's auto-reset circuit but
// direct strapping controls (RTS→reset, DTR→IO0/boot) interpreted by the chip.
// Wrong order = unwanted reset or a device stuck in download mode, and a real
// reset makes the CDC device re-enumerate, invalidating the SerialPort handle.
// ---------------------------------------------------------------------------
export const TRANSPORT_PROFILES = {
  // External USB-UART bridge (CP210x / CH340 / FT232): classic DTR+RTS auto-reset.
  uart_bridge: {
    label: "external USB-UART bridge",
    before: "default_reset", // esptool-js ClassicReset
    after: "hard_reset", // pulse RTS
    flash_baud: 460800, // worth raising: real UART
    // Safe for a bridge: both lines low = chip runs, EN/IO0 released.
    monitor_signals: { dataTerminalReady: false, requestToSend: false },
    reenumerates_on_reset: false,
    // Pulse EN ourselves instead of trusting esptool-js's after("hard_reset"),
    // which is a no-op when the connect sequence already left RTS deasserted.
    explicit_hard_reset: true,
  },
  // ESP32-C6 / C3 / S3 native USB (Espressif VID 0x303a, PID 0x1001).
  //
  // DO NOT DRIVE DTR/RTS WHEN ATTACHING TO A RUNNING C6. The USB-Serial/JTAG
  // peripheral emulates the classic auto-reset circuit and resets the chip on
  // DTR=0 while RTS=1. Clearing "both" lines is only safe if the change is
  // atomic — CE_Dongle_v3's own tools/push_fs_serial.py documents that pyserial
  // applies DTR before RTS, stepping through (0,1) and rebooting the device on
  // every connect; it now leaves the lines asserted instead. Chrome's state
  // after port.open() is not specified, so the safe default is to never call
  // setSignals() in monitor mode. esptool-js still drives the lines during
  // flashing, where a reset is exactly what we want.
  usb_serial_jtag: {
    label: "built-in USB-Serial/JTAG",
    before: "usb_reset", // esptool-js UsbJtagSerialReset sequence
    after: "hard_reset",
    flash_baud: 115200, // CDC ignores baud; skip the pointless re-open
    monitor_signals: null, // never call setSignals() — see above
    reenumerates_on_reset: true, // USB device drops and comes back
    explicit_hard_reset: true,
  },
  // Same, but explicitly deasserts both lines in ONE setSignals call. Only for
  // measuring whether Chrome's single call is atomic on a given host — if it is
  // not, the device reboots on attach. Not for production.
  usb_serial_jtag_deassert: {
    label: "built-in USB-Serial/JTAG (deassert DTR+RTS — experiment only)",
    before: "usb_reset",
    after: "hard_reset",
    flash_baud: 115200,
    monitor_signals: { dataTerminalReady: false, requestToSend: false },
    reenumerates_on_reset: true,
    explicit_hard_reset: true,
  },
};

// Espressif USB-Serial/JTAG identifiers — used to auto-pick the profile.
export const USB_SERIAL_JTAG = { vendorId: 0x303a, productId: 0x1001 };

export function autoProfile(port) {
  const info = port?.getInfo?.() ?? {};
  return info.usbVendorId === USB_SERIAL_JTAG.vendorId && info.usbProductId === USB_SERIAL_JTAG.productId
    ? "usb_serial_jtag"
    : "uart_bridge";
}

const TASMOTA_STEPS = (opts = {}) => [
  { op: "wait_boot", label: "Wait for Tasmota boot", timeout: opts.bootTimeout ?? 20 },
  {
    op: "command",
    label: "Read firmware status",
    cmd: "Status",
    payload: "2",
    expect_key: "StatusFWR",
    timeout: 10,
    capture: { fw_version: "StatusFWR.Version", core: "StatusFWR.Core", hardware: "StatusFWR.Hardware" },
  },
  {
    op: "command",
    label: "Read device identity",
    cmd: "Status",
    payload: "0",
    expect_key: "Status",
    timeout: 10,
    capture: { topic: "Status.Topic", device_name: "Status.DeviceName" },
  },
  {
    op: "set_and_check",
    label: "Set FriendlyName1 and verify readback",
    cmd: "FriendlyName1",
    value: "{friendly_name}",
    timeout: 10,
  },
  {
    op: "command",
    label: "Read back FriendlyName1",
    cmd: "FriendlyName1",
    expect_key: "FriendlyName1",
    timeout: 10,
    capture: { friendly_readback: "FriendlyName1" },
  },
  { op: "assert_equals", label: "Verify FriendlyName1 stuck", var: "friendly_readback", equals: "{friendly_name}" },
  {
    op: "command",
    label: "Read sensor status (test-step shape)",
    cmd: "Status",
    payload: "10",
    expect_key: "StatusSNS",
    timeout: 10,
    capture: { sns_time: "StatusSNS.Time" },
  },
];

export const SCENARIOS = {
  ce_dongle_esp32: {
    name: "CE_Dongle_V2 (ESP32, UART bridge) — proof run",
    chip: "esp32",
    transport: "uart_bridge",
    flash: { mode: "dio", freq: "40m", size: "detect" },
    monitor_baud: 115200,
    vars: { friendly_name: "CE_PROOF" },
    steps: [
      { op: "esp_connect", label: "Detect chip + read MAC" },
      { op: "erase", label: "Erase flash" },
      {
        op: "flash",
        label: "Write firmware",
        firmware: "tasmota32_CE_DONGLE_V2-14.2.0.factory.bin",
        address: "0x0",
        verify_md5: true,
      },
      { op: "esp_reset", label: "Hard reset into the new firmware" },
      { op: "serial_open", label: "Open monitor serial", baud: 115200 },
      ...TASMOTA_STEPS(),
    ],
  },

  ce_aqua_esp32: {
    name: "CE_Aqua_V2 (ESP32, UART bridge) — proof run",
    chip: "esp32",
    transport: "uart_bridge",
    flash: { mode: "dio", freq: "40m", size: "detect" },
    monitor_baud: 115200,
    vars: { friendly_name: "CE_PROOF" },
    steps: [
      { op: "esp_connect", label: "Detect chip + read MAC" },
      { op: "erase", label: "Erase flash" },
      {
        op: "flash",
        label: "Write firmware",
        firmware: "tasmota32_CE_AQUA_V2-14.2.0.factory.bin",
        address: "0x0",
        verify_md5: true,
      },
      { op: "esp_reset", label: "Hard reset into the new firmware" },
      { op: "serial_open", label: "Open monitor serial", baud: 115200 },
      ...TASMOTA_STEPS(),
    ],
  },

  // CE_Dongle_V3 = ESP32-C6, 8MB flash, talks over its built-in USB-Serial/JTAG.
  //
  // Flash map (from firmware/partitions/esp32c6_partition_8MB_app3904k_fs3392k.csv):
  //   0x000000  factory image (bootloader + partition table + safeboot + app0)
  //   0x0E0000  app0        — where a field/OTA app-only update goes
  //   0x4B0000  spiffs      — LittleFS, 0x350000 bytes
  //
  // The build deliberately ships an EMPTY LittleFS (custom_files_upload =
  // no_files), and THIS firmware keeps Tasmota's whole Settings blob on
  // LittleFS (/.settings). So a blank production device needs the populated
  // filesystem image flashed too — exactly what the project's own
  // "Flash factory + filesystem" task (pio-tools/ce_flash_fs.py) does.
  // Flash params stay "keep": PlatformIO already baked qio/80m/8MB into the
  // image header, so there is nothing to patch.
  c6_dongle_v3: {
    name: "CE_Dongle_V3 (ESP32-C6, USB-Serial/JTAG) — blank device, factory + filesystem",
    chip: "esp32c6",
    transport: "usb_serial_jtag",
    flash: { mode: "keep", freq: "keep", size: "keep" },
    monitor_baud: 115200,
    vars: { friendly_name: "CE_PROOF" },
    steps: [
      { op: "esp_connect", label: "Detect chip + read MAC" },
      { op: "erase", label: "Erase flash" },
      {
        op: "flash",
        label: "Write factory image + LittleFS",
        files: [
          { firmware: "tasmota32c6-CE_DONGLE_V3.factory.bin", address: "0x0" },
          { firmware: "tasmota32c6-CE_DONGLE_V3-littlefs.bin", address: "0x4B0000" },
        ],
        verify_md5: true,
      },
      { op: "esp_reset", label: "Hard reset into the new firmware" },
      { op: "await_reenumerate", label: "Wait for the USB CDC device to come back", timeout: 25 },
      { op: "serial_open", label: "Open monitor serial", baud: 115200 },
      ...TASMOTA_STEPS({ bootTimeout: 60 }),
    ],
  },

  // Field/OTA-style update: app only, no erase, no filesystem write — this is
  // the path that PRESERVES /.settings and the Berry scripts on LittleFS.
  c6_dongle_v3_app_only: {
    name: "CE_Dongle_V3 (ESP32-C6) — app-only update, keeps settings + FS",
    chip: "esp32c6",
    transport: "usb_serial_jtag",
    flash: { mode: "keep", freq: "keep", size: "keep" },
    monitor_baud: 115200,
    vars: { friendly_name: "CE_PROOF" },
    steps: [
      { op: "esp_connect", label: "Detect chip + read MAC" },
      {
        op: "flash",
        label: "Write app0 only (0xE0000)",
        files: [{ firmware: "tasmota32c6-CE_DONGLE_V3.bin", address: "0xE0000" }],
        verify_md5: true,
      },
      { op: "esp_reset", label: "Hard reset into the new firmware" },
      { op: "await_reenumerate", label: "Wait for the USB CDC device to come back", timeout: 25 },
      { op: "serial_open", label: "Open monitor serial", baud: 115200 },
      ...TASMOTA_STEPS({ bootTimeout: 30 }),
    ],
  },

  // Non-destructive: talks to whatever firmware is already on the device.
  // Use this to check the C6 handshake-line behaviour without erasing anything.
  monitor_only: {
    name: "Monitor only (no erase, no flash)",
    chip: null,
    transport: null, // auto-detected from the port's USB ids
    flash: { mode: "dio", freq: "40m", size: "detect" },
    monitor_baud: 115200,
    vars: { friendly_name: "CE_PROOF" },
    steps: [
      { op: "serial_open", label: "Open monitor serial", baud: 115200 },
      // Probes repeatedly: works whether the device just booted, has been idle
      // for hours, or is still sitting in the ROM/stub loader (then it fails,
      // which is the answer you want).
      { op: "wait_boot", label: "Probe until the firmware answers", timeout: 20 },
      { op: "command", label: "Ping Status", cmd: "Status", expect_key: "Status", timeout: 10, capture: { topic: "Status.Topic" } },
      {
        op: "command",
        label: "Read firmware status",
        cmd: "Status",
        payload: "2",
        expect_key: "StatusFWR",
        timeout: 10,
        capture: { fw_version: "StatusFWR.Version", hardware: "StatusFWR.Hardware" },
      },
    ],
  },
};

export const DEFAULT_SCENARIO = "ce_dongle_esp32";
