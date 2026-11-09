#!/usr/bin/env python3
"""Deprecated command alias: compile the 511-byte variant from source.

This compatibility entry point DOES NOT clone or patch a binary.  It preserves
scripts written against build_mini_clone511.py while the preferred command is
build_mini_compat.py or build_mini.py --app-spm-512.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import build_mini

ROOT=Path(__file__).resolve().parent
COMPATIBLE=build_mini.SPM512_COMPATIBLE

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mcu',default='atmega328p')
    p.add_argument('--all',action='store_true')
    p.add_argument('--output-dir',default=str(ROOT/'output'/'spm511'))
    p.add_argument('--clock-source',choices=build_mini.SUPPORTED_CLOCKS,default='external_crystal')
    p.add_argument('--verify-reassembly',action='store_true',help='Unnecessary; source compilation is mandatory')
    p.add_argument('--f-cpu',type=int,default=16000000)
    p.add_argument('--baud',default='115200')
    args=p.parse_args()
    targets=COMPATIBLE if args.all else [args.mcu]
    for chip in targets:
        if chip not in COMPATIBLE:
            p.error(f'{chip}: compact SPM ABI unsupported; use build_mini_compat.py')
        dest=Path(args.output_dir)/chip
        cmd=[sys.executable,str(ROOT/'build_mini.py'),'--mcu',chip,
             '--f-cpu',str(args.f_cpu),'--baud',str(args.baud),
             '--clock-source',args.clock_source,'--app-spm-512',
             '--output-dir',str(dest)]
        subprocess.run(cmd,check=True)
        meta=json.loads((dest/(chip+'.json')).read_text())
        if meta['boot_bytes']!=512 or meta['code_bytes']!=506:
            print('WARNING: unexpected code footprint, inspect before flashing',file=sys.stderr)
        print(f'Compiled {chip} directly from optiboot_mini.S')

if __name__=='__main__':
    try:main()
    except (OSError,subprocess.CalledProcessError) as exc:
        print('ERROR:',exc,file=sys.stderr);sys.exit(1)
