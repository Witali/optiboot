#!/usr/bin/env python3
"""Build Mini256, or explicitly opt into the ATmega328PB Mini512 experiment."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import build_mini
import device_database

ROOT = Path(__file__).resolve().parent
TARGETS = tuple(m for m, d in device_database.DEVICES.items()
                if device_database.supports_mini(d))


def one(mcu, dest, f_cpu=16000000, baud=115200, toolchain='auto', *, experimental_512=False):
    if experimental_512 and mcu != 'atmega328pb':
        raise ValueError('The experimental 512-byte Mini reservation is restricted to atmega328pb')
    if not experimental_512 and mcu not in TARGETS:
        raise ValueError('256-byte Flash read/write is unavailable for ' + mcu)
    boot_bytes = 512 if experimental_512 else 256
    dev = build_mini.DEVICES[mcu]
    device_database.check_generated_device(mcu)
    if not 8000000 <= f_cpu <= dev['max_mhz'] * 1000000:
        raise ValueError('F_CPU outside project limits or the device rating')
    uart = build_mini.best_baud(f_cpu, baud)
    if abs(uart['baud_error_percent']) > 2.5:
        raise ValueError('UART divider error exceeds 2.5%')
    _, cc, objcopy, flags = build_mini.compiler_tools(toolchain)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    obj, raw = dest / (mcu + '.o'), dest / (mcu + '.bin')
    experiment_flags = ['-DMINI_FLASHREAD_EXPERIMENTAL_328PB_512=1'] if experimental_512 else []
    subprocess.run([cc, *flags, '-mmcu=' + mcu, '-I', str(ROOT),
                    '-DMINI_FLASH_ONLY_256=1', '-DMINI_FLASH256_READBACK=1',
                    *experiment_flags, f'-DBOOT_BYTES={boot_bytes}', f'-DF_CPU={f_cpu}', f'-DBAUD_RATE={baud}',
                    f'-DMINI_U2X={uart["u2x"]}', f'-DMINI_UBRR={uart["ubrr"]}',
                    '-c', str(ROOT / 'optiboot_mini.S'), '-o', str(obj)], check=True)
    linked = build_mini.linked_object(obj, mcu)
    subprocess.run([objcopy, '-O', 'binary', '-j', '.text', str(linked), str(raw)], check=True)
    data = raw.read_bytes()
    symbols = subprocess.check_output(['llvm-objdump', '-t', str(obj)], text=True)
    def symbol(name):
        match = re.search(r'^([0-9a-fA-F]+)\s+\S+\s+\.text\s+\S+\s+' + re.escape(name) + r'$', symbols, re.M)
        if not match:
            raise RuntimeError('Missing firmware symbol: ' + name)
        return int(match[1], 16)
    used = symbol('_code_end')
    parameter = symbol('parameter_constant')
    footer_start = boot_bytes - 3
    if (len(data) != boot_bytes or used > footer_start
            or data[used:footer_start] != b'\xff' * (footer_start-used)
            or data[-3:] != bytes(dev['sig'])):
        raise RuntimeError(f'Code/signature does not fit the physical {boot_bytes}-byte boot section')
    if data[parameter:parameter+2] != bytes.fromhex('03fd'):
        raise RuntimeError('The reused parameter constant is not the expected SBRC opcode')
    if experimental_512 and used + 3 > 256:
        raise RuntimeError('Experimental Mini code plus signature must remain within the 256-byte useful budget')
    start = dev['flash'] - boot_bytes
    if symbol('boot256_end') != boot_bytes:
        raise RuntimeError('The reset-only application return does not wrap at the physical Flash end')
    (dest / (mcu + '.hex')).write_text(build_mini.make_hex(data, start))
    result = dict(mcu=mcu, edition='mini-experimental-512' if experimental_512 else 'mini', boot_bytes=boot_bytes,
                  boot_start=f'0x{start:04X}', boot_word_address=f'0x{start//2:04X}',
                  bootsz1_0_bits='11', code_bytes=used, footer_bytes=3,
                  free_bytes=footer_start-used, page_bytes=dev['page'], flash_bytes=dev['flash'],
                  signature=''.join(f'{v:02X}' for v in dev['sig']),
                  f_cpu_hz=f_cpu, baud=baud, **uart,
                  requires_hardware_reset=True, eeprom_busy_interlock=True,
                  flash_read=True, flash_write=True, eeprom_read=False, eeprom_write=False,
                  code_sha256=hashlib.sha256(data).hexdigest(),
                  on_silicon_tested=False, avrdude_host_tested=False)
    if experimental_512:
        result.update(experimental=True, application_bytes=start, useful_bytes=used+3,
                      hardware_min_boot_bytes=512,
                      canonical_mini256_target=False)
    (dest / (mcu + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mcu', default='atmega8')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--experimental-328pb-512', action='store_true',
                        help='explicitly build Mini for ATmega328PB with its 512-byte physical Boot reservation')
    parser.add_argument('--f-cpu', type=int, default=16000000)
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--toolchain', choices=('auto', 'clang', 'gcc'), default='auto')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'output/mini')
    args = parser.parse_args()
    if args.experimental_328pb_512 and (args.all or args.list or args.mcu != 'atmega328pb'):
        parser.error('--experimental-328pb-512 requires --mcu atmega328pb and cannot use --all or --list')
    if args.list:
        print('\n'.join(TARGETS))
        return
    for mcu in TARGETS if args.all else (args.mcu,):
        result = one(mcu, args.output_dir / mcu, args.f_cpu, args.baud, args.toolchain,
                     experimental_512=args.experimental_328pb_512)
        print(f'OK {mcu}: {result["code_bytes"]}+3/{result["boot_bytes"]} bytes at {result["boot_start"]}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print('ERROR:', error, file=sys.stderr)
        sys.exit(1)
