# Optiboot ATmega328P: 368 bytes and upstream machine-code comparison

October 28, 2026. Historical experimental image tested in a custom AVR interpreter,
not a physical MCU. Current firmware and repository paths: `../../README.md`.

Upstream: https://github.com/Optiboot/optiboot  
C source: https://github.com/Optiboot/optiboot/blob/master/optiboot/bootloaders/optiboot/optiboot.c  
ATmega328/P datasheet, section 30.8:
https://docs.arduino.cc/resources/datasheets/Atmel-42735-8-bit-AVR-Microcontroller-ATmega328-328P_Datasheet.pdf

## Size

| Variant | Instructions | Version | Occupied, excluding FF | Difference from reference |
|---|---:|---:|---:|---:|
| Official HEX | 472 | 2 | 474 | — |
| Initial image, broken WDT | 408 | 2 | 410 | 64 |
| `optiboot_mini328_final` | 366 | 2 | 368 | 106 / 22.36% |
| `optiboot_mini328_final_tiny`, no API stub | 364 | 2 | 366 | 108 / 22.78% |

HEX covers `0x7E00..0x7FFF`, with `03 08` at `0x7FFE..0x7FFF` and FF padding.
BIN is always 512 bytes and must not be written at address zero.

The official image includes LED indication and application-callable SPM, which
these variants omit. This is not a feature-matched size comparison. Upstream
could itself be reduced with `NO_APP_SPM=1 LED_START_FLASHES=0`; that matched build
was not made in the original environment, which lacked avr-gcc/avr-libc.

## Main optimization

The ATmega328P temporary hardware Flash buffer can be filled before page erase
(the datasheet's first update sequence):

1. Receive UART bytes and fill words in the hardware SPM buffer.
2. Validate CRC_EOP and reply with STK_INSYNC `0x14`.
3. Erase only after successful validation (`SPMCSR=0x03`).
4. Write the buffer (`0x05`) and wait.
5. Enable RWW (`0x11`) and reply with STK_OK `0x10`.

There is no 128-byte SRAM page buffer. A bad EOP leaves the old page intact.
The model retains the temporary buffer across erase and clears it after write;
the physical implementation still requires board testing.

## Fixes and reductions

- The initial WDT values `0x06/0x00` left WDE off. Correct values are `0x0E`
  for one second and `0x08` for 16 ms, enabling application entry after timeout.
- As upstream does, UART receive avoids WDR for FE0 framing-error bytes so an
  invalid stream cannot indefinitely delay application entry.
- Unsupported EEPROM PROG_PAGE packets are fully received, EOP gets INSYNC,
  and execution waits for the one-second WDT, matching the reference HEX.
  The initial implementation had aborted receive early.
- High length bytes are ignored like the supplied reference; READ_PAGE low
  length zero produces 256 bytes.
- Used BRxx instead of BRxx+RJMP where in range; shared SET_DEVICE,
  SET_DEVICE_EXT and UNIVERSAL discard logic; removed redundant MOVW before
  Flash write. Application entry uses RJMP to the end of 32 KiB Flash and
  PC wraparound, as upstream does.

## Protocol validation

`PROTOCOL_AUDIT.md` records the comparison. `differential_test.py` executes actual
instructions from both upstream HEX 8.3 and the derived image. Per variant,
575 transactions / 2556 receive bytes cover command values without additional
arguments, all 256 GET_PARAMETER selectors, randomized commands, full/partial
page programming, high length bytes and zero-length reads. UART responses and
application Flash matched byte for byte.

Tests also covered nine MCUSR combinations, FE0, bad EOP, unsupported EEPROM
WRITE, WDT state and preventing boot-section erase. This does not establish
equivalence for every `256^N` input stream or physical UART/SPM/WDT operation.
Intentional differences include invalid-length checks and boot-page protection.

## Original-stage build

Python 3, Clang AVR, llvm-objcopy and readelf were required, without AVR-LibC:

```sh
python3 build.py optiboot_mini328_final optiboot_mini328_final_tiny
python3 test_emulator.py
python3 differential_test.py
python3 test_invariants.py
```

The suites provide instruction-level functional checks, upstream comparison,
and SPMCSR/SPM, WDTCSR, version and boot-protection invariants.
`download_upstream.sh` retrieves the C-source checkout when GitHub is available.

## Historical board-test procedure

Only ATmega328P, 16 MHz, UART0 115200 and a 512-byte section starting at `0x7E00`
were targeted. Typical Uno HFUSE `0xDE` must be verified against the actual board.
Other AVRs, ATmega4809 and 8 MHz boards are outside this image's configuration.
First back up Flash/fuses and ensure ISP recovery. The recorded ISP example was:

```sh
# ISP example; avrdude may erase the application firmware.
avrdude -c usbasp -p m328p -U flash:w:optiboot_mini328_final.hex:i
```

The proposed spare-board checks were avrdude `-c arduino -p m328p -b 115200
-P /dev/ttyACM0`, signature, full program/verify, auto-reset and wrong-baud
behavior. Fuse/lock changes require prior inspection.

## Files in the original stage

- `optiboot_mini328_final.{S,hex,bin}`: 368-byte research variant with RET at boot+2.
- `optiboot_mini328_final_tiny.{S,hex,bin}`: 366 bytes without that RET. Neither
  supports the former application SPM API.
- `upstream_reference.hex/.bin`: official reference, BIN padded to 512 for tests.
- `original_mini_410B_broken_WDT.S`: comparison source; not suitable for programming.
- `CHANGES_vs_410B.patch`: assembly changes.
- Tests and build scripts: reproducible model checks.
- COPYING: GNU GPL v2 text; source declares GPL-2.0-or-later.
