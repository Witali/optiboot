#!/usr/bin/env python3
"""Compare nominal public-edition binaries from Clang and AVR-GCC.

Also compile the application SPM header for every profile exposing that ABI.
All output is local; this script does not connect to a board.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import build_dual
import build_flashread
import build_mini
import generate_firmware

ROOT = Path(__file__).resolve().parent


def verify(chip, edition, output):
    dev = build_mini.DEVICES[chip]
    hz = 12000000 if chip == 'attiny1634' else 8000000 if dev['profile'].startswith('soft') else 16000000
    source = 'internal_rc' if dev['profile'].startswith('soft') else 'external_crystal'
    images = {}
    for toolchain in ('clang', 'gcc'):
        base = output / toolchain
        if edition == 'flashread256':
            folder = base / edition / chip
            build_flashread.one(chip, folder, hz, toolchain=toolchain)
        else:
            opts = SimpleNamespace(f_cpu=hz, clock_source=source, baud='auto',
                output_dir=base, signature_source='auto', allow_overclock=False,
                allow_baud_error=False, legacy_eeprom_byte_address=False)
            command = build_dual.build_command(chip, edition, opts)
            subprocess.run(command + ['--toolchain', toolchain], check=True,
                           capture_output=True, text=True)
            folder = base / edition / chip
        generate_firmware.verify_artifacts(chip, edition, folder)
        images[toolchain] = (folder / (chip+'.bin')).read_bytes()
    if images['clang'] != images['gcc']:
        raise RuntimeError('Clang and GCC produced different firmware bytes')
    spm = edition != 'flashread256' and not dev['virtual_boot']
    if spm:
        probe = output / 'spm_probe.c'
        # This API needs only Flash geometry from avr/io.h. Older avr-libc
        # lacks PB headers; supply the reviewed geometry explicitly in this
        # isolated compile probe, without substituting another register map.
        probe.write_text('#include <avr/io.h>\n#ifndef FLASHEND\n'
                         '#define FLASHEND '+str(dev['flash']-1)+'\n#endif\n'
                         '#include "optiboot_mini_app_spm.h"\n'
                         'void probe(void) { optiboot_mini_do_spm(0, 1, 0x1234); }\n')
        target, flags = build_mini.assembler_target(chip, 'avr-gcc')
        command = ['avr-gcc', '-mmcu='+target, *flags, '-Os', '-I', str(ROOT),
                   '-DOPTIBOOT_MINI_BOOT_BYTES='+str(512 if edition == 'compact' else 1024)]
        if edition == 'compact':
            command.append('-DOPTIBOOT_MINI_SPM512=1')
        dest = output / 'header_objects'
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(command + ['-c', str(probe), '-o', str(dest/(chip+'_'+edition+'.o'))],
                       check=True, capture_output=True, text=True)
    return dict(mcu=chip, edition=edition, frequency_hz=hz,
                byte_identical=True, spm_header_compiled=spm,
                sha256=hashlib.sha256(images['clang']).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'output/toolchains')
    parser.add_argument('--mcu', choices=tuple(build_mini.DEVICES))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    passed, failed = [], []
    for chip in (args.mcu,) if args.mcu else build_mini.DEVICES:
        for edition in generate_firmware.valid_types(chip):
            try:
                passed.append(verify(chip, edition, args.output))
                print(f'PASS Clang/GCC {chip}/{edition}', flush=True)
            except Exception as error:
                failed.append(dict(mcu=chip, edition=edition, error=str(error)))
                print(f'FAIL Clang/GCC {chip}/{edition}: {error}', flush=True)
    (args.output/'summary.json').write_text(json.dumps(dict(passed=passed,
        failed=failed, software_only=True), indent=2)+'\n')
    print(f'RESULT: {len(passed)} passed; {len(failed)} failed.')
    return bool(failed)


if __name__ == '__main__':
    sys.exit(main())
