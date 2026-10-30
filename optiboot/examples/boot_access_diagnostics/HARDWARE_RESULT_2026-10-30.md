# Nano-compatible board: boot-access result, 2026-10-30

## Observed identity and protection

The device's physical signature, read by the diagnostic from the signature row,
is **`1E 95 16` (ATmega328PB)**. Its existing serial bootloader reports
`1E 95 0F` instead and communicates at 57600 baud. Its 1950 supplied firmware
bytes match Arduino's stock `ATmegaBOOT_168_atmega328.hex` at `0x7800..0x7F9D`.
Future ISP operations must select the actual 328PB device.

The diagnostic produced three identical complete reports. Within each report,
eight additional fuse/lock reads agreed with the first read.

| Field | Direct hardware value |
|---|---|
| Low fuse | `0xFF` |
| High fuse | `0xDA` |
| Extended fuse | `0xFD` |
| Raw lock byte | `0xCF` |
| Implemented lock bits (`raw & 0x3F`) | `0x0F` |
| Configured boot section | 2048 bytes, `0x7800..0x7FFF` |
| Reset target | Boot section |

`BLB12=0` blocks application reads of the boot section, and `BLB11=0` blocks
SPM writes to that section. `BLB02=1` and `BLB01=1` permit the existing boot
code to read and program application Flash. An SPM instruction executing from
the application section cannot program Flash regardless of those permissions.
Lock-bit programming also requires the appropriate boot-section SPM code;
software can tighten Boot Lock bits but cannot release their protection.

## Read-access check

CRC-16/CCITT-FALSE over the boot section, as visible to the application, was
`0xC584`. The trusted bootloader backup's corresponding CRC is `0x035E`.
`0xC584` is also the CRC of 2048 zero bytes, consistent with a blocked read.
The application therefore did not read the actual bootloader contents.

Write restrictions were decoded from the actual lock bits and the MCU's
hardware rules. No attempt was made to erase or program the boot section,
fuses or lock bits. A software-only bootloader replacement is blocked on this
board; release requires an external Chip Erase/programming path.

The old bootloader's `UNIVERSAL` fuse/lock responses were all `0x00`, including
values that directly read as `0xFF`, `0xDA`, `0xFD` and `0xCF`. Those serial
responses are dummy values and must not be interpreted as real protection.

## Procedure and restoration

Before uploading the diagnostic, all 32768 Flash bytes and 1024 EEPROM bytes
were backed up locally and independently verified against the board. The
temporary diagnostic was uploaded through the existing bootloader and its
written bytes were verified. The final standalone diagnostic occupies
1838 Flash bytes and contains no SPM instruction in executable sections.

The original application pages were restored in an obligatory cleanup step,
including on capture failure. Afterwards, verification against the original
backups passed for **all 32768 Flash bytes and all 1024 EEPROM bytes**.
The original bootloader remained installed. This tested the diagnostic, not
the new experimental Mini bootloader on physical hardware.

Backups and raw serial captures remain outside the tracked source tree and
are not part of this report or its Git commit. No board serial number or
application/EEPROM contents are included.

References: [ATmega328PB datasheet, sections 31 and 32](https://ww1.microchip.com/downloads/en/DeviceDoc/40001906C.pdf)
and [avr-libc fuse/lock reading](https://avrdudes.github.io/avr-libc/avr-libc-user-manual/group__avr__boot.html).
