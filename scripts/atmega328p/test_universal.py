#!/usr/bin/env python3
"""Regression for assembled AVR with software fuse/lock LPM emulator.

The emulator models the read-only BLBSET|SPMEN LPM path, not exact timing.
EEPROM/Flash transitions and STK500 framing tested against real AVR opcodes.
"""
from pathlib import Path
from test_eeprom import EEAVR, pkt_load, pkt_write, pkt_read, BOOT
from random import Random

HERE = (Path(__file__).resolve().parents[2] / "optiboot/bootloaders/optiboot_328p")
FW = BOOT

FUSE = {0:0x62, 1:0xE7, 2:0xF9, 3:0xD2}

class UniversalAVR(EEAVR):
    def __init__(self, boot=FW, mcusr=2):
        super().__init__(boot,mcusr)
        self.fuse_reads = []
        self.fuse_arm_at = None
        self.fuse_values = dict(FUSE)

    def io_write(self,addr,val):
        if addr==0x57 and val==0x09:
            self.fuse_arm_at = self.cycles
        return super().io_write(addr,val)

    def step(self):
        op = self.u16(self.pc)
        if op & 0xfe0f == 0x9004: # LPM Rd, Z
            rd = (op>>4) & 31
            assert self.io.get(0x57)==0x09, 'Expected BLBSET|SPMEN before LPM'
            assert self.fuse_arm_at is not None and self.cycles - self.fuse_arm_at <= 3, 'LPM too late after SPMCSR write'
            z = self.z()
            assert z in self.fuse_values, f'Reserved fuse/lock Z address {z}'
            self.reg[rd] = self.fuse_values[z]
            self.fuse_reads.append((z,self.reg[rd]))
            self.io[0x57] = 0    # hardware autoclears bits following LPM
            self.fuse_arm_at = None
            self.cycles += 3
            self.pc = (self.pc + 2) & 0x7fff
            return
        return super().step()

def init():
    a = UniversalAVR()
    needle=bytes.fromhex('2091c00027ff')
    off=FW.find(needle)
    assert off!=-1
    a.rxwait_pc=0x7e00 + off
    for _ in range(1000):
        if a.pc==a.rxwait_pc:break
        a.step()
    else:raise AssertionError('Boot failed')
    assert a.io[0x60]==0x0e
    return a

def cmd_univ(a,op,second,third=0,fourth=0):
    packet=bytes([0x56,op,second,third,fourth,0x20])
    reply=a.send(packet)
    assert reply[0]==0x14 and reply[-1]==0x10 and len(reply)==3,reply
    return reply[1]

def run():
    a=init()
    for (op,second,z) in ((0x50,0x00,0),(0x58,0x00,1),(0x50,0x08,2),(0x58,0x08,3)):
        for third in (0,1,0xff):
            for fourth in (0,0x5a):
                v=cmd_univ(a,op,second,third,fourth)
                assert v==FUSE[z],(op,second,third,fourth,v,FUSE[z])
    print('PASS: 24 hardware-like BLBSET+LPM reads: low/high/extended fuses and lock bits')
    assert len(a.fuse_reads)==24
    assert a.io[0x57]==0,'SPMCSR not cleared by LPM'
    for opcode in range(256):
        if opcode in (0x50,0x58):continue
        assert cmd_univ(a,opcode,0)==0,(opcode,'unexpected nonzero')
    for subcode in range(256):
        if subcode in (0,8):continue
        assert cmd_univ(a,0x50,subcode)==0,(subcode,'unexpected nonzero')
        assert cmd_univ(a,0x58,subcode)==0,(subcode,'unexpected nonzero')
    print('PASS: 762 unsupported UNIVERSAL queries return 0x00')
    for cmd in ((0xac,0xa0,0x12,0x34),(0xac,0xa8,0,0),(0x30,0,1,0)):
        assert cmd_univ(a,*cmd)==0
    assert a.fuse_values==FUSE
    print('PASS: fuse writes, lock writes and 0x30 signature request do not change memory')
    assert a.send(b'u ')==bytes.fromhex('141e950f10')
    rng=Random(0x42fa)
    for address in range(0,1024,16):
        data=rng.randbytes(16)
        assert a.send(pkt_load(address))==b'\x14\x10'
        assert a.send(pkt_write(data))==b'\x14\x10'
        assert a.send(pkt_load(address))==b'\x14\x10'
        assert a.send(pkt_read(16))==b'\x14'+data+b'\x10'
    assert a.eeprom[0:16]!=bytes([255]*16)
    print('PASS: EEPROM 1 KiB roundtrip immediately following UNIVERSAL reads')
    data=rng.randbytes(128)
    assert a.send(pkt_load(0x0200))==b'\x14\x10'
    assert a.send(pkt_write(data,b'F'))==b'\x14\x10'
    assert a.flash[0x200:0x280]==data
    assert a.send(pkt_load(0x0200))==b'\x14\x10'
    assert a.send(pkt_read(128,b'F'))==b'\x14'+data+b'\x10'
    assert a.flash[0x7e00:]==FW
    print('PASS: Flash SPM erase/fill/write/verify following UNIVERSAL, unchanged boot sector')
    # Protocol error, before fuse LPM: no fuse access, WDT set to 16ms
    b=init()
    b.rx.extend(bytes((0x56,0x50,0,0,0,0x00)))
    for i in range(20000):
        b.step()
        if b.io.get(0x60)==8:break
    else:raise AssertionError('Bad EOP did not trigger protocol error')
    assert b.fuse_reads==[]
    print('PASS: bad EOP prevents all UNIVERSAL side effects')
    print('TOTAL: 24 fuse/lock reads, 762 unsupported requests, 256 EEPROM transactions, Flash regression and negative tests')

if __name__=='__main__':run()
