/* Select UART hardware access at compile time from the device profile. */
#if MINI_UART_STYLE == 0
#include "modern.inc"
#elif MINI_UART_STYLE == 1
#include "legacy.inc"
#elif MINI_UART_STYLE == 2
#include "mega64.inc"
#else
#error Unsupported USART hardware profile
#endif
