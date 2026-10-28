# Optiboot Mini ATmega328P: Flash, EEPROM R/W and UNIVERSAL fuse/lock reads

October 28, 2026. Experimental ATmega328P / Uno, 16 MHz, UART0 115200 8N1.
No physical tests were performed. This is the historical 508-byte stage;
the later alignment fix produces the current 512-byte image.

## Result

| Measure | Previous | This stage |
|---|---:|---:|
| Instructions | 496 bytes | 506 bytes |
| Version | 2 bytes | 2 bytes |
| Occupied / boot size | 498/512 | 508/512 |
| Spare space | 14 bytes | 4 bytes |
| EEPROM R/W | Yes | Yes |
| UNIVERSAL `0x56` | Zero-result stub | Fuse/lock reads |
| Fixed EEPROM SRAM array | 16 bytes at `0x0100` | None |
| Temporary EEPROM staging | 16-byte array | Up to 16 stack bytes |
| Flash without SRAM page array | Yes | Yes |

BIN/HEX spans `0x7E00..0x7FFF`; four spare bytes are FF and the last two are
version `03 08`.

## UNIVERSAL additions

UNIVERSAL consumes four ISP bytes plus EOP `0x20` and replies with INSYNC,
one result byte and OK.

| Body | Result | LPM Z address |
|---|---|---|
| `50 00 00 00` | Low fuse | 0 |
| `58 00 00 00` | Lock bits | 1 |
| `50 08 00 00` | Extended fuse | 2 |
| `58 08 00 00` | High fuse | 3 |

For those opcode1/opcode2 pairs, fields three and four are ignored, usually zero.
Other bodies return zero without programming anything. Arbitrary ISP, fuse/lock
writes, Chip Erase and signature reads through `0x56 30...` are unsupported.
READ_SIGN `0x75` separately returns `1E 95 0F`.

```asm
    clr  r31             ; Z = 0..3
    ldi  r16,0x09        ; BLBSET|SPMEN
    out  0x37,r16        ; SPMCSR
    lpm  r16,Z           ; Read fuse/lock within the required timing window.
```

Fuse/lock values are read using LPM; SPM programs Flash.

## Size and SRAM changes

1. Removed the fixed EEPROM array. Receive uses PUSH, and after valid EOP, POP
   retrieves bytes in reverse order. Z already holds the final EEPROM address,
   so writes proceed backward. This saved 12 bytes at an intermediate point
   without losing EOP-before-write. The stack still temporarily uses up to
   16 SRAM bytes.
2. Reused existing wait_spm for EEPROM instead of a duplicate busy loop.
3. PROG_PAGE type selection uses CPI/BREQ without intermediate MOV/RJMP.
4. Simplified SET_PARAMETER and shared verify_eop for already-received data.
5. Uses T with BST/BLD for fuse/lock selectors without an extra counter register.
6. After EEPE clears, one OUT sets EECR=0 instead of two CBI instructions for
   EEPM bits. Interrupts are disabled in this loader.
7. Moved EEPROM read EEPE waiting outside the per-byte loop.

Full UART initialization including UCSR0C, WDRF/EXTRF/POR handling, WDT,
UART framing checks, EEPROM length/range checks and boot-write protection remain.

## STK500v1 / avrdude behavior

GET_SYNC, GET_PARAMETER, SET_PARAMETER (consumes two bytes, ignores settings),
SET_DEVICE/EXT, ENTER/LEAVE_PROGMODE, LOAD_ADDRESS, Flash/EEPROM PROG_PAGE and
READ_PAGE, and READ_SIGN accompany UNIVERSAL.

- Flash writes accept even lengths up to 128; reads are block-based. The SPM
  buffer replaces an SRAM page array.
- EEPROM writes are 1..16 bytes; reads up to 256; ranges and EOP are checked.
  Writes are not atomic against power failure.
- LOAD_ADDRESS uses words multiplied by two, matching classic AVR
  `avrdude -c arduino`. A separate odd EEPROM start is unavailable, but blocks
  include odd-addressed bytes.
- CRC_EOP is not a CRC; verify the payload by reading back.
- Fuse-write commands and ISP sequences such as AC A0 do not execute; the
  result remains zero.

The proposed board test, after ISP installation, used:

```sh
# Select the actual port, such as /dev/ttyUSB0, /dev/ttyACM0 or COM3.
avrdude -p m328p -c arduino -P /dev/ttyUSB0 -b 115200 -U eeprom:r:backup.bin:r
# Read-only fuses, if supported by that avrdude version through the loader.
avrdude -p m328p -c arduino -P /dev/ttyUSB0 -b 115200 -U lfuse:r:-:h -U hfuse:r:-:h -U efuse:r:-:h
```

Back up Flash/EEPROM before changes, check fuses against the actual board and
retain ISP recovery. This image belongs at `0x7E00` in a 512-byte boot section,
not the application at zero. Typical Uno high fuse `0xDE` assumes compatible
hardware and is not an instruction to change unknown settings.

## Recorded validation

- Clang AVR / llvm-objcopy build: no unresolved external relocations, 506
  instruction bytes, two version bytes, four FF bytes and a 512-byte BIN.
- `test_eeprom.py`: 598 valid transactions plus negative cases, full EEPROM,
  Flash program/verify, bad EOP, invalid addresses and truncated packets.
- `test_universal.py`: 24 fuse/lock reads, 762 unsupported requests, blocked
  ISP writes, EEPROM/Flash after fuse reads and bad EOP. The model requires
  BLBSET|SPMEN before LPM and clears the mode after reading.
- `test_differential_upstream.py`: 556 old-subset commands with matching UART
  and application Flash. SET_PARAMETER is intentionally excluded because
  upstream treats it as an unknown no-argument command, while this image
  consumes its two fields.
- No physical MCU, real UART/avrdude session, hardware SPM/LPM/EEPROM timing
  or transmission-error measurement was available.

## Original files and commands

The original assembly/image stem is `optiboot_328_eeprom_universal`. Prior
498-byte source/image records, `changes_from_498B.diff`, simulator and tests,
`build.py`, `test_full.log` and COPYING accompany it. The handoff inventory also
records alternate `optiboot_328_eeprom_rw` names used by saved artifacts; use
`../../IMPORT_MANIFEST.json` for actual repository destinations.

```sh
python3 build.py
python3 test_eeprom.py
python3 test_universal.py
python3 test_differential_upstream.py
```

Sources:

- https://github.com/Optiboot/optiboot
- https://github.com/avrdudes/avrdude/blob/main/src/stk500.c
- https://docs.arduino.cc/resources/datasheets/Atmel-42735-8-bit-AVR-Microcontroller-ATmega328-328P_Datasheet.pdf
