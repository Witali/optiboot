# Experimental ATmega328P firmware

This branch imports the Optiboot ATmega328P research handoff dated 2026-10-28.
The AVR assembly firmware was optimized with the assistance of artificial
intelligence. The research combines size optimization with additional EEPROM
and diagnostic functions while retaining a 512-byte boot section.

## Features and target

The current source is
[`optiboot_328_verified.S`](../../optiboot/bootloaders/optiboot_328p/optiboot_328_verified.S).
It targets ATmega328P, a 16 MHz clock, and UART0 at nominal 115200 baud, 8N1.
The image occupies `0x7E00..0x7FFF`: 510 instruction bytes and two version bytes
(`03 08`), with no spare space in the boot section.

Compared with earlier size-focused prototypes in this research, the functional
additions are EEPROM read/write and read-only fuse/lock queries. Their limits
and the Flash memory optimization are described below.

| Function | Implementation and limits |
|---|---|
| Flash programming and reading | STK500v1 `PROG_PAGE`/`READ_PAGE`; programming fills the hardware SPM page buffer without a separate 128-byte SRAM array. Writes accept 2..128 bytes, an even length, and a 128-byte-aligned start address. |
| EEPROM writing | `PROG_PAGE` with memory type `E`; 1..16 bytes per packet across the 1024-byte EEPROM. Data is staged on the AVR stack, the terminator and range are checked before writing, and completion waits for the EEPROM controller. |
| EEPROM reading | `READ_PAGE` with memory type `E`; range-checked access to addresses 0..1023. Read length uses the low byte; zero represents 256 bytes. |
| Fuse/lock diagnostics | Read-only `UNIVERSAL` requests return low, high and extended fuses and lock bits. Fuse/lock programming and arbitrary ISP commands are not implemented. |
| Input and Flash write checks | Rejects unaligned Flash writes before SPM, rejects invalid EEPROM ranges and write lengths, and checks end-of-packet before modifying memory. Watchdog reset handles protocol aborts; UART framing-error handling is retained. |

The assembly retains serial synchronization, parameter responses, device-setting
packet consumption, address loading, the fixed ATmega328P signature, and
watchdog-based application entry. LED startup flashes and an application-callable
SPM service are omitted in this implementation.

Optimization here means fitting the enhanced feature set into 512 bytes. The
current enhanced image is larger than some earlier minimal variants; the
[research changelog](research/02_CHANGELOG_HISTORY.md) records those tradeoffs.

## Validation and protocol limits

The supplied tests execute the assembled machine code in a limited Python AVR
interpreter. They cover EEPROM round trips and negative cases, fuse/lock reads,
Flash regression, 556 differential STK500v1 transactions against the supplied
upstream reference, and instruction-adjacency/alignment checks. They do not
provide cycle-accurate or physical-hardware validation. No test on a real
ATmega328P or real USB/UART link was performed for the handoff or this import.
The [import validation record](VALIDATION_2026-10-28.md) documents the successful
rebuild, byte-for-byte BIN/HEX comparison, and rerun of all five current suites.

This firmware implements a subset of STK500v1, not full AVR061. `GET_SIGN_ON`
returns only an acknowledgement; chip erase is acknowledged without erasing;
the high length byte is ignored; and an unknown memory type falls back to
Flash. Do not use `avrdude -e` or attempt fuse/lock writes through this bootloader.
See the [full translated audit](current/AUDIT.md),
[protocol description](research/03_PROTOCOL_AND_HARDWARE.md), and
[hardware test plan](research/06_HARDWARE_TEST_PLAN.md).

## Build and test

From the repository root, Python 3.10 or newer can run all five current suites
against the supplied binary without downloading dependencies:

```sh
python scripts/atmega328p/run_tests.py
```

To rebuild and test the resulting binary, install `clang` with an AVR backend,
`llvm-objcopy`, `llvm-objdump`, and `readelf` on `PATH`, then run:

```sh
python scripts/atmega328p/run_tests.py --build
```

LLVM versions such as LLVM 18 leave local branch relocations in the object.
For those versions, `avr-ld` (from `binutils-avr`) must also be on `PATH`.
The build resolves relocations without relaxation and checks the final image.

Alternatively, `bash scripts/atmega328p/RUN_CURRENT_TESTS.sh` rebuilds and runs the
same suites; set `PYTHON` if the interpreter is named differently from `python3`.
The bootloader directory also provides `make`, `make check` (supplied image),
and `make test` (rebuild and test), consistent with the repository's Makefiles.
On Windows, the build commands can run inside WSL when its Linux environment
provides the tools listed above.
The build writes `.o`, `.bin`, and `.hex` into
`optiboot/bootloaders/optiboot_328p/build/`, which Git ignores. Tests select the
rebuilt binary automatically with `--build`; `--firmware PATH` selects a specific
512-byte binary. The committed images and object files are preserved research
artifacts, not the build output directory.

## Repository layout and provenance

| Location | Contents |
|---|---|
| `optiboot/bootloaders/optiboot_328p/` | Current assembly, supplied firmware and reference images, license, and historical assembly/binary snapshots. |
| `scripts/atmega328p/` | Current build, simulator, regression suites and test runner; historical tools are in `history/`. |
| `docs/atmega328p/research/` | English translations of the handoff documents, requirements history, task lists, and recorded test recheck. |
| `docs/atmega328p/current/` | Current audit, change diff, original build/test logs and checksums. |
| `docs/atmega328p/history/` and `diffs/` | Stage documentation, original manifests and logs, and cross-stage patches. |
| `docs/atmega328p/archives/` | English editions of all seven stage ZIPs, refreshed internal checksums, and a manifest recording original/current hashes. |
| `docs/atmega328p/manifests/` | Original archive-wide inventories and checksum lists, unchanged. |

All 266 files from the handoff are accounted for by
[`IMPORT_MANIFEST.json`](IMPORT_MANIFEST.json). It records each original path,
its repository destination, and original/current SHA256 values. Assembly,
firmware, objects and licenses are byte-for-byte preserved. Research documentation
has been translated into English, including copies inside stage ZIPs; filenames,
references and internal archive checksums have been updated. The exact original
handoff documents and ZIPs remain available in the initial import commit
[`db107e2`](https://github.com/Witali/optiboot/commit/db107e21b11ea79675637d330a499c2f02d0973a).
Python and shell paths were adapted to the repository layout; the current build
also supports the AVR linker when required, uses a separate output directory,
and the current tests accept a selected
binary. Archived documents and their checksums describe the original ZIP layout;
use this page and the import manifest for current paths and commands. Historical
task lists and copyable agent prompts are records of the research, not current
development instructions. Stage snapshots can also be inspected in the English
ZIP editions; source code, firmware and test programs inside those editions
retain their original bytes.

The assembly states GPL-2.0-or-later and preserves the Optiboot attribution to
Peter Knight, Bill Westfield and contributors. See the
[included COPYING](../../optiboot/bootloaders/optiboot_328p/COPYING) and
[translated sources/license notes](research/07_SOURCES_LICENSE.md). The fork's
existing [LICENSE](../../LICENSE) remains the upstream project license.
