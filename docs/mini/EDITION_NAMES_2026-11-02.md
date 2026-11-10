# Edition naming update

Historical snapshot: the reservation sizes below describe the November 2 rename.
ATtiny Middle subsequently changed to 512/576 bytes; see the
[current integration record](INTEGRATION_2026-11-10.md) and [Virtual Boot guide](VIRTUAL_BOOT.md).

Date: 2026-11-02. Public edition names are now `mini`, `middle` and `full`.
This is a naming change from source revision
`91c85c2a6bb4e94223218381bdce45da5a6811ef`; firmware features, Boot geometry,
addresses and binary contents are preserved.

| Previous edition | Current edition | Reserved Boot area |
|---|---|---|
| `flashread256` | `mini` | 256 bytes on 14 eligible ATmega |
| `compact` | `middle` | 512 bytes on 22 ATmega; 1024 bytes on four Virtual ATtiny |
| `full` | `full` | 1024 bytes on all 39 profiles |

Old edition names and their existing CLI aliases remain accepted. They resolve
to the same canonical output directories and JSON edition values as the new
names. The paired builder and AVRDUDE verification runner accept the relevant
old names too. New Make targets are `mini_256`, `mini_middle` and `mini_full`;
the old `mini_flashread256` and `mini_compact` targets remain aliases. The legacy
Basic `make mini` target, internal architecture flags and source filenames are
preserved. Dated reports and JSON/CSV evidence retain their original names.

## Validation

All checks used software models; no board, serial port or ISP programmer was
accessed.

* All 441 clock/device/edition combinations built and passed executed smoke
  checks. Each resulting matrix row, including SHA-256, Boot address, footprint,
  padding and baud settings, matches the earlier
  [423-image matrix](UART_MATRIX_2026-11-01.csv) plus the
  [18 ATmega168PB images](ATMEGA168PB_MATRIX_2026-11-01.csv), after mapping names.
* All 126 instruction-model tests and 19 generator tests passed. Alias
  regressions cover canonical directories and metadata, unchanged image hashes,
  unsupported-device rejection, the paired builder and Make target equivalence.
* Real AVRDUDE 8.0-arduino.1 passed full application Flash transfers and normal
  verification on modeled ATmega168PB for all three editions, plus full EEPROM
  transfers for Middle/Full. Boot contents remained unchanged.
* The Arduino upload runner passed its four ATmega168PB cases: ordinary even-
  and odd-length HEX, optionally padded HEX, and rejection of the loader's own
  Boot HEX before any SPM instruction.

## Reproduce

Run from `optiboot/bootloaders/optiboot/`:

```sh
python3 generate_firmware.py atmega168pb mini 16MHz
python3 generate_firmware.py atmega168pb middle 16MHz
python3 generate_firmware.py atmega168pb full 16MHz
make mini_test
python3 verify_editions.py --all-clocks --smoke --output output/rename-validation
python3 verify_avrdude.py --mcu atmega168pb --avrdude /path/to/avrdude --config /path/to/avrdude.conf --output output/rename-avrdude
python3 verify_arduino.py --mcu atmega168pb --avrdude /path/to/avrdude --config /path/to/avrdude.conf --timeout 6 --output output/rename-arduino
```

For the matrix comparison, map `flashread256` to `mini` and `compact` to
`middle`, then compare rows using MCU, edition, frequency and clock source as
the key. No other column needs to be changed.
