#!/usr/bin/env python3
"""Legacy target name that compiles the SAME optiboot_mini.S source.

Emits optiboot_mini328.bin/.hex/.o beside this script for compatibility with
older build procedures.  Never assembles an independent source copy.
"""
from pathlib import Path
import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent
REFERENCE=ROOT/'optiboot_mini328.sha256'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--toolchain',choices=['auto','clang','gcc'],default='auto')
    p.add_argument('--verify-reference',action='store_true')
    args=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='mini328-src-') as d:
        cmd=[sys.executable,str(ROOT/'build_mini.py'), '--mcu','atmega328p',
             '--f-cpu','16000000','--baud','115200','--boot-bytes','512',
             '--clock-source','external_crystal','--toolchain',args.toolchain,
             '--output-dir',d]
        subprocess.run(cmd,check=True)
        for ext in ('.bin','.hex','.o'):
            shutil.copyfile(Path(d)/('atmega328p'+ext),ROOT/('optiboot_mini328'+ext))
    data=(ROOT/'optiboot_mini328.bin').read_bytes()
    sha=hashlib.sha256(data).hexdigest()
    if args.verify_reference and sha!=REFERENCE.read_text().split()[0]:
        raise RuntimeError(f'Baseline mismatch: {sha}')
    print('Legacy target assembled from optiboot_mini.S:',sha,
          'REFERENCE OK' if args.verify_reference else '')

if __name__=='__main__':
    try:main()
    except (RuntimeError,subprocess.CalledProcessError,OSError) as exc:
        print('ERROR:',exc,file=sys.stderr);sys.exit(1)
