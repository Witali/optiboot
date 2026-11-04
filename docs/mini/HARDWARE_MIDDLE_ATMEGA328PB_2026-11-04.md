# Middle 512-byte ATmega328PB Nano hardware validation

Date: 2026-11-04. One physical Nano with ATmega328PB passed 45 distinct checks
across a full USB run and a focused cold-start retry. Middle remains installed;
the original application and all EEPROM bytes were restored and verified.
The [sanitized results](HARDWARE_MIDDLE_ATMEGA328PB_RESULTS_2026-11-04.json)
record both runs, including the initial cold-start criterion failure.

## Exact configuration

| Item | Value |
|---|---|
| Firmware source revision | `30651a823368ee0d4e692d6450530bbd8c70c39c` |
| MCU / signature | ATmega328PB / `1E 95 16` |
| Edition | Middle, 512-byte hardware Boot reservation |
| Code and footer / padding | 510 / 2 bytes |
| Boot byte address | `0x7E00` |
| Application / EEPROM | 32256 / 1024 bytes |
| Configured clock / UART | External 16 MHz / USART0, 115200 baud, 8N1 |
| LFUSE / HFUSE / EFUSE | `FF / DE / FD`, unchanged |
| Lock byte | `CF`, Boot protection retained |
| ISP / USB tools | USBasp; AVRDUDE 8.0-arduino.1; PowerShell 7.6.5 |
| Probe compiler | AVR-GCC 7.3.0 in WSL; shared 328P register definitions |

Boot BIN SHA-256:

```text
156d3701c01e5a9f5008b371c08e4753b7d7200e1535b1c776755040723a99c1
```

## Installation and preservation

The physical signature was read through USBasp. Two independent complete Flash
and EEPROM reads matched before any write. The planned image preserved all
32256 application bytes and replaced only the last 512 bytes. Existing fuses
already selected this Boot area, so no fuse was changed. After ISP Chip Erase,
the complete planned Flash and original EEPROM were written and automatically
verified; lock protection was restored last.

AVRDUDE logged a transient USBasp paged-read transport error during automatic
Flash verification. Verification subsequently completed for all 32768 bytes.
An additional complete ISP readback independently matched the planned Flash,
original EEPROM, signature, fuses and lock byte. USB tests began only after that
verification. Raw device backups and logs remain private.

## Physical coverage

| Area | Result |
|---|---|
| Real serial upload and normal verification | All 32256 application Flash bytes and all 1024 EEPROM bytes |
| Protocol | Sync, ACK-only sign-on, version 8.3, READ_SIGN and three UNIVERSAL signature bytes |
| Memory transfers | 256-byte and legacy zero-length reads; application/Boot crossing; EEPROM blocks 1..16; short Flash page behavior |
| Negative cases | Invalid memory types, lengths, alignment, overflow, boundaries, EOP and incomplete packets |
| Boot protection | Serial Boot programming rejected; complete Boot unchanged; application LPM Boot reads blocked |
| Application SPM ABI | Scratch page `0x7D80` erased, filled, written, read and restored; r1 zero; protected Boot-address calls returned |
| Direct configuration | Repeated application reads of actual signature, fuses and locks match ISP values |
| Handoff | Observed r2 `0A`, r1 `00`, MCUSR `02`, WDTCSR `00` |
| Reset stress | 50 application-triggered watchdog resets; 20 DTR reset/sync/leave cycles |
| Recovery | UART echo, BREAK recovery and three successive AVRDUDE sessions |
| Physical power cycle | Recorded power-reset application entry and two 500 ms first-invocation ticks |
| Final state | Complete 32768-byte Flash and 1024-byte EEPROM match the pre-test snapshots; Middle and Boot protection retained |

The maximum host-observed watchdog restart interval was 135 ms. This includes
USB and host scheduling delays; it is not a watchdog oscillator measurement.
With lock byte CF enabled, unchanged Boot after appSPM attempts establishes the
combined protection. It does not isolate the software guard from hardware locks.
Only reviewed SPM erase/fill/write opcodes were used; no lock-programming opcode
was tested.

## Cold-start observation and retry

The first full run passed 43 checks but failed the older requirement for three
saved uptime ticks. Its first-entry record was `STAR`, cause `05`, r1 `00`,
MCUSR `05`, WDTCSR `00`, with one tick. The final query reported cause `0F`.
Automatic restoration of the original application and EEPROM succeeded.

Middle preserves reset flags. For its focused retry, the original three-tick
acceptance path was retained and an additional evidence path was added: PORF
must be set, EXTRF/WDRF absent from the first record, at least one tick saved,
r1 zero, MCUSR consistent with the reset cause, and watchdog disabled.
Eighteen hardware-free checks cover accepted and rejected evidence records.
The older Basic edition retains its original criterion.

The user disconnected every power source, waited about five seconds and
reconnected only Nano USB. The retry recorded first cause `05`, r1 `00`,
MCUSR `05`, WDTCSR `00` and two ticks; the query cause was again `0F`.
This proves application entry from the power-reset path and at least 1000 ms
of execution in that first invocation. It does not establish uninterrupted
execution throughout the host's four-second wait. A later external reset is
consistent with the query flags; its timing and cause were not measured.
USB enumeration or stale-handle closure is a possible explanation, not a result.

Pure watchdog-only cause `08` without EXTRF was not physically qualified.
Middle follows the existing Optiboot reset-flag policy; Microchip documents
that WDRF affects whether WDE can clear. See the
[ATmega328PB datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/40001906C.pdf).

## Reproduce and Arduino IDE follow-up

The [USB runner guide](../../scripts/hardware/nano_usb/README.md) gives the
verified ISP evidence contract, complete `-Edition middle` test command,
`-ColdStartOnly` retry and interruption recovery. Keep board snapshots private.

The [Arduino smoke sketch](../../scripts/hardware/nano_usb/arduino_smoke/README.md)
is prepared for a separate IDE upload. Its MiniCore 3.1.3 local overrides select
the tested Arduino protocol and 32256-byte limit. MiniCore is not installed on
this host; that sketch and the IDE workflow have not been compiled or uploaded
as part of this bench run.

This report qualifies one board with this exact image and configuration. Other
devices, editions, clocks, voltage/temperature margins and erase/write power-loss
behavior retain their separate validation requirements.
