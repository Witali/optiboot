# Optiboot Mini: features, benefits and validation

Mini is an optional assembly implementation for classic AVR devices. Its
current public generator offers three editions from one assembly source:
Mini for 14 parts, Middle for 26, and Full for all 39. The original
Optiboot repository layout, C source, board targets and stock HEX files remain
available.

The [edition naming update](EDITION_NAMES_2026-11-02.md) records the rename
from FlashRead256/Compact to Mini/Middle, compatibility aliases and validation.

The [improvement plan](ROADMAP.md) records the proposed next steps and their
completion criteria.

The [shared device database](DEVICE_DATABASE.md) supplies the builders and
[generated device reference](DEVICES.md); register constants remain outside JSON.

| Capability | Mini | Middle | Full | Practical benefit / limit |
|---|---|---|---|---|
| Reserved Boot area | 256 B | 512 B ATmega; 1024 B Virtual ATtiny | 1024 B | Respect each chip's physical Boot minimum |
| Flash write and readback | Yes | Yes | Yes | Normal upload verification remains enabled |
| EEPROM write/read | No | Yes | Yes | Serial configuration transfer and verification |
| READ_SIGN | Yes | Yes | Yes | Exact part signature checking |
| UNIVERSAL signature query | No | Yes | Yes | Additional host compatibility |
| GET_SIGN_ON / SET_PARAMETER | No | No | Yes | Full protocol clients and diagnostics |
| Actual fuse/lock reads | No | No | Yes | Inspect configuration without an ISP read session |
| Application SPM ABI | No | Hardware-Boot ATmega | Hardware-Boot ATmega | Application Flash service with Boot-region guards |
| Input and address checks | Yes | Yes | Yes | Reject invalid lengths, types, alignment, overflow and Boot writes |
| Supported device/edition profiles | 14 | 26 | 39 | 79 supported combinations, with explicit build metadata |

The write-only 256-byte edition has been removed. The read/write edition now
occupies a real 256-byte Boot section, with 249..255 useful bytes at
16 MHz / 115200 on all 14 supported ATmega parts. It requires aligned full-page
writes, page-aligned reads, and hardware-reset entry. The audited Arduino
AVRDUDE path supplies full write pages automatically for ordinary HEX files;
see the [Arduino protocol audit](ARDUINO_PROTOCOL_AUDIT_2026-11-01.md).
ATmega328P/PB cannot use
256-byte Boot sections. Middle and Full retain EEPROM support; Full retains
the extra sign-on and fuse/lock query handlers.

## Comparison with the original C implementation

The stock Optiboot C implementation already provides compact images, fast
uploads, fast application startup, broad AVR support and an application SPM
service. Mini does not claim to introduce those features to Optiboot or to
improve measured upload speed. Relative to C source defaults at
`e363ecbe2b6542b5db5b4209589f274c87d833a7`, Mini offers the following combination;
optional C build configurations can differ.

| Area | Mini contribution | Evidence and scope |
|---|---|---|
| Smallest verified upload profile | Flash write plus readback in 256 bytes on 14 eligible parts | Size/layout checks and executed instructions for each part; no physical validation yet |
| EEPROM support | Included in Middle/Full, rather than a default-disabled EEPROM option | Every EEPROM byte transferred in each supported profile's memory test |
| Real fuse/lock inspection | Full returns actual bytes for four read-only UNIVERSAL operations | Instruction-model tests plus [physical Full ATmega328PB reads](HARDWARE_FULL_ATMEGA328PB_2026-11-04.md) |
| Defensive protocol checks | Explicit packet, memory-type, length, alignment, overflow and Boot-region checks | Negative-case regressions; no power-loss atomicity guarantee |
| Large AVR addressing | Extended Flash support through 256 KiB, independent EEPROM addressing | Actual AVRDUDE tested against instruction models, including upper-bank Flash followed by EEPROM |
| Configuration and build output | Validated edition/device/clock combinations, BIN/HEX agreement and SHA-256 metadata | Earlier 423 clock/edition builds plus 18 ATmega168PB builds and self-contained generator tests |
| Reproducibility | Model tests, clock matrix, full-memory runner and actual AVRDUDE loopback runner | Sources and sanitized results are checked in; raw board backups are excluded |

## Build and validation

From `optiboot/bootloaders/optiboot/`:

```sh
python3 generate_firmware.py atmega8 mini 16MHz
python3 generate_firmware.py atmega328pb middle 16MHz
python3 generate_firmware.py atmega328pb full 16MHz
make mini_test
make mini_matrix
make mini328_check
```

The [build guide](../../optiboot/bootloaders/optiboot/README_MINI_MULTI.md)
contains the complete part table, host contract and Mini page-padding
command. The [2026-11-01 report](UART_VALIDATION_2026-11-01.md) records the
current software checks and exact image hashes. ATtiny uses the separate
[Virtual Boot workflow](VIRTUAL_BOOT.md).

The [ATmega168PB addendum](ATMEGA168PB_2026-11-01.md) documents the newly added
39th profile, its three editions and additional software validation. Earlier
reports retain their original device counts and source revisions.

The [2026-10-30 hardware report](HARDWARE_ATMEGA328PB_2026-10-30.md) records
42 physical checks on one ATmega328PB Nano running the older Basic image with
SHA-256 `149ebc0347815b42daaa20defce83342462306e9ddd3f15c63eeb59baafd70d1`.
Those results do not qualify the new Middle, Full or Mini binaries.
The separate [2026-11-04 Middle report](HARDWARE_MIDDLE_ATMEGA328PB_2026-11-04.md)
records 45 physical checks on one ATmega328PB Nano with the exact 512-byte
Middle hash, including a focused cold-start retry. The separate
[Full report](HARDWARE_FULL_ATMEGA328PB_2026-11-04.md) records 49 distinct checks
on another ATmega328PB Nano with the exact 1024-byte image, including a final
diagnostic retry. Other configurations retain their software-only qualification.

The new editions remain experimental. Software models do not establish silicon
errata, real SPM/EEPROM latency, oscillator tolerance, electrical UART timing or
power-loss recovery. ATtiny Virtual Boot has no hardware Boot-region protection
and requires an ISP seed plus vector relocation. Mini has fewer customization
options than the C implementation: use the C targets for startup LED animation
and other unsupported options. Fuse/lock writes and true Chip Erase require
an ISP programmer.
