#!/usr/bin/env python3
"""Prepare a full-page Intel HEX for the 256-byte Flash-only Optiboot edition.

AVRDUDE sends the final STK_PROG_PAGE with a short length if the image ends
inside a Flash page. The 256B firmware deliberately has no variable-length
flash-write support. This tool fills each touched physical page with 0xFF.

NO Flash read-back is possible; use `avrdude -c arduino -D -V` and make a
separate ISP backup/recovery plan. This program never opens a serial port.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flash256.upload_flash256 import make_pages, parse_intel_hex
from build_flash256 import TARGETS
from build_mini import DEVICES


def rec(addr: int, payload: bytes, record_type: int = 0) -> str:
    if not 0 <= addr <= 65535: raise ValueError('Address must fit 16 bits')
    if len(payload) > 255: raise ValueError('Record payload too long')
    fields = bytes((len(payload), addr>>8, addr&255, record_type)) + payload
    return ':' + fields.hex().upper() + f'{(-sum(fields)) & 255:02X}'


def prepare(input_text: str, mcu: str, boot_bytes: int = 256):
    """Return (prepared hex, number of touched pages, highest byte address)."""
    if mcu not in TARGETS: raise ValueError(f'Unsupported MCU: {mcu}')
    if boot_bytes not in (256,512): raise ValueError('Boot reservation must be 256 or 512 bytes')
    dev = DEVICES[mcu]
    pages = make_pages(input_text, mcu)
    if any(address+len(data)>dev['flash']-boot_bytes for address,data in pages):
        raise ValueError('Application HEX overlaps the selected Boot reservation')
    # Full-page records; sparse groups remain sparse in Intel HEX. AVRDUDE
    # still determines the number of blocks from the highest addressed byte.
    lines = []
    for page_addr, content in pages:
        for i in range(0, len(content), 16):
            lines.append(rec(page_addr+i, content[i:i+16]))
    lines.append(':00000001FF')
    result = '\n'.join(lines) + '\n'
    again = parse_intel_hex(result)
    expected = {a+i: b for a, content in pages for i, b in enumerate(content)}
    if again != expected:
        raise AssertionError('HEX serialization did not round-trip')
    if any(a >= dev['flash']-boot_bytes for a in again):
        raise AssertionError('Boot section overlap')
    # Re-check last occupied byte is aligned to a whole hardware page.
    highest = max(again)
    if (highest+1) % dev['page']:
        raise AssertionError('Unexpected partial final page')
    return result, len(pages), highest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mcu',required=True,choices=sorted(TARGETS))
    ap.add_argument('--boot-bytes',type=int,choices=(256,512),default=256,
                    help='256 for Flash256; 512 for FlashRead512')
    ap.add_argument('--input',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args()
    if args.input.resolve() == args.output.resolve():
        ap.error('Input and output must be different paths')
    data, numpages, end=prepare(args.input.read_text(), args.mcu, args.boot_bytes)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(data)
    print(f'Prepared {args.mcu}: {numpages} pages; last byte 0x{end:04X}; saved {args.output}')
    if args.boot_bytes==256:
        print('Run AVRDUDE with -c arduino -D -V (no chip erase, no verify).')
        print('Only acknowledgements are available; programmed Flash cannot be read back by the 256B loader.')
    else:
        print('FlashRead512: use -c arduino -D with readback verification enabled.')

if __name__=='__main__':
    try:main()
    except (ValueError,AssertionError,OSError) as e:
        print('ERROR:',e,file=sys.stderr)
        raise SystemExit(1)
