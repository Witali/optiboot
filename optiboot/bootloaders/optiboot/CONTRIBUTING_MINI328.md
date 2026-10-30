# Contributing to Optiboot Mini 328P

## Language and repository integration policy

**English is required for every project-facing artifact**, including:

- AVR assembly source files and inline comments;
- Python, shell, and Makefile comments, messages, assertions and docstrings;
- README files, hardware test plans, commit messages, pull-request descriptions and changelogs;
- test descriptions, expected-failure explanations, release notes, and generated documentation;
- file and directory names (do not introduce locale suffixes such as `_RU`).

The original upstream Optiboot files should remain unchanged unless a separate, reviewed change is explicitly required. Keep the derivative as an optional `make mini328` target and avoid overwriting stock `optiboot.c` or `optiboot_atmega328.hex`.

## Compatibility and regression policy

1. Preserve `avrdude -c arduino`, STK500v1 framing, and the established Optiboot Flash programming behavior.
2. Preserve the added EEPROM read/write/verify operations, supported read-only fuse/lock `STK_UNIVERSAL` opcodes, and `GET_SIGN_ON`.
3. Remain within the 512-byte boot section at `0x7E00–0x7FFF` for the specified ATmega328P at 16 MHz.
4. Do not remove watchdog, EEPROM/SPM interlocks, Flash boot-boundary checks or address validation to save bytes.
5. Rebuild the AVR BIN and HEX, check the new size and address map, and rerun the integration tests, English-only checker, and archived software regression tests.
6. A changed binary needs a new SHA-256 reference and an explanation of the behavioral differences. Do not silently reuse the previous reference.
7. Keep hardware validation claims separate from simulator results. Real-chip and real-AVRDUDE testing is still outstanding.

## Minimum maintainer checks

```sh
make mini328_check
make mini_test
python3 /path/to/unpacked-package/scripts/verify_master_patch.py
python3 /path/to/unpacked-package/scripts/verify_package.py
```

The historical QA suite lives in `qa/regression_suite_512.zip` in the integration package. Its scripts can be executed after extracting it with a tool that preserves executable permissions, for example Unix `unzip`:

```sh
unzip regression_suite_512.zip -d qa-tests
cd qa-tests
./run_all_tests.sh
```

Running the Python ZIP extractor may not preserve executable mode bits; in that case use `bash run_all_tests.sh` and set executable permissions on the nested shell scripts.

## Documentation checklist for new capabilities

When a new function is introduced, update `README_MINI328_AVRDUDE.md` with its STK500v1 opcode, packet/response format, an AVRDUDE command example (if applicable), hardware prerequisites, limitations, and whether the behavior was verified by simulation or on an actual board. Update the main `README_MINI328.md` only when the feature changes its concise feature summary.
