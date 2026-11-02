# Shared microcontroller database

[`devices.json`](../../optiboot/bootloaders/optiboot/devices.json) is the
authoritative per-MCU data source for the Mini, Middle and Full build tools.
It retains the existing device records, field names and ordering. The former
parallel MCU tuple list in `gen_devices.py` has been removed. Generation reads
the database and never rewrites it.

Register addresses, assembly `#define` constants and the include-file format
are not moved into JSON. Existing architecture templates in
[`device_database.py`](../../optiboot/bootloaders/optiboot/device_database.py)
render the same `devices/*.inc` files as before. Those files continue to supply
the firmware constants; `devices/select.inc` selects one MCU from its compiler
macro. Audited low-level assembly-mode allowlists and compiler compatibility
exceptions remain separate from device geometry.

## Data and consumers

The JSON maps each lowercase MCU name to one record:

| Fields | Meaning |
|---|---|
| `flash`, `eeprom`, `page`, `flash_erase_group_bytes` | Memory sizes and programming geometry, in bytes |
| `sig` | Three signature bytes; shared signatures between related parts are allowed |
| `ramend` | SRAM end address, not SRAM capacity |
| `max_mhz`, `profile` | Existing project clock rating and architecture template |
| `default_boot`, `hardware_min_boot_bytes`, `virtual_boot` | Default reservation and physical/Virtual Boot geometry |
| `spm512_capable`, `wide_branches`, `wdt_ccp_style` | Existing reviewed assembly capabilities |
| `sigrow_lpm_supported_by_datasheet` | Whether the hardware signature-row path has been audited |
| `dual_compact_enabled` | Existing eligibility flag for Middle; the legacy field name is preserved |

`device_database.load_devices()` validates the complete input before builders
use it. It rejects duplicate keys, missing/unknown fields, invalid types,
malformed signatures, inconsistent Boot layouts and unsupported geometry.
These checks establish internal consistency; datasheet review remains necessary
to establish the accuracy of hardware facts and register templates.

`build_mini.DEVICES` remains a compatibility export of the same shared data.
The public generator, paired builder and Mini target list use the shared
edition policy. Virtual Boot patching, ISP seed creation and the ATtiny host
reuse the same Flash sizes, signatures, erase groups and vector definitions.
The fixed historical `mini328` reference and independent test fixtures remain
separate regression oracles.

Before compilation, both assembly builders compare the selected device include
and selector with the database-derived content. A stale or missing file stops
the build with a regeneration command. Parallel builds only read these files;
they do not race to regenerate them. The build-resume digest includes the
shared database module as well as JSON and assembly inputs.

## Maintain and verify

1. Review the exact device datasheet, signature, memory geometry, Boot sizes,
   clock/voltage constraints and architecture before changing a record.
2. Update `devices.json` for per-MCU properties. Change an architecture template
   only if needed; keep register constants outside JSON.
3. Run `python3 gen_devices.py` from `optiboot/bootloaders/optiboot/`. Review the
   generated include diff and [device reference](DEVICES.md).
4. Run `python3 gen_devices.py --check` or `make mini_devices_check`. This is a
   read-only check of all generated includes, the selector and device reference.
   Unexpected include files are reported for manual review, never deleted.
5. Run `make mini_test` and the applicable build matrix. Compare image hashes,
   addresses and sizes with the previous revision; do not refresh fixtures to
   conceal a change.

`make mini_devices` regenerates the outputs. `mini_test` starts with the
read-only consistency check. The original Optiboot C sources, board targets
and repository layout remain available.

## Extraction validation, 2026-11-02

The extraction started from `d1321d8daeecd2062818fe9060017537ca6fea9c`.
All 39 JSON records and 40 device includes retain their original content;
register constants were not moved into JSON. Validation was software-only.

* All 126 instruction-model tests and 27 generator/database tests passed.
* All 441 supported clock/device/edition images built and passed executed smoke
  checks. Their SHA-256, Boot addresses, sizes, padding and baud settings match
  the [423-image reference](UART_MATRIX_2026-11-01.csv) plus the
  [18 ATmega168PB images](ATMEGA168PB_MATRIX_2026-11-01.csv), with only the
  historical edition names mapped to Mini/Middle.
* All 79 Clang/AVR-GCC pairs produced identical binaries; all 57 application
  SPM header probes compiled.
* The stock C `atmega328` target still produces HEX SHA-256
  `73b0833cbac1550825c8cd67fcc24363cd0d2bdd38f6963f42feb29ee7b2ec96`,
  matching the earlier comparison with the unmodified upstream C target.

Reproduce the software checks from the bootloader directory:

```sh
python3 gen_devices.py --check
make mini_test
python3 verify_editions.py --all-clocks --smoke --output output/database-validation
python3 verify_toolchains.py --output output/database-toolchains
```

Compare `output/database-validation/matrix.csv` with the two reference matrices
using MCU, edition, frequency and clock source as the key. Map `flashread256`
to `mini` and `compact` to `middle`; every other column must match unchanged.
