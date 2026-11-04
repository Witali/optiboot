# Middle Nano identification and application upload

Date: 2026-11-04. The USB-connected Nano reported ATmega328PB signature
`1E 95 16`. Its complete 512-byte Boot image matched the previously qualified
Middle image. The supplied `lpx-nano-dialogue-quality.hex` was uploaded through
the Arduino serial protocol at 115200 baud and verified successfully.
The [sanitized results](MIDDLE_NANO_APPLICATION_UPLOAD_RESULTS_2026-11-04.json)
record the measurements.

## Identification

The complete 32768-byte Flash and 1024-byte EEPROM were saved through USB before
upload. Boot bytes `0x7E00..0x7FFF` had SHA-256:

```text
156d3701c01e5a9f5008b371c08e4753b7d7200e1535b1c776755040723a99c1
```

This identifies the exact tested Middle image, rather than inferring the edition
from a version response. Its application capacity is 32256 bytes.

A preceding, separate read-only USBasp session identified the same MCU type and
Middle fingerprint, with LFUSE/HFUSE/EFUSE `FF / DE / FD` and lock byte `CF`.
No bootloader or fuse write was needed in that session. No unique board identity
was recorded, so the ISP and USB sessions do not establish physical board identity.
Configuration bytes were read through ISP, not through Middle's serial protocol.

## Application and results

| Check | Result |
|---|---|
| Intel HEX syntax, record lengths, checksums and EOF | Passed; no overlapping data |
| Application data | 10486 bytes, contiguous addresses `0x0000..0x28F5` |
| Fit within Middle application capacity | Passed; 10486 of 32256 bytes |
| AVRDUDE write and automatic verification | Passed; 10486 Flash bytes verified |
| Independent comparison against complete USB Flash readback | All 10486 supplied application bytes matched |
| Boot preservation | All 512 bytes unchanged; Middle fingerprint retained |
| EEPROM preservation | All 1024 bytes unchanged |

Supplied Intel HEX file SHA-256, including its original text formatting:

```text
444c05056d384394692269723415795a91385ceebbb942f01cb28aeb7aa2c2f6
```

AVRDUDE 8.0-arduino.1 was used with PowerShell 7.6.5. With local variables
`$avrdude`, `$config`, `$port` and `$hex` set to the executable, configuration,
target serial port and supplied file, the upload command is:

```powershell
& $avrdude -C $config -c arduino -p m328pb -P $port -b 115200 `
  -D -A -U "flash:w:${hex}:i"
```

The initial Flash and EEPROM backup used the same connection settings and
`-n -D -A`. The upload command also included `-U flash:r:after-flash.bin:r` and
`-U eeprom:r:after-eeprom.bin:r` after the write operation, capturing both memories
in that same AVRDUDE session. The before snapshots were retained separately in
the private capture directory. The user-supplied application remains installed;
the previous application was not restored.

This is an upload and memory-integrity check. Application behavior and the Arduino
IDE workflow were not exercised. This follow-up does not add another full protocol,
reset or cold-start qualification run to the
[earlier Middle hardware report](HARDWARE_MIDDLE_ATMEGA328PB_2026-11-04.md).
The application HEX, raw memory captures and device logs are not included.
