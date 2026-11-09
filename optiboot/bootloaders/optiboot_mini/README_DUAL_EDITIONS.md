# Supported Compact and Full editions

Policy dated 2026-10-31; Virtual Boot updated 2026-11-08.
The active matrix contains **25 Compact + 38 Full = 63 profiles**, compiled
from one `optiboot_mini.S`. Thirteen ATmega with a 1024-byte hardware minimum
have Full only. Low-level historical builders can reproduce former compact
experiments, but those are outside the active product matrix.

`devices.json` records `dual_compact_enabled` and `hardware_min_boot_bytes`.
`build_dual.py --list` reports current availability. Virtual ATtiny have a null
hardware minimum and retain both editions.

* Compact on 21 ATmega: 512-byte hardware Boot; Flash/EEPROM read/write,
  READ_SIGN, UNIVERSAL signature, audited SIGRD+LPM where supported,
  watchdog/MCUSR, boot checks, and application-callable SPM ABI.
* Compact/Middle on four ATtiny: Virtual Boot; 549/576 bytes payload/reservation
  on ATtiny84/85, 505/512 on ATtiny841, and 501/512 on ATtiny1634. Automatic
  sizing uses whole erase groups (64 bytes on 84/85/841; 128 on 1634).
* Full on 38 AVR: 1024 bytes, adding GET_SIGN_ON, SET_PARAMETER, and read-only
  fuse/lock queries. ATtiny applications execute SPM directly, with no callable
  boot-service ABI. No edition implements fuse/lock writes.
* Flash256: separate write-only profile on 13 ATmega with a 256-byte hardware
  minimum; full-page padded HEX and `-c arduino -D -V` are required.
* FlashRead512: separate 284–286-byte readback experiment on the same 13;
  needs a 512-byte Boot Section and full-page padded writes.

Default ATmega328P: 16 MHz external crystal, 115200 baud; Compact payload
510 bytes in 512, Full payload 635 in 1024. Match BOOTSZ/BOOTRST when changing
hardware boot size. Read [Virtual Boot sizing](README_VIRTUAL_BOOT_SIZING.md)
for ATtiny's different vector/ISP procedure.

```sh
python3 build_dual.py --list
python3 build_dual.py --all --jobs 6
python3 build_dual.py --edition both --mcu atmega644p
python3 build_dual.py --edition compact --mcu atmega328p
python3 build_flash256.py --all --f-cpu 16000000 --baud 115200
python3 build_flash256_readback.py --all --f-cpu 16000000 --baud 115200
python3 -m unittest mini_tests.test_dual_editions -v
```

Outputs: `output/dual/compact/<mcu>/`, `output/dual/full/<mcu>/`, and
`output/dual/matrix_dual.json`/CSV. The active matrix excludes obsolete
1024-byte hardware Compact configurations. Hardware, real AVRDUDE/Arduino IDE,
oscillator behavior, and fuse/lock protection remain unverified.
