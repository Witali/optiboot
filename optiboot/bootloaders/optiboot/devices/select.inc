/* Device selection follows the compiler -mmcu option. */
#if defined(__AVR_ATmega328P__)
#include "atmega328p.inc"
#elif defined(__AVR_ATmega328__)
#include "atmega328.inc"
#elif defined(__AVR_ATmega328PB__)
#include "atmega328pb.inc"
#elif defined(__AVR_ATmega168P__)
#include "atmega168p.inc"
#elif defined(__AVR_ATmega168__)
#include "atmega168.inc"
#elif defined(__AVR_ATmega88P__)
#include "atmega88p.inc"
#elif defined(__AVR_ATmega88__)
#include "atmega88.inc"
#elif defined(__AVR_ATmega324PA__)
#include "atmega324pa.inc"
#elif defined(__AVR_ATmega164PA__)
#include "atmega164pa.inc"
#elif defined(__AVR_ATmega16__)
#include "atmega16.inc"
#elif defined(__AVR_ATmega32A__)
#include "atmega32a.inc"
#elif defined(__AVR_ATmega64A__)
#include "atmega64a.inc"
#elif defined(__AVR_ATmega128A__)
#include "atmega128a.inc"
#elif defined(__AVR_ATmega1284__)
#include "atmega1284.inc"
#elif defined(__AVR_ATmega1284P__)
#include "atmega1284p.inc"
#else
#error Unsupported MCU: select an ATmega profile defined in devices/
#endif
