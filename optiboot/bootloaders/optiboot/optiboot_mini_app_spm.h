/* Optiboot Mini application SPM interface, compatible with Optiboot 8.x.
 *
 * Only include this with the matching Full (--app-spm, 1024B) or Compact
 * (--app-spm-512, 512B on 22 supported ATmega, plus
 * -DOPTIBOOT_MINI_SPM512=1) image. Set OPTIBOOT_MINI_BOOT_BYTES to the actual
 * fuse-selected boot size. Not compatible with Virtual Boot ATtiny.
 * LLVM/clang AVR call encoding was tested; test with your avr-gcc version.
 *
 * The service is at BOOT_START + 2 BYTEs. Parts with CALL use an absolute
 * byte address (converted to words by the assembler), including 256KiB
 * chips. Small parts without CALL use ICALL with a word address in Z.
 * For 128/256KiB Flash, set RAMPZ to the desired 64KiB BYTE bank before
 * calling; the function does not alter RAMPZ.
 *
 * IMPORTANT: SPM directly modifies application Flash. The call provides no
 * high-level transaction support, no power-loss protection and no status
 * return; forbidden commands/boot-sector addresses are ignored.
 * Pass data=0 to erase/write so RWW is re-enabled before returning to an
 * application located in RWW. data!=0 is only appropriate when the caller
 * executes entirely from NRWW during multi-step operations.
 * Do not execute or interrupt into a page being erased. The compact 512B
 * entry does NOT mask interrupts and does NOT poll EEPE before SPM: the
 * application must disable unsafe interrupts, ensure EEPROM writes are
 * finished, and restore its own SREG after the complete page operation.
 * The service rejects addresses in the configured Boot section, including
 * RWW / lock commands; pass address 0 for address-independent commands.
 * For example, Compact ATmega328P rejects byte addresses >= 0x7E00.
 */
#ifndef OPTIBOOT_MINI_APP_SPM_H
#define OPTIBOOT_MINI_APP_SPM_H
#include <stdint.h>
#include <avr/io.h>
#ifndef OPTIBOOT_MINI_BOOT_BYTES
#error Define OPTIBOOT_MINI_BOOT_BYTES to match the actual image/fuse settings
#endif
#if OPTIBOOT_MINI_BOOT_BYTES < 1024 && !defined(OPTIBOOT_MINI_SPM512)
#error For a 512-byte boot section define OPTIBOOT_MINI_SPM512 and flash the matching --app-spm-512 image
#endif
#if defined(OPTIBOOT_MINI_SPM512) && OPTIBOOT_MINI_BOOT_BYTES != 512
#error OPTIBOOT_MINI_SPM512 requires 512 boot bytes
#endif
#ifndef FLASHEND
#error FLASHEND must be defined by the target AVR device header
#endif
#define OPTIBOOT_MINI_SPM_ENTRY_BYTE \
    ((uint32_t)(FLASHEND) + 1UL - (uint32_t)(OPTIBOOT_MINI_BOOT_BYTES) + 2UL)

static inline __attribute__((always_inline))
void optiboot_mini_do_spm(uint16_t byte_address, uint8_t spm_command,
                          uint16_t word_data)
{
    register uint16_t a __asm__("r24") = byte_address;
    register uint8_t c __asm__("r22") = spm_command;
    register uint16_t d __asm__("r20") = word_data;
    /* A direct absolute CALL permits >128KiB Flash and avoids EIND setup.
     * Outputs express the GCC caller-clobbered argument registers.
     * The service preserves every callee-saved register, and restores r1=0.
     */
#if defined(__AVR_HAVE_JMP_CALL__) || FLASHEND > 0x1FFF
    __asm__ volatile ("call %3" : "+r"(a), "+r"(c), "+r"(d)
        : "i"(OPTIBOOT_MINI_SPM_ENTRY_BYTE)
        : "r0", "r1", "r18", "r19", "r26", "r27", "r30", "r31", "memory", "cc");
#else
    /* Explicit loads avoid Clang treating a fixed r30 uint16_t operand as
     * eight bits and omitting the high-byte load for the Z pair. */
    __asm__ volatile ("ldi r30,lo8(%3)\n\tldi r31,hi8(%3)\n\ticall"
        : "+r"(a), "+r"(c), "+r"(d)
        : "i"(OPTIBOOT_MINI_SPM_ENTRY_BYTE / 2)
        : "r0", "r1", "r18", "r19", "r26", "r27", "r30", "r31", "memory", "cc");
#endif
}
#endif
