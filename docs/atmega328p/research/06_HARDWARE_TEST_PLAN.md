# Initial physical ATmega328P test plan

No physical test of this firmware has been performed. This is a proposed plan,
not a report of completed work.

1. Use a spare Arduino Uno or ATmega328P with a 16 MHz clock and prepare a
   working ISP programmer for recovery.
2. Before changing anything, back up all accessible Flash, EEPROM, fuse and lock
   data through ISP. Check BOOTSZ/BOOTRST, clock and BOD settings, and preserve
   the working original Optiboot. Do not guess fuse settings.
3. Program the current HEX into the boot section; it already addresses `0x7E00`.
   Read it back through ISP and compare byte for byte. Do not write BIN at zero.
4. Check power-on and external reset. Confirm bootloader entry through
   DTR/RTS/RESET and application entry after the watchdog timeout.
5. Exercise normal `avrdude -c arduino -p m328p -b 115200 -P <port>` operations:
   GET_SYNC, GET_PARAMETER, READ_SIGN, READ_PAGE/PROG_PAGE and verify. On a
   disposable application, separately test dropped/corrupted UART frames and
   incorrect EOP.
6. Back up EEPROM, then test read-only access first. On the spare MCU, write a
   known pattern across 0..1023 in 16-byte packets and verify after reset. Check
   boundaries including `0x000`, `0x1FE`, `0x200` and `0x3F0`.
7. On the spare MCU, test ordinary Flash pages, short final-page payloads and
   the last application page before `0x7E00`. Check that boot memory is
   unchanged. Exercise bad EOP, truncated packets, address alignment and RWW
   re-enabling.
8. Compare all four read-only UNIVERSAL fuse/lock results with the ISP programmer.
   Do not attempt fuse/lock programming through the bootloader.
9. Brownout or power loss during Flash/EEPROM programming can damage data even
   with correct code. Test such cases only on a spare MCU with BOD and ISP recovery.
10. Record the UART log, avrdude/USB-UART/OS versions, exact fuses, clock source,
    source revision and HEX SHA256, then update the research documentation.

Do not use `avrdude -e` through this UART bootloader: CHIP_ERASE and its
UNIVERSAL equivalent do not physically erase despite possible ACK responses.
Fuse/lock writes require an appropriate ISP/HV programmer.
