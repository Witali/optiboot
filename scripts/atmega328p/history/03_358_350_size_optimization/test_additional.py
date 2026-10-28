#!/usr/bin/env python3
"""Additional valid protocol comparisons and reset-only UART setup caveat.
This AVR interpreter models instructions and flash *semantics*, not real cycles or UART wire timing.
"""
from pathlib import Path
from differential_test import init,ORIG
from test_emulator import AVR
import random

R=(Path(__file__).resolve().parents[4] / "optiboot/bootloaders/optiboot_328p/history/03_358_350_size_optimization")
names=['optiboot_mini328_final','optiboot_mini328_final_tiny','optiboot_mini328_reset_only_350']

for name in names:
    mini=(R/(name+'.bin')).read_bytes()
    a,b=init(ORIG,True),init(mini,False)
    rng=random.Random(20261028)
    count=0
    for i in range(64):
        # Never cross a physical page boundary, so operations are supported by SPM.
        page=rng.randrange(0x7E00//128)*128
        offset=rng.randrange(0,64)*2
        length=rng.randint(1,(128-offset)//2)*2
        addr=page+offset
        assert 0<=addr<=0x7dfe
        data=rng.randbytes(length)
        packets=[
            b'U'+bytes(((addr//2)&255, (addr//2)>>8))+b' ',
            b'd'+bytes((rng.randrange(3),length,ord('F')))+data+b' ',
            b't'+bytes((rng.randrange(3),length,ord('F')))+b' '
        ]
        for pkt in packets:
            va,vb=a.send(pkt),b.send(pkt)
            assert va==vb, f'{name}: packet {pkt[:10].hex()} reference={va.hex()} new={vb.hex()}'
            count+=1
        assert a.flash[:0x7E00]==b.flash[:0x7E00], f'{name}: flash mismatch after {addr:#x} length {length}'
        assert a.flash[addr:addr+length]==data
    # Read several page boundaries and verify full boot-protection preserved in both.
    for addr in [0, 0x7D80,0x7DFE]:
        cmd=b'U'+bytes(((addr//2)&255, (addr//2)>>8))+b' '
        assert a.send(cmd)==b.send(cmd)
        n=2
        assert a.send(b't\x00'+bytes([n])+b'F ')==b.send(b't\x00'+bytes([n])+b'F ')
        count+=2
    print(f'PASS {name}: {count} additional valid protocol exchanges; full program Flash exactly equal')

# UART reset value is 8N1 (0x06) on physical reset; the 350-byte version assumes it.
# Show direct application-to-boot handoff with a different UCSR0C state.
for name in ['optiboot_mini328_final','optiboot_mini328_reset_only_350']:
    image=(R/(name+'.bin')).read_bytes()
    m=AVR(image,mcusr=0)
    m.io[0xC2]=0x36   # simulate direct app handoff with changed UART framing
    pattern=bytes.fromhex('2091c00027ff')
    rxpos=0x7E00+image.find(pattern)
    assert rxpos>=0x7E00
    for _ in range(3000):
        if m.pc==rxpos:break
        m.step()
    else:raise AssertionError('Boot did not initialize')
    expected=0x06 if name=='optiboot_mini328_final' else 0x36
    assert m.io[0xC2]==expected, f'{name}: UCSR0C must equal 0x{expected:02x}'
    print(f'PASS UART caveat {name}: UCSR0C after app handoff = 0x{m.io[0xC2]:02x}')
