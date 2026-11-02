#!/usr/bin/env python3
"""Build paired Optiboot Mini MIDDLE/FULL profiles from the ONE assembly source.

MIDDLE: only ATmega with <=512-byte hardware Boot minimum, plus four
         experimental ATtiny Virtual-Boot profiles. Retains EEPROM, FLASH,
         STK500v1 signatures, watchdog, MCUSR and application SPM ABI where
         available. No middle edition for 64KiB+ ATmega with 1024B BOOTSZ.
FULL:    1024-byte physical (or Virtual ATtiny) boot, EEPROM, FLASH,
         Optiboot application SPM ABI on hardware-Boot AVRs, real fuse/lock
         read, both signature commands, GET_SIGN_ON and SET_PARAMETER.

Both editions use optiboot_mini.S; no binary patching, no split firmware source.
All builds are experimental and require ISP recovery on physical hardware.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

import build_mini
import build_mini_compat

ROOT = Path(__file__).resolve().parent
EDITION_KEYS = ('middle', 'full')
EDITION_ALIASES = {'middle': 'middle', 'compact': 'middle', 'compact512': 'middle',
                   'full': 'full', 'full1024': 'full'}


def available_editions(chip: str) -> tuple[str, ...]:
    """Public edition policy; no Middle on hardware with a 1024-byte minimum."""
    dev = build_mini.DEVICES[chip]
    middle_allowed = bool(dev.get('dual_compact_enabled', True))
    if not dev['virtual_boot'] and dev.get('hardware_min_boot_bytes', 1024) >= 1024:
        if middle_allowed:
            raise ValueError(f'{chip}: invalid devices.json: 1024B hardware Boot forbids Middle')
    if dev['virtual_boot']:
        if dev.get('hardware_min_boot_bytes') is not None:
            raise ValueError(f'{chip}: Virtual Boot must have null hardware minimum')
    return EDITION_KEYS if middle_allowed else ('full',)


def firmware_sources_digest() -> str:
    """Include every firmware input in a resume key; never reuse stale builds."""
    paths = [ROOT / 'optiboot_mini.S', ROOT / 'build_mini.py',
             ROOT / 'build_mini_compat.py', ROOT / 'devices.json']
    paths += sorted((ROOT / 'devices').rglob('*.inc'))
    paths += sorted((ROOT / 'uart').rglob('*.inc'))
    h = hashlib.sha256()
    for path in paths:
        h.update(str(path.relative_to(ROOT)).encode() + b'\0')
        h.update(path.read_bytes() + b'\0')
    return h.hexdigest()


def target_clock(chip: str, device: dict, opts) -> tuple[int, str]:
    cpu = (8_000_000 if device['profile'] in ('soft85', 'soft84') else
           12_000_000 if chip == 'attiny1634' else 16_000_000) if opts.f_cpu is None else opts.f_cpu
    src = opts.clock_source or ('internal_rc' if device['profile'] in ('soft85', 'soft84') and cpu == 8_000_000
                                else 'external_crystal')
    return cpu, src


def build_command(chip: str, edition: str, opts) -> list[str]:
    """Select *hardware capabilities*, not a second MCU-specific source."""
    edition = EDITION_ALIASES.get(edition, edition)
    if edition not in EDITION_KEYS:
        raise ValueError(f'Unknown edition: {edition}')
    if edition not in available_editions(chip):
        raise ValueError(f'{chip}: MIDDLE is not offered (hardware Boot minimum 1024B); use FULL')
    dev = build_mini.DEVICES[chip]
    cpu, src = target_clock(chip, dev, opts)
    dst = Path(opts.output_dir) / edition / chip
    if edition == 'middle':
        # Reuse the already regression-tested R10 per-architecture selection.
        compatibility_args = SimpleNamespace(f_cpu=cpu, clock_source=src,
            baud=opts.baud, output_dir=str(Path(opts.output_dir) / edition),
            signature_source=opts.signature_source, get_sign_on=False,
            allow_overclock=opts.allow_overclock, allow_baud_error=opts.allow_baud_error)
        command, _, _ = build_mini_compat.build_command(chip, compatibility_args)
    else:
        command = [sys.executable, str(ROOT / 'build_mini.py'), '--mcu', chip,
            '--f-cpu', str(cpu), '--clock-source', src, '--baud', str(opts.baud),
            '--boot-bytes', '1024', '--signature-source', opts.signature_source,
            '--universal-signature', '--mcusr-parity', '--output-dir', str(dst)]
        if not dev['virtual_boot']:
            command.append('--app-spm')
        if opts.allow_overclock:
            command.append('--allow-overclock')
        if opts.allow_baud_error:
            command.append('--allow-baud-error')
    if opts.legacy_eeprom_byte_address:
        if chip not in ('atmega64a', 'atmega128a'):
            raise ValueError('--legacy-eeprom-byte-address requires ATmega64A or ATmega128A')
        command.append('--legacy-eeprom-byte-address')
    return command


def verify_manifest(chip: str, edition: str, meta: dict) -> dict:
    """Fail closed if feature flags or boot size contradict the edition contract."""
    edition = EDITION_ALIASES.get(edition, edition)
    dev = build_mini.DEVICES[chip]
    if edition not in available_editions(chip):
        raise AssertionError(f'{chip}: obsolete/disabled Middle profile')
    footprint = meta['code_bytes'] + meta['footer_bytes']
    must = {
        'stk_read_sign_0x75': True,
        'stk_universal_signature_0x30': True,
        'mcusr_parity': True,
        'stk_get_sign_on_string': edition == 'full',
        'stk_set_parameter_2byte': edition == 'full',
        'stk_universal_fuse_lock_reads': edition == 'full',
        'app_spm': not dev['virtual_boot'],
    }
    for key, value in must.items():
        if meta.get(key) != value:
            raise AssertionError(f'{chip}/{edition}: {key}={meta.get(key)!r}, expected {value!r}')
    if edition == 'full' and meta['boot_bytes'] != 1024:
        raise AssertionError(f'{chip}: FULL must use exactly 1024 bytes')
    if edition == 'middle' and not dev['virtual_boot'] and meta['boot_bytes'] != 512:
        raise AssertionError(f'{chip}: all active physical Middle profiles require 512B BOOTSZ')
    if edition == 'middle' and not dev['virtual_boot'] and footprint > 512:
        raise AssertionError(f'{chip}: MIDDLE overflow ({footprint}/512)')
    if footprint > meta['boot_bytes']:
        raise AssertionError(f'{chip}/{edition}: payload overflow')
    if meta['signature_source'] == 'hardware' and not dev.get('sigrow_lpm_supported_by_datasheet'):
        raise AssertionError(f'{chip}: unaudited signature-row profile selected')
    if meta['virtual_boot_vector_patch_required'] != bool(dev['virtual_boot']):
        raise AssertionError(f'{chip}: inconsistent virtual-boot flag')
    if meta['eeprom_bytes'] != dev['eeprom']:
        raise AssertionError(f'{chip}: missing/wrong EEPROM geometry')
    return {
        'edition': edition,
        'hardware_min_boot_bytes': dev.get('hardware_min_boot_bytes'),
        'boot_bytes': meta['boot_bytes'], 'code_bytes': meta['code_bytes'],
        'footer_bytes': meta['footer_bytes'], 'payload_bytes': footprint,
        'payload_within_512': footprint <= 512,
        'hardware_boot': not dev['virtual_boot'],
        'virtual_boot': bool(dev['virtual_boot']),
        'signature_source': meta['signature_source'],
        'eeprom_bytes': dev['eeprom'],
        'eeprom_read': True, 'eeprom_write': True,
        'flash_read': True, 'flash_write': True,
        'read_sign': True, 'universal_signature': True,
        'universal_fuse_lock_read': edition == 'full',
        'get_sign_on': edition == 'full',
        'set_parameter_payload': edition == 'full',
        'mcusr_parity': True,
        'app_spm_abi': not dev['virtual_boot'],
        'direct_app_spm': bool(dev['virtual_boot']),
        'boot_start_hex': meta['boot_start_hex'],
        'bootsz1_0_bits': meta['bootsz1_0_bits'],
        'sha256': meta['bin_sha256'],
        'experimental': True,
    }


def run_one(chip: str, edition: str, opts) -> tuple[str, str, dict | None, str | None]:
    edition = EDITION_ALIASES.get(edition, edition)
    try:
        cmd = build_command(chip, edition, opts)
        dest = Path(opts.output_dir) / edition / chip
        meta_path = dest / (chip + '.json')
        bin_path = dest / (chip + '.bin')
        reuse = False
        if opts.resume and meta_path.exists() and bin_path.exists():
            old = json.loads(meta_path.read_text())
            if (old.get('edition_build_command') == cmd and
                    old.get('edition_source_digest') == opts.edition_source_digest):
                reuse = hashlib.sha256(bin_path.read_bytes()).hexdigest() == old.get('bin_sha256')
        if not reuse:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=opts.timeout)
            if completed.returncode:
                return chip, edition, None, (completed.stderr + completed.stdout)[-3200:]
        meta = json.loads(meta_path.read_text())
        entry = verify_manifest(chip, edition, meta)
        meta['dual_edition'] = edition
        meta['edition_source_digest'] = opts.edition_source_digest
        meta['edition_contract'] = entry
        meta['edition_build_command'] = cmd
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
        return chip, edition, entry, None
    except (subprocess.TimeoutExpired, OSError, ValueError, AssertionError) as exc:
        return chip, edition, None, str(exc)


def build_matrix(opts) -> int:
    opts.edition = EDITION_ALIASES.get(opts.edition, opts.edition)
    if opts.all and (opts.f_cpu is not None or opts.clock_source or opts.legacy_eeprom_byte_address):
        raise ValueError('--all uses default per-device clock and current EEPROM addressing; run --mcu for overrides')
    opts.edition_source_digest = firmware_sources_digest()
    chips = list(build_mini.DEVICES) if opts.all else [opts.mcu]
    editions = EDITION_KEYS if opts.edition == 'both' else (opts.edition,)
    if not opts.all and opts.edition == 'middle' and 'middle' not in available_editions(chips[0]):
        raise ValueError(f'{chips[0]}: MIDDLE disabled; hardware Boot minimum is 1024B. Choose --edition full')
    pairs = [(mcu, edition) for mcu in chips for edition in editions
             if edition in available_editions(mcu)]
    excluded = [f'middle/{mcu}' for mcu in chips if 'middle' in editions
                and 'middle' not in available_editions(mcu)]
    for entry in excluded:
        print(f'SKIP {entry}: hardware Boot minimum 1024B, Full only', flush=True)
    out = Path(opts.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows, errors = {}, {}
    with ThreadPoolExecutor(max_workers=max(1, min(12, opts.jobs))) as executor:
        futures = {executor.submit(run_one, chip, edition, opts): (chip, edition)
                   for chip, edition in pairs}
        for fut in as_completed(futures):
            chip, edition, entry, problem = fut.result()
            if problem:
                errors[f'{edition}/{chip}'] = problem
                print(f'FAIL {edition}/{chip}: {problem}', file=sys.stderr, flush=True)
            else:
                rows[f'{edition}/{chip}'] = entry
                print(f'OK   {edition:7} {chip:13} '
                      f'{entry["payload_bytes"]:4}B payload / '
                      f'{entry["boot_bytes"]:4}B boot '
                      f'EEPROM={entry["eeprom_bytes"]}B SIG={entry["signature_source"]}', flush=True)
    summary = {
        'source': 'optiboot_mini.S',
        'firmware_sources_sha256': opts.edition_source_digest,
        'editions': list(editions),
        'available_editions_by_mcu': {m: list(available_editions(m)) for m in chips},
        'excluded_profiles': excluded,
        'total': len(pairs), 'passed': len(rows), 'failed': len(errors),
        'silicon_tested': False, 'hardware_avrdude_tested': False,
        'middle_payload_within_512': sum(x['payload_within_512'] for x in rows.values()
                                          if x['edition'] == 'middle'),
        'firmware': dict(sorted(rows.items())), 'errors': dict(sorted(errors.items())),
    }
    (out / 'matrix_dual.json').write_text(json.dumps(summary, indent=2) + '\n')
    fields = ['mcu', 'edition', 'boot_bytes', 'payload_bytes', 'code_bytes', 'footer_bytes',
              'payload_within_512', 'signature_source', 'eeprom_bytes', 'get_sign_on',
              'universal_fuse_lock_read', 'app_spm_abi', 'sha256']
    with (out / 'matrix_dual.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for key, entry in sorted(rows.items()):
            writer.writerow({name: entry.get(name, key.split('/')[1] if name == 'mcu' else None)
                             for name in fields})
    print(f'RESULT: {len(rows)}/{len(pairs)} valid edition builds; '
          f'{summary["middle_payload_within_512"]} middle images have payload <=512B.')
    return 1 if errors else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--edition', type=lambda v: EDITION_ALIASES.get(v, v),
                   choices=('middle', 'full', 'both'), default='both',
                   help='Edition; compact remains an alias for middle')
    p.add_argument('--mcu', choices=list(build_mini.DEVICES), default='atmega328p')
    p.add_argument('--all', action='store_true')
    p.add_argument('--list', action='store_true', help='Print the CURRENT supported editions for every MCU')
    p.add_argument('--resume', action='store_true', help='Reuse previously verified outputs from an identical build command')
    p.add_argument('--signature-source', choices=('constants', 'hardware', 'auto'), default='auto')
    p.add_argument('--f-cpu', type=int)
    p.add_argument('--clock-source', choices=build_mini.SUPPORTED_CLOCKS)
    p.add_argument('--baud', default='auto')
    p.add_argument('--jobs', type=int, default=6)
    p.add_argument('--timeout', type=int, default=90, help='Seconds per compiler process')
    p.add_argument('--allow-overclock', action='store_true')
    p.add_argument('--allow-baud-error', action='store_true')
    p.add_argument('--legacy-eeprom-byte-address', action='store_true')
    p.add_argument('--output-dir', default=str(ROOT / 'output' / 'dual'))
    opts = p.parse_args()
    if opts.list:
        for name in build_mini.DEVICES:
            d=build_mini.DEVICES[name]
            print(f'{name:14} minBoot={str(d.get("hardware_min_boot_bytes") or "virtual"):>7} '
                  f'editions={",".join(available_editions(name))}')
        return 0
    try:
        return build_matrix(opts)
    except (ValueError, OSError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
