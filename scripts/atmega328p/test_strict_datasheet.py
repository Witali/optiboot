#!/usr/bin/env python3
"""Strict additional tests of instruction-level firmware against specific
ATmega328P datasheet invariants. Not a silicon-accurate emulator.
"""
from pathlib import Path
from random import Random
from test_universal import UniversalAVR, FW
from test_eeprom import pkt_load, pkt_write, pkt_read

D=(Path(__file__).resolve().parents[2] / "optiboot/bootloaders/optiboot_328p")

# Check exact binary instruction adjacencies, not just assembly text. The AVR
# instructions OUT and LPM/SPM are little-endian encoded two-byte words.
# Conservative timing: immediate successor -> within 3/4 CPU clock windows.
def test_static_instructions():
    b=FW
    assert len(b)==512
    assert b[510:512]==b'\x03\x08'
    assert bytes.fromhex('37bfe895') in b, 'OUT SPMCSR,r19 / SPM must be adjacent'
    assert bytes.fromhex('07bfe895') in b, 'OUT SPMCSR,r16 / SPM must be adjacent'
    assert bytes.fromhex('07bf0491') in b, 'OUT SPMCSR,r16 / LPM r16,Z must be adjacent'
    assert bytes.fromhex('fa9af99a') in b, 'SBI EEMPE / SBI EEPE must be adjacent'
    assert bytes.fromhex('2093600010936000') in b, 'WDTCSR timed writes must be adjacent'
    # Check that the two-byte reset vector dispatches to the boot routine.
    assert b[:2] in (bytes.fromhex('00c0'),),b[:2].hex()

class SiliconChecks(UniversalAVR):
    def __init__(self):
        super().__init__(FW,2)
        self.spm_log=[]
    def spm(self):
        z=self.z()
        cmd=self.io.get(0x57,0)
        if cmd in (3,5):
            assert (z&0x7f)==0, (f'Datasheet: SPM Page Erase/Write Z PCWORD must be 0', hex(z), cmd)
            assert z<0x7e00, 'Cannot write boot section'
        if cmd==1:
            assert (z&1)==0, 'SPM temporary buffer must be word-addressed'
        self.spm_log.append((cmd,z))
        super().spm()

def init():
    a=SiliconChecks()
    off=FW.find(bytes.fromhex('2091c00027ff'))
    assert off>=0
    a.rxwait_pc=0x7e00+off
    for _ in range(20000):
        if a.pc==a.rxwait_pc: break
        a.step()
    else:raise AssertionError('Boot did not enter UART receive')
    return a

def test_flash_paths():
    a=init(); rng=Random(3318)
    for address in (0,0x80,0x100,0x400,0x7d80):
        for length in (2,4,64,126,128):
            data=rng.randbytes(length)
            assert a.send(pkt_load(address))==b'\x14\x10'
            assert a.send(pkt_write(data,b'F'))==b'\x14\x10'
            assert a.flash[address:address+length]==data
            assert a.send(pkt_load(address))==b'\x14\x10'
            assert a.send(pkt_read(length,b'F'))==b'\x14'+data+b'\x10'
    assert a.flash[0x7e00:]==FW
    assert any(cmd==3 for cmd,_ in a.spm_log)
    assert any(cmd==5 for cmd,_ in a.spm_log)
    assert all(z%128==0 for cmd,z in a.spm_log if cmd in (3,5))
    print('PASS: Page Erase/Write always uses Z PCWORD=0, 25 aligned page transactions incl. last app page')

def test_bad_flash_offsets():
    for addr in (2,64,126,0x17e,0x7dfe):
        a=init()
        assert a.send(pkt_load(addr))==b'\x14\x10'
        before=a.flash[:]
        a.rx.extend(pkt_write(b'\x00\x11\x22\x33',b'F'))
        for _ in range(30000):
            if a.io.get(0x60)==8:break
            a.step()
        else:raise AssertionError(f'Bad offset {addr:#x} not rejected')
        assert not a.erase_count and not a.write_count
        assert a.flash==before
    print('PASS: five unaligned page starts rejected *before* SPM without flash damage')

def test_fuse_after_eeprom():
    a=init()
    rng=Random(0x13AE)
    for addr in range(0,1024,16):
        data=rng.randbytes(16)
        assert a.send(pkt_load(addr))==b'\x14\x10'
        assert a.send(pkt_write(data))==b'\x14\x10'
        assert a.send(pkt_load(addr))==b'\x14\x10'
        assert a.send(pkt_read(16))==b'\x14'+data+b'\x10'
    for op,mid,z in ((0x50,0,0),(0x58,0,1),(0x50,8,2),(0x58,8,3)):
        assert a.send(bytes((0x56,op,mid,0,0,0x20)))==bytes((0x14,a.fuse_values[z],0x10))
    print('PASS: full EEPROM 1K roundtrip + all 4 fuse/lock reads after EEPROM finishes')

if __name__=='__main__':
    test_static_instructions()
    print('PASS: EEPROM and SPM timed instruction pairs are adjacent in assembled machine code')
    test_flash_paths()
    test_bad_flash_offsets()
    test_fuse_after_eeprom()
    print('STRICT DATASHEET AUDIT PASS; not a replacement for a hardware test')
