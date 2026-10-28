#!/usr/bin/env python3
"""Byte-for-byte STK500 response comparison with official Optiboot HEX.
Tests only originally implemented semantics; new fuse/lock+EEPROM feature is separate.
"""
from pathlib import Path
from random import Random
from avr_base_sim import AVR
from test_universal import init as init_new
D=(Path(__file__).resolve().parents[4] / "optiboot/bootloaders/optiboot_328p/history/07_512_datasheet_audit")
REF=(D/'upstream_reference.bin').read_bytes()

def init_old():
    s=AVR(REF,2)
    idx=REF.find(bytes.fromhex('8091c00087ff'))
    assert idx>=0
    s.rxwait_pc=0x7e00+idx
    for _ in range(20000):
        if s.pc==s.rxwait_pc:break
        s.step()
    else:raise AssertionError('Official bootloader UART initialization failed')
    return s

def run():
    old,new=init_old(),init_new()
    r=Random(0x1234d1)
    n=0
    def compare(pkt):
        nonlocal n
        a,b=old.send(pkt),new.send(pkt)
        assert a==b,('UART mismatch',pkt[:12].hex(),a[:50].hex(),b[:50].hex())
        assert old.flash[:0x7e00]==new.flash[:0x7e00],('Flash mismatch',pkt[:12].hex())
        n+=1
    for selector in range(256): compare(bytes([0x41,selector,0x20]))
    for _ in range(12):
        compare(b'B'+r.randbytes(20)+b' ')
        compare(b'E'+r.randbytes(5)+b' ')
        compare(b'V\x00\x00\x00\x00 ')
    compare(b'P ')
    compare(b'u ')
    for i in range(256):
        if i in (0x40,0x41,0x42,0x45,0x55,0x56,0x64,0x74,0x75,0x51): continue
        compare(bytes((i,0x20)))
    for address,length in ((0,128),(0x80,128),(0x600,16),(0x700,64),(0x7d80,128)):
        payload=r.randbytes(length)
        compare(bytes([0x55,(address>>1)&255,(address>>9)&255,0x20]))
        compare(bytes((0x64,0,length,ord('F')))+payload+b' ')
        compare(bytes((0x74,0,length,ord('F'),0x20)))
        assert old.flash[address:address+length]==payload
    compare(b'Q ')
    assert old.io[0x60]==new.io[0x60]==8
    print(f'PASS: {n} legacy STK500v1 transactions, identical UART and application Flash')

if __name__=='__main__':run()
