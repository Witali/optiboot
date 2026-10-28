#!/usr/bin/env python3
"""Build the single-section AVR assembly using clang and llvm-objcopy.
LLVM versions emitting local relocations additionally use avr-ld; no avr-libc is required.
"""
import argparse
import re
import shutil
import subprocess
from pathlib import Path

ROOT = (Path(__file__).resolve().parents[2] / "optiboot/bootloaders/optiboot_328p")

def run(*cmd):
    return subprocess.check_output([str(x) for x in cmd], text=True)

def make_ihex(data: bytes, base=0x7E00):
    lines = []
    def line(addr, typ, payload):
        rec = bytes((len(payload), addr >> 8, addr & 255, typ)) + payload
        return ':' + (rec + bytes((-sum(rec) & 255,))).hex().upper()
    for off in range(0, len(data), 16):
        lines.append(line(base + off, 0, data[off:off+16]))
    lines.append(line(0, 1, b''))
    return '\n'.join(lines) + '\n'

def build(name):
    output = ROOT / 'build'
    output.mkdir(exist_ok=True)
    src = ROOT / (name + '.S')
    obj = output / (name + '.o')
    binary = output / (name + '.bin')
    ihex = output / (name + '.hex')
    subprocess.run(['clang', '-target', 'avr', '-mmcu=atmega328p', '-c', str(src), '-o', str(obj)], check=True)
    image_obj = obj
    rel = run('readelf', '-r', obj)
    if 'There are no relocations in this file' not in rel:
        if shutil.which('avr-ld') is None:
            raise RuntimeError('This LLVM assembler emits local relocations; install avr-ld (binutils-avr) to resolve them.')
        image_obj = output / (name + '.elf')
        # Keep section-relative addresses: the image is placed at 0x7E00 by Intel HEX.
        # Do not enable linker relaxation or change the supplied assembly layout.
        subprocess.run(['avr-ld', '-m', 'avr5', '-Ttext=0', '-e', '_start', str(obj), '-o', str(image_obj)], check=True)
        rel = run('readelf', '-r', image_obj)
        if 'There are no relocations in this file' not in rel:
            raise RuntimeError('Linked image has unresolved relocations: '+rel)
    syms = run('readelf','-s',image_obj)
    matches=re.findall(r'^\s*\d+:\s+([0-9a-f]+)\s+\d+\s+NOTYPE\s+GLOBAL.*\s_code_end$',syms,re.M)
    if len(matches)!=1: raise RuntimeError('Unable to find _code_end in symbol table')
    n=int(matches[0],16)
    if n>510: raise RuntimeError(f'Bootloader {n} bytes > 510 bytes available!')
    subprocess.run(['llvm-objcopy', '-O','binary','-j','.text',str(image_obj),str(binary)],check=True)
    data=binary.read_bytes()
    assert len(data)==512, len(data)
    assert data[n:510]==b'\xff'*(510-n)
    if name.endswith('_signon'):
        # GET_SIGN_ON's tiny 7-byte flash table has a fixed Z-pointer at 0x7FF6.
        # If edits ever move the table, fail the build rather than return garbage.
        m=re.findall(r'^\s*\d+:\s+([0-9a-f]+)\s+\d+\s+NOTYPE\s+LOCAL.*\ssignon_text$',syms,re.M)
        assert len(m)==1 and int(m[0],16)==0x1F6, f'SIGNON string moved: {m}; update Z address'
        assert data[0x1F6:0x1FD]==b'AVR STK'
    assert data[510:]==bytes((3,8))
    ihex.write_text(make_ihex(data), encoding='ascii', newline='\n')
    run('llvm-objdump','-dr',image_obj)
    print(f'{name}: code={n}B, version=2B, occupied={n+2}/512B, saved={474-n-2}B vs upstream HEX')
    return n

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('names',nargs='*',default=['optiboot_328_verified'])
    for name in ap.parse_args().names:build(name)
