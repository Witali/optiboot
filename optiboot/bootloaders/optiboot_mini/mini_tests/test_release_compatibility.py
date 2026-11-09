"""Verify every shipped image and rebuilt image against the downloaded release."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from generate_firmware import parse_ihex
from build_mini import DEVICES
from flash256.prepare_avrdude_hex import prepare,rec


class ReleaseCompatibilityTests(unittest.TestCase):
    def test_readback_hex_preparation_respects_512_byte_boot_boundary(self):
        for chip in ('atmega8','atmega16'):
            dev=DEVICES[chip]
            boot=dev['flash']-512
            with self.subTest(mcu=chip):
                valid=rec(boot-1,b'\x42')+'\n:00000001FF\n'
                prepared,_,end=prepare(valid,chip,512)
                self.assertEqual(end,boot-1)
                invalid=rec(boot,b'\x42')+'\n:00000001FF\n'
                with self.assertRaisesRegex(ValueError,'Boot reservation'):
                    prepare(invalid,chip,512)
                # The exact same page is still application space for Flash256.
                self.assertEqual(prepare(invalid,chip,256)[2],boot+dev['page']-1)

    def test_all_63_rebuilt_images_match_the_downloaded_release(self):
        profiles = json.loads((ROOT/'firmware/manifest.json').read_text())['profiles']
        matrix = json.loads((ROOT/'output/dual/matrix_dual.json').read_text())
        self.assertEqual(set(matrix['firmware']), set(profiles))
        self.assertEqual(len(profiles), 63)
        for key, reference in profiles.items():
            edition, chip = key.split('/')
            with self.subTest(profile=key):
                shipped = ROOT/'firmware'/edition/chip
                rebuilt = ROOT/'output/dual'/edition/chip
                blob = (shipped/(chip+'.bin')).read_bytes()
                self.assertEqual(hashlib.sha256(blob).hexdigest(),reference['sha256'])
                self.assertEqual(hashlib.sha256((shipped/(chip+'.hex')).read_bytes()).hexdigest(),
                                 reference['hex_sha256'])
                self.assertEqual((rebuilt/(chip+'.bin')).read_bytes(),blob)
                start = int(reference['boot_start_hex'],16)
                expected = {start+i: value for i,value in enumerate(blob)}
                self.assertEqual(parse_ihex(shipped/(chip+'.hex')),expected)
                self.assertEqual(parse_ihex(rebuilt/(chip+'.hex')),expected)
                meta = json.loads((rebuilt/(chip+'.json')).read_text())
                for field in ('f_cpu_hz','clock_source','baud_requested','boot_bytes','boot_start_hex'):
                    self.assertEqual(meta[field],reference[field])

    def test_gnu_and_llvm_assemble_the_same_virtual_boot_images(self):
        # GNU as and LLVM differ in relocation emission and numeric suffixes.
        for chip in ('attiny84','attiny85','attiny841','attiny1634'):
            with self.subTest(mcu=chip), tempfile.TemporaryDirectory() as tmp:
                ref = json.loads((ROOT/'firmware/manifest.json').read_text())['profiles'][f'compact/{chip}']
                proc = subprocess.run([sys.executable,str(ROOT/'build_mini.py'),
                    '--mcu',chip,'--compact-tiny','--mcusr-parity','--toolchain','gcc',
                    '--f-cpu',str(ref['f_cpu_hz']),'--clock-source',ref['clock_source'],
                    '--output-dir',tmp],capture_output=True,text=True)
                self.assertEqual(proc.returncode,0,proc.stderr)
                blob=(Path(tmp)/(chip+'.bin')).read_bytes()
                self.assertEqual(hashlib.sha256(blob).hexdigest(),ref['sha256'])


if __name__ == '__main__':
    unittest.main()
