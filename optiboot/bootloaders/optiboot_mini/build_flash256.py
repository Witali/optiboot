#!/usr/bin/env python3
"""Build the experimental Flash-only STK500v1 subset in 256B Boot sections.

Same optiboot_mini.S source, device and USART includes as Compact/Full.
Only the mini256 branch is selected by MINI_FLASH_ONLY_256=1.
Never use this profile for EEPROM, flash read-back or application SPM.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import build_mini

ROOT=Path(__file__).resolve().parent
TARGETS=tuple(k for k,v in build_mini.DEVICES.items() if
    v['flash'] in (8192,16384) and v['page'] in (64,128) and
    v['profile'] in ('modern','legacy') and not v.get('virtual_boot') and
    (2048//8)==256)


def one(mcu, dest, f_cpu=16000000, baud=115200, toolchain='auto'):
    if mcu not in TARGETS:
        raise ValueError('256B hardware Boot not supported by this audited target: '+mcu)
    dev=build_mini.DEVICES[mcu]
    if f_cpu<8000000 or f_cpu>dev['max_mhz']*1000000:
        raise ValueError('F_CPU outside project limit or chip rating')
    u=build_mini.best_baud(f_cpu,baud)
    if abs(u['baud_error_percent'])>2.5:
        raise ValueError('UART baud divider error exceeds 2.5%')
    name,cc,oc,tcflags=build_mini.compiler_tools(toolchain)
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    flags=[*tcflags,'-mmcu='+mcu,'-I',str(ROOT),
        '-DMINI_FLASH_ONLY_256=1','-DBOOT_BYTES=256',
        f'-DF_CPU={f_cpu}',f'-DBAUD_RATE={baud}',
        f'-DMINI_U2X={u["u2x"]}',f'-DMINI_UBRR={u["ubrr"]}']
    obj=dest/(mcu+'.o');raw=dest/(mcu+'.bin')
    subprocess.run([cc,*flags,'-c',str(ROOT/'optiboot_mini.S'),'-o',str(obj)],check=True)
    image_object=build_mini.resolved_image_object(obj)
    subprocess.run([oc,'-O','binary','-j','.text',str(image_object),str(raw)],check=True)
    data=raw.read_bytes()
    symbols=subprocess.check_output(['llvm-objdump','-t',str(obj)],text=True)
    x=re.search(r'^([0-9a-fA-F]+)\s+g\s+\.text\s+\S+\s+_code_end$',symbols,re.M)
    if not x:raise RuntimeError('Missing _code_end symbol')
    used=int(x.group(1),16)
    if len(data)!=256 or used>256 or data[used:]!=b'\xff'*(256-used):
        raise RuntimeError(f'{mcu}: unexpected code/erased payload: {used}, {len(data)}')
    base=dev['flash']-256
    if base%dev['page']:
        raise RuntimeError('Boot origin not page aligned')
    (dest/(mcu+'.hex')).write_text(build_mini.make_hex(data,base))
    result={
        'mcu':mcu,'edition':'flash_only_256','boot_bytes':256,'boot_start':f'0x{base:04X}',
        'boot_word_address':f'0x{base//2:04X}','bootsz1_0_bits':'11',
        'code_bytes':used,'free_bytes':256-used,'page_bytes':dev['page'],'flash_bytes':dev['flash'],
        'signature':''.join(f'{v:02X}' for v in dev['sig']),
        'uart_style':dev['profile'],'f_cpu_hz':f_cpu,'baud':baud,
        'ubrr':u['ubrr'],'u2x':u['u2x'],'baud_error_percent':u['baud_error_percent'],
        'supported': ['STK_GET_SYNC','STK_GET_PARAMETER (constant 3)','STK_SET_DEVICE',
                      'STK_SET_DEVICE_EXT','STK_ENTER_PROGMODE','STK_LOAD_ADDRESS',
                      'STK_PROG_PAGE Flash full page','STK_READ_SIGN','STK_LEAVE_PROGMODE (ACK)'],
        'unsupported': ['STK_READ_PAGE','EEPROM read/write','GET_SIGN_ON','UNIVERSAL',
                        'fuse/lock read/write','application SPM ABI'],
        'avrdude_note':'Only -c arduino -D -V; use flash256/prepare_avrdude_hex.py to pad final page. No read-back verification. Real AVRDUDE and hardware not tested.',
        'watchdog':'1s programming timeout; LEAVE ACK is followed by a configured 16ms watchdog reset',
        'invalid_packet':'Bad EOP before erase triggers watchdog timeout; length fields are not validated, only full-page host packets are supported',
        'code_sha256':hashlib.sha256(data).hexdigest(),
        'source_sha256':hashlib.sha256((ROOT/'flash256'/'flash256.inc').read_bytes()).hexdigest(),
        'simulation_tested':False,'on_silicon_tested':False,'avrdude_host_tested':False
    }
    (dest/(mcu+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mcu',default='atmega8')
    p.add_argument('--all',action='store_true')
    p.add_argument('--list',action='store_true')
    p.add_argument('--f-cpu',type=int,default=16000000)
    p.add_argument('--baud',type=int,default=115200)
    p.add_argument('--toolchain',choices=['auto','clang','gcc'],default='auto')
    p.add_argument('--output-dir',default=str(ROOT/'output'/'flash256'))
    args=p.parse_args()
    if args.list:
        for k in TARGETS:print(k)
        return
    data=[]
    for k in (TARGETS if args.all else (args.mcu,)):
        r=one(k,Path(args.output_dir)/k,args.f_cpu,args.baud,args.toolchain)
        data.append(r)
        print(f'OK {k:11}: {r["code_bytes"]}/256 bytes, {r["page_bytes"]}-B pages, {r["boot_start"]}')
    if args.all:
        (Path(args.output_dir)/'matrix.json').write_text(json.dumps(data,indent=2)+'\n')
        import csv
        with (Path(args.output_dir)/'matrix.csv').open('w',newline='') as f:
            fields=['mcu','code_bytes','free_bytes','boot_start','page_bytes','f_cpu_hz','baud','baud_error_percent','code_sha256']
            c=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');c.writeheader();c.writerows(data)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
