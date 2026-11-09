# Optiboot Mini handoff record

This is the 2026-10-31 generator source updated on 2026-11-08 for page-/erase-group-
aligned ATtiny Virtual Boot. The original handoff also referenced CURRENT/,
HISTORY/Archives/, and a technical timeline; those external historical archives
are not part of this smaller update. This repository imports the active source
as `optiboot/bootloaders/optiboot_mini/`. See its README and import manifest.

Start with README_GENERATOR.md, README_DUAL_EDITIONS.md, and
README_VIRTUAL_BOOT_SIZING.md. There is one assembly source, `optiboot_mini.S`,
with `devices.json`, device/UART includes, and edition builders. Use:

```sh
python3 generate_firmware.py atmega328p compact 16MHz
python3 generate_firmware.py atmega8 flash256 8MHz
python3 generate_firmware.py atmega2560 full 16MHz
python3 generate_firmware.py --list
```

User decisions preserved from the source handoff:

* The 13 ATmega with 1024-byte hardware minimum retain Full only.
* Other 21 ATmega offer 512-byte Compact and 1024-byte Full.
* Four ATtiny offer Virtual Compact/Middle (576 bytes on 84/85, 512 on
  841/1634) and Full 1024. They have no hardware BOOTSZ protection.
* Flash256 is independent for 13 ATmega with a 256-byte hardware minimum.
* FlashRead512 is a readback experiment (284–286-byte payload) on those 13.
* EEPROM read/write, Flash read/write, signatures, SPM ABI where applicable,
  WDT/MCUSR behavior, and Flash protection are priorities for Middle.
  GET_SIGN_ON is omitted there and supplied in Full with fuse/lock reads.

The 2026-10-31 handoff reported 115 generated artifacts: 63 paired editions,
plus 13 Flash256 and 13 FlashRead512 at each of 8 and 16 MHz. That historical
inventory predates the Virtual Boot update. Consult current validation for
new sizes and hashes. The research archives do not contain a verbatim chat
export; technical timelines reconstruct decisions and are not transcripts.

Compilation/model results do not establish physical AVR, actual AVRDUDE, or
Arduino IDE compatibility. Hardware tests with ISP recovery remain necessary.
