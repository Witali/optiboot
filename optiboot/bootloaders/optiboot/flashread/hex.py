"""Offline HEX parsing and full-page preparation for the Mini edition."""
from build_flashread import TARGETS
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
    if mcu not in TARGETS:raise ValueError('Not a supported Mini MCU')
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
