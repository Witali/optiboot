# FlashRead512 research record, 2026-10-31

READ_PAGE did not fit in 256 bytes while retaining the minimal AVRDUDE command
set, READ_SIGN, watchdog, EOP-before-erase checks, and Boot guard. The prototype
uses 280 code bytes for legacy USART or 282 for modern USART, plus three
signature bytes and one padding byte: 284/286 total. Another 28/30 code bytes
would need removal for the 256-byte target. This update contains that earlier
FlashRead512 source, not the separate R13 research archive.

The prototype requires 512-byte BOOTSZ. It supports GET_SYNC (30), GET_PARAMETER
(41), SET_DEVICE (42), SET_DEVICE_EXT (45), ENTER_PROGMODE (50), LOAD_ADDRESS
(55), PROG_PAGE (64), READ_PAGE (74), READ_SIGN (75), and LEAVE_PROGMODE (51).
READ_PAGE accepts `F` and lengths 1..64/128 by MCU, returns exactly that many
bytes, requires page-aligned start, and refuses Boot reads. PROG_PAGE requires
a complete physical page; malformed EOP/parameters fail before erase. No
EEPROM, GET_SIGN_ON, fuse/lock, UNIVERSAL, or application-callable SPM is supplied.

Both page commands share parsing and type/address checks. Opcode bit 4 is
preserved in T via BST; READ_SIGN and READ_PAGE share the LPM loop; Flash page
filling shares execute_spm. All code lives in `flash256/flash256.inc`, selected
from the same `optiboot_mini.S`.

```sh
python3 build_flash256.py --all --f-cpu 16000000 --baud 115200
python3 build_flash256_readback.py --all --f-cpu 16000000 --baud 115200
python3 build_flash256_readback.py --all --f-cpu 8000000 --baud 38400 --output-dir output/readback512_8mhz
python3 flash256/prepare_avrdude_hex.py --mcu atmega8 --input firmware.hex --output firmware.padded.hex --boot-bytes 512
avrdude -c arduino -p m8 -P COM5 -b 115200 -D -U flash:w:firmware.padded.hex:i
```

Boot origins for 8/16 KiB Flash are `0x1E00`/`0x3E00`; the corresponding
Flash256 origins are `0x1F00`/`0x3F00`. Change BOOTSZ and install via ISP.
`-V` is unnecessary with READ_PAGE; `-D` remains necessary because UNIVERSAL
chip erase is unsupported. Ordinary AVRDUDE page operations must respect the
prototype's page-aligned, at-most-one-page read restriction.

The source report recorded 15/15 tests, 13/13 unchanged Flash256 BINs,
unchanged ATmega328P Compact/Full, and 13/13 readback builds at both clocks.
Run the three Flash256/readback suites to reproduce software checks. Physical
AVR, real AVRDUDE, power-loss behavior, and hardware SPM timing were not tested.
Compact provides EEPROM and an SPM ABI in a 512-byte hardware section where
supported; FlashRead512 remains a separate size-reduction experiment.
