/* Experimental flash-only 256 byte bootloader, STK500v1 subset.
 * AVRDUDE -c arduino -D -V command subset only: GET_SYNC, GET_PARAMETER,
 * SET_DEVICE, SET_DEVICE_EXT, ENTER_PROGMODE, LOAD_ADDRESS, PROG_PAGE,
 * READ_SIGN, LEAVE_PROGMODE. Full-page writes only. Prepare HEX through
 * flash256/prepare_avrdude_hex.py before using AVRDUDE. No read-back, EEPROM,
 * application SPM, GET_SIGN_ON, UNIVERSAL, chip erase or fuse operations.
 * Shared MCU/UART configuration with Optiboot Mini.  GPL-2.0-or-later.
 */
#ifndef MINI_FLASH256_READBACK
#define MINI_FLASH256_READBACK 0
#endif
#if MINI_VIRTUAL_BOOT || FLASH_SIZE > 16384 || MINI_FLASH_BANKED || MINI_SPM_EXT || MINI_SOFT_UART
#error Flash256 requires classic hardware-Boot 8/16KiB ATmega
#endif
#if MINI_FLASH256_READBACK && BOOT_BYTES != 512
#error STK_READ_PAGE requires 512-byte physical Boot section in this implementation
#elif !MINI_FLASH256_READBACK && BOOT_BYTES != 256
#error Flash-only write-only profile requires 256-byte physical Boot section
#endif
#if FLASH_PAGE_BYTES != 64 && FLASH_PAGE_BYTES != 128
#error Flash256 requires 64/128-byte hardware Flash pages
#endif
.section .text
.global _start
_start:
    cli
#if MINI_LEGACY_STACK
    ldi r16,(SRAM_END & 0xff)
    out 0x3d,r16
    ldi r16,(SRAM_END >> 8)
    out 0x3e,r16
#endif
    clr r1
#if MINI_UART_STYLE == 0
    clr r29        /* required for Y=0x00C0 / WDT=0x0060 */
#endif
    in r16,MCUSR_IO
    out MCUSR_IO,r1
    /* Disable WDT before taking the application exit; WDRF forces WDE
     * until reset flags are cleared and the timed WDT sequence completes. */
    wdr
    ldi r17,0
    rcall config_wdt
    sbrc r16,3
    rjmp boot256_end
    /* config_wdt already leaves r18 = 0x18, used for UART enable. */
    /* config_wdt has already initialized Y to USART0 on modern parts. */
    MINI_UART_INIT
    ldi r17,0x0e
    rcall config_wdt
cmd_loop:
    rcall rx_char
    cpi r16,0x41   /* GET_PARAMETER: 1 byte */
    breq cmd_parameter
    cpi r16,0x42   /* SET_DEVICE: 20 bytes */
    breq cmd_set_device
    cpi r16,0x45   /* SET_DEVICE_EXT: 5 */
    breq cmd_set_device_ext
    cpi r16,0x55   /* LOAD_ADDRESS: word address */
    breq cmd_address
#if MINI_FLASH256_READBACK
    cpi r16,0x75
    breq cmd_signature
    /* READ_PAGE (0x74) and PROG_PAGE (0x64) share a parser.
     * Save bit 4 as T before masking; UART RX does not clobber T. */
    bst r16,4
    andi r16,0xef
    cpi r16,0x64
    breq cmd_page
    cpi r16,0x41  /* LEAVE 0x51 was masked to 0x41 */
#else
    cpi r16,0x64   /* PROG_PAGE: Flash-only */
    breq cmd_write
    cpi r16,0x75   /* READ_SIGN */
    breq cmd_signature
    cpi r16,0x51   /* LEAVE_PROGMODE */
#endif
    brne cmd_done
    ldi r17,0x08  /* WDT 16ms after ACK */
    rcall config_wdt
cmd_done:
    rcall verify_eop
cmd_ok:
    ldi r16,0x10
    rcall tx_char
    rjmp cmd_loop

cmd_set_device:
    ldi r19,20
    rjmp discard
cmd_set_device_ext:
    ldi r19,5
discard:
    rcall rx_char
    dec r19
    brne discard
    rjmp cmd_done

cmd_parameter:
    rcall rx_char
    rcall verify_eop
    ldi r16,3
    rcall tx_char
    rjmp cmd_ok

cmd_address:
    rcall rx_char
    mov r22,r16
    rcall rx_char
    mov r23,r16
    lsl r22
    rol r23
    rjmp cmd_done

cmd_signature:
#if MINI_FLASH256_READBACK
    /* Reuse STK_READ_PAGE LPM loop to send signature without 3 TX calls. */
    ldi r25,3
    ldi r30,lo8(BOOT_START + BOOT_BYTES - 4)
    ldi r31,hi8(BOOT_START + BOOT_BYTES - 4)
    rjmp read_common
#else
    rcall verify_eop
    ldi r16,SIG0
    rcall tx_char
    ldi r16,SIG1
    rcall tx_char
    ldi r16,SIG2
    rcall tx_char
    rjmp cmd_ok
#endif

#if MINI_FLASH256_READBACK
cmd_page:
#else
cmd_write:
#endif
    /* Only full-page, aligned writes; avrdude sends page-size bytes. */
    /* Consume length MSB and LSB. Only a full physical page is
     * read; a shorter or longer frame fails EOP BEFORE any erase.
     * This saves 8B of redundant explicit length checks. */
    rcall rx_char
#if MINI_FLASH256_READBACK
    tst r16                /* Reject >255-byte blocks */
    brne bad_packet
#endif
    rcall rx_char
#if MINI_FLASH256_READBACK
    mov r25,r16            /* Exact READ_PAGE length / PROG_PAGE page size */
#endif
    rcall rx_char
    cpi r16,0x46  /* F */
    brne bad_packet
    /* Reject attempts to overwrite boot, before any SPM erase. */
    cpi r23,(BOOT_START >> 8)
    brsh bad_packet
    mov r16,r22
    andi r16,(FLASH_PAGE_BYTES - 1)
    brne bad_packet
    movw r30,r22
#if MINI_FLASH256_READBACK
    brts read_page
    cpi r25,FLASH_PAGE_BYTES
    brne bad_packet
#endif
    ldi r25,(FLASH_PAGE_BYTES/2)
fill_loop:
    rcall rx_char
    mov r0,r16
    rcall rx_char
    mov r1,r16
    ldi r18,0x01
#if MINI_FLASH256_READBACK
    rcall execute_spm       /* Reuse existing SPM + wait routine */
#else
    out SPMCSR_IO,r18
    spm
#endif
    adiw r30,2
    dec r25
    brne fill_loop
    rcall verify_eop   /* never erase before EOP verified */
    movw r30,r22
    ldi r18,0x03
    rcall execute_spm
    ldi r18,0x05
    rcall execute_spm
    ldi r18,0x11
    rcall execute_spm
    rjmp cmd_ok

#if MINI_FLASH256_READBACK
read_page:
    tst r25
    breq bad_packet
    cpi r25,FLASH_PAGE_BYTES+1
    brsh bad_packet
read_common:
    rcall verify_eop
read_loop:
    lpm r16,Z+
    rcall tx_char
    dec r25
    brne read_loop
    rjmp cmd_ok
#endif

execute_spm:
    out SPMCSR_IO,r18
    spm
wait_spm:
    in r18,SPMCSR_IO
    sbrc r18,0
    rjmp wait_spm
    ret

bad_packet:
    /* Keep the normal 1s WDT running; no Flash erase has occurred. */
    rjmp bad_packet
rx_char:
rx_wait:
    MINI_UART_RX_POLL
    MINI_UART_RECEIVE
    ret
verify_eop:
    rcall rx_char
    cpi r16,0x20
    brne bad_packet
    ldi r16,0x14
    /* Fall through into tx_char. Both have the same ABI. */
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
#if MINI_FLASH256_READBACK
    .org BOOT_BYTES-4,0xff
    .byte SIG0,SIG1,SIG2  /* readback and READ_SIGN share LPM */
#endif
.org BOOT_BYTES,0xff
boot256_end:
