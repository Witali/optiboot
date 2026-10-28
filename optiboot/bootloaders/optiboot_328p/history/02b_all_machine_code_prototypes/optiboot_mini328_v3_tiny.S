/*
 * optiboot_mini328_v3_tiny.S: experimental size-optimized STK500v1/Optiboot derivative.
 * Target: ATmega328P, 16 MHz external crystal, UART0 115200 8N1, BOOTSZ=256 words.
 * Boot address: 0x7E00. GPL-2.0-or-later (derived from Optiboot by Peter Knight,
 * Bill Westfield and contributors). No physical-hardware test; experimental.
 *
 * AVR-GCC/AVR-AS and Clang integrated assembler can compile this source.
 * The assembler emits 512 bytes (0xFF gap, version at the end).
 * Main size is measured excluding fill and version.
 *
 * Deliberately dropped: LED flashes, EEPROM, app-callable SPM service.
 * Retained: MCU reset decision + WDT timeout, serial sync, GET_PARAMETER,
 * SET_DEVICE, SET_DEVICE_EXT, LOAD_ADDRESS, UNIVERSAL, PROG_PAGE, READ_PAGE,
 * READ_SIGN, LEAVE_PROGMODE; STK500v1 INSYNC/OK framing.
 */

.section .text
.global _start
_start:
    rjmp boot_start

/* Register allocation:
 * r1  = zero (cleared on boot and after page fill)
 * r2  = copy of MCUSR for application startup
 * r16 = UART byte/input/output value
 * r17 = work register, WDT configuration, signature values
 * r18 = USART status/temp
 * r19 = loop count
 * r20 = parameter type
 * r22:r23 = current flash BYTE address
 * r24 = temp
 * r25 = page byte length
 * X = SRAM buffer pointer (0x0100)
 * Z = flash address or page-fill address
 */
boot_start:
    cli
    clr r1
    in   r16, 0x34         ; MCUSR
    mov  r2, r16
    out  0x34, r1          ; clear reset reason (enables WDT disable after WDRF)
    wdr
    clr  r17
    rcall wdt_config        ; disable watchdog on application start
    tst  r16              ; cleared MCUSR = explicit software bootloader entry
    breq start_uart
    andi r16, 0x0A         ; WDRF | EXTRF
    cpi  r16, 0x02         ; enter only on external reset without WDRF
    breq start_uart
    rjmp boot_end          ; 16K-word PC wraps from end of Flash to 0

start_uart:
    ldi  r16, 0x02         ; U2X0 (double-speed UART0)
    sts  0xC0, r16         ; UCSR0A
    ldi  r16, 0x18         ; RXEN0 | TXEN0
    sts  0xC1, r16         ; UCSR0B
    ldi  r16, 0x06         ; 8N1
    sts  0xC2, r16         ; UCSR0C
    ldi  r16, 16           ; UBRR0 = 16, 117647 actual baud @16MHz (+2.12%)
    sts  0xC4, r16         ; UBRR0L
    ldi  r17, 0x0E         ; WDT 1s: WDE|WDP2|WDP1
    rcall wdt_config

next_command:
    rcall rx_char
    cpi  r16, 0x41         ; GET_PARAMETER
    brne 1f
    rjmp command_parameter
1:  cpi  r16, 0x42         ; SET_DEVICE
    brne 1f
    ldi  r19, 20
    rjmp command_discard
1:  cpi  r16, 0x45         ; SET_DEVICE_EXT
    brne 1f
    ldi  r19, 5
    rjmp command_discard
1:  cpi  r16, 0x55         ; LOAD_ADDRESS
    brne 1f
    rjmp command_address
1:  cpi  r16, 0x56         ; UNIVERSAL
    brne 1f
    ldi  r19, 4
    rjmp command_universal
1:  cpi  r16, 0x64         ; PROG_PAGE
    brne 1f
    rjmp command_write
1:  cpi  r16, 0x74         ; READ_PAGE
    brne 1f
    rjmp command_read
1:  cpi  r16, 0x75         ; READ_SIGN
    brne 1f
    rjmp command_signature
1:  cpi  r16, 0x51         ; LEAVE_PROGMODE
    brne 1f
    rjmp command_leave
1:  rcall verify_eop       ; SYNC, ENTER_PROGMODE, other no-payload cmds
    rjmp command_ok

command_parameter:
    rcall rx_char
    mov  r20, r16
    rcall verify_eop
    ldi  r16, 3            ; non-version parameter
    cpi  r20, 0x81         ; software major version
    brne 1f
    ldi  r16, 8
1:  rcall tx_char          ; minor and other params are both 3
    rjmp command_ok

/* Shared discard for SET_DEVICE (20), SET_DEVICE_EXT (5), UNIVERSAL (4).
 * 4-byte discard also returns an extra zero response byte.
 */
command_discard:
command_universal:
    mov  r20, r19
1:  rcall rx_char
    dec  r19
    brne 1b
    rcall verify_eop
    cpi  r20, 4
    breq 2f
    rjmp command_ok
2:  clr  r16
    rcall tx_char
    rjmp command_ok

command_address:
    rcall rx_char
    mov  r22, r16          ; word-address low
    rcall rx_char
    mov  r23, r16          ; word-address high
    lsl  r22               ; word -> byte address
    rol  r23
    rcall verify_eop
    rjmp command_ok

command_write:
    rcall read_length
    rcall rx_char          ; memory type ('E' unsupported, but consume payload)
    mov  r20, r16
    tst  r25
    breq protocol_error
    cpi  r25, 129          ; max 128 bytes/page
    brsh protocol_error
    sbrc r25, 0           ; SPM fill requires pairs of bytes
    rjmp protocol_error
    ldi  r26, 0            ; buffer X=0x0100
    ldi  r27, 1
    mov  r19, r25
write_rx_loop:
    rcall rx_char
    st   X+, r16
    dec  r19
    brne write_rx_loop
    rcall verify_eop
    cpi  r20, 0x45         ; original sends INSYNC, then waits for WDT
    breq error_loop

    cpi  r23, 0x7E         ; don't write boot area, regardless of BOOTLOCK
    brsh protocol_error
    movw r30, r22
    ldi  r16, 0x03         ; PGERS|SPMEN
    rcall spm_execute_wait
    clr  r26                ; X = 0x0100 after receiving <=128 bytes
    movw r30, r22
    mov  r19, r25
write_spm_loop:
    ld   r0, X+
    ld   r1, X+
    ldi  r16, 0x01         ; SPMEN (page fill)
    out  0x37, r16
    spm
    adiw r30, 2
    subi r19, 2
    brne write_spm_loop
    clr  r1                ; ABI zero register used by application startup
    movw r30, r22
    ldi  r16, 0x05         ; PGWRT | SPMEN
    rcall spm_execute_wait
    ldi  r16, 0x11         ; RWWSRE | SPMEN
    out  0x37, r16
    spm
    rjmp command_ok

protocol_error:
    ldi  r17, 0x08
    rcall wdt_config       ; 16ms watchdog
error_loop:
    rjmp error_loop


command_read:
    rcall read_length
    rcall rx_char
    mov  r20, r16
    rcall verify_eop
    cpi  r20, 0x45         ; original sends INSYNC, then waits for WDT
    breq error_loop
    movw r30, r22
read_loop:
    lpm  r16, Z+
    rcall tx_char
    dec  r25
    brne read_loop
    rjmp command_ok

read_length:
    rcall rx_char          ; high byte (expected 0)
    rcall rx_char          ; low byte
    mov  r25, r16
    ret

command_signature:
    rcall verify_eop
    ldi  r16, 0x1E
    rcall tx_char
    ldi  r16, 0x95
    rcall tx_char
    ldi  r16, 0x0F
    rcall tx_char
    rjmp command_ok

command_leave:
    ldi  r17, 0x08        ; 16ms WDT with WDE
    rcall wdt_config
    rcall verify_eop

command_ok:
    ldi  r16, 0x10         ; STK_OK
    rcall tx_char
    rjmp next_command

verify_eop:
    rcall rx_char
    cpi  r16, 0x20         ; CRC_EOP = ' '
    brne protocol_error
    ldi  r16, 0x14         ; STK_INSYNC
    rjmp tx_char           ; tail call: tx_char returns to caller of verify_eop

rx_char:
rx_wait:
    lds  r18, 0xC0        ; UCSR0A
    sbrs r18, 7           ; RXC0
    rjmp rx_wait
    sbrs r18, 4           ; FE0=1: do not keep WDT alive on framing error
    wdr                    ; good frames only
    lds  r16, 0xC6        ; UDR0
    ret

tx_char:
tx_wait:
    lds  r18, 0xC0        ; UCSR0A
    sbrs r18, 5           ; UDRE0
    rjmp tx_wait
    sts  0xC6, r16        ; UDR0
    ret

wdt_config:
    ldi  r18, 0x18          ; WDCE | WDE
    sts  0x60, r18         ; timed change sequence
    sts  0x60, r17
    ret

spm_execute_wait:
    out  0x37, r16
    spm
wait_spm:
    in   r18, 0x37        ; SPMCSR
    sbrc r18, 0
    rjmp wait_spm
    ret

/* For AVR fuses 0xDE (512B boot section), ensure version at 0x7FFE.
 * Fail assembly if instructions use more than 510 bytes.
 */
.global _code_end
_code_end:
.fill (0x01FE - (. - _start)), 1, 0xFF
.byte 3, 8
boot_end:
