# Contributing to Optiboot Mini

Keep Mini an optional assembly target alongside the stock C implementation.
Preserve the existing repository layout and board targets. Write Mini code,
comments, documentation, messages and test descriptions in English.

## Compatibility and regression checks

1. Preserve the hardware-UART ATmega `avrdude -c arduino` interface and documented
   Flash page semantics. ATtiny Virtual Boot has a separate uploader and vector
   contract; do not imply interchangeable host support.
2. Retain each edition's documented features, watchdog handling, EEPROM/SPM
   interlocks and address/boot-boundary checks. Mini must retain Flash
   readback; do not restore the removed write-only edition. Middle includes
   EEPROM and application SPM on hardware-Boot ATmega; Full adds sign-on,
   SET_PARAMETER and read-only fuse/lock `UNIVERSAL` operations.
3. Keep Middle ATmega328P within its 512-byte boot section at `0x7E00..0x7FFF`,
   Full within 1024 bytes, and Mini within 256 physical bytes on every
   eligible device. Respect each MCU's physical boot-section minimum.
4. Review signature, register map, Flash/EEPROM geometry, reset behavior and
   datasheet clock limits before adding a device profile. Regenerate the device
   includes with `python3 gen_devices.py` when changing its profile inputs.
5. Compare BIN/HEX addresses, size and SHA-256 after assembly changes. Explain
   intentional changes to a reference image rather than silently replacing the
   baseline hash. The fixed `mini328` target is a separate regression reference.
6. Keep build, instruction-model and physical test evidence distinct. A passing
   software model does not qualify UART timing, silicon errata or power loss.

## Minimum checks

Run from `optiboot/bootloaders/optiboot/`, with the toolchain described in
[README_MINI_MULTI.md](README_MINI_MULTI.md):

```sh
make mini328_check
python3 build_mini.py --verify-baseline
make mini_test
make mini_matrix
```

`mini_test` runs both `mini_tests/` and `generator_tests/`, building test images
in temporary directories without an external handoff archive. The matrix runner
builds all public edition/device/clock cases and exercises the exact binaries.
`mini_tests/fixtures/` holds earlier images, symbol objects and expected hashes
for response-equivalence and reference regressions. See the
[current validation report](../../../docs/mini/UART_VALIDATION_2026-11-01.md)
for the actual AVRDUDE loopback runner and software/hardware scope.

For changes to shared Makefile integration, also build the stock `atmega328`
target and compare its output with an unmodified checkout using the same
toolchain and options.

## Hardware evidence and documentation

The [ATmega328PB report](../../../docs/mini/HARDWARE_ATMEGA328PB_2026-10-30.md)
records 42 successful physical checks on one Nano at 16 MHz / 115200 baud.
The [reproduction guide](../../../scripts/hardware/nano_usb/README.md) provides
the runner, probes, backups and restoration procedure for that exact build.
That evidence applies only to the older image hash in the report. The new
editions still need hardware validation. Keep board memory backups and raw
captures local; they are not test fixtures for publication.

When changing a protocol operation, document its packet/response format,
address units, host command, bounds and failure behavior. Update
[README_MINI328_AVRDUDE.md](README_MINI328_AVRDUDE.md) for the fixed 328P
reference, [README_MINI_MULTI.md](README_MINI_MULTI.md) for the current target,
and the [feature comparison](../../../docs/mini/FEATURES.md) when claims change.
Record exact clock, baud, boot layout, image hash and test method for new
hardware evidence.
