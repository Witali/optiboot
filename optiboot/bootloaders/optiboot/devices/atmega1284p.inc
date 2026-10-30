/* Hardware configuration for atmega1284p. Generated; see gen_devices.py. */
#define FLASH_SIZE 131072
#define EEPROM_SIZE 4096
#define FLASH_PAGE_BYTES 256
#define SIG0 0x1e
#define SIG1 0x97
#define SIG2 0x5
#define SRAM_END 0x40ff
#define MINI_UART_STYLE 0
#define MINI_LEGACY_STACK 1
#define MINI_SPM_EXT 1
#define SPMCSR_IO 0x37
#define SPMCSR_MEM 0x57
#define WDT_IO 0x21
#define EEPROM_EECR_IO 0x1f
#define EEPROM_EEDR_IO 0x20
#define EEPROM_EEARL_IO 0x21
#define EEPROM_EEARH_IO 0x22
#define RAMPZ_IO 0x3b
#define MINI_FLASH_128K 1
#ifndef BOOT_BYTES
#define BOOT_BYTES 1024
#endif
#define BOOT_START (FLASH_SIZE - BOOT_BYTES)
