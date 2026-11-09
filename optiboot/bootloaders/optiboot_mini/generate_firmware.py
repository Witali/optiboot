#!/usr/bin/env python3
"""One-command, validated Optiboot Mini firmware generator.

Examples:
  python generate_firmware.py atmega328p compact 16MHz
  python generate_firmware.py --mcu atmega8 --type flash256 --freq 8MHz
  python generate_firmware.py atmega2560 full 16MHz --baud 115200
  python generate_firmware.py --list

Uses the existing builders and ONE assembly source (optiboot_mini.S).
No HEX patching, fuse programming or firmware flashing is performed here.
Build results are EXPERIMENTAL until physically tested with ISP recovery.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import build_dual
import build_flash256
import build_flash256_readback
import build_mini

ROOT = Path(__file__).resolve().parent
EDITION_ALIASES = {
    'compact': 'compact', 'compact512': 'compact', 'middle': 'compact', 'mid': 'compact',
    'full': 'full', 'full1024': 'full',
    'flash256': 'flash256', 'mini': 'flash256', 'flash-only': 'flash256', 'flash-only-256': 'flash256',
    'flashread512': 'flashread512', 'flashread': 'flashread512',
    'flash-read': 'flashread512',
    'flash-read-512': 'flashread512',
}


def parse_frequency(value: str) -> int:
    """Parse Hz or MHz; unsuffixed 8..28 means MHz, larger numbers mean Hz."""
    s = value.strip().lower().replace('_', '').replace(' ', '')
    match = re.fullmatch(r'(\d+(?:\.\d+)?)(mhz|m|hz)?', s)
    if not match:
        raise ValueError(f'Invalid frequency {value!r}. Examples: 8MHz, 16MHz, 16000000')
    try:
        amount = Decimal(match.group(1))
        unit = match.group(2)
        if unit in ('mhz', 'm') or (unit is None and amount <= 28):
            amount *= 1_000_000
        if amount != amount.to_integral_value():
            raise ValueError('Frequency must represent an integral number of Hz')
        hz = int(amount)
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError('Unrecognizable frequency') from exc
    if not build_mini.MIN_F_CPU <= hz <= build_mini.MAX_F_CPU:
        raise ValueError('Supported project frequency range is 8..28 MHz')
    return hz


def default_clock(mcu: str, hz: int) -> str:
    if mcu in ('attiny84', 'attiny85') and hz == 8_000_000:
        return 'internal_rc'
    if mcu == 'attiny85':
        # ATtiny85 has an external clock input, not a dedicated crystal oscillator.
        return 'external_clock'
    return 'external_crystal'


def valid_types(mcu: str) -> tuple[str, ...]:
    allowed = list(build_dual.available_editions(mcu))
    if mcu in build_flash256.TARGETS:
        allowed.extend(['flash256', 'flashread512'])
    return tuple(allowed)


def choose_flash_baud(hz: int, requested: str) -> int:
    if requested.lower() != 'auto':
        try:
            baud = int(requested)
        except ValueError as exc:
            raise ValueError('--baud must be a positive integer or auto') from exc
        if baud <= 0:
            raise ValueError('--baud must be positive')
        return baud
    candidates = (38400, 57600, 19200) if hz == 8_000_000 else (115200, 57600, 38400, 19200)
    for candidate in candidates:
        if abs(build_mini.best_baud(hz, candidate)['baud_error_percent']) <= 2.5:
            return candidate
    raise ValueError('No baud rate with acceptable nominal USART divider error')


def parse_ihex(path: Path) -> dict[int, int]:
    """Read and validate all Intel HEX data records, checksums and ELA addresses."""
    result: dict[int, int] = {}
    upper = 0
    saw_eof = False
    for line_num, line in enumerate(path.read_text(encoding='ascii').splitlines(), 1):
        if not line.startswith(':'):
            raise ValueError(f'Intel HEX line {line_num}: missing colon')
        try:
            record = bytes.fromhex(line[1:])
        except ValueError as exc:
            raise ValueError(f'Intel HEX line {line_num}: non-hex data') from exc
        if len(record) < 5 or len(record) != record[0] + 5 or sum(record) % 256:
            raise ValueError(f'Intel HEX line {line_num}: invalid length/checksum')
        n, high, low, kind = record[:4]
        address = (high << 8) | low
        data = record[4:4+n]
        if saw_eof:
            raise ValueError('Intel HEX contains records after EOF')
        if kind == 0:
            for i, byte in enumerate(data):
                addr = upper + address + i
                if addr in result:
                    raise ValueError(f'Overlapping HEX records at 0x{addr:X}')
                result[addr] = byte
        elif kind == 4:
            if n != 2 or address:
                raise ValueError('Malformed extended linear address record')
            upper = int.from_bytes(data, 'big') << 16
        elif kind == 1:
            if n != 0:
                raise ValueError('Malformed EOF record')
            saw_eof = True
        else:
            raise ValueError(f'Unexpected Intel HEX record type: {kind}')
    if not saw_eof:
        raise ValueError('Intel HEX has no EOF')
    return result


def verify_artifacts(mcu: str, edition: str, result_dir: Path) -> dict[str, Any]:
    meta_file = result_dir / f'{mcu}.json'
    hex_file = result_dir / f'{mcu}.hex'
    bin_file = result_dir / f'{mcu}.bin'
    for path in (meta_file, hex_file, bin_file):
        if not path.is_file():
            raise RuntimeError(f'Builder did not produce expected file: {path}')
    meta = json.loads(meta_file.read_text())
    payload = bin_file.read_bytes()
    boot_bytes = int(meta['boot_bytes'])
    if len(payload) != boot_bytes:
        raise RuntimeError(f'BIN size mismatch: {len(payload)} instead of {boot_bytes} bytes')
    chip = build_mini.DEVICES[mcu]
    expected_base = chip['flash'] - boot_bytes
    if expected_base % chip['page']:
        raise RuntimeError('Boot start is not aligned to a physical Flash page')
    actual_base = int(meta.get('boot_start_hex', meta.get('boot_start', '0x0')), 16)
    if actual_base != expected_base:
        raise RuntimeError(f'Boot address mismatch: {actual_base:04X} vs {expected_base:04X}')
    data = parse_ihex(hex_file)
    if len(data) != boot_bytes or any(data.get(expected_base+i) != byte
                                       for i, byte in enumerate(payload)):
        raise RuntimeError('HEX content is not identical to BIN at the target Boot address')
    digest = hashlib.sha256(payload).hexdigest()
    claimed = meta.get('bin_sha256', meta.get('code_sha256'))
    if digest != claimed:
        raise RuntimeError('BIN SHA-256 differs from builder metadata')
    if edition in ('compact', 'full'):
        build_dual.verify_manifest(mcu, edition, meta)
        useful = int(meta['code_bytes']) + int(meta['footer_bytes'])
        if useful > boot_bytes:
            raise RuntimeError('Code/footer overflow')
    else:
        expect_boot = 256 if edition == 'flash256' else 512
        if boot_bytes != expect_boot or meta['edition'] != ('flash_only_256' if edition == 'flash256'
                                                            else 'flash_readback_512'):
            raise RuntimeError('Flash-only build edition/section mismatch')
        useful = int(meta['code_bytes']) + (4 if edition == 'flashread512' else 0)
        if useful > boot_bytes:
            raise RuntimeError('Flash-only payload overflow')
    return {'image': payload, 'meta': meta, 'boot': boot_bytes,
            'start': expected_base, 'useful': useful, 'sha256': digest,
            'hex_path': hex_file, 'bin_path': bin_file, 'meta_path': meta_file}


def build_one(mcu: str, edition: str, hz: int, *, baud: str='auto',
              clock_source: str='auto', signature_source: str='auto',
              legacy_eeprom_byte_address: bool=False,
              out: Path=ROOT / 'generated', timeout: int=180,
              dry_run: bool=False, verbose: bool=False) -> dict[str, Any]:
    mcu = mcu.lower().strip()
    edition = EDITION_ALIASES.get(edition.lower().strip(), '')
    if mcu not in build_mini.DEVICES:
        raise ValueError(f'Unknown MCU {mcu!r}; run --list to see all 38')
    if not edition:
        raise ValueError('Unknown firmware type; choose compact, full, flash256 or flashread512')
    if edition not in valid_types(mcu):
        raise ValueError(f'{mcu}: {edition} unavailable; choose {", ".join(valid_types(mcu))}')
    device = build_mini.DEVICES[mcu]
    if hz < build_mini.MIN_F_CPU or hz > device['max_mhz'] * 1_000_000:
        raise ValueError(f'{mcu}: frequency must be between 8 MHz and rated {device["max_mhz"]} MHz')
    source = default_clock(mcu, hz) if clock_source == 'auto' else clock_source
    if source not in build_mini.SUPPORTED_CLOCKS:
        raise ValueError('Invalid clock source')
    if source == 'internal_rc' and hz != 8_000_000:
        raise ValueError('The existing firmware only supports internal RC at 8 MHz')
    if mcu == 'attiny85' and source == 'external_crystal':
        raise ValueError('ATtiny85 has no crystal oscillator; use external_clock or internal_rc')
    if legacy_eeprom_byte_address and (edition != 'full' or mcu not in ('atmega64a', 'atmega128a')):
        raise ValueError('Legacy EEPROM byte addressing applies only to ATmega64A/128A Full')
    if legacy_eeprom_byte_address and mcu == 'atmega64a':
        raise ValueError('ATmega64A Full legacy EEPROM address mode currently fails assembly (BRxx range); use standard addressing')
    if edition.startswith('flash') and signature_source != 'auto':
        raise ValueError('Flash256/FlashRead512 use constant signatures; omit --signature-source')
    if edition in ('compact', 'full') and signature_source == 'hardware' and not device.get('sigrow_lpm_supported_by_datasheet'):
        raise ValueError(f'{mcu} is not audited for SIGRD+LPM; choose auto or constants')
    baud = str(baud).lower().strip()
    if baud != 'auto':
        try:
            if int(baud) <= 0: raise ValueError()
        except ValueError:
            raise ValueError('--baud must be a positive integer or auto') from None
    # Stable collision-free output grouping for independent combinations.
    addressing = 'legacy-eeaddr' if legacy_eeprom_byte_address else 'standard-eeaddr'
    variant = f'{hz}Hz_{source}_baud-{baud}_signature-{signature_source}_{addressing}'
    workspace = Path(out).expanduser().resolve() / mcu / variant
    result_dir = workspace / edition / mcu
    if edition in ('compact', 'full'):
        command = [sys.executable, str(ROOT/'build_dual.py'), '--mcu', mcu,
                   '--edition', edition, '--f-cpu', str(hz), '--clock-source', source,
                   '--baud', str(baud), '--signature-source', signature_source,
                   '--output-dir', str(workspace)]
        if legacy_eeprom_byte_address:
            command.append('--legacy-eeprom-byte-address')
    else:
        selected_baud = choose_flash_baud(hz, str(baud))
        if abs(build_mini.best_baud(hz, selected_baud)['baud_error_percent']) > 2.5:
            raise ValueError('UART divider error is over 2.5%; change baud or frequency')
        builder = 'build_flash256.py' if edition == 'flash256' else 'build_flash256_readback.py'
        command = [sys.executable, str(ROOT/builder), '--mcu', mcu,
                   '--f-cpu', str(hz), '--baud', str(selected_baud),
                   '--output-dir', str(workspace/edition)]
    if dry_run:
        return {'command': command, 'result_dir': result_dir, 'dry_run': True}
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'Build timed out after {timeout} s') from exc
    (workspace/'build.log').write_text('COMMAND: '+ ' '.join(command) +
                                       '\n\nSTDOUT:\n'+proc.stdout+'\nSTDERR:\n'+proc.stderr)
    if verbose:
        print(proc.stdout, end='')
        if proc.stderr: print(proc.stderr, file=sys.stderr, end='')
    if proc.returncode:
        raise RuntimeError('Firmware build failed (see build.log):\n' +
                           (proc.stderr or proc.stdout)[-2500:])
    check = verify_artifacts(mcu, edition, result_dir)
    meta = check['meta']
    if edition in ('compact', 'full'):
        actual_baud = meta['baud_requested']
        baud_error = meta['baud_error_percent']
        features = {
            'flash_read': True, 'flash_write': True, 'eeprom_read': True, 'eeprom_write': True,
            'get_sign_on': edition == 'full', 'read_fuses_lock': edition == 'full',
            'app_spm_abi': not device['virtual_boot'],
        }
    else:
        actual_baud = meta['baud']
        baud_error = meta['baud_error_percent']
        features = {
            'flash_read': edition == 'flashread512', 'flash_write': True,
            'eeprom_read': False, 'eeprom_write': False,
            'get_sign_on': False, 'read_fuses_lock': False, 'app_spm_abi': False,
        }
    warnings = ['EXPERIMENTAL firmware: not verified with real AVRDUDE or physical MCU.',
                'CPU frequency and clock source must match device clock/fuse settings.']
    if device['virtual_boot']:
        warnings.append('Virtual Boot requires ISP seed and application vector patch; no hardware BOOTSZ protection.')
    if edition.startswith('flash'):
        warnings.append('PROG_PAGE requires full Flash pages; prepare/pad the application HEX first.')
        warnings.append('Use AVRDUDE -c arduino -D'+(' -V' if edition=='flash256' else '')+'; full Arduino IDE upload needs integration.')
    if source == 'internal_rc':
        warnings.append('Internal RC frequency can drift; UART timing needs board-level calibration.')
    result = {
        'mcu': mcu, 'edition': edition, 'frequency_hz': hz, 'clock_source': source,
        'baud': actual_baud, 'baud_error_percent': baud_error,
        'signature_source': meta.get('signature_source', 'constants'),
        'boot_bytes': check['boot'], 'hardware_min_boot_bytes': device.get('hardware_min_boot_bytes'),
        'boot_start': f'0x{check["start"]:X}', 'bootsz1_0_bits': meta.get('bootsz1_0_bits'),
        'payload_bytes': check['useful'], 'free_bytes': check['boot']-check['useful'],
        'flash_page_bytes': device['page'], 'flash_bytes': device['flash'],
        'eeprom_bytes': device['eeprom'], 'features': features,
        'sha256': check['sha256'], 'on_silicon_tested': False, 'warnings': warnings,
        'files': {'hex': str(check['hex_path']), 'bin': str(check['bin_path']),
                  'original_build_metadata': str(check['meta_path']),
                  'build_log': str(workspace/'build.log')},
    }
    result['files']['build_info'] = str(result_dir/'build_info.json')
    (result_dir/'build_info.json').write_text(json.dumps(result, indent=2,
                                                          ensure_ascii=False)+'\n')
    return result


def print_list(mcu_filter: str | None=None) -> None:
    names = list(build_mini.DEVICES)
    if mcu_filter:
        if mcu_filter not in build_mini.DEVICES:
            raise ValueError(f'Unknown MCU {mcu_filter}; choose from --list')
        names = [mcu_filter]
    print(f'{"MCU":15} {"Flash":>6} {"Min Boot":>9} {"Max MHz":>7}  Available firmware types')
    for chip in names:
        dev = build_mini.DEVICES[chip]
        min_boot = str(dev.get('hardware_min_boot_bytes') or 'virtual')
        print(f'{chip:15} {dev["flash"]//1024:>4}KB {min_boot:>9} {dev["max_mhz"]:>7}  '
              f'{", ".join(valid_types(chip))}')


def main(argv: list[str] | None=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mcu_pos', nargs='?', help='MCU, e.g. atmega328p')
    parser.add_argument('type_pos', nargs='?', help='compact, full, flash256 or flashread512')
    parser.add_argument('freq_pos', nargs='?', help='16MHz, 8MHz, 16000000, etc.')
    parser.add_argument('--mcu', dest='mcu_opt')
    parser.add_argument('--type', '--edition', dest='type_opt')
    parser.add_argument('--freq', '--frequency', '--f-cpu', dest='freq_opt')
    parser.add_argument('--baud', default='auto', help='UART speed, auto by default')
    parser.add_argument('--clock', '--clock-source', default='auto', choices=('auto', *build_mini.SUPPORTED_CLOCKS))
    parser.add_argument('--signature-source', default='auto', choices=('auto', 'constants', 'hardware'))
    parser.add_argument('--legacy-eeprom-byte-address', action='store_true')
    parser.add_argument('--output', '--out', default=str(ROOT/'generated'))
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--dry-run', action='store_true', help='Validate and show the underlying command, do not compile')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--list', action='store_true', help='Show available editions per MCU')
    args = parser.parse_args(argv)
    try:
        if args.list:
            print_list((args.mcu_opt or args.mcu_pos or '').lower() or None)
            return 0
        mcu = (args.mcu_opt or args.mcu_pos or '').lower()
        edition = (args.type_opt or args.type_pos or '').lower()
        freq = args.freq_opt or args.freq_pos
        if not mcu or not edition or not freq:
            parser.error('specify MCU, firmware type and CPU frequency; or use --list')
        if args.timeout < 1: raise ValueError('--timeout must be positive')
        info = build_one(mcu, edition, parse_frequency(freq), baud=args.baud,
                         clock_source=args.clock, signature_source=args.signature_source,
                         legacy_eeprom_byte_address=args.legacy_eeprom_byte_address,
                         out=Path(args.output), timeout=args.timeout,
                         dry_run=args.dry_run, verbose=args.verbose)
        if args.dry_run:
            print('DRY RUN; command:')
            print(' '.join(info['command']))
            print('Expected directory:', info['result_dir'])
            return 0
        print(f'OK {info["mcu"]} / {info["edition"]} / {info["frequency_hz"]} Hz')
        print(f'Boot: {info["boot_bytes"]} B at {info["boot_start"]}, '
              f'payload {info["payload_bytes"]} B; free {info["free_bytes"]} B')
        print(f'UART: {info["baud"]} baud; divider error {info["baud_error_percent"]:+.2f}%')
        print('HEX:', info['files']['hex'])
        print('BIN:', info['files']['bin'])
        print('Build settings:', info['files']['build_info'])
        for note in info['warnings']:
            print('NOTE:', note)
        return 0
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
