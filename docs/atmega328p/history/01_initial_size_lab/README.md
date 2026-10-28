# Optiboot Mini 328: initial size-reduction research

Research snapshot: October 28, 2026. Machine code was assembled and protocol/
Flash behavior exercised in a small custom interpreter, not a physical Arduino
Uno or ATmega328P. This historical stage was later found to have incorrect WDT
configuration; do not program it. The current image is documented at
`../../README.md`.

## Basis

- Upstream: https://github.com/Optiboot/optiboot
- C source: https://github.com/Optiboot/optiboot/blob/master/optiboot/bootloaders/optiboot/optiboot.c
- Reference HEX: `upstream/optiboot_atmega328.hex`, obtained from GitHub master
  on October 28; blob `ac2526dd99b662a2952e78942b49d21232444c9e`.
- Observed C blob: `d7fba90a02616f095ec733ac4c434b4d42db58a6`.
  `download_upstream.sh` retrieves the full upstream checkout with network access.
- Original and derivative code declare GPL-2.0-or-later; see COPYING.

## ATmega328P sizes

| Build | Instructions | Version | Occupied, excluding FF padding | Difference from supplied upstream HEX |
|---|---:|---:|---:|---:|
| Official reference | 472 | 2 | 474 | — |
| `optiboot_mini328`, buffered | 408 | 2 | 410 | 64 bytes / 13.5% |
| `optiboot_mini328_stream`, streaming | 400 | 2 | 402 | 72 bytes / 15.2% |

Each HEX/BIN spans 512 bytes at `0x7E00..0x7FFF`, the 256-word boot section.
Unused bytes are FF; the final bytes `03 08` represent version 8.3. Instruction
size is measured from `_code_end` before padding.

The reference includes LED startup and application-callable SPM; both are omitted
here. The 64/72-byte differences therefore do not measure assembly optimization
at feature parity. A matched upstream build with `LED_START_FLASHES=0 NO_APP_SPM=1`
was not included. Merged routines, nearby error handlers and X-register reuse
were assessed separately.

## Implemented behavior and omissions

- UART0, 115200 8N1 at 16 MHz; U2X0=1, UBRR0=16, actual rate about 117647
  (+2.12%).
- STK500v1 GET_SYNC, GET_PARAMETER (software version), SET_DEVICE,
  SET_DEVICE_EXT, ENTER_PROGMODE, LOAD_ADDRESS, UNIVERSAL, PROG_PAGE, READ_PAGE,
  READ_SIGN and LEAVE_PROGMODE, with INSYNC/OK framing.
- External reset without WDRF, or MCUSR=0, enters the loader; POR/WDRF starts
  the application. The original MCUSR is copied to r2.
- The intended WDT behavior was one second while waiting and 16 ms on exit/error.
  Later analysis found that this stage's `0x06/0x00` values did not enable WDE.
- Flash uses SPM erase/fill/write/RWWSRE and LPM reads. It rejects writes from
  `0x7E00`, EEPROM operations and invalid Flash lengths (zero, odd, over 128).
  Programming handles at most one page, two bytes per iteration.
- No LED flashing, EEPROM R/W, software UART, other clocks/MCUs, extended
  STK500 commands or unaligned-page programming.
- The old boot+2 do_spm service is replaced by RET. Applications using that API
  are incompatible.

## Buffered and streaming writes

The main `optiboot_mini328.S` receives a whole page into SRAM at `0x0100`,
validates CRC_EOP, then erases and writes. Bad EOP leaves the old page intact.

The streaming variant receives directly into the hardware SPM buffer, saving
eight code bytes and up to 128 SRAM bytes, but erases before validating EOP.
A truncated transfer can destroy page data; it was not recommended as the main
bootloader.

## Original-stage build and tests

The original environment used Clang 17 with `-target avr -mmcu=atmega328p` and
llvm-objcopy. Register constants are embedded; no avr-libc headers or intermodule
relocations were needed there.

```sh
python3 build.py
python3 build.py optiboot_mini328_stream
python3 test_emulator.py
```

The interpreter executes assembled AVR instructions and checks STK500 responses,
Flash programming/readback, boot protection, application entry and bad EOP.
It is not a full timing/register/peripheral model. Real USB/UART, capacitive
auto-reset, chip variation and physical watchdog behavior require board tests.

The original-layout upstream comparison procedure was:

```sh
sh download_upstream.sh
cd upstream/original_repo/optiboot/bootloaders/optiboot
make atmega328 LED_START_FLASHES=0 NO_APP_SPM=1
```

That upstream command requires GNU AVR-GCC. The assembly builds use Clang AVR
and LLVM object tools. Repository tools and sources now occupy separate trees;
consult `../../IMPORT_MANIFEST.json` for relocated paths.

## Historical programming notes

The target was ATmega328P / ordinary Uno, 16 MHz, a 512-byte boot section at
`0x7E00` and BOOTRST enabled. A typical Uno HFUSE is `0xDE`, but the actual board's
fuses/locks must be checked. These images are unsuitable for other MCUs, 8 MHz,
or incompatible fuses. The later WDT finding means these initial images should
not be installed; this original ISP example is retained as a historical record:

```sh
# USBasp SPI/ISP example, not a normal UART upload.
avrdude -c usbasp -p m328p -U flash:w:optiboot_mini328.hex:i
```

The original plan required an ISP Flash/fuse backup and recovery access, then
Arduino/avrdude `-c arduino -p m328p -b 115200` signature/program/verify tests,
auto-reset and watchdog-reset checks. Fuse/lock settings were not to be changed
without examining the board.

## Proposed follow-up

- Make a feature-matched official build without LED/application SPM.
- Reposition rare branches and simplify dispatch/length checks without weakening
  protections.
- Explore fixed-target UART/WDT, reset-vector RJMP and prepared-register reuse.
- Test physical AVR behavior, including first-byte reception after auto-reset.
