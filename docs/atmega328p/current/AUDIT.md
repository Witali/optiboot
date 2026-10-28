# Optiboot Mini EEPROM + UNIVERSAL audit: ATmega328P

**Date:** October 28, 2026.  
**Objects:** historical `optiboot_328_eeprom_universal.S` (506 instruction bytes
plus two version bytes = 508), and corrected `optiboot_328_verified.S`
(510+2 = 512).  
**Method:** source, AVR object and machine-code inspection, official
specifications and a limited machine-code interpreter. No physical MCU test.

## Findings

- The corrected image passes the supplied software tests for Flash, EEPROM and
  fuse/lock diagnostics within the ordinary ATmega328P avrdude `-c arduino`
  command subset.
- It is not a complete AVR061/STK500v1 implementation or a hardware STK500.
- A significant issue was found: SPM Page Write did not guarantee Z PCWORD=0.
  The corrected image accepts only 128-byte-aligned Flash starts and rejects
  unaligned addresses before SPM.
- Physical UART, SPM, EEPROM, fuse/lock and watchdog behavior under load remain
  unverified. The image is experimental.

## 1. ATmega328P datasheet checks

| Subsystem | Code behavior | Datasheet reference | Finding |
|---|---|---|---|
| Boot placement | `0x7E00..0x7FFF`, BOOTSZ=256 words | 26.3, 26.4 and memory tables | Correct for matching BOOTSZ/BOOTRST fuses. |
| AVR stack | Reset SP=RAMEND, RCALL/RET and PUSH/POP, CLI before EEPROM | 6.5–6.5.1 | Assumes reset initialization; stack consumes SRAM. |
| Temporary SPM buffer | R1:R0, Z, OUT SPMCSR=01 immediately before SPM, address +2 | 26.8, 26.8.2 | Fill-before-erase is explicitly permitted. |
| Erase/write | `03 -> SPM`, wait, `05 -> SPM`, wait, RWW enable `11 -> SPM` | 26.8.1, 26.8.3, 26.8.6 | Valid at page-aligned addresses; arbitrary old starts were a defect. |
| Page address | 64 words / 128 bytes, PCWORD=0 | 26.8.3, 27.9 | Corrected by rejecting unaligned starts. |
| Boot protection | CPI r23,7E after EOP, before erase | 26.8.5 | Software protection for aligned writes; hardware BLB11 protection is also recommended. |
| EEPROM address/data | EEARL=I/O 21, EEARH=22, EEDR=20 | 12.6.1–12.6.3, Atmel-42735B/2016 | Checks full 0..1023 range and length. |
| EEPROM ready/read | Poll EEPE, SBI EECR,EERE, IN EEDR | 12.6.4 | Matches the documented sequence. |
| EEPROM write | OUT EECR=0 selects EEPM=00; adjacent SBI EEMPE / EEPE | 12.6.4 | Within the four-clock window; interrupts are disabled. |
| EEPROM/SPM coordination | wait_spm before EEPROM, wait EEPE=0 before replying | 12.6.4, 26.8.8 | Matches the normal command sequence. |
| Fuse/lock read | Z=0..3, SPMCSR=09, immediate LPM r16,Z | 26.8.9 | Within the three-clock window. |
| Watchdog | Clear MCUSR before disabling WDE; timed STS pair, 0E/08 intervals | 10.8–10.9 | Assumes ordinary fuses with WDTON unprogrammed. |
| UART0 | U2X=1, RXEN/TXEN, UCSZ=3, UBRR=16 at 16 MHz | 19.3, 19.10 | About 117647 baud, +2.12% versus 115200; physical noise tolerance untested. |

References examined during research:

- Atmel-7810D (2015): https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7810-Automotive-Microcontrollers-ATmega328P_Datasheet.pdf
- Atmel-42735B (2016), especially EEAR9/EEAR8 in section 12.6.1:
  https://docs.arduino.cc/resources/datasheets/Atmel-42735-8-bit-AVR-Microcontroller-ATmega328-328P_Datasheet.pdf
- Microchip DS40002061B:
  https://www.microchip.com/content/dam/mchp/documents/MCU08/ProductDocuments/DataSheets/ATmega48A-PA-88A-PA-168A-PA-328-P-DS-DS40002061B.pdf

The 2015 automotive datasheet's EEARH table on page 20 shows only EEAR8 despite
describing 1 KiB EEPROM. Later ATmega328/P documentation explicitly gives
EEAR9:8 in the two low EEARH bits. The firmware's r27 handling for
`0x200..0x3FF` follows that corrected table.

### Previous Page Write defect

The 508-byte image loaded Z directly from an arbitrary even request address:

```asm
    movw r30, r22
    ldi  r16, 0x05
    rcall spm_execute_wait
```

Section 26.8.3 requires low page-word bits of Z to be zero for Page Write.
Ordinary avrdude page starts meet this condition, but LOAD_ADDRESS could supply
other even addresses. The corrected source checks before filling SPM:

```asm
    mov  r16, r22
    andi r16, 0x7F
    brne protocol_error
```

The six-byte check fits within 512 bytes by removing the old two-byte RET stub.
Application-callable SPM had already been omitted; applications using the former
boot+2 entry are incompatible. Unaligned writes now abort through WDT without
SPM/erase rather than attempting a partial-page preservation operation.
Normal avrdude 128-byte pages, including short last-page payloads, begin aligned.

## 2. AVR061 / STK500v1 comparison

Protocol reference: https://ww1.microchip.com/downloads/en/AppNotes/doc2525.pdf

| Command / field | Behavior and limits |
|---|---|
| GET_SYNC 30 | INSYNC, OK. |
| GET_PARAMETER 41 | Software major 8, minor 3, other selectors 3; Optiboot-like rather than a general STK500. |
| SET_PARAMETER 40, SET_DEVICE 42, SET_DEVICE_EXT 45 | Consume fields/EOP, ACK, ignore configuration. |
| ENTER/LEAVE 50/51 | ACK; LEAVE starts the application through WDT. |
| LOAD_ADDRESS 55 | 16-bit word address times two, including EEPROM for classic AVR `-c arduino`. |
| PROG_PAGE 64, F | Even 2..128-byte payload, 128-byte-aligned start. |
| READ_PAGE 74, F | LPM reads; low length byte, zero means 256. |
| PROG_PAGE 64, E | 1..16 bytes on stack until EOP; sequential EEPROM writes. |
| READ_PAGE 74, E | EERE reads within 0..1023. |
| UNIVERSAL 56 | Four read-only fuse/lock opcode combinations; others return zero. |
| READ_SIGN 75 | Constant `1E 95 0F`. |
| GET_SIGN_ON 31 | ACK only, no AVR STK string. |
| CHIP_ERASE 52 / UNIVERSAL AC 80 | ACK / zero without erasing. Do not use `-e`. |
| Separate READ_FUSE / READ_LOCK | Absent; supported reads use UNIVERSAL. |
| Unknown command / bad EOP | Unknown commands usually ACK; bad EOP triggers fast WDT, not all AVR061 UNKNOWN/NOSYNC responses. |
| bytes_high | Received but ignored; READ_PAGE 0102 reads two rather than 258 bytes. |
| Invalid memtype | Anything other than E becomes Flash. |

CRC_EOP `0x20` is only an end marker. It does not detect silent UART payload
corruption; use avrdude verify/readback. The research checked host EEPROM block
and word-address handling in avrdude `src/stk500.c`, including
`set_memchr_a_div`, `stk500_paged_write` and `stk500_paged_load`:
https://github.com/avrdudes/avrdude/blob/main/src/stk500.c

## 3. Build and software tests

The assembled object, Intel HEX and full BIN were checked for placement
`0x7E00..0x7FFF`, version `03 08` at `0x7FFE..0x7FFF`, 512-byte length and no
unresolved relocations. The original tools were Clang AVR and llvm-objcopy.

- EEPROM: 598 valid exchanges including all EEPROM, plus negative cases.
- UNIVERSAL: 24 fuse/lock reads, 762 unsupported requests and subsequent
  EEPROM/Flash regression.
- Upstream differential: 556 transactions with identical UART and application
  Flash for the shared subset.
- Strict checks: assembled SPMCSR/SPM/LPM and EEMPE/EEPE adjacency, aligned Z
  for 25 page transactions, five rejected unaligned starts, EEPROM and fuse tests.
- Protocol-limit tests reproduce known sign-on, erase, high-length and unknown
  memory-type behavior.

The limited Python interpreter does not fully model analog UART, timers,
physical nonvolatile memory, interrupts, temperature or supply conditions.
Three-/four-clock checks rely on instruction adjacency in the assembled image.
Physical hardware is necessary for final confirmation.

## 4. Operational limits and proposed precautions

1. Do not use `avrdude -e` or fuse/lock writes with `-c arduino`; an ACK may
   mean no operation occurred. Use a suitable ISP/HV programmer for those tasks.
2. Retain boot lock-bit protection when loader self-update is not needed.
   The software `0x7E00` check is not hardware protection.
3. Use ATmega328P, not 328PB, an external 16 MHz clock/Uno, matching
   BOOTRST/BOOTSZ for 512 bytes and UART0 115200. Other clocks require UBRR
   changes and testing.
4. Flash starts must align to 128 bytes; EEPROM writes use 1..16-byte packets
   and classic Arduino word addressing.
5. Verify programmed Flash/EEPROM by reading back (`-U flash:v:...`,
   `-U eeprom:v:...`, or normal avrdude verify). Power loss can leave a 16-byte
   EEPROM block partially written.
6. Flash programming is vulnerable to power loss even with correct sequencing.
   Consider BOD, reliable power and ISP recovery.
7. No spare byte remains. Stronger protocol checks require additional
   optimization or removing functions.

## 5. Original-layout local commands

```sh
python3 build.py
python3 test_eeprom.py
python3 test_universal.py
python3 test_differential_upstream.py
python3 test_strict_datasheet.py
python3 test_protocol_limits.py
```

For current repository commands see `../README.md`. The HEX is experimental;
physical-hardware validation has not been performed.
