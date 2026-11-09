# Multi-device port history

This document preserves early porting records, including superseded sizes and
references to guides in external handoff archives. Current builds use one source
for 38 MCU. See README_DUAL_EDITIONS.md for 63 active paired profiles and
README_VIRTUAL_BOOT_SIZING.md for the 2026-11-08 ATtiny update.

The 2026-10-31 record first described binary clones for 12 compatible 16/32 KiB
ATmega: reuse of a 511-byte image with signature and six 16 KiB address constants
patched. That method was subsequently removed; all profiles now compile source.
The old wrapper name build_mini_clone511.py remains for automation only.

The 2026-10-30 software-UART addendum introduced ATtiny84/85 via uart/soft.inc:
8 MHz/19200 default, 64-byte pages, Virtual Boot through EEPROM-ready vectors
14/6. Early code occupied 582 bytes in 1024. Initial installation used ISP seed,
SELFPRGEN, patched reset vectors, and the custom tiny uploader. The following
early statement that software UART was absent predates that addendum.

---

> **CURRENT STATUS, 30 October 2026:** 34 ATmega profiles plus two experimental virtual-boot ATtiny profiles build. The following tables document the original 15-MCU release and are historical. See `../../../../docs/EXPANDED_PORTS_2026-10-30.md` and the package root `README_START_HERE.md` for the newer matrix. ATtiny85/84 software USART is NOT implemented.

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

The toolchain requires Clang/LLVM AVR support or AVR-GCC/avr-objcopy. It generates `output/<mcu>/<mcu>.hex`, `.bin`, `.o` and `.json` (build manifest). A failed size or baud check produces an error instead of a misleading ready-to-flash HEX. The default Uno build is checked against the previous regression-tested binary SHA-256.

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

ATmega128A, ATmega1284, and ATmega1284P now have a 17-bit Flash address path. They use the full 1024-byte minimum boot section; the original 512-byte limit does **not** apply. ATmega128A uses the ATmega64A-style USART0 register map and SPMCSR at data address `0x68`; ATmega1284/1284P use modern USART0 and SPMCSR at data address `0x57`. These chips additionally require RAMPZ, ELPM and extended linear-address Intel HEX records. For a byte-for-byte explanation and fuse setup, read the historical handoff guide `README_128K.md` (not included in this update). There is no officially named ATmega1284A part: select ATmega1284 or ATmega1284P based on the actual chip/signature.

Chip signatures, UART register maps, SPM location and EEPROM address registers live in `devices/*.inc`. New unrecognised devices are deliberately rejected by `select.inc` until their maps are reviewed.

## Clock and baud-rate configuration

`F_CPU` is the **actual CPU clock**, not merely the oscillator's nominal frequency: take CKDIV8/CLKPR into account. `CLOCK_SOURCE=external_crystal` is the default. `external_clock` and `internal_rc` are supported as build settings, but **neither this tool nor the bootloader changes fuses or calibrates the oscillator**.

**Minimum project clock: 8 MHz.** The builder rejects `F_CPU < 8000000` for all MCUs, even with `--allow-overclock` or `--allow-baud-error`; 1, 2 and 4 MHz builds are no longer supported. Fuses and CLKPR must be configured to make the *actual* CPU frequency match `F_CPU`; specifically, avoid accidental `/8` clock prescaling (`CKDIV8`) on 8 MHz RC devices.

With `BAUD_RATE=auto`, hardware UART builds at **8 MHz use 38400** to minimize baud divider error (+0.16%, normal 16x mode). Above 8 MHz, external clocks prefer 115200 if its calculated UART error is within 2.5%, otherwise 57600. Internal RC is supported at **8 MHz / 38400** for hardware USART, or **8 MHz / 19200** on the software UART ATtiny84/85. **ATtiny84/85 at 16 MHz on an external clock now default to 115200**; 8 MHz with an external clock defaults to 57600, while 8 MHz internal RC remains at 19200. Their bit-level emulator tests cover external-clock 115200 and 57600 with nominal host clock deviation of +/-1.5%. Real hardware has not been tested. On ATtiny84/85 the idle soft-UART loop deliberately does not feed WDT (once per new byte only), so a silent bootloader can time out and start the application. The build searches normal (16x) and double-speed (8x) modes for hardware USART, selecting the lowest nominal error. Internal RC oscillator tolerance, voltage, and temperature drift are additional and **must be measured**.

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
The 512-byte 328P default preserves this project's previous Mini STK500v1 handlers. It is **not** feature-complete relative to official Optiboot v8.3; see [FEATURE_PARITY_UPSTREAM.md](FEATURE_PARITY_UPSTREAM.md) for the missing optional LED, RS-485, alternate reset modes and the default-enabled upstream app-callable SPM API.

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

## Upstream feature parity

Optiboot Mini intentionally does not implement every upstream Optiboot 8.3 option. See [FEATURE_PARITY_UPSTREAM.md](FEATURE_PARITY_UPSTREAM.md) before changing boards, enabling LED/RS-485, using `WDTTIME` or application-callable SPM. Unsupported user-supplied upstream Makefile options now cause an explicit build error rather than being silently ignored.

## Application-callable SPM mode (opt-in)

`make mini_spm MCU=atmega328p F_CPU=16000000` builds an additional
1024-byte Boot image, with `do_spm(uint16_t,uint8_t,uint16_t)` at
`BOOT_START+2` and both STK500v1 signature forms. The app can use the
`optiboot_mini_app_spm.h` header. This mode does NOT overwrite the default
512-byte image; its output is in `output/spm/<mcu>/`. See `docs/APP_SPM_RU.md`
in the release package for the ABI, safety warnings and test coverage.
