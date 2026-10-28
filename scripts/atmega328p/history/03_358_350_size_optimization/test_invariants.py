#!/usr/bin/env python3
"""Static AVR binary checks plus negative boot-write test (no physical hardware)."""
from pathlib import Path
from test_emulator import AVR
from differential_test import init

ROOT=(Path(__file__).resolve().parents[4] / "optiboot/bootloaders/optiboot_328p/history/03_358_350_size_optimization")

def check(name):
    b=(ROOT/(name+'.bin')).read_bytes()
    assert len(b)==512 and b[-2:]==b'\x03\x08'
    locs=[i for i in range(0,510,2) if b[i:i+2]==bytes.fromhex('e895')]
    assert len(locs)==3, f'{name} expected 3 SPM sites, got {locs}'
    for off in locs:
        op=int.from_bytes(b[off-2:off], 'little')
        assert op & 0xf800 == 0xb800, (hex(off), hex(op))
        port=(op&0xf)|((op>>5)&0x30)
        assert port==0x37, f'SPMCSR must be written immediately before SPM, got port={port:#x}'
    # WDTCSR two consecutive 2-cycle STS accesses after WDCE|WDE write.
    pat=bytes.fromhex('2093600010936000')
    assert pat in b, f'{name}: watchdog reconfiguration window violated'
    # Program tries to write boot area; protection must reject before page erase.
    a=init(b,False)
    assert a.send(b'U\x00\x3f ')==b'\x14\x10'
    orig=b[:]
    a.rx.extend(b'd\x00\x08F'+bytes(range(8))+b' ')
    fail_pc=0x7e00+b.index(bytes.fromhex('ffcf'))
    for _ in range(50000):
        a.step()
        if a.pc==fail_pc:break
    else:raise AssertionError('No guard on boot page write')
    assert a.erase_count==0 and a.write_count==0
    assert a.flash[0x7e00:]==orig
    assert a.tx[-1:]==[0x14], a.tx
    assert a.io[0x60]==0x08
    print(f'PASS {name}: 3 SPM timing windows; 4-cycle WDT window; boot-area protection; version 8.3')

if __name__=='__main__':
    for n in ('optiboot_mini328_final','optiboot_mini328_final_tiny','optiboot_mini328_reset_only_350'):
        check(n)
