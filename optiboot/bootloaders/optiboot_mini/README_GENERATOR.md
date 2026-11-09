# Unified firmware generator

The wrapper calls existing builders around the single `optiboot_mini.S` source,
`devices.json`, device/UART includes, and `flash256/flash256.inc`.

```sh
python3 generate_firmware.py atmega328p compact 16MHz
python3 generate_firmware.py --mcu atmega328p --type compact --freq 16MHz
```

The required inputs are MCU, edition, and actual CPU frequency after prescaling.
Examples: `8MHz`, `10MHz`, `12MHz`, `16MHz`, `20MHz`, `16000000`. The generator
does not program fuses, change CLKPR, or select a physical clock source.

| Edition | Reservation | Functions and restrictions |
|---|---|---|
| `flash256` / `mini` | 256 B | Flash write and READ_SIGN on 13 ATmega; full-page HEX and AVRDUDE `-D -V` required |
| `flashread512` | 512 B | Flash read/write on the same 13; full-page HEX and `-D`, verification supported |
| `compact` / `middle` | 512 B on 21 ATmega; automatic 512/576 B on four ATtiny | Flash/EEPROM read/write, signatures, ATmega SPM ABI; no GET_SIGN_ON or fuse/lock reads |
| `full` | 1024 B on 38 AVR | Compact plus GET_SIGN_ON, SET_PARAMETER, fuse/lock reads; no fuse/lock writes |

Compact is disabled for 13 ATmega with a 1024-byte hardware minimum.
ATtiny84/85 use 576-byte Virtual Boot; ATtiny841/1634 use 512 bytes, aligned
to erase groups rather than just pages. See [Virtual Boot sizing](README_VIRTUAL_BOOT_SIZING.md).
Full remains 1024 bytes. The Flash-only editions do not support EEPROM.

```sh
python3 generate_firmware.py atmega328p full 16MHz
python3 generate_firmware.py atmega8 flash256 8MHz
python3 generate_firmware.py atmega16 flashread512 16MHz
python3 generate_firmware.py atmega2560 full 16MHz
python3 generate_firmware.py attiny85 middle 8MHz
python3 generate_firmware.py --mcu atmega328p --type full --freq 12MHz --baud 57600 --signature-source constants
python3 generate_firmware.py --list
python3 generate_firmware.py --list --mcu atmega328p
python3 generate_firmware.py atmega328p compact 16MHz --dry-run
python3 generate_firmware.py atmega328p compact 16MHz --out ./generated
```

Options include `--baud auto|NUMBER`, `--clock auto|internal_rc|external_crystal|external_clock`,
`--signature-source auto|hardware|constants` (Compact/Full), `--out`, `--list`,
`--dry-run`, and `--verbose`. Legacy EEPROM byte addressing is optional for
ATmega128A Full; the ATmega64A Full legacy mode is rejected because an existing
BRxx range overflow prevents assembly. Standard ATmega64A Full is supported.
Invalid MCU/edition combinations and clocks below 8 MHz or above device ratings
fail before compilation. RC frequency and real UART accuracy require hardware checks.

Outputs beneath `generated/<mcu>/<configuration>/<edition>/<mcu>/` are BIN,
absolute-address Intel HEX, profile JSON, and `build_info.json`. The configuration
directory contains `build.log`. Validation checks the BIN length, boot origin,
page alignment, footer, SHA-256, and exact HEX/BIN byte equivalence.
`bootsz1_0_bits` describes two bits, not a complete fuse byte.

Python 3.10+ and AVR LLVM tools are required: `clang`, `llvm-objcopy`,
`llvm-objdump`, and `readelf`. LLVM versions that emit local relocations also
need `avr-ld` from binutils-avr. Windows users can use WSL or an equivalent
toolchain on PATH; `generate_firmware.cmd` is a Windows launcher. Selection
and dry runs work without a compiler. Host serial upload additionally needs pyserial.

```sh
python3 -m unittest discover -s generator_tests -v
```

For ATtiny, pass matching `--boot-bytes` to all tiny tools: their legacy default
is 1024. A reservation change requires ISP reinstallation and repatched vectors.
Firmware is software-validated only; actual AVRDUDE, Arduino IDE, and physical
AVR tests remain pending. Keep ISP recovery available.
