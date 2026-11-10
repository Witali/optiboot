# Canonical firmware integration, 2026-11-10

The canonical 39-device, 79-profile builder now includes the November 8
page-aligned Virtual Boot policy. Run `python3 generate_firmware.py --list`
from the repository root. The [firmware index](README.md) links the current
builder, installation guide, device table and hardware evidence.

## Integrated changes

* Full hardware branch `46e024064fce926712616aafe008369ede5b7675` was merged
  as `b954e47`. It includes the earlier Middle qualification, Full Nano
  qualification, serial capture fixes and the process runner.
* Middle application-upload branch
  `ede5b9a36577e06ba849fe94503c253e6e4e0489` was merged as `fa3e250`.
* Canonical Virtual Boot integration is `23de934`. It shares Flash geometry
  with the device database and tiny helpers instead of introducing another
  device registry or replacing the current Mini implementation.

Middle tries increasing complete erase-group reservations from 512 through
1024 bytes and recompiles at each start address. ATtiny84/85 fit 549 payload
bytes in 576 reserved bytes at `0x1DC0`; ATtiny841 fits 505/512 at `0x1E00`;
ATtiny1634 fits 501/512 at `0x3E00`. Full remains 1024 bytes, hardware ATmega
Middle remains 512 bytes, and Mini remains 256 bytes.

Both address bytes are compared when a Virtual Boot boundary is not aligned
to 256 bytes. Tests execute the last writable application erase group and
reject writes at Boot start before any erase. The ISP seed, vector patcher
and uploader accept matching `--boot-bytes`; their API/CLI default stays 1024
for older installations. See [installation and migration](VIRTUAL_BOOT.md).

The imported `optiboot/bootloaders/optiboot_mini/` source and release images
remain a reference snapshot. Its four Middle image hashes are independent
regression fixtures for the canonical builder.

## Verification

Checks ran in WSL Ubuntu with Python 3.12.3, Clang/LLVM 18.1.3 and AVR-GCC 7.3.0.
From `optiboot/bootloaders/optiboot/`:

```sh
make mini_test
python3 verify_toolchains.py
python3 verify_editions.py --all-clocks --smoke --stress --jobs 4
```

* Generated device files match the shared database.
* All 132 firmware tests and 30 generator tests passed. These include four
  imported image hashes, vector relocation, ISP seeds, uploader agreement,
  invalid sizes, grouped erases, non-256-aligned boundaries and legacy defaults.
* GCC and LLVM emitted identical BIN files for all 79 device/edition profiles;
  the toolchain check also compiled the application SPM header examples.
* All 441 supported frequency/clock/device/edition builds passed their image
  checks and protocol smoke execution. Complete application Flash and EEPROM
  stress passed for all 79 profiles, preserving every Boot image.
* Against the pre-port baseline `fa3e250`, 75 images remained byte-identical:
  14 Mini, 22 ATmega Middle and 39 Full. Explicit 1024-byte ATtiny Middle builds
  also reproduced all four previous images exactly.
* After the final metadata/help adjustment, all six Virtual Boot boundary tests
  and three public-generator integration tests were rerun successfully.
* AVRDUDE 8.0-arduino.1 passed full application uploads, readback verification
  and EEPROM transfers against the instruction models for all 71 hardware-UART
  profiles. Sixty-five passed on the first run; six Windows/WSL localhost
  connections failed to open and passed when those cases alone were rerun.
  No firmware/protocol failure was observed. The eight ATtiny profiles use
  their dedicated tiny-host and GPIO/UART model checks instead.

To repeat the client interoperability check, supply an installed AVRDUDE and
its matching configuration:

```sh
python3 verify_avrdude.py --avrdude /path/to/avrdude --config /path/to/avrdude.conf
```

From the repository root:

```sh
python3 scripts/atmega328p/run_tests.py --build
pwsh -NoProfile -File scripts/hardware/nano_usb/test_cold_evidence.ps1
pwsh -NoProfile -File scripts/hardware/nano_usb/test_serial_capture.ps1
pwsh -NoProfile -File scripts/hardware/nano_usb/test_process_runner.ps1
```

The six original ATmega328P software-model suites passed. The offline hardware
runner checks passed 61 cold-evidence checks, 38 serial-capture checks and three
synthetic process cases covering output flooding, thread affinity and transport
errors. They did not open a serial port or ISP programmer.
All 76 local Markdown links in the 11 updated guides resolved successfully.

The current ATmega328PB images also match the recorded hardware evidence:

| Edition | BIN SHA-256 |
|---|---|
| Middle | `156d3701c01e5a9f5008b371c08e4753b7d7200e1535b1c776755040723a99c1` |
| Full | `6a16bbe0776d704e4c9ab7651961bd35b02efe68809a7492090232014d5d82ef` |

See [Middle qualification](HARDWARE_MIDDLE_ATMEGA328PB_2026-11-04.md),
[Full qualification](HARDWARE_FULL_ATMEGA328PB_2026-11-04.md), and the
[10,486-byte application upload](MIDDLE_NANO_APPLICATION_UPLOAD_2026-11-04.md).
The integration run did not repeat physical hardware testing. ATtiny Virtual
Boot remains software-validated only; its ISP, fuses and electrical UART timing
still need device-specific hardware validation.
