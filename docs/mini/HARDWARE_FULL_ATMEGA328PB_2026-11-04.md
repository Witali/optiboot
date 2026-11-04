# Full 1024-byte ATmega328PB Nano hardware validation

Date: 2026-11-04. ISP installation and independent readback passed. USB protocol,
memory, reset and physical cold-start qualification are pending.

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

## Software preparation

All eight existing application-SPM instruction-model tests passed before the
physical SPM phase. Their coverage includes ABI entry, application page operations,
Boot-address and unsupported-command rejection, SREG preservation and protocol
regressions. These model results do not establish physical peripheral timing
or simulate asynchronous interrupts. The PowerShell runner also passed all 61
hardware-free edition-configuration and cold-start evidence checks. Both SPM
probes compiled to 892 bytes, with their seven call sites targeting the selected
ABI entry exclusively (`0x7E02` for Middle, `0x7C02` for Full).

## Reproduce

The [USB runner guide](../../scripts/hardware/nano_usb/README.md) describes
`-Edition full`, fresh verified ISP evidence, interruption recovery and private
backup handling. Full uses the scratch page at `0x7B80` and the application SPM
entry at `0x7C02`. Probes never invoke lock-bit programming opcode `09`.

The [Arduino smoke guide](../../scripts/hardware/nano_usb/arduino_smoke/README.md)
includes a separate Full board override for the 31744-byte application limit.
That IDE workflow has not been compiled or uploaded in this bench run.
