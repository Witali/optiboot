#!/usr/bin/env python3
"""Experimental Flash-only 256B bootloader uploader (requires pyserial for I/O).

Writes complete AVR Flash pages with the STK500v1 subset. No Flash read-back
or verification is possible through this firmware. Input HEX is checksummed.
Use --dry-run to validate an image and show a plan without any serial port.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time

# Allow standalone run from within flash256/ folder.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build_flash256 import TARGETS
from build_mini import DEVICES


def parse_intel_hex(raw: str) -> dict[int,int]:
    result={}
    high=0
    eof=False
    for line_no,line in enumerate(raw.splitlines(),1):
        line=line.strip()
        if not line:continue
        if eof:raise ValueError(f'HEX data after EOF at line {line_no}')
        if not line.startswith(':'):raise ValueError(f'Bad HEX record at line {line_no}')
        b=bytes.fromhex(line[1:])
        if len(b)<5 or len(b)!=b[0]+5 or sum(b)&255:
            raise ValueError(f'Wrong length/checksum at line {line_no}')
        count=b[0];addr=(b[1]<<8)|b[2];kind=b[3];data=b[4:-1]
        if kind==0:
            for i,v in enumerate(data):
                absolute=high+addr+i
                if absolute in result and result[absolute]!=v:
                    raise ValueError(f'Conflicting HEX data at 0x{absolute:x}')
                result[absolute]=v
        elif kind==1:
            if count!=0:raise ValueError('Unexpected EOF length')
            eof=True
        elif kind==4:
            if count!=2:raise ValueError('Unexpected extended linear address length')
            high=int.from_bytes(data,'big')<<16
        elif kind==2:
            if count!=2:raise ValueError('Unexpected segment address length')
            high=int.from_bytes(data,'big')<<4
        elif kind in (3,5):
            continue  # Start execution address records, not Flash data.
        else:raise ValueError(f'Unsupported Intel HEX record type {kind}')
    if not eof:raise ValueError('Missing Intel HEX EOF')
    return result


def make_pages(hex_text: str, mcu: str) -> list[tuple[int,bytes]]:
    if mcu not in TARGETS:raise ValueError('Not a supported Flash256 MCU')
    info=DEVICES[mcu];size=info['page'];boot=info['flash']-256
    raw=parse_intel_hex(hex_text)
    if not raw:raise ValueError('HEX contains no Flash data')
    if any(addr>=boot for addr in raw):
        raise ValueError(f'Application HEX overlaps Boot or outside Flash >= 0x{boot:04X}')
    pages={}
    for addr,value in raw.items():
        pageaddr=addr & ~(size-1)
        page=pages.setdefault(pageaddr, bytearray([255]*size))
        page[addr-pageaddr]=value
    return [(addr,bytes(page)) for addr,page in sorted(pages.items())]


def packet_for_page(addr, content):
    if addr%2:raise ValueError('Flash address must be even')
    if len(content) not in (64,128):raise ValueError('Only 64/128-B page writes supported')
    word=addr//2
    return (bytes((0x55,word&255,(word>>8)&255,0x20)),
            bytes((0x64,0,len(content),0x46))+content+b' ')


def upload(port,mcu,pages,baud):
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError('pyserial required: python -m pip install pyserial') from exc
    info=DEVICES[mcu]
    with serial.Serial(port=port,baudrate=baud,timeout=0.5,write_timeout=0.5) as ser:
        # Active-low DTR reset pulse for a typical Arduino-style USB-UART circuit.
        ser.dtr=False
        time.sleep(0.06)
        ser.dtr=True
        time.sleep(0.07)
        ser.reset_input_buffer()
        def call(req,expected):
            ser.write(req)
            got=ser.read(len(expected))
            if got!=expected:
                raise RuntimeError(f'STK500 transfer failed: sent {req[:8].hex()}, got {got.hex()}, expected {expected.hex()}')
        for attempt in range(3):
            try:
                call(b'0 ',b'\x14\x10')
                break
            except RuntimeError:
                if attempt==2:raise
                ser.reset_input_buffer()
                time.sleep(0.04)
        call(b'u ',b'\x14'+bytes(info['sig'])+b'\x10')
        for i,(addr,content) in enumerate(pages,1):
            load,write=packet_for_page(addr,content)
            call(load,b'\x14\x10')
            call(write,b'\x14\x10')
            print(f'Wrote page {i}/{len(pages)} at 0x{addr:04X}')
        call(b'Q ',b'\x14\x10')
    print('Transfers acknowledged; DEVICE FLASH WAS NOT READ BACK OR VERIFIED.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mcu',required=True,choices=sorted(TARGETS))
    p.add_argument('--hex',required=True,type=Path)
    p.add_argument('--port')
    p.add_argument('--baud',type=int,default=115200)
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    pages=make_pages(args.hex.read_text(),args.mcu)
    print(f'{args.mcu}: {len(pages)} full pages ({len(pages)*len(pages[0][1])} bytes transferred), Boot reserved 256 B')
    if args.dry_run:
        for addr,_ in pages:print(f'  0x{addr:04X}')
        print('DRY RUN; no serial I/O')
    else:
        if not args.port:p.error('--port is required unless --dry-run')
        upload(args.port,args.mcu,pages,args.baud)

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,OSError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
