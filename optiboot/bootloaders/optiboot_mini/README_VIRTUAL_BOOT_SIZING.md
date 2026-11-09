# Middle / Compact Virtual Boot sizing

Updated 2026-11-08. Firmware remains experimental; the archive reports software
validation, with no physical AVR, real serial AVRDUDE, or Arduino IDE testing.

## Reservation policy

For ATtiny without hardware Boot Sections, Middle (`compact`) selects the
smallest reservation of at least 512 bytes that contains code plus footer and
starts on both a Flash page boundary and a complete erase-group boundary.
The lower bound is `R = ceil(max(512, payload_bytes) / erase_group_bytes) * erase_group_bytes`.
Because instruction size can depend on `BOOT_START`, the builder compiles each
candidate in ascending order and accepts the first image that fits. It fails if
none fits within 1024 bytes; it does not remove functions. Full stays at 1024.

`BOOT_START = FLASH_SIZE - R`. Virtual Boot has no hardware BOOTSZ setting.
The payload length, reserved application address range, and hardware BOOTSZ on
ATmega are separate quantities.

| MCU | Flash | Page | Erase group | Payload | Reservation | Boot start | Spare |
|---|---:|---:|---:|---:|---:|---|---:|
| ATtiny84 | 8192 B | 64 B | 64 B | 549 B | 576 B | `0x1DC0` | 27 B |
| ATtiny85 | 8192 B | 64 B | 64 B | 549 B | 576 B | `0x1DC0` | 27 B |
| ATtiny841 | 8192 B | 16 B | 64 B (4 pages) | 505 B | 512 B | `0x1E00` | 7 B |
| ATtiny1634 | 16384 B | 32 B | 128 B (4 pages) | 501 B | 512 B | `0x3E00` | 11 B |

ATtiny84/85 reserve nine 64-byte pages and recover 448 application bytes relative
to the former 1024-byte reservation. ATtiny841/1634 recover 512 bytes. Their
uploader must write entire four-page erase groups (64/128 bytes), because a
single physical-page write could erase neighboring application data.

The 576-byte image adds a full 16-bit boot-address comparison. The old high-byte
comparison would reject the last three valid application pages at `0x1D00..0x1DBF`.

## Build and prepare images

Run from this module directory with Python and AVR tools on PATH:

```sh
python3 generate_firmware.py attiny85 middle 8MHz --out ./generated
python3 build_mini.py --mcu attiny85 --compact-tiny --mcusr-parity \
  --boot-bytes auto --f-cpu 8000000 --clock-source internal_rc \
  --output-dir ./output/attiny85
python3 tiny/make_seed.py --mcu attiny85 --boot-bytes 576 \
  ./output/attiny85/attiny85.bin ./output/attiny85_seed.hex
python3 tiny/patch_vectors.py --mcu attiny85 --boot-bytes 576 \
  application.hex application_patched.hex
```

The seed is for initial ISP installation only. After ISP installation and fuse
configuration, the experimental serial uploader can use the patched application:

```sh
python3 tiny/flash_tiny.py --mcu attiny85 --boot-bytes 576 \
  --port /dev/ttyUSB0 --ack-experimental application_patched.hex
```

Use the exact same `boot_bytes` from the build JSON in the compiled loader,
ISP seed, application-vector patch, and serial uploader. The tiny CLI tools keep
the legacy **1024-byte default**; explicitly pass 576 or 512 for new Middle
images. Changing the reservation requires ISP reinstallation, a regenerated
seed, and a newly patched application. Loader HEX is not a serial application.

## Behavior and limits

STK500v1 subset, Flash and EEPROM read/write, signatures, watchdog/MCUSR policy,
and software boot checks are retained. Applications can still execute SPM and
overwrite the loader or vectors: these ATtiny have no protected hardware boot
region. Reset and an unused EEPROM-ready interrupt vector are redirected. An
application that uses that ISR needs a separate integration decision; power
failure during vector programming can require ISP recovery.

`mini_tests.test_virtual_boot_page_sizes` covers automatic selection, alignment,
576/640-byte explicit reservations, the last application erase group, refusal
to erase/write Boot, ISP seed generation, and vector relocation. Physical
clock/fuse behavior, serial wiring, power failure, and Arduino IDE remain untested.
