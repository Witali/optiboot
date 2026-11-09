# Import compatibility validation, 2026-11-09

Source archive: `Optiboot_VirtualBoot_PageAligned_512_576_2026-11-08.zip`.
SHA-256: `9e7a209c8b760f7e004d7169b931269719b6b509c9b279a877d22019a7037dc9`.
Repository base: `cc260444d54aaff41e36837d7ce3c772a2dbfbc0`.

## Compatibility outcome

All 63 active Middle/Full profiles rebuild successfully. Each rebuilt BIN is
byte-for-byte identical to its supplied release BIN; every decoded Intel HEX
contains the same bytes at the same absolute addresses. The reference metadata
also checks CPU clock, clock source, UART baud, boot origin, and reservation.
The four ATtiny Middle images also match when assembled with AVR-GCC.

| MCU | Payload | Reservation | Boot origin |
|---|---:|---:|---|
| ATtiny84/85 | 549 B | 576 B | `0x1DC0` |
| ATtiny841 | 505 B | 512 B | `0x1E00` |
| ATtiny1634 | 501 B | 512 B | `0x3E00` |

Full remains 1024 bytes. The product matrix still contains 25 Middle and 38
Full profiles. Thirteen ATmega with 1024-byte hardware minimum remain Full-only.
No imported firmware assembly, UART include, or device include was changed.

The earlier hardened ATmega328P implementation keeps its source, images,
protocol contract, and build entry point. Its six original suites were rebuilt
and passed independently, including 556 differential STK500v1 transactions and
header validation covering 2078 rejections, 512 valid reads, 80 valid writes,
and 40 truncated-packet scenarios.

## Reproduced checks

Environment: Ubuntu WSL, Python 3.12.3, Clang/LLVM 18.1.3, GNU AVR binutils,
AVR-GCC 7.3.0. Commands from this module:

```sh
python3 run_tests.py
python3 -m unittest mini_tests.test_release_compatibility mini_tests.test_flash256_avrdude -v
make mini328_check
```

The complete imported run registered 254 firmware/model tests: **217 passed,
37 explicitly skipped**, with zero failures or errors. All **11 generator
tests passed**. The additional host/release run passed **7/7**, including a new
512-byte Boot-boundary preparation check added after the full run began.
Some host/release cases overlap the main run and are not additional unique tests.
The runner prepares both the automatic-signature release matrix and a separate
63-profile constant-signature matrix for reset/SPM peripheral models.

Covered behavior includes:

* Synchronization, parameters, signatures, and the supported STK500v1 command
  subset; Full GET_SIGN_ON and read-only fuse/lock queries.
* Flash/EEPROM read/write, malformed packets, application and Boot boundaries,
  128/256 KiB banked addressing, and legacy UART mappings.
* Reset/MCUSR combinations across 38 MCU, application SPM on 34 ATmega,
  direct application SPM on four ATtiny, ABI preservation, and Boot guards.
* Bit-level software UART timing, watchdog idle behavior, and RC/external-clock
  build policies in the supplied models.
* Virtual Boot automatic and explicit 576/640-byte reservations, the last
  application erase group, refusal to erase Boot, ISP seed, and reset/EE-ready
  vector patching.
* Generator selection, invalid combinations, clock parsing, HEX/BIN integrity,
  and known unsupported legacy ATmega64A Full EEPROM mode.

The 37 skips are historical R3–R8 snapshot comparisons and old object/BIN
fixtures absent from this ZIP. They are explicitly reported, not counted as
successful compatibility checks. Current checks that previously expected the
old ATtiny reservation now use the November release contract; unchanged ATmega
Compact images retain their R10 hash comparisons. Raw historical reports and
the older 115-profile inventory describe their original dates.

## Import adaptations

* Resolve local relocations emitted by LLVM 18/GNU as using the object's AVR
  architecture, section origin zero, and no linker relaxation. Reject unresolved
  relocations or linker errors before producing firmware.
* Pass plain numeric assembler definitions rather than C-only UL suffixes.
* Correct the obsolete low-level default ATmega328P baseline pin to the hash
  already recorded in the imported multidevice test. Legacy mini328_check now
  has its required checksum file. The assembly itself is unchanged.
* Generate current test prerequisites instead of depending on an author's old
  output directory. Report absent historical snapshots as skips.
* Add a standalone module Makefile and test runner; original upstream targets
  and the hardened ATmega328P tree are preserved.
* Let HEX preparation select 256-byte Flash256 or 512-byte FlashRead512 Boot
  boundaries. The old 256-byte default remains; 512-byte preparation now rejects
  application pages inside the larger reserved region.
* Translate imported Russian documentation into English, preserve historical
  numbers/status, and record source hashes and adaptation status in the manifest.

## Limits

These checks execute the supplied limited AVR models and compilers. They do
not establish compatibility with a physical AVR, an actual serial AVRDUDE or
Arduino IDE session, real oscillator drift, fuse/lock behavior, power failure,
or hardware SPM/EEPROM timing. The minimal Flash256/FlashRead512 host restrictions
and the tiny tools' legacy 1024-byte defaults remain documented.
No device was flashed during this import. Initial Virtual Boot installation,
reservation changes, and recovery require ISP and matching vector patches.
