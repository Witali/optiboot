"""Database validation, generated-file consistency and builder preflight checks."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import device_database as database
import gen_devices
import build_mini
import build_flashread


class DeviceDatabaseTests(unittest.TestCase):
    def test_existing_host_view_is_preserved(self):
        original = json.loads(database.DATABASE_PATH.read_text())
        self.assertIs(build_mini.DEVICES, database.DEVICES)
        self.assertEqual(database.DEVICES, original)
        self.assertEqual(list(database.DEVICES), list(original))
        # This literal map also guards the old standalone Virtual Boot tools.
        from tiny.patch_vectors import TARGETS
        self.assertEqual(TARGETS, {
            'attiny841': {'flash': 8192, 'boot': 1024, 'vector': 14},
            'attiny1634': {'flash': 16384, 'boot': 1024, 'vector': 26},
            'attiny85': {'flash': 8192, 'boot': 1024, 'vector': 6},
            'attiny84': {'flash': 8192, 'boot': 1024, 'vector': 14},
        })

    def test_generation_matches_all_existing_includes_and_never_rewrites_database(self):
        before = database.DATABASE_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            output, table = Path(tmp)/'devices', Path(tmp)/'DEVICES.md'
            self.assertEqual(gen_devices.generate(output, table), len(database.DEVICES))
            actual = {path.name for path in output.glob('*.inc')}
            self.assertEqual(actual, {path.name for path in (ROOT/'devices').glob('*.inc')})
            for name in actual:
                self.assertEqual((output/name).read_text(), (ROOT/'devices'/name).read_text(), name)
            self.assertEqual(table.read_text(), gen_devices.TABLE_PATH.read_text())
            stamps = {path: path.stat().st_mtime_ns for path in [*output.glob('*.inc'), table]}
            gen_devices.generate(output, table, check=True)
            self.assertEqual(stamps, {path: path.stat().st_mtime_ns for path in stamps})
        self.assertEqual(database.DATABASE_PATH.read_bytes(), before)

    def test_stale_or_missing_generated_files_are_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, table = Path(tmp)/'devices', Path(tmp)/'DEVICES.md'
            gen_devices.generate(output, table)
            header = output/'atmega168pb.inc'
            header.write_text(header.read_text().replace('#define SIG2 0x15', '#define SIG2 0x16'))
            before = header.read_bytes()
            with self.assertRaisesRegex(ValueError, 'atmega168pb.inc'):
                database.check_generated_device('atmega168pb', directory=output)
            with self.assertRaisesRegex(ValueError, 'atmega168pb.inc'):
                gen_devices.generate(output, table, check=True)
            self.assertEqual(header.read_bytes(), before)
            gen_devices.generate(output, table)
            (output/'select.inc').unlink()
            with self.assertRaisesRegex(ValueError, 'select.inc'):
                database.check_generated_device('atmega168pb', directory=output)
            gen_devices.generate(output, table)
            unexpected = output/'obsolete.inc'
            unexpected.write_text('/* Preserve unexpected files for manual review. */\n')
            with self.assertRaisesRegex(ValueError, 'obsolete.inc'):
                gen_devices.generate(output, table, check=True)
            self.assertTrue(unexpected.exists())

    def test_inconsistent_database_records_are_rejected(self):
        mutations = [('sig', [30, 148]), ('sig', [30, 148, 256]), ('sig', [30, 148, True]),
                     ('flash', 12000), ('flash', True), ('page', 96),
                     ('flash_erase_group_bytes', 64), ('flash_erase_group_bytes', 1024),
                     ('eeprom', -1), ('ramend', 0), ('max_mhz', 0),
                     ('profile', 'unknown'), ('profile', []),
                     ('virtual_boot', True), ('wide_branches', 0), ('wdt_ccp_style', 3),
                     ('default_boot', 384), ('hardware_min_boot_bytes', 512),
                     ('spm512_capable', False)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'devices.json'
            for field, value in mutations:
                with self.subTest(field=field, value=value):
                    devices = copy.deepcopy(database.DEVICES)
                    devices['atmega168pb'][field] = value
                    path.write_text(json.dumps(devices))
                    with self.assertRaisesRegex(ValueError, 'atmega168pb'):
                        database.load_devices(path)
            for field in ('dual_compact_enabled', 'spm512_capable'):
                devices = copy.deepcopy(database.DEVICES)
                devices['atmega2560'][field] = True
                path.write_text(json.dumps(devices))
                with self.assertRaisesRegex(ValueError, '512-byte'):
                    database.load_devices(path)

    def test_duplicate_keys_missing_fields_and_invalid_virtual_boot_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'devices.json'
            for raw in ('{}', '[]', '{"atmega168pb": {}, "atmega168pb": {}}',
                        '{"atmega168pb": {"flash": 16384, "flash": 8192}}'):
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    database.load_devices(path)
            for field, value in (('hardware_min_boot_bytes', 256), ('default_boot', 512),
                                  ('spm512_capable', True), ('extra_field', True)):
                devices = copy.deepcopy(database.DEVICES)
                devices['attiny841'][field] = value
                path.write_text(json.dumps(devices))
                with self.assertRaisesRegex(ValueError, 'attiny841'):
                    database.load_devices(path)

    def test_an_edited_record_drives_the_generated_signature_and_stale_check(self):
        devices = copy.deepcopy(database.DEVICES)
        devices['atmega168pb']['sig'][2] = 0x16
        devices['atmega168pb']['default_boot'] = 1024
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'devices.json'
            path.write_text(json.dumps(devices))
            changed = database.load_devices(path)
            header = database.render_device('atmega168pb', changed['atmega168pb'])
            self.assertIn('#define SIG2 0x16', header)
            self.assertIn('#define BOOT_BYTES 1024', header)
            with self.assertRaisesRegex(ValueError, 'atmega168pb.inc'):
                database.check_generated_device('atmega168pb', devices=changed)
        self.assertEqual(database.DEVICES['atmega168pb']['sig'], [0x1e, 0x94, 0x15])

    def test_both_builders_reject_stale_inputs_before_selecting_a_compiler(self):
        with mock.patch.object(database, 'check_generated_device', side_effect=ValueError('stale')) as check:
            with mock.patch.object(build_mini, 'compiler_tools') as compiler:
                with self.assertRaisesRegex(ValueError, 'stale'):
                    build_mini.build(SimpleNamespace(mcu='atmega168pb'))
                with self.assertRaisesRegex(ValueError, 'stale'):
                    build_flashread.one('atmega168pb', Path('unused'))
                self.assertEqual(check.call_count, 2)
                compiler.assert_not_called()

    def test_generated_files_pass_the_read_only_cli_check(self):
        run = subprocess.run([sys.executable, str(ROOT/'gen_devices.py'), '--check'],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('Checked 39 AVR device profiles', run.stdout)


if __name__ == '__main__':
    unittest.main()
