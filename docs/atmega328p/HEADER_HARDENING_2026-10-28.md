# Page-header hardening within the existing boot section

## Preparatory counter refactor

The audited baseline used 510 instruction bytes plus two version bytes, filling
the 512-byte boot section. Its BIN SHA256 was
`29fe3aa03cc412568160d1990cefa12f7674f243f8c3d6336bdc09fbe79fd642`.

The first change represents page lengths as the zero-based final byte index in
r24. Flash programming shifts that index into a zero-based final word index.
Loops use SUBI/BRCC to include index zero; the EEPROM end-address check can use
the offset directly. Flash and EEPROM write-size bounds still reject their old
invalid sizes without separate zero-count tests.

| Step | Instructions | Version | Occupied | BIN length |
|---|---:|---:|---:|---:|
| Audited baseline | 510 | 2 | 512 | 512 |
| Counter-only refactor | 504 | 2 | 506 | 512 |
| Complete length and E/F validation | 510 | 2 | 512 | 512 |

The six recovered bytes are FF padding. No capability is removed. At this
preparatory step, the old high-length/type behavior remained unchanged. The
following implementation step reinvests those six bytes in validation.

All five existing regression suites passed against the refactored BIN, including
the 556 upstream differential transactions, full EEPROM round trips, fuse/lock
queries, Flash alignment checks and the old documented protocol-limit behavior.
The counter-only BIN SHA256 is
`37eeb2872e39f548f3e0139c589f769332fa612cb9a2a5d8629e7222e7a429b5`.

The source and current BIN/HEX/object artifacts are updated together. Original
source/image/object snapshots remain in history and the stage archives. The
import manifest records both the handoff hashes and current working versions.
These measurements and tests use software tools; physical-board testing remains
pending.

## Completed header validation

Both READ_PAGE and PROG_PAGE now call one `read_header` helper. It accepts the
complete unsigned length only in `0x0001..0x0100` and memory type only E/F.
Invalid headers enter the existing short-watchdog abort loop before a memory
read, SPM buffer fill, erase, write or EEPROM access. No unsupported feature was
removed and no dedicated SRAM buffer was introduced.

The byte budget is unchanged from the audited baseline: 510 instruction bytes
plus two version bytes, filling the same 512-byte boot section at
`0x7E00..0x7FFF`. Version bytes remain `03 08` at `0x7FFE..0x7FFF`.

### Why the checks fit

The parser receives the full length into r25:r24 and subtracts one with SBIW.
For a 16-bit input N, the high byte of `(N-1) mod 65536` is zero exactly when
`1 <= N <= 256`. Zero becomes FFFF; values above 256 retain a nonzero high byte.
The low byte is already the zero-based final index required by the refactored
loops and EEPROM end-address check.

Memory types E/F are adjacent values 45/46. The parser stores their low bit in T,
subtracts 45 and accepts only results below two. Thus every other byte is rejected.
Read and write callers branch using T; the receive and EOP routines preserve it.
The shared parser grows by 16 bytes versus the preparatory parser, while its
callers shrink by ten bytes: a net six-byte addition.

The instruction choices follow Microchip's
[SUBI flag definition](https://onlinedocs.microchip.com/oxy/GUID-0B644D8F-67E7-49E6-82C9-1B2B9ABE6A0D-en-US-23/GUID-97B6BD58-B46B-4037-AF73-2FD88C822D29.html),
[conditional branch summary](https://onlinedocs.microchip.com/oxy/GUID-0B644D8F-67E7-49E6-82C9-1B2B9ABE6A0D-en-US-23/GUID-38931E58-9CEC-40B0-AE87-4A97EF329AB8.html),
and [T-bit description](https://developerhelp.microchip.com/xwiki/bin/view/products/mcu-mpu/8-bit-avr/structure/status/).
The timed SPM, EEPROM and watchdog instruction pairs are retained and pass the
existing static/instruction-level checks.

### Preserved and intentionally changed behavior

- Valid reads accept every length 1..256 for Flash and EEPROM. A 256-byte read
  uses `01 00`; the formerly tolerated zero-length `00 00` is rejected.
- Flash writes retain even lengths 2..128, 128-byte start alignment, boot
  protection and EOP-before-erase behavior.
- EEPROM writes retain lengths 1..16, stack staging, range checks and
  EOP-before-programming behavior.
- An oversized declaration cannot be silently truncated to its low byte.
  An unknown memory type cannot fall back to Flash.
- Remaining sign-on, chip-erase, arbitrary ISP and programmer-setting limits
  are unchanged. Error handling still uses the existing watchdog abort policy.

## Verification

The new direct reproduction test failed against the audited old BIN because
the oversized-prefix packet changed Flash. It passes against the hardened BIN.
The old assertions documenting ignored high bytes and unknown-type fallback
were replaced by positive legal-packet checks, with rejection verified by the
new independent boundary suite; no malformed-packet success is treated as correct.

| Check | Result |
|---|---|
| Existing functional regressions and updated remaining-limit checks | Passed. |
| New default header suite | 2078 rejected cases, 512 valid reads, 80 valid writes, 40 split-packet cases. |
| Exhaustive shared-parser length pass | All 65,280 invalid 16-bit lengths rejected; 67,358 rejected cases including the default boundary cases. |
| Memory-type space | Every one of the 254 undefined types rejected at both read and write entry points. |
| Client-profile audit | All 44 supported-profile checks and three header-protection assertions passed. |
| Toolchain comparison | LLVM/Clang and GNU AVR-GCC produced identical 512-byte BINs. |
| Flash/EEPROM/fuse checks | Full EEPROM, 556 upstream transactions, page alignment, boot protection and timed instruction-pair tests passed. |

The complete current audit is in
[`PROTOCOL_HARDENING_RESULTS_2026-10-28.json`](PROTOCOL_HARDENING_RESULTS_2026-10-28.json).
The earlier report and JSON remain the pre-hardening observations.

Current artifacts:

| Artifact | SHA256 |
|---|---|
| BIN | `8248d39c5768dde48708c47de1f3d4872dfc1b9d519853641aa307ba92ae200e` |
| HEX | `5cf8d1053840d3c4613b66131a56f942649ecfe54699f7caf69925b6db8748db` |

```sh
make -C optiboot/bootloaders/optiboot_328p test
python scripts/atmega328p/test_header_validation.py --exhaustive
python scripts/atmega328p/audit_protocol.py \
  --output docs/atmega328p/PROTOCOL_HARDENING_RESULTS_2026-10-28.json
```

These are assembled-code software-model results. Actual MCU, UART and reset
timing tests remain pending; there is no claim of full AVR061 implementation.
