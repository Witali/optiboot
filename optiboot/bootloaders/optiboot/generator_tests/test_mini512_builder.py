"""The ATmega328PB Mini512 experiment is explicit and cannot expand Mini256."""
import hashlib
import inspect
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_flashread
import device_database
from flashread.hex import parse_intel_hex


class Mini512BuilderTests(unittest.TestCase):
    def test_opt_in_is_keyword_only_and_not_a_canonical_target(self):
        parameter = inspect.signature(build_flashread.one).parameters['experimental_512']
        self.assertIs(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameter.default, False)
        self.assertEqual(len(build_flashread.TARGETS), 14)
        self.assertNotIn('atmega328pb', build_flashread.TARGETS)
        self.assertFalse(device_database.supports_mini(device_database.DEVICES['atmega328pb']))

    def test_unsupported_targets_fail_before_creating_output(self):
        with tempfile.TemporaryDirectory(prefix='mini512-guards-') as name:
            output = Path(name) / 'output'
            with self.assertRaisesRegex(ValueError, '256-byte'):
                build_flashread.one('atmega328pb', output)
            for mcu in (*build_flashread.TARGETS, 'atmega328p', 'unknown'):
                with self.subTest(mcu=mcu), self.assertRaisesRegex(ValueError, 'restricted to atmega328pb'):
                    build_flashread.one(mcu, output, experimental_512=True)
            self.assertFalse(output.exists())

    def test_cli_rejects_ambiguous_experimental_selection(self):
        for selection in ([], ['--all'], ['--list'], ['--mcu', 'atmega168pb'],
                          ['--mcu', 'atmega328pb', '--all']):
            with self.subTest(selection=selection):
                result = subprocess.run([sys.executable, str(ROOT / 'build_flashread.py'),
                                         '--experimental-328pb-512', *selection],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('requires --mcu atmega328pb', result.stderr)

    def test_both_requested_clock_baud_images_have_physical_512_layout(self):
        with tempfile.TemporaryDirectory(prefix='mini512-build-') as name:
            for hz, baud in ((16000000, 115200), (8000000, 38400)):
                with self.subTest(hz=hz, baud=baud):
                    output = Path(name) / str(hz)
                    meta = build_flashread.one('atmega328pb', output, hz, baud, experimental_512=True)
                    binary = (output / 'atmega328pb.bin').read_bytes()
                    addresses = parse_intel_hex((output / 'atmega328pb.hex').read_text())
                    self.assertEqual((len(binary), min(addresses), max(addresses)), (512, 0x7E00, 0x7FFF))
                    self.assertEqual(bytes(addresses[address] for address in range(0x7E00, 0x8000)), binary)
                    self.assertEqual(binary[-3:], bytes.fromhex('1E9516'))
                    self.assertEqual(binary[meta['code_bytes']:-3], b'\xff' * meta['free_bytes'])
                    self.assertEqual(meta['code_sha256'], hashlib.sha256(binary).hexdigest())
                    self.assertEqual(meta['edition'], 'mini-experimental-512')
                    self.assertEqual((meta['boot_bytes'], meta['boot_start'], meta['application_bytes']),
                                     (512, '0x7E00', 32256))
                    self.assertEqual(meta['useful_bytes'], meta['code_bytes'] + 3)
                    self.assertEqual(meta['hardware_min_boot_bytes'], 512)
                    self.assertLessEqual(meta['useful_bytes'], 256)
                    for feature in ('flash_read', 'flash_write', 'eeprom_busy_interlock', 'experimental'):
                        self.assertTrue(meta[feature])
                    for feature in ('eeprom_read', 'eeprom_write', 'canonical_mini256_target',
                                    'on_silicon_tested', 'avrdude_host_tested'):
                        self.assertFalse(meta[feature])
                    self.assertEqual(json.loads((output / 'atmega328pb.json').read_text()), meta)

    def test_assembler_independently_rejects_wrong_mcu_boot_or_readback(self):
        _, compiler, _, flags = build_flashread.build_mini.compiler_tools('auto')
        with tempfile.TemporaryDirectory(prefix='mini512-asm-guards-') as name:
            for mcu, boot, readback, opt_in in (
                    ('atmega328p', 512, 1, 1), ('atmega168pb', 512, 1, 1),
                    ('atmega328pb', 256, 1, 1), ('atmega328pb', 1024, 1, 1),
                    ('atmega328pb', 512, 0, 1), ('atmega328pb', 512, 1, 0)):
                with self.subTest(mcu=mcu, boot=boot, readback=readback, opt_in=opt_in):
                    result = subprocess.run([
                        compiler, *flags, '-mmcu=' + mcu, '-I', str(ROOT),
                        '-DMINI_FLASH_ONLY_256=1', f'-DMINI_FLASH256_READBACK={readback}',
                        f'-DMINI_FLASHREAD_EXPERIMENTAL_328PB_512={opt_in}', f'-DBOOT_BYTES={boot}',
                        '-DF_CPU=16000000', '-DBAUD_RATE=115200', '-DMINI_U2X=1', '-DMINI_UBRR=16',
                        '-c', str(ROOT / 'optiboot_mini.S'), '-o', str(Path(name) / 'rejected.o')],
                        capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('error:', result.stderr.lower())

    def test_experimental_useful_budget_cannot_grow_into_reservation_padding(self):
        native_check_output = subprocess.check_output

        def code_grew_to_254(arguments, **kwargs):
            output = native_check_output(arguments, **kwargs)
            if arguments[:2] == ['llvm-objdump', '-t']:
                output = re.sub(r'^[0-9a-fA-F]+(\s+\S+\s+\.text\s+\S+\s+_code_end)$',
                                r'000000fe\1', output, flags=re.M)
            return output

        with tempfile.TemporaryDirectory(prefix='mini512-budget-') as name:
            with mock.patch.object(subprocess, 'check_output', side_effect=code_grew_to_254):
                with self.assertRaisesRegex(RuntimeError, '256-byte useful budget'):
                    build_flashread.one('atmega328pb', Path(name), experimental_512=True)


if __name__ == '__main__':
    unittest.main()
