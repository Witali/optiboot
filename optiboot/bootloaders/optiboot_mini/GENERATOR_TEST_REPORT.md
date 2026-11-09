# Historical generator test report

Date: 2026-10-31, before page-aligned Virtual Boot sizing.

* generator_tests: 11/11 passed, covering 38 MCU profiles, selection policy,
  frequency parsing, invalid arguments, Intel HEX/BIN verification, actual builds
  of all four editions, software-UART ATtiny85, and banked ATmega2560.
* Existing dual/Flash256/AVRDUDE/readback suites: 26/26 passed.
* Manual payload/reservation checks: ATmega328P Compact 510/512 and Full
  635/1024 at 16 MHz; ATmega8 Flash256 254/256 at 8 MHz; ATmega16 FlashRead512
  284/512 at 16 MHz; ATtiny85 Compact 541/1024 at 8 MHz; ATmega2560 Full
  787/1024 at 16 MHz; ATmega328P Compact 503/512 at 12 MHz/57600 with constant
  signature; ATmega128A Full legacy EEPROM 744/1024; ATtiny1634 Full 578/1024
  at 12 MHz.
* Existing ATmega64A Full legacy-byte-address mode failed a BRNE branch-range
  check. The generator rejects this optional mode; standard Full remains supported.
* Generated HEX/BIN and checksums were validated; ATmega328P Compact/Full
  matched prior R11 reference images byte for byte.

Physical AVR, actual AVRDUDE, and Arduino IDE were not tested. Current ATtiny
Middle reservations supersede the historical 1024-byte values in this report.
