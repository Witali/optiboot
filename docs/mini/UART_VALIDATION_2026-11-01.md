# UART editions: software validation, 2026-11-01

Edition naming update (2026-11-02): `FlashRead256` / `flashread256` is now
`Mini` / `mini`; `Compact` / `compact` is now `Middle` / `middle`.
This dated report retains its original names and evidence. The old CLI
names remain accepted as aliases.

All results on this page are software results. No serial port, ISP programmer
or physical board was accessed. The earlier 42-check Nano hardware report
applies only to its recorded Basic image, not to these editions.

Firmware, generator and test source commit:
`6449f85aa2fefade2f838f9a5c5feac3e7fb91b6`.

The later [Arduino protocol audit](ARDUINO_PROTOCOL_AUDIT_2026-11-01.md) adds
ordinary unpadded-HEX cases. AVRDUDE 8.0-arduino.1 supplies full write pages
automatically, so the manual preparation tool is optional for that upload path.
It also verifies rejection of every FlashRead256 Boot page before any SPM.

## Supported firmware

| Edition | Device profiles | Physical/reserved area | Included memory operations |
|---|---:|---|---|
| FlashRead256 | 13 hardware-Boot ATmega | 256 B | Flash write and readback |
| Compact | 21 ATmega + four Virtual Boot ATtiny | 512 B ATmega, 1024 B ATtiny | Flash and EEPROM read/write |
| Full | 34 ATmega + four Virtual Boot ATtiny | 1024 B | Flash and EEPROM read/write, fuse/lock reads |

There are 76 supported device/edition combinations across 38 MCUs. The
write-only 256-byte edition is removed. The oversized readback prototype is
replaced by a real 256-byte read/write image. ATmega328P/PB still require at
least 512 physical Boot bytes; no 256-byte image is offered for them.

Source inputs were reviewed from `Optiboot_UART_Agent_Handoff_2026-11-01.zip`
(SHA-256 `609bbfd93b70c6f396688044f7287eb2366a49f59b72cca54abeebefc8054083`).
The current repository contains the active source, required regression fixtures,
reproduction tools and sanitized results. Archived write-only firmware,
historical snapshot test modules requiring missing artifacts, raw captures and
board-memory backups are not part of this update. All pre-existing repository
test modules are retained.

## Results

| Check | Result |
|---|---|
| Instruction-model regression suite | 124 tests passed |
| Generator and page-preparation suite | 16 tests passed |
| Device/edition/clock builds | 423/423 passed; BIN size, HEX checksum/address agreement, Boot geometry and SHA-256 checked |
| Protocol execution for every clock image | 423/423 passed; sync/signature, first/last application group read/write, EEPROM boundaries where supported |
| Full-memory execution | 76/76 profiles passed; every application Flash byte and every supported EEPROM byte transferred and read back; Boot unchanged |
| Actual AVRDUDE 8.0-arduino.1 against instruction models | 68/68 hardware-UART profiles passed with normal Flash/EEPROM verification |
| Actual AVRDUDE with padded final Flash page | 13/13 FlashRead256 profiles passed; verification enabled |
| Clang vs AVR-GCC | 76/76 nominal profile builds byte-identical |
| Application SPM service | All 55 current hardware-Boot Compact/Full profiles programmed application Flash and rejected Boot fill/erase/write; preserved callee-saved registers and cleared r1 |
| Application SPM C header | Compile probes passed for all 55 ABI profiles; CALL/ICALL target encoding checked independently |
| Reset entry | All 63 Compact/Full profiles exercised with each of 16 reset-flag combinations; FlashRead256 also tested with randomized registers and seven reset causes on 26 images |
| Frozen `mini328` reference | Unchanged: SHA-256 `be531a3f0b7294c6e9f00f4d02a8c5e7ff28d8fb2b7c90cb6501d0294cfae00b` |
| Stock C `atmega328` build | HEX byte-identical to upstream `e363ecbe2b6542b5db5b4209589f274c87d833a7`, using the same AVR-GCC/options |

The complete nominal clock matrix is [UART_MATRIX_2026-11-01.csv](UART_MATRIX_2026-11-01.csv).
It includes each image's Boot address, useful/free bytes, divider error and
BIN SHA-256. [UART_RESULTS_2026-11-01.json](UART_RESULTS_2026-11-01.json)
contains the per-profile memory, host and cross-compiler results without local
account paths or raw logs.

The clock matrix covers external 8/10/12/16/20 MHz, subject to each device's
rating, plus internal RC at 8 MHz. ATtiny85 uses external clock input where
appropriate. Automatic baud selection is tested at these nominal points;
arbitrary explicit frequencies, baud rates, overclocking and electrical
margins are not an exhaustive part of this matrix.

Whole-memory software-UART tests use a byte adapter at the actual RX/TX routine
entry points to keep the run practical. The 24 ATtiny84/85 clock/edition images
also execute their unmodified GPIO UART routines for waveform sync/signature
checks. Separate waveform regressions cover page/EEPROM transfers, bit timing,
framing and nominal host offsets of +/-1.5%. These are instruction-cycle models,
not measurements of a physical oscillator or pin.

## FlashRead256 layout and behavior

At 16 MHz / 115200, every BIN is exactly 256 bytes, including signature and
padding. BOOTSZ1:0 is `11`; actual complete fuse bytes are part-specific.

| MCU | Instructions | Signature | Useful total | Free padding | Boot origin |
|---|---:|---:|---:|---:|---|
| ATmega8 / 8A / 8515 / 8535 | 248 B | 3 B | 251 B | 5 B | `0x1F00` |
| ATmega16 / 162 | 246 B | 3 B | 249 B | 7 B | `0x3F00` |
| ATmega164A/P/PA / 168/P | 250 B | 3 B | 253 B | 3 B | `0x3F00` |
| ATmega88 / 88P | 252 B | 3 B | 255 B | 1 B | `0x1F00` |

The size reduction shares packet termination/discard handling, word reception,
reply return paths and a checked instruction-byte constant. The builder checks
that constant's opcode and resolves byte-address relocations before exporting
the BIN/HEX. It does not patch compiled firmware bytes. Clock speed was not
reduced to make the image fit.

The reset-only prologue immediately reconfigures or disables WDT; it relies on
hardware-reset UART format/divisor-high state and disabled interrupts. The
watchdog counter is cleared by chip reset, as described in the
[ATmega8A datasheet, section 11.4](https://ww1.microchip.com/downloads/en/DeviceDoc/ATmega8A-Data-Sheet-DS40001974B.pdf).
The receive path still feeds WDT according to framing status. The image is not
an application-callable replacement for reset entry.

On each of 13 devices at both 8 MHz / 38400 and 16 MHz / 115200, the tests cover
all 256 parameter IDs, every allowed Flash read length, first/last application
pages, command framing, bad EOP, truncated data, invalid high length/type,
alignment, Boot bounds, LOAD_ADDRESS overflow and EEPROM-busy blocking before
SPM buffer fill. Erase/write follows a valid EOP. Full-page application HEX
preparation and actual host verification are tested as well.

## Defects corrected during validation

* EEPROM after upper Flash banks: AVRDUDE preserves its extended Flash bank
  latch when switching to EEPROM. The old 256 KiB path rejected that normal
  sequence. EEPROM checks now ignore the Flash-only bank bit while retaining
  genuine LOAD_ADDRESS overflow and EEPROM range checks. A direct regression
  and actual AVRDUDE transfers on ATmega2560/2561 cover this sequence. The host
  behavior follows [AVRDUDE v8.0 stk500.c](https://github.com/avrdudes/avrdude/blob/v8.0/src/stk500.c).
* AVR-GCC software UART: assembly frequency/baud constants no longer use C
  integer suffixes that GNU as rejects in delay expressions. Clang and GCC
  now produce the same firmware bytes.
* Small-AVR application SPM calls: parts without absolute CALL use ICALL with
  an explicit complete Z word address. This also avoids a Clang fixed-register
  operand issue that omitted Z's high byte. Large parts keep absolute CALL,
  including full 256 KiB target addresses.
* Old GCC ATmega324PB specs: assembly can use the identical 324PA instruction
  set while explicitly selecting the reviewed 324PB register map/signature;
  the manifest records the assembler MCU. This is not a substitute for a PB
  device header when compiling an application. The isolated C header probe
  supplies known Flash geometry when the installed old avr-libc lacks PB
  headers.
* ATtiny841 grouped erase and watchdog setup: the host transfers complete
  64-byte groups, and the generated CCP register map retains the current
  profile. Software-UART idle polling no longer feeds WDT continuously.

## Reproduce without hardware

Run from `optiboot/bootloaders/optiboot/`. No external handoff archive is needed.
The tested tools were Python 3.12.3, Clang/LLVM 18.1.3, AVR-GCC 7.3.0,
GNU AVR binutils 2.26 and GNU Make 4.3 under Ubuntu/WSL. The host tests used the
Windows AVRDUDE 8.0-arduino.1 executable and its matching configuration file.

```sh
make mini_test
python3 verify_editions.py --all-clocks --smoke --stress --jobs 4
python3 verify_toolchains.py
make mini328_check
python3 build_mini.py --verify-baseline
```

Run real AVRDUDE through the loopback model with the executable and matching
configuration installed on the host:

```sh
python3 verify_avrdude.py --avrdude /path/to/avrdude --config /path/to/avrdude.conf
python3 verify_avrdude.py --avrdude /path/to/avrdude --config /path/to/avrdude.conf --edition flashread256 --padded-application --output output/avrdude-padded
```

A Windows `.exe` can be invoked from WSL by its `/mnt/...` path; the runner
converts generated file paths for it. All target connections are bound to
`127.0.0.1` and use AVRDUDE `-P net:127.0.0.1:PORT`. The command uses
`-c arduino -D`, normal part checking and normal verification, without `-V` or `-F`.
It retries only an unopened localhost transport before any target input; it
never replays a partially written target. Outputs and logs remain in ignored
`output/` directories. Publish only reviewed summaries, not unfiltered logs.

To reproduce the stock C comparison, build `make atmega328` in an unmodified
checkout of the pinned upstream commit and in a copy of this source using the
same compiler/options, then compare `optiboot_atmega328.hex`. The tested HEX
SHA-256 was `73b0833cbac1550825c8cd67fcc24363cd0d2bdd38f6963f42feb29ee7b2ec96`.
The frozen `mini328` reference is separate from the current Basic configuration;
the latter also passes its own explicit `--verify-baseline` check.

## Remaining physical validation

Software checks do not qualify actual SPM/EEPROM timing, watchdog duration,
lock/fuse programming, silicon errata, voltage or temperature tolerance,
oscillator calibration, electrical UART timing, or recovery after power loss.
Model peripherals simplify completion timing and implement only the required
instruction set. An actual AVRDUDE process validates host interoperability with
that model, not a physical board. All new editions require board-level tests
before being described as hardware-validated. ATtiny Virtual Boot additionally
requires an ISP seed, vector relocation and grouped-erase validation; it has no
hardware-protected Boot region.
