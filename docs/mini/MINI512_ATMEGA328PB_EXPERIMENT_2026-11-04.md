# Experimental Mini on an ATmega328PB Nano

Date: 2026-11-04. The opt-in Mini port passed 55 physical USB checks on the same
ATmega328PB Nano previously used for the Full qualification. Final independent
ISP verification passed; original application and EEPROM are restored, Mini
remains installed, and Boot protection is retained. The
[sanitized results](MINI512_ATMEGA328PB_RESULTS_2026-11-04.json) record both phases.

This experiment retains the Flash read/write Mini protocol and a useful-size
budget of at most 256 bytes. The ATmega328PB physically reserves at least
512 Boot bytes (256 words), so the experiment uses that reservation. It does not
qualify a real 256-byte Boot section or add the chip to the 14 canonical Mini256
targets. The common device database and normal generator edition list are unchanged.

## Image and physical layout

| Item | Value |
|---|---|
| MCU / physical signature | ATmega328PB / `1E 95 16` |
| Edition label | `mini-experimental-512` |
| Tested clock / UART | External 16 MHz / USART0, 115200, 8N1 |
| Physical Boot / byte start | 512 bytes / `0x7E00` |
| Code / signature footer / padding | 252 / 3 / 257 bytes |
| Total useful bytes | 255; signature footer is at the end of the reservation |
| Application capacity / Flash page | 32256 / 128 bytes |
| LFUSE / HFUSE / EFUSE / lock | `FF / DE / FD / CF` |
| Installation fuse change | HFUSE `DC` to `DE`, only BOOTSZ0 |
| Binary SHA-256 | `ff0b46f3276f4a8c75a0b765d263eac5ae93f5fe6bd1dddafa572ca49aff959d` |

The 8 MHz / 38400 build has 248 code bytes plus three signature bytes (251 useful),
with SHA-256 `fe3fcc2d44adb6f4ba52e291ded195f343297e1a43859a153fef357cc30748a7`.
That clock was instruction-tested, not physically qualified in this run.

The [datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/40001906C.pdf#page=380)
defines Boot sizes in words. The 512-byte reservation is the same as Middle on
this chip, so both provide 32256 application bytes. Mini has fewer features.

## Protocol contract

- Flash writes require aligned, complete 128-byte pages. Reads require an aligned
  page start and a length of 1..128 bytes. All four physical Boot pages reject
  both user reads and writes.
- `READ_SIGN` returns the configured `1E9516` signature. `GET_PARAMETER` returns
  the fixed value `03` for every selector; AVRDUDE therefore displays FW `3.3`.
  This is a compatibility placeholder, not an Optiboot release number.
- EEPROM protocol, UNIVERSAL signature/fuse queries and the application SPM ABI
  are absent. Unsupported payloads recover through the watchdog.
- Mini clears MCUSR. Watchdog reset routes directly to the application with
  r1 zero and WDT disabled; other reset causes enter the UART wait. There is no
  r2 reset-cause ABI. Power-on application entry normally follows the idle timeout.

## Software evidence

Six builder/CLI/assembler-guard tests and 15 new instruction tests passed. The
instruction tests exercise every application page, upper-half addressing,
all Boot pages before any SPM, parameter selectors after signature access,
malformed packets, EEPROM-busy interlock, randomized reset registers and
Flash-end wrap back to the application reset vector.

All eight existing canonical Mini instruction tests also passed. All 28 canonical
BINs (14 chips at the two reference clock/baud pairs) were compared with pre-edit
baselines and remained byte-identical. Four canonical ATmega168PB host cases
also passed with the normal CLI.

Real AVRDUDE 8.0-arduino.1 passed six localhost instruction-model cases: short
even/odd uploads, explicit padding, protected Boot upload rejection, all 32256
application bytes, and raw application-prefix verification. The exact combined
application-prefix `flash:v` plus `signature:v` session also passed without
UNIVERSAL, programming, EEPROM or Boot reads. The negative model Boot upload
intentionally reaches the firmware guard and a bounded host timeout; this is
not a physical watchdog timing measurement.

The tests caught a newly activated LLVM high-byte relocation error in
`GET_PARAMETER` after `READ_SIGN`. It was fixed before hardware programming.
The USB runner passed 34 hardware-free checks; the final ISP tool passed 119
synthetic state/identity/restoration checks.

## Physical USB checks

Fresh complete Flash and EEPROM backups were independently read twice through
ISP. The current Full image and `FF/DC/FD/CF` configuration were verified before
installation. The plan preserved all 31744 original application bytes, erased
the released `0x7C00..0x7DFF` half of the old Full reservation and installed Mini
at `0x7E00`. Original EEPROM was restored after Chip Erase, then HFUSE and final
Boot protection were set. A separate complete ISP readback matched the plan.

USB checks covered verified full-application upload, all 256 parameter selectors,
parameter relocation after signature access, every read length on pages `0000`,
`4000`, `7D80`, full-page writes, all Boot pages, out-of-Flash/overflow/alignment
guards, unsupported memories, invalid lengths/EOP, truncation, no-op Chip Erase,
direct fuse/lock diagnostics, 50 watchdog resets, 20 DTR cycles, UART echo,
BREAK, three AVRDUDE reconnects and a physical power cycle. The observed maximum
watchdog restart interval was 133 ms including host/USB delays.

The armed cold probe recorded nine nominal 500 ms first-invocation ticks, with
initial r1 `00`, MCUSR `00` and WDT `00`; the host waited six seconds after USB
returned. This establishes first-invocation execution for those saved ticks.
It does not establish the original hardware reset flags or uninterrupted
execution throughout the whole host wait. r2 was not interpreted or exported.

The initial read-only USB preflight stalled and was stopped before test writes.
A direct signature query, direct full application-prefix verification and the
complete USB bench then passed. Its exact initial cause was not established.
One initial watchdog-probe upload sync returned `42`; normal AVRDUDE
retry completed and verified that upload.

Final ISP readback matched the complete post-installation Flash snapshot,
including the unchanged Mini Boot. Only nine EEPROM bytes differed after the
application probe; all were within 1014..1023. The finisher restored the original
1024 EEPROM bytes, then independently reread all Flash, EEPROM, signature,
fuses and locks. Every comparison passed and no qualification failure remains.
Raw memories and captures stay private.

## Reproduce

Build from `optiboot/bootloaders/optiboot/`:

```sh
python3 build_flashread.py --mcu atmega328pb --experimental-328pb-512 --f-cpu 16000000 --baud 115200
python3 -m unittest generator_tests.test_mini512_builder mini_tests.test_mini512_experiment -v
python3 verify_arduino.py --avrdude /path/to/avrdude --config /path/to/avrdude.conf --mcu atmega328pb --experimental-328pb-512
```

The regular `generate_firmware.py atmega328pb mini ...` path remains unavailable.
Use the explicit experimental builder. Match the physical Boot reservation,
clock and baud when installing through ISP; never select a 256-byte Boot size.

The separate [USB runner](../../scripts/hardware/nano_usb/test_nano_mini512.ps1)
requires verified current-board ISP snapshots and the pinned image. Its default
mode builds probes and verifies application Flash without test writes. Use
`-Run -ColdStart` for the bench, following its power-cycle signal. Raw board
backups, captures and generated files belong in ignored private directories.

Mini cannot read Boot or EEPROM over UART. The USB runner restores and verifies
only application Flash and explicitly leaves full restoration pending. Disconnect
Nano USB, reconnect ISP, then use the
[final ISP tool](../../scripts/hardware/nano_usb/finish_nano_mini512_isp.ps1)
with the same `-IspBackupDirectory`, the `-UsbResultDirectory`, a new private
`-OutputDirectory`, the installed `-AvrdudePath`, and `-Run`. It requires exact
current full-Flash/Boot/configuration agreement before restoring EEPROM, then
independently reads all memory and configuration. Default mode only reads/plans.
It performs no Flash, fuse, lock or Chip Erase writes.

The application watchdog/cold probe changes only EEPROM addresses 1014..1023.
The final tool restores all original EEPROM and retains unexpected changes or
USB failures as qualification failures even after successful data restoration.

Offline helpers are
[USB guards](../../scripts/hardware/nano_usb/test_nano_mini512_helpers.ps1) and
[final ISP guards](../../scripts/hardware/nano_usb/test_nano_mini512_isp_helpers.ps1).
One board/clock/image is under test; other chips, a genuine 256-byte Boot area,
voltage/temperature margins, endurance and power loss during erase/write are
outside this physical qualification.
