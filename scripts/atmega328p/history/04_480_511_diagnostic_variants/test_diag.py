#!/usr/bin/env python3
"""Tests experimental protocol extension by executing AVR opcodes in a limited simulator.
The simulator is not a physical/microarchitecturally complete ATmega328P model.
"""
from avr_base_sim import AVR
from pathlib import Path
import random
import sys

DIR=(Path(__file__).resolve().parents[4] / "optiboot/bootloaders/optiboot_328p/history/04_480_511_diagnostic_variants")

class DiagAVR(AVR):
    def __init__(self, boot, mcusr=2):
        super().__init__(boot, mcusr)
        self.eeprom=bytearray((i*71+3)&255 for i in range(1024))
        self.fuse=[0xFF,0xFF,0xFD,0xDE]   # low, lock, ext, high
        self.sig=[0x1E,0,0x95,0,0x0F]  # Z=0,2,4
    def io_write(self,addr,val):
        if addr==0x3F and (val &1):   # EECR.EERE triggers sample
            eaddr = (self.io.get(0x41,0) | (self.io.get(0x42,0)<<8))&0x3ff
            self.io[0x40]=self.eeprom[eaddr]
            self.io[0x3f]=val & ~1
            return
        super().io_write(addr,val)
    def step(self):
        op=self.u16(self.pc)
        if op&0xff00==0x9900: # SBIC (not present in base interpreter)
            addr=0x20+((op>>3)&0x1f)
            bit=op&7
            self.cycles+=1
            skip=not(self.io_read(addr)&(1<<bit))
            self.pc=(self.pc+2+(2 if skip else 0)) & 0x7fff
            return
        if op&0xfe0f==0x9004: # LPM Rd,Z (special fuses/sig mode)
            rd=(op>>4)&0x1f
            if self.io.get(0x57,0)==0x09:
                assert self.z()<4, ('bad fuse pointer',self.z())
                self.reg[rd]=self.fuse[self.z()]
            elif self.io.get(0x57,0)==0x21:
                assert self.z() in (0,2,4)
                self.reg[rd]=self.sig[self.z()]
            else:
                self.reg[rd]=self.flash[self.z()]
            self.io[0x57]=0
            self.cycles+=1
            self.pc=(self.pc+2)&0x7fff
            return
        return super().step()

def init(name='optiboot_328_diag'):
    img=(DIR/(name+'.bin')).read_bytes()
    a=DiagAVR(img)
    pat=bytes.fromhex('2091c00027ff')
    loc=img.find(pat)
    assert loc>=0
    a.rxwait_pc=0x7e00+loc
    for _ in range(5000):
        if a.pc==a.rxwait_pc:break
        a.step()
    else:raise AssertionError('Boot did not reach input poll')
    return a

def check(name='optiboot_328_diag'):
    a=init(name)
    count=0
    def run(packet,expected):
        nonlocal count
        res=a.send(packet)
        assert res==expected,(packet.hex(),res.hex(),expected.hex())
        count+=1
    run(b'0 ',b'\x14\x10')
    if name.endswith('_signon'):
        run(b'1 ',b'\x14AVR STK\x10')
    run(b'A\x81 ',b'\x14\x08\x10')
    run(b'@\x81\x17 ',b'\x14\x10')
    run(b'B'+bytes(20)+b' ',b'\x14\x10')
    run(b'E'+bytes(5)+b' ',b'\x14\x10')
    run(b'P ',b'\x14\x10')
    run(b'u ',b'\x14\x1e\x95\x0f\x10')
    run(b'V\x50\x00\x00\x00 ',b'\x14\xff\x10') # low fuse
    run(b'V\x50\x08\x00\x00 ',b'\x14\xfd\x10') # ext fuse
    run(b'V\x58\x00\x00\x00 ',b'\x14\xff\x10') # lock
    run(b'V\x58\x08\x00\x00 ',b'\x14\xde\x10') # high fuse
    for i,b in enumerate((0x1e,0x95,0x0f)):
        run(bytes((0x56,0x30,0x00,i,0x00,0x20)),bytes((0x14,b,0x10)))
    run(b'V\x30\x00\x03\x00 ',b'\x14\x00\x10')  # out of range
    run(b'V\xac\xa0\x00\x00 ',b'\x14\x00\x10')  # fuse write cannot be emulated
    run(b'V\x58\x08\x01\x00 ',b'\x14\x00\x10')  # invalid read syntax
    # EEPROM correct address path: avrdude 328P LOAD_ADDRESS 0x0100 -> EEPROM 0x0200
    run(b'U\x00\x01 ',b'\x14\x10')
    run(b't\x00\x10E ',b'\x14'+bytes(a.eeprom[512:528])+b'\x10')
    run(b't\x00\x10F ',b'\x14'+bytes(a.flash[512:528])+b'\x10')
    assert a.io[0x41]==(512+15)&255
    assert a.io[0x42]==2
    run(b'U\x00\x00 ',b'\x14\x10')
    data=random.Random(1234).randbytes(128)
    run(bytes((0x64,0,128,ord('F')))+data+b' ',b'\x14\x10')
    run(bytes((0x74,0,128,ord('F'),0x20)),b'\x14'+data+b'\x10')
    assert a.flash[:128]==data
    assert a.eeprom == bytes((i*71+3)&255 for i in range(1024))
    # SET_PARAMETER consumes two payload bytes and preserves command framing.
    run(b'@\x80\xfe ',b'\x14\x10')
    run(b'0 ',b'\x14\x10')
    run(b'Q ',b'\x14\x10')
    print(f'PASS: {count} interactions; {a.cycles} simulated instructions; EEPROM read, fuses, lock, signature, legacy flash P/R and WDT verified')

if __name__=='__main__':
    for name in sys.argv[1:] or ['optiboot_328_diag','optiboot_328_diag_signon']:
        print(name)
        check(name)
