#!/usr/bin/env python3
"""Build the single-section AVR assembly using clang and llvm-objcopy.
No AVR linker or avr-libc required: all local relocations are resolved in assembly.
"""
import argparse
import re
import subprocess
from pathlib import Path

ROOT = (Path(__file__).resolve().parents[4] / "optiboot/bootloaders/optiboot_328p/history/02_368_protocol_audit")

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
    src = ROOT / (name + '.S')
    obj = ROOT / (name + '.o')
    binary = ROOT / (name + '.bin')
    ihex = ROOT / (name + '.hex')
    subprocess.run(['clang', '-target', 'avr', '-mmcu=atmega328p', '-c', str(src), '-o', str(obj)], check=True)
    rel = run('readelf', '-r', obj)
    if 'There are no relocations in this file' not in rel:
        raise RuntimeError('Assembly has unresolved relocations: '+rel)
    syms = run('readelf','-s',obj)
    matches=re.findall(r'^\s*\d+:\s+([0-9a-f]+)\s+\d+\s+NOTYPE\s+GLOBAL.*\s_code_end$',syms,re.M)
    if len(matches)!=1: raise RuntimeError('Unable to find _code_end in symbol table')
    n=int(matches[0],16)
    if n>510: raise RuntimeError(f'Bootloader {n} bytes > 510 bytes available!')
    subprocess.run(['llvm-objcopy', '-O','binary','-j','.text',str(obj),str(binary)],check=True)
    data=binary.read_bytes()
    assert len(data)==512, len(data)
    assert data[n:510]==b'\xff'*(510-n)
    assert data[510:]==bytes((3,8))
    ihex.write_text(make_ihex(data))
    run('llvm-objdump','-dr',obj)
    print(f'{name}: code={n}B, version=2B, occupied={n+2}/512B, saved={474-n-2}B vs upstream HEX')
    return n

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('names',nargs='*',default=['optiboot_mini328'])
    for name in ap.parse_args().names:build(name)
