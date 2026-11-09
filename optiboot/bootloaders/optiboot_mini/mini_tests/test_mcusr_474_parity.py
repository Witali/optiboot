#!/usr/bin/env python3
"""Match reset-cause handling of the official Optiboot 8.3 ATmega328 474B HEX.

Software-level AVR execution model, NOT a hardware watchdog timing or
oscillator accuracy test. Uses the exact published upstream HEX as a fixture.
The simulator implements MCUSR's WRITE-ZERO-TO-CLEAR semantics explicitly.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(ROOT)]
from test_compact_signature_512 import AVRCompact
from test_legacy_uart import symaddr

UPSTREAM_HEX = HERE / 'fixtures' / 'optiboot_8_3_atmega328_official_474.hex'
UPSTREAM_SHA256 = '6d0dfd5601a39900a3abfffce82e30c5c3f5169099c00acb3f3d92ba38528e30'


def load_official_hex():
    data = bytearray(b'\xff' * 512)
    upper = 0
    count = 0
    for record in UPSTREAM_HEX.read_text().splitlines():
        record = record.strip()
        if not record:
            continue
        raw = bytes.fromhex(record[1:])
        if ((sum(raw) & 0xff) != 0):
            raise AssertionError('Bad Intel HEX checksum')
        n, addr, kind = raw[0], (raw[1] << 8) | raw[2], raw[3]
        if kind == 4:
            upper = int.from_bytes(raw[4:6], 'big') << 16
        elif kind == 0:
            for i, value in enumerate(raw[4:4+n]):
                location = upper + addr + i
                if location < 0x7e00 or location >= 0x8000:
                    raise AssertionError(f'Out-of-boot address {location:x}')
                data[location - 0x7e00] = value
            count += n
    if count != 474:
        raise AssertionError(f'Expected 474 firmware bytes, got {count}')
    if hashlib.sha256(data).hexdigest() != UPSTREAM_SHA256:
        raise AssertionError('Upstream fixture SHA-256 mismatch')
    return bytes(data)


class ResetFlagAVR(AVRCompact):
    """MCUSR is sticky and writing zero clears the corresponding bit."""
    def __init__(self, image, mcusr=0):
        super().__init__(image, mcusr)
        self.mcusr_log = []
        self.wdt_log = []

    def io_write(self, addr, val):
        if addr == 0x54:  # MCUSR I/O 0x34 -> memory 0x54
            before = self.io[addr]
            self.mcusr_log.append((self.pc, before, val))
            self.io[addr] = before & val
            return
        if addr == 0x60:  # WDTCSR
            self.wdt_log.append((self.pc, val, self.io[0x54]))
        super().io_write(addr, val)


def run_until_app_or_rx(image, cause, rx_addr):
    cpu = ResetFlagAVR(image, cause)
    cpu.rxwait_pc = rx_addr
    for _ in range(20000):
        if cpu.pc == rx_addr:
            return 'boot', cpu
        if cpu.app_started:
            return 'app', cpu
        cpu.step()
    raise AssertionError(f'Could not reach app or UART receive for cause=0x{cause:02x}, PC={cpu.pc:04x}')


class ResetParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = load_official_hex()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cp = subprocess.run([
            sys.executable, str(ROOT/'build_mini.py'), '--mcu', 'atmega328p',
            '--f-cpu', '16000000', '--baud', '115200', '--boot-bytes', '512',
            '--app-spm-512', '--output-dir', str(cls.out),
        ], capture_output=True, text=True)
        if cp.returncode:
            raise AssertionError(cp.stderr)
        cls.new = (cls.out/'atmega328p.bin').read_bytes()
        cls.meta = json.loads((cls.out/'atmega328p.json').read_text())
        cls.rx_new = 0x7e00 + symaddr(cls.out/'atmega328p.o', 'rx_wait')
        cls.rx_old = 0x7f76  # official Optiboot 8.3 .lst

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compare(self, cause):
        oldmode, old = run_until_app_or_rx(self.reference, cause, self.rx_old)
        newmode, new = run_until_app_or_rx(self.new, cause, self.rx_new)
        self.assertEqual(newmode, oldmode, f'reset reason 0x{cause:02x}')
        self.assertEqual(new.io[0x54], old.io[0x54], f'MCUSR for reset 0x{cause:02x}')
        if newmode == 'app':
            self.assertEqual(new.reg[2], old.reg[2], f'r2 for reset 0x{cause:02x}')
        return newmode, new, old

    def test_512_byte_binary_footer_abi(self):
        self.assertEqual(len(self.new), 512)
        self.assertEqual(self.meta['code_bytes'], 498)
        self.assertEqual(self.new[-5:], bytes.fromhex('1e950f0308'))
        self.assertEqual(symaddr(self.out/'atmega328p.o', 'optiboot_mini_do_spm'), 2)
        self.assertTrue(self.meta['app_spm_512'])
        self.assertEqual(self.meta['app_spm_entry_byte_address'], 0x7e02)

    def test_all_sixteen_reset_flag_combinations_match_474(self):
        for cause in range(16):
            with self.subTest(mcusr=f'0x{cause:02x}'):
                self.compare(cause)

    def test_no_unconditional_mcusr_clear(self):
        for cause, expected in ((1,1),(4,4),(8,8),(9,9),(12,12)):
            with self.subTest(cause=cause):
                mode, new, ref = self.compare(cause)
                self.assertEqual(mode, 'app')
                self.assertEqual(new.io[0x54], expected)
                self.assertFalse(new.mcusr_log, f'MCUSR write should not occur for {cause:02x}')

    def test_extrf_wdrf_clears_only_wdrf_before_wdt_unlock(self):
        for reason in (0x0a,0x0b,0x0e,0x0f):
            with self.subTest(reason=reason):
                mode, c, old = self.compare(reason)
                self.assertEqual(mode, 'app')
                self.assertEqual(c.reg[2], reason)
                self.assertEqual(c.io[0x54], reason & ~8)
                self.assertEqual([v for _,_,v in c.mcusr_log], [0xf7])
                self.assertEqual([v for _,_,v in old.mcusr_log], [0xf7])
                self.assertTrue(c.wdt_log)
                self.assertEqual(c.wdt_log[0][2], reason & ~8,
                                 'WDRF must clear before WDE/WDTCSR writes')

    def test_external_reset_then_wdt_timeout(self):
        for reason in (2,3,6,7):
            with self.subTest(reason=reason):
                mode, c, old = self.compare(reason)
                self.assertEqual(mode, 'boot')
                self.assertEqual(c.io[0x54], reason)
                # Model a subsequent hardware WDT reset without a power cycle.
                later_reason = c.io[0x54] | 8
                later_ref_reason = old.io[0x54] | 8
                self.assertEqual(later_reason, later_ref_reason)
                mode2, c2, old2 = self.compare(later_reason)
                self.assertEqual(mode2, 'app')
                self.assertEqual(c2.reg[2], later_reason)
                self.assertEqual(c2.io[0x54], reason)
                self.assertEqual(old2.io[0x54], reason)

    def test_bootloader_uart_and_signatures_still_respond(self):
        mode, c, _ = self.compare(2)
        self.assertEqual(mode, 'boot')
        self.assertEqual(c.send(b'0 '), b'\x14\x10')
        self.assertEqual(c.send(b'u '), bytes.fromhex('14 1e 95 0f 10'))
        self.assertEqual(c.send(b'A\x81 '), bytes.fromhex('14 08 10'))
        for i,v in enumerate((0x1e, 0x95, 0x0f)):
            packet = bytes((0x56,0x30,0,i,0,0x20))
            self.assertEqual(c.send(packet), bytes((0x14,v,0x10)))

    def test_r4_default_328p_baseline_hash_is_stable(self):
        with tempfile.TemporaryDirectory() as path:
            cp = subprocess.run([sys.executable,str(ROOT/'build_mini.py'),
                '--mcu','atmega328p','--verify-baseline','--output-dir',path],
                capture_output=True,text=True)
            self.assertEqual(cp.returncode,0,cp.stderr)


if __name__ == '__main__':
    unittest.main()
