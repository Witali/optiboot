"""Self-contained tests for the unified CLI, without requiring physical AVR hardware."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import generate_firmware as gen


class GeneratorSelectionTests(unittest.TestCase):
    def test_clock_parser(self):
        for text in ('16', '16MHz', '16M', '16000000Hz', '16_000_000'):
            self.assertEqual(gen.parse_frequency(text), 16_000_000)
        self.assertEqual(gen.parse_frequency('8.0 MHz'), 8_000_000)
        self.assertEqual(gen.parse_frequency('12.5MHz'), 12_500_000)
        for text in ('7MHz', '42MHz', '16GHz', '0', 'oops', '-16MHz'):
            with self.assertRaises(ValueError, msg=text):
                gen.parse_frequency(text)

    def test_edition_policy(self):
        self.assertEqual(len(gen.build_mini.DEVICES), 38)
        self.assertEqual(sum('compact' in gen.valid_types(m) for m in gen.build_mini.DEVICES), 25)
        self.assertEqual(sum('full' in gen.valid_types(m) for m in gen.build_mini.DEVICES), 38)
        self.assertEqual(sum('flash256' in gen.valid_types(m) for m in gen.build_mini.DEVICES), 13)
        self.assertEqual(sum('flashread512' in gen.valid_types(m) for m in gen.build_mini.DEVICES), 13)
        for m, meta in gen.build_mini.DEVICES.items():
            if not meta['virtual_boot'] and meta['hardware_min_boot_bytes'] >= 1024:
                self.assertEqual(gen.valid_types(m), ('full',))

    def test_disallowed_profiles_fail_before_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            for chip, edition in [('atmega2560','compact'), ('atmega328p','flash256'),
                                  ('attiny85','flashread512'), ('foobar','full')]:
                with self.assertRaises(ValueError):
                    gen.build_one(chip, edition, 16_000_000, out=Path(tmp), dry_run=True)
            with self.assertRaises(ValueError):
                gen.build_one('atmega8', 'full', 20_000_000, out=Path(tmp), dry_run=True)
            with self.assertRaises(ValueError):
                gen.build_one('atmega328p', 'compact', 16_000_000,
                              clock_source='internal_rc', out=Path(tmp), dry_run=True)
            with self.assertRaises(ValueError):
                gen.build_one('atmega8','flash256',16_000_000,
                              signature_source='hardware',out=Path(tmp),dry_run=True)
            with self.assertRaises(ValueError):
                gen.build_one('atmega8','full',16_000_000,
                              legacy_eeprom_byte_address=True,out=Path(tmp),dry_run=True)
            with self.assertRaises(ValueError):
                gen.build_one('atmega64a','full',16_000_000,
                              legacy_eeprom_byte_address=True,out=Path(tmp),dry_run=True)

    def test_all_policy_combinations_can_be_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for chip in gen.build_mini.DEVICES:
                for edition in gen.valid_types(chip):
                    d = gen.build_one(chip, edition, 8_000_000, out=Path(tmp), dry_run=True)
                    self.assertIn('command', d)
                    self.assertIn('result_dir', d)

    def test_malformed_hex_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            hex_file = Path(tmp)/'bad.hex'
            hex_file.write_text(':0100000001FF\n:00000001FF\n')
            with self.assertRaises(ValueError):
                gen.parse_ihex(hex_file)


class GeneratorBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='optiboot_generator_test_')
        cls.output_dir = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_compact_and_full_atmega328p(self):
        for edition, payload, boot in [('compact', 510, 512), ('full', 635, 1024)]:
            info = gen.build_one('atmega328p', edition, 16_000_000, out=self.output_dir)
            self.assertEqual(info['payload_bytes'], payload)
            self.assertEqual(info['boot_bytes'], boot)
            self.assertEqual(info['boot_start'], '0x7E00' if edition == 'compact' else '0x7C00')
            m = json.loads(Path(info['files']['build_info']).read_text())
            self.assertTrue(m['features']['eeprom_read'])
            self.assertTrue(m['features']['eeprom_write'])
            self.assertEqual(m['sha256'], hashlib.sha256(Path(m['files']['bin']).read_bytes()).hexdigest())
            baseline = ROOT/'output'/'dual'/edition/'atmega328p'/'atmega328p.bin'
            self.assertEqual(Path(info['files']['bin']).read_bytes(), baseline.read_bytes())

    def test_flash256_8mhz(self):
        r = gen.build_one('atmega8', 'flash256', 8_000_000, out=self.output_dir)
        self.assertEqual((r['boot_bytes'],r['payload_bytes'],r['baud']), (256,254,38400))
        self.assertFalse(r['features']['flash_read'])

    def test_flashread512_16mhz(self):
        r = gen.build_one('atmega16', 'flashread512', 16_000_000, out=self.output_dir)
        self.assertEqual((r['boot_bytes'],r['payload_bytes']), (512,284))
        self.assertTrue(r['features']['flash_read'])
        self.assertFalse(r['features']['eeprom_read'])

    def test_soft_uart_virtual_boot(self):
        r = gen.build_one('attiny85', 'compact', 8_000_000, out=self.output_dir)
        self.assertEqual(r['clock_source'], 'internal_rc')
        self.assertEqual(r['baud'], 19200)
        self.assertIsNone(r['hardware_min_boot_bytes'])
        self.assertFalse(r['features']['app_spm_abi'])

    def test_banked_avr_full(self):
        r = gen.build_one('atmega2560', 'full', 16_000_000, out=self.output_dir)
        self.assertEqual((r['boot_bytes'],r['payload_bytes'],r['boot_start']), (1024,787,'0x3FC00'))

    def test_cli_entrypoint(self):
        run = subprocess.run([sys.executable,str(ROOT/'generate_firmware.py'),
                              '--mcu','atmega8','--type','flash256','--freq','8MHz',
                              '--output',str(self.output_dir)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('OK atmega8 / flash256',run.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
