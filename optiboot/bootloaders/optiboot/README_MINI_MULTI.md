# Optiboot Mini: editions and builds

Optiboot Mini is an experimental assembly alternative alongside the original
Optiboot C implementation. The original directory layout, C sources, board
targets and stock HEX files are preserved. The current public generator offers
three editions from `optiboot_mini.S` and its device/UART includes.

| Edition | Reserved Boot area | Profiles | Flash read/write | EEPROM read/write | Fuse/lock reads, sign-on | Application SPM ABI |
|---|---:|---:|---|---|---|---|
| `mini` | 256 B | 14 ATmega | Yes; aligned full-page writes | No | No | No |
| `middle` | 512 B on 22 ATmega; 1024 B Virtual Boot on four ATtiny | 26 | Yes | Yes | No | Yes on ATmega |
| `full` | 1024 B | All 39 | Yes | Yes | Yes | Yes on 35 ATmega |

The canonical edition names are `mini`, `middle` and `full`. The previous
`flashread256` and `compact` names (including their existing aliases) remain
accepted for reproducible older commands. New output directories and edition
metadata always use the canonical names. This rename does not change firmware
bytes, Boot geometry or features. Dated validation records retain their names.
See the [rename validation](../../../docs/mini/EDITION_NAMES_2026-11-02.md).

The write-only 256-byte edition is removed. The former oversized readback
prototype is replaced by a real 256-byte image. At 16 MHz / 115200 baud its
code and three signature bytes occupy 249..255 bytes on all 14 supported
parts; the remaining bytes are `0xFF` padding. ATmega328P/PB have a physical
512-byte minimum and cannot use this edition.

See the [feature comparison](../../../docs/mini/FEATURES.md),
[software validation report](../../../docs/mini/UART_VALIDATION_2026-11-01.md)
and [ATtiny workflow](../../../docs/mini/VIRTUAL_BOOT.md). The older
[ATmega328PB hardware report](../../../docs/mini/HARDWARE_ATMEGA328PB_2026-10-30.md)
applies to its recorded SHA-256 only, not these new editions.

The [ATmega168PB addendum](../../../docs/mini/ATMEGA168PB_2026-11-01.md)
extends the earlier 38-device results with the 39th device and its three editions.

## Build and select an edition

Run from `optiboot/bootloaders/optiboot/` with Python 3.10 or later,
Clang/LLVM AVR support or AVR-GCC, `avr-objcopy`/`llvm-objcopy`, `readelf`,
`llvm-objdump` and `avr-ld`. Assemblers that emit local relocations are linked
at section address zero without relaxation; Intel HEX provides the physical
Boot address. The tests were run in Ubuntu under WSL; a native Windows launcher
`generate_firmware.cmd` forwards arguments to Python, but it does not install
an AVR toolchain.

Older GCC packages without ATmega324PB specs use the same-ISA 324PA assembler
target while explicitly selecting the correct project 324PB register map and
signature; the manifest records `assembler_mcu`. PB application C code still
requires suitable device headers. The SPM header probes can supply reviewed
Flash geometry explicitly when the installed old avr-libc lacks PB headers.

```sh
python3 generate_firmware.py --list
python3 generate_firmware.py atmega8 mini 16MHz
python3 generate_firmware.py atmega168p mini 8MHz
python3 generate_firmware.py atmega168pb mini 16MHz
python3 generate_firmware.py atmega168pb middle 16MHz
python3 generate_firmware.py atmega168pb full 16MHz
python3 generate_firmware.py atmega328pb middle 16MHz
python3 generate_firmware.py atmega328pb full 16MHz
python3 generate_firmware.py atmega2560 full 16MHz
python3 generate_firmware.py attiny85 middle 8MHz
python3 generate_firmware.py attiny1634 full 12MHz
make mini_256 MINI_MCU=atmega16 F_CPU=16000000
make mini_middle MINI_MCU=atmega328pb
make mini_full MINI_MCU=atmega2560
```

The legacy `make mini` target still builds Basic. Use `mini_256`, `mini_middle`
or `mini_full` for the three public editions; `mini_flashread256` and
`mini_compact` remain Make target aliases.

Supply the actual CPU frequency, including clock dividers. The generator checks
part limits, clock-source constraints, nominal baud error, Boot geometry,
BIN/HEX agreement and hash. It writes files below `generated/` in directories
that identify the MCU, frequency, clock source, baud, signature mode and
edition. `build_info.json` records the exact paths and settings. A build does
not program a board or change fuses.

Automatic baud selection depends on frequency and clock source. In particular,
Mini uses 38400 at 8 MHz and 115200 at 16 MHz; an explicit `--baud`
may select another valid divider. Software UART uses 19200 for the default
8 MHz internal RC clock and faster nominal rates for external clocks.
Internal RC accuracy still requires physical validation and calibration.

## Device availability

| MCU group | Mini | Middle | Full |
|---|---|---|---|
| ATmega8, 8A, 8515, 8535, 16, 162, 164A/P/PA, 168/P/PB, 88/P | 256 B | 512 B | 1024 B |
| ATmega328, 328P, 328PB, 32A, 324A/P/PA/PB | Unavailable | 512 B | 1024 B |
| ATmega64A, 640, 644/A/P/PA, 128A, 1280, 1281, 1284/P, 2560, 2561 | Unavailable | Unavailable: hardware minimum 1024 B | 1024 B |
| ATtiny84, 85, 841, 1634 | Unavailable | 1024 B Virtual Boot | 1024 B Virtual Boot |

This is 79 edition/device profiles. ATtiny1634 is limited to 12 MHz in these
profiles; the others have individual ratings in `devices.json`. The generator
refuses unsupported combinations instead of labelling a 1024-byte hardware
Boot area as 256 or 512 bytes. ATmega2560/2561 use extended Flash banks;
EEPROM addressing remains independent of the Flash bank latch.

## Upload contract

For hardware-Boot ATmega, use the exact AVRDUDE part, `-c arduino`, the build's
baud, and `-D`. Keep normal verification enabled. The `arduino` programmer
uses word-addressed EEPROM in this protocol; another STK500 programmer setting
can have different EEPROM address units.

Mini accepts aligned, complete physical pages (64 or 128 bytes).
Readback accepts lengths 1..PAGE from a page-aligned address. The audited
Arduino AVR Boards 1.8.8 / AVRDUDE 8.0-arduino.1 upload path automatically
transfers full pages even when the ordinary HEX ends inside a page. Manual
padding is not required for that tested path. For another host that sends
short write packets, the optional preparation tool pads each touched page:

```sh
python3 flashread/prepare_avrdude_hex.py --mcu atmega8 --input app.hex --output app_full_pages.hex
avrdude -p m8 -c arduino -P PORT -b 115200 -D -U flash:w:app_full_pages.hex:i
```

Replace `PORT`, the part and baud for the actual board. This command writes
application Flash, not the bootloader. The preparation tool only creates a
file; it does not open a serial port. Standard Nano ATmega168 board settings
use 19200 baud; build with `--baud 19200` to match them, or use a board definition
with the baud recorded in the firmware manifest. The default 16 MHz image uses
115200. The 256-byte edition supports sync,
parameter queries (constant value 3), SET_DEVICE/SET_DEVICE_EXT framing,
enter/leave, LOAD_ADDRESS, READ_SIGN, Flash PROG_PAGE and READ_PAGE. It has no
EEPROM protocol, UNIVERSAL, sign-on string, application SPM service or fuse
writes. Chip Erase is acknowledged without erasing memory, as in an Optiboot
upload with `-D`. Unsupported odd commands can request the short watchdog
exit; they do not perform an ISP operation.

Mini requires entry through hardware reset: it relies on reset UART
format/divisor-high state and disabled interrupts. It immediately configures
the watchdog, enters the application after watchdog reset, and uses the
watchdog for inactivity/error exit. Its receive path retains framing-error
handling. It waits for an outstanding EEPROM write before every SPM command,
including buffer fill. Erase/write occurs only after valid packet termination.
Boot reads/writes, invalid lengths, alignment errors and address overflow are
rejected. A malformed request normally stops replies until watchdog reset.

The running 256-byte loader cannot install or replace itself over UART. Every
page in its own Boot area is rejected before any SPM command, including buffer
fill. Arduino's Burn Bootloader action is a separate programmer/fuse workflow;
use ISP for initial installation or replacement of this image. No lock bits or
fuses were inspected or modified in the software audit. See the
[Arduino protocol audit](../../../docs/mini/ARDUINO_PROTOCOL_AUDIT_2026-11-01.md)
for the observed host command sequence and self-write rejection tests.

Middle and Full include EEPROM transfers (write blocks 1..16 bytes), Flash
readback, bounds checks, READ_SIGN and UNIVERSAL signature queries. Full also
implements GET_SIGN_ON, SET_PARAMETER and four read-only UNIVERSAL fuse/lock
queries. Partial Flash writes erase unspecified bytes in a transferred page;
they are not read-modify-write updates. The ATtiny841/1634 require complete
64/128-byte erase groups through their dedicated host tool.

Middle/Full on hardware-Boot ATmega expose the application SPM entry at
`BOOT_START + 2`, compatible with the supplied `optiboot_mini_app_spm.h`.
Set its Boot-size macros to match the installed image. The middle entry
requires the caller to manage interrupt and EEPROM-busy conditions as described
in the header. The service rejects Boot-region fill/erase/write commands;
actual lock-bit protection is also a board fuse/lock configuration matter.
No Mini edition provides fuse writes or a true Chip Erase programmer service.

## Regression and advanced targets

```sh
make mini_test
make mini_matrix
python3 verify_toolchains.py
make mini328_check
python3 build_mini.py --verify-baseline
```

`mini_test` runs the self-contained instruction-model and generator suites.
`mini_matrix` builds and exercises every supported device/edition at the
report's nominal clock points, then transfers every application Flash byte and
EEPROM byte in one selected image per profile. The separate `verify_avrdude.py`
runner tests an actual AVRDUDE process against models over loopback TCP; it
never opens physical serial ports. See the validation report for commands.

`make mini` / `build_mini.py` retain the earlier Basic configuration for
regression and explicit feature experiments. It is distinct from the three
public editions. `make mini328` remains the frozen ATmega328P reference.
Do not infer edition features from the Basic target or from its older hardware
test report. Advanced builder switches are not an additional tested public
edition. Unsupported upstream C customization options still require the C
target. Historical compatibility fixtures are kept only for regression tests.
