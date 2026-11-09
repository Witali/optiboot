#!/usr/bin/env python3
"""AVRDUDE signature transport regression: Arduino vs plain stk500v1.

Source of truth: avrdudes/avrdude src/arduino.c uses STK_READ_SIGN;
src/stk500.c implements STK_UNIVERSAL and avr_read_byte_default.
The MCU emulator is opcode-level (NOT real silicon / serial timing).
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from avr_base_sim import AVR

ROOT = Path(__file__).resolve().parents[1]

class SignatureSimulator(AVR):
    """Base 328P simulator with the fuse LPM Rd,Z instruction modeled."""
    def step(self):
        op = self.u16(self.pc)
        if op & 0xfe0f == 0x9004:   # LPM Rd,Z (fuse via BLBSET|SPMEN)
            reg = (op >> 4) & 31
            if self.io.get(0x57) == 9:
                self.reg[reg] = (0x62, 0xfd, 0xff, 0xd9)[self.z() & 3]
                self.io[0x57] = 0
            else:
                self.reg[reg] = self.flash[self.z()]
            self.pc = (self.pc+2) % len(self.flash)
            return
        return super().step()


def run_packet(cpu, payload, size):
    tx0 = len(cpu.tx)
    cpu.rx.extend(payload)
    for _ in range(100000):
        cpu.step()
        if len(cpu.tx) - tx0 >= size:
            break
    else:
        raise AssertionError('No complete STK500v1 response to '+payload.hex(' '))
    return bytes(cpu.tx[tx0:])


class SigCompatibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        default = d / 'default'
        cp0 = subprocess.run([sys.executable, str(ROOT/'build_mini.py'), '--mcu', 'atmega328p',
                              '--verify-baseline', '--output-dir', str(default)],
                             capture_output=True, text=True)
        if cp0.returncode:
            raise RuntimeError(cp0.stderr)
        cls.original = (default/'atmega328p.bin').read_bytes()
        cp = subprocess.run([sys.executable, str(ROOT/'build_mini.py'), '--mcu', 'atmega328p',
                             '--boot-bytes', '1024', '--universal-signature',
                             '--output-dir', str(d)], capture_output=True, text=True)
        if cp.returncode:
            raise RuntimeError(cp.stderr)
        cls.compat = (d/'atmega328p.bin').read_bytes()

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def emulator(self, image):
        if len(image) == 512:
            return SignatureSimulator(image)
        cpu = SignatureSimulator(self.original)
        cpu.flash = bytearray(b'\xff'*(0x8000 - len(image))) + image
        cpu.pc = 0x8000 - len(image)
        return cpu

    def test_original_arduino_mode_signature_unchanged(self):
        cpu = self.emulator(self.original)
        self.assertEqual(run_packet(cpu, b'0 ',2), b'\x14\x10')
        self.assertEqual(run_packet(cpu, b'u ',5), bytes.fromhex('14 1e 95 0f 10'))
        for i in range(3):
            self.assertEqual(run_packet(cpu, bytes((0x56,0x30,0,i,0,0x20)),3), bytes.fromhex('14 00 10'))

    def test_compat_arduino_mode_signature(self):
        cpu = self.emulator(self.compat)
        self.assertEqual(run_packet(cpu, b'0 ',2), b'\x14\x10')
        self.assertEqual(run_packet(cpu, b'u ',5), bytes.fromhex('14 1e 95 0f 10'))
        self.assertEqual(run_packet(cpu, b'1 ',9), bytes.fromhex('14 41 56 52 20 53 54 4b 10'))

    def test_compat_universal_signature_byte_by_byte(self):
        cpu = self.emulator(self.compat)
        for i, b in enumerate((0x1e,0x95,0x0f)):
            payload=bytes((0x56,0x30,0,i,0,0x20))
            self.assertEqual(run_packet(cpu,payload,3), bytes((0x14,b,0x10)))

    def test_compat_invalid_signature_indices(self):
        cpu = self.emulator(self.compat)
        for cmd in ((0x56,0x30,0,3,0,0x20), (0x56,0x30,0,0xff,0,0x20),
                    (0x56,0x30,1,1,0,0x20), (0x56,0xac,0x53,0,0,0x20)):
            self.assertEqual(run_packet(cpu,bytes(cmd),3), bytes.fromhex('14 00 10'))

    def test_compat_fuse_reads_not_regressed(self):
        cpu = self.emulator(self.compat)
        for cmd,reply in [((0x56,0x50,0,0,0,0x20),0x62),
                          ((0x56,0x58,8,0,0,0x20),0xd9)]:
            self.assertEqual(run_packet(cpu,bytes(cmd),3), bytes((0x14,reply,0x10)))

    def test_compat_flash_page_write_and_read(self):
        cpu = self.emulator(self.compat)
        data = bytes(((i * 13 + 17) & 255) for i in range(128))
        self.assertEqual(run_packet(cpu, bytes.fromhex('55 00 00 20'),2), b'\x14\x10')
        write = bytes((0x64, 0, 128, ord('F'))) + data + b' '
        self.assertEqual(run_packet(cpu,write,2), b'\x14\x10')
        self.assertEqual(bytes(cpu.flash[:128]), data)
        self.assertEqual(run_packet(cpu, bytes.fromhex('55 00 00 20'),2), b'\x14\x10')
        read = bytes((0x74, 0, 128, ord('F'), 0x20))
        self.assertEqual(run_packet(cpu,read,130), b'\x14'+data+b'\x10')

    def test_compat_bootsize_and_footer(self):
        self.assertEqual(len(self.compat), 1024)
        self.assertEqual(self.compat[-12:], bytes.fromhex('1e 95 0f')+b'AVR STK'+bytes((3,8)))
        self.assertEqual(len(self.original), 512)

if __name__ == '__main__': unittest.main()
