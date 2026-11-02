# Arduino upload protocol and FlashRead256 self-write audit

Edition naming update (2026-11-02): `FlashRead256` / `flashread256` is now
`Mini` / `mini`; `Compact` / `compact` is now `Middle` / `middle`.
This dated report retains its original names and evidence. The old CLI
names remain accepted as aliases.

Date: 2026-11-01. This audit uses the installed Arduino AVR Boards 1.8.8 upload
recipe and real AVRDUDE 8.0-arduino.1 against AVR instruction models. It does
not open a serial port or ISP programmer, run the Arduino IDE, or qualify a
physical board. Firmware instructions are unchanged from commit
`6449f85aa2fefade2f838f9a5c5feac3e7fb91b6`.

## Conclusions

* Ordinary application HEX files upload and verify through the tested
  `-c arduino -D` path, including files ending inside a page or on an odd byte.
  AVRDUDE supplies complete 64/128-byte write packets. Manual HEX padding is
  optional for this tested host version.
* The running FlashRead256 loader cannot replace its own Boot image through
  this interface. All Boot pages are rejected before any SPM instruction,
  including page-buffer fill. This is a firmware guard, independent of any
  additional physical lock-bit protection.
* Initial bootloader installation, replacement and fuse configuration require
  ISP with this implementation. Arduino's Burn Bootloader action uses a
  separate programmer/erase/fuse workflow; ordinary sketch upload does not.
* This is compatibility with the classic AVR `arduino` upload backend. It is
  not full AVR061 compliance or a claim about other Arduino board protocols.
  ATmega328P/PB cannot use 256-byte Boot sections; use a supported 512/1024-byte
  edition on those parts.

The earlier instruction to always run the manual page-preparation tool was
too restrictive for AVRDUDE 8.0-arduino.1. The firmware still requires full
STK_PROG_PAGE payloads, but the ordinary Arduino upload path already supplies
them. The optional tool remains useful with another host that sends short
write packets. Other AVRDUDE versions were not part of this new host matrix.

## Host contract and observed commands

The installed platform's upload recipe invokes AVRDUDE with the selected MCU,
board protocol, port and baud, `-D`, and `-Uflash:w:APPLICATION.hex:i`. Verification
is enabled unless the user explicitly disables it. The tested command substitutes
loopback TCP for the physical serial port while retaining those upload options.
The selected board must have `upload.protocol=arduino` and a matching baud.
See the official [Arduino AVR platform recipe](https://github.com/arduino/ArduinoCore-avr/blob/1.8.8/platform.txt)
and [board definitions](https://github.com/arduino/ArduinoCore-avr/blob/1.8.8/boards.txt).

| Command | Wire code | Observed FlashRead256 behavior |
|---|---|---|
| GET_SYNC | `30` | `14 10` reply; repeated startup synchronization accepted |
| GET_PARAMETER | `41` | `14 03 10`; host queries `80`, `81`, `82`, `98`; informational values are placeholders |
| SET_DEVICE | `42` | Consumes 20 parameter bytes and EOP, then acknowledges; no ISP device state is configured |
| SET_DEVICE_EXT | `45` | Consumes five parameter bytes and EOP, then acknowledges |
| ENTER_PROGMODE | `50` | Acknowledges entry to the bootloader session |
| READ_SIGN | `75` | `14`, the exact three part-signature bytes, `10` |
| LOAD_ADDRESS | `55` | Little-endian word address converted to a byte address; overflow rejected |
| PROG_PAGE | `64` | Flash type `F`, aligned complete physical page; application region only |
| READ_PAGE | `74` | Flash type `F`, page-aligned address, length 1..PAGE; readback verification |
| LEAVE_PROGMODE | `51` | Acknowledges and selects short watchdog exit; physical timeout duration is not modeled |

These are the request types observed in the successful verbose uploads. The
`arduino` backend uses READ_SIGN instead of the generic STK500 ISP signature
sequence, as implemented in [AVRDUDE arduino.c](https://github.com/avrdudes/avrdude/blob/v8.0/src/arduino.c).
The host's page operations are in [stk500.c](https://github.com/avrdudes/avrdude/blob/v8.0/src/stk500.c);
the normal writer in [avr.c](https://github.com/avrdudes/avrdude/blob/v8.0/src/avr.c)
supplies whole pages before invoking that backend.

GET_SIGN_ON and UNIVERSAL were not needed by this upload sequence. The
13 supported devices have at most 16 KiB Flash and need no extended bank
command. Chip Erase was not sent with `-D`; the loader only acknowledges that
command without implementing a true Chip Erase. EEPROM and fuse/lock writes
are outside this edition's protocol.

There are deliberate differences from [AVR061](https://ww1.microchip.com/downloads/en/Appnotes/doc2525.pdf):
parameter reads return a placeholder, unsupported commands do not implement the
full UNKNOWN/FAILED response contract, and invalid EOP/addresses enter watchdog
recovery instead of a complete programmer error-response sequence. The Full
edition is also a bootloader subset, not a complete STK500 programmer.

## Executed checks

| Check | Scope and expected result |
|---|---|
| Ordinary HEX ending with two bytes in its last page | 13 profiles at 16 MHz / 115200; upload and readback pass |
| Ordinary HEX ending with one byte in its last page | Same 13; upload and readback pass |
| Explicitly padded odd-length HEX | Same 13; upload and readback pass |
| Attempt to upload the loader's own 256-byte Boot HEX | Same 13; rejected at Boot PROG_PAGE, zero SPM calls, all Flash unchanged |
| Stock Nano ATmega168 baud setting | Four additional cases with a matching 19200-baud build; three application uploads pass, own Boot write rejected |
| All Boot pages, direct protocol requests | 13 MCUs at 8 MHz / 38400 and 16 MHz / 115200; 76 page-write attempts rejected before SPM |
| Targeted firmware regressions | All eight `test_flashread256` tests pass |
| Generator and page-preparation regressions | All 16 tests pass |

The main host matrix has 52 cases: 39 verified application uploads and 13
blocked Boot writes. The Nano ATmega168 baud check adds four cases. Firmware
BINs are exactly 256 bytes. The 115200-baud image hashes match the earlier
[UART matrix](UART_MATRIX_2026-11-01.csv). The
[sanitized machine results](ARDUINO_PROTOCOL_RESULTS_2026-11-01.json) record
per-case command counts, page-write lengths, image hashes and outcomes.

The negative Boot cases intentionally stop at the firmware guard. This model
does not advance a real watchdog clock; the runner bounds the waiting host
process and records whether it timed out. That bounded wait is not a measured
watchdog duration. The runner never restarts AVRDUDE after target input begins;
process retries are restricted to unopened WSL localhost forwarding connections.

## Board configuration

A default 16 MHz FlashRead256 build uses 115200 baud. The stock Arduino Nano
ATmega168 board definition uses 19200, so build with the corresponding setting
or provide an appropriate board definition:

```sh
python3 generate_firmware.py atmega168 flashread256 16MHz --baud 19200
```

The selected MCU, real CPU clock, BOOTSZ and upload baud must match the installed
firmware. The maximum sketch size must stay below `FLASH_SIZE - 256`; the stock
board's more conservative limit is safe but does not expose all recovered
space. No board-definition, fuse or lock setting was modified by this audit.

## Reproduce without hardware

Run from `optiboot/bootloaders/optiboot/` with the toolchain in the
[build guide](../../optiboot/bootloaders/optiboot/README_MINI_MULTI.md):

```sh
python3 -m unittest mini_tests.test_flashread256 -v
python3 -m unittest discover -s generator_tests -v
python3 verify_arduino.py --avrdude /path/to/avrdude --config /path/to/avrdude.conf --timeout 6
python3 verify_arduino.py --avrdude /path/to/avrdude --config /path/to/avrdude.conf --mcu atmega168 --baud 19200 --timeout 6 --output output/arduino-stock-nano168
```

The script uses `-v`, `-c arduino`, `-D`, the manifest baud and ordinary
`-Uflash:w:...:i`, with verification and signature checking enabled. It records
host requests locally, decodes framing independently of the firmware dispatcher,
compares application bytes and page padding, and observes SPM calls directly.
It binds only to `127.0.0.1`; no COM port, USB device or programmer is opened.
The TCP substitution does not test physical baud accuracy, DTR auto-reset,
UART electrical behavior, actual fuses/locks, or real watchdog/SPM timing.
Raw requests and logs remain in ignored `output/` directories; they are not
published test fixtures.
