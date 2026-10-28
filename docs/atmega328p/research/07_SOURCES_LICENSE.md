# Sources, provenance and license

## Original Optiboot

- Official repository: https://github.com/Optiboot/optiboot
- C source: https://github.com/Optiboot/optiboot/blob/master/optiboot/bootloaders/optiboot/optiboot.c
- Command definitions: https://github.com/Optiboot/optiboot/blob/master/optiboot/bootloaders/optiboot/stk500.h
- Observed `optiboot.c` GitHub blob SHA:
  `d7fba90a02616f095ec733ac4c434b4d42db58a6`. This identifies the blob read
  during research, not a pinned revision of the entire repository.
- The reference `optiboot_atmega328.hex`, reported version 8.3, is supplied in
  `OFFICIAL_REFERENCE/` and intermediate projects in the original layout.
  Its options and machine code may differ from current HEAD C source.
- The original handoff did not include the complete upstream source tree because
  it had not been saved locally during research. It could be obtained with
  `git clone https://github.com/Optiboot/optiboot.git` or the initial stage's
  `download_upstream.sh`. That historical limitation must not be presented as a
  complete source checkout inside the handoff. The current repository separately
  contains the upstream tree inherited by this fork.

## Protocol and MCU references

- AVR061 STK500v1: https://ww1.microchip.com/downloads/en/AppNotes/doc2525.pdf
- ATmega328P Atmel 7810D:
  https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7810-Automotive-Microcontrollers-ATmega328P_Datasheet.pdf
- ATmega328/P Atmel-42735B, including EEAR9:8 clarification:
  https://docs.arduino.cc/resources/datasheets/Atmel-42735-8-bit-AVR-Microcontroller-ATmega328-328P_Datasheet.pdf
- Microchip DS40002061B:
  https://www.microchip.com/content/dam/mchp/documents/MCU08/ProductDocuments/DataSheets/ATmega48A-PA-88A-PA-168A-PA-328-P-DS-DS40002061B.pdf
- avrdude `stk500.c`: https://github.com/avrdudes/avrdude/blob/main/src/stk500.c
- Optiboot EEPROM addressing in avrdude: https://github.com/Optiboot/optiboot/issues/235

## License

The derivative firmware declares GPL-2.0-or-later in its source and in the
COPYING files supplied by earlier stages. Preserve attribution and GPL terms,
and provide source when distributing derivative versions. Do not imply upstream
developer endorsement without evidence.

## Evidence limits

The references were examined during the original research. Sources, images and
software tests are included. No electrical measurements, oscilloscope traces or
real avrdude session recordings were produced.
