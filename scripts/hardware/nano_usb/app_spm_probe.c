/* GPL-2.0-or-later. Exercise the installed Middle512 application SPM ABI.
 * Only PGERS/SPMEN, page-buffer fill and PGWRT/SPMEN are used. No lock command.
 * The final application page is restored before reporting; the host independently
 * verifies the whole Flash, including Boot, and finally restores the user's app.
 */
#include <avr/eeprom.h>
#include <avr/interrupt.h>
#include <avr/io.h>
#include <avr/pgmspace.h>
#include <avr/wdt.h>
#include <stdint.h>

#define OPTIBOOT_MINI_BOOT_BYTES 512
#define OPTIBOOT_MINI_SPM512 1
#include "optiboot_mini_app_spm.h"

#if FLASHEND != 0x7FFF || SPM_PAGESIZE != 128 || F_CPU != 16000000UL
#error This physical probe is restricted to the 16 MHz ATmega328P/328PB layout.
#endif

#define SCRATCH_ADDRESS 0x7D80
#define BOOT_ADDRESS 0x7E00

static uint8_t original_page[128];
static uint8_t erased_ok, written_ok, restored_ok, observed_r1;

void disable_watchdog_early(void) __attribute__((naked, used, section(".init3")));
void disable_watchdog_early(void) {
    MCUSR = 0;
    wdt_disable();
}

static uint8_t pattern(uint8_t offset) {
    return (uint8_t)(offset * 37U + 0x43U);
}

static void write_page(uint8_t restore) {
    optiboot_mini_do_spm(SCRATCH_ADDRESS, 3, 0);
    for (uint8_t offset = 0; offset < 128; offset += 2) {
        uint8_t low = restore ? original_page[offset] : pattern(offset);
        uint8_t high = restore ? original_page[offset + 1] : pattern(offset + 1);
        uint16_t word = (uint16_t)low | ((uint16_t)high << 8);
        optiboot_mini_do_spm(SCRATCH_ADDRESS + offset, 1, word);
    }
    optiboot_mini_do_spm(SCRATCH_ADDRESS, 5, 0);
}

static void put_char(char value) {
    while (!(UCSR0A & _BV(UDRE0))) {}
    UDR0 = value;
}

static void put_text(const char *value) {
    while (*value) put_char(*value++);
}

static void report(void) {
    const char digits[] = "0123456789ABCDEF";
    put_text("APP_SPM_RESULT erase="); put_text(erased_ok ? "PASS" : "FAIL");
    put_text(" write="); put_text(written_ok ? "PASS" : "FAIL");
    put_text(" restore="); put_text(restored_ok ? "PASS" : "FAIL");
    put_text(" r1="); put_char(digits[observed_r1 >> 4]); put_char(digits[observed_r1 & 15]);
    put_text(" boot_calls=RETURNED\r\n");
}

int main(void) {
    uint8_t saved_sreg = SREG;
    cli();
    eeprom_busy_wait();
    for (uint8_t offset = 0; offset < 128; ++offset)
        original_page[offset] = pgm_read_byte((const void *)(uintptr_t)(SCRATCH_ADDRESS + offset));

    optiboot_mini_do_spm(SCRATCH_ADDRESS, 3, 0);
    erased_ok = 1;
    for (uint8_t offset = 0; offset < 128; ++offset)
        if (pgm_read_byte((const void *)(uintptr_t)(SCRATCH_ADDRESS + offset)) != 0xFF) erased_ok = 0;

    write_page(0);
    written_ok = 1;
    for (uint8_t offset = 0; offset < 128; ++offset)
        if (pgm_read_byte((const void *)(uintptr_t)(SCRATCH_ADDRESS + offset)) != pattern(offset)) written_ok = 0;

    write_page(1);
    restored_ok = 1;
    for (uint8_t offset = 0; offset < 128; ++offset)
        if (pgm_read_byte((const void *)(uintptr_t)(SCRATCH_ADDRESS + offset)) != original_page[offset]) restored_ok = 0;

    /* CF boot locks stay enabled. An unchanged Boot readback establishes the
     * combined protection; it does not isolate the software guard's effect. */
    optiboot_mini_do_spm(BOOT_ADDRESS, 3, 0);
    optiboot_mini_do_spm(BOOT_ADDRESS, 1, 0x5AA5);
    optiboot_mini_do_spm(BOOT_ADDRESS, 5, 0);
    __asm__ __volatile__("mov %0,r1" : "=r" (observed_r1));
    SREG = saved_sreg;

    UCSR0A = _BV(U2X0);
    UBRR0H = 0;
    UBRR0L = 16;
    UCSR0C = _BV(UCSZ01) | _BV(UCSZ00);
    UCSR0B = _BV(TXEN0) | _BV(RXEN0);
    report();
    for (;;) {
        if ((UCSR0A & _BV(RXC0)) && UDR0 == 'I') report();
    }
}
