# Arduino IDE smoke test

Target: the tested Nano with **ATmega328PB, external 16 MHz, UART0 at 115200**
and the installed **512-byte Optiboot Middle**. Application limit: **32256 bytes**.
The sketch blinks `LED_BUILTIN`, prints a counter each second and echoes received
serial bytes. It makes no EEPROM, SPM or watchdog changes.

1. If needed, install **MiniCore 3.1.3** using its
   [official instructions](https://github.com/MCUdude/MiniCore/blob/v3.1.3/README.md#how-to-install).
2. For the exact tested upload path, merge the supplied
   [boards.local.txt](boards.local.txt) and [platform.local.txt](platform.local.txt)
   lines into files with those names beside MiniCore 3.1.3's `avr/boards.txt`
   and `avr/platform.txt`. Preserve any existing local customizations, then
   restart the IDE. These are package-local overrides for this Middle setup.
3. Select these options:

   | Arduino IDE setting | Value |
   |---|---|
   | Board | MiniCore > ATmega328 |
   | Variant | 328PB |
   | Clock | External 16 MHz |
   | Bootloader | Yes (UART0) |
   | Baud rate | 115200 |
   | Port | Nano's own USB serial port |

4. Open `arduino_smoke.ino` and use the ordinary **Upload** arrow. This uploads
   through the installed Middle bootloader. **Burn Bootloader** would replace
   it with MiniCore's bundled Urboot and program MiniCore's fuse settings.
5. Open Serial Monitor at **115200 baud**. Expect `SMOKE_READY`, increasing
   `counter=` lines and a blinking LED. Send `ping` with a newline; it is echoed.

The verbose upload command should use `-patmega328pb`, `-carduino`,
`-b115200`, `-D` and a Flash-only HEX write. The supplied recipe retains normal
AVRDUDE verification. The IDE should report a maximum of 32256 application bytes.

The overrides matter because the stock MiniCore 3.1.3 UART0 profile reserves
384 bytes for Urboot, advertises 32384 bytes and selects `urclock`. Its standard
upload recipe includes `-xnometadata` and an EEPROM upload. The supplied files
select the tested Arduino protocol and this loader's application limit. The
recipe override affects uploads for that MiniCore package; remove these local
overrides when returning to the stock package configuration.

Primary references: MiniCore 3.1.3
[board definitions](https://github.com/MCUdude/MiniCore/blob/v3.1.3/avr/boards.txt)
and [upload recipe](https://github.com/MCUdude/MiniCore/blob/v3.1.3/avr/platform.txt).
