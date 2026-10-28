#!/usr/bin/env python3
"""Opcode-level regression for Optiboot Mini EEPROM R/W.

Executes the *assembled* machine code via avr_base_sim.py. A custom EEPROM
peripheral checks EECR/EEAR/EEDR strobes and simulates EEPROM busy polling.
This is a narrow emulator, NOT a cycle-accurate or hardware verification.
"""
from avr_base_sim import AVR
from pathlib import Path
import random
import sys

D=(Path(__file__).resolve().parents[4] / "optiboot/bootloaders/optiboot_328p/history/07_512_datasheet_audit")
BOOT=(D/'optiboot_328_verified.bin').read_bytes()
BASE=(D/'optiboot_mini328_358.bin').read_bytes()
SEED=0x3280A5

class EEAVR(AVR):
    def __init__(self, boot=BOOT, mcusr=2):
        super().__init__(boot,mcusr)
        self.eeprom=bytearray(b'\xFF'*1024)
        self.eewrites=[]
        self.eereads=0
        self.armed_at=None
        self.busy_polls=0

    def io_read(self,addr):
        if addr==0x3F:  # EECR, mapped I/O address=0x1F
            state=self.io.get(0x3F,0)&~0x07
            if self.armed_at is not None and self.cycles-self.armed_at<4: state|=4
            if self.busy_polls>0:
                self.busy_polls-=1
                state|=2
            return state
        return super().io_read(addr)

    def io_write(self,addr,val):
        if addr==0x3F:
            # EECR bits: EERE=0, EEPE=1, EEMPE=2
            eear=(self.io.get(0x41,0)|(self.io.get(0x42,0)<<8))
            assert 0<=eear<1024,('out of range EEPROM',hex(eear))
            if val&1:
                assert not self.busy_polls,('EEPROM read while busy',self.busy_polls)
                self.io[0x40]=self.eeprom[eear]
                self.eereads+=1
            if val&4 and self.armed_at is None:
                assert not self.busy_polls,('EEPROM arm while busy',self.busy_polls)
                self.armed_at=self.cycles
            if val&2:
                assert self.armed_at is not None and self.cycles-self.armed_at<=4, 'EEPE too late / missing EEMPE'
                assert self.io.get(0x57,0)&1==0, 'EEPE during Flash SPM'
                assert (self.io.get(0x3F,0)&0x30)==0, 'EEPROM must be in atomic erase+write mode'
                data=self.io.get(0x40,0)
                self.eeprom[eear]=data
                self.eewrites.append((eear,data))
                self.armed_at=None
                # Model an EEPROM write lasting multiple polls (not real timing).
                self.busy_polls=5
            self.io[0x3F]=val&~7
            return
        return super().io_write(addr,val)

    def step(self):
        op=self.u16(self.pc)
        if (op&0xFF00)==0x9800: # CBI: clear a bit in a low I/O register
            addr=0x20+((op>>3)&0x1F)
            bit=op&7
            self.io_write(addr,self.io_read(addr)&~(1<<bit))
            self.cycles+=1
            self.pc=(self.pc+2)&0x7FFF
            return
        if (op&0xFF00)==0x9900: # SBIC (skip if bit clear)
            addr=0x20+((op>>3)&0x1F)
            bit=op&7
            skip=not(self.io_read(addr)&(1<<bit))
            newpc=self.pc+2
            if skip:
                nextop=self.u16(self.pc+2)
                newpc+=4 if ((nextop&0xFE0F in (0x9000,0x9200)) or nextop==0x940C) else 2
            self.cycles+=1
            self.pc=newpc&0x7FFF
            return
        return super().step()

def init(boot=BOOT,mcusr=2):
    sim=EEAVR(boot,mcusr=mcusr)
    needle=bytes.fromhex('2091c00027ff')
    idx=boot.find(needle)
    assert idx>=0,'Cannot locate UART input polling opcode'
    sim.rxwait_pc=0x7e00+idx
    for _ in range(5000):
        if sim.pc==sim.rxwait_pc:break
        sim.step()
    else:raise AssertionError('Did not start UART loop')
    assert sim.io[0x60]==0x0E,'WDT must have 1s timeout'
    return sim

def pkt_load(byte_address):
    assert byte_address%2==0
    w=byte_address//2
    return bytes((0x55,w&255,w>>8,0x20))

def pkt_read(n,typ=b'E'):
    return b't'+bytes((n>>8,n&255))+typ+b' '

def pkt_write(data,typ=b'E'):
    return b'd'+bytes((len(data)>>8,len(data)&255))+typ+data+b' '

def do(sim,packet,answer):
    got=sim.send(packet)
    assert got==answer,(packet[:20].hex(),got[:60].hex(),answer[:60].hex())

def error_packet_must_not_write(packet,prefix=(),limit=150000):
    a=init()
    for msg in prefix:
        assert a.send(msg)==b'\x14\x10'
    before=a.eeprom[:]
    a.rx.extend(packet)
    writes0=len(a.eewrites)
    for _ in range(limit):
        if a.io[0x60]==8: # protocol_error -> WDT reset; RX may retain rejected payload
            break
        a.step()
    else:raise AssertionError('Bad packet did not enter protocol_error before timeout')
    assert a.eeprom==before and len(a.eewrites)==writes0


def run():
    print('Test: EEPROM data path with real AVR instructions (simulated peripheral)')
    a=init()
    rng=random.Random(SEED)
    count=0
    def runp(p,r):
        nonlocal count
        do(a,p,r)
        count+=1

    # Confirm the normal avrdude / STK500v1 session, 8.3 SW version, Flash unaffected.
    runp(b'0 ',b'\x14\x10')
    runp(b'A\x81 ',b'\x14\x08\x10')
    runp(b'A\x82 ',b'\x14\x03\x10')
    runp(b'B'+bytes(20)+b' ',b'\x14\x10')
    runp(b'E'+bytes(5)+b' ',b'\x14\x10')
    runp(b'V\x00\x00\x00\x00 ',b'\x14\x00\x10')
    runp(b'u ',b'\x14\x1E\x95\x0F\x10')

    untouched_flash=a.flash[:0x7e00]
    expected=bytearray(a.eeprom)
    # avrdude -c arduino uses LOAD_ADDRESS (word) then 16-byte EEPROM blocks.
    # Exercise the *whole* 1KiB EEPROM and crossing of 256-byte bank boundaries.
    for off in range(0,1024,16):
        payload=rng.randbytes(16)
        runp(pkt_load(off),b'\x14\x10')
        runp(pkt_write(payload),b'\x14\x10')
        expected[off:off+16]=payload
        assert a.eeprom[off:off+16]==payload,('write mismatch',off)
        runp(pkt_load(off),b'\x14\x10')
        runp(pkt_read(16),b'\x14'+payload+b'\x10')
    assert a.eeprom==expected
    assert a.flash[:0x7e00]==untouched_flash,'EEPROM operation changed program Flash'
    assert len(a.eewrites)==1024,'Expected exactly one EEPROM write per byte'
    print('PASS: 64x16B EEPROM writes and 64x16B reads, all 1024 bytes correct')

    # Verify explicit atomic EEPM=00 setup works even when EEPROM modebits start stale.
    weird=init()
    weird.io[0x3F]=0x30
    weird.busy_polls=8  # a previous write still in progress when entering bootloader
    do(weird,pkt_load(0),b'\x14\x10')
    do(weird,pkt_write(b'1234567890123456'),b'\x14\x10')
    assert weird.eeprom[:16]==b'1234567890123456'
    assert weird.io.get(0x3F,0)&0x30==0
    print('PASS: waits for previous EEPROM busy cycle and enforces atomic EEPM=00')

    # Partial length (1..15) packets are accepted at even start addresses.
    for n in range(1,16):
        off=100+n*32  # even for even n only; adjust
        off&=~1
        payload=rng.randbytes(n)
        runp(pkt_load(off),b'\x14\x10')
        runp(pkt_write(payload),b'\x14\x10')
        runp(pkt_load(off),b'\x14\x10')
        runp(pkt_read(n),b'\x14'+payload+b'\x10')
        expected[off:off+n]=payload
    assert a.eeprom==expected
    print('PASS: partial EEPROM packets of lengths 1..15')

    # Read up to 256 bytes per STK_READ_PAGE (zero low length from 0x0100).
    runp(pkt_load(256),b'\x14\x10')
    runp(pkt_read(256),b'\x14'+bytes(expected[256:512])+b'\x10')
    print('PASS: 256-byte EEPROM read (STK length low byte zero)')

    # Bootloader's Flash write path still works, and EEPROM content is untouched.
    flash_data=rng.randbytes(128)
    runp(pkt_load(0x300),b'\x14\x10')
    runp(pkt_write(flash_data,b'F'),b'\x14\x10')
    runp(pkt_load(0x300),b'\x14\x10')
    runp(pkt_read(128,b'F'),b'\x14'+flash_data+b'\x10')
    assert a.flash[0x300:0x380]==flash_data
    assert a.eeprom==expected
    assert a.flash[0x7e00:]==BOOT,'Bootloader section changed'
    runp(b'Q ',b'\x14\x10')
    assert a.io[0x60]==8
    print('PASS: Flash r/w unchanged, bootloader protected, WDT exit correct')

    # All validation errors must leave EEPROM untouched.
    error_packet_must_not_write(pkt_write(bytes(range(16)))[:-1]+b'\x00',prefix=[pkt_load(0)])
    error_packet_must_not_write(pkt_write(b'\x5A'*16),prefix=[pkt_load(0x3F8)])
    error_packet_must_not_write(pkt_write(b'\x5A'*16),prefix=[pkt_load(0x400)])
    error_packet_must_not_write(pkt_write(b'\x5A'*16),prefix=[pkt_load(0xFF00)])
    error_packet_must_not_write(pkt_write(b'\x5A'*17),prefix=[pkt_load(0)])
    error_packet_must_not_write(pkt_write(b''),prefix=[pkt_load(0)])
    print('PASS: invalid EOP, overruns, invalid start addresses, oversized/zero writes => no EEPROM modifications')

    # EEPROM read outside 1KB must not wrap to address zero.
    invalid=init()
    assert invalid.send(pkt_load(0x400))==b'\x14\x10'
    invalid.rx.extend(pkt_read(16))
    for _ in range(150000):
        if invalid.io[0x60]==8:break
        invalid.step()
    else:raise AssertionError('EEPROM out-of-range read did not reject')
    assert invalid.eereads==0,'Invalid read accessed EEPROM peripheral'
    print('PASS: EEPROM out-of-range reads rejected without accessing EEPROM')

    # Truncated input must never start EEPROM write before CRC_EOP validation.
    bad=init()
    assert bad.send(pkt_load(0))==b'\x14\x10'
    bad.rx.extend(pkt_write(b'1234567890123456')[:-1])
    for _ in range(10000):
        if not bad.rx and bad.pc==bad.rxwait_pc:break
        bad.step()
    else:raise AssertionError('Truncated packet did not stop at receive polling')
    assert bad.eewrites==[]
    print('PASS: truncated packet cannot write EEPROM')

    for cause in (1,8):
        b=EEAVR(BOOT,mcusr=cause)
        for _ in range(500):
            b.step()
            if b.app_started:break
        assert b.app_started,('Failed to start app after reset',cause)
    print('PASS: power-on/watchdog reset app entry')

    # Differential comparison on unaffected serial protocol with previous 358B version.
    b=init(BASE)
    c=init(BOOT)
    for i in range(256):
        packet=bytes((0x41,i,0x20))
        assert b.send(packet)==c.send(packet),(i,'GET_PARAMETER changed')
        count+=1
    for off in (0,0x80,0x600,0x7d80):
        payload=rng.randbytes(128)
        for packet in (pkt_load(off),pkt_write(payload,b'F'),pkt_read(128,b'F')):
            assert b.send(packet)==c.send(packet),('Flash command response mismatch',off,packet[:1])
            assert b.flash[:0x7e00]==c.flash[:0x7e00],('Application Flash content mismatch',off)
            count+=1
    print('PASS: 268 differential legacy commands vs previous 358-byte build')
    print('TOTAL:',count,'complete valid command-response transactions plus negative tests')

if __name__=='__main__':
    run()
