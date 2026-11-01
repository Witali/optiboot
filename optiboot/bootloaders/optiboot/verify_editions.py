#!/usr/bin/env python3
"""Build and verify every supported edition/clock through the public generator.

This is software validation. --smoke checks every built image, including
software-UART waveforms where applicable. --stress executes real AVR
instructions for every application Flash byte and EEPROM byte in one build of
each profile. Bit-level software UART timing is covered by mini_tests separately.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
from pathlib import Path
import sys
import time

import build_mini
import generate_firmware as generator

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'mini_tests'))


def cases(all_clocks):
    for chip, dev in build_mini.DEVICES.items():
        for edition in generator.valid_types(chip):
            clocks = ((8000000, 10000000, 12000000, 16000000, 20000000)
                      if all_clocks else (8000000, 16000000))
            for hz in clocks:
                if hz <= dev['max_mhz'] * 1000000:
                    yield chip, edition, hz, 'external_clock' if chip == 'attiny85' else 'external_crystal'
            if all_clocks:
                yield chip, edition, 8000000, 'internal_rc'


def build_case(case, output):
    chip, edition, hz, clock = case
    info = generator.build_one(chip, edition, hz, clock_source=clock, out=output / 'images')
    # Re-open the files through the independent HEX/BIN validator once more.
    generator.verify_artifacts(chip, edition, Path(info['files']['bin']).parent)
    row = {k: info[k] for k in ('mcu', 'edition', 'frequency_hz', 'clock_source',
            'baud', 'baud_error_percent', 'boot_bytes', 'boot_start', 'payload_bytes',
            'free_bytes', 'sha256')}
    return row, Path(info['files']['bin']).parent


def address(cpu, value, flash=True):
    if flash and cpu.flash_size > 131072:
        reply = cpu.send(bytes((0x56, 0x4d, 0, value >> 17, 0, 0x20)))
        assert reply == b'\x14\x00\x10'
    word = value // 2
    assert cpu.send(bytes((0x55, word & 255, word >> 8 & 255, 0x20))) == b'\x14\x10'


def stress(chip, edition, folder):
    if edition == 'flashread256':
        from flashread_models import make_cpu
        cpu, image, dev = make_cpu(chip, folder)
    else:
        from device_models import create
        cpu, image, dev = create(chip, folder)
    assert cpu.send(b'0 ') == b'\x14\x10'
    assert cpu.send(b'u ') == b'\x14' + bytes(dev['sig']) + b'\x10'
    group = dev['flash_erase_group_bytes']
    original_boot = bytes(cpu.flash[cpu.boot_start:])
    for start in range(0, cpu.boot_start, group):
        payload = bytes((i*73 + start//group*17 + 19) & 255 for i in range(group))
        address(cpu, start)
        assert cpu.send(bytes((0x64, group >> 8, group & 255, 0x46)) + payload + b' ') == b'\x14\x10'
        assert cpu.flash[start:start+group] == payload, (chip, edition, start)
        for offset in range(0, group, dev['page']):
            address(cpu, start+offset)
            length = dev['page']
            expected = payload[offset:offset+length]
            assert cpu.send(bytes((0x74, length >> 8, length & 255, 0x46, 0x20))) == b'\x14'+expected+b'\x10'
    assert bytes(cpu.flash[cpu.boot_start:]) == original_boot == image
    if edition != 'flashread256':
        for start in range(0, dev['eeprom'], 16):
            data = bytes((i*29+start*3+11) & 255 for i in range(16))
            address(cpu, start, flash=False)
            assert cpu.send(b'd\x00\x10E'+data+b' ') == b'\x14\x10'
            address(cpu, start, flash=False)
            assert cpu.send(b't\x00\x10E ') == b'\x14'+data+b'\x10'
        eeprom_bytes = dev['eeprom']
    else:
        eeprom_bytes = 0
    return {'mcu': chip, 'edition': edition, 'application_flash_bytes': cpu.boot_start,
            'eeprom_bytes': eeprom_bytes, 'boot_unchanged': True}


def smoke(row, folder):
    """Exercise both application boundaries for this exact clock/edition image."""
    chip, edition = row['mcu'], row['edition']
    if edition == 'flashread256':
        from flashread_models import make_cpu
        cpu, image, dev = make_cpu(chip, folder)
    else:
        from device_models import create
        cpu, image, dev = create(chip, folder)
    assert cpu.send(b'0 ') == b'\x14\x10'
    assert cpu.send(b'u ') == b'\x14' + bytes(dev['sig']) + b'\x10'
    group = dev['flash_erase_group_bytes']
    for start in (0, cpu.boot_start-group):
        payload = bytes((i*31+start+7) & 255 for i in range(group))
        address(cpu, start)
        assert cpu.send(bytes((0x64, group >> 8, group & 255, 0x46)) + payload + b' ') == b'\x14\x10'
        assert bytes(cpu.flash[start:start+group]) == payload
        for offset in range(0, group, dev['page']):
            address(cpu, start+offset)
            n = dev['page']
            assert cpu.send(bytes((0x74, n >> 8, n & 255, 0x46, 0x20))) == b'\x14'+payload[offset:offset+n]+b'\x10'
    assert bytes(cpu.flash[cpu.boot_start:]) == image
    if edition != 'flashread256':
        for start in (0, dev['eeprom']-16):
            payload = bytes((i*43+3) & 255 for i in range(16))
            address(cpu, start, flash=False)
            assert cpu.send(b'd\x00\x10E'+payload+b' ') == b'\x14\x10'
            address(cpu, start, flash=False)
            assert cpu.send(b't\x00\x10E ') == b'\x14'+payload+b'\x10'
    waveform = dev['profile'].startswith('soft')
    if waveform:
        from test_soft_uart import SoftAVR
        from test_legacy_uart import symaddr
        # Execute the unmodified GPIO RX/TX routines, without SoftByteUART.
        wire = SoftAVR(image, dev, baud=row['baud'], f_cpu=row['frequency_hz'])
        wire.rxwait_pc = wire.boot_start + symaddr(folder / (chip+'.o'), 'rx_wait')
        wire.wait_ready()
        wire.send_wave(b'0 ')
        wire.send_wave(b'u ')
        assert wire.decoded_transmit() == b'\x14\x10\x14'+bytes(dev['sig'])+b'\x10'
    return dict(mcu=chip, edition=edition, frequency_hz=row['frequency_hz'],
                clock_source=row['clock_source'], boot_unchanged=True,
                software_uart_waveform=waveform)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/validation')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--all-clocks', action='store_true')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--stress', action='store_true')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    matrix, folders, builds, failures = [], {}, [], []
    jobs = list(cases(args.all_clocks))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        pending = {pool.submit(build_case, case, args.output): case for case in jobs}
        for count, future in enumerate(as_completed(pending), 1):
            case = pending[future]
            try:
                row, folder = future.result()
                matrix.append(row)
                builds.append((row, folder))
                chip, edition, hz, clock = case
                # Select a build near the normal reference for each MCU/edition.
                if (chip, edition) not in folders or (hz == 16000000 and clock != 'internal_rc'):
                    folders[chip, edition] = folder
            except Exception as error:
                failures.append({'case': case, 'error': str(error)})
            if count % 20 == 0 or count == len(jobs):
                print(f'Builds checked: {count}/{len(jobs)}; failed: {len(failures)}', flush=True)
    matrix.sort(key=lambda r: (r['mcu'], r['edition'], r['frequency_hz'], r['clock_source']))
    with (args.output / 'matrix.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(matrix[0]) if matrix else [])
        writer.writeheader()
        writer.writerows(matrix)
    smoke_results, results = [], []
    if args.smoke and not failures:
        for count, (row, folder) in enumerate(sorted(builds, key=lambda pair: str(pair[1])), 1):
            try:
                smoke_results.append(smoke(row, folder))
            except Exception as error:
                failures.append({'case': [row['mcu'], row['edition'], row['frequency_hz'],
                                         row['clock_source'], 'smoke'], 'error': str(error)})
            if count % 20 == 0 or count == len(builds):
                print(f'Images exercised: {count}/{len(builds)}; failed: {len(failures)}', flush=True)
    if args.stress and not failures:
        for (chip, edition), folder in sorted(folders.items()):
            try:
                results.append(stress(chip, edition, folder))
                print(f'PASS memory {chip}/{edition}', flush=True)
            except Exception as error:
                failures.append({'case': [chip, edition, 'memory stress'], 'error': str(error)})
                print(f'FAIL memory {chip}/{edition}: {error}', flush=True)
    summary = dict(builds=len(matrix), planned_builds=len(jobs), failures=failures,
                   image_smoke=smoke_results, memory_stress=results, software_only=True,
                   seconds=round(time.monotonic()-started, 3))
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(f'RESULT: {len(matrix)}/{len(jobs)} builds; {len(smoke_results)} exercised images; '
          f'{len(results)} memory profiles; {len(failures)} failures.')
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
