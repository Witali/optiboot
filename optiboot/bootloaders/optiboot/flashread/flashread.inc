/* Flash read/write STK500v1 subset. Reset entry only; no EEPROM protocol.
 * Full aligned physical-page writes, reads of 1..PAGE bytes, no Boot access.
 * GPL-2.0-or-later; see the repository LICENSE.
 */
#if !MINI_FLASH256_READBACK || BOOT_BYTES != 256
#error Only the 256-byte Flash read/write profile is supported; write-only was removed
#endif
#if MINI_VIRTUAL_BOOT || FLASH_SIZE > 16384 || (MINI_UART_STYLE != 0 && MINI_UART_STYLE != 1)
#error FlashRead256 requires an approved classic 8/16-KiB hardware-Boot ATmega
#endif
#if FLASH_PAGE_BYTES != 64 && FLASH_PAGE_BYTES != 128
#error FlashRead256 requires 64/128-byte Flash pages
#endif
.section .text
.global _start
_start:
#if MINI_LEGACY_STACK
    ldi r16,(SRAM_END & 0xff)
    out 0x3d,r16
    ldi r16,(SRAM_END >> 8)
    out 0x3e,r16
#endif
    clr r1
#if MINI_UART_STYLE == 0
    clr r29
#endif
    in r16,MCUSR_IO
    out MCUSR_IO,r1
    /* The reset-only prologue disables/reconfigures WDT immediately. */
    ldi r17,0
    sbrs r16,3
    ldi r17,0x0e
    rcall config_wdt
parameter_constant:
    sbrc r16,3  /* The low opcode byte is the protocol version constant 3. */
    rjmp boot256_end
    MINI_UART_INIT
cmd_loop:
    rcall packet
    ldi r16,0x10
    rcall tx_char
    rjmp cmd_loop
cmd_parameter:
    rcall rx_char
    ldi r25,0
    /* Keep a byte-address relocation: LLVM mis-encodes a folded section difference. */
    ldi r30,lo8(parameter_constant + BOOT_START)
#if BOOT_BYTES != 256
    ldi r31,hi8(BOOT_START + parameter_constant - _start)
    rjmp read_common
#else
    rjmp internal_read
#endif
cmd_signature:
    ldi r25,2
    ldi r30,lo8(BOOT_START + BOOT_BYTES - 3)
internal_read:
    ldi r31,hi8(BOOT_START + BOOT_BYTES - 3)
read_common:
    rcall verify_eop
read_loop:
    lpm r16,Z+
    rcall tx_char
    dec r25
    brpl read_loop
    ret
cmd_page:
    rcall rx_word
    mov r25,r16
    rcall rx_char
    subi r16,0x46
    or r16,r0
    brne bad_packet
    cpi r23,(BOOT_START >> 8)
    brsh bad_packet
    mov r16,r22
    andi r16,(FLASH_PAGE_BYTES-1)
    brne bad_packet
    movw r30,r22
    dec r25
#if FLASH_PAGE_BYTES == 128
    brmi bad_packet
#else
    cpi r25,FLASH_PAGE_BYTES
    brsh bad_packet
#endif
    brts read_common
    cpi r25,FLASH_PAGE_BYTES-1
    brne bad_packet
fill_loop:
    rcall rx_word
    ldi r18,1
    rcall execute_spm
    adiw r30,2
    subi r25,2
    brpl fill_loop
    rcall verify_eop
    movw r30,r22
    ldi r18,3
    rcall execute_spm
    ldi r18,5
    rcall execute_spm
    ldi r18,0x11
execute_spm:
    /* An EEPROM write started by the application may survive an external
     * reset. Wait before touching SPMCSR, including the first buffer fill. */
    sbic EEPROM_EECR_IO,1
    rjmp execute_spm
    out SPMCSR_IO,r18
    spm
wait_spm:
    in r18,SPMCSR_IO
    sbrc r18,0
    rjmp wait_spm
    ret
packet:
    rcall rx_char
    cpi r16,0x41
    breq cmd_parameter
    ldi r19,21
    cpi r16,0x42
    breq discard
    ldi r19,6
    cpi r16,0x45
    breq discard
    cpi r16,0x55
    breq cmd_address
    cpi r16,0x75
    breq cmd_signature
    bst r16,4
    andi r16,0xef
    cpi r16,0x64
    breq cmd_page
    /* Only LEAVE is odd among remaining supported commands. Unsupported
     * odd commands also request a short exit; no ISP operation is executed. */
    ldi r17,0x08
    sbrc r16,0
    rcall config_wdt
    rjmp verify_eop
bad_packet:
    rjmp bad_packet
rx_word:
    rcall rx_char
    mov r0,r16
rx_char:
rx_wait:
    MINI_UART_RX_POLL
    MINI_UART_RECEIVE
    mov r1,r16
    ret
cmd_address:
    rcall rx_word
    movw r22,r0
    lsl r22
    rol r23
    brcs bad_packet
verify_eop:
    ldi r19,1
discard:
    rcall rx_char
    dec r19
    brne discard
    cpi r16,0x20
    brne bad_packet
    ldi r16,0x14
tx_char:
tx_wait:
    MINI_UART_TX_POLL
    MINI_UART_TRANSMIT
    ret
config_wdt:
#if MINI_UART_STYLE == 0
    ldi r28,0x60
    ldi r18,0x18
    std Y+0,r18
    std Y+0,r17
    ldi r28,0xc0
#else
    ldi r18,0x18
    out WDT_IO,r18
    out WDT_IO,r17
#endif
    ret
.global _code_end
_code_end:
.org BOOT_BYTES-3,0xff
.byte SIG0,SIG1,SIG2
.org BOOT_BYTES,0xff
boot256_end:
