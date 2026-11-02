#!/usr/bin/env python3
"""Prepare a full-page Intel HEX for the 256-byte Flash read/write edition.

The 256B firmware requires complete STK_PROG_PAGE payloads. The audited
AVRDUDE 8.0-arduino.1 Arduino upload path pads the final page automatically;
this optional tool prepares full pages for hosts without that behavior.
Each touched physical page is filled with 0xFF outside the supplied data.

Flash readback remains available. Use `avrdude -c arduino -D`, with verify
enabled. This program only prepares a file and never opens a serial port.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flashread.hex import make_pages, parse_intel_hex
from build_flashread import TARGETS
from build_mini import DEVICES


def rec(addr: int, payload: bytes, record_type: int = 0) -> str:
    if not 0 <= addr <= 65535: raise ValueError('Address must fit 16 bits')
    if len(payload) > 255: raise ValueError('Record payload too long')
    fields = bytes((len(payload), addr>>8, addr&255, record_type)) + payload
    return ':' + fields.hex().upper() + f'{(-sum(fields)) & 255:02X}'


def prepare(input_text: str, mcu: str):
    """Return (prepared hex, number of touched pages, highest byte address)."""
    if mcu not in TARGETS: raise ValueError(f'Unsupported MCU: {mcu}')
    dev = DEVICES[mcu]
    pages = make_pages(input_text, mcu)
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
    if any(a >= dev['flash']-256 for a in again):
        raise AssertionError('Boot section overlap')
    # Re-check last occupied byte is aligned to a whole hardware page.
    highest = max(again)
    if (highest+1) % dev['page']:
        raise AssertionError('Unexpected partial final page')
    return result, len(pages), highest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mcu',required=True,choices=sorted(TARGETS))
    ap.add_argument('--input',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args()
    if args.input.resolve() == args.output.resolve():
        ap.error('Input and output must be different paths')
    data, numpages, end=prepare(args.input.read_text(), args.mcu)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(data)
    print(f'Prepared {args.mcu}: {numpages} pages; last byte 0x{end:04X}; saved {args.output}')
    print('Run AVRDUDE with -c arduino -D and normal verification enabled (no -V).')
    print('The 256-byte loader supports Flash readback; every programmed page can be verified.')

if __name__=='__main__':
    try:main()
    except (ValueError,AssertionError,OSError) as e:
        print('ERROR:',e,file=sys.stderr)
        raise SystemExit(1)
