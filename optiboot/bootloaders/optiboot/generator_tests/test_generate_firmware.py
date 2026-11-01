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
        self.assertEqual(len(gen.build_mini.DEVICES), 39)
        self.assertEqual(sum('compact' in gen.valid_types(m) for m in gen.build_mini.DEVICES), 26)
        self.assertEqual(sum('full' in gen.valid_types(m) for m in gen.build_mini.DEVICES), 39)
        self.assertEqual(sum('flashread256' in gen.valid_types(m) for m in gen.build_mini.DEVICES), 14)
        self.assertTrue(all('flash256' not in gen.valid_types(m) for m in gen.build_mini.DEVICES))
        for m, meta in gen.build_mini.DEVICES.items():
            if not meta['virtual_boot'] and meta['hardware_min_boot_bytes'] >= 1024:
                self.assertEqual(gen.valid_types(m), ('full',))

    def test_disallowed_profiles_fail_before_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            for chip, edition in [('atmega2560','compact'), ('atmega328p','flash256'),
                                  ('attiny85','flashread256'), ('foobar','full'),
                                  ('atmega16','flash256'), ('atmega16','flashread512')]:
                with self.assertRaises(ValueError):
                    gen.build_one(chip, edition, 16_000_000, out=Path(tmp), dry_run=True)
            with self.assertRaises(ValueError):
                gen.build_one('atmega8', 'full', 20_000_000, out=Path(tmp), dry_run=True)
            with self.assertRaises(ValueError):
                gen.build_one('atmega328p', 'compact', 16_000_000,
                              clock_source='internal_rc', out=Path(tmp), dry_run=True)
            with self.assertRaises(ValueError):
                gen.build_one('atmega8','flashread256',16_000_000,
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
            reference = {'compact': '156d3701c01e5a9f5008b371c08e4753b7d7200e1535b1c776755040723a99c1',
                         'full': '6a16bbe0776d704e4c9ab7651961bd35b02efe68809a7492090232014d5d82ef'}
            self.assertEqual(m['sha256'], reference[edition])

    def test_flashread256_8mhz(self):
        r = gen.build_one('atmega8', 'flashread256', 8_000_000, out=self.output_dir)
        self.assertEqual((r['boot_bytes'],r['baud']), (256,38400))
        self.assertLessEqual(r['payload_bytes'],256)
        self.assertTrue(r['features']['flash_read'])

    def test_atmega168pb_signature_and_layout_in_every_edition(self):
        from mini_tests.device_models import create
        from mini_tests.flashread_models import make_cpu
        for edition, boot, start in (('flashread256',256,'0x3F00'),
                                      ('compact',512,'0x3E00'), ('full',1024,'0x3C00')):
            with self.subTest(edition=edition):
                info = gen.build_one('atmega168pb', edition, 16_000_000, out=self.output_dir)
                self.assertEqual((info['boot_bytes'],info['boot_start']), (boot,start))
                self.assertEqual((info['flash_bytes'],info['flash_page_bytes'],info['eeprom_bytes']),
                                 (16384,128,512))
                folder = Path(info['files']['bin']).parent
                cpu, _, _ = (make_cpu('atmega168pb',folder) if edition == 'flashread256'
                              else create('atmega168pb',folder))
                self.assertEqual(cpu.send(b'u '), bytes.fromhex('14 1e 94 15 10'))
                if edition != 'flashread256':
                    self.assertEqual(info['signature_source'], 'hardware')
                    self.assertEqual(cpu.send(bytes.fromhex('56 30 00 02 00 20')),
                                     bytes.fromhex('14 15 10'))

    def test_flashread256_16mhz(self):
        r = gen.build_one('atmega16', 'flashread256', 16_000_000, out=self.output_dir)
        self.assertEqual((r['boot_bytes'],r['payload_bytes']), (256,249))
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
                              '--mcu','atmega8','--type','flashread256','--freq','8MHz',
                              '--output',str(self.output_dir)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('OK atmega8 / flashread256',run.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
