/* ATtiny841 USART0 memory-mapped at 0x80..0x86.
 * YL (r28) is the fixed 0x80 USART base, YH (r29) remains zero.
 * STD/LDD encode in 2 bytes instead of the 4-byte STS/LDS pairs,
 * while preserving the 2-cycle I/O access needed by UART timing.
 * No other compact-tiny path modifies r28. */
.macro MINI_UART_INIT
    ldi r28,0x80
    ldi r16,(MINI_U2X << 1)
    std Y+6,r16       ; UCSR0A
    std Y+5,r18       ; UCSR0B (RXEN0|TXEN0)
    ldi r16,0x06
    std Y+4,r16       ; UCSR0C 8N1
    ldi r16,(MINI_UBRR & 0xFF)
    std Y+1,r16       ; UBRR0L
#if MINI_UBRR < 256
    std Y+2,r29       ; UBRR0H=0
#else
    ldi r16,((MINI_UBRR >> 8) & 15)
    std Y+2,r16
#endif
.endm
.macro MINI_UART_RX_POLL
    ldd r18,Y+6
    sbrs r18,7
    rjmp rx_wait
    sbrs r18,4
    wdr
.endm
.macro MINI_UART_TX_POLL
    ldd r18,Y+6
    sbrs r18,5
    rjmp tx_wait
.endm
.macro MINI_UART_RECEIVE
    ld r16,Y
.endm
.macro MINI_UART_TRANSMIT
    st Y,r16
.endm
