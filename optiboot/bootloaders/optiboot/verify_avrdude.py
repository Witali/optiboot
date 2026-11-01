#!/usr/bin/env python3
"""Run real AVRDUDE against the AVR instruction models over loopback TCP.

No serial ports, ISP programmers or physical boards are opened. This checks
host/protocol interoperability; it does not validate electrical UART timing.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import build_mini
import generate_firmware as generator

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'mini_tests'))
from device_models import create
from flashread_models import make_cpu


class Target:
    def __init__(self, cpu):
        self.cpu, self.error = cpu, None
        self.sent = 0
        self.had_input = False
        self.received_bytes = 0
        self.stopped = threading.Event()
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(1)
        self.socket.settimeout(0.5)
        self.port = self.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def serve(self):
        try:
            while not self.stopped.is_set():
                try:
                    connection, _ = self.socket.accept()
                except socket.timeout:
                    continue
                session_input = False
                with connection:
                    connection.settimeout(0.5)
                    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    while not self.stopped.is_set():
                        try:
                            data = connection.recv(4096)
                        except socket.timeout:
                            continue
                        if not data:
                            break
                        session_input = self.had_input = True
                        self.received_bytes += len(data)
                        if hasattr(socket, 'TCP_QUICKACK'):
                            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)
                        self.cpu.rx.extend(data)
                        for _ in range(2000000):
                            if self.cpu.pc == self.cpu.error_pc:
                                raise RuntimeError('Firmware rejected the host packet')
                            if not self.cpu.rx and self.cpu.pc == self.cpu.rxwait_pc:
                                break
                            self.cpu.step()
                        else:
                            raise RuntimeError('Instruction model did not return to receive')
                        reply = bytes(self.cpu.tx[self.sent:])
                        self.sent = len(self.cpu.tx)
                        if reply:
                            connection.sendall(reply)
                if session_input:
                    return
                # A WSL localhost-forwarding probe may connect without data.
        except Exception as error:
            self.error = error

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *unused):
        self.stopped.set()
        self.thread.join(2)
        self.socket.close()


def native_path(path, windows_executable):
    path = str(Path(path).resolve())
    if windows_executable and os.name != 'nt':
        return subprocess.check_output(['wslpath', '-w', path], text=True).strip()
    return path


def verify(chip, edition, args):
    dev = build_mini.DEVICES[chip]
    info = generator.build_one(chip, edition, 16000000, out=args.output / 'images')
    folder = Path(info['files']['bin']).parent
    cpu, boot, _ = (make_cpu(chip, folder) if edition == 'flashread256' else create(chip, folder))
    app = bytes((i*73+i//dev['page']*17+19) & 255 for i in range(cpu.boot_start))
    eeprom = bytes((i*29+7) & 255 for i in range(dev['eeprom']))
    case = args.output / chip / edition
    case.mkdir(parents=True, exist_ok=True)
    image = case / 'application.hex'
    if args.padded_application:
        from flashread.prepare_avrdude_hex import prepare
        # Verify that the real host retains a deliberately padded final page.
        unpadded = build_mini.make_hex(app[:-13], 0)
        prepared, _, _ = prepare(unpadded, chip)
        image.write_text(prepared)
        app = app[:-13] + b'\xff'*13
    else:
        image.write_text(build_mini.make_hex(app, 0))
    ee = case / 'eeprom.bin'
    ee.write_bytes(eeprom)
    windows = args.avrdude.suffix.lower() == '.exe'
    part = 'm' + chip.removeprefix('atmega')
    with Target(cpu) as target:
        command = [str(args.avrdude), '-c', 'arduino', '-p', part,
                   '-P', f'net:127.0.0.1:{target.port}', '-b', str(info['baud']),
                   '-D', '-q', '-q']
        if args.config:
            command += ['-C', native_path(args.config, windows)]
        command += ['-U', 'flash:w:' + native_path(image, windows) + ':i']
        if edition != 'flashread256':
            command += ['-U', 'eeprom:w:' + native_path(ee, windows) + ':r']
        # AVRDUDE's normal verification is enabled: no -V and no signature override.
        if windows and os.name != 'nt':
            time.sleep(0.5)  # Let WSL advertise this new localhost listener.
        try:
            for attempt in range(5):
                result = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
                if not result.returncode or target.had_input:
                    break
                # Retry only an unopened transport; never replay a written target.
                time.sleep(0.3*(attempt+1))
        except subprocess.TimeoutExpired as error:
            output = (error.stdout or b'') + (error.stderr or b'')
            if isinstance(output, bytes):
                output = output.decode(errors='replace')
            (case / 'avrdude.log').write_text(output)
            raise RuntimeError(f'AVRDUDE exceeded {args.timeout}s after {target.received_bytes} input bytes; see the local case log') from None
        (case / 'avrdude.log').write_text(result.stdout + result.stderr)
    if target.error:
        raise RuntimeError(str(target.error))
    if result.returncode:
        raise RuntimeError(f'AVRDUDE returned {result.returncode}; see the local case log')
    assert bytes(cpu.flash[:cpu.boot_start]) == app
    assert bytes(cpu.flash[cpu.boot_start:]) == boot
    if edition != 'flashread256':
        assert bytes(cpu.eeprom) == eeprom
    return dict(mcu=chip, edition=edition, application_bytes=len(app),
                eeprom_bytes=0 if edition == 'flashread256' else len(eeprom),
                avrdude_verify=True, boot_unchanged=True, software_model=True,
                padded_final_page=args.padded_application, sha256=info['sha256'],
                frequency_hz=info['frequency_hz'], baud=info['baud'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avrdude', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--mcu')
    parser.add_argument('--edition', choices=('compact', 'full', 'flashread256'))
    parser.add_argument('--output', type=Path, default=ROOT / 'output/avrdude-validation')
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--padded-application', action='store_true',
                        help='Check FlashRead256 with a final page padded by the supplied tool')
    args = parser.parse_args()
    if args.padded_application and args.edition != 'flashread256':
        parser.error('--padded-application requires --edition flashread256')
    args.avrdude = args.avrdude.resolve()
    passed, failed = [], []
    for chip, dev in build_mini.DEVICES.items():
        if dev['virtual_boot'] or args.mcu and chip != args.mcu:
            continue
        for edition in generator.valid_types(chip):
            if args.edition and edition != args.edition:
                continue
            try:
                passed.append(verify(chip, edition, args))
                print(f'PASS real AVRDUDE / modeled AVR: {chip}/{edition}', flush=True)
            except Exception as error:
                failed.append(dict(mcu=chip, edition=edition, error=str(error)))
                print(f'FAIL real AVRDUDE / modeled AVR: {chip}/{edition}: {error}', flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'summary.json').write_text(json.dumps(dict(passed=passed, failed=failed,
        software_only=True), indent=2) + '\n')
    if not passed and not failed:
        parser.error('No hardware-UART profile matched; ATtiny uses its dedicated host workflow')
    print(f'RESULT: {len(passed)} passed; {len(failed)} failed; no physical hardware accessed.')
    return bool(failed)


if __name__ == '__main__':
    sys.exit(main())
