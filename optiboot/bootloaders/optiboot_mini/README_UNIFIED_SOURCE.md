# Single assembly source for 38 AVR

Historical architecture record dated 2026-10-31. See README_DUAL_EDITIONS.md
and README_VIRTUAL_BOOT_SIZING.md for the current product matrix and reservations.

Every MCU is assembled from `optiboot_mini.S`. `-mmcu` selects exactly one
`devices/<mcu>.inc` via select.inc and includes only that target's three signature
bytes. There is no table of other MCU signatures in the image.

* MINI_SPM512_CAPABLE: 21 classic 8/16/32 KiB ATmega, with 64/128-byte pages.
  The early compact implementation used 506 code + 5 footer = 511 bytes;
  the EEPROM-first revision later recorded 504 + 5 = 509. Current automatic
  hardware-signature images can differ; use the build manifest.
* MINI_FLASH_BANKED/MINI_FLASH_256K select RAMPZ, ELPM, and extended addressing.
* MINI_FLASH_ERASE_GROUP_BYTES selects four-page erase on ATtiny841/1634,
  independently from UART style.
* MINI_WDT_CCP_STYLE selects protected watchdog writes on ATtiny841/1634.
* MINI_VIRTUAL_BOOT uses redirected reset/EEPROM-ready vectors with direct
  application SPM; no dummy application-callable Boot ABI.
* MINI_SOFT_UART/MINI_UART_STYLE choose software UART on ATtiny84/85 or the
  correct hardware USART map. Legacy ATmega use IN/OUT UART macros.

build_mini_compat.py always recompiles source. build_mini_clone511.py and
build_mini328.py are legacy names that also compile the same source, with no
binary-template patching. The former separate mini328 assembly is absent.

```sh
python3 build_mini_compat.py --all --jobs 6
python3 build_mini_compat.py --mcu atmega328p --f-cpu 8000000 --baud auto
python3 build_dual.py --all --jobs 6
```

The earlier 21-small-ATmega release reported 29/38 unchanged BINs; nine legacy
models (8/8A/8515/8535/88/88P/16/32A/162) changed from 1024- to 512-byte images.
Optional upstream LED, RS485, and configurable watchdog features were not added.

## R10 signature-row selection

`--signature-source constants|hardware|auto` controls READ_SIGN and UNIVERSAL
signature replies. Hardware mode writes SIGRD|SPMEN (`0x21`) immediately before
each LPM and reads Z=0,2,4. Ordinary banked Flash uses ELPM/RAMPZ; signature
reads use LPM regardless of bank. Hardware mode is allowed only where
devices.json marks sigrow_lpm_supported_by_datasheet, originally 24/38 targets.
The default low-level mode is constants; auto chooses audited hardware or
constants per device. Expand that set only after checking the exact MCU.

Historical payloads: ATmega328P 503 bytes with constants or 510 with hardware
signature, both in a 512-byte section; ATmega640/644 497/504 in a 1024-byte
hardware section. Banked 128/256 KiB hardware-signature mode adds 11 bytes.
No GET_SIGN_ON fits in the 512-byte hardware-signature build (two spare bytes).

R11 added paired editions from the same source: Compact retains Flash/EEPROM
and omits GET_SIGN_ON; Full adds GET_SIGN_ON, SET_PARAMETER, fuse/lock reads.
The initial report compared 38 Compact images with R10; later policy disables
13 of them. These are compiler/model observations, not hardware validation.
