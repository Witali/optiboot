# Optiboot Mini: experimental ATmega328P protocol extensions

October 28, 2026. Based on the 358-byte assembly Mini,
`optiboot_mini328_358.S`. Each image covers the 512-byte boot area
`0x7E00..0x7FFF`, with version `03 08` at `0x7FFE`. The derivative declares
GPL-2.0-or-later; see COPYING. These are historical research variants; current
firmware is described at `../../README.md`.

No physical ATmega328P or real-UART avrdude test was performed. The limited AVR
interpreter models EEPROM, special LPM reads and Flash.

## Images

| Image | Instructions | Version | Occupied | Free | Features |
|---|---:|---:|---:|---:|---|
| Initial Mini | 356 | 2 | 358 | 154 | Base Flash program/read. |
| `optiboot_328_diag` | 478 | 2 | 480 | 32 | EEPROM READ, read-only UNIVERSAL and SET_PARAMETER framing. |
| `optiboot_328_diag_signon` | 509 | 2 | 511 | 1 | Also GET_SIGN_ON with `AVR STK`. |

The 480-byte variant was preferred for further development because ordinary
avrdude does not need GET_SIGN_ON and the 511-byte image leaves little space.

## Added diagnostic operations

- READ_PAGE `0x74` with memory type E (`0x45`) reads EEPROM through
  EEAR/EEDR/EECR without a 128-byte SRAM buffer. It uses the byte address already
  obtained from word-based LOAD_ADDRESS, matching ATmega328P avrdude behavior
  discussed in https://github.com/Optiboot/optiboot/issues/235. It reads 1..256
  bytes, with low length zero meaning 256.
- UNIVERSAL `0x56` consumes four input bytes and returns one result byte.
  Supported read-only bodies are:

| Body | Result | Special LPM address |
|---|---|---|
| `50 00 00 00` | Low fuse | BLBSET, Z=0 |
| `50 08 00 00` | Extended fuse | Z=2 |
| `58 00 00 00` | Lock byte | Z=1 |
| `58 08 00 00` | High fuse | Z=3 |
| `30 00 n 00`, n=0,1,2 | Signature byte | SIGRD, Z=0,2,4 |

Other bodies return zero like base Optiboot and do not program fuse/lock data.

- SET_PARAMETER `0x40` consumes two fields and sends INSYNC/OK without storing
  a setting: a compatible no-op, not complete STK500 configuration support.
- The sign-on variant implements GET_SIGN_ON `0x31` as
  `14 + 'AVR STK' + 10`. Its seven-byte string is fixed at Flash `0x7FF6`;
  the build checks that address to detect accidental table movement.

Flash PROG_PAGE/READ_PAGE, GET_SYNC, GET_PARAMETER, SET_DEVICE/EXT, LOAD_ADDRESS,
READ_SIGN, LEAVE_PROGMODE, EOP validation, WDT, FE0 and SRAM-free Flash page
buffering are retained.

## Unimplemented operations and tradeoffs

- EEPROM PROG_PAGE is absent. EEPROM lacks Flash's temporary 128-byte buffer.
  EOP-before-write requires SRAM staging or a different protocol/block-size
  restriction. Streaming could partially overwrite EEPROM before a truncated
  packet is rejected, so it was not chosen as the default.
- An alternative without a fixed SRAM block would be one-byte PROG_DATA `0x61`
  (data byte plus EOP), but it needs EEPROM programming/address increment logic
  and a host using that command. Normal ATmega328P avrdude generally uses PROG_PAGE.
- Separate READ_FUSE `0x72`, READ_FUSE_EXT `0x77` and READ_LOCK `0x73` are absent;
  the values can be read through UNIVERSAL.
- READ_OSCCAL `0x76` could use SIGRD/Z=1 but did not fit with all other functions
  in the 511-byte image.
- CHIP_ERASE `0x52` is a no-op. Erasing all application pages with SPM is not
  equivalent to ISP Chip Erase and could undermine recovery. SPM cannot program
  fuses.
- STK500v2 is a separate protocol requiring a different loader/host design.

## Original-stage model checks

```sh
python3 build.py optiboot_328_diag optiboot_328_diag_signon
python3 differential_diag.py
python3 test_diag.py
```

The builds occupy 480/511 bytes with 478/509 instruction bytes; both retain the
version address. Each had 549 comparisons with upstream for unchanged commands,
matching UART and model Flash. Intentionally new semantics were excluded from
that comparison. New-code checks covered 26/27 functional transactions per
variant (EEPROM READ, fuse/lock/signature, SET_PARAMETER and optional sign-on),
plus base Flash and WDT behavior.

The interpreter omits real UART, electrical EEPROM/SPM delays and full AVR
timing/error cases. Physical tests need ISP recovery and an original-image backup.

## References and proposed follow-up

- AVR061: https://ww1.microchip.com/downloads/en/AppNotes/doc2525.pdf
- ATmega328P datasheet:
  https://ww1.microchip.com/downloads/aemDocuments/documents/MCU08/ProductDocuments/DataSheets/Atmel-7810-Automotive-Microcontrollers-ATmega328P_Datasheet.pdf
- Upstream: https://github.com/Optiboot/optiboot
- EEPROM addressing: https://github.com/Optiboot/optiboot/issues/235

The proposed next steps were physical EEPROM READ/UNIVERSAL tests with ISP
recovery; a separate EEPROM-write build using up to 128 SRAM bytes with EOP
validation before programming, followed by an actual size check; or one-byte
PROG_DATA plus a suitable host if no fixed SRAM buffer was acceptable.
