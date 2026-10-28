# Optiboot Mini ATmega328P: EEPROM read/write

October 28, 2026. Historical experimental firmware without physical validation.
For the current image and relocated repository tools, see `../../README.md`.

## Result

- 496 instruction bytes plus two version bytes = 498 occupied bytes.
- Full image: 512 bytes at `0x7E00..0x7FFF`; 14 unused bytes are FF.
- Earlier Flash-only Mini: 358 bytes including version.
- ATmega328P / Uno, 16 MHz, UART0 115200 8N1.
- Flash still uses the temporary hardware SPM buffer without an SRAM page array.
- EEPROM adds READ_PAGE/PROG_PAGE memory type E (`0x45`). Writes accept 1..16
  bytes staged in a 16-byte SRAM array at `0x0100`; reads accept 1..256 bytes,
  with low length zero meaning 256.
- Normal classic-AVR avrdude `-c arduino` sends 16-byte EEPROM blocks without
  host changes. EEPROM reads need no staging array; the working AVR stack is
  separate.
- Checks enforce EEPROM addresses 0..1023, including packet end/length overflow.
- GET_PARAMETER, SET_DEVICE/EXT, LOAD_ADDRESS, UNIVERSAL (zero-result stub),
  Flash PROG_PAGE/READ_PAGE, READ_SIGN and LEAVE remain. SET_PARAMETER now consumes
  two bytes correctly without changing settings.
- LED flashes, fuse/lock programming and application-callable SPM are absent.

## STK500v1 packets

LOAD_ADDRESS: `55 low_word_address high_word_address 20` returns `14 10`.
For ATmega328P with `-c arduino`, the address is in words even for EEPROM.
EEPROM byte address `0x0200` therefore uses word address `0x0100`, packet
`55 00 01 20`. The loader multiplies by two for both memories. A standalone odd
EEPROM start is unavailable, but 16-byte blocks include odd-addressed bytes.

- EEPROM write: `64 00 10 45 <16 data bytes> 20`, response `14 10`.
- EEPROM read: `74 00 10 45 20`, response `14 <16 data bytes> 10`.
- Flash uses type F (`0x46`) in the same commands.

CRC_EOP `0x20` is a terminator, not a checksum. Use avrdude readback/verify to
detect silent payload corruption.

## EEPROM write sequence

1. Check length 1..16, start address and last address no greater than 1023.
2. Receive all bytes into SRAM `0x0100..0x010F`.
3. Validate trailing CRC_EOP `0x20`.
4. Wait for Flash SELFPRGEN/SPMEN, then EEPE before each byte. Select atomic
   erase-and-write mode EEPM1=EEPM0=0.
5. Execute SBI EECR,EEMPE followed by SBI EECR,EEPE within the four-clock window.
6. Wait for the final write before STK_OK.

Missing/bad EOP leaves EEPROM unchanged and triggers watchdog reset. Power loss
after a valid packet can still leave a partially programmed block: the packet
is not a power-failure-atomic transaction. Existing bytes are not compared with
new values, so repeated writes contribute to wear.

## Original files and build

- `optiboot_328_eeprom_rw.S`: complete assembly.
- Matching HEX: ISP-addressed `0x7E00..0x7FFF`; BIN: 512 bytes including FF.
- `build.py`: Clang AVR, llvm-objcopy, llvm-objdump and readelf build/checks.
- `avr_base_sim.py`, `test_eeprom.py`: limited instruction/peripheral model.
- `optiboot_mini328_358.bin`: earlier image for differential Flash/STK500 checks.
- `upstream_reference.bin`: supplied official Optiboot reference.
- `eeprom_test16.bin`: sample that changes EEPROM addresses 0..15 when written.
- `test_output.txt`: model-test results.
- COPYING: GPL-2.0-or-later derivative of https://github.com/Optiboot/optiboot.

```sh
python3 build.py optiboot_328_eeprom_rw
python3 test_eeprom.py
```

The build checks relocations, at most 510 instruction bytes, the two version
bytes, 512-byte BIN length and HEX addresses. The tests execute assembled
instructions rather than modeling analog UART or physical EEPROM/Flash durations.

## Proposed real-board checks

Install/recover through ISP. Check the `0x7E00` 512-byte boot section, BOOTRST
and 16 MHz clock; typical Uno high fuse `0xDE` is not a substitute for checking
the actual board configuration. After ISP installation and USB/UART DTR/RESET
connection, the recorded example was:

```sh
# Back up EEPROM first; replace the port for the actual board.
avrdude -p m328p -c arduino -P /dev/ttyUSB0 -b 115200 -U eeprom:r:backup_eeprom.bin:r
# Changes addresses 0..15 on a spare/backed-up device.
avrdude -p m328p -c arduino -P /dev/ttyUSB0 -b 115200 -U eeprom:w:eeprom_test16.bin:r -U eeprom:v:eeprom_test16.bin:r
# Read back the complete EEPROM.
avrdude -p m328p -c arduino -P /dev/ttyUSB0 -b 115200 -U eeprom:r:readback_eeprom.bin:r
```

Do not write this HEX into the application at zero. Preserve ISP access and
do not overwrite valuable EEPROM with the example without a backup.

## Checks and limits

598 valid transactions plus negative cases passed: 64 writes of 16 bytes and
full 1024-byte readback, 15 short blocks, 256-byte reads, Flash regression and
268 differential transactions against the 358-byte image. Bad EOP, truncated
packets, EEPROM overrun and invalid lengths produced no model EEPROM writes.
No actual ATmega328P/avrdude test was performed; physical EEPROM, watchdog,
UART and SPM timing remain unverified.

EEPROM sequencing was studied in the Atmel/Microchip ATmega328P datasheet
(EECR, EEMPE/EEPE, SPM waiting and EEPM); host block/address handling was examined
in avrdude `src/stk500.c`.
