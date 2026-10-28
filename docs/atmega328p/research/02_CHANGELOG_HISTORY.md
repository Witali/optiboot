# Optiboot Mini firmware history

All stages below were researched on October 28, 2026. Paths refer to the original
handoff layout; consult `../IMPORT_MANIFEST.json` for repository destinations.
Occupied size means instruction bytes plus two version bytes, excluding `0xFF`
padding. Each stage's BIN/HEX usually covers the full 512-byte boot section.

| Stage | Occupied size / variants | Changes and findings | Original sources |
|---|---:|---|---|
| 0. Official Optiboot | 474 bytes (472+2) | `Optiboot/optiboot` reference `optiboot_atmega328.hex`, reported software 8.3. Includes LED indication and application-callable SPM, which were later omitted. | `OFFICIAL_REFERENCE/` |
| 1. Initial Mini | 410 bytes / streaming 402 bytes | STK500v1 subset, UART0 and Flash programming; SRAM-buffered writes in 410 bytes, streaming with early erase in 402 bytes. The 410-byte version had a critical WDT error: `0x06/0x00` instead of `0x0E/0x08`. The streaming version erases before EOP validation. | `HISTORY_SOURCES/01_initial_size_lab/` |
| 2. Upstream comparison | 368 bytes / 366 without RET | Fixed WDT, FE0, argument/EOP handling and compared machine-code behavior with upstream HEX. Receives directly into the hardware SPM buffer, validates EOP, erases, then writes; no 128-byte SRAM buffer. Compared 575 model transactions per variant. | `HISTORY_SOURCES/02_368_protocol_audit/`, `02b_all_machine_code_prototypes/` |
| 3. Further optimization | 358, 356, 350 bytes | Register reuse, T flag with BST/BRTC, LSR word-count validation, shared LEAVE/EOP handlers. The 350-byte variant assumes reset-state `UCSR0C` and is unsuitable for arbitrary application entry. | `HISTORY_SOURCES/03_358_350_size_optimization/` |
| 4. STK500v1 extensions | 480, 511 bytes | Diagnostic EEPROM READ, UNIVERSAL fuse/lock/signature reads and correct SET_PARAMETER consumption. The 511-byte image adds GET_SIGN_ON. No EEPROM WRITE; these remained research variants. | `HISTORY_SOURCES/04_480_511_diagnostic_variants/` |
| 5. Useful avrdude commands | Prototypes | Prioritized memory type E in PROG_PAGE/READ_PAGE, then UNIVERSAL, over sign-on/legacy commands. Studied `stk500.c` and classic AVR word-based EEPROM addressing with `-c arduino`. | `HISTORY_SOURCES/04b_command_selection_prototypes/` |
| 6. EEPROM R/W | 498 bytes (496+2) | Reads/writes all 1024 EEPROM bytes. Receives 1..16-byte write packets into a 16-byte SRAM buffer, checks EOP before writes, checks ranges and waits for EEPE/SPM. Flash still needs no separate SRAM page buffer. | `HISTORY_SOURCES/05_498_eeprom_read_write/` |
| 7. EEPROM + UNIVERSAL | 508 bytes (506+2) | Replaced the EEPROM array with up to 16 PUSH/POP operations and backward-address writes. Added read-only low/high/extended fuse and lock queries. Model tests included 598 base and 556 upstream-comparison transactions. | `HISTORY_SOURCES/06_508_eeprom_universal/` |
| 8. Datasheet audit, current | 512 bytes (510+2) | Found the SPM Page Write `PCWORD=0` requirement. Added 128-byte Flash start alignment validation, removed the old RET stub, rebuilt within 512 bytes and passed the tests. | `CURRENT/`, `HISTORY_SOURCES/07_512_datasheet_audit/` |

## Findings to retain in later versions

1. Watchdog: do not program the initial 410-byte version. For ordinary WDTON
   configuration, use `0x0E` for the one-second timeout and `0x08` for the short
   watchdog exit after LEAVE.
2. Flash: fill the temporary hardware buffer, validate `CRC_EOP`, erase, write,
   then enable RWW. Erase must follow EOP validation. Check 128-byte alignment
   before Page Write to ensure `PCWORD=0`.
3. EEPROM: receive 1..16 bytes, validate EOP and range, then write. Observe
   `EECR.EEMPE` to `EEPE` timing, wait for `EEPE=0` and coordinate with SPM.
4. Stack: EEPROM temporarily uses the stack. Check SP initialization after reset,
   nested RCALL/RET use, and interaction with interrupts, which remain disabled.
5. UART: 16 MHz, U2X0=1 and UBRR0L=16 produce about 117647 baud (+2.12%). FE0
   affects watchdog servicing; the physical link has not been tested.
6. `CRC_EOP=0x20` is a terminator, not a checksum. Image integrity requires a
   subsequent readback and verify.
7. The official 474-byte image has different features: it includes LED startup
   and application-callable SPM. The size difference does not isolate assembly
   optimization at feature parity. A feature-matched upstream build was not made
   during the original research.

## Supporting records

See stage READMEs and `.patch`/`.diff` files. `CROSS_STAGE_DIFFS/` contains
line-by-line differences between canonical stage sources; substantial structural
changes mean these are not complete semantic change reviews.
