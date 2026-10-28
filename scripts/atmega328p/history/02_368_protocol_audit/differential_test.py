#!/usr/bin/env python3
"""Machine-code differential test: Optiboot official 8.3 ATmega328P .hex vs mini assembly.
The AVR interpreter is deliberately incomplete and abstracts UART/timer/watchdog.
All commands are run by executing actual AVR instructions from both firmware images.
This checks payload parsing, wire reply bytes/order, Flash content, WDT configuration.
"""
from test_emulator import AVR
from pathlib import Path
import random

R=(Path(__file__).resolve().parents[4] / "optiboot/bootloaders/optiboot_328p/history/02_368_protocol_audit")
ORIG=(R/'upstream_reference.bin').read_bytes()
assert len(ORIG)==512 and ORIG[-2:]==b'\x03\x08'
STK={0x41,0x42,0x45,0x55,0x56,0x64,0x74,0x75,0x51}

def init(binary,orig):
    a=AVR(binary,mcusr=2)
    pat=bytes.fromhex('8091c00087ff' if orig else '2091c00027ff')
    pos=binary.find(pat)
    assert pos>=0, 'No RX loop detected'
    a.rxwait_pc=0x7e00+pos
    for i in range(15000):
        if a.pc==a.rxwait_pc:
            break
        a.step()
    else:
        raise RuntimeError(f'Boot did not initialize, pc={a.pc:#x}')
    assert a.io[0x60]==0x0e, f'Watchdog reset 1s should be on, got {a.io[0x60]:#02x}'
    return a

def run(name):
    small=(R/(name+'.bin')).read_bytes()
    ref,mini=init(ORIG,True),init(small,False)
    rng=random.Random(0xB00C)
    cmds=0; bytes_tested=0
    def pair(pkt,description=''):
        nonlocal cmds,bytes_tested
        cmds+=1;bytes_tested+=len(pkt)
        try:
            x=ref.send(pkt)
            y=mini.send(pkt)
        except Exception as e:
            raise AssertionError(f'{description} packet={pkt[:32].hex()} (len={len(pkt)}): {e}') from e
        if x!=y: raise AssertionError(f'RESPONSE DIFFERENCE {description}: got={y.hex()[:100]} ref={x.hex()[:100]}')
        return x
    # Common commands, various arbitrary GET_PARAMETER values.
    for code in range(256):
        if code not in STK:
            assert pair(bytes((code,0x20)), f'no-args {code:#x}')==b'\x14\x10'
    for param in range(256):
        expected=8 if param==0x81 else 3
        assert pair(bytes((0x41,param,0x20)),f'parameter {param:#x}')==bytes((0x14,expected,0x10))
    for _ in range(12):
        assert pair(b'B'+rng.randbytes(20)+b' ','SET_DEVICE')==b'\x14\x10'
        assert pair(b'E'+rng.randbytes(5)+b' ','SET_DEVICE_EXT')==b'\x14\x10'
        assert pair(b'V'+rng.randbytes(4)+b' ','UNIVERSAL')==b'\x14\x00\x10'
    assert pair(b'u ','READ_SIGN')==b'\x14\x1e\x95\x0f\x10'
    assert pair(b'P ','ENTER_PROGMODE')==b'\x14\x10'
    # Random full/partial Flash page write/read with 128-byte page semantics.
    for adr,length in [(0x0000,128),(0x0080,128),(0x0300,2),(0x0480,8),(0x0680,64),(0x0c00,126),(0x7d80,128)]:
        payload=rng.randbytes(length)
        assert pair(bytes((0x55,(adr>>1)&255,(adr>>9)&255,0x20)),f'LOAD {adr:#04x}')==b'\x14\x10'
        assert pair(bytes((0x64,0,length,ord('F')))+payload+b' ',f'PROG {adr:#04x}')==b'\x14\x10'
        assert ref.flash[:0x7e00]==mini.flash[:0x7e00], f'Flash differs after writing {adr:#x}'
        assert pair(bytes((0x74,0,length,ord('F'),0x20)),f'READ {adr:#04x}')==b'\x14'+payload+b'\x10'
        # Reference GETLENGTH ignores high length byte on this MCU.
        assert pair(bytes((0x74,1,length,ord('F'),0x20)),f'READ(high=1) {adr:#04x}')==b'\x14'+payload+b'\x10'
    # The stock official HEX ignores memory-type 'E' for READ_PAGE, returning Flash.
    assert pair(b't\x00\x08E ', 'READ_PAGE EEPROM type')==b'\x14'+bytes(ref.flash[0x7d80:0x7d88])+b'\x10'
    # Zero read length: original do..while semantics return 256 bytes.
    assert pair(b'U\x00\x00 ', 'LOAD 0')==b'\x14\x10'
    zero_read=pair(b't\x00\x00F ', 'READ_PAGE length=0')
    assert len(zero_read)==258, len(zero_read)
    # Full 128-byte length with ignored nonzero high for PROG_PAGE.
    assert pair(b'U\x00\x20 ', 'LOAD high byte')==b'\x14\x10'
    payload=rng.randbytes(128)
    assert pair(b'd\x03\x80F'+payload+b' ', 'PROG_PAGE high=3')==b'\x14\x10'
    assert ref.flash[:0x7e00]==mini.flash[:0x7e00]
    assert pair(b'Q ', 'LEAVE_PROGMODE')==b'\x14\x10'
    assert ref.io[0x60]==mini.io[0x60]==0x08
    print(f'PASS {name}: {cmds} machine-code commands, {bytes_tested} RX bytes; '
          f'FLASH-identical; replies-identical; WDT 0x0E/0x08; '
          f'original={ref.cycles},mini={mini.cycles} instructions')

def error_case(name,orig,packet,first_reply,expected_wdt):
    a=init(ORIG if orig else (R/(name+'.bin')).read_bytes(),orig)
    a.rx.extend(packet)
    image=ORIG if orig else (R/(name+'.bin')).read_bytes()
    errloops={0x7e00+i for i in range(len(image)-1) if image[i:i+2]==bytes.fromhex('ffcf')}
    for i in range(200000):
        a.step()
        if a.pc in errloops:
            break
    else:
        raise AssertionError('Error handler never reached: '+name+' '+packet[:5].hex())
    assert bytes(a.tx)==first_reply, f'error response={a.tx} expected={list(first_reply)}'
    assert a.io[0x60]==expected_wdt,(name,hex(a.io[0x60]),expected_wdt)
    assert a.erase_count==0
    return a

def check_reset_and_framing(name):
    image=(R/(name+'.bin')).read_bytes()
    for orig,binary in [(True,ORIG),(False,image)]:
        for mcusr in [0,1,2,3,4,8,9,10,11]:
            a=AVR(binary,mcusr)
            should_enter=mcusr==0 or ((mcusr&0x0a)==0x02)
            for _ in range(15000):
                a.step()
                if a.app_started or a.pc==0x7e00+binary.find(bytes.fromhex('8091c00087ff' if orig else '2091c00027ff')):
                    break
            else:raise AssertionError(f'MCUSR startup timeout {name} mcusr={mcusr}')
            assert a.app_started != should_enter, f'MCUSR={mcusr}: incorrect startup route'
            if a.app_started:
                assert a.reg[2]==mcusr, f'MCUSR={mcusr}: R2 not passed to app'
                assert a.io[0x60]==0, f'MCUSR={mcusr}: WDT not disabled before app'
            else:
                assert a.io[0x60]==0x0e, f'MCUSR={mcusr}: boot WDT 1s not enabled'
        a=init(binary,orig)
        a.io[0xc0]=a.io.get(0xc0,0)|0x10  # FE0 framing error
        count=a.wdr_count
        assert a.send(b'0 ')==b'\x14\x10'
        assert a.wdr_count==count, 'Framing error incorrectly feeds watchdog'
        a.io[0xc0]&=~0x10
        assert a.send(b'0 ')==b'\x14\x10'
        assert a.wdr_count==count+2, 'Valid UART bytes must feed watchdog'
    print(f'PASS {name}: reset routing 9 MCUSR states; FE0 gating of watchdog for both firmware images')

def check_malformed(name):
    # Both must reject malformed EOP without sending INSYNC.
    for orig in (True,False):
        error_case(name,orig,b'0\x00',b'',0x08)
        error_case(name,orig,b't\x00\x08F\x00',b'',0x08)
        error_case(name,orig,b'd\x00\x08F'+bytes(range(8))+b'\x00',b'',0x08)
    # Unsupported EEPROM WRITE sends INSYNC, then waits 1s for WDT (no OK).
    for orig in (True,False):
        error_case(name,orig,b'd\x00\x08E'+bytes(range(8))+b' ',b'\x14',0x0e)
    print(f'PASS {name}: EOP reject, EEPROM WRITE unsupported behavior and WDT')

if __name__=='__main__':
    for name in ['optiboot_mini328_final','optiboot_mini328_final_tiny']:
        run(name)
        check_malformed(name)
        check_reset_and_framing(name)
