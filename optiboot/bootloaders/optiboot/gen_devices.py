from pathlib import Path
P=Path(__file__).parent/'devices'
# Chip, flash bytes, EEPROM bytes, page bytes, signature, max rated MHz, register profile, SRAMEND.
devices = [
 ('atmega328p',32768,1024,128,(0x1e,0x95,0x0f),20,'modern',0x8FF),
 ('atmega328',32768,1024,128,(0x1e,0x95,0x14),20,'modern',0x8FF),
 ('atmega328pb',32768,1024,128,(0x1e,0x95,0x16),20,'modern',0x8FF),
 ('atmega168p',16384,512,128,(0x1e,0x94,0x0b),20,'modern',0x4FF),
 ('atmega168',16384,512,128,(0x1e,0x94,0x06),20,'modern',0x4FF),
 ('atmega88p',8192,512,64,(0x1e,0x93,0x0f),20,'modern',0x4FF),
 ('atmega88',8192,512,64,(0x1e,0x93,0x0a),20,'modern',0x4FF),
 ('atmega324pa',32768,1024,128,(0x1e,0x95,0x11),20,'modern',0x8FF),
 ('atmega164pa',16384,512,128,(0x1e,0x94,0x0a),20,'modern',0x4FF),
 ('atmega16',16384,512,128,(0x1e,0x94,0x03),16,'legacy',0x45F),
 ('atmega32a',32768,1024,128,(0x1e,0x95,0x02),16,'legacy',0x85F),
 ('atmega64a',65536,2048,256,(0x1e,0x96,0x02),16,'mega64',0x10FF),
 ('atmega128a',131072,4096,256,(0x1e,0x97,0x02),16,'mega128',0x10FF),
 ('atmega1284',131072,4096,256,(0x1e,0x97,0x06),20,'modern128',0x40FF),
 ('atmega1284p',131072,4096,256,(0x1e,0x97,0x05),20,'modern128',0x40FF),
]
import json
jsonout={}
for name,flash,eeprom,page,sig,maxmhz,profile,ramend in devices:
    vals={'FLASH_SIZE':flash, 'EEPROM_SIZE':eeprom,'FLASH_PAGE_BYTES':page, 'SIG0':sig[0],'SIG1':sig[1],'SIG2':sig[2],'SRAM_END':ramend,
        'MINI_UART_STYLE':{'modern':0,'legacy':1,'mega64':2,'mega128':2,'modern128':0}[profile], 'MINI_LEGACY_STACK':int(profile!='modern'), 'MINI_SPM_EXT':int(profile in ('mega64','mega128','modern128')),
        'SPMCSR_IO':0x37,'SPMCSR_MEM':0x68 if profile in ('mega64','mega128') else 0x57, 'WDT_IO':0x21,
        'EEPROM_EECR_IO':0x1F if profile in ('modern','modern128') else 0x1C,
        'EEPROM_EEDR_IO':0x20 if profile in ('modern','modern128') else 0x1D,
        'EEPROM_EEARL_IO':0x21 if profile in ('modern','modern128') else 0x1E,
        'EEPROM_EEARH_IO':0x22 if profile in ('modern','modern128') else 0x1F}
    if profile in ('legacy','mega64','mega128'): vals.update({'UART_A_IO':0x0B,'UART_B_IO':0x0A,'UART_DATA_IO':0x0C,'UART_L_IO':0x09})
    if flash>65536: vals.update({'RAMPZ_IO':0x3B, 'MINI_FLASH_128K':1})
    else: vals.update({'MINI_FLASH_128K':0})
    if profile == 'legacy': vals.update({'UART_C_IO':0x20,'UART_H_IO':0x20})
    elif profile in ('mega64','mega128'): vals.update({'UART_C_MEM':0x95,'UART_H_MEM':0x90})
    body=['/* Hardware configuration for %s. Generated; see gen_devices.py. */'%name]
    body += [f'#define {k} {hex(v) if k.startswith("SIG") or k.endswith("_IO") or k.endswith("_MEM") or k=="SRAM_END" else v}' for k,v in vals.items()]
    body += ['#ifndef BOOT_BYTES', '#define BOOT_BYTES 1024' if name in ('atmega64a','atmega128a','atmega1284','atmega1284p') else '#define BOOT_BYTES 512','#endif', '#define BOOT_START (FLASH_SIZE - BOOT_BYTES)','']
    (P/(name+'.inc')).write_text('\n'.join(body))
    jsonout[name]={'flash':flash,'eeprom':eeprom,'page':page,'sig':list(sig),'max_mhz':maxmhz,'profile':profile,'ramend':ramend,'default_boot':1024 if name in ('atmega64a','atmega128a','atmega1284','atmega1284p') else 512}
selectors=['/* Device selection follows the compiler -mmcu option. */']
for i,(name,*_) in enumerate(devices):
    avrmacro = '__AVR_ATmega'+name[len('atmega'):].upper()+'__'
    # Actual compiler macros mixed case e.g __AVR_ATmega328P__, __AVR_ATmega64A__
    part = name[len('atmega'):]
    macro='__AVR_ATmega'+part.upper()+'__' if part[0].isdigit() else '__AVR_ATmega'+part+'__'
    # Use lowercase digits and uppercase suffix: 328pb => 328PB; 168p => 168P
    import re
    m=re.match(r'(\d+)([a-z]*)',part)
    macro='__AVR_ATmega'+m.group(1)+m.group(2).upper()+'__'
    selectors.append(('#if' if i==0 else '#elif')+' defined('+macro+')')
    selectors.append('#include "'+name+'.inc"')
selectors += ['#else', '#error Unsupported MCU: select an ATmega profile defined in devices/', '#endif','']
(P/'select.inc').write_text('\n'.join(selectors))
(Path(__file__).parent/'devices.json').write_text(json.dumps(jsonout,indent=2)+'\n')
print('Generated',len(devices),'device headers')
