# Reproducing the handoff build and tests

This translated record describes the original archive layout. For the current
repository layout, use `../README.md` and `scripts/atmega328p/run_tests.py`.

## Tools

- Python 3.
- `clang` with AVR support: `clang -target avr -mmcu=atmega328p`.
- `llvm-objcopy`, `llvm-objdump`, `readelf`.
- GNU AVR-LibC is not needed: the assembly defines its I/O registers directly.
- `avrdude` is needed only for future physical tests, not for model tests.

The repository build additionally uses `avr-ld` when the LLVM assembler emits
local relocations, as LLVM 18 does.

## Commands in the original extracted layout

```sh
bash RUN_CURRENT_TESTS.sh
```

Or, manually:

```sh
cd CURRENT
python3 build.py
python3 test_eeprom.py
python3 test_universal.py
python3 test_differential_upstream.py
python3 test_strict_datasheet.py
python3 test_protocol_limits.py
```

`build.py` checks `_code_end`, an instruction size of at most 510 bytes,
the fixed 512-byte image length, trailing version `03 08`, and the absence of
unresolved relocations. The original script wrote `.o/.bin/.hex` beside the
source; the repository version writes to an ignored `build/` directory.
Prebuilt binaries are supplied, and the reproduced images were checked by SHA256.

`TEST_RECHECK_2026-10-28.txt` records the actual rerun made during handoff
preparation, including HEX/BIN equality. Earlier full logs are in
`CURRENT/test_all.log` and the stage directories.

## Formats

- `.S`: compilable assembly.
- `.hex`: Intel HEX with addresses `0x7E00..0x7FFF`.
- `.bin`: raw 512-byte image without addresses; do not program it at `0x0000`.
- `.o`: saved LLVM/AVR object for reproducibility.
- `upstream_reference.bin`: original Optiboot image for differential testing.
- `TEST_RECHECK_2026-10-28.txt`, `SHA256SUMS.txt`: handoff build/content checks.

## Original archive integrity

The original `SHA256SUMS.txt` covers the original file tree, excluding itself.
On a GNU system, the original layout could be checked with:

```sh
sha256sum -c SHA256SUMS.txt
```

Those original inventories are retained as provenance; the repository's
`IMPORT_MANIFEST.json` records translated paths and current content hashes.
English stage ZIPs have refreshed internal inventories.

Independent physical validation requires a real ATmega328P and an ISP programmer;
see `06_HARDWARE_TEST_PLAN.md`.
