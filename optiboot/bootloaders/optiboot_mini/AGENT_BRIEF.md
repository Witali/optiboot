
## Unified parameter-driven build (2026-10-31)

Use `python generate_firmware.py <mcu> <compact|full|flash256|flashread512> <frequency>` (e.g., `atmega328p compact 16MHz`). See README_GENERATOR.md. The wrapper validates the MCU/edition policy, frequencies, flash geometry, Intel HEX vs BIN and SHA256; it calls the existing builders, leaving optiboot_mini.S untouched. The legacy ATmega64A Full byte-addressed EEPROM profile is explicitly disabled in the wrapper because its current assembler layout fails a BRxx range check.

# Optiboot Mini: continuation brief for another coding agent

Project snapshot: 2026-10-31, updated 2026-11-08. The original handoff called
the active source CURRENT/. In this repository it is this module directory;
the external HISTORY/ archives mentioned below are not included in this update.
All firmware editions compile from one `optiboot_mini.S` assembly source.
Do not break STK500v1/AVRDUDE, Flash read/write, EEPROM read/write, MCUSR/
watchdog, Boot protection, or app-callable SPM ABI (when present).

**New user decision:** Drop Compact from every MCU with a *hardware minimum*
Boot size of 1024 bytes: ATmega64A, 640, 644/644A/644P/644PA,
128A, 1280/1281, 1284/1284P, 2560/2561. These retain FULL only.
Other 21 ATmega have Compact+Full; 4 experimental Virtual-Boot ATtiny
retain both (not hardware 1024 Boot devices).
Active dual matrix is **25 Compact + 38 Full = 63**.

Flash256 (13 classic ATmega with 256-byte hardware Boot): original write-only,
requires padded full-page HEX and AVRDUDE `-c arduino -D -V`.
FlashRead512: read-back research edition needs 512-byte Boot, not 256;
verification uses `STK_READ_PAGE`, but programming still full-page-only.
The target 256-byte read-back version remains unsolved (need ~28–30 B).

COMPACT: GET_SIGN_ON omitted by user decision (not required to identify MCU
in AVRDUDE); signatures through READ_SIGN or UNIVERSAL, SIGRD+LPM for validated
MCUs and constants otherwise, EEPROM read/write required. FULL 1024 adds real
fuse/lock reads (NOT writes), SET_PARAMETER and GET_SIGN_ON.
Default ATmega328P 16MHz external crystal 115200 baud; other F_CPU values
must respect each silicon's rating and UART error.

**Never assume hardware validation**: these remain simulator/build-verified only.
Check true BOOTSZ and BOOTRST settings, SPM timing, RWW handling, watchdog,
EEPROM persistence, signature-row access and fuse/lock behavior on real silicon.
UPDATE 2026-11-08: Compact/Middle Virtual Boot size is the smallest whole Flash erase-group reserve >=512B fitting the code (ATtiny84/85 576B; ATtiny841/1634 512B); Full is still 1024B. See README_VIRTUAL_BOOT_SIZING.md. For ATtiny Virtual Boot require seed ISP and vector patching; there is no
hardware-protected boot block.

Build and test commands, live artifacts, and SHA matrices live in CURRENT/.
Original archives, earlier source versions and failure analyses are stored
unaltered in HISTORY/Archives/. Read HISTORY_TIMELINE_RU.md and
VALIDATION/ for actual test results. Historical ZIPs are not shipped builds.

The literal message-by-message chat transcript is **not** included; a factual
technical timeline is supplied instead.
