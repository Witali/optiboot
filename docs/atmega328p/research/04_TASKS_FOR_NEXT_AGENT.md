# Historical development handoff: proposed next tasks

This translated task list records the research handoff. It does not authorize
additional work in the current repository session.

## Established state

- Target: an STK500v1 subset on ATmega328P, 16 MHz, UART0.
- Latest source: `CURRENT/optiboot_328_verified.S` in the original layout.
  It occupies all 512 bytes; earlier 508/498/358-byte builds are historical.
- EEPROM: 1024-byte read/write, 1..16-byte writes staged on the SRAM stack,
  EOP validation before writing. Flash uses its hardware SPM buffer without an
  SRAM page array. UNIVERSAL only reads fuse/lock bits.
- Validation is software-only. The custom AVR interpreter and tests are supplied.
  The original build needs Clang AVR and LLVM object tools.

## P0: preserve behavior and test physical hardware

1. Check WDE/reset reasons, SPM Z/PCWORD=0, EEMPE-to-EEPE timing, stack and boot
   locks against the datasheet. Retain checks unless an equivalent safe replacement
   is established.
2. Test a real ATmega328P through USB/UART with ISP recovery and an original
   bootloader backup. Do not describe it as production-ready without those tests.
3. Rebuild and run all suites after each change. Compare real AVR instructions
   with the previous firmware and fail the build if it exceeds 512 bytes.

## P1: improve STK500v1 compatibility safely

4. Prioritize the ignored high length byte. Reject unsupported sizes safely
   rather than silently processing a different length; retain the 512-byte limit.
5. Assess explicit rejection of CHIP_ERASE and unsupported UNIVERSAL operations
   (ISP chip erase, fuse/lock writes), preserving synchronization with real avrdude.
6. Reject invalid memory types instead of returning Flash as nonexistent EEPROM.
7. Consider UNIVERSAL signature/OSCCAL diagnostics only after preserving EEPROM
   and normal avrdude behavior.

## P2: optimize without removing needed functions

8. Investigate register reuse, shared EEPROM receive/transmit paths, handler
   placement for compact BRxx, shared SPM/EEPE waiting and efficient length/page
   checks. AVR instructions occupy two or four bytes; relative branches can
   constrain layout.
9. Compare identical features. The official 474-byte image includes LED and
   application-callable SPM, which this implementation omits.
10. Seek actual free space, for example 10..30 bytes, for stronger protocol checks
    before adding low-value commands.

## Proposed acceptance criteria

- Assembly compiles; the final image has no unresolved relocations. BIN is 512
  bytes, HEX addresses `0x7E00..0x7FFF`, and the final version bytes are `03 08`.
- Valid shared commands pass regression against the previous and upstream images.
- Tests include the full 1 KiB EEPROM, wrong EOP, truncated packets, range errors,
  Flash read/write including the last application page, fuse/lock reads, WDT/FE0,
  and instruction timing windows.
- For each new command, document input/output format, avrdude support and
  intentionally unsupported cases.
- Do not claim full AVR061 before implementing it. Document physical power-loss
  risks for Flash/EEPROM writes.

## Original-layout quick start

```sh
cd CURRENT
python3 build.py
python3 test_eeprom.py
python3 test_universal.py
python3 test_differential_upstream.py
python3 test_strict_datasheet.py
python3 test_protocol_limits.py
```

The handoff recommended continuing from `optiboot_328_verified.S` and reading
`CURRENT/AUDIT.md` first. For current repository paths, see `../README.md`.
