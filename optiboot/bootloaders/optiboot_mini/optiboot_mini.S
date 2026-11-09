/*
 * Optiboot Mini STK500v1 multi-device experimental port, October 2026.
 * Default ATmega328P / 16MHz / UART0 115200 8N1; target via -mmcu and device includes.
 * Boot origin/footer are calculated from FLASH_SIZE and BOOT_BYTES.
 * Experimental: no silicon test and no real avrdude run.
 *
 * Fixes vs the 512B Optiboot Mini: checks BOTH length bytes for
 * STK_READ_PAGE/STK_PROG_PAGE, supports valid read length 0x0100=256,
 * refuses unknown memory types with INSYNC+FAILED instead of touching FLASH,
 * implements STK_GET_SIGN_ON with AVR061's "AVR STK" reply.
 *
 * Uses Y as stable USART0 base for modern parts; legacy parts use IN/OUT.
 * For 128/256 KiB Flash: r3 holds upper byte-address bits, RAMPZ drives
 * ELPM/SPM, and full-bank overflow and boot-sector writes are rejected.
 * 128/256 KiB targets use 1024-byte boot sections (not limited to 512 B).
 * Shares two-byte receive and common error responses across handlers.
 * Keeps avrdude -c arduino format, read/write FLASH, 1..16B EEPROM writes,
 * EEPROM read, read-only UNIVERSAL fuse/lock commands, WDT and SPM interlock.
 * Preserves Optiboot's ACK without true Chip Erase for legacy avrdude.
 * Rejects overflow in LOAD_ADDRESS, restores r1 and UBRR0H; validates FLASH read ends.
 * r1 is cleared at boot entry. Match BOOTSZ to the emitted build manifest.
 * Full AVR061 is NOT implemented. Every new MCU port requires hardware testing.
 *
 * Based on Optiboot, Copyright (c) Peter Knight, Bill Westfield et al.
 * GPL-2.0-or-later; see COPYING. Hardware testing and ISP recovery required.
 */

/* Single executable source for every supported MCU.  The target -mmcu selects
 * exactly ONE device include, hence exactly ONE 3-byte silicon signature.
 * Unsupported peripherals and services never enter the assembled image.
 */
#include "devices/select.inc"
#ifndef F_CPU
#define F_CPU 16000000UL
#endif
#ifndef BAUD_RATE
#define BAUD_RATE 115200UL
#endif
#include "uart/select.inc"
#if defined(MINI_FLASH_ONLY_256) && MINI_FLASH_ONLY_256
#include "flash256/flash256.inc"
#else
/* Silicon signature-row read is only valid on device profiles audited for
 * SIGRD|SPMEN and Z addresses 0,2,4.  The fallback uses the footer bytes.
 * Default remains the original footer path for binary compatibility.
 */
#ifndef MINI_SIGROW_HARDWARE
#define MINI_SIGROW_HARDWARE 0
#endif
#ifndef MINI_DEVICE_SIGROW_CAPABLE
#define MINI_DEVICE_SIGROW_CAPABLE 0
#endif
#if MINI_SIGROW_HARDWARE && !MINI_DEVICE_SIGROW_CAPABLE
#error Hardware SIGRD+LPM is not verified for this MCU; use footer constants
#endif
/* Compact 64KiB / 256-byte-page / modern USART0 family experiment. The physical
 * BOOTSZ is still 1024 bytes / 512 words, never 512 bytes.  The compact
 * SPM512 instruction core is reused at BOOT_START+2; the signature/version
 * footer remains at the physical Flash end.  No binary patching.
 */
#ifndef MINI_COMPACT_64K
#define MINI_COMPACT_64K 0
#endif
/* Compact 128/256-KiB SPM ABI and 5-byte footer in a 1024-byte hardware
 * section. Banked ELPM/RAMPZ and upper-address validations are retained. */
#ifndef MINI_COMPACT_BANKED
#define MINI_COMPACT_BANKED 0
#endif
#if MINI_COMPACT_BANKED && (!MINI_FLASH_BANKED || FLASH_PAGE_BYTES != 256 || BOOT_BYTES != 1024 || MINI_VIRTUAL_BOOT)
#error The compact banked profile requires a 128/256KiB hardware-Boot AVR
#endif
#if MINI_COMPACT_BANKED
/* Code was rearranged so every remaining short branch stays in reach.
 * The AVR assembler enforces the displacement at build time. */
#undef MINI_WIDE_BRANCHES
#define MINI_WIDE_BRANCHES 0
#endif

#if MINI_COMPACT_64K
#if !(defined(__AVR_ATmega644__) || defined(__AVR_ATmega644A__) || defined(__AVR_ATmega644P__) || defined(__AVR_ATmega644PA__) || defined(__AVR_ATmega640__) || defined(__AVR_ATmega64A__))
#error MINI_COMPACT_64K requires ATmega644 family or ATmega640
#endif
#if FLASH_SIZE != 65536 || FLASH_PAGE_BYTES != 256 || BOOT_BYTES != 1024 || MINI_VIRTUAL_BOOT || (MINI_UART_STYLE != 0 && MINI_UART_STYLE != 2)
#error Incorrect 64KiB 256B-page family 1024-byte BOOTSZ or hardware profile
#endif
#undef MINI_WIDE_BRANCHES
#define MINI_WIDE_BRANCHES 0  /* All conditional destinations are checked by AVR assembler. */
#endif
#ifndef MINI_U2X
#define MINI_U2X 1
#endif
#ifndef MINI_UBRR
#define MINI_UBRR (((F_CPU + 4UL * BAUD_RATE) / (8UL * BAUD_RATE)) - 1)
#endif
#if MINI_UBRR < 0 || MINI_UBRR > 4095
#error Unsupported UART divider
#endif
#if FLASH_SIZE > 262144
#error This implementation addresses at most 256 KiB of Flash
#endif
#if MINI_FLASH_BANKED && ((FLASH_SIZE != 131072) && (FLASH_SIZE != 262144))
#error RAMPZ addressing is supported for 128 or 256 KiB devices
#endif
#if MINI_FLASH_256K && FLASH_SIZE != 262144
#error The STK_UNIVERSAL extended address port requires 256 KiB
#endif
/* AVRDUDE releases before its 2022 STK500v1 fix can use BYTE addresses
 * for EEPROM on ATmega64A/ATmega128A, unlike the normal WORD convention.
 * This build-time variant is explicit because the two host conventions
 * cannot be reliably inferred from the 16-bit LOAD_ADDRESS packet.
 */
#ifndef MINI_OLD_AVRDUDE_EEPROM
#define MINI_OLD_AVRDUDE_EEPROM 0
#endif
/* Optional signature compatibility for stk500v1 hardware programmer clients.
 * -c arduino uses STK_READ_SIGN (0x75), which is already supported.
 * -c stk500v1 reads the signature using UNIVERSAL 30 00 <index> 00.
 * The compatibility mode preserves all existing protocol handlers, but may
 * require a larger BOOTSZ if optimization cannot keep it in 512 bytes.
 */
#ifndef MINI_UNIVERSAL_SIGNATURE
#define MINI_UNIVERSAL_SIGNATURE 0
#endif
/* 512-byte opt-in variant: universal signature only, not universal fuse/lock.
 * Full-featured builds with MINI_COMPACT_UNIVERSAL_SIGNATURE=0 are unchanged.
 */
#ifndef MINI_COMPACT_UNIVERSAL_SIGNATURE
#define MINI_COMPACT_UNIVERSAL_SIGNATURE 0
#endif
/* Optional real fuse/lock READ on 64KiB compact family. The extra opcodes
 * do not fit a 512-byte payload; this is strictly an optional 1024B BOOTSZ
 * flavor. EEPROM and Optiboot app-SPM are not removed to make space. */
/* Optional exact AVR061 GET_SIGN_ON reply for compact profiles.
 * Strictly build-time: no profile grows its physical BOOTSZ implicitly.
 */
#ifndef MINI_COMPACT_SIGN_ON
#define MINI_COMPACT_SIGN_ON 0
#endif
#ifndef MINI_COMPACT_FUSE_LOCK_READ
#define MINI_COMPACT_FUSE_LOCK_READ 0
#endif
#if MINI_COMPACT_FUSE_LOCK_READ && !(MINI_COMPACT_64K && MINI_COMPACT_UNIVERSAL_SIGNATURE)
#error Fuse/lock read add-on requires the compact 64KiB class
#endif
#if MINI_COMPACT_UNIVERSAL_SIGNATURE && !MINI_UNIVERSAL_SIGNATURE
#error Compact mode requires universal signature support
#endif
#ifndef MINI_APP_SPM
#define MINI_APP_SPM 0
#endif
#ifndef MINI_APP_SPM_512
#define MINI_APP_SPM_512 0
#endif
/* Virtual-Boot ATtiny can use the compact STK500 protocol and signature
 * footer, without exposing a fictitious application SPM ABI. */
#ifndef MINI_TINY_COMPACT
#define MINI_TINY_COMPACT 0
#endif
/* Virtual Boot can reserve any whole number of Flash erase groups between
 * 512 and 1024 bytes. This is stricter than page alignment on tiny841/1634
 * (four physical pages are erased together); never split an erase group.
 */
#if MINI_TINY_COMPACT && (!MINI_VIRTUAL_BOOT || MINI_APP_SPM || MINI_APP_SPM_512 || BOOT_BYTES < 512 || BOOT_BYTES > 1024 || (BOOT_BYTES % FLASH_PAGE_BYTES) || (BOOT_BYTES % MINI_FLASH_ERASE_GROUP_BYTES))
#error MINI_TINY_COMPACT requires page/erase-group-aligned 512..1024-byte Virtual Boot without APP_SPM
#endif
#if MINI_TINY_COMPACT
#undef MINI_WIDE_BRANCHES
#define MINI_WIDE_BRANCHES 0  /* Only short conditional jumps; assembler checks range. */
#endif

/* Enable upstream Optiboot 8.3 MCUSR semantics on any supported device.
 * Preserve existing standalone legacy images when this is not selected.
 */
#ifndef MINI_MCUSR_PARITY
#define MINI_MCUSR_PARITY MINI_APP_SPM_512
#endif
/* ATtiny virtual boot has no dedicated Boot Section. Application code can
 * execute SPM directly (when SELFPRGEN is programmed), so it must NOT expose
 * a synthetic Optiboot BOOT_START+2 application-callable SPM entry.
 */
#if MINI_APP_SPM_512 && (!MINI_COMPACT_64K && !MINI_COMPACT_BANKED && (!MINI_SPM512_CAPABLE || BOOT_BYTES != 512) || !MINI_COMPACT_UNIVERSAL_SIGNATURE || !MINI_UNIVERSAL_SIGNATURE || !MINI_APP_SPM)
#error Compact SPM requires hardware-compatible profile, matching boot size, dual signature, and APP_SPM
#endif
#if MINI_APP_SPM && BOOT_BYTES < 1024 && !MINI_APP_SPM_512
#error The full app-callable SPM service requires a >=1024-byte boot section
#endif
#if MINI_APP_SPM && MINI_VIRTUAL_BOOT
#error Virtual Boot ATtiny uses direct application SPM; do not enable MINI_APP_SPM
#endif
#if MINI_FLASH_ERASE_GROUP_BYTES < FLASH_PAGE_BYTES || (MINI_FLASH_ERASE_GROUP_BYTES % FLASH_PAGE_BYTES)
#error Invalid Flash erase group geometry
#endif
#if MINI_WDT_CCP_STYLE && !MINI_VIRTUAL_BOOT
#error CCP watchdog variant belongs to a Virtual Boot profile
#endif
#if MINI_SOFT_UART != (MINI_UART_STYLE == 5)
#error Software UART capability/profile mismatch
#endif
#if MINI_COMPACT_UNIVERSAL_SIGNATURE && (!MINI_SPM512_CAPABLE && !MINI_COMPACT_64K && !MINI_COMPACT_BANKED && !MINI_TINY_COMPACT)
#error Compact dual-signature mode requires supported classic ATmega profile
#endif

/* R7: one architecture-specialized source, shared bodies but two placements.
 * Moving TX after EOP and LOAD_ADDRESS after UNIVERSAL makes their short
 * branches converge on classic USART AVRs. Banked and software-UART profiles
 * retain R6 code placement because their BRxx reachability differs. */
#ifndef MINI_R7_TAIL_FUSION
#define MINI_R7_TAIL_FUSION ((MINI_APP_SPM_512 || MINI_TINY_COMPACT) && !MINI_FLASH_BANKED && !MINI_SOFT_UART && !MINI_COMPACT_FUSE_LOCK_READ)
#endif
.macro MINI_R7_ADDRESS_BODY
    rcall read_length     ; receive low/high word bytes into r24:r25
    movw r22, r24         ; low/high bytes into address register pair
    lsl  r22               ; word -> byte address
    rol  r23
#if MINI_FLASH_BANKED
    clr  r3
    adc  r3, r29          ; word bit 15 becomes byte-address bit 16
#if MINI_FLASH_256K
    bst  r4,0             ; 4D 00 <bank> 00 -> 17th word-address bit
    bld  r3,1             ; 18th byte-address bit / RAMPZ bit 1
#endif
#elif MINI_SPM_EXT && !MINI_COMPACT_64K
    brcc .Lme64_error_skip_0
    rjmp protocol_error
.Lme64_error_skip_0:
#elif MINI_UNIVERSAL_SIGNATURE && !MINI_COMPACT_UNIVERSAL_SIGNATURE
    brcc .Laddress_no_overflow_wide
    rjmp protocol_error
.Laddress_no_overflow_wide:
#else
#if MINI_COMPACT_FUSE_LOCK_READ
    brcc .Laddress_small_safe
    rjmp protocol_error
.Laddress_small_safe:
#else
    brcs protocol_error   ; reject word address >= 0x8000, avoid 16-bit wrap
#endif
#endif
    rjmp command_default

.endm
.macro MINI_R7_TX_ROUTINE
tx_char:
tx_wait:
#if MINI_SOFT_UART
    ; Direct entry for TX with the same original bit-loop timing.
    MINI_UART_SOFT_TX_ROUTINE
#else
    MINI_UART_TX_POLL
    MINI_UART_TRANSMIT
    ret
#endif

.endm
.section .text
.global _start
_start:
#if MINI_APP_SPM
    ; Official Optiboot 8.x ABI: BOOT_START+0 = skip table,
    ; BOOT_START+2 = callable do_spm(uint16_t address, uint8_t command,
    ;                              uint16_t data).
    ; Standard Optiboot ABI: BOOT_START+2, exact entry in words.
    ; Compact profile (512-byte on small ATmega, 1024-byte BOOTSZ on
    ; ATmega644 family) places the SPM body at this entry directly.
    rjmp boot_start
#if MINI_APP_SPM_512
app_spm_service:
    ; Upper address guard: SPM must never write the 512-byte Boot section.
    ; Caller must pass an application address even for RWW/lock operations.
    ; The function intentionally uses official Optiboot's interrupt contract:
    ; caller must ensure it does not execute interrupts from a Flash page
    ; being erased or written; no global CLI/SREG prologue is fitted here.
#if MINI_FLASH_BANKED
    in r18,RAMPZ_IO
    cpi r18,(BOOT_START >> 16)
    brlo .Lspm_512_addr_ok
    brne .Lspm_512_ret
#endif
    cpi r25, ((BOOT_START >> 8) & 0xFF)
    brsh .Lspm_512_ret
.Lspm_512_addr_ok:
    movw r30,r24
    movw r0,r20
    mov r24,r22
    rcall spm_execute_wait
    clr r1
    andi r22,6
    breq .Lspm_512_ret
    or r20,r21
    brne .Lspm_512_ret
    ldi r24,0x11
    rcall spm_execute_wait ; share RWW-enable + SPM busy wait
.Lspm_512_ret:
    ret
#else
    rjmp app_spm_service
#endif
#else
    ; Old 512-byte boot image: CLI remains at BOOT_START+0.
#endif

/* Register allocation:
 * r1  = cleared on entry; later used as HIGH data byte during Flash fill
 * r2  = copy of MCUSR for application startup
 * r3  = Flash 64-KiB bank index (RAMPZ), when MINI_FLASH_BANKED
 * r4  = high word-address bit for 256-KiB STK500v1 LOAD_EXT_ADDR
 * r29 = zero from boot entry; must remain zero (Y=0x00C0 on modern USART)
 * r16 = UART byte/input/output value
 * r17 = watchdog configuration value
 * r18 = USART status/temp
 * r19 = shared discard count / EEPROM receive count / SPMEN preload (1)
 * r20 = GET_PARAMETER selector, READ_PAGE memory type, ISP opcode1
 * r21 = UNIVERSAL ISP opcode2 (bit 3 mapped into Z via T flag)
 * r22:r23 = low 16 bits of the current BYTE address (Flash or EEPROM)
 * r25 = page byte length for READ_PAGE, word count for Flash PROG_PAGE
 * X = EEPROM READ pointer; EEPROM WRITE payload is held on AVR stack
 * Y = UART base on modern parts, zero-high register on legacy devices
 * Z = flash address, page-fill address, or EEPROM last-byte address
 */
boot_start:
    cli
#if MINI_LEGACY_STACK
    ; Older AVR devices do not initialize SP automatically on reset.
    ldi r16, (SRAM_END & 0xFF)
    out 0x3D, r16
    ldi r16, ((SRAM_END >> 8) & 0xFF)
    out 0x3E, r16
#endif
    clr r1                 ; AVR zero register restored for application
    clr r29                ; zero register available from very first instruction
#if MINI_FLASH_BANKED
    clr r3                 ; current Flash byte-address bank index (RAMPZ)
    out RAMPZ_IO,r3
#endif
#if MINI_FLASH_256K
    clr r4                 ; extended word address (from STK_UNIVERSAL 4D)
#endif
    in   r16, MCUSR_IO     ; MCUSR varies on ATtiny1634
    mov  r2, r16
#if !MINI_MCUSR_PARITY
    out  MCUSR_IO, r29     ; Legacy Mini behavior: clear reset reason.
#else
    ; Optiboot 8.3 reset-flag contract: preserve PORF/BORF/EXTRF, and clear
    ; ONLY WDRF when EXTRF was present. Use 0xF7 (write-zero-to-clear).
    ; We can issue this write even for EXTRF without WDRF: no flag changes.
    ; Crucially this runs BEFORE disabling WDT, because WDRF forces WDE.
    ; r16 and r2 still hold the original MCUSR value for boot routing and app.
    ldi r18,0xF7
    sbrc r2,1
    out MCUSR_IO,r18
#endif
#if !(MINI_APP_SPM_512)
    wdr
#endif
    clr  r17
    rcall wdt_config        ; disable watchdog on application start
    tst  r16              ; cleared MCUSR = explicit software bootloader entry
    breq start_uart
    andi r16, 0x0A         ; WDRF | EXTRF
    cpi  r16, 0x02         ; enter only on external reset without WDRF
    breq start_uart
#if MINI_VIRTUAL_BOOT
    ; No BOOTRST fuse: reset-vector has been patched by tiny/patch_vectors.py.
    ; The reserved EEPROM-ready vector holds a relocated RJMP into the app.
    ; Jump through the end of FLASH so the short RJMP wraps to the vector.
    rjmp boot_end + (MINI_APP_VECTOR_WORD * 2)
#elif (BOOT_BYTES > 4096)
    jmp 0                  ; absolute jump only for oversized Boot sections
#else
    rjmp boot_end          ; wrap at program-memory end to reset vector zero
#endif

start_uart:
    MINI_UART_INIT
    ldi  r17, 0x0E         ; WDT 1s: WDE|WDP2|WDP1
    rcall wdt_config

/* EEPE can remain busy after an external reset while an application
 * EEPROM write is finishing.  Datasheet 26.8.8 prohibits SPMCSR writes
 * (including fuse reads) until EEPE clears.  Poll at every new packet.
 * Internal EEPROM writes already finish before STK_OK, so this replaces
 * the duplicate wait previously inside eeprom_read without size growth.
 */
next_command:
.Lwait_eepe_before_command:  sbic EEPROM_EECR_IO, 1           ; wait EEPE before any SPM/BLBSET operation
    rjmp .Lwait_eepe_before_command
    rcall rx_char
#if !(MINI_APP_SPM_512 || MINI_TINY_COMPACT) || MINI_COMPACT_SIGN_ON
    cpi  r16, 0x31         ; AVR061 GET_SIGN_ON
    breq command_signon
#endif
  cpi  r16, 0x41         ; GET_PARAMETER
    breq command_parameter
#if !(MINI_APP_SPM_512 || MINI_TINY_COMPACT)
    ldi  r19,2            ; candidate count for SET_PARAMETER
    cpi  r16, 0x40
    breq command_discard
#endif
    ldi  r19,20           ; candidate count for SET_DEVICE
    cpi  r16, 0x42
    breq command_discard
    ldi  r19,5            ; candidate count for SET_DEVICE_EXT
    cpi  r16, 0x45
    breq command_discard
    cpi  r16, 0x55         ; LOAD_ADDRESS
    breq command_address
.Ldispatch_universal:  cpi  r16, 0x56         ; UNIVERSAL
    breq universal_handler
  cpi  r16, 0x64         ; PROG_PAGE
    brne .Ldispatch_read_page
    rjmp command_write
.Ldispatch_read_page:  cpi  r16, 0x74         ; READ_PAGE
#if MINI_FLASH_256K
    brne .Ldispatch_read_signature
    rjmp command_read
#elif MINI_UNIVERSAL_SIGNATURE && !MINI_COMPACT_UNIVERSAL_SIGNATURE || (MINI_COMPACT_64K && MINI_UART_STYLE == 2 && MINI_COMPACT_FUSE_LOCK_READ)
    brne .Lskip_command_read_wide
    rjmp command_read
.Lskip_command_read_wide:
#else
    breq command_read
#endif
.Ldispatch_read_signature:  cpi  r16, 0x75         ; READ_SIGN
    breq command_signature
.Ldispatch_leave_program_mode:  cpi  r16, 0x51         ; LEAVE_PROGMODE
    brne command_default
    rcall wdt_16ms        ; 16ms WDT with WDE
command_default:
    rcall verify_eop       ; SYNC, ENTER, LEAVE and other no-payload cmds
command_ok:
    ldi  r16, 0x10         ; STK_OK
command_finish:
    rcall tx_char
    rjmp next_command

#if MINI_COMPACT_FUSE_LOCK_READ || (MINI_COMPACT_BANKED && MINI_FLASH_256K)
; Keep the parameter and common response near dispatch.  The AVR's conditional
; branch reaches this location without a two-word BRNE + RJMP trampoline.
command_parameter:
    rcall rx_char
    mov r20,r16
    rcall verify_eop
    ldi r16,3
    cpi r20,0x81
    brne .Lparameter_version_ready
    ldi r16,8
.Lparameter_version_ready:
universal_response:
    rcall tx_char
    rjmp command_ok
#endif

command_signature:
#if MINI_SIGROW_HARDWARE
    ldi r25,3
    clr r30                ; hardware signature index starts at 0
    rcall verify_eop
signature_row_setup:
    lsl r30                ; index -> byte address 0,2,4
    clr r31
#if MINI_COMPACT_64K || (MINI_COMPACT_BANKED && !MINI_OLD_AVRDUDE_EEPROM)
    ldi r20,0x81          ; normalized Flash=1, SIGRD selector bit7=1
#else
    ldi r20,0x80          ; normal Flash even, EEPROM odd, SIGRD bit7=1
#endif
    ldi r19,0x21          ; SIGRD|SPMEN for every LPM
    rjmp read_loop
#else
    ldi r25,3
#endif
#if MINI_SIGROW_HARDWARE
#if !(MINI_APP_SPM_512 || MINI_TINY_COMPACT) || MINI_COMPACT_SIGN_ON
    /* Signature is read from silicon, so no signature constant in the footer. */
command_signon:
    ldi r25,7
    ldi r30,((FLASH_SIZE - 9) & 0xFF)
    rjmp static_bytes
#endif
#else
#if (MINI_APP_SPM_512 || MINI_TINY_COMPACT) && !MINI_COMPACT_SIGN_ON
    ldi r30,((FLASH_SIZE - 5) & 0xFF)
#else
    ldi r30,((FLASH_SIZE - 12) & 0xFF)
    rjmp static_bytes
command_signon:
    ldi r25,7
    ldi r30,((FLASH_SIZE - 9) & 0xFF)
#endif
#endif
#if !MINI_SIGROW_HARDWARE || !(MINI_APP_SPM_512 || MINI_TINY_COMPACT) || MINI_COMPACT_SIGN_ON
static_bytes:
#if MINI_UNIVERSAL_SIGNATURE
    rcall verify_eop
static_bytes_after_eop:
#if MINI_COMPACT_64K || (MINI_COMPACT_BANKED && !MINI_OLD_AVRDUDE_EEPROM)
    ldi r20,1            ; normalized F=1, EEPROM=0
#else
    clr r20              ; select LPM branch in every iteration
#endif
    ldi r31,(((FLASH_SIZE - 1) >> 8) & 0xFF)
#else
    clr r20              ; select LPM branch in every iteration
    ldi r31,(((FLASH_SIZE - 1) >> 8) & 0xFF)
    rcall verify_eop
#endif
#if MINI_FLASH_BANKED
    ldi r16,((FLASH_SIZE - 1) >> 16)  ; footer bank = 1 for 128K, 3 for 256K
    out RAMPZ_IO,r16
#endif
    rjmp read_loop
#endif /* static data needed for footer-signature or GET_SIGN_ON */

/* UNIVERSAL: read-only ISP emulation for ATmega328P.
 * 50 00 xx yy low fuse; 50 08 xx yy ext fuse
 * 58 00 xx yy lock bits; 58 08 xx yy high fuse
 * Third/fourth ISP bytes are ignored for these read commands.
 * Strictly recognises only these four opcode pairs; other commands
 * (including 0xAC ISP writes) return 0. 0x30 signature requests are
 * implemented only when MINI_UNIVERSAL_SIGNATURE=1; the compact 512B
 * flavor omits fuse/lock LPM reads in exchange for this capability.
 * Signature is also supplied via standard STK_READ_SIGN (0x75).
 */
#if !(MINI_APP_SPM_512 || MINI_TINY_COMPACT)
command_parameter:
    rcall rx_char
    mov  r20, r16
    rcall verify_eop
    ldi  r16, 3            ; non-version parameter
    cpi  r20, 0x81         ; software major version
    brne .Lparameter_version_ready
    ldi  r16, 8
.Lparameter_version_ready:  rjmp universal_response  ; common payload byte then STK_OK
#endif

/* Shared discard for SET_PARAMETER (2), SET_DEVICE (20), SET_DEVICE_EXT (5). */
command_discard:
    rcall discard_and_verify
    rjmp command_ok


#if !MINI_R7_TAIL_FUSION
command_address:
    MINI_R7_ADDRESS_BODY
#endif

/* The high byte matters: READ_PAGE allows up to 256 bytes (0x0100).
 * 0x0000 retains legacy Optiboot's 256-byte interpretation.
 */
universal_handler:
    rcall read_length      ; first two opcode bytes
#if MINI_FLASH_256K
    ; AVRdude STK500v1 extension: 56 4D 00 <word_addr[23:16]> 00 20
    ; 256 KiB has only one extended word-address bit.  Reject other values
    ; rather than allowing wrap-around into another writable page.
    cpi r24,0x4D
    brne .Lordinary_universal
    tst r25
    brne .Lordinary_universal
    rcall rx_char
    cpi r16,2
    brlo .Lvalid_extended_word_address
    rjmp protocol_error
.Lvalid_extended_word_address:
    mov r4,r16
    rcall rx_char          ; trailing ISP byte must be zero
    tst r16
    breq .Lvalid_extended_opcode_tail
    rjmp protocol_error
.Lvalid_extended_opcode_tail:
    rcall verify_eop
    clr r16
    rjmp universal_response
.Lordinary_universal:
#endif
#if MINI_UNIVERSAL_SIGNATURE
    rcall rx_char              ; third ISP byte = signature index
    mov r30,r16                ; ZL survives both receive and EOP
    rcall rx_char              ; fourth ISP byte (don't use)
    rcall verify_eop
    clr r16                   ; unsupported ISP command -> 0
#if (MINI_APP_SPM_512 || MINI_TINY_COMPACT) && !MINI_COMPACT_FUSE_LOCK_READ
    ; Shrink the signature check to two instructions: r24==0x30, r25==0.
    ; For an unsupported opcode jump straight to the response; otherwise
    ; GET_PARAMETER immediately below would consume an extra UART byte.
    subi r24,0x30
    or r24,r25
    brne universal_response
#else
    ; Fuse-read add-on needs original r24, so do NOT use the SUBI trick.
    cpi r24,0x30
    brne .Lother_universal
    tst r25
    brne universal_response
#endif
    cpi r30,3                 ; accept only sig indices 0..2
    brsh universal_response
#if MINI_SIGROW_HARDWARE
    ldi r25,1               ; return one byte via the same silicon loop
    rjmp signature_row_setup
#else
    ; The signature moves from FLASH_END-4 to FLASH_END-11 when the
    ; seven GET_SIGN_ON characters are inserted before the 2-byte version.
    ; UNIVERSAL 30 00 <index> 00 must return the same bytes as READ_SIGN.
#if (MINI_APP_SPM_512 || MINI_TINY_COMPACT) && !MINI_COMPACT_SIGN_ON
    subi r30, 5
#else
    subi r30, 12
#endif
    ldi r25,1                 ; return exactly one signature byte
    rjmp static_bytes_after_eop
#endif
.Lother_universal:
#else
    ldi r19,2
    rcall discard_and_verify
    clr r16                   ; unsupported ISP command -> 0
#endif
#if MINI_COMPACT_UNIVERSAL_SIGNATURE && !MINI_COMPACT_FUSE_LOCK_READ
    ; Signature is serviced above; all other UNIVERSAL commands return 0.
    ; No fuse/lock reads in the compact 512-byte compatibility variant.
    ; Fall through into universal_response (r16 was already cleared).
#else
    bst  r24,3
    andi r24,0xF7
    cpi  r24,0x50
    brne universal_response
    clr  r30
    bld  r30,0
    bst  r25,3
    andi r25,0xF7
    brne universal_response
    bld  r30,1
    clr  r31
    ldi  r16,0x09         ; BLBSET|SPMEN, followed immediately by LPM
    #if MINI_SPM_EXT
    sts  SPMCSR_MEM,r16
#else
    out  SPMCSR_IO,r16
#endif
    lpm  r16,Z
#if MINI_COMPACT_FUSE_LOCK_READ
    rjmp universal_response    ; do not fall through GET_PARAMETER
#endif
#endif /* !MINI_COMPACT_UNIVERSAL_SIGNATURE */
#if (MINI_APP_SPM_512 || MINI_TINY_COMPACT) && !MINI_COMPACT_FUSE_LOCK_READ && !(MINI_COMPACT_BANKED && MINI_FLASH_256K)
command_parameter:
    rcall rx_char
    mov r20,r16
    rcall verify_eop
    ldi r16,3
    cpi r20,0x81
    brne .Lparameter_version_ready
    ldi r16,8
.Lparameter_version_ready:
    ; Fall through into universal_response instead of RJMP.
#endif
#if !MINI_COMPACT_FUSE_LOCK_READ && !(MINI_COMPACT_BANKED && MINI_FLASH_256K)
universal_response:
    rcall tx_char
    rjmp command_ok
#endif

#if MINI_R7_TAIL_FUSION
command_address:
    MINI_R7_ADDRESS_BODY
#endif

command_read:
    rcall read_length
#if MINI_COMPACT_64K || MINI_COMPACT_BANKED
    rcall validate_compact_256_length
#else
    subi r24,1           ; high length 0 accepts 0..255, 1 accepts only low=0
    brcs .Lread_length_valid              ; original high byte 0
    or   r24,r25         ; (high-1)|low must be zero for 0x0100
#if MINI_WIDE_BRANCHES
    breq .Lme64_error_skip_1
    rjmp protocol_error
.Lme64_error_skip_1:
#else
    brne protocol_error
#endif
.Lread_length_valid:
#endif
    rcall rx_char
    mov r20,r16
    rcall verify_eop
#if MINI_COMPACT_64K || (MINI_COMPACT_BANKED && !MINI_OLD_AVRDUDE_EEPROM)
    ; Shared 64K-family normalized memory selector: E=0, F=1.
    subi r20,0x45
    cpi r20,2
#if MINI_SIGROW_HARDWARE && MINI_FLASH_BANKED
    brlo .Lsigrow_valid_read_type
    rjmp read_bad_memtype
.Lsigrow_valid_read_type:
#else
    brsh read_bad_memtype
#endif
#if MINI_COMPACT_BANKED
    ; No sentinel register: memory_range_check tests normalized r20 bit 0.
#endif
#else
#if FLASH_SIZE >= 65536
    clr r18              ; sentinel: complete 64/128 KiB Flash range
#else
    ldi r18,(FLASH_SIZE >> 8)
#endif
    cpi r20,0x46         ; Flash
    breq read_check_common
    ldi r18,(EEPROM_SIZE >> 8)
    cpi r20,0x45         ; EEPROM
#if MINI_FLASH_128K
    breq .Lread_memtype_good
    rjmp read_bad_memtype
.Lread_memtype_good:
#else
    brne read_bad_memtype
#endif
#endif
#if MINI_OLD_AVRDUDE_EEPROM
    movw r26,r22           ; preserve standard word-derived address
    lsr  r23               ; old host supplied EEPROM BYTE address
    ror  r22               ; undo LOAD_ADDRESS's x2 conversion
#endif
read_check_common:
    rcall memory_range_check
#if MINI_FLASH_BANKED
    out RAMPZ_IO,r3      ; ELPM Z+ increments RAMPZ across 64-KiB boundaries
#endif
    movw r30,r22
read_loop:
#if MINI_COMPACT_64K || (MINI_COMPACT_BANKED && !MINI_OLD_AVRDUDE_EEPROM)
    sbrs r20,0           ; F=1, E=0 (normalized)
#else
    sbrc r20,0           ; E odd; F even
#endif
    rjmp read_eeprom_byte
#if MINI_SIGROW_HARDWARE && !MINI_FLASH_BANKED
    sbrc r20,7             ; silicon signature marker
    out SPMCSR_IO,r19      ; immediate predecessor of LPM, <=3 cycles
#endif
#if MINI_FLASH_BANKED
#if MINI_SIGROW_HARDWARE
    sbrs r20,7             ; signature path uses LPM, normal uses ELPM
    rjmp read_normal_flash
    out SPMCSR_IO,r19
    lpm r16,Z+
    rjmp read_after_lpm
read_normal_flash:
#endif
    elpm r16,Z+
#if MINI_SIGROW_HARDWARE
read_after_lpm:
#endif
#else
    lpm r16,Z+
#endif
#if MINI_SIGROW_HARDWARE
    sbrc r20,7
    adiw r30,1             ; LPM Z+ advanced 1; next signature byte is +2
#endif
    rjmp read_send
read_eeprom_byte:
    out EEPROM_EEARL_IO,r30
    out EEPROM_EEARH_IO,r31
    sbi EEPROM_EECR_IO,0
    in r16,EEPROM_EEDR_IO
    adiw r30,1
read_send:
    rcall tx_char
    dec r25
    brne read_loop
#if MINI_OLD_AVRDUDE_EEPROM
    sbrc r20,0            ; restore Flash/word-derived internal address only for E
    movw r22,r26
#endif
    rjmp command_ok
discard_and_verify:
.Ldiscard_next_byte:  rcall rx_char
    dec r19
    brne .Ldiscard_next_byte

verify_eop:
    rcall rx_char
    cpi  r16, 0x20         ; CRC_EOP = ' '
#if MINI_WIDE_BRANCHES
    breq .Lme64_error_skip_2
    rjmp protocol_error
.Lme64_error_skip_2:
#else
    brne protocol_error
#endif
    ldi  r16, 0x14         ; STK_INSYNC
#if MINI_R7_TAIL_FUSION
    /* TX RET is also verify_eop's RET; saves one RJMP instruction. */
    MINI_R7_TX_ROUTINE
#else
    rjmp tx_char
#endif

/* Send footer constants (silicon signature fallback / GET_SIGN_ON string).
 * Only the string remains when SIGRD supplies the signature.
 * Reuses READ_PAGE's LPM/putch loop, with EEPROM selector cleared.
 */
protocol_error:
    rcall wdt_16ms         ; 16ms watchdog
error_loop:
    rjmp error_loop



#if MINI_COMPACT_64K || MINI_COMPACT_BANKED
/* Count high-byte check, reused by Flash READ and Flash WRITE.
 * 0x0000 and 0x0100 both represent 256 bytes, as in the old protocol. */
validate_compact_256_length:
    subi r24,1
    brcs .Lcompact_len_ok
    or r24,r25
    brne protocol_error
.Lcompact_len_ok:
    ret
#endif

memory_range_check:
    movw r30, r22
    mov  r16, r25
    dec  r16
    add  r30, r16
    adc  r31, r29         ; YH is zero in every supported register profile
#if MINI_FLASH_BANKED
#if MINI_COMPACT_BANKED && !MINI_OLD_AVRDUDE_EEPROM
    ; r20 bit 0 = Flash (1) / EEPROM (0): avoid 6 bytes of r18 setup.
    ; SBRC does not alter carry set by ADC, so wrap is still detected.
    sbrc r20,0
    rjmp .Lrange_flash
    brcs .Lrange_reject
    tst r3
    brne .Lrange_reject
    cpi r31,(EEPROM_SIZE >> 8)
    brlo .Lrange_pass
#else
    ; r18=0 selects Flash, nonzero selects EEPROM. TST preserves C.
    tst r18
    breq .Lrange_flash
    brcs .Lrange_reject
    tst r3
    brne .Lrange_reject
    cp r31,r18
    brlo .Lrange_pass
#endif
.Lrange_reject:
    rjmp protocol_error
.Lrange_flash:
    brcc .Lrange_pass       ; no wrap is always valid in Flash
#if MINI_FLASH_256K
    mov r16,r3
    cpi r16,3
    breq .Lrange_reject     ; bank 3 wraps beyond 0x3FFFF
#else
    tst r3
    brne .Lrange_reject    ; bank 1 wraps beyond 0x1FFFF
#endif
.Lrange_pass:
    ret
#elif MINI_SPM_EXT && !MINI_COMPACT_64K
    brcc .Lme64_error_skip_3
    rjmp protocol_error
.Lme64_error_skip_3:
#else
    brcs protocol_error
#endif
#if MINI_COMPACT_64K
    tst r20
    brne .Lrange_ok
    cpi r31,(EEPROM_SIZE >> 8)
#else
#if FLASH_SIZE == 65536
    tst r18              ; zero sentinel skips upper bound check for full 64 KiB Flash
    breq .Lrange_ok
#endif
    cp   r31, r18
#endif
#if MINI_WIDE_BRANCHES
    brlo .Lme64_error_skip_4
    rjmp protocol_error
.Lme64_error_skip_4:
#else
    brsh protocol_error
#endif
#if FLASH_SIZE == 65536
.Lrange_ok:
#endif
    ret

command_write:
    rcall read_length
#if MINI_COMPACT_64K || MINI_COMPACT_BANKED
    ; Shared 256-byte validation covers BOTH Flash and EEPROM lengths.
    ; EEPROM still separately rejects 256 (low byte zero) and >16.
    rcall validate_compact_256_length
#else
#if FLASH_PAGE_BYTES == 256
    ; Accept 1..255 bytes or exactly 0x0100 (a whole 256-byte page).
    tst r24
    breq .Lwrite_high_zero
    cpi r24,1
#if MINI_WIDE_BRANCHES
    breq .Lme64_error_skip_5
    rjmp protocol_error
.Lme64_error_skip_5:
#else
    brne protocol_error
#endif
    tst r25
#if MINI_WIDE_BRANCHES
    breq .Lme64_error_skip_6
    rjmp protocol_error
.Lme64_error_skip_6:
#else
    brne protocol_error
#endif
    rjmp .Lwrite_length_ok
.Lwrite_high_zero:
    tst r25
#if MINI_WIDE_BRANCHES
    brne .Lme64_error_skip_7
    rjmp protocol_error
.Lme64_error_skip_7:
#else
    breq protocol_error
#endif
.Lwrite_length_ok:
#else
    tst r24
#if MINI_WIDE_BRANCHES
    breq .Lme64_error_skip_8
    rjmp protocol_error
.Lme64_error_skip_8:
#else
    brne protocol_error
#endif
    tst r25
#if MINI_WIDE_BRANCHES
    brne .Lme64_error_skip_9
    rjmp protocol_error
.Lme64_error_skip_9:
#else
    breq protocol_error
#endif
#endif
#endif
    rcall rx_char          ; memory type, accept all except 'E'
#if MINI_COMPACT_64K
    clr r20                ; EEPROM writes pass normalized E=0 selector
#endif
    cpi  r16, 0x45        ; EEPROM write: stage on stack, validate EOP
    breq eeprom_write
    cpi r16,0x46           ; accept only F otherwise
    breq flash_write
    ; Invalid memtype: drain this payload, acknowledge framing, return FAILED.
    ; This cannot modify flash/EEPROM and does not de-sync a proper host.
    mov r19,r25
    rcall discard_and_verify
read_bad_memtype:
    ldi r16,0x11         ; INSYNC was already sent, report STK_FAILED
    rjmp command_finish
flash_write:
#if MINI_FLASH_ERASE_GROUP_BYTES > FLASH_PAGE_BYTES
    ; Both ATtiny841 and ATtiny1634 erase a 4-PAGE GROUP, not an
    ; individual page. Tiny841: 4*16=64 bytes; Tiny1634: 4*32=128.
    ; Receive ALL four pages into SRAM, check CRC_EOP BEFORE erase, then
    ; erase once and write the four physical pages individually.
    ; Special host is needed; stock AVRDUDE sends physical pages instead.
#if !MINI_TINY_COMPACT
    ; The normal (larger) profile keeps a second guard here. Compact Tiny
    ; already checked this byte in command_write, so a repeat is redundant.
    tst r24
    breq .Ltiny_high_ok
    rjmp protocol_error
.Ltiny_high_ok:
#endif
    cpi r25,(4 * FLASH_PAGE_BYTES)
    breq .Ltiny_length_ok
    rjmp protocol_error
.Ltiny_length_ok:
    mov r16,r22
    andi r16,((4 * FLASH_PAGE_BYTES) - 1) ; group-aligned
    breq .Ltiny_align_ok
    rjmp protocol_error
.Ltiny_align_ok:
#if (BOOT_START & 0xFF) != 0
    ; For a non-256B-aligned virtual Boot, checking ZH alone would reject
    ; valid application groups in the same 256B window as BOOT_START.
    cpi r23,(BOOT_START >> 8)
    brlo .Ltiny_boot_safe
    brne .Ltiny_boot_reject
    cpi r22,(BOOT_START & 0xFF)
    brlo .Ltiny_boot_safe
.Ltiny_boot_reject:
    rjmp protocol_error
#else
    cpi r23,(BOOT_START >> 8)
    brlo .Ltiny_boot_safe
    rjmp protocol_error
#endif
.Ltiny_boot_safe:
    ldi r19,(4 * FLASH_PAGE_BYTES)
.Ltiny_receive_group:
    rcall rx_char
    push r16                 ; 64/128 bytes on normal SRAM stack
    dec r19
    brne .Ltiny_receive_group
    rcall verify_eop          ; malformed packet never erases Flash
    movw r30,r22
    ldi r16,3                ; erase all four pages once
    rcall spm_execute_wait  ; preserves Z; no need for another MOVW
    ; Z += complete erase group. SUBI/SBCI save one instruction pair
    ; compared to LDI/ADD/ADC, including the carry into ZH.
    subi r30,(256 - 4 * FLASH_PAGE_BYTES)
    sbci r31,0xFF
    ldi r20,4                ; pages remaining
.Ltiny_next_page:
    ldi r25,(FLASH_PAGE_BYTES / 2) ; 8/16 words per physical page
.Ltiny_next_word:
    sbiw r30,2
    pop r1                   ; reverse staging: high byte first
    pop r0
    ldi r16,1
    out SPMCSR_IO,r16
    spm
    dec r25
    brne .Ltiny_next_word
    ldi r16,5
    rcall spm_execute_wait   ; writes this 32-byte page, clears temp buffer
    dec r20
    brne .Ltiny_next_page
    rjmp command_ok
#else
#if MINI_COMPACT_64K || MINI_COMPACT_BANKED
    ; 8-bit byte count: 0 represents exactly 256 bytes.  Count down by 2,
    ; avoiding the 128-word conversion and the separate 256-byte path.
    sbrc r25,0
    rjmp protocol_error
#else
#if FLASH_PAGE_BYTES == 256
    tst r24
    breq .Lflash_short_page
    ldi r25, 128
    rjmp .Lflash_length_ready
.Lflash_short_page:
#endif
    lsr r25                ; convert even bytes to words
#if MINI_WIDE_BRANCHES
    brcc .Lme64_error_skip_10
    rjmp protocol_error
.Lme64_error_skip_10:
#else
    brcs protocol_error
#endif
    cpi r25, ((FLASH_PAGE_BYTES / 2) + 1)
#if MINI_WIDE_BRANCHES
    brlo .Lme64_error_skip_11
    rjmp protocol_error
.Lme64_error_skip_11:
#else
    brsh protocol_error
#endif
#if FLASH_PAGE_BYTES == 256
.Lflash_length_ready:
#endif
#endif
    ; Datasheet 26.8.3: Page Write requires PCWORD=0 in Z.
    ; Reject a non-page-aligned start, preventing SPM address misuse
    ; and a payload spanning two different physical flash pages.
#if MINI_COMPACT_64K || MINI_COMPACT_BANKED
    tst r22                 ; 256-byte page alignment
#else
    mov  r16, r22
    andi r16, (FLASH_PAGE_BYTES - 1)  ; page-aligned address
#endif
#if MINI_WIDE_BRANCHES
    breq .Lme64_error_skip_12
    rjmp protocol_error
.Lme64_error_skip_12:
#else
    brne protocol_error
#endif
    movw r30, r22
#if MINI_FLASH_BANKED
    out RAMPZ_IO,r3      ; required for SPM temporary-buffer fill / erase / write
#endif
#if MINI_APP_SPM_512 && !MINI_FLASH_BANKED
    ldi  r24, 0x01         ; SPMEN for shared SPM/wait routine
#else
    ldi  r19, 0x01         ; preloaded SPMEN across whole page (saves cycles)
#endif

/* Fill the target AVR's hardware temporary page buffer BEFORE flash erase.
 * Atmel datasheet 30.8 explicitly allows SPM fill -> page erase -> write.
 * A bad CRC_EOP cannot destroy old Flash: no page erase has happened.
 * Unlike the SRAM version this uses no 128-byte software buffer.
 */
hardware_fill_loop:
    rcall rx_char
    mov  r0, r16
    rcall rx_char
    mov  r1, r16
#if MINI_APP_SPM_512 && !MINI_FLASH_BANKED
    ; Call the existing SPM+busy-wait instead of inlining OUT+SPM.
    ; rx_char leaves r24 unchanged; r24=1 is invariant in this fill loop.
    rcall spm_execute_wait
#else
    #if MINI_SPM_EXT
    sts SPMCSR_MEM,r19
#else
    out SPMCSR_IO,r19
#endif
    spm
#endif
    adiw r30, 2
#if MINI_COMPACT_64K || MINI_COMPACT_BANKED
    subi r25,2
#else
    dec  r25
#endif
    brne hardware_fill_loop
    ; r1 now contains the last Flash word high byte. No later code
    ; uses r1 as its zero register; r29 (YH) remains zero permanently.
    rcall verify_eop      ; STK_INSYNC must precede actual erase
#if MINI_FLASH_BANKED
    ; Reject only the last physical Flash bank above BOOT_START.
    ; Other banks and addresses below BOOT_START are writable.
#if MINI_FLASH_256K
    mov r16,r3
    cpi r16,3
    brne .Lboot_target_safe
#else
    tst r3
    breq .Lboot_target_safe
#endif
    cpi r23, ((BOOT_START >> 8) & 0xFF)
    brlo .Lboot_target_safe
    rjmp protocol_error
.Lboot_target_safe:
#else
#if MINI_VIRTUAL_BOOT && (BOOT_START & 0xFF) != 0
    ; Compare the low byte too: the last writable page might share the
    ; high address byte with the first Virtual Boot page (e.g. 0x1DC0).
    cpi r23, (BOOT_START >> 8)
    brlo .Lvirtual_write_safe
    brne .Lvirtual_write_reject
    cpi r22, (BOOT_START & 0xFF)
    brlo .Lvirtual_write_safe
.Lvirtual_write_reject:
    rjmp protocol_error
.Lvirtual_write_safe:
#else
    cpi  r23, (BOOT_START >> 8) ; reject addresses within boot section
#if MINI_WIDE_BRANCHES
    brlo .Lme64_error_skip_13
    rjmp protocol_error
.Lme64_error_skip_13:
#else
    brsh protocol_error
#endif
#endif
#endif

    movw r30, r22
#if MINI_APP_SPM_512
    ldi  r24, 0x03
    rcall spm_execute_wait
    ldi  r24, 0x05
    rcall spm_execute_wait
    ldi  r24, 0x11
    rcall spm_execute_wait
#else
    ldi  r16, 0x03        ; erase, hardware temp page buffer retained!
    rcall spm_execute_wait
    ldi  r16, 0x05        ; write temporary page buffer to Flash
    rcall spm_execute_wait
    ldi  r16, 0x11        ; RWWSRE|SPMEN
    rcall spm_execute_wait
#endif
    rjmp command_ok
#endif /* MINI_FLASH_ERASE_GROUP_BYTES > FLASH_PAGE_BYTES */

/* EEPROM write: push 1..16 received bytes onto normal AVR hardware stack.
 * avrdude -c arduino sends EEPROM data in 16-byte blocks for ATmega328P.
 * CRC_EOP is validated BEFORE any EEPROM writes. Then POP bytes in LIFO
 * order and program addresses from the block's end down to its start.
 * Incomplete or incorrect packets do not modify EEPROM; sudden power loss
 * during commit can still leave a partially written EEPROM block.
 * No dedicated 16-byte array in SRAM; peak stack usage increases by 16B.
 * Valid EEPROM address range 0x000..0x3FF (inclusive) is enforced.
 */
eeprom_write:
#if MINI_COMPACT_BANKED || (FLASH_PAGE_BYTES == 256 && MINI_WIDE_BRANCHES && !MINI_COMPACT_64K)
    ; Valid 256-page write lengths are 1..255 or precisely 0x0100.
    ; A low byte of zero therefore cannot be a legal EEPROM block.  The
    ; single biased comparison covers both 0 and 17..256. Restore r25
    ; before the stack-staging/commit loops; the error path never commits.
    subi r25,1
    cpi r25,16
    brlo .Leeprom_short_valid
    rjmp protocol_error
.Leeprom_short_valid:
    inc r25
#elif MINI_COMPACT_64K
    tst r25               ; EEPROM length 0 or 256 is invalid
    breq protocol_error
    cpi r25,17            ; 1..16 byte EEPROM blocks only
    brsh protocol_error
#else
#if FLASH_PAGE_BYTES == 256
    tst r24               ; EEPROM blocks never use the 256-byte form
#if MINI_WIDE_BRANCHES
    breq .Lme64_error_skip_14
    rjmp protocol_error
.Lme64_error_skip_14:
#else
    brne protocol_error
#endif
#endif
    cpi r25,17
#if MINI_WIDE_BRANCHES || MINI_TINY_COMPACT
    brlo .Lme64_error_skip_15
    rjmp protocol_error
.Lme64_error_skip_15:
#else
    brsh protocol_error
#endif
#endif
#if MINI_OLD_AVRDUDE_EEPROM
    movw r26,r22          ; save word-derived address for subsequent commands
    lsr  r23              ; reconstruct host's EEPROM byte address
    ror  r22
#endif
#if MINI_COMPACT_BANKED && !MINI_OLD_AVRDUDE_EEPROM
    clr r20                 ; EEPROM 0 in normalized banked flag
#elif !MINI_COMPACT_64K
    ldi r18,(EEPROM_SIZE >> 8)
#endif
    rcall memory_range_check
    mov  r19, r25         ; keep commit count; use r19 for input loop
.Leeprom_receive_next:  rcall rx_char
    push r16              ; stage byte in stack, no dedicated 16-byte SRAM array
    dec  r19
    brne .Leeprom_receive_next
    rcall verify_eop      ; validate packet before modifying any EEPROM
/* Z = last EEPROM byte, retained from eeprom_range_check.
 * Pop bytes in reverse order, write from end of block backwards.
 * RCALL/RET in receiver leave the staged bytes untouched.
 */
#if !MINI_APP_SPM_512
    rcall wait_spm        ; ensure Flash self-programming has finished
#else
    ; SPM512 size optimization: all Flash erase/write/RWW entrypoints already
    ; finish via spm_execute_wait before accepting any next STK500 command.
    ; App-callable do_spm also awaits SPM completion before RET. In this
    ; serial command path, no SPM instruction can remain in flight here.
#endif
    ; At each command entry we already wait until EEPE clears. There is
    ; no other EEPROM writer (interrupts disabled), so the first write
    ; starts with EEPE clear. Wait AFTER each write, including the last.
.Leeprom_commit_next:  out EEPROM_EECR_IO,r29        ; EECR=0: YH=0 after USART init
    out EEPROM_EEARL_IO,r30        ; EEARL
    out EEPROM_EEARH_IO,r31        ; EEARH
    pop  r16
    out EEPROM_EEDR_IO,r16        ; EEDR
    sbi EEPROM_EECR_IO,2          ; EEMPE, 4 CPU cycles to trigger EEPE
    sbi EEPROM_EECR_IO,1          ; EEPE, start 3.4ms atomic erase/write
    sbiw r30,1
    dec  r25             ; Z flag is retained by SBIC/RJMP
.Leeprom_wait_write_complete:  sbic EEPROM_EECR_IO,1          ; every write complete before next/ACK
    rjmp .Leeprom_wait_write_complete
    brne .Leeprom_commit_next
#if MINI_OLD_AVRDUDE_EEPROM
    movw r22,r26          ; restore standard internal address for next command
#endif
    rjmp command_ok


/* Shared discard and EOP verification: SET, invalid memory and UNIVERSAL. */

read_length:
    rcall rx_char          ; high length byte
    mov  r24, r16
    rcall rx_char          ; low length byte
    mov  r25, r16
    ret

rx_char:
rx_wait:
#if MINI_SOFT_UART
    ; Put the receive routine at the public entry: no extra RCALL/RET/RJMP.
    MINI_UART_SOFT_RX_ROUTINE
#else
    MINI_UART_RX_POLL
    MINI_UART_RECEIVE
    ret
#endif

#if !MINI_R7_TAIL_FUSION
    MINI_R7_TX_ROUTINE
#endif

wdt_16ms:
    ldi  r17, 0x08
wdt_config:
    ; Temporarily repoint Y from USART0 (0xC0) to WDTCSR (0x60).
    ; STD is one word, unlike two-word STS, with the same 2-cycle execution.
    ; Both WDT writes remain adjacent, within the 4-cycle unlock window.
    ; Restore Y before returning, including the initial call before UART setup.
#if MINI_UART_STYLE == 0
    ldi  r28, 0x60
    ldi  r18, 0x18
    std  Y+0, r18
    std  Y+0, r17
    ldi  r28, 0xC0
#elif MINI_WDT_CCP_STYLE
    ; ATtiny841/1634 use protected I/O write via CCP (0xD8), NOT WDCE.
    ; tiny841 CCP is extended-memory 0x71, tiny1634 CCP is I/O 0x2F.
    ; The following OUT to WDTCSR occurs within 4 instruction cycles.
    ldi r18,0xD8
#if MINI_WDT_CCP_STYLE == 1
    sts MINI_WDT_CCP_ADDR,r18
#else
    out MINI_WDT_CCP_ADDR,r18
#endif
    out WDT_IO,r17
    ldi r18,0x18             ; needed for RXEN|TXEN by MINI_UART_INIT
#else
    ldi r18,0x18
    out WDT_IO,r18
    out WDT_IO,r17
#endif
    ret

spm_execute_wait:
#if MINI_APP_SPM_512 && MINI_SPM_EXT
    sts SPMCSR_MEM,r24
#elif MINI_APP_SPM_512
    out SPMCSR_IO,r24
#elif MINI_SPM_EXT
    sts SPMCSR_MEM,r16
#else
    out SPMCSR_IO,r16
#endif
    spm
wait_spm:
#if MINI_SPM_EXT
    lds r18, SPMCSR_MEM
#else
    in r18, SPMCSR_IO
#endif
    sbrc r18, 0
    rjmp wait_spm
    ret

/* EEPROM address is 0..1023.  r25=0 means 256 bytes for READ_PAGE,
 * just as in the historical Optiboot read loop.  Test the inclusive
 * end address = start + (length - 1) to avoid wraparound/wrong writes.
 * r18=top address high-byte limit (zero sentinel for 64 KiB); clobbers r16, Z, flags.
 */




/* Application-callable SPM, ABI-compatible with official Optiboot 8.x:
 * byte address BOOT_START+2, void do_spm(uint16_t addr, uint8_t cmd, uint16_t data).
 * Incoming avr-gcc registers: addr=r25:r24, cmd=r22, data=r21:r20.
 * r0,r1 and r18..r27,Z are caller-clobbered; all callee-saved registers
 * (r2..r17, r28:r29) remain intact. r1 is reset to zero before RET.
 *
 * This deliberately adds a safety guard not present in upstream do_spm:
 * - allow only page-buffer fill 0x01, erase 0x03, write 0x05,
 *   RWW re-enable 0x11 and lock-bit programming 0x09;
 * - reject out-of-range banks and any write/erase/fill into the boot area.
 * - wait for pending EEPROM and SPM operations;
 * - disable interrupts during the operation and restore caller's SREG;
 * - on erase/write, if data==0, re-enable RWW before returning.
 * For 128/256KiB flash the application supplies RAMPZ with the upper
 * BYTE-address bits, as for upstream Optiboot. RAMPZ is left unchanged.
 *
 * No automatic page staging/verification: caller must perform complete
 * page operations in the proper order and protect its own application data.
 */
#if MINI_APP_SPM
.global optiboot_mini_do_spm
optiboot_mini_do_spm = _start + 2
#if !MINI_APP_SPM_512
app_spm_service:
    in   r19,0x3F             ; caller SREG (including interrupt-enable)
    cli
    push r19                ; restore SREG before return
    ; ATmega SPM service has RWW and BLBSET operations. On ATtiny there is
    ; no service (the application executes SPM directly).
    cpi  r22,0x11            ; RWWSRE|SPMEN, independent of Z
    breq .Lspm_preflight
    cpi  r22,0x09            ; BLBSET|SPMEN, lock-bit programming
    breq .Lspm_preflight
    cpi  r22,0x01            ; temporary page buffer fill
    breq .Lspm_address_check
    cpi  r22,0x03            ; page erase
    breq .Lspm_address_check
    cpi  r22,0x05            ; page write
    brne .Lspm_return
.Lspm_address_check:
#if MINI_FLASH_BANKED
    in   r18,RAMPZ_IO
    cpi  r18,((BOOT_START >> 16) & 0xFF)
    brlo .Lspm_address_safe
    brne .Lspm_return      ; outside the actual Flash banks
#endif
    ; BOOT_START is page-aligned, so a byte address comparison suffices.
    cpi  r25,((BOOT_START >> 8) & 0xFF)
    brsh .Lspm_return      ; do not permit self-erase/self-write
.Lspm_address_safe:
.Lspm_preflight:
    ; Check that previous EEPROM / SPM work has settled.
.Lspm_ee_wait:
    sbic EEPROM_EECR_IO,1
    rjmp .Lspm_ee_wait
    rcall wait_spm
    movw r30,r24             ; Z = page/word byte address
    movw r0,r20              ; SPM data word
.Lspm_execute:
    ; Fast SPM operation: SPMCSR is written immediately before SPM.
    ; Both OUT and STS variants satisfy the four-cycle enable window.
#if MINI_SPM_EXT
    sts  SPMCSR_MEM,r22
#else
    out  SPMCSR_IO,r22
#endif
    spm
    clr  r1                  ; avr-gcc zero register convention
    rcall wait_spm
    ; Match upstream Optiboot 8.3's RWW behavior for erase/write with data=0.
    cpi  r22,0x03
    breq .Lspm_maybe_rww
    cpi  r22,0x05
    brne .Lspm_return
.Lspm_maybe_rww:
    mov  r18,r20
    or   r18,r21
    brne .Lspm_return
    ldi  r18,0x11
#if MINI_SPM_EXT
    sts  SPMCSR_MEM,r18
#else
    out  SPMCSR_IO,r18
#endif
    spm
    rcall wait_spm
.Lspm_return:
    pop  r19
    out  0x3F,r19           ; restore caller I flag, status bits
    ret
#endif /* !MINI_APP_SPM_512 */
#endif /* MINI_APP_SPM */

/* The boot section, signature and optional GET_SIGN_ON footer are device-relative.
 * BOOTSZ and BOOTRST fuses must match the emitted image.
 */
.global _code_end
_code_end:
#if MINI_SIGROW_HARDWARE
#if (MINI_APP_SPM_512 || MINI_TINY_COMPACT) && !MINI_COMPACT_SIGN_ON
.fill ((BOOT_BYTES - 2) - (. - _start)),1,0xFF
.byte 3,8
#else
.fill ((BOOT_BYTES - 9) - (. - _start)),1,0xFF
.ascii "AVR STK"
.byte 3,8
#endif
#else
#if (MINI_APP_SPM_512 || MINI_TINY_COMPACT) && !MINI_COMPACT_SIGN_ON
.fill ((BOOT_BYTES - 5) - (. - _start)),1,0xFF
.byte SIG0,SIG1,SIG2
.byte 3,8
#else
.fill ((BOOT_BYTES - 12) - (. - _start)),1,0xFF
.byte SIG0,SIG1,SIG2
.ascii "AVR STK"
.byte 3, 8
#endif
#endif
boot_end:

#endif /* MINI_FLASH_ONLY_256 */
