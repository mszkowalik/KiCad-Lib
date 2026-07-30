# Applied state — the live library

**This is the record of what was actually applied**, read back from the production library at
`http://192.168.200.28/lib` on 2026-07-30. It supersedes the *proposed* tables in
`02-migration-173.md`, which described the dev database before the work ran.

| | |
|---|---|
| Footprints | **171** |
| Renamed | **77** |
| With a `display_name` | **171/171** |
| Dangling `Footprint` references | 0 |
| Mirror header/filename mismatches | 0 |
| Mirror warnings on full rebuild | 0 |

Every rename was applied as a **new footprint version** (the `(footprint "NAME")` header inside
the `.kicad_mod` must match its filename), so the previous version stays restorable from the
version rail. Each is also recorded in `audit_log` as `footprint.rename` with `previous_name`.

> **Boards already laid out are not updated by a rename.** They keep the old footprint string
> until *Update Footprints from Library* is run in KiCad.

## Renames applied

| Previous name | Current name |
|---|---|
| `7Sigma_Logo` | `7Sigma-Logo_3mm_SilkScreen` |
| `ANT-SMD_KH-IPEX-K501-29` | `U.FL_Kinghelm_KH-IPEX-K501-29_Vertical` |
| `ANT-SMD_L10.0-W3.0` | `Antenna_SMD_Rainsun_GPS1003` |
| `ANT-TH_L9.0-W9.0_BWGNSCNX9-9W2` | `Antenna_THT_BatWireless_BWGNSCNX9-9W2` |
| `ANT_1206_3216Metric` | `Abracon_ACS0301U_1206_3216Metric` |
| `ANT_3PIN_1206_3216Metric` | `PulseElectronics_W3011_3.2x1.6mm` |
| `BAT-TH_HU2032-LF` | `BatteryHolder_Renata_HU2032-LF_1x2032` |
| `BAT-TH_KEYS2466` | `BatteryHolder_Keystone_2466_1xAAA_Drill1.2mm_Pad1.6mm` |
| `CONN-SMD_DF40C-100DS-0.4V-51` | `DEPRECATED_DF40C-100DS-0.4V_WrongPinNumbering_DoNotUse` |
| `CONN-TH_DB301V-3.5-2P-GN` | `TerminalBlock_Dorabo_DB301V-3.5-2P_1x02_P3.50mm_Vertical` |
| `CONN-TH_XY302V-3.5-2P` | `TerminalBlock_Xinlaiya_XY302V-3.5-2P_1x02_P3.50mm_Vertical` |
| `DFN-6_1.6x1mm-P0.55mm` | `DFN-6_1.6x1mm_P0.5mm` |
| `FIX-LEMB2-4.8V0-F` | `Lightpipe_FIX-LEMB2-4.8V0-F` |
| `FIX-LEMB2-7V0-F` | `Lightpipe_FIX-LEMB2-7V0-F` |
| `FIX-LEMB3-8V0-F` | `Lightpipe_FIX-LEMB3-8V0-F` |
| `FPC-SMD_24P-P0.50_FPC-05F-24PH20` | `Xunpu_FPC-05F-24PH20_1x24-1MP_P0.50mm_Horizontal` |
| `FPC-SMD_AFC01-S22FCC-00` | `Jushuo_AFC01-S22FCC-00_1x22-1MP_P0.50mm_Horizontal` |
| `FUSE-TH_L24.4-W9.4-P22.60` | `FuseHolder_Cylinder-5x20mm_XFCN_PTF-77_P22.6mm_Horizontal` |
| `HAMMOND_1551RFLGY` | `Enclosure_Hammond_1551RFLGY` |
| `HAMMOND_1551TFLGY` | `Enclosure_Hammond_1551TFLGY` |
| `HAMMOND_1551XFLGY` | `Enclosure_Hammond_1551XFLGY` |
| `HAMMOND_1556CGY` | `Enclosure_Hammond_1556CGY` |
| `IDC-SMD_10P-P1.27-3220-10-0300-00` | `Hanxia_JN1.27-2x5-TP-H4.9_2x05_P1.27mm_Vertical_SMD` |
| `IND-SMD_L4.5-W4.1_SRP4020TA` | `L_Bourns_SRP4020TA` |
| `L_SMD_L5.8-W5.2` | `L_ShouHan_CY54_5.8x5.2mm` |
| `LED-SMD_3P-L3.5-W3.5-R-RD-C` | `LED_Silverlight_M3535N1_3.5x3.5mm` |
| `LED-SMD_3P-L3.8-W3.8` | `LED_OSRAM_SFH4725AS_3.8x3.8mm` |
| `LED-SMD_4P-L1.3-W1.3-P0.80_WS2812E-1313` | `LED_Worldsemi_WS2812E-1313_1.3x1.3mm_P0.8mm` |
| `LED-SMD_4P-L1.6-W1.5-BR` | `LED_XINGLIGHT_XL-1615RGBC-RF_1.6x1.5mm` |
| `LGA-12_L2.0-W2.0-P0.50-BL` | `STMicroelectronics_LGA-12_2x2mm_P0.5mm_LayoutBorder4x2y` |
| `LGA-94_L15.0-W18.0-P0.6_xE310` | `Telit_xE310_LGA-94_15x18mm_P0.6mm` |
| `LGA-97_L10.5-W8.3-P0.60-TL` | `Murata_LBUA5QJ2AB_LGA-97_10.5x8.3mm_P0.6mm` |
| `LGA-SMD_L23.6-W19.9-P1.10_EG915U-EC` | `Quectel_EG915U_LGA-126_19.9x23.6mm_P1.1mm` |
| `MIC-SMD_5P-L3.0-W4.0-P0.85-BL` | `Microphone_ST_MP34DT05-A_3x4mm_P0.85mm` |
| `MIC-SMD_5P-L3.5-W2.7-TL_MMICT390200012` | `Microphone_InvenSense_T3902_3.5x2.7mm` |
| `MountingHole_2.5mm_Pad_4mm` | `MountingHole_2.5mm_Pad4mm` |
| `MountingHole_3.2mm_M3_Pad_6mm` | `MountingHole_3.2mm_M3_Pad6mm` |
| `NID65_MWU` | `Converter_DCDC_MEANWELL_NID65_Vertical` |
| `NID65_MWU_Horizontal` | `Converter_DCDC_MEANWELL_NID65_Horizontal` |
| `PhoenixContact_DMCV_1,5_12-GF-3.5_1x12_P3.50mm_Vertical_ThreadedFlange` | `PhoenixContact_DMCV_1,5_12-G1F-3.5_2x12_P3.50mm_Vertical_ThreadedFlange` |
| `Pin_D0.7mm_W1mm_Soldering` | `Pin_D0.7mm_Pad1.4mm_Soldering` |
| `QFN-60_L7.0-W7.0-P0.40-TL-EP5.3` | `QFN-60-1EP_7x7mm_P0.4mm_EP5.3x5.3mm` |
| `Raspberry-Pi-5-Compute-Module` | `RaspberryPi_CM5_Mechanical_40x55mm_4xMountingHole2.7mm` |
| `RELAY-SMD_G6K-2F-X-XX` | `Relay_DPDT_OMRON_G6K-2F-Y_Pad2.1x1mm` |
| `RJ45-TH_R-RJ45R08P-A004` | `RJ45_Ckmtw_R-RJ45R08P-A004` |
| `RJ45-TH_RC01812` | `RJ45_RCH_RC01812` |
| `RJ45_CKMTW_R-RJ45S08P-B000` | `RJ45_Ckmtw_R-RJ45S08P-B000` |
| `SIM-SMD_NANO-SIM-TL6P-H1.35` | `nanoSIM_ShouHan_TL6P-H1.35` |
| `SMA-SMD_BWSMA-KE-P001` | `SMA_BAT_Wireless_BWSMA-KE-P001` |
| `SMA-TH_BWSMA-KE-Z001` | `SMA_BAT_Wireless_BWSMA-KE-Z001` |
| `SMD_BD5.6-D4.1` | `Mounting_Sinhoo_SMTSO2515CTJ` |
| `SMD_BD5.6-L5.6-W5.6-D3.6` | `Mounting_Sinhoo_SMTSO2010CTJ` |
| `SMD_RH-5015` | `TestPoint_Ronghe_RH-5015_SMD` |
| `SOIC-14_3.9x8.7mm_P1.27mm_EP6.4x2.65` | `SOIC-14-1EP_3.9x8.7mm_P1.27mm_EP2.2x6.4mm` |
| `SON-12_L4.0-W2.5-P0.40-BL-EP` | `SON-12-1EP_2.5x4mm_P0.4mm_ThermalVias` |
| `SW-SMD_4P-L3.0-W2.6-P1.80-LS3.4-H0.65` | `SW_Push-4P_SPST_SMD_3x2.6mm_H0.65mm_G-Switch_GT-TC025D-H0065-L1` |
| `SW-SMD_4P-L4.2-W3.2-P2.15-LS4.5-H2.5` | `SW_Push-4P_SPST_SMD_4.2x3.2mm_H2.5mm_G-Switch_GT-TC048D-H025-L1` |
| `SW-SMD_4P-L6.0-W6.0-P4.50-LS9.0-H4.3` | `SW_Push-4P_SPST_SMD_6x6mm_H4.3mm_Kinghelm_KH-6X6X4.3H-STM` |
| `SW-SMD_4P-L6.0-W6.0-P4.50-LS9.0-H5.0` | `SW_Push-4P_SPST_SMD_6x6mm_H5mm_Kinghelm_KH-6X6X5H-STM` |
| `SW-SMD_4P-L6.0-W6.0-P4.50-LS9.0-H7.0` | `SW_Push-4P_SPST_SMD_6x6mm_H7mm_Kinghelm_KH-6X6X7H-STM` |
| `SW-SMD_L6.0-W3.5-LS8.4-H2.5` | `SW_Push-2P_SPST_SMD_6x3.5mm_H2.5mm_ShouHan_TS3625A` |
| `SW-SMD_TS24CA` | `SW_Push-4P_SPST_SMD_4.7x3.5mm_H2.25mm_ShouHan_TS24CA` |
| `SW-TH_4P-L6.0-W6.0-P4.50-LS6.5-H9.0` | `SW_Push-4P_SPST_THT_6x6mm_H9mm_Kinghelm_KH-6X6X9H-TJ` |
| `SW-TH_4P-RA-L6.0-W6.0-H9.0` | `SW_Push-4P_SPST_THT_Horizontal_6x6mm_HCTL_TC-6615-9.0-160G` |
| `TAKACHI_SIM6-12-3W` | `Enclosure_TAKACHI_SIM6-12-3W` |
| `USB-3.1-SMD_U262-161N-4BVC11` | `USB_C_Receptacle_XKB_U262-161N-4BVC11` |
| `USB-B-TH_USB-B01` | `USB_B_SOFNG_USB-B01` |
| `USON-8_L3.0-W2.0-P0.50-BL-EP` | `Winbond_USON-8-1EP_2x3mm_P0.5mm_EP0.3x1.7mm` |
| `V-DFN3020-13-A_L3.0-W2.0-P0.45-BL-EP_AP6335X` | `DiodesIncorporated_V-DFN3020-13-A_3x2mm_P0.45mm` |
| `VQFN-14_L3.5-W3.5-P0.50-BL-EP-ThermalVias` | `VQFN-14-1EP_3.5x3.5mm_P0.5mm_EP2x2mm_ThermalVias` |
| `VQFN-20_L4.6-W3.6-P0.50-BL-EP` | `VQFN-20-1EP_4.6x3.6mm_P0.5mm_EP3.05x2.05mm` |
| `VSON-14_L4.0-W3.0-P0.50-BL-EP_TI_DSJ` | `TexasInstruments_VSON-14-1EP_4x3mm_P0.5mm_ThermalVias` |
| `VSON-6_L1.5-W1.5-P0.50-TL` | `VSON-6_1.5x1.5mm_P0.5mm` |
| `WSON-10-1EP_2.2x2.0mm_P0.40-EP0.9x1.5mm` | `WSON-10-1EP_2.2x2mm_P0.4mm_EP0.9x1.5mm_ThermalVias` |
| `WSON-8_L6.0-W5.0-P1.27-BL-EP` | `WSON-8-1EP_5x6mm_P1.27mm_EP4.3x3.4mm` |
| `XCVR_LC76G` | `Quectel_LC76G-28Pin_P1.1mm` |
| `XCVR_LE910R1-EU` | `Telit_LE910R1_LGA-181_28.2x28.2mm_Layout15x15_P1.8mm` |

## Current footprints and their package names

| Footprint | `display_name` |
|---|---|
| `7Sigma-Logo_3mm_SilkScreen` | Logo 3mm silkscreen |
| `Abracon_ACS0301U_1206_3216Metric` | 1206 |
| `Antenna_SMD_Rainsun_GPS1003` | SMD 10x3mm |
| `Antenna_THT_BatWireless_BWGNSCNX9-9W2` | THT 9x9mm |
| `BatteryHolder_Keystone_2466_1xAAA_Drill1.2mm_Pad1.6mm` | AAA Holder |
| `BatteryHolder_Renata_HU2032-LF_1x2032` | CR2032 Holder |
| `CP_EIA-7343-31_Kemet-D` | EIA-7343-31 Kemet-D |
| `CP_Elec_10x10` | D10xH10mm |
| `CP_Elec_6.3x7.7` | D6.3xH7.7mm |
| `C_0402_1005Metric` | 0402 |
| `C_0805_2012Metric` | 0805 |
| `C_1206_3216Metric` | 1206 |
| `C_1210_3225Metric` | 1210 |
| `Converter_DCDC_MEANWELL_NID65_Horizontal` | NID65 THT Horizontal |
| `Converter_DCDC_MEANWELL_NID65_Vertical` | NID65 THT Vertical |
| `Crystal_SMD_3225-4Pin_3.2x2.5mm` | SMD3225-4P |
| `DEPRECATED_DF40C-100DS-0.4V_WrongPinNumbering_DoNotUse` | DO NOT USE - wrong pin numbering |
| `DFN-6_1.6x1mm_P0.5mm` | DFN-6 |
| `DFN-8-1EP_3x2mm_P0.5mm_EP1.36x1.46mm` | DFN-8 3x2mm |
| `DFN-8-1EP_3x3mm_P0.65mm_EP1.55x2.4mm` | DFN-8 3x3mm |
| `D_0402_1005Metric` | 0402 |
| `D_SMA` | SMA |
| `D_SOD-123` | SOD-123 |
| `D_SOD-123F` | SOD-123F |
| `D_SOD-323` | SOD-323 |
| `D_SOD-523` | SOD-523 |
| `DiodesIncorporated_V-DFN3020-13-A_3x2mm_P0.45mm` | VDFN-13 |
| `ESP32-WROOM-32U` | ESP32-WROOM-32U |
| `Enclosure_Hammond_1551RFLGY` | Enclosure 1551RFLGY |
| `Enclosure_Hammond_1551TFLGY` | Enclosure 1551TFLGY |
| `Enclosure_Hammond_1551XFLGY` | Enclosure 1551XFLGY |
| `Enclosure_Hammond_1556CGY` | Enclosure 1556CGY |
| `Enclosure_TAKACHI_SIM6-12-3W` | Enclosure SIM6-12-3W |
| `FuseHolder_Cylinder-5x20mm_XFCN_PTF-77_P22.6mm_Horizontal` | THT 24.4x9.4mm |
| `Fuse_0805_2012Metric` | 0805 |
| `Fuse_1206_3216Metric` | 1206 |
| `Fuse_2920_7451Metric` | 2920 |
| `HVSSOP-10-1EP_3x3mm_P0.5mm_EP1.57x1.88mm_ThermalVias` | HVSSOP-10 |
| `Hanxia_JN1.27-2x5-TP-H4.9_2x05_P1.27mm_Vertical_SMD` | 2x05 1.27mm SMD, 4.04mm rows |
| `Hirose_DF40C-100DS-0.4V_2x50_P0.4mm` | 2x50 0.4mm |
| `IDC-Header_2x05_P2.54mm_Vertical` | 2x05 2.54mm |
| `Jushuo_AFC01-S22FCC-00_1x22-1MP_P0.50mm_Horizontal` | FPC-22P 0.5mm |
| `Kinghelm_KH5220-A36` | Chip Antenna 6x2mm |
| `LED_0402_1005Metric` | 0402 |
| `LED_0603_1608Metric` | 0603 |
| `LED_0805_2012Metric` | 0805 |
| `LED_OSRAM_SFH4725AS_3.8x3.8mm` | 3.8x3.8mm |
| `LED_Silverlight_M3535N1_3.5x3.5mm` | SMD3535 |
| `LED_Worldsemi_WS2812E-1313_1.3x1.3mm_P0.8mm` | 1.3x1.3mm |
| `LED_XINGLIGHT_XL-1615RGBC-RF_1.6x1.5mm` | 1.6x1.5mm |
| `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm_ThermalVias` | LFCSP-16 |
| `LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y` | LGA-14 3x2.5mm |
| `L_0402_1005Metric` | 0402 |
| `L_0603_1608Metric` | 0603 |
| `L_Bourns_SRP4020TA` | 4.5x4.1mm |
| `L_Changjiang_FTC404030S` | 4.1x4.1mm |
| `L_Murata_DFE201610P` | 0806 |
| `L_ShouHan_CY54_5.8x5.2mm` | 5.8x5.2mm |
| `L_Wuerth_HCM-1350` | SMD 13.3x13.3mm |
| `Lightpipe_FIX-LEMB2-4.8V0-F` | Lightpipe L4.8mm, D2.3mm head |
| `Lightpipe_FIX-LEMB2-7V0-F` | Lightpipe L7mm, D2.3mm head |
| `Lightpipe_FIX-LEMB3-8V0-F` | Lightpipe L8mm, D3.3mm head |
| `Microphone_InvenSense_T3902_3.5x2.7mm` | 2.6x3.5mm |
| `Microphone_ST_MP34DT05-A_3x4mm_P0.85mm` | 4x3mm |
| `MountingHole_2.5mm_Pad4mm` | MountingHole 2.5mm, pad 4mm |
| `MountingHole_3.2mm_M3_Pad6mm` | MountingHole 3.2mm M3, pad 6mm |
| `Mounting_Sinhoo_SMTSO2010CTJ` | SMD nut, 3.8mm hole |
| `Mounting_Sinhoo_SMTSO2515CTJ` | SMD nut M2.5, 4.3mm hole |
| `Murata_LBUA5QJ2AB_LGA-97_10.5x8.3mm_P0.6mm` | LGA-97 10.5x8.3mm |
| `Osram_BPW34S-SMD` | SMD 4.5x4mm |
| `PhoenixContact_DMCV_1,5_12-G1F-3.5_2x12_P3.50mm_Vertical_ThreadedFlange` | TB-2x12P 3.5mm Vertical Flanged |
| `PhoenixContact_MCV_1,5_12-GF-3.5_1x12_P3.50mm_Vertical_ThreadedFlange` | TB-12P 3.5mm Vertical Flanged |
| `PhoenixContact_MCV_1,5_2-GF-3.5_1x02_P3.50mm_Vertical_ThreadedFlange` | TB-2P 3.5mm Vertical Flanged |
| `PhoenixContact_MCV_1,5_4-GF-3.5_1x04_P3.50mm_Vertical_ThreadedFlange` | TB-4P 3.5mm Vertical Flanged |
| `PhoenixContact_MCV_1,5_8-GF-3.5_1x08_P3.50mm_Vertical_ThreadedFlange` | TB-8P 3.5mm Vertical Flanged |
| `PhoenixContact_MC_1,5_10-GF-3.81_1x10_P3.81mm_Horizontal_ThreadedFlange` | TB-10P 3.81mm Horizontal Flanged |
| `PhoenixContact_MC_1,5_2-G-3.5_1x02_P3.50mm_Horizontal` | TB-2P 3.5mm Horizontal |
| `PhoenixContact_MC_1,5_2-G-3.81_1x02_P3.81mm_Horizontal` | TB-2P 3.81mm Horizontal |
| `PhoenixContact_MC_1,5_2-GF-3.81_1x02_P3.81mm_Horizontal_ThreadedFlange` | TB-2P 3.81mm Horizontal Flanged |
| `PhoenixContact_MC_1,5_4-GF-3.81_1x04_P3.81mm_Horizontal_ThreadedFlange` | TB-4P 3.81mm Horizontal Flanged |
| `PhoenixContact_MC_1,5_6-GF-3.81_1x06_P3.81mm_Horizontal_ThreadedFlange` | TB-6P 3.81mm Horizontal Flanged |
| `PhoenixContact_MC_1,5_8-GF-3.81_1x08_P3.81mm_Horizontal_ThreadedFlange` | TB-8P 3.81mm Horizontal Flanged |
| `PhoenixContact_MSTBV_2,5_2-GF-5,08_1x02_P5.08mm_Vertical_ThreadedFlange` | TB-2P 5.08mm Vertical Flanged |
| `PhoenixContact_MSTBV_2,5_4-GF-5,08_1x04_P5.08mm_Vertical_ThreadedFlange` | TB-4P 5.08mm Vertical Flanged |
| `PinHeader_1x02_P2.54mm_Horizontal` | 1x02 2.54mm |
| `PinHeader_2x05_P1.27mm_Vertical_SMD` | 2x05 1.27mm SMD, 3.9mm rows |
| `PinHeader_2x07_P2.54mm_Vertical` | 2x07 2.54mm |
| `PinSocket_2x15_P2.54mm_Horizontal` | 2x15 2.54mm |
| `Pin_D0.7mm_Pad1.4mm_Soldering` | Pin D0.7mm, pad 1.4mm |
| `PulseElectronics_W3011_3.2x1.6mm` | SMD-3P 3.2x1.6mm |
| `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm_ThermalVias` | QFN-16 |
| `QFN-28_4x4mm_P0.5mm` | QFN-28 |
| `QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm_ThermalVias` | QFN-56 EP3.2x3.2mm |
| `QFN-56-1EP_7x7mm_P0.4mm_EP4x4mm_ThermalVias` | QFN-56 EP4x4mm |
| `QFN-60-1EP_7x7mm_P0.4mm_EP5.3x5.3mm` | QFN-60 |
| `QFN-68-1EP_8x8mm_P0.4mm_EP6.4x6.4mm_ThermalVias` | QFN-68 |
| `Quectel_EG915U_LGA-126_19.9x23.6mm_P1.1mm` | LGA-126 19.9x23.6mm |
| `Quectel_LC76G-28Pin_P1.1mm` | LC76G-28Pin 9.7x10.1mm |
| `RJ45_Ckmtw_R-RJ45R08P-A004` | RJ45 8P8C THT |
| `RJ45_Ckmtw_R-RJ45S08P-B000` | RJ45 8P8C Shielded THT |
| `RJ45_RCH_RC01812` | RJ45 8P8C Shielded SMD |
| `R_0402_1005Metric` | 0402 |
| `R_0805_2012Metric` | 0805 |
| `R_1206_3216Metric` | 1206 |
| `RaspberryPi_CM5_Mechanical_40x55mm_4xMountingHole2.7mm` | Mechanical 40x55mm |
| `Relay_DPDT_OMRON_G6K-2F-Y_Pad2.1x1mm` | SMD 10x6.5mm |
| `Relay_SPDT_Omron_G2RL-1` | THT 12.5x28.8mm |
| `SMA_BAT_Wireless_BWSMA-KE-P001` | SMA SMD |
| `SMA_BAT_Wireless_BWSMA-KE-Z001` | SMA THT |
| `SMA_BAT_Wireless_BWSMA-KWE-Z001` | SMA THT Right-Angle |
| `SOIC-14-1EP_3.9x8.7mm_P1.27mm_EP2.2x6.4mm` | SOIC-14 EP |
| `SOIC-14_3.9x8.7mm_P1.27mm` | SOIC-14 |
| `SOIC-16_3.9x9.9mm_P1.27mm` | SOIC-16 |
| `SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm_ThermalVias` | SOIC-8 EP |
| `SOIC-8_3.9x4.9mm_P1.27mm` | SOIC-8 |
| `SOIC-8_5.3x5.3mm_P1.27mm` | SOIC-8 5.3x5.3mm |
| `SON-12-1EP_2.5x4mm_P0.4mm_ThermalVias` | SON-12 |
| `SOT-223` | SOT-223 |
| `SOT-23-3` | SOT-23-3 |
| `SOT-23-5` | SOT-23-5 |
| `SOT-23-6` | SOT-23-6 |
| `SOT-353_SC-70-5` | SC-70-5 |
| `SOT-363_SC-70-6` | SC-70-6 |
| `SOT-523` | SOT-523 |
| `SOT-563` | SOT-563 |
| `STMicroelectronics_LGA-12_2x2mm_P0.5mm_LayoutBorder4x2y` | LGA-12 2x2mm |
| `SW_DIP_SPSTx06_Slide_9.6x16.8mm_W7.62mm_P2.54mm` | THT-12P 9.6x16.8mm |
| `SW_Push-2P_SPST_SMD_6x3.5mm_H2.5mm_ShouHan_TS3625A` | SMD-2P 6.1x3.7x2.5mm |
| `SW_Push-4P_SPST_SMD_3x2.6mm_H0.65mm_G-Switch_GT-TC025D-H0065-L1` | SMD-4P 3x2.6x0.65mm |
| `SW_Push-4P_SPST_SMD_4.2x3.2mm_H2.5mm_G-Switch_GT-TC048D-H025-L1` | SMD-4P 4.2x3.2x2.5mm |
| `SW_Push-4P_SPST_SMD_4.7x3.5mm_H2.25mm_ShouHan_TS24CA` | SMD-4P 4.7x3.5x2.25mm Right-Angle |
| `SW_Push-4P_SPST_SMD_6x6mm_H4.3mm_Kinghelm_KH-6X6X4.3H-STM` | SMD-4P 6x6x4.3mm |
| `SW_Push-4P_SPST_SMD_6x6mm_H5mm_Kinghelm_KH-6X6X5H-STM` | SMD-4P 6x6x5mm |
| `SW_Push-4P_SPST_SMD_6x6mm_H7mm_Kinghelm_KH-6X6X7H-STM` | SMD-4P 6x6x7mm |
| `SW_Push-4P_SPST_THT_6x6mm_H9mm_Kinghelm_KH-6X6X9H-TJ` | THT-4P 6x6x9mm |
| `SW_Push-4P_SPST_THT_Horizontal_6x6mm_HCTL_TC-6615-9.0-160G` | THT-4P 6x6mm Right-Angle |
| `TDSON-8_6.15x5.15mm` | TDSON-8 |
| `TSOP-6_1.65x3.05mm_P0.95mm` | TSOP-6 |
| `TSSOP-20_4.4x6.5mm_P0.65mm` | TSSOP-20 |
| `Telit_LE910R1_LGA-181_28.2x28.2mm_Layout15x15_P1.8mm` | LGA-181 28.2x28.2mm |
| `Telit_xE310_LGA-94_15x18mm_P0.6mm` | LGA-94 15x18mm |
| `TerminalBlock_Dorabo_DB301V-3.5-2P_1x02_P3.50mm_Vertical` | TB-2P 3.5mm Vertical |
| `TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal` | TB-2P 5.08mm Horizontal |
| `TerminalBlock_Plug_Invisible` | TB Plug (no land) |
| `TerminalBlock_Xinlaiya_XY302V-3.5-2P_1x02_P3.50mm_Vertical` | TB-2P 3.5mm Vertical |
| `TestPoint_Pad_1.5x1.5mm` | TestPoint 1.5x1.5mm |
| `TestPoint_Pad_D1.5mm` | TestPoint D1.5mm |
| `TestPoint_Ronghe_RH-5015_SMD` | TestPoint Loop 2.8x1.5mm |
| `TexasInstruments_VSON-14-1EP_4x3mm_P0.5mm_ThermalVias` | VSON-14 |
| `Texas_SWRA117D_2.4GHz_Left` | PCB Trace |
| `U.FL_Kinghelm_KH-IPEX-K501-29_Vertical` | U.FL SMD |
| `UQFN-16_1.8x2.6mm_P0.4mm` | UQFN-16 |
| `USB_B_SOFNG_USB-B01` | USB-B 4P THT |
| `USB_C_Receptacle_G-Switch_GT-USB-7010ASV` | USB-C 16P, 0.6mm shell posts |
| `USB_C_Receptacle_XKB_U262-161N-4BVC11` | USB-C 16P, 0.7mm shell posts |
| `USON-10_2.5x1.0mm_P0.5mm` | USON-10 |
| `VQFN-14-1EP_3.5x3.5mm_P0.5mm_EP2x2mm_ThermalVias` | VQFN-14 |
| `VQFN-20-1EP_4.6x3.6mm_P0.5mm_EP3.05x2.05mm` | VQFN-20 |
| `VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm_ThermalVias` | VQFN-40 |
| `VSON-6_1.5x1.5mm_P0.5mm` | VSON-6 |
| `VSON-8_3.3x3.3mm_P0.65mm_NexFET` | VSON-8 |
| `WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm_ThermalVias` | WQFN-16 |
| `WSON-10-1EP_2.2x2mm_P0.4mm_EP0.9x1.5mm_ThermalVias` | WSON-10 |
| `WSON-8-1EP_5x6mm_P1.27mm_EP4.3x3.4mm` | WSON-8 |
| `Winbond_USON-8-1EP_2x3mm_P0.5mm_EP0.3x1.7mm` | USON-8 2x3mm |
| `Winbond_USON-8-2EP_3x4mm_P0.8mm_EP0.2x0.8mm` | USON-8 3x4mm |
| `Xilinx_FGG484` | BGA-484 23x23mm |
| `Xilinx_FTG256` | BGA-256 17x17mm |
| `Xunpu_FPC-05F-24PH20_1x24-1MP_P0.50mm_Horizontal` | FPC-24P 0.5mm |
| `nanoSIM_ShouHan_TL6P-H1.35` | nanoSIM 6P |
| `ublox_ZED` | LGA-102 17x22mm |

---

## Not renamed, on purpose

- **`DEPRECATED_DF40C-100DS-0.4V_WrongPinNumbering_DoNotUse`** — kept, not deleted, because three
  historical versions of `DF40C-100DS-0.4V-51` still pin it; deleting would make that component's
  own history unreproducible. Renamed and marked so it cannot be picked by mistake.
- **`BatteryHolder_Keystone_2466_1xAAA_Drill1.2mm_Pad1.6mm`** and
  **`Relay_DPDT_OMRON_G6K-2F-Y_Pad2.1x1mm`** — these could not take the bare KiCad stock name,
  because our copper differs from stock (drill/origin, and pad size). Rather than change working
  geometry and force a board re-route, the true measured value is recorded in the name, which is
  exactly what the standard prescribes when copper deviates. The relay also had a wildcard MPN
  (`G6K-2F-X-XX`) corrected to the real part, `G6K-2F-Y`.
