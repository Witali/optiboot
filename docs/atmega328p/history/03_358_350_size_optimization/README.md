# Optiboot ATmega328P: further reduction to 358 / 356 / 350 bytes

October 28, 2026. These historical experimental images were assembled and tested
in an instruction interpreter, not a physical ATmega328P. Upstream is
https://github.com/Optiboot/optiboot. The starting point was the research's
368-byte assembly image. The official reference has additional LED/SPM features.

## Results

| Image | Instructions | Version | Occupied | Characteristics |
|---|---:|---:|---:|---|
| `optiboot_mini328_previous_368.hex` | 366 | 2 | 368 | Previous image. |
| `optiboot_mini328_final.hex` | 356 | 2 | 358 | Recommended at this stage for later board tests; full UART initialization and RET at boot+2. |
| `optiboot_mini328_final_tiny.hex` | 354 | 2 | 356 | Omits the old two-byte SPM API stub. |
| `optiboot_mini328_reset_only_350.hex` | 348 | 2 | 350 | Also omits UCSR0C initialization; requires hardware/WDT reset rather than arbitrary application entry with changed UART settings. |

Each image spans `0x7E00..0x7FFF`, has FF padding and `03 08` at `0x7FFE`.
ATmega328P's minimum boot size is 256 words / 512 bytes. Reducing occupied bytes
below 512 does not increase the main application's available Flash.

## Ten-byte reduction from the 368-byte variant

1. PROG_PAGE reuses r25 as the write counter instead of MOV r19,r25 and
   SUBI r19,2: two bytes saved.
2. Shared SET_DEVICE/EXT/UNIVERSAL discard logic identifies UNIVERSAL using
   command bit 4 and BST/BRTC through T. UART and verify_eop preserve T:
   two bytes saved.
3. LSR r25 validates word count, exposing odd length in C and zero in Z;
   CPI r25,65 checks the 64-word maximum: two bytes saved.
4. LEAVE_PROGMODE and no-argument commands share verify_eop before STK_OK:
   four bytes saved.
5. Preloading SPMEN=1 in r19 costs the same code size but avoids 63 LDI
   instructions for a full page.

The 350-byte variant saves two more bytes by removing RET and six by omitting
LDI/STS UCSR0C. The datasheet's UCSR0C reset value is `0x06` (8N1). Direct entry
from an application that changed UART format can therefore fail; the main
research variant retained full initialization at 358 bytes.

## Protocol and tests

`differential_test.py` compares real instructions with upstream for 575
transactions: all 256 parameter selectors, unknown commands, addressing, Flash
read/write lengths and types, signature and LEAVE. UART bytes and Flash match.

`test_additional.py` adds 198 transactions per variant: randomized pages, even
lengths 2..128, short pages and repeated writes/readback. With direct application
entry and UCSR0C=`0x36`, the main variant restores `0x06`; the 350-byte variant
leaves `0x36`, reproducing the difference.

`test_emulator.py` and `test_invariants.py` cover bad-EOP preservation, boot
protection, SPMCSR/SPM adjacency, WDTCSR timing, MCUSR, watchdog and FE0.
Compatibility covers the tested valid subset, not every bit stream.

Intentional differences remain: invalid-length rejection, boot protection,
omitted LED/application SPM and some MCUSR changes. EEPROM programming is absent.
The SPM fill/erase/write sequence has documentary support, not physical tests.
The model abstracts electrical timing, UART and Flash, so successful checks do
not guarantee board operation.

## Original-stage commands

Python 3, Clang AVR, llvm-objcopy and readelf are required; no AVR-LibC:

```sh
python3 build.py optiboot_mini328_final optiboot_mini328_final_tiny optiboot_mini328_reset_only_350
python3 test_emulator.py
python3 differential_test.py
python3 test_invariants.py
python3 test_additional.py
```

The target is ATmega328P, 16 MHz, UART0 115200 and a 512-byte boot section.
Physical tests require a working backup and ISP recovery, checked fuses/locks
and the correct `0x7E00` destination. BIN contains boot data, not an application
image addressed to zero. Repository paths are mapped in `../../IMPORT_MANIFEST.json`.

## Further tradeoffs

- Removing six UART-init bytes requires guaranteed full reset, as in the
  350-byte variant. Retain 358 when entry compatibility matters.
- Removing length checks (about ten bytes), boot protection (four) or FE0
  handling (two) would sacrifice behavior/protection and was not recommended.
- Simpler MCUSR decisions could reduce code but change POR/WDT/EXTRF cases.
- A much smaller custom protocol would require an adapted host rather than
  unmodified avrdude/Arduino IDE.
- The 358-byte image's roughly 154 spare boot bytes could support more checks
  or minimal EEPROM functions. Further reduction alone does not expand the
  application's Flash because BOOTSZ remains unchanged.

## Original files

Three source/HEX/BIN variants; build and test scripts; OPTIMIZATION_DIFF.patch
and RESET_ONLY_DIFF.patch; BUILD_RESULTS.txt, TEST_RESULTS.txt and SHA256SUMS;
upstream_reference.bin (Optiboot 8.3); and COPYING for the GPL derivative.
