/* Software UART 8N1, no timer/interrupt use. ATtiny84: PA1 TX PA2 RX;
 * ATtiny85: PB0 TX PB1 RX. RX idle=1, start=0, LSB first, stop=1.
 *
 * Timing assumes F_CPU is the ACTUAL CPU frequency (CLKDIV8 disabled
 * when 8 MHz RC is selected). Bit time is rounded to nearest cycle.
 * WDR must not run in the idle RX polling loop, so silence times out.
 * Registers r6 (shift) and r18 (delay) dedicated to software UART;
 * r16 provides transmit/receive value. No interrupts (boot starts with CLI).
 * Timing diagrams/tests are in mini_tests/test_soft_uart.py.
 * Based on original code; license GPL-2.0-or-later.
 */
#define SOFT_BIT_CYCLES ((F_CPU + BAUD_RATE / 2) / BAUD_RATE)
#if SOFT_BIT_CYCLES < 100 || SOFT_BIT_CYCLES > 750
#error Unsupported software UART baud/F_CPU: need 100..750 CPU cycles per bit
#endif
/* Shared timing loop: LDI 1, RCALL 3, DEC/BRNE = 3*N-1,
 * RET 4 => 3*N+7 cycles in total. Moving LDI to each call site
 * preserves cycle-accurate receive and transmit delay.
 * Rx start sample: choose 3*N+9 approximately half-bit.
 * Rx data: choose 3*N+12 per bit (sampling and loop overhead).
 * TX between pin edges: 3*N+13..15 cycles including branches.
 */
#define SOFT_HALF_N ((SOFT_BIT_CYCLES / 2 - 9 + 1) / 3)
#define SOFT_RX_N ((SOFT_BIT_CYCLES - 12 + 1) / 3)
#define SOFT_TX_N ((SOFT_BIT_CYCLES - 14 + 1) / 3)
#define SOFT_TX_START_N ((SOFT_BIT_CYCLES - 10 + 1) / 3)
#if SOFT_HALF_N < 1 || SOFT_HALF_N > 255 || SOFT_RX_N < 1 || SOFT_RX_N > 255 || SOFT_TX_N < 1 || SOFT_TX_N > 255
#error Software UART delay-counter overflow
#endif

.macro MINI_UART_INIT
    ; Set output latch high BEFORE switching DDR to output: no false start.
    sbi SOFT_PORT_IO,SOFT_TX_BIT
    cbi SOFT_DDR_IO,SOFT_RX_BIT
    sbi SOFT_PORT_IO,SOFT_RX_BIT  ; optional pullup for idle RX
    sbi SOFT_DDR_IO,SOFT_TX_BIT
.endm
.macro MINI_UART_RX_POLL
.endm
.macro MINI_UART_RECEIVE
    rcall soft_uart_rx
.endm
.macro MINI_UART_TX_POLL
.endm
.macro MINI_UART_TRANSMIT
    rcall soft_uart_tx
.endm

.macro MINI_UART_SOFT_RX_ROUTINE
/* UART receive, blocking. Verifies start at 0.5 bit and stop at 9.5.
 * WDR is fed once on entry; while idle RX waits, WDT expires as intended.
 * Malformed stop bit is discarded; missing framing will cause watchdog
 * expiration if no complete valid packet subsequently arrives.
 */
soft_uart_rx:
    ; Feed WDT once per byte, BEFORE the idle wait. Do not feed inside
    ; the wait loop: otherwise an idle ATtiny never boots the application.
    wdr
.Lsoft_rx_wait_start:
    sbic SOFT_PIN_IO, SOFT_RX_BIT
    rjmp .Lsoft_rx_wait_start
    ldi r18, SOFT_HALF_N
    rcall .Lsoft_delay
    sbic SOFT_PIN_IO, SOFT_RX_BIT
    rjmp .Lsoft_rx_wait_start    ; glitch: line high at mid-start
    ldi r18, SOFT_RX_N
    rcall .Lsoft_delay
    ldi r16, 8
    clr r6
.Lsoft_rx_data:
    clc
    sbic SOFT_PIN_IO, SOFT_RX_BIT
    sec
    ror r6
    ldi r18, SOFT_RX_N
    rcall .Lsoft_delay
    dec r16
    brne .Lsoft_rx_data
    sbis SOFT_PIN_IO, SOFT_RX_BIT
    rjmp .Lsoft_rx_wait_start    ; framing error: discard incomplete byte
    mov r16,r6
    ret

.endm

.macro MINI_UART_SOFT_TX_ROUTINE
/* Transmit: no interrupts, 1 start + 8 data + 1 stop, LSB first.
 * Branch-balanced pin action (set/clear paths both five cycles), so
 * baud is almost independent of the bit pattern.
 */
soft_uart_tx:
    mov r6,r16
    ldi r16,8
    cbi SOFT_PORT_IO,SOFT_TX_BIT
    ldi r18, SOFT_TX_START_N
    rcall .Lsoft_delay
.Lsoft_tx_data:
    sbrc r6,0
    sbi SOFT_PORT_IO,SOFT_TX_BIT
    sbrs r6,0
    cbi SOFT_PORT_IO,SOFT_TX_BIT
    lsr r6
    ldi r18, SOFT_TX_N
    rcall .Lsoft_delay
    dec r16
    brne .Lsoft_tx_data
    sbi SOFT_PORT_IO,SOFT_TX_BIT
    ldi r18, SOFT_TX_N
    rjmp .Lsoft_delay      ; tail-return via delay's RET, no extra stack frame
.Lsoft_delay:
    dec r18
    brne .Lsoft_delay
    ret
.endm
