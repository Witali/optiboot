# Optiboot Mini — multi-device AVR build

This is an **experimental multi-device port** of the existing Optiboot Mini assembly, not a replacement for upstream `optiboot.c`. The default is **ATmega328P / 16 MHz / external crystal / UART 115200, 8N1**, as on the Arduino Uno.

The stock `make atmega328` target and legacy `make mini328` target remain available; this adds a separate `make mini` target. `make mini` consumes `MINI_MCU`, `MCU` or an explicitly supplied `MCU_TARGET`. It uses `F_CPU` or the project's `AVR_FREQ`; otherwise it defaults to 16 MHz. Device selection is also automatic for anyone compiling `optiboot_mini.S` using `-mmcu=<chip>`: `devices/select.inc` reads compiler-defined `__AVR_ATmega...__` macros.

## Examples

```sh
make mini                                   # Uno default: atmega328p / 16 MHz
make mini MINI_MCU=atmega328pb
make mini MCU=atmega168p F_CPU=12000000
make mini MCU_TARGET=atmega32a F_CPU=16000000
make mini MCU=atmega328p F_CPU=8000000 CLOCK_SOURCE=internal_rc
make mini MCU=atmega328p F_CPU=20000000 BAUD_RATE=115200
make mini MCU=atmega328p F_CPU=24000000 MINI_ALLOW_OVERCLOCK=1
make mini MCU=atmega128a F_CPU=16000000  # 1024-byte boot; extended Flash addressing
make mini MCU=atmega1284p F_CPU=20000000 # 1024-byte boot; MCU rated up to 20 MHz
make mini_list
make mini_test
```

The equivalent standalone invocation is `python3 build_mini.py --mcu atmega324pa --f-cpu 12000000 --baud auto`.

The toolchain requires Clang/LLVM AVR support or AVR-GCC/avr-objcopy, plus `readelf` and `llvm-objdump`. Assemblers that emit local relocations also require `avr-ld` from binutils-avr. The build resolves those relocations at section address zero without linker relaxation; Intel HEX supplies the physical boot address. It generates `output/<mcu>/<mcu>.hex`, `.bin`, `.o`, optional `.elf` and `.json` (build manifest). A failed size or baud check produces an error instead of a misleading ready-to-flash HEX. Use `--verify-baseline` with the standalone builder to require the previous regression-tested Uno binary SHA-256.

## Build support table

| MCU | Flash | Flash page | EEPROM | Current boot section | Build verified | Hardware tested |
|---|---:|---:|---:|---:|---|---|
| ATmega328P | 32 KiB | 128 B | 1 KiB | 512 B | Yes (bit-identical baseline) | No |
| ATmega328 / ATmega328PB | 32 KiB | 128 B | 1 KiB | 512 B | Yes | No |
| ATmega168 / ATmega168P | 16 KiB | 128 B | 512 B | 512 B | Yes | No |
| ATmega88 / ATmega88P | 8 KiB | 64 B | 512 B | 512 B | Yes | No |
| ATmega324PA | 32 KiB | 128 B | 1 KiB | 512 B | Yes | No |
| ATmega164PA | 16 KiB | 128 B | 512 B | 512 B | Yes | No |
| ATmega16 | 16 KiB | 128 B | 512 B | **512 B** | Yes (emulator smoke-tested) | No |
| ATmega32A | 32 KiB | 128 B | 1 KiB | **512 B** | Yes (emulator smoke-tested) | No |
| ATmega64A | 64 KiB | 256 B | 2 KiB | 1024 B (minimum) | Yes | No |
| **ATmega128A** | 128 KiB | 256 B | 4 KiB | **1024 B** (606 B code) | Yes (emulated) | No |
| **ATmega1284 / 1284P** | 128 KiB | 256 B | 4 KiB | **1024 B** (608 B code) | Yes (emulated) | No |

The ATmega16/32A use `uart/legacy.inc`: `SBIS` polls RXC, FE and UDRE directly in the low I/O space without a temporary `IN` instruction. This preserves UART status checks and saves four bytes, allowing **512-byte** boot sections for both parts. ATmega16 boots at `0x3E00`, ATmega32A at `0x7E00` (when BOOTSZ/BOOTRST fuses are correctly configured). The ATmega64A requires 1024 bytes of boot Flash at minimum; it also has a different SPMCSR location and a 256-byte page. Its 256-byte `PROG_PAGE` form is handled with a distinct code path. The boot address is derived from device Flash size and the actual selected boot section, never from a hardcoded ATmega328P value.

ATmega128A, ATmega1284, and ATmega1284P now have a 17-bit Flash address path. They use the full 1024-byte minimum boot section; the original 512-byte limit does **not** apply. ATmega128A uses the ATmega64A-style USART0 register map and SPMCSR at data address `0x68`; ATmega1284/1284P use modern USART0 and SPMCSR at data address `0x57`. These chips additionally require RAMPZ, ELPM and extended linear-address Intel HEX records. For a byte-for-byte explanation and fuse setup, read [the 128 KiB port guide](README_128K.md). There is no officially named ATmega1284A part: select ATmega1284 or ATmega1284P based on the actual chip/signature.

Chip signatures, UART register maps, SPM location and EEPROM address registers live in `devices/*.inc`. New unrecognised devices are deliberately rejected by `select.inc` until their maps are reviewed.

## Clock and baud-rate configuration

`F_CPU` is the **actual CPU clock**, not merely the oscillator's nominal frequency: take CKDIV8/CLKPR into account. `CLOCK_SOURCE=external_crystal` is the default. `external_clock` and `internal_rc` are supported as build settings, but **neither this tool nor the bootloader changes fuses or calibrates the oscillator**.

When `BAUD_RATE=auto`, external clocks prefer 115200 if the calculated UART error is within 2.5%, otherwise 57600. Internal RC defaults to 9600 (1 MHz), 19200 (2 MHz), or 38400 (4/8 MHz), with a tighter 1.5% calculated-divider-error limit. The build searches normal (16x) and double-speed (8x) UART modes, selecting the lowest nominal error. Actual internal RC oscillator tolerance, voltage, and temperature drift are additional and **must be measured**.

Supported build input frequencies include 10, 12, 16 and 20 MHz (subject to each device's datasheet limit). 24, 25 and 28 MHz are deliberate **out-of-spec overclocking experiments** on all listed parts and require `MINI_ALLOW_OVERCLOCK=1` or `--allow-overclock`. This switch is an acknowledgement, not a guarantee that the chip, clock source, or UART works. The datasheet operating-frequency and voltage limits still apply. For legacy ATmega16/32A, calibrated RC frequency selection and OSCCAL values require particular care: the ATmega32A datasheet documents factory calibration loading for its default 1 MHz RC mode. A build option does not select a fuse nor load OSCCAL automatically.

## Protocol and compatibility

The assembly retains the existing Optiboot Mini STK500v1-compatible subset: page write/read of Flash, 1–16-byte EEPROM writes, EEPROM reads, `GET_SIGN_ON`, signature, read-only fuse/lock `UNIVERSAL`, watchdog timeout, and the established classic Optiboot no-op Chip Erase acknowledgement. Read-modify-write of partially written Flash pages is *not* added. Real Chip Erase and fuse writes remain ISP-only. The EEPROM memory addressing assumes the **classic-AVR `avrdude -c arduino` word-address convention**; configure avrdude for the correct exact chip (`-p ...`).

**Verification status:** the old ATmega328P 16 MHz image is bit-identical and its historical software-emulation results carry over to that configuration. ATmega16/32A and ATmega128A/1284/1284P additionally have AVR-opcode-level peripheral smoke tests (not hardware-accurate timing). All MCU ports remain **unverified with real avrdude or on silicon**. Treat all non-328P firmware images as *port candidates*, not production firmware.

To avoid bricking a target, check fuse settings, BOOTRST, BOOTSZ, CKDIV8, oscillator, USART wiring, and ISP recovery availability. Consult the chip datasheet for the exact fuse encoding; do not reuse ATmega328P fuse values on legacy devices.

## License and project conventions

The source is derived from the Optiboot project and retains its GPLv2 licensing and attribution. Keep **all repository files, source comments, test output, changelogs and documentation in English**. Use standard avrdude without altering its protocol. Upstream files are preserved as-is.

For ATmega64A, verify that the ATmega103 compatibility fuse is disabled when using the modern USART0 and memory map. This port has not been hardware-tested.

## Legacy USART module

`uart/legacy.inc` owns all ATmega16/32A initialization and RX/TX poll sequences.
`uart/modern.inc` preserves the bit-identical ATmega328P reference image, and
`uart/mega64.inc` uses the ATmega64A/ATmega128A extended USART0 register addresses. The main
source uses `MINI_UART_INIT`, `MINI_UART_RX_POLL`, `MINI_UART_TX_POLL`,
`MINI_UART_RECEIVE`, and `MINI_UART_TRANSMIT` assembler macros.

The legacy `UCSRC` and `UBRRH` share I/O address `0x20`; writes use the
`URSEL` bit explicitly (1 for 8N1 UCSRC, 0 for UBRRH). Every build configures
RX/TX and UBRR explicitly, including when entering without hardware reset.
No function or protocol command has been removed to achieve 512 bytes.

### Verified results (simulation only)

| MCU | Instructions | Footer | Boot area | Origin |
|---|---:|---:|---:|---|
| ATmega16 | 500 B | 12 B | 512 B | `0x3E00` |
| ATmega32A | 500 B | 12 B | 512 B | `0x7E00` |
| ATmega328P | 500 B | 12 B | 512 B | `0x7E00` |
| ATmega64A | 568 B | 12 B | 1024 B (hardware minimum) | `0xFC00` |
| ATmega128A | 606 B | 12 B | 1024 B (hardware minimum) | `0x1FC00` |
| ATmega1284 | 608 B | 12 B | 1024 B (hardware minimum) | `0x1FC00` |
| ATmega1284P | 608 B | 12 B | 1024 B (hardware minimum) | `0x1FC00` |

The tests execute AVR instructions for sync, sign-on, signatures, fuse reads,
Flash page programming and verification, EEPROM R/W, RX framing-error
watchdog handling, and power-on application start. They also compare legacy
512-byte UART answers to the prior 1024-byte builds and cover invalid EOP.
This is not a silicon, voltage/timing, or real avrdude hardware test.

## AVRDUDE EEPROM addressing modes (ATmega64A, ATmega128A only)

Historically some AVRDUDE STK500v1 implementations used **byte** EEPROM addresses for ATmega64(A)/128(A), while newer releases unified the **word** address convention across parts. The two modes use the same wire format and cannot be autodetected safely. The default is **word** (recommended with modern AVRDUDE). For a known older host:

```sh
python3 build_mini.py --mcu atmega64a --legacy-eeprom-byte-address
make mini MCU=atmega128a MINI_OLD_AVRDUDE_EEPROM=1
```

The old-host variant only changes EEPROM address interpretation; Flash always takes a word address. **Do not mix host conventions** for EEPROM read/write. The full test and reproduction notes are at the package root in `docs/AUDIT_2026-10-30.md`.
