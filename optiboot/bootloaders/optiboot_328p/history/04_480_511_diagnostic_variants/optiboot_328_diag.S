/*
 * optiboot_mini328_final.S: experimental size-optimized STK500v1/Optiboot derivative.
 * Target: ATmega328P, 16 MHz external crystal, UART0 115200 8N1, BOOTSZ=256 words.
 * Boot address: 0x7E00. GPL-2.0-or-later (derived from Optiboot by Peter Knight,
 * Bill Westfield and contributors). No physical-hardware test; experimental.
 *
 * AVR-GCC/AVR-AS and Clang integrated assembler can compile this source.
 * The assembler emits 512 bytes (0xFF gap, version at the end).
 * Main size is measured excluding fill and version.
 *
 * Deliberately dropped: LED flashes, EEPROM write, app-callable SPM service.
 * Experimental feature-extension variant based on 358B baseline.
 * Retained: MCU reset decision + WDT timeout, serial sync, GET_PARAMETER,
 * SET_DEVICE, SET_DEVICE_EXT, SET_PARAMETER, LOAD_ADDRESS, UNIVERSAL, PROG_PAGE, READ_PAGE,
 * READ_SIGN, LEAVE_PROGMODE; STK500v1 INSYNC/OK framing.
 * Adds EEPROM READ_PAGE and read-only ISP emulation for fuse/lock/signature.
 */

.section .text
.global _start
_start:
    rjmp boot_start
    ret                     ; disable optional app-callable SPM entry

/* Register allocation:
 * r1  = zero (cleared on boot and after page fill)
 * r2  = copy of MCUSR for application startup
 * r16 = UART byte/input/output value
 * r17 = watchdog configuration value
 * r18 = USART status/temp
 * r19 = discard loop count / SPMEN preload (1)
 * r20 = parameter selector or memory type for PROG_PAGE
 * r22:r23 = current flash BYTE address
 * r25 = page byte length for READ_PAGE, word count for PROG_PAGE
 * X = unused; the ATmega328P hardware SPM buffer stores the page
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
    breq command_parameter
1:  cpi  r16, 0x40         ; SET_PARAMETER, two args, ignored
    brne 1f
    ldi  r19, 2
    rjmp command_discard
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
1:
1:  cpi  r16, 0x56         ; UNIVERSAL
    breq command_universal
1:  cpi  r16, 0x64         ; PROG_PAGE
    brne 1f
    rjmp command_write
1:
1:  cpi  r16, 0x74         ; READ_PAGE
    brne 1f
    rjmp command_read
1:
1:  cpi  r16, 0x75         ; READ_SIGN
    brne 1f
    rjmp command_signature
1:
1:  cpi  r16, 0x51         ; LEAVE_PROGMODE
    brne command_default
    ldi  r17, 0x08        ; 16ms WDT with WDE
    rcall wdt_config
command_default:
    rcall verify_eop       ; SYNC, ENTER, LEAVE and other no-payload cmds
command_ok:
    ldi  r16, 0x10         ; STK_OK
    rcall tx_char
    rjmp next_command


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

/* Discard payload for SET_PARAMETER (2), SET_DEVICE (20),
 * SET_DEVICE_EXT (5). The two-byte SET_PARAMETER reply is INSYNC/OK.
 */
command_discard:
1:  rcall rx_char
    dec  r19
    brne 1b
    rcall verify_eop
    rjmp command_ok

/* STK_UNIVERSAL: four ISP command bytes, read-only emulation.
 * SPI-programming read commands supported on the chip via SPMCSR and LPM:
 *   50 00 00 00 -> low fuse,   50 08 00 00 -> extended fuse
 *   58 00 00 00 -> lock bits,  58 08 00 00 -> high fuse
 *   30 00 n  00 -> signature byte n (n=0,1,2)
 * Otherwise the original Optiboot-compatible reply of 0x00 is returned.
 * Crucial: do not treat ISP write commands as real programming requests.
 */
command_universal:
    rcall rx_char
    mov  r20, r16          ; ISP opcode
    rcall rx_char
    mov  r21, r16          ; ISP opcode second byte
    rcall rx_char
    mov  r24, r16          ; ISP opcode third byte
    rcall rx_char          ; fourth byte is dummy for read ops
    rcall verify_eop

    cpi  r20, 0x50
    breq universal_fuse_lo
    cpi  r20, 0x58
    breq universal_fuse_hi
    cpi  r20, 0x30
    breq universal_signature
    rjmp universal_zero
universal_fuse_lo:
    clr  r30
    rjmp universal_fuse_common
universal_fuse_hi:
    ldi  r30, 1
universal_fuse_common:
    tst  r24              ; only the read command form with byte 3==0
    brne universal_zero
    tst  r21
    breq universal_fuse_read
    cpi  r21, 8
    brne universal_zero
    subi r30, 0xFE        ; Z += 2 (extended/high fuse selectors)
universal_fuse_read:
    clr  r31
    ldi  r16, 0x09        ; BLBSET|SPMEN; LPM must follow OUT <=3 cycles
    out  0x37, r16
    lpm  r16, Z
    rjmp universal_result
universal_signature:
    tst  r21
    brne universal_zero
    cpi  r24, 3
    brsh universal_zero
    mov  r30, r24
    lsl  r30              ; signature index 0/1/2 => Z=0/2/4
    clr  r31
    ldi  r16, 0x21        ; SIGRD|SPMEN
    out  0x37, r16
    lpm  r16, Z
    rjmp universal_result
universal_zero:
    clr  r16
universal_result:
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

command_read:
    rcall read_length
    rcall rx_char
    mov  r20, r16          ; 'E'=EEPROM, everything else=Flash
    rcall verify_eop
    cpi  r20, 0x45
    breq eeprom_read
    movw r30, r22
read_loop:
    lpm  r16, Z+
    rcall tx_char
    dec  r25
    brne read_loop
    rjmp command_ok

/* ATmega328P EEAR IO: low=0x21 high=0x22; EECR=0x1F EEDR=0x20
 * avrdude sends the LOAD_ADDRESS value as word-address on ATmega328P,
 * which our LOAD_ADDRESS handler already multiplied by 2.
 * No SRAM page buffer required; read 1..256 bytes into UART.
 */
eeprom_read:
    movw r26, r22          ; X is the EEPROM byte-address
read_eeprom_loop:
1:  sbic 0x1F, 1           ; EEPE busy from any preceding write?
    rjmp 1b
    out  0x21, r26        ; EEARL
    out  0x22, r27        ; EEARH
    sbi  0x1F, 0          ; EERE
    in   r16, 0x20        ; EEDR
    rcall tx_char
    adiw r26, 1
    dec  r25
    brne read_eeprom_loop
    rjmp command_ok

command_signature:
    rcall verify_eop
    ldi  r16, 0x1E
    rcall tx_char
    ldi  r16, 0x95
    rcall tx_char
    ldi  r16, 0x0F
    rcall tx_char
    rjmp command_ok

command_write:
    rcall read_length
    rcall rx_char          ; memory type, accept all except 'E'
    mov  r20, r16
    lsr  r25               ; C=odd length; Z=zero; count now in words
    brcs protocol_error
    breq protocol_error
    cpi  r25, 65           ; ATmega328P hardware page holds 64 words
    brsh protocol_error
    movw r30, r22
    ldi  r19, 0x01         ; preloaded SPMEN across whole page (saves cycles)

/* Fill the ATmega328P's hardware temporary page buffer BEFORE flash erase.
 * Atmel datasheet 30.8 explicitly allows SPM fill -> page erase -> write.
 * A bad CRC_EOP cannot destroy old Flash: no page erase has happened.
 * Unlike the SRAM version this uses no 128-byte software buffer.
 */
hardware_fill_loop:
    rcall rx_char
    mov  r0, r16
    rcall rx_char
    mov  r1, r16
    out  0x37, r19         ; SPMEN page buffer fill
    spm
    adiw r30, 2
    dec  r25
    brne hardware_fill_loop
    clr  r1
    rcall verify_eop      ; STK_INSYNC must precede actual erase
    cpi  r20, 0x45        ; EEPROM unsupported: send INSYNC then timeout
    breq error_loop
    cpi  r23, 0x7E        ; refuse modifying the boot partition
    brsh protocol_error

    movw r30, r22
    ldi  r16, 0x03        ; erase, hardware temp page buffer retained!
    rcall spm_execute_wait
    ldi  r16, 0x05        ; write temporary page buffer to Flash
    rcall spm_execute_wait
    ldi  r16, 0x11        ; RWWSRE|SPMEN
    out  0x37, r16
    spm
    rjmp command_ok

protocol_error:
    ldi  r17, 0x08
    rcall wdt_config       ; 16ms watchdog
error_loop:
    rjmp error_loop


read_length:
    rcall rx_char          ; high length byte discarded, as upstream HEX does
    rcall rx_char          ; low length byte
    mov  r25, r16
    ret

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
