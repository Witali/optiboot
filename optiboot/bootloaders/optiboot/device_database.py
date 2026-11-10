"""Validated device data and its assembly representation for Optiboot Mini.

devices.json is the authoritative per-MCU database. Architecture-specific
register templates live here; importing this module never writes files.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent
DATABASE_PATH = ROOT / 'devices.json'
PROFILES = frozenset(('modern', 'modern128', 'modern256', 'legacy', 'mega64',
                      'mega128', 'tiny841', 'tiny1634', 'soft84', 'soft85'))
INTEGER_FIELDS = ('flash', 'eeprom', 'page', 'max_mhz', 'ramend', 'default_boot',
                  'flash_erase_group_bytes', 'wdt_ccp_style')
BOOLEAN_FIELDS = ('virtual_boot', 'spm512_capable', 'wide_branches',
                  'sigrow_lpm_supported_by_datasheet', 'dual_compact_enabled')
REQUIRED_FIELDS = frozenset((*INTEGER_FIELDS, *BOOLEAN_FIELDS, 'sig', 'profile',
                             'hardware_min_boot_bytes'))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate database key: {key}')
        result[key] = value
    return result


def _power_of_two(value):
    return type(value) is int and value > 0 and value & (value - 1) == 0


def load_devices(path=DATABASE_PATH):
    """Read and validate all records before exposing any device to a builder."""
    devices = json.loads(Path(path).read_text(encoding='utf-8'),
                         object_pairs_hook=_unique_object)
    if not isinstance(devices, dict) or not devices:
        raise ValueError('Device database must be a nonempty object')
    for name, dev in devices.items():
        if not re.fullmatch(r'(atmega|attiny)\d+[a-z]*', name):
            raise ValueError(f'Invalid MCU identifier: {name}')
        if not isinstance(dev, dict) or set(dev) != REQUIRED_FIELDS:
            raise ValueError(f'{name}: missing or unknown database fields')
        for field in INTEGER_FIELDS:
            if type(dev[field]) is not int:
                raise ValueError(f'{name}: {field} must be an integer')
        for field in BOOLEAN_FIELDS:
            if type(dev[field]) is not bool:
                raise ValueError(f'{name}: {field} must be a boolean')
        if not isinstance(dev['profile'], str) or dev['profile'] not in PROFILES:
            raise ValueError(f'{name}: unsupported architecture profile')
        sig = dev['sig']
        if (not isinstance(sig, list) or len(sig) != 3 or
                any(type(byte) is not int or not 0 <= byte <= 255 for byte in sig)):
            raise ValueError(f'{name}: signature must contain three byte values')
        flash, page, erase = (dev[k] for k in ('flash', 'page', 'flash_erase_group_bytes'))
        if not _power_of_two(flash) or not 8192 <= flash <= 262144:
            raise ValueError(f'{name}: unsupported Flash geometry')
        if not _power_of_two(page) or not 16 <= page <= 256 or flash % page:
            raise ValueError(f'{name}: invalid Flash page geometry')
        if not _power_of_two(erase) or erase < page or erase > 256 or flash % erase:
            raise ValueError(f'{name}: invalid Flash erase group')
        if not _power_of_two(dev['eeprom']) or dev['eeprom'] > 65536 or not 0x100 <= dev['ramend'] <= 0xffff:
            raise ValueError(f'{name}: invalid EEPROM or SRAM geometry')
        if not 8 <= dev['max_mhz'] <= 28 or dev['wdt_ccp_style'] not in (0, 1, 2):
            raise ValueError(f'{name}: invalid clock rating or watchdog style')
        virtual = dev['profile'].startswith(('tiny', 'soft'))
        if dev['virtual_boot'] != virtual or virtual != name.startswith('attiny'):
            raise ValueError(f'{name}: architecture and Virtual Boot disagree')
        minimum = dev['hardware_min_boot_bytes']
        if virtual:
            if minimum is not None or dev['default_boot'] != 1024 or dev['spm512_capable']:
                raise ValueError(f'{name}: invalid Virtual Boot configuration')
        else:
            expected_minimum = 256 if flash <= 16384 else 512 if flash <= 32768 else 1024
            if type(minimum) is not int or minimum != expected_minimum:
                raise ValueError(f'{name}: invalid hardware Boot minimum')
            if dev['default_boot'] not in [minimum << i for i in range(4)]:
                raise ValueError(f'{name}: default Boot area is not a hardware Boot size')
            if minimum >= 1024 and (dev['dual_compact_enabled'] or dev['spm512_capable']):
                raise ValueError(f'{name}: hardware Boot minimum forbids a 512-byte profile')
            if dev['dual_compact_enabled'] and not dev['spm512_capable']:
                raise ValueError(f'{name}: Middle requires the 512-byte application SPM profile')
        if dev['default_boot'] % erase or dev['default_boot'] >= flash:
            raise ValueError(f'{name}: default Boot area is not erase-aligned inside Flash')
    return devices


def supports_mini(dev):
    return (dev['hardware_min_boot_bytes'] == 256 and
            dev['profile'] in ('modern', 'legacy') and
            dev['page'] in (64, 128) and dev['flash'] <= 16384)


def available_editions(dev):
    editions = ('middle', 'full') if dev['dual_compact_enabled'] else ('full',)
    return editions + ('mini',) if supports_mini(dev) else editions


def application_vector(dev):
    """Relocated EEPROM-ready vector used by the existing Virtual Boot ABI."""
    profile = dev['profile']
    return {'tiny841': 14, 'tiny1634': 26, 'soft85': 6, 'soft84': 14}[profile]


def virtual_boot_sizes(dev):
    """Whole-erase-group Middle reservations, tried from 512 through 1024 bytes."""
    page, group, flash = (dev[k] for k in ('page', 'flash_erase_group_bytes', 'flash'))
    if not dev['virtual_boot'] or group < page or group % page or flash % group:
        raise ValueError('Invalid Virtual Boot Flash erase-group geometry')
    return tuple(range(((512 + group - 1) // group) * group, 1025, group))


def validate_virtual_boot_size(dev, value):
    if type(value) not in (int, str):
        raise ValueError('Virtual Boot reservation must be an integer')
    size = int(value)
    choices = virtual_boot_sizes(dev)
    if size not in choices:
        raise ValueError(f'Invalid Virtual Boot reservation {size}; whole-erase-group sizes: {choices}')
    return size


def linker_architecture(dev):
    if dev['profile'] in ('soft84', 'soft85', 'tiny841'):
        return 'avr25'
    if dev['virtual_boot']:
        return 'avr35'
    return ('avr6' if dev['flash'] > 131072 else 'avr51' if dev['flash'] > 65536
            else 'avr4' if dev['flash'] <= 8192 else 'avr5')


def nominal_frequency(dev):
    return 8_000_000 if dev['profile'].startswith('soft') else min(16, dev['max_mhz']) * 1_000_000


def compiler_macro(name):
    match = re.fullmatch(r'(atmega|attiny)(\d+)([a-z]*)', name)
    if not match:
        raise ValueError(f'Invalid MCU identifier: {name}')
    family = 'ATmega' if match.group(1) == 'atmega' else 'ATtiny'
    return f'__AVR_{family}{match.group(2)}{match.group(3).upper()}__'


def render_selector(devices):
    lines = ['/* MCU device selection from compiler -mmcu. */']
    for index, name in enumerate(devices):
        lines += [f'{"#if" if index == 0 else "#elif"} defined({compiler_macro(name)})',
                  f'#include "{name}.inc"']
    lines += ['#else', '#error Unsupported MCU: define a device profile', '#endif', '']
    return '\n'.join(lines)


def check_generated_device(name, devices=None, directory=ROOT / 'devices'):
    """Refuse compilation against stale data; concurrent builders only read."""
    devices = DEVICES if devices is None else devices
    expected = {f'{name}.inc': render_device(name, devices[name]),
                'select.inc': render_selector(devices)}
    for filename, text in expected.items():
        path = Path(directory) / filename
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            raise ValueError(f'Stale generated device file: {filename}; run python3 gen_devices.py')


DEVICES = load_devices()


def render_device(name, dev):
    """Render the existing assembly ABI from a validated device record."""
    flash, eeprom, page, sig, profile, ramend, default_boot = (
        dev[k] for k in ('flash', 'eeprom', 'page', 'sig', 'profile', 'ramend', 'default_boot'))
    extra = dev
    banked=flash>65536
    large=flash>131072
    # Size-dependent flag MINI_SPM_EXT historically also selects long-branch
    # variants; for the new 256-KiB target it keeps more headroom.
    spm_ext=profile in ('mega64','mega128','modern256')
    style=2 if profile in ('mega64','mega128') else 1 if profile=='legacy' else 3 if profile=='tiny841' else 4 if profile=='tiny1634' else 5 if profile in ('soft85','soft84') else 0
    virtual=dev['virtual_boot']
    vals={'FLASH_SIZE':flash, 'EEPROM_SIZE':eeprom,'FLASH_PAGE_BYTES':page,
        'SIG0':sig[0],'SIG1':sig[1],'SIG2':sig[2],'SRAM_END':ramend,
        'MINI_UART_STYLE':style, 'MINI_LEGACY_STACK':int(style in (1,2,3,4,5)),
        'MINI_VIRTUAL_BOOT':int(virtual),
        'MINI_FLASH_ERASE_GROUP_BYTES':extra['flash_erase_group_bytes'],
        'MINI_WIDE_BRANCHES':int(extra['wide_branches']),
        'MINI_SPM512_CAPABLE':int(extra['spm512_capable']),
        'MINI_SOFT_UART':int(profile in ('soft85','soft84')),
        'MINI_WDT_CCP_STYLE':extra['wdt_ccp_style'],
        'MINI_WDT_CCP_ADDR':113 if profile=='tiny841' else 47 if profile=='tiny1634' else 0,
        'MCUSR_IO':0x35 if profile=='tiny1634' else 0x34,
        'MINI_SPM_EXT':int(spm_ext),
        'MINI_FLASH_BANKED':int(banked), 'MINI_FLASH_128K':int(banked),
        'MINI_FLASH_256K':int(large),
        'SPMCSR_IO':0x37,'SPMCSR_MEM':0x68 if style==2 else 0x57,
        'WDT_IO':0x30 if profile=='tiny1634' else 0x21,
        'EEPROM_EECR_IO':0x1f if style==0 else 0x1c,
        'EEPROM_EEDR_IO':0x20 if style==0 else 0x1d,
        'EEPROM_EEARL_IO':0x21 if style==0 else 0x1e,
        'EEPROM_EEARH_IO':0x22 if style==0 else 0x1f}
    if style in (1,2): vals.update({'UART_A_IO':0x0b,'UART_B_IO':0x0a,'UART_DATA_IO':0x0c,'UART_L_IO':0x09})
    if virtual: vals['MINI_APP_VECTOR_WORD'] = application_vector(dev)
    if banked: vals['RAMPZ_IO']=0x3b
    if style==1: vals.update({'UART_C_IO':0x20,'UART_H_IO':0x20})
    if style==2: vals.update({'UART_C_MEM':0x95,'UART_H_MEM':0x90})
    if style==5: vals.update({'SOFT_PORT_IO':0x18 if profile=='soft85' else 0x1b,
                              'SOFT_DDR_IO':0x17 if profile=='soft85' else 0x1a,
                              'SOFT_PIN_IO':0x16 if profile=='soft85' else 0x19,
                              'SOFT_TX_BIT':0 if profile=='soft85' else 1,
                              'SOFT_RX_BIT':1 if profile=='soft85' else 2})
    body=[f'/* Hardware configuration for {name}. Generated by gen_devices.py. */']
    for k,v in vals.items():
        body.append(f'#define {k} {hex(v) if k.startswith("SIG") or k.endswith("_IO") or k.endswith("_MEM") or k=="SRAM_END" else v}')
    body+=['#ifndef BOOT_BYTES',f'#define BOOT_BYTES {default_boot}','#endif',
           '#define BOOT_START (FLASH_SIZE - BOOT_BYTES)',
           f'#define MINI_DEVICE_SIGROW_CAPABLE {int(extra["sigrow_lpm_supported_by_datasheet"])}','']
    return '\n'.join(body)
