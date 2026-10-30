# ATmega328P/328PB boot-access diagnostics

This example reads actual fuses, lock bits and the device signature directly
with the avr-libc `LPM` helpers. It does not depend on the installed bootloader's
`UNIVERSAL` command: old Nano/Optiboot bootloaders can return dummy zeros for
fuses and lock bits. Eight repeated reads check consistency.

Target: a classic Nano/Uno with ATmega328P or ATmega328PB and an actual 16 MHz clock. Open the
sketch in Arduino IDE, upload it as an application using the currently installed
bootloader's upload settings, then read the serial report at 115200 baud, 8N1.
The report repeats every two seconds. Uploading temporarily replaces the
existing application, so save and verify a complete Flash backup first.

The diagnostic recognizes physical signatures `1E 95 0F` (328P) and `1E 95 16`
(328PB). Some Nano-compatible boards use a 328PB with an old bootloader that
reports the 328P signature over STK500v1. Use the physical signature for future
ISP programming. This example uses only registers shared by both models; a
328P build can diagnose this compatibility case without suppressing AVRDUDE's
signature checks. Other signatures are reported but not interpreted.

For a standalone build without the Arduino core:

```sh
avr-gcc -x c++ -mmcu=atmega328p -DF_CPU=16000000UL -DDIAGNOSTICS_STANDALONE -Os -ffunction-sections -fdata-sections -Wl,--gc-sections boot_access_diagnostics.ino -o diagnostics.elf
avr-objcopy -O ihex -R .eeprom diagnostics.elf diagnostics.hex
```

Keep build outputs and any board backups outside the tracked source tree.
The example contains no `SPM` instruction and never programs Flash, EEPROM,
fuses or lock bits. It temporarily configures UART0 for report output.

## Interpreting the result

Zero means a fuse or lock bit is programmed. The report masks unimplemented
lock bits with `0x3F` and decodes these hardware restrictions:

| Bit | When zero |
|---|---|
| BLB12 | Application `LPM` cannot read the boot section. |
| BLB11 | `SPM` cannot write the boot section. |
| BLB02 | Boot-section `LPM` cannot read the application. |
| BLB01 | `SPM` cannot write the application. |

Even if the lock bits permit writing, an `SPM` instruction executing in the
ATmega328P/328PB application section cannot program Flash. Application-driven updates
need suitable code already executing in the boot section. Lock bits can be
tightened in software through boot code, but cannot be cleared in software;
releasing protection requires an external Chip Erase.

`app_read_boot_crc16` is CRC-16/CCITT-FALSE over the boot section as visible to
the application. Compare it with the same calculation on a trusted bootloader
backup to distinguish real readable bytes from blocked reads. It is not a
Flash dump and does not demonstrate write access.

Write permissions are decoded from actual lock bits and CPU rules; the sketch
does not attempt destructive writes. Preserve the existing bootloader and
restore the saved application's overwritten pages after collecting results.

References: [ATmega328P datasheet, section 26](https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7810-Automotive-Microcontrollers-ATmega328P_Datasheet.pdf)
and [ATmega328PB datasheet, section 31](https://ww1.microchip.com/downloads/en/DeviceDoc/40001906C.pdf),
plus [avr-libc boot utilities](https://avrdudes.github.io/avr-libc/avr-libc-user-manual/group__avr__boot.html).
