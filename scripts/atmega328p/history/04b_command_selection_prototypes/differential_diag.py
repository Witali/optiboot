#!/usr/bin/env python3
"""Differential firmware-code test for LEGACY/unchanged STK500v1 operations.
It executes AVR instructions of the original official Optiboot HEX and
this experimental diagnostics variant in a deliberately limited interpreter.
New protocol features have their own tests in test_diag.py.
"""
from pathlib import Path
from avr_base_sim import AVR
from test_diag import DiagAVR, init as init_diag
import random
D=(Path(__file__).resolve().parents[4] / "optiboot/bootloaders/optiboot_328p/history/04b_command_selection_prototypes")
U=(D/'upstream_reference.bin').read_bytes()

def init_orig():
    a=AVR(U,mcusr=2)
    pat=bytes.fromhex('8091c00087ff')
    loc=U.find(pat)
    assert loc>=0
    a.rxwait_pc=0x7e00+loc
    for _ in range(15000):
        if a.pc==a.rxwait_pc:break
        a.step()
    else:raise AssertionError('Original did not reach receive')
    return a

def check(name):
    ref=init_orig();a=init_diag(name)
    rng=random.Random(0xABCD)
    count=0
    def compare(pkt):
        nonlocal count
        response_ref=ref.send(pkt)
        response_a=a.send(pkt)
        assert response_ref==response_a,(name,pkt[:20].hex(),response_ref[:50].hex(),response_a[:50].hex())
        assert ref.flash[:0x7e00]==a.flash[:0x7e00], 'Flash contents differ'
        count+=1
        return response_a
    for i in range(256):
        compare(bytes((0x41,i,0x20)))
    for _ in range(10):
        compare(b'B'+rng.randbytes(20)+b' ')
        compare(b'E'+rng.randbytes(5)+b' ')
        compare(b'V'+bytes((0x00,0x00,0x00,0x00))+b' ')
    compare(b'P ')
    compare(b'u ')
    noargs={0x41,0x42,0x45,0x55,0x56,0x64,0x74,0x75,0x51,0x40,0x31}
    for i in range(256):
        if i not in noargs:
            compare(bytes((i,0x20)))
    for address,length in [(0,128),(0x80,128),(0x600,16),(0x700,64),(0x7d80,128)]:
        data=rng.randbytes(length)
        compare(bytes((0x55,(address>>1)&255,(address>>9)&255,0x20)))
        compare(bytes((0x64,0,length,ord('F')))+data+b' ')
        compare(bytes((0x74,0,length,ord('F'),0x20)))
        assert a.flash[address:address+length]==data
    compare(b'Q ')
    assert a.io[0x60]==ref.io[0x60]==8
    print(f'PASS {name}: {count} legacy commands, byte-identical responses and Flash, matching WDT leave')

if __name__=='__main__':
    for name in ('optiboot_328_diag','optiboot_328_diag_signon'):
        check(name)
