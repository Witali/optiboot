"""Full-page preparation is part of the verified Mini upload contract."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_flashread import TARGETS
from build_mini import DEVICES
from flashread.hex import parse_intel_hex
from flashread.prepare_avrdude_hex import prepare, rec


class FlashReadPages(unittest.TestCase):
    def test_sparse_pages_preserve_data_and_pad_the_final_page(self):
        for chip in TARGETS:
            with self.subTest(chip=chip):
                size = DEVICES[chip]['page']
                original = rec(3, b'\x12\x34')+'\n'+rec(size*3+7, b'\x56')+'\n:00000001FF\n'
                output, count, highest = prepare(original, chip)
                data = parse_intel_hex(output)
                self.assertEqual((count, highest), (2, size*4-1))
                self.assertEqual(len(data), size*2)
                self.assertEqual((data[3], data[4], data[size*3+7]), (0x12, 0x34, 0x56))
                self.assertEqual(data[highest], 255)
                self.assertNotIn(size, data)

    def test_boot_region_and_unsupported_mcu_are_rejected(self):
        for chip in TARGETS:
            source = rec(DEVICES[chip]['flash']-256, b'\x01')+'\n:00000001FF\n'
            with self.assertRaises(ValueError):
                prepare(source, chip)
        with self.assertRaises(ValueError):
            prepare(':00000001FF\n', 'atmega328p')

    def test_empty_malformed_and_conflicting_hex_are_rejected(self):
        first = rec(0, b'\x01')+'\n'
        for source in (':00000001FF\n', ':0100000001FF\n:00000001FF\n', first,
                       first+rec(0, b'\x02')+'\n:00000001FF\n',
                       first+':00000001FF\n'+first):
            with self.assertRaises(ValueError):
                prepare(source, 'atmega8')

    def test_cli_keeps_verification_enabled(self):
        with tempfile.TemporaryDirectory() as name:
            source, dest = Path(name)/'app.hex', Path(name)/'padded.hex'
            original = rec(0, b'\x01\x02\x03')+'\n:00000001FF\n'
            source.write_text(original)
            result = subprocess.run([sys.executable, str(ROOT/'flashread/prepare_avrdude_hex.py'),
                '--mcu', 'atmega8', '--input', str(source), '--output', str(dest)],
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('verification enabled', result.stdout)
            self.assertNotIn('-D -V', result.stdout)
            self.assertEqual(len(parse_intel_hex(dest.read_text())), 64)
            self.assertEqual(source.read_text(), original)

    def test_cli_refuses_to_overwrite_its_input(self):
        with tempfile.TemporaryDirectory() as name:
            source = Path(name)/'app.hex'
            original = rec(0, b'\x01')+'\n:00000001FF\n'
            source.write_text(original)
            result = subprocess.run([sys.executable, str(ROOT/'flashread/prepare_avrdude_hex.py'),
                '--mcu', 'atmega8', '--input', str(source), '--output', str(source)],
                text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(source.read_text(), original)


if __name__ == '__main__':
    unittest.main()
