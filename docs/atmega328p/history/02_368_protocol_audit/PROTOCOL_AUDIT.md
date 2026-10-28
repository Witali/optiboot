# STK500v1 audit: upstream Optiboot HEX versus Optiboot Mini

This historical comparison used the official `optiboot_atmega328.hex` reporting
Optiboot 8.3, rather than C text alone. `upstream_reference.bin` contains the full
512-byte boot segment including FF padding; instructions occupy the first 472
bytes. Later stages add functions and alignment checks; see `../../README.md`.

| Command or aspect | Official reference HEX | Derived final variants |
|---|---|---|
| GET_SYNC `0x30` | `14 10` | Same. |
| GET_PARAMETER `0x41` | SW_MAJOR=08, SW_MINOR=03, other selectors=03; `14 <byte> 10` | Same. |
| SET_DEVICE `0x42` | Consumes/ignores 20 bytes | Same. |
| SET_DEVICE_EXT `0x45` | Consumes/ignores five bytes | Same. |
| ENTER_PROGMODE `0x50`, unknown single-byte commands | Valid EOP gets `14 10` | Same. |
| LOAD_ADDRESS `0x55` | Two little-endian word-address bytes, multiplied by two | Same. |
| UNIVERSAL `0x56` | Consumes four bytes; `14 00 10` on ATmega328P without RAMPZ | Same. |
| Flash PROG_PAGE `0x64` | Reads big-endian length, type, payload, EOP; sends `14`, erase/write, then `10` | Same responses/Flash for valid even 2..128-byte writes. |
| READ_PAGE `0x74` | `14`, N Flash bytes, `10`; low length zero means 256 | Same. |
| READ_SIGN `0x75` | `14 1E 95 0F 10` | Same. |
| LEAVE_PROGMODE `0x51` | Enables 16-ms WDT, then `14 10` | Same. |
| Bad CRC_EOP | No INSYNC, 16-ms WDT | Same. |
| UART FE0 | Reads byte without servicing WDT | Same. |
| PROG_PAGE type E | Receives payload, sends INSYNC, waits for one-second WDT | Same. |
| READ_PAGE type E | Supplied HEX ignores memory type and reads Flash | Same reference-HEX behavior. |

## C source versus prebuilt HEX

The examined current C source waits for WDT on type-E reads when EEPROM support
is disabled. The supplied official HEX lacks that check in READ_PAGE. This
research used the prebuilt HEX for byte-level compatibility because that was
also the size/execution reference. Returning Flash for type E does not provide
EEPROM access.

## Intentional differences

1. Invalid Flash lengths: rejects zero, odd and over-128-byte writes, avoiding
   SRAM overflow or invalid SPM buffer fills. Normal Arduino/avrdude writes fit
   the supported subset; malformed requests differ from upstream.
2. Boot protection: software rejects PROG_PAGE when the address high byte is
   at least `0x7E`, before erase/write. Upstream relies on hardware lock bits.
3. LED/application SPM: both are omitted. The normal variant returns at boot+2;
   the tiny variant executes loader code there, so the former API cannot be used.
4. MCUSR: retains the original reason in r2 but clears all MCUSR flags, while
   upstream clears selected flags. Application-visible MCUSR can differ even
   when r2 and tested entry/exit decisions agree.
5. Without LED flashes, UART becomes ready at a different time despite matching
   packet format.

## Test coverage

- 575 transactions and 2556 UART receive bytes per final variant, executing AVR
  opcodes from both images. Compared transmitted bytes, addresses, application
  Flash after each successful PROG_PAGE, and WDT register values.
- 247 unknown/no-payload command cases, all 256 GET_PARAMETER selectors, random
  SET_DEVICE/EXT/UNIVERSAL fields and different read/write types and lengths.
- Seven full/partial writes: 128, 128, 2, 8, 64, 126 and 128 bytes at different
  addresses, including the end of application Flash. Also high length bytes and
  zero-length reads.
- Nine MCUSR combinations, FE0, EOP errors, unsupported EEPROM WRITE responses/
  WDT, and boot-section erase prevention.
- Checked OUT SPMCSR immediately before SPM at three sites, WDTCSR values and
  the four-clock WDT configuration window.

## Limits

The interpreter implements only required opcodes and abstracts UART, timers,
watchdog timeout and hardware Flash. It does not reproduce physical SPI/UART
timing, SRAM organization, interrupt races, auto-reset or lock-bit hardware.
WDT evidence consists of configuration bits and reset-reason transitions, not
board measurements. The fill/erase/write sequence was checked against the
datasheet, not silicon. These tests do not establish physical equivalence for
every malformed packet.
