# Experimental multi-device Optiboot Mini

Imported from the 2026-11-08 page-aligned Virtual Boot update. The active
generator supports Mini (`flash256`), Middle (`compact`), Full, and the separate
FlashRead512 research edition. All use this module's `optiboot_mini.S` and
per-device hardware includes.

This module coexists with the repository's hardened
[`optiboot_328p`](../optiboot_328p/README.md) implementation. They have different
protocol contracts: the older implementation supplies read-only fuse queries
inside 512 bytes and omits application SPM; Middle supplies the SPM ABI and
both signature commands while omitting fuse queries and GET_SIGN_ON. Choose
an edition explicitly; the existing upstream Makefile and ATmega328P targets
continue to build their existing sources.

## Build

From this directory, with Python 3.10+, AVR-enabled Clang/LLVM, `readelf`, and
`avr-ld` (binutils-avr) on PATH:

```sh
python3 generate_firmware.py attiny85 middle 8MHz
python3 generate_firmware.py atmega328p compact 16MHz
python3 generate_firmware.py atmega328p full 16MHz
python3 generate_firmware.py --list
python3 build_dual.py --all --jobs 6
```

Windows builds can run in WSL with those tools installed. The command launcher
also works with a suitable Windows toolchain. Imported builders resolve local
relocations emitted by LLVM 18/GNU as, at section origin zero and without
relaxation. The physical Flash origin remains encoded by the source/HEX writer.
The four ATtiny Middle images are also checked with AVR-GCC.

| Target | Middle payload | Virtual Boot reservation | Origin |
|---|---:|---:|---|
| ATtiny84/85 | 549 B | 576 B (9 x 64-byte pages) | `0x1DC0` |
| ATtiny841 | 505 B | 512 B (8 x 64-byte erase groups) | `0x1E00` |
| ATtiny1634 | 501 B | 512 B (4 x 128-byte erase groups) | `0x3E00` |

Middle tries the smallest complete erase-group reservation between 512 and
1024 bytes that fits. Full remains 1024. ATmega hardware BOOTSZ selection is
unchanged: 21 ATmega offer 512-byte Middle plus Full; 13 with a 1024-byte
hardware minimum offer Full only. Together with the four ATtiny, this gives
25 Middle and 38 Full profiles.

Read [Virtual Boot sizing](README_VIRTUAL_BOOT_SIZING.md) before preparing
ATtiny images: **use matching `--boot-bytes` in the ISP seed, application
vector patch, and uploader**. Those helper CLI defaults remain 1024 for older
installations. Changing the reserve requires ISP reinstallation and repatching.
ATtiny841/1634 must be written in complete erase groups, not single pages.

## Verify

```sh
python3 run_tests.py
# Equivalent convenience target:
make test
```

The runner builds the 63 active profiles with automatic signature selection
and a second matrix with constant signatures for the reset/SPM models. It then
runs firmware/model and generator suites. Release checks compare all 63 rebuilt
BINs and decoded HEX images with the supplied archive; `firmware/` retains those
original BIN/HEX bytes and portable metadata. Temporary outputs are ignored.
The existing ATmega328P implementation has its own independent test runner:

```sh
python3 ../../../scripts/atmega328p/run_tests.py --build
```

Run that existing runner from the repository root as
`python3 scripts/atmega328p/run_tests.py --build`.

Some imported research tests compare R3–R8 snapshots or old objects that the
downloaded ZIP did not include. They report explicit skips when those fixtures
are absent; current firmware, protocol, reset, SPM, and Virtual Boot checks
continue to run. Historical reports retain their original counts and are not
current validation evidence. See [import validation](VALIDATION_2026-11-09.md).

The images have not been validated on physical AVR, actual serial AVRDUDE, or
Arduino IDE. Software models do not prove oscillator/fuse behavior, power-loss
recovery, or hardware timing. Virtual Boot has no hardware boot protection;
applications can execute SPM directly. Initial installation/recovery uses ISP.

## Provenance and license

[IMPORT_MANIFEST.json](IMPORT_MANIFEST.json) records the source chat, ZIP
SHA-256, original source hashes, and repository paths. English translations
retain technical values and historical status. Original source assembly,
device/UART includes, and released firmware bytes are preserved. Compiler
drivers, test setup, and documentation are adapted for this repository.
The downloaded ZIP and omitted historical patches/objects remain local import
inputs rather than active builds. No earlier source tree is overwritten.

The source preserves attribution to Peter Knight, Bill Westfield, and Optiboot
contributors, under GPL-2.0-or-later; see [COPYING](COPYING).
