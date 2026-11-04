#!/usr/bin/env python3
"""Audit Arduino-style Flash uploads and Boot-write rejection on AVR models.

Uses real AVRDUDE with -c arduino -D and verification enabled. The transport
is loopback TCP only; this script never opens a serial port or programmer.
The tested Arduino path must accept ordinary and pre-padded application HEX.
"""
import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import build_flashread
import build_mini
import generate_firmware
from verify_avrdude import Target, native_path
from mini_tests.flashread_models import make_cpu
from flashread.prepare_avrdude_hex import prepare

ROOT = Path(__file__).resolve().parent
NAMES = {0x30: 'GET_SYNC', 0x40: 'SET_PARAMETER', 0x41: 'GET_PARAMETER',
         0x42: 'SET_DEVICE', 0x45: 'SET_DEVICE_EXT', 0x50: 'ENTER_PROGMODE',
         0x51: 'LEAVE_PROGMODE', 0x52: 'CHIP_ERASE', 0x55: 'LOAD_ADDRESS',
         0x56: 'UNIVERSAL', 0x64: 'PROG_PAGE', 0x74: 'READ_PAGE', 0x75: 'READ_SIGN'}


class RecordingQueue(deque):
    def __init__(self):
        super().__init__()
        self.stream = bytearray()

    def extend(self, data):
        self.stream.extend(data)
        super().extend(data)


def decode_requests(raw):
    """Decode the host's byte stream independently of the firmware dispatcher."""
    fixed = {0x30: 2, 0x40: 4, 0x41: 3, 0x42: 22, 0x45: 7, 0x50: 2,
             0x51: 2, 0x52: 2, 0x55: 4, 0x56: 6, 0x74: 5, 0x75: 2}
    packets = []
    offset = 0
    while offset < len(raw):
        opcode = raw[offset]
        if opcode == 0x64:
            if len(raw)-offset < 4:
                break
            size = 5 + int.from_bytes(raw[offset+1:offset+3], 'big')
        elif opcode in fixed:
            size = fixed[opcode]
        else:
            raise AssertionError(f'Unexpected Arduino host opcode 0x{opcode:02X}')
        if len(raw)-offset < size:
            break
        packet = bytes(raw[offset:offset+size])
        assert packet[-1] == 0x20, 'Host packet has invalid EOP'
        packets.append(packet)
        offset += size
    return packets, len(raw)-offset


def audit(chip, mode, folder, info, args):
    cpu, boot, dev = make_cpu(chip, folder)
    page = dev['page']
    cpu.rx = RecordingQueue()
    spm_calls = []
    original_spm = cpu.spm
    def observe_spm():
        spm_calls.append(cpu.z())
        original_spm()
    cpu.spm = observe_spm
    case = args.output / chip / mode
    case.mkdir(parents=True, exist_ok=True)
    image = case/'upload.hex'
    if mode == 'boot':
        image.write_text(build_mini.make_hex(boot, cpu.boot_start))
        app = None
    else:
        length = (cpu.boot_start if mode in ('full_application', 'verify_application')
                  else page+2 if mode == 'short_even' else page+1)
        app = bytes((i*37+11) & 255 for i in range(length))
        text = build_mini.make_hex(app, 0)
        if mode == 'padded_odd':
            if getattr(args, 'experimental_328pb_512', False):
                app = app.ljust((len(app)+page-1)//page*page, b'\xff')
                text = build_mini.make_hex(app, 0)
            else:
                text, _, highest = prepare(text, chip)
                app += b'\xff'*(highest+1-len(app))
        image.write_text(text)
    if mode == 'verify_application':
        # Match the physical Mini runner's application-prefix preflight exactly:
        # raw input, -n -D -A, no attempted Boot or EEPROM read.
        image = case/'application.bin'
        image.write_bytes(app)
        cpu.flash[:cpu.boot_start] = app
    before = bytes(cpu.flash)
    windows = args.avrdude.suffix.lower() == '.exe'
    with Target(cpu) as target:
        command = [str(args.avrdude), '-C'+native_path(args.config, windows),
                   '-v', '-p'+chip, '-c', 'arduino',
                   '-P', f'net:127.0.0.1:{target.port}', '-b', str(info['baud']),
                   '-D']
        if mode == 'verify_application':
            command += ['-n', '-A', '-Uflash:v:'+native_path(image, windows)+':r']
        else:
            command += ['-Uflash:w:'+native_path(image, windows)+':i']
        if windows and sys.platform != 'win32':
            time.sleep(0.5)  # Allow WSL to advertise the new localhost listener.
        for attempt in range(5):
            timed_out = False
            try:
                result = subprocess.run(command, capture_output=True, text=True,
                                        timeout=args.timeout)
                log = result.stdout+result.stderr
                returncode = result.returncode
            except subprocess.TimeoutExpired as error:
                stdout, stderr = error.stdout or b'', error.stderr or b''
                log = (stdout+stderr).decode(errors='replace')
                returncode, timed_out = None, True
            if returncode == 0 or target.had_input:
                break
            time.sleep(0.3*(attempt+1))  # Retry unopened WSL forwarding only.
        (case/'avrdude.log').write_text(log)
    raw = bytes(cpu.rx.stream)
    (case/'host_requests.bin').write_bytes(raw)
    packets, trailing = decode_requests(raw)
    accepted = returncode == 0 and not timed_out
    firmware_version = re.search(r'FW Version\s*:\s*(\d+\.\d+)', log)
    firmware_version = firmware_version[1] if firmware_version else None
    assert bytes(cpu.flash[cpu.boot_start:]) == boot, 'Boot contents changed'
    if accepted:
        assert mode != 'boot', 'Host overwrote the Boot image'
        assert target.error is None and trailing == 0
        span = (len(app)+page-1)//page*page
        assert bytes(cpu.flash[:span]) == app.ljust(span, b'\xff'), 'Application/padding differs'
        assert bytes(cpu.flash[span:]) == before[span:], 'Data beyond the application changed'
        assert any(packet[0] == 0x74 for packet in packets), 'No readback verification'
        if getattr(args, 'experimental_328pb_512', False):
            assert firmware_version == '3.3', 'AVRDUDE did not receive Mini parameter value 3'
        address = 0
        for packet in packets:
            if packet[0] == 0x55:
                address = int.from_bytes(packet[1:3], 'little')*2
            elif packet[0] in (0x64, 0x74):
                length = int.from_bytes(packet[1:3], 'big')
                assert packet[3] == 0x46, 'Host accessed unsupported memory'
                assert address+length <= cpu.boot_start, 'Host accessed protected Boot bytes'
        if mode == 'verify_application':
            assert bytes(cpu.flash) == before and not spm_calls
            assert not any(packet[0] == 0x64 for packet in packets), 'Read-only verify programmed Flash'
    else:
        assert cpu.pc == cpu.error_pc, 'Failure did not come from the firmware guard'
        assert str(target.error) == 'Firmware rejected the host packet'
        if mode == 'boot':
            assert packets[-1][0] == 0x64, 'Failure preceded the Boot PROG_PAGE request'
            load = next(packet for packet in reversed(packets) if packet[0] == 0x55)
            assert int.from_bytes(load[1:3], 'little')*2 == cpu.boot_start
            assert bytes(cpu.flash) == before and not spm_calls, 'Boot attempt reached SPM'
        else:
            raise AssertionError('Arduino application upload was rejected')
    counts = Counter(NAMES[packet[0]] for packet in packets)
    lengths = [int.from_bytes(packet[1:3], 'big') for packet in packets if packet[0] == 0x64]
    selectors = sorted({packet[1] for packet in packets if packet[0] == 0x41})
    return dict(mcu=chip, mode=mode, upload_accepted=accepted,
                boot_unchanged=True, no_spm_on_boot_attempt=not spm_calls if mode == 'boot' else None,
                verified_by_avrdude=accepted, firmware_guard_rejected=not accepted,
                host_process_timed_out=timed_out, host_return_code=returncode,
                unopened_transport_retries=attempt,
                request_counts=dict(sorted(counts.items())), write_packet_lengths=lengths,
                get_parameter_ids=selectors, trailing_request_bytes=trailing,
                host_reported_firmware_version=firmware_version,
                application_bytes=len(app) if app is not None else 0,
                sha256=info['sha256'], baud=info['baud'], software_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avrdude', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--mcu', choices=build_flashread.TARGETS+('atmega328pb',))
    parser.add_argument('--experimental-328pb-512', action='store_true',
                        help='Opt into the separate 512-byte 328PB Mini experiment')
    parser.add_argument('--output', type=Path, default=ROOT/'output/arduino-audit')
    parser.add_argument('--timeout', type=int, default=12)
    parser.add_argument('--baud', default='auto')
    args = parser.parse_args()
    if args.experimental_328pb_512:
        if args.mcu not in (None, 'atmega328pb'):
            parser.error('--experimental-328pb-512 requires --mcu atmega328pb')
        args.mcu = 'atmega328pb'
    elif args.mcu == 'atmega328pb':
        parser.error('atmega328pb requires --experimental-328pb-512')
    args.avrdude = args.avrdude.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    rows, failed = [], []
    for chip in (args.mcu,) if args.mcu else build_flashread.TARGETS:
        if args.experimental_328pb_512:
            folder = args.output/'images'/'mini-experimental-512'/chip
            result = build_flashread.one(chip, folder, baud=(115200 if args.baud == 'auto'
                                          else int(args.baud)), experimental_512=True)
            info = dict(result, sha256=result['code_sha256'])
        else:
            info = generate_firmware.build_one(chip, 'mini', 16000000, baud=args.baud,
                                               out=args.output/'images')
            folder = Path(info['files']['bin']).parent
        modes = ('short_even', 'short_odd', 'padded_odd', 'boot')
        if args.experimental_328pb_512:
            modes += ('full_application', 'verify_application')
        for mode in modes:
            try:
                row = audit(chip, mode, folder, info, args)
                rows.append(row)
                print(f'PASS {chip}/{mode}: upload_accepted={row["upload_accepted"]}; '
                      f'write_lengths={row["write_packet_lengths"]}', flush=True)
            except Exception as error:
                failed.append(dict(mcu=chip, mode=mode, error=str(error)))
                print(f'FAIL {chip}/{mode}: {error}', flush=True)
    summary = dict(cases=rows, failed=failed, software_only=True,
                   programmer='arduino', verification_enabled=True, baud_source='firmware_manifest',
                   experimental_328pb_512=args.experimental_328pb_512)
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(f'RESULT: {len(rows)} cases checked; {len(failed)} failures; no physical hardware accessed.')
    return bool(failed)


if __name__ == '__main__':
    sys.exit(main())
