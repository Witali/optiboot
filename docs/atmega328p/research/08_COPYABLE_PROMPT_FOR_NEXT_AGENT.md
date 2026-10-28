# Historical copyable development prompt

This is a translated handoff artifact, not an instruction to begin additional work
in the current session.

Continue engineering the compact Optiboot Mini bootloader for ATmega328P,
16 MHz, UART0 115200, a 512-byte boot section and an STK500v1 subset.
The current software-tested source and HEX are `CURRENT/optiboot_328_verified.S`
and `.hex` in the original layout: 510 code bytes plus two version bytes =
512/512 bytes. This is separate from Micronucleus Block64; keep MCU/protocol
assumptions separate.

Read `00_START_HERE.md`, `02_CHANGELOG_HISTORY.md`, `03_PROTOCOL_AND_HARDWARE.md`,
`CURRENT/AUDIT.md` and `04_TASKS_FOR_NEXT_AGENT.md` first. The handoff includes
earlier ZIPs, extra experiments, the Python AVR interpreter, tests, differences,
upstream images and SHA256 inventories. Repository paths are documented in
`../README.md` and `../IMPORT_MANIFEST.json`.

Established findings: Flash uses its hardware SPM buffer without an SRAM page
array and validates EOP before erase. EEPROM supports 1024-byte read/write with
1..16-byte writes staged on the stack and EOP checked before programming.
UNIVERSAL `0x56` provides only four fuse/lock reads. Watchdog values are
`0x0E/0x08`; UART FE0 handling is retained; Flash Page Write requires
128-byte alignment and `PCWORD=0`.

Historical defects: the initial 410-byte image has broken WDT configuration;
the 402-byte streaming image erases too early; the 508-byte image lacks the Page
Write Z-alignment check. The 512-byte image fixes that check. All tests use a
limited custom software interpreter; there has been no physical ATmega328P
test. AVR061 support is partial: CHIP_ERASE is ACK/no-op, GET_SIGN_ON is
ACK-only, high length bytes are ignored, and unknown memory types become Flash.
CRC_EOP is not a CRC. Do not use `avrdude -e` through this bootloader.

The proposed development task was to reduce size while preserving EEPROM,
Flash, fuse/lock reads and reliability, then use the freed space for high-length
validation and accurate unsupported-command responses. Rebuild and run all
tests after each firmware change, retain logs/hashes, compare shared semantics
with upstream, and establish hardware reliability through real-board tests with
ISP recovery before claiming it.
