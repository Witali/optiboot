# Update 2026-11-08: page-/erase-group-aligned ATtiny Compact Virtual Boot

Read `README_VIRTUAL_BOOT_SIZING.md` first. The 2026-10-31 reports and
archived 115-image CSV were produced before this update and are historical;
new compact ATtiny payloads may differ because the sub-256-byte boot-start
boundary requires an extra low-byte address guard.

Builder `build_mini.py --compact-tiny --boot-bytes auto` now selects the minimum
safe erase-group-aligned reserve. `build_dual.py` and `generate_firmware.py`
use this new policy. Tiny helper tools still default to the **legacy 1024 B**;
pass `--boot-bytes` explicitly when using the new Middle images. No silicon
validation is claimed. Hardware ATmega BOOTSZ policy is unchanged.
