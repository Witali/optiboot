# Historical R11 build and test results

This report predates both the 63-profile selection policy and the 2026-11-08
ATtiny reservation update. Its numbers describe the earlier experiment.

* 38 MCU x 2 editions = 76/76 builds; all 38 Compact BIN hashes matched R10
  with automatic signature selection. Twenty-nine payloads were at most 512
  bytes; remaining hardware/virtual reservations were 1024 bytes.
* All 38 Full images fit 1024 bytes; ATmega2560/2561 had the largest payload
  at 787 bytes. Builders compiled one source without binary patching/cloning.

| Suite | Result | Coverage |
|---|---:|---|
| test_dual_editions | 10/10 | 76 BINs, R10 hashes, signature, Flash/EEPROM, EOP, fuse/lock, SPM, 256 KiB banks, software UART |
| test_app_spm | 8/8 | Calling ABI and self-programming |
| test_r10_sigrow | 9/9 | SIGRD+LPM and RAMPZ bypass |
| test_tiny_virtual | 7/7 | Vector Boot, grouped erase, EEPROM |
| test_soft_uart | 11/11 | Bit-level timing model |
| test_128k | 8/8 | 128 KiB Flash/RAMPZ |
| test_compact_64k_fuse | 7/7 | 64 KiB EEPROM/fuse/lock/SPM |

The source recorded 60/60 tests across seven completed suites. Coverage was
software-only and did not exhaust every command/MCU combination.
Two historical suites did not complete: test_universal_signature_ide2 required
an obsolete default ATmega328P hash; test_all_mcusr_spm_parity required the older
`output/compat/matrix.json`, which paired builds do not generate. Those runs
were not counted as success or established functional regressions.

Checked commands included Compact synchronization, parameters, both signature
forms, Flash/EEPROM read/write; Full additionally supplied GET_SIGN_ON,
two-byte SET_PARAMETER, read-only fuse/lock, malformed packets and bad EOP.
SPM API on ATmega328P/644P, EEPROM boundaries across eight MCU, banked Flash,
and ATtiny software UART were exercised. ATtiny require patched vectors and
ISP seed; there is no hardware protection. Real AVRDUDE/Arduino IDE and
physical silicon were not tested.
