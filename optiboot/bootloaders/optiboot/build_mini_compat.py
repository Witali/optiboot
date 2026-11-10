#!/usr/bin/env python3
"""Source-only Optiboot Mini builder for all supported AVR architectures.

One assembly source (optiboot_mini.S), one active MCU profile selected by
-mmcu, no binary patching.  For compatible 8/16/32-KiB ATmega, enable the
509-byte SPM ABI variant; modern 64KiB ATmega use compact 509-byte
code within physical 1KiB Boot; other physical-Boot ATmega use full 1KiB ABI.
Virtual-Boot ATtiny perform SPM from application code directly, so no
APP_SPM ABI is emitted for them.  All builds remain experimental.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import build_mini
import device_database

ROOT=Path(__file__).resolve().parent


def build_command(chip, args):
    dev=build_mini.DEVICES[chip]
    freq=device_database.nominal_frequency(dev) if args.f_cpu is None else args.f_cpu
    source=args.clock_source or ('internal_rc' if dev['profile'] in ('soft85','soft84') and freq==8_000_000 else 'external_crystal')
    dest=Path(args.output_dir)/chip
    compact=build_mini.supports_spm512(dev)
    compact64=chip in build_mini.COMPACT_64K or chip in build_mini.COMPACT_LEGACY64
    banked=chip in build_mini.COMPACT_BANKED
    cmd=[sys.executable,str(ROOT/'build_mini.py'),'--mcu',chip,
         '--f-cpu',str(freq),'--clock-source',source,'--baud',str(args.baud),
         '--boot-bytes','auto' if dev['virtual_boot'] else '512' if compact else '1024', '--output-dir',str(dest)]
    if compact:
        cmd.append('--app-spm-512')
    elif compact64:
        cmd.append('--compact-644' if chip in build_mini.COMPACT_644 else '--compact-64k')
    elif banked:
        cmd.append('--compact-banked')
    elif dev['virtual_boot']:
        cmd+=['--compact-tiny','--mcusr-parity']
    else:
        cmd+=['--app-spm','--mcusr-parity','--universal-signature']
    if getattr(args,'get_sign_on',False) and (compact64 or banked or dev['virtual_boot']):
        cmd.append('--compact-sign-on')
    cmd+=['--signature-source',args.signature_source]
    if args.allow_overclock:
        cmd.append('--allow-overclock')
    if args.allow_baud_error:
        cmd.append('--allow-baud-error')
    return cmd, dest, compact


def run_one(chip,args):
    cmd,dest,compact=build_command(chip,args)
    try:
        proc=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
        if proc.returncode:
            return chip,False,proc.stderr[-2600:]+'\n'+proc.stdout[-400:]
        result=json.loads((dest/(chip+'.json')).read_text())
        result['boot_mode']='virtual_experimental' if build_mini.DEVICES[chip]['virtual_boot'] else 'physical'
        result['boot_code_origin']='compiled_single_assembly_source'
        result['app_spm_abi_available']=not build_mini.DEVICES[chip]['virtual_boot']
        result['app_spm_direct_available']=bool(build_mini.DEVICES[chip]['virtual_boot'])
        result['build_command']=cmd
        (dest/(chip+'.json')).write_text(json.dumps(result,indent=2)+'\n')
        # The verified firmware is the compiler's output, never a patched BIN.
        return chip,True,result
    except (OSError,ValueError,TimeoutError,subprocess.TimeoutExpired) as exc:
        return chip,False,str(exc)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mcu',default='atmega328p',choices=list(build_mini.DEVICES))
    p.add_argument('--all',action='store_true')
    p.add_argument('--signature-source',choices=['constants','hardware','auto'],default='constants',
                   help='Audited silicon SIGRD+LPM when supported, otherwise constants')
    p.add_argument('--get-sign-on',action='store_true',
        help='Enable AVR061 GET_SIGN_ON in compact 1024-byte modes; 512-byte profiles remain unchanged')
    p.add_argument('--f-cpu',type=int)
    p.add_argument('--clock-source',choices=build_mini.SUPPORTED_CLOCKS)
    p.add_argument('--baud',default='auto')
    p.add_argument('--jobs',type=int,default=6)
    p.add_argument('--allow-overclock',action='store_true')
    p.add_argument('--allow-baud-error',action='store_true')
    p.add_argument('--output-dir',default=str(ROOT/'output'/'compat'))
    args=p.parse_args()
    if args.all and (args.f_cpu or args.clock_source):
        p.error('--all uses each device default clock; use --mcu for overrides')
    # Active edition policy: avoid regenerating obsolete 1024-byte Compact.
    chips=([m for m,dev in build_mini.DEVICES.items()
            if dev.get('dual_compact_enabled', True)] if args.all else [args.mcu])
    if not args.all and not build_mini.DEVICES[args.mcu].get('dual_compact_enabled',True):
        p.error(f'{args.mcu}: Compact disabled for 1024B minimum hardware Boot; build FULL with build_dual.py')
    good={}; errors={}
    with ThreadPoolExecutor(max_workers=max(1,min(12,args.jobs))) as pool:
        futures={pool.submit(run_one,chip,args):chip for chip in chips}
        for fut in as_completed(futures):
            chip,ok,data=fut.result()
            if ok:
                good[chip]=data
                print(f'OK {chip}: {data["boot_bytes"]} B, code {data["code_bytes"]} B, source build, '
                      f'{"SPM ABI" if data["app_spm"] else "direct SPM"}',flush=True)
            else:
                errors[chip]=data
                print(f'FAIL {chip}: {data}',file=sys.stderr,flush=True)
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    summary={'total':len(chips),'passed':len(good),'failed':len(errors),'silicon_tested':False,
             'source_file':'optiboot_mini.S','source_only':True,'firmware':good,'errors':errors}
    (out/'matrix.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(f'RESULT: {len(good)}/{len(chips)} builds directly from source')
    return 1 if errors else 0

if __name__=='__main__':
    sys.exit(main())
