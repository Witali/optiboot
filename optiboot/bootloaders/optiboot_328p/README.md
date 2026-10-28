# Experimental ATmega328P assembly bootloader

`optiboot_328_verified.S` is the current AI-assisted, size-optimized assembly
implementation, with EEPROM read/write and read-only fuse/lock diagnostics.
Target: ATmega328P, 16 MHz, UART0 115200 8N1, a 512-byte boot section at `0x7E00`.
Tests use a limited software model; physical-hardware validation is pending.

See the [firmware documentation](../../../docs/atmega328p/README.md)
for functions, limits and the
research history. From the repository root:

```sh
python scripts/atmega328p/run_tests.py
python scripts/atmega328p/run_tests.py --build
```

The second command needs the LLVM AVR tools and `readelf`, plus `avr-ld` if the
assembler emits local relocations. Fresh build outputs
go in `build/`; the committed `.bin`, `.hex`, and `.o` files are the original
research artifacts. `history/` holds earlier assembly and binary variants;
historical scripts and documents are in the corresponding `scripts/atmega328p/`
and `docs/atmega328p/` directories. `reference/` holds the supplied upstream images.

From this directory, `make` builds, `make check` tests the supplied image, and
`make test` rebuilds and tests. Override `PYTHON` if necessary.

The source declares GPL-2.0-or-later and retains the original Optiboot attribution.
See `COPYING` and the repository's existing `LICENSE`.
