# Import validation, 2026-10-28

The 266-file research handoff was imported into the `experimental` branch.
All 263 entries covered by the original JSON manifest matched their recorded
sizes and SHA256 values before import. The repository import manifest accounts
for all 266 files, including the original inventories and seven nested stage ZIPs.

## Current firmware

| Artifact | SHA256 |
|---|---|
| `optiboot_328_verified.S` | `b82b6b2a4c312e6765e869963ad6ba87b7f26b383e4823f6c3c8b7d1e1126b89` |
| `optiboot_328_verified.bin` | `29fe3aa03cc412568160d1990cefa12f7674f243f8c3d6336bdc09fbe79fd642` |
| `optiboot_328_verified.hex` | `3918a262913d19514350c4bc3e41b8a91b7f95fd0fcb5a43a2abb01a65fa5a8b` |

The supplied BIN passed all five current regression suites under Python on
Windows. The unchanged assembly was then rebuilt under Ubuntu WSL with Clang
18.1.3, GNU `avr-ld`, `readelf`, and LLVM object tools:

```sh
make -C optiboot/bootloaders/optiboot_328p test
```

Clang 18 emits local branch relocations. The adapted build script resolves them
with `avr-ld` without linker relaxation and verifies the resulting image.
The rebuilt BIN and HEX matched the supplied files byte for byte. The build
reported 510 bytes of instructions plus two version bytes, occupying 512 bytes.
All five suites passed again against the rebuilt BIN:

| Suite | Result |
|---|---|
| `test_eeprom.py` | 598 valid transactions plus negative cases; full 1 KiB EEPROM round trip and Flash/reset regression. |
| `test_universal.py` | 24 fuse/lock reads, 762 unsupported queries, EEPROM/Flash regression and negative cases. |
| `test_differential_upstream.py` | 556 transactions with identical UART responses and application Flash versus the supplied upstream reference. |
| `test_strict_datasheet.py` | Instruction-adjacency checks, 25 aligned Flash transactions, five rejected unaligned starts, EEPROM and fuse/lock regression. |
| `test_protocol_limits.py` | Existing sign-on, chip-erase, length-field and memory-type limitations reproduced. |

Python files were checked for syntax and the new documentation's relative links
were checked for valid destinations. Historical stages and their old test logs
are preserved as research evidence; they were not individually rebuilt or
revalidated during this import.

These results use the supplied limited software AVR model. No physical MCU,
ISP programmer, electrical measurements, or real USB/UART exchange was tested.
