# Current interface and hardware limits: 512 bytes

The complete audit is `CURRENT/AUDIT.md` in the original handoff layout.
This translated record defines what compatibility means for this research.

## Hardware target

- ATmega328P, not ATmega328PB or 4809; 16 MHz, UART0 8N1, nominal 115200 baud.
  UBRR=16 with U2X0 gives approximately 117647 baud.
- Boot section: 256 words / 512 bytes at `0x7E00..0x7FFF`, with matching
  BOOTRST/BOOTSZ configuration. The final two bytes are `03 08`.
- Flash pages: 64 words / 128 bytes. EEPROM: 1024 bytes. SRAM holds the working
  stack; Flash needs no additional SRAM page buffer. EEPROM uses up to 16 stack
  bytes with PUSH/POP.
- MCUSR determines entry after watchdog/software reset; external reset is the
  main bootloader-entry case. Physical DTR/RTS auto-reset needs separate testing.

## STK500v1 subset for normal avrdude `-c arduino` use

| Command | Current behavior |
|---|---|
| `0x30 GET_SYNC` | `14 10` after valid EOP. |
| `0x41 GET_PARAMETER` | SW_MAJOR=8, SW_MINOR=3, other selectors=3. |
| `0x40 SET_PARAMETER` | Consumes two fields and acknowledges; does not configure hardware. |
| `0x42 SET_DEVICE`, `0x45 SET_DEVICE_EXT` | Consumes fields and acknowledges; settings are ignored. |
| `0x50 ENTER_PROGMODE` | Acknowledges without a special mode transition. |
| `0x51 LEAVE_PROGMODE` | Acknowledges, then starts the application through WDT. |
| `0x55 LOAD_ADDRESS` | 16-bit word address multiplied by two for Flash and EEPROM, matching classic AVR `-c arduino`. |
| `0x64 PROG_PAGE`, `F` | Even lengths 2..128, 128-byte-aligned start; hardware SPM buffer, EOP checked before erase. |
| `0x74 READ_PAGE`, `F` | LPM reads; low length byte, with zero meaning 256 bytes. |
| `0x64 PROG_PAGE`, `E` | 1..16 bytes staged on the stack; EOP and range checked before writing. |
| `0x74 READ_PAGE`, `E` | EERE reads with range checking for addresses 0..1023. |
| `0x56 UNIVERSAL` | Four read-only fuse/lock queries; response `14 <byte> 10`. |
| `0x75 READ_SIGN` | Constant ATmega328P signature `1E 95 0F`. |

Supported UNIVERSAL request bodies are `50 00 00 00` (low fuse), `58 08 00 00`
(high fuse), `50 08 00 00` (extended fuse), and `58 00 00 00` (lock bits).
UNIVERSAL signature reads are absent from the current 512-byte image; use READ_SIGN.

## Differences from full AVR061

- GET_SIGN_ON returns ACK without the seven-byte `AVR STK` string.
- CHIP_ERASE and UNIVERSAL ISP chip erase do not erase, even if acknowledged.
  Do not use `avrdude -e`.
- UNIVERSAL is not an arbitrary four-byte ISP engine. Fuse/lock programming
  and UNIVERSAL signature reads are unsupported.
- Separate READ_FUSE/READ_LOCK commands are absent. SET_PARAMETER changes no
  physical settings.
- The high read/write length byte is ignored. For example, READ_PAGE length
  `0x0102` is treated as two bytes, not 258. Other out-of-range lengths are not
  supported.
- Unknown commands generally receive ACK. Bad EOP causes watchdog reset rather
  than the full set of standard STK500 error responses.
- An unknown memory type is treated as Flash. Invalid Flash write addresses
  cause watchdog reset, a stricter policy than some upstream modes.
- `CRC_EOP=0x20` is a terminator, not a CRC. Always verify by reading back.
- A UNIVERSAL `00` reply does not establish that the requested ISP operation ran.

## Source-level hardware sequence checks

These were checked with datasheets and a limited interpreter, not physical silicon.

1. SPM: fill the temporary page buffer with SPM (`SPMCSR=0x01`, then SPM).
   After EOP validation, erase with `0x03`, wait, write with `0x05`, wait, and
   re-enable RWW with `0x11`.
2. EEPROM: wait for SPM, set EEARH/L and EEDR, use EEPM[1:0]=00, and place
   SBI EEMPE / SBI EEPE within four clocks. Respond after the write completes.
3. Fuses: `SPMCSR=0x09` (BLBSET|SPMEN), then immediate LPM with Z=0..3;
   read-only access.
4. UART: 8N1, detects FE0 and does not service WDT for a framing-error byte.
5. WDT: handles MCUSR reset reasons, one-second / 16-ms configurations, and
   watchdog servicing during valid receive.

Physical validation is still required for these hardware properties.
