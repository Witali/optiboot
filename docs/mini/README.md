# Mini, Middle and Full firmware

The canonical builder supports 39 AVR and 79 device/edition combinations.
Start from the repository root with Python 3.10+ and the AVR toolchain on PATH:

```sh
python3 generate_firmware.py --list
python3 generate_firmware.py atmega8 mini 16MHz
python3 generate_firmware.py atmega328pb middle 16MHz
python3 generate_firmware.py atmega328pb full 16MHz
python3 generate_firmware.py attiny85 middle 8MHz
```

On Windows, run these commands from WSL with AVR-enabled Clang/LLVM or AVR-GCC,
binutils-avr, `readelf`, and `llvm-objdump` installed. The root launcher forwards
arguments to the existing implementation rather than maintaining another builder.
The generator creates BIN/HEX, a profile JSON and `build_info.json`; it does not
flash a board. `--out PATH` selects the output directory and `--dry-run` validates
selection without compiling.

| Edition | Reserved Flash | Functions |
|---|---|---|
| Mini | 256 B on 14 eligible ATmega | Flash write/readback, signature, minimal STK500v1 |
| Middle | 512 B on 22 ATmega; 512/576 B on four ATtiny | Flash/EEPROM, signatures, ATmega application SPM ABI |
| Full | 1024 B on all 39 AVR | Middle plus sign-on, SET_PARAMETER, read-only fuse/lock queries |

ATtiny Middle automatically selects complete erase groups: 576 bytes on 84/85
and 512 on 841/1634. Its ISP seed, application-vector patch and uploader must
all receive matching `--boot-bytes`; their legacy default remains 1024.

* [Build parameters and upload contract](../../optiboot/bootloaders/optiboot/README_MINI_MULTI.md)
* [Features and comparison](FEATURES.md)
* [Every supported MCU and edition](DEVICES.md)
* [ATtiny Virtual Boot installation and migration](VIRTUAL_BOOT.md)
* [Shared device database](DEVICE_DATABASE.md)
* [Full Nano hardware evidence](HARDWARE_FULL_ATMEGA328PB_2026-11-04.md)
* [Middle Nano hardware evidence](HARDWARE_MIDDLE_ATMEGA328PB_2026-11-04.md)
* [Middle application-upload verification](MIDDLE_NANO_APPLICATION_UPLOAD_2026-11-04.md)

The hardware reports qualify their exact ATmega328PB images/configurations.
ATtiny Virtual Boot remains software-validated only. Original C build targets
remain available; `optiboot/bootloaders/optiboot_mini/` preserves the older import
as a reference snapshot. See the November 10 integration record for current checks.
