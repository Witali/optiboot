# Experimental ATtiny Virtual Boot and software UART

The four ATtiny profiles reserve 1024 bytes at the top of Flash. They require
an ISP seed, permission for self-programming, and application vector relocation;
they do not have the protected BOOTRST section used by ATmega. These ports have
only been compiled and exercised in software models. Hardware validation and an
ISP recovery path are required before relying on them.

## Profiles and transfer sizes

| MCU | Flash | EEPROM | Flash page | UART | Example clock / baud | Flash transfer |
|---|---:|---:|---:|---|---|---:|
| ATtiny841 | 8 KiB | 512 B | 16 B | Hardware USART | 16 MHz / 115200 | 64 B |
| ATtiny1634 | 16 KiB | 256 B | 32 B | Hardware USART | 12 MHz / 115200 | 128 B |
| ATtiny84 | 8 KiB | 512 B | 64 B | Software, TX PA1 / RX PA2 | 8 MHz internal RC / 19200 | 64 B |
| ATtiny85 | 8 KiB | 512 B | 64 B | Software, TX PB0 / RX PB1 | 8 MHz internal RC / 19200 | 64 B |

ATtiny841/1634 erase four physical pages together. Their uploader stages and
transfers a complete 64/128-byte group, then verifies it. Sending an isolated
16/32-byte page can destroy neighboring data. ATtiny84/85 use 64-byte pages
and leave 7168 bytes for the application. Both Middle and Full reserve
1024 bytes on all four Virtual Boot parts.

Run the following commands from `optiboot/bootloaders/optiboot/`:

```sh
python3 generate_firmware.py attiny841 middle 16MHz
python3 generate_firmware.py attiny1634 full 12MHz
python3 generate_firmware.py attiny84 middle 8MHz --output output/vboot
python3 generate_firmware.py attiny85 middle 8MHz --output output/vboot
```

The generated manifest records the actual clock, baud, image hash, reserved
region and Virtual Boot requirements. ATtiny84/85 default to 8 MHz / 19200
through both Make and the standalone builder. An explicit `F_CPU` must describe
the actual CPU clock, including dividers. The builder does not set clock fuses
or calibrate OSCCAL. ATtiny1634 is rated to 12 MHz in these profiles; supply
`F_CPU=12000000` explicitly.

## ISP seed and application upload

1. Arrange ISP recovery and record the target's existing memory and fuse/lock
   settings. Check the exact part's self-programming requirements, including
   SELFPRGEN. Keep RESET and ISP access usable; do not copy a complete fuse byte
   from another MCU.
2. Build the bootloader and create a sparse ISP seed with its RESET/EE_RDY
   trampolines. For example:

   ```sh
   python3 tiny/make_seed.py --mcu attiny85 BOOT_IMAGE.bin isp_seed.hex
   ```

   Replace `BOOT_IMAGE.bin` with the BIN path printed by the generator.
   Install this seed through an ISP programmer, with part-specific fuse settings.
   The bootloader-only HEX is not a complete reset-bootable image.
3. Prepare an application with a 16-bit RESET `RJMP` and an unused EEPROM-ready
   vector. Patch the application before uploading:

   ```sh
   python3 tiny/patch_vectors.py --mcu attiny85 app.hex app_vboot.hex
   ```

   The patcher redirects RESET to the bootloader and moves the application's
   original jump to EE_RDY: vector word 6 for ATtiny85, 14 for ATtiny84/841,
   and 26 for ATtiny1634. It validates Intel HEX checksums, address bounds and
   opcodes, and refuses an occupied EE_RDY vector unless explicitly overridden
   with `--overwrite-ee-vector`. An application using that interrupt must be
   adapted before it can share the vector with Virtual Boot.
4. Install `pyserial` on the host and use the dedicated uploader:

   ```sh
   python3 tiny/flash_tiny.py --mcu attiny85 --port /dev/ttyUSB0 --baud 19200 --reset-dtr --ack-experimental app_vboot.hex
   ```

   Change the MCU, port and baud to match the build. Hardware UART examples use
   115200; ATtiny84/85 use 19200 by default. The uploader checks the signature,
   reset/vector preconditions and reserved-region boundary before writing. It
   uses the required transfer groups and reads them back by default. Stock
   AVRDUDE compatibility with this Virtual Boot workflow has not been established.

Sparse uploads fill omitted bytes within each transferred group with `0xFF`.
Preserve a group's full contents in the application HEX if neighboring data
must survive. Interrupted rewriting of the first page can corrupt RESET and
prevent further UART recovery; restore the seed through ISP.

## ATtiny84/85 software UART

`uart/soft.inc` implements 8N1 with the least significant bit first, polling and
compile-time delays, without timers or interrupts. Both editions reserve a
1024-byte image. Register `r6` holds the shift byte,
`r18` the delay counter and `r16` the interface byte.

Use TTL/CMOS logic compatible with target VCC, a common ground, adapter TX to
target RX and adapter RX to target TX. These are not RS-232 voltage levels.
ATtiny85 UART pins overlap ISP functions; avoid conflicting external drivers
during ISP. An optional DTR reset circuit must match the board wiring.

The handoff's instruction-cycle model covers RX/TX start/data/stop bits,
STK500v1, Flash/EEPROM transactions and host baud offsets of ±1.5%. At the
8 MHz / 19200 reference it reports 414–420 cycles between `0x55` TX transitions.
Lower-level regression tests also cover 1 MHz / 9600 and 16 MHz / 38400.
The public generator accepts 8 MHz and above; its external-clock profiles
include 8 MHz / 57600 and 16 MHz / 115200. Nominal bit-level timing and
host baud offsets are tested separately from the accelerated full-memory
protocol model. The builder rejects unsupported timing combinations.

These software results do not establish real RC tolerance, jitter, temperature
or voltage behavior. ATtiny841/1634 also use a different CCP watchdog sequence
from ATtiny84/85; retain their separate implementation paths.

The current receiver executes `WDR` on entry to reception, rather than on
every start-bit polling iteration. An idle input therefore permits watchdog
timeout. Regression tests count the actual WDR instructions during an idle
wait and exercise application dispatch after power-on. This corrects the
older continuously-fed watchdog loop; real timeout and framing behavior still
require physical validation.

## Validation still required

Test actual reset and watchdog paths, SELFPRGEN, SPM/EEPROM latency, grouped
erase, UART waveforms, oscillator calibration, application dispatch and power
loss on physical devices. Keep ISP recovery available throughout. ATtiny44/45
are future work and are not included in the
39 supported build profiles.
