# History of user requests and research decisions

This is an English translation of the request chronology reconstructed from the
available conversation, not a complete transcript. The main technical history
is `02_CHANGELOG_HISTORY.md`.

1. **Find and minimize:** "Find the Arduino Optiboot bootloader, download its
   sources, and try to optimize it to reduce its size further." This led to
   upstream research and the initial 410/402-byte images.
2. **Compare behavior and protocol:** "Compare our assembly with original
   Optiboot. Think about simplifying it further for minimum size, and check
   that the protocol matches the original exactly." Differential tests fixed
   WDT/FE0 and produced 368/366-byte variants.
3. **SRAM:** "Have you already removed the RAM buffer?" The research confirmed
   hardware SPM buffering instead of a Flash SRAM array from the 368-byte stage.
4. **Further reduction:** "What else can be optimized in this firmware?" This
   produced 358/356/350-byte versions and evaluated the reset-only tradeoff.
5. **Additional functions:** "What functions could be added, perhaps programming
   protocol functions that are not implemented?" STK500v1 review produced the
   480/511-byte diagnostic variants.
6. **Useful avrdude commands:** "Choose the most promising commands needed by
   this programmer." EEPROM PROG_PAGE/READ_PAGE and limited UNIVERSAL were
   prioritized.
7. **EEPROM first:** "Let's start with the commands for EEPROM." The result was
   498 bytes, a 16-byte SRAM receive buffer and EOP validation before writes.
8. **Fit UNIVERSAL:** "Can this be optimized further to fit additional functions,
   perhaps 0x56 UNIVERSAL?" EEPROM staging moved to the stack; the 508-byte image
   added four read-only fuse/lock operations.
9. **Chip/protocol audit:** "Check that all protocols are followed correctly and
   match the chip datasheet." This identified the SPM Page Write PCWORD=0 issue,
   produced the 512-byte image, and confirmed only limited protocol compliance.
10. **Project handoff:** "Collect all our research and firmware change history
    into a separate archive for another agent." This produced the supplied handoff.

Optiboot is the ATmega328P UART/STK500v1 bootloader. The user's separate
Micronucleus Block64 project targets ATtiny88 with V-USB and a different protocol;
it is not a continuation of this code. These historical requests are records,
not new instructions for the current session.
