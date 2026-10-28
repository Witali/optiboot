# Optiboot Mini ATmega328P: complete research handoff

**Snapshot date:** October 28, 2026.  
**Project:** separate from Micronucleus Block64; its protocols, sources and limits
must not be mixed with this project.  
**Languages:** English documentation, AVR Assembly, Python 3.

This is a translated research record. Paths such as `CURRENT/` describe the
original handoff layout; see `../README.md` and `../IMPORT_MANIFEST.json` for the
repository layout and current commands.

## Where to start

1. Current experimental source: `CURRENT/optiboot_328_verified.S`.
2. Firmware: `CURRENT/optiboot_328_verified.hex`, addressed to `0x7E00..0x7FFF`.
   The corresponding `.bin` contains exactly 512 bytes without address metadata.
3. Main hardware/protocol audit: `CURRENT/AUDIT.md`; review it before optimizing.
4. Reproduction: `RUN_CURRENT_TESTS.sh`, `01_REPRODUCE.md`, `CURRENT/build.py`
   and `CURRENT/test_*.py`.
5. Version history: `02_CHANGELOG_HISTORY.md` and `HISTORY_SOURCES/`.
6. Open issues: `04_TASKS_FOR_NEXT_AGENT.md`; protocol limits:
   `03_PROTOCOL_AND_HARDWARE.md`.
7. Earlier stage ZIPs: `ORIGINAL_STAGE_ARCHIVES/` (seven archives). Intermediate
   sources and logs are also in `HISTORY_SOURCES/`. In this repository the
   documentation inside those ZIPs has been translated into English; the exact
   original ZIPs remain available in the initial import commit `db107e2`.

## Last confirmed research status

- Target: ATmega328P / Arduino Uno, 16 MHz, hardware UART0 at 115200,
  an STK500v1-compatible subset and a 512-byte boot section.
- Latest image: 510 instruction bytes plus two version bytes = 512/512 bytes,
  with no free space. Boot starts at `0x7E00`; version `03 08` is at
  `0x7FFE..0x7FFF`.
- Features: Flash page read/write using the hardware SPM buffer without a
  128-byte SRAM page buffer; 1024-byte EEPROM read/write, with 1..16-byte write
  packets temporarily held on the stack; selected read-only fuse/lock queries
  through `UNIVERSAL (0x56)`.
- WDT and UART FE0 behavior were restored. Flash Page Write now checks
  128-byte start-address alignment.
- Tests used only a limited custom AVR software interpreter. No physical
  ATmega328P board was available. On October 28 the source was rebuilt, HEX/BIN
  hashes matched the saved images, and the tests were rerun. See
  `TEST_RECHECK_2026-10-28.txt`.
- This is not full AVR061/STK500v1 compliance. For example, `CHIP_ERASE` can be
  acknowledged without erasing, `GET_SIGN_ON` returns only ACK, and the high
  length byte is ignored. Do not use `avrdude -e` or fuse/lock programming
  through this bootloader.
- Use a spare board with ISP recovery, backups and separately checked fuses
  for the first physical test.

## Contents

| Subject | Original handoff location |
|---|---|
| User requirements history | `05_USER_REQUEST_HISTORY.md` |
| Chronology and fixes | `02_CHANGELOG_HISTORY.md` |
| Commands and incompatibilities | `03_PROTOCOL_AND_HARDWARE.md` |
| Proposed next development cycle | `04_TASKS_FOR_NEXT_AGENT.md` |
| Build/test commands | `01_REPRODUCE.md` |
| Physical test plan | `06_HARDWARE_TEST_PLAN.md` |
| Sources and license | `07_SOURCES_LICENSE.md` |
| Original inventories | `FILE_INVENTORY.csv`, `MANIFEST_SHA256.json`, `SHA256SUMS.txt` |
| Earlier stage archives | `ORIGINAL_STAGE_ARCHIVES/` |
| Stage differences | `CROSS_STAGE_DIFFS/` and `.diff`/`.patch` in `HISTORY_SOURCES/` |

This is research firmware. Compilation and model tests do not establish correct
operation on physical silicon or a real USB/UART link.
