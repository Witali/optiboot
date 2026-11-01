"""Application SPM ABI and Boot guards for every current ATmega edition."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import build_mini
import build_dual
from device_models import create

ROOT = Path(__file__).resolve().parents[1]


class CurrentSPMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='current-spm-')
        cls.folder = Path(cls.temp.name)
        subprocess.run([sys.executable, str(ROOT/'build_dual.py'), '--all',
                        '--edition', 'both', '--jobs', '4', '--output-dir', str(cls.folder)],
                       capture_output=True, text=True, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def invoke(self, cpu, address, command, data=0):
        saved = {r: cpu.reg[r] for r in (*range(2, 18), 28, 29)}
        cpu.reg[24], cpu.reg[25] = address & 255, address >> 8 & 255
        cpu.reg[22] = command
        cpu.reg[20], cpu.reg[21] = data & 255, data >> 8
        if cpu.flash_size > 65536:
            cpu.io[0x5b] = address >> 16
        cpu.stack.append(0x0400)
        cpu.pc = cpu.boot_start + 2
        for _ in range(5000):
            if cpu.pc == 0x0400:
                break
            cpu.step()
        else:
            self.fail('Application SPM service did not return')
        self.assertEqual(cpu.reg[1], 0)
        self.assertEqual({r: cpu.reg[r] for r in saved}, saved)

    def test_all_current_hardware_profiles_write_app_and_reject_boot(self):
        checked = 0
        for chip, dev in build_mini.DEVICES.items():
            if dev['virtual_boot']:
                continue
            for edition in build_dual.available_editions(chip):
                with self.subTest(chip=chip, edition=edition):
                    cpu, boot, _ = create(chip, self.folder/edition/chip)
                    address = 0x0200
                    page = dev['page']
                    cpu.flash[address:address+page] = bytes(page)
                    self.invoke(cpu, address, 3)
                    self.assertEqual(cpu.flash[address:address+page], bytes([255]*page))
                    expected = bytes((i*29+13) & 255 for i in range(page))
                    for offset in range(0, page, 2):
                        self.invoke(cpu, address+offset, 1,
                                    expected[offset] | expected[offset+1] << 8)
                    self.invoke(cpu, address, 5)
                    self.assertEqual(cpu.flash[address:address+page], expected)
                    before = bytes(cpu.flash)
                    for command in (1, 3, 5):
                        self.invoke(cpu, cpu.boot_start, command, 0)
                        self.assertEqual(bytes(cpu.flash), before)
                    self.assertEqual(cpu.flash[cpu.boot_start:], boot)
                    checked += 1
        self.assertEqual(checked, 55)

    def test_virtual_profiles_have_no_hardware_boot_spm_entry(self):
        for chip, dev in build_mini.DEVICES.items():
            if not dev['virtual_boot']:
                continue
            for edition in build_dual.available_editions(chip):
                folder = self.folder/edition/chip
                meta = json.loads((folder/(chip+'.json')).read_text())
                self.assertFalse(meta['app_spm'])
                self.assertIsNone(meta['app_spm_entry_byte_address'])
                self.assertEqual((folder/(chip+'.bin')).read_bytes()[:2], b'\xf8\x94')

    def test_reset_cause_and_application_handoff_for_all_63_profiles(self):
        for chip, dev in build_mini.DEVICES.items():
            for edition in build_dual.available_editions(chip):
                for cause in range(16):
                    with self.subTest(chip=chip, edition=edition, cause=cause):
                        cpu, _, _ = create(chip, self.folder/edition/chip, cause, ready=False)
                        vector = {'attiny85': 6, 'attiny84': 14,
                                  'attiny841': 14, 'attiny1634': 26}.get(chip)
                        result = None
                        for _ in range(400):
                            if cpu.pc == cpu.rxwait_pc:
                                result = 'boot'
                                break
                            if cpu.pc == 0 or vector is not None and cpu.pc == vector*2:
                                result = 'app'
                                break
                            cpu.step()
                        expected = 'boot' if cause == 0 or cause & 0x0a == 2 else 'app'
                        self.assertEqual(result, expected)
                        if result == 'app':
                            self.assertEqual(cpu.reg[2], cause)
                            self.assertEqual(cpu.reg[1], 0)
                        status = 0x55 if chip == 'attiny1634' else 0x54
                        wanted = cause & (0xf7 if cause & 2 else 0xff)
                        self.assertEqual(cpu.io[status], wanted)
