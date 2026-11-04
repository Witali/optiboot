# Full 1024-byte ATmega328PB Nano hardware validation

Date: 2026-11-04. One physical ATmega328PB Nano completed 49 distinct hardware
checks across a complete USB bench and a focused final diagnostic retry. Full
remains installed; the original application and all EEPROM bytes were restored
and verified. The [sanitized results](HARDWARE_FULL_ATMEGA328PB_RESULTS_2026-11-04.json)
preserve both earlier diagnostic-capture failures and the final passing retry.

The user connected a different physical Nano from the board used for the
[Middle qualification](HARDWARE_MIDDLE_ATMEGA328PB_2026-11-04.md). This run uses
fresh backups of that second board. It is not a same-board performance comparison.

## Exact configuration

| Item | Value |
|---|---|
| Firmware source revision | `89628571b118638c653533469f54830aa8cf1d61` |
| MCU / signature | ATmega328PB / `1E 95 16` |
| Edition | Full, 1024-byte hardware Boot reservation |
| Code / footer / padding | 626 / 9 / 389 bytes |
| Boot byte address | `0x7C00` |
| Application / EEPROM | 31744 / 1024 bytes |
| Configured clock / UART | External 16 MHz / USART0, 115200 baud, 8N1 |
| LFUSE / HFUSE / EFUSE | `FF / DC / FD` |
| Fuse change | HFUSE `DE` to `DC`; only BOOTSZ0 changed |
| Lock byte | `CF`, Boot protection retained |
| ISP / USB tools | USBasp; AVRDUDE 8.0-arduino.1; PowerShell 7.6.5 |
| Probe compiler | AVR-GCC 7.3.0 in WSL; shared 328P register definitions |

Boot BIN SHA-256:

```text
6a16bbe0776d704e4c9ab7651961bd35b02efe68809a7492090232014d5d82ef
```

The image matches the previously recorded 16 MHz Full entry in the
[software clock matrix](UART_MATRIX_2026-11-01.csv). No bootloader instructions
were changed for this hardware run.

## Installation and preservation

The physical signature was read through USBasp without overriding signature
checks. Two independent complete Flash and EEPROM reads matched before writing.
The existing configuration was `FF / DE / FD`, lock `CF`. The additional Boot
reservation at `0x7C00..0x7DFF` contained only erased bytes, so the original
application fits below the new Boot boundary.

External ISP Chip Erase cleared protection for installation. The complete planned
Flash, including all 31744 original application bytes and the new Full image,
and the complete original EEPROM were written and automatically verified.
HFUSE was changed to `DC` for the 1024-byte Boot area, then lock `CF` was restored.
LFUSE and EFUSE were not written. A separate complete ISP readback matched the
planned Flash, original EEPROM, signature and intended configuration.

The [ATmega328PB datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/40001906C.pdf)
defines this Boot area as 512 words; its byte size is 1024. Raw board memories,
programming logs and restoration backups remain private.

## Physical coverage

| Area | Result |
|---|---|
| Serial upload and normal AVRDUDE verification | All 31744 application Flash bytes and all 1024 EEPROM bytes |
| Protocol | Sync, `AVR STK` sign-on, version 8.3, READ_SIGN and all three UNIVERSAL signature bytes |
| Full configuration commands | All four actual fuse/lock reads; SET_PARAMETER payload consumption and fixed-parameter behavior |
| Packet recovery | SET_PARAMETER invalid EOP and truncation; invalid memory types, lengths, alignment, boundaries, overflow and incomplete memory packets |
| Memory transfers | 256-byte and legacy zero-length reads, application/Boot crossing, EEPROM write blocks 1..16 and short Flash page behavior |
| Boot protection | Serial Boot writes rejected; complete Boot unchanged; application LPM Boot reads blocked |
| Application SPM | Scratch page `0x7B80` erased, filled, written, read and restored; r1 zero; protected Boot-address calls returned |
| Handoff and reset stress | r2 `0A`, r1 `00`, MCUSR `02`, WDTCSR `00`; 50 application watchdog resets and 20 DTR reset/sync/leave cycles |
| Reconnection | UART echo, BREAK recovery and three consecutive real AVRDUDE sessions |
| Physical power cycle | First-entry record `STAR`, cause `05`, r1 `00`, MCUSR `05`, WDTCSR `00`, one 500 ms tick |
| Final direct diagnostics | Three complete, stable signature/fuse/lock/Boot-access frames after the separately recorded startup drain |
| Final state | Complete 32768-byte Flash and 1024-byte EEPROM match the post-installation, pre-test snapshots |

The maximum host-observed watchdog restart interval in the repeated bench was
124 ms. It includes host and USB scheduling and is not an oscillator measurement.
With lock `CF`, unchanged Boot establishes the combined software/hardware
protection; it does not isolate the firmware guard. Physical SPM probes use only
reviewed page fill/erase/write opcodes `01/03/05`. They never invoke lock-bit
programming `09` or RWW-only `11`.

## Software preparation

All eight existing application-SPM instruction-model tests passed before the
physical SPM phase. Their coverage includes ABI entry, application page operations,
Boot-address and unsupported-command rejection, SREG preservation and protocol
regressions. These model results do not establish physical peripheral timing
or simulate asynchronous interrupts. The PowerShell runner also passed all 61
hardware-free edition-configuration and cold-start evidence checks. Both SPM
probes compiled to 892 bytes, with their seven call sites targeting the selected
ABI entry exclusively (`0x7E02` for Middle, `0x7C02` for Full).
The final capture/drain/framing helpers passed 38 hardware-free checks, and the
process-output helper passed three synthetic scenarios. No Arduino core or GUI
was required for these tests.

## Initial USB observations

The first read-only USB preflight timed out before any test writes. A direct
AVRDUDE signature check and a subsequent unredirected preflight passed, including
exact full-memory agreement with the fresh ISP snapshots. The cause of the
initial timeout was not established. Separately, the native-process helper was
changed to forward output from the calling thread; three hardware-free scenarios
cover stream capture, console-thread affinity, exit codes and transport cancellation.

The first complete bench run reached its physical cold-start check. The saved
record was `STAR`, cause `05`, r1 `00`, MCUSR `05`, WDTCSR `00`, with one 500 ms
tick. Its later query reported cause `0F`. Final direct diagnostics then failed
the strict three-frame validation: the text contained repeated fragments, nested
banners and NULs. Its 232159 characters included two valid frames at the end with
the expected signature, `FF/DC/FD/CF`, Boot `0400/7C00` and CRC `B76F`.

Automatic restoration and complete Flash/EEPROM comparison succeeded, as did
independent serial fuse/lock verification. The failed attempt remains a failed
attempt; the two valid frames do not satisfy the three-frame requirement.
The exact source of the capture corruption has not been established.

During both complete bench attempts, the first synchronization attempt for the
SPM probe upload returned `0x42`; normal AVRDUDE retry completed and verified
each upload.

## Capture retry and final verification

The second complete bench used bounded byte reads and again passed the memory,
protocol, SPM, reset and physical cold-start checks. Its initial measured
diagnostics contained exactly three clean frames: 2007 bytes over 7220.75 ms.
Its final capture contained a 4100-byte startup prefix, including 62 NULs, followed
by three clean frames. The strict whole-capture NUL check rejected it. Complete
application/EEPROM restoration and fuse/lock verification again succeeded.

The runner now explicitly drains startup input only for the named initial/final
diagnostic captures, before starting the measurement. This is a separate 250 ms
preparation window with its own byte/read/time evidence. Negative-packet recovery
and watchdog-probe timing are unchanged. Measured captures still reject NULs,
nested banners, duplicate fields, incorrect values and fewer than three reports.

The focused `-DiagnosticsOnly` retry retained fresh ISP/USB preflight and complete
restoration. Its startup drain discarded 4079 bytes over 270.15 ms. The subsequent
measurement recorded 2007 bytes over 7200.14 ms in nine reads: three complete
valid frames, no NULs, and the expected `FF/DC/FD/CF`, Boot `0400/7C00`, CRC `B76F`.
All three focused checks passed. Together with the second complete bench, they
cover 49 distinct passing checks; neither earlier failed attempt is relabeled
as an entirely passing run. The exact driver/runtime origin of the startup
bytes remains unproved.

The second bench used tools at `aa1b743`; the focused final retry used
`ba3b98a`. Exact source hashes and full revisions are recorded in the sanitized
JSON. The bootloader image was identical throughout.

## Cold-start scope and limits

Both physical power cycles recorded first cause `05`, r1 `00`, MCUSR `05`,
WDTCSR `00` and one saved 500 ms tick; the later query cause was `0F`. This proves
application entry from the power-reset path and at least 500 ms of execution in
that first invocation. It does not establish uninterrupted execution for the
host's whole four-second wait or directly timestamp entry relative to opening
the port. A later external reset is consistent with the flags; its timing and
source were not measured.

Pure watchdog-only cause `08` without EXTRF was not physically qualified.
This exact Full build explicitly selects the existing Optiboot MCUSR-parity
policy. Software SREG/interrupt-state and opcode tests do not simulate actual
asynchronous interrupts. Voltage/temperature margins, Flash endurance and power
loss during erase/write were not qualified. Other devices, clocks and images
retain their separate validation requirements.

## Reproduce

The [USB runner guide](../../scripts/hardware/nano_usb/README.md) describes
`-Edition full`, fresh verified ISP evidence, interruption recovery and private
backup handling. Full uses the scratch page at `0x7B80` and the application SPM
entry at `0x7C02`. Probes never invoke lock-bit programming opcode `09`.

The [Arduino smoke guide](../../scripts/hardware/nano_usb/arduino_smoke/README.md)
includes a separate Full board override for the 31744-byte application limit.
That IDE workflow has not been compiled or uploaded in this bench run.
